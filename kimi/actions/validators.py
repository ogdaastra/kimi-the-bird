"""Validation of model-proposed actions.

Claude Haiku only *suggests*. Every suggestion is parsed into a schema,
checked against :data:`kimi.safety.ALLOWED_ACTIONS`, its parameters are
validated and cleaned, and its preconditions are checked. Anything that
fails is rejected and logged; nothing unvalidated is ever executed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ..ai.prompts import ART_KINDS, DRAWING_ELEMENTS
from ..character import MOODS
from ..safety import SafetyViolation, check_action_name, clean_text, sanitize_output
from ..world.locations import ART_LOCATION, HOME, NOTE_LOCATION, RESEARCH_LOCATION, LocationGraph

TEXT_ART_KINDS = ("story", "poem", "project")


class ActionRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RawDecision(BaseModel):
    """Structural schema for a decision. Unknown fields are ignored, never executed."""

    model_config = ConfigDict(extra="ignore")

    action: str
    thought: str | None = None
    destination: str | None = None
    topic: str | None = None
    food: str | None = None
    art_kind: str | None = None
    title: str | None = None
    content: str | None = None
    drawing_elements: list[str] = []
    duration_minutes: int | None = None
    note_id: int | None = None
    creation_id: int | None = None
    visitor_impression: str | None = None
    mood: str | None = None
    interest: str | None = None
    new_goal: str | None = None
    opinion_subject: str | None = None
    opinion: str | None = None

    @field_validator("drawing_elements", mode="before")
    @classmethod
    def _list(cls, v: Any) -> list:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("drawing_elements must be a list")
        return v[:20]


@dataclass
class ValidationContext:
    graph: LocationGraph
    current_location: str
    is_night: bool = False
    unread_notes: dict[int, str] = field(default_factory=dict)   # note id -> location
    creation_ids: set[int] = field(default_factory=set)
    research_allowed: bool = True
    research_block_reason: str = ""
    sharing_enabled: bool = False


@dataclass
class ValidatedAction:
    action: str
    params: dict
    required_location: str | None
    extras: dict = field(default_factory=dict)

    def describe(self) -> str:
        bits = [self.action]
        for key in ("destination", "food", "topic", "art_kind", "title", "note_id"):
            if self.params.get(key) not in (None, ""):
                bits.append(f"{key}={self.params[key]}")
        return " ".join(str(b) for b in bits)


_TOPIC_ALLOWED = re.compile(r"[^\w \-'’,.()&]", re.UNICODE)


def _clamp_int(value: int | None, lo: int, hi: int, default: int) -> int:
    if value is None:
        return default
    return max(lo, min(hi, int(value)))


def _clean_topic(topic: str | None) -> str:
    t = clean_text(topic or "", 120)
    t = _TOPIC_ALLOWED.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" .,-")
    return t[:80]


def _match_food(requested: str | None, menu: tuple[str, ...]) -> str | None:
    if not menu:
        return None
    if requested:
        r = requested.strip().lower()
        for item in menu:
            if r == item.lower() or r in item.lower() or item.lower() in r:
                return item
    return None


def _extras(d: RawDecision) -> dict:
    return {
        "thought": sanitize_output(d.thought, 400) if d.thought else "",
        "mood": d.mood if d.mood in MOODS else None,
        "interest": clean_text(d.interest, 60) if d.interest else None,
        "new_goal": clean_text(d.new_goal, 120) if d.new_goal else None,
        "opinion_subject": clean_text(d.opinion_subject, 60) if d.opinion_subject else None,
        "opinion": clean_text(d.opinion, 200) if d.opinion else None,
    }


def validate_decision(raw: dict, ctx: ValidationContext) -> ValidatedAction:
    if not isinstance(raw, dict):
        raise ActionRejected("Decision was not a JSON object")
    try:
        check_action_name(raw.get("action"))
    except SafetyViolation as exc:
        raise ActionRejected(str(exc)) from None
    try:
        d = RawDecision.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ActionRejected(f"Invalid parameters: {first.get('loc')} {first.get('msg')}") from None

    g = ctx.graph
    here = ctx.current_location
    extras = _extras(d)
    a = d.action

    def need_destination() -> str:
        if not d.destination or d.destination not in g:
            raise ActionRejected(f"Unknown destination {d.destination!r}")
        return d.destination

    if a == "move_to":
        dest = need_destination()
        if dest == here:
            # Already here: treat as spending a little time here rather than wasting the decision.
            return ValidatedAction("visit_location", {"destination": dest, "duration_minutes": 20}, dest, extras)
        return ValidatedAction(a, {"destination": dest}, None, extras)

    if a == "visit_location":
        dest = need_destination()
        return ValidatedAction(a, {"destination": dest, "duration_minutes": _clamp_int(d.duration_minutes, 10, 120, 30)},
                               dest, extras)

    if a == "eat":
        candidates = []
        if d.destination in g and g.get(d.destination).food:
            candidates.append(d.destination)
        if g.get(here).food:
            candidates.append(here)
        if not candidates:
            nearest = g.nearest_with(here, lambda loc: bool(loc.food) and loc.id != HOME)
            if nearest:
                candidates.append(nearest)
        if ctx.is_night:
            # Marigold's cafe is closed at night; Kimi snacks at home instead.
            candidates = [c for c in candidates if c != "cafe"] or [HOME]
        place = candidates[0]
        menu = g.get(place).food
        food = _match_food(d.food, menu) or (menu[0] if menu else None)
        if food is None:
            raise ActionRejected("Nothing to eat there")
        return ValidatedAction(a, {"food": food, "destination": place}, place, extras)

    if a == "sleep":
        return ValidatedAction(a, {}, HOME, extras)

    if a == "rest":
        return ValidatedAction(a, {"duration_minutes": _clamp_int(d.duration_minutes, 10, 120, 30)}, None, extras)

    if a == "explore":
        def can_explore(lid: str) -> bool:
            return "explore" in g.get(lid).activities
        if d.destination in g and can_explore(d.destination):
            place = d.destination
        elif can_explore(here):
            place = here
        else:
            place = g.nearest_with(here, lambda loc: "explore" in loc.activities) or "shrub"
        return ValidatedAction(a, {"topic": _clean_topic(d.topic) or None,
                                   "duration_minutes": _clamp_int(d.duration_minutes, 15, 90, 40)}, place, extras)

    if a == "observe":
        return ValidatedAction(a, {"duration_minutes": _clamp_int(d.duration_minutes, 10, 60, 20)}, None, extras)

    if a == "read_note":
        if not ctx.unread_notes:
            raise ActionRejected("There are no unread notes")
        note_id = d.note_id
        if note_id not in ctx.unread_notes:
            if len(ctx.unread_notes) == 1:
                note_id = next(iter(ctx.unread_notes))
            else:
                raise ActionRejected(f"Note {d.note_id!r} is not an unread note")
        params = {
            "note_id": note_id,
            "reply": sanitize_output(d.content, 500) if d.content else None,
            "visitor_impression": clean_text(d.visitor_impression, 150) if d.visitor_impression else None,
        }
        return ValidatedAction(a, params, ctx.unread_notes[note_id], extras)

    if a == "research":
        if not ctx.research_allowed:
            raise ActionRejected(ctx.research_block_reason or "Research is not available right now")
        topic = _clean_topic(d.topic)
        if len(topic) < 2:
            raise ActionRejected("Research needs a topic")
        return ValidatedAction(a, {"topic": topic}, RESEARCH_LOCATION, extras)

    if a == "write_diary":
        content = sanitize_output(d.content, 2500) if d.content else ""
        if len(content) < 20:
            raise ActionRejected("A diary entry needs some writing")
        return ValidatedAction(a, {"title": sanitize_output(d.title, 80) if d.title else None, "content": content},
                               None, extras)

    if a == "create_art":
        kind = d.art_kind if d.art_kind in ART_KINDS else ("drawing" if d.drawing_elements else None)
        if kind is None:
            raise ActionRejected("create_art needs an art_kind")
        title = sanitize_output(d.title, 80) if d.title else ""
        content = sanitize_output(d.content, 4000) if d.content else ""
        elements = [e for e in d.drawing_elements if e in DRAWING_ELEMENTS]
        if kind in TEXT_ART_KINDS and len(content) < 20:
            raise ActionRejected(f"A {kind} needs its text in content")
        if kind not in TEXT_ART_KINDS and not elements:
            elements = ["kimi", "flower", "sun"]
        return ValidatedAction(a, {"art_kind": kind, "title": title or f"Untitled {kind}",
                                   "content": content, "elements": elements[:12]}, ART_LOCATION, extras)

    if a == "reflect":
        content = sanitize_output(d.content, 1200) if d.content else ""
        if len(content) < 5:
            raise ActionRejected("A reflection needs some thoughts")
        return ValidatedAction(a, {"content": content, "topic": _clean_topic(d.topic) or None}, None, extras)

    if a == "leave_message":
        content = sanitize_output(d.content, 500) if d.content else ""
        if len(content) < 2:
            raise ActionRejected("A message needs some text")
        return ValidatedAction(a, {"content": content}, NOTE_LOCATION, extras)

    if a == "share_creation":
        if not ctx.sharing_enabled:
            raise ActionRejected("Sharing creations is disabled in Settings")
        if d.creation_id not in ctx.creation_ids:
            raise ActionRejected(f"Unknown creation {d.creation_id!r}")
        return ValidatedAction(a, {"creation_id": d.creation_id}, ART_LOCATION, extras)

    if a == "continue":
        return ValidatedAction(a, {"duration_minutes": _clamp_int(d.duration_minutes, 10, 60, 20)}, None, extras)

    raise ActionRejected(f"Unhandled action {a!r}")  # pragma: no cover - allow-list keeps this unreachable
