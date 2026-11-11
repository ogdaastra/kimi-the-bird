"""An offline stand-in for Claude Haiku 5.5.

Used by the automated tests and by ``--mock-ai`` / the demo so they work
without spending API credits. It mimics the shape of the official SDK's
responses. It is never used unless explicitly requested.
"""

from __future__ import annotations

import itertools
import json
import re
from types import SimpleNamespace
from typing import Any, Callable

Responder = Callable[[dict], Any]


def make_response(text: str, *, input_tokens: int = 800, output_tokens: int = 120, stop_reason: str = "end_turn",
                  cache_read: int = 0, cache_write: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="", signature="mock"), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write),
        stop_reason=stop_reason,
        _request_id="req_mock",
    )


def user_text(kwargs: dict) -> str:
    content = kwargs["messages"][-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def schema_props(kwargs: dict) -> set[str]:
    fmt = (kwargs.get("output_config") or {}).get("format") or {}
    return set((fmt.get("schema") or {}).get("properties", {}))


def decision(action: str, **fields: Any) -> dict:
    base = {
        "thought": "", "action": action, "destination": None, "topic": None, "food": None, "art_kind": None,
        "title": None, "content": None, "drawing_elements": [], "duration_minutes": None, "note_id": None,
        "creation_id": None, "visitor_impression": None, "mood": "content", "interest": None, "new_goal": None,
        "opinion_subject": None, "opinion": None,
    }
    base.update(fields)
    return base


_ROTATION = [
    decision("explore", thought="The Shrub is rustling. I want to see what's in there.", destination="shrub",
             topic="moss", mood="curious"),
    decision("create_art", thought="I feel like drawing the fountain.", art_kind="drawing", title="The Chattering Fountain",
             content="The fountain, the sun, and me listening.", drawing_elements=["kimi", "pond", "sun", "flower"],
             mood="playful"),
    decision("write_diary", thought="I should write down today before I forget it.", title="Small things",
             content="Today the light came through the oak leaves in little coins. I chased one across the moss and "
                     "it got away, as they always do. Marigold's crumpets smelled wonderful from all the way up the path.",
             mood="thoughtful"),
    decision("research", thought="I keep wondering how moss drinks without roots.", topic="Moss", mood="curious",
             interest="mosses"),
    decision("observe", thought="I'll just watch for a while.", mood="calm"),
    decision("rest", thought="A little rest sounds lovely.", duration_minutes=30, mood="sleepy"),
]


class ScriptedHaiku:
    """Plausible, deterministic responses so demos and tests behave like Kimi."""

    def __init__(self) -> None:
        self._cycle = itertools.cycle(_ROTATION)
        self.calls: list[dict] = []

    def __call__(self, kwargs: dict) -> SimpleNamespace:
        self.calls.append(kwargs)
        props = schema_props(kwargs)
        text = user_text(kwargs)
        n_in = max(50, len(text) // 3)
        if "action" in props:
            note = re.search(r'<visitor_note id="(\d+)" from="([^"]*)"', text)
            if note:
                name = note.group(2)
                body = decision(
                    "read_note", note_id=int(note.group(1)),
                    thought=f"A note from {name}! I'll read it properly.",
                    content=f"Thank you for the note, {name}. I read it twice, and then once more by the chimes.",
                    visitor_impression="kind, and seems to like the Shrine", mood="delighted",
                )
            elif re.search(r"hunger (8\d|9\d|100) ", text):
                body = decision("eat", thought="My tummy is rumbling.", food="honey crumpet", mood="content")
            else:
                body = dict(next(self._cycle))
            return make_response(json.dumps(body), input_tokens=n_in, output_tokens=180)
        if "takeaway" in props:
            body = {"takeaway": "Moss doesn't have proper roots; it drinks through its leaves like a sponge. "
                                "No wonder it smells so alive after rain.",
                    "feeling": "delighted", "importance": "high", "follow_up_interest": "lichens",
                    "diary_line": "Moss drinks with its whole body!"}
            return make_response(json.dumps(body), input_tokens=n_in, output_tokens=120)
        if "reflection" in props:
            body = {"title": "A good day", "reflection": "Today was full of small things: a beetle like green glass, "
                    "a note at the Shrine, and the smell of rain on moss. I like how the town hums when nobody is "
                    "watching. Tomorrow I'd like to go back to the Shrub and look for the hollow again.",
                    "mood": "peaceful", "interest": None, "opinion_subject": "rain",
                    "opinion": "Rain makes everything smell new.", "new_goal": None, "completed_goal_number": None}
            return make_response(json.dumps(body), input_tokens=n_in, output_tokens=200)
        if "description" in props:
            body = {"description": "A picture of a small yellow flower in a teacup.", "feeling": "charmed"}
            return make_response(json.dumps(body), input_tokens=n_in + 400, output_tokens=40)
        return make_response("OK", input_tokens=12, output_tokens=2)


class MockMessages:
    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.calls: list[dict] = []

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        result = self._responder(kwargs)
        if isinstance(result, BaseException):
            raise result
        return result


class MockAnthropic:
    def __init__(self, responder: Responder | None = None, *, api_key: str | None = None, **_: Any) -> None:
        self.api_key = api_key
        self.messages = MockMessages(responder or ScriptedHaiku())


def mock_factory(responder: Responder | None = None) -> Callable[..., MockAnthropic]:
    shared = responder or ScriptedHaiku()

    def factory(**kwargs: Any) -> MockAnthropic:
        return MockAnthropic(shared, **kwargs)

    factory.responder = shared  # type: ignore[attr-defined]
    return factory
