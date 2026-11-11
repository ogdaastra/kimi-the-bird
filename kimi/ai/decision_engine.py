"""Asks Claude Haiku 5.5 what Kimi would like to do, and related small tasks.

The engine never executes anything: it returns parsed JSON that the action
validators check against Kimi's permitted actions.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import replace

from ..config import SettingsStore
from .claude_client import AIError, ClaudeClient
from .costs import estimate_tokens
from .prompts import (
    IMAGE_PROMPT,
    SYSTEM_PROMPT,
    DecisionContext,
    decision_schema,
    image_schema,
    reflection_schema,
    render_decision_context,
    render_reflection_prompt,
    render_research_prompt,
    research_schema,
)

log = logging.getLogger("kimi.decisions")


class DecisionEngine:
    def __init__(self, client: ClaudeClient, settings: SettingsStore) -> None:
        self.client = client
        self.settings = settings
        self._decision_schema = decision_schema()

    def _fit(self, ctx: DecisionContext) -> str:
        """Render the context, trimming the least important parts to stay under the size limit."""
        budget = self.settings.get().max_input_tokens - estimate_tokens(SYSTEM_PROMPT) - 200
        ctx = replace(ctx, memories=list(ctx.memories), recent_events=list(ctx.recent_events),
                      unread_notes=[dict(n) for n in ctx.unread_notes])
        text = render_decision_context(ctx)
        while estimate_tokens(text) > budget:
            if len(ctx.memories) > 3:
                ctx.memories.pop()
            elif len(ctx.recent_events) > 3:
                ctx.recent_events.pop(0)
            elif len(ctx.unread_notes) > 1:
                ctx.unread_notes.pop()
            elif ctx.unread_notes and len(ctx.unread_notes[0]["body"]) > 300:
                ctx.unread_notes[0]["body"] = ctx.unread_notes[0]["body"][:300] + "…"
            elif ctx.memories:
                ctx.memories.pop()
            else:
                break
            text = render_decision_context(ctx)
        return text

    def decide(self, ctx: DecisionContext) -> dict:
        s = self.settings.get()
        result = self.client.complete(
            purpose="decision",
            system=SYSTEM_PROMPT,
            user_content=self._fit(ctx),
            max_tokens=s.decision_max_tokens,
            effort=s.decision_effort,
            schema=self._decision_schema,
        )
        assert result.data is not None
        return result.data

    def interpret_research(self, topic: str, title: str, extract: str, url: str, self_summary: str) -> dict:
        s = self.settings.get()
        result = self.client.complete(
            purpose="research",
            system=SYSTEM_PROMPT,
            user_content=render_research_prompt(topic, title, extract, url, self_summary),
            max_tokens=s.research_max_tokens,
            effort="low",
            schema=research_schema(),
        )
        assert result.data is not None
        return result.data

    def reflect(self, day: int, highlights: list[str], self_summary: str, goals: list[str], stats: str) -> dict:
        s = self.settings.get()
        result = self.client.complete(
            purpose="reflection",
            system=SYSTEM_PROMPT,
            user_content=render_reflection_prompt(day, highlights, self_summary, goals, stats),
            max_tokens=s.reflection_max_tokens,
            effort=s.reflection_effort,
            schema=reflection_schema(),
        )
        assert result.data is not None
        return result.data

    def describe_image(self, image_bytes: bytes, media_type: str, location_name: str) -> dict:
        if media_type not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            raise AIError("bad_request", "Unsupported image type")
        s = self.settings.get()
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.standard_b64encode(image_bytes).decode("ascii")}},
            {"type": "text", "text": IMAGE_PROMPT.format(location=location_name)},
        ]
        result = self.client.complete(
            purpose="vision",
            system=SYSTEM_PROMPT,
            user_content=content,
            max_tokens=s.vision_max_tokens,
            effort="low",
            schema=image_schema(),
        )
        assert result.data is not None
        return result.data
