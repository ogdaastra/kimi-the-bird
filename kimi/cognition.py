"""Kimi's cognitive loop.

Each time Kimi has nothing to do it wakes up, looks at its world, and
decides what to do next:

1. Instincts (local, free): sleep at night, eat when very hungry, rest when
   exhausted.
2. Between AI decisions Kimi potters about or follows simple local habits.
3. When a decision is due, the current situation, needs, relevant memories,
   visitor notes and surroundings are sent to Claude Haiku 5.5, which
   suggests one action.
4. The suggestion is validated against the allow-list and turned into a plan.
5. If the AI is unavailable (no key, budget reached, offline), Kimi keeps
   living on local habits.

Decisions are paced by a minimum interval and an adaptive idle multiplier:
when nothing is happening and Kimi keeps choosing quiet activities, the gap
between AI calls grows; visitor notes or discoveries shrink it again.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from .actions.research import SHELVES, ResearchUnavailable
from .actions.validators import ActionRejected, ValidatedAction, ValidationContext, validate_decision
from .ai.claude_client import AIError
from .ai.prompts import WIDER_WORLD, DecisionContext
from .safety import sanitize_name, sanitize_untrusted
from .world.curio3d import curiosity_spots
from .world.curiosities import CURIOSITIES
from .world.locations import HOME
from .world.world import PlanStep

if TYPE_CHECKING:  # pragma: no cover
    from .runtime import KimiRuntime

log = logging.getLogger("kimi.cognition")

LINGER_MAX_WAIT_S = 240


@dataclass
class DecisionOutcome:
    raw: dict
    action: ValidatedAction | None
    rejected: str | None = None
    payload: dict = field(default_factory=dict)


def _sim_label(sim_minute: float) -> str:
    day = int(sim_minute // 1440) + 1
    hour = (sim_minute % 1440) / 60
    tod = "night" if hour < 5 or hour >= 21 else "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return f"Day {day} {tod}"


class CognitiveLoop:
    def __init__(self, rt: "KimiRuntime") -> None:
        self.rt = rt
        self.in_flight = None
        self._generation = 0
        self.next_decision_at = rt.mono()  # think as soon as Kimi wakes up
        self.last_decision_at = -1e9
        self.idle_multiplier = 1.0
        self.events_since_decision = 0
        self.decisions_made = 0
        self.recent_actions: deque[str] = deque(maxlen=6)
        for row in reversed(rt.db.query(
            "SELECT action FROM action_log WHERE source IN ('mind','instinct','fallback') "
            "AND status IN ('completed','started') ORDER BY id DESC LIMIT 6"
        )):
            self.recent_actions.append(row["action"])

    # -- control ---------------------------------------------------------------
    def autonomy_ok(self) -> bool:
        s = self.rt.settings.get()
        return s.autonomous_enabled and not s.emergency_stopped and not s.paused

    def cancel(self) -> None:
        """Forget any in-flight decision; its result will be ignored."""
        self._generation += 1
        self.in_flight = None

    def notify_event(self, important: bool = True) -> None:
        self.events_since_decision += 1
        if important:
            self.idle_multiplier = 1.0
            s = self.rt.settings.get()
            self.next_decision_at = min(self.next_decision_at, self.last_decision_at + s.decision_min_interval_s)

    def seconds_until_next(self) -> float:
        return max(0.0, self.next_decision_at - self.rt.mono())

    # -- main entry ------------------------------------------------------------
    def update(self) -> None:
        rt = self.rt
        rt.maybe_consolidate()
        if not self.autonomy_ok():
            return
        w = rt.world
        if w.travel or w.activity or w.plan or self.in_flight is not None:
            return
        steps = self.instinct()
        if steps:
            self._enqueue(steps)
            return
        now = rt.mono()
        if now < self.next_decision_at:
            wait = self.next_decision_at - now
            if wait <= LINGER_MAX_WAIT_S:
                self._linger(wait)
            else:
                self._fallback("waiting for the next thought")
            return
        ok, why = rt.client.availability()
        if ok:
            self._request_decision()
        else:
            self._fallback(why)

    def _enqueue(self, steps: list[PlanStep]) -> None:
        self.rt.world.enqueue(steps)
        self.recent_actions.append(steps[-1].action)
        self.rt.advance_plan()

    def _linger(self, wait_real_s: float) -> None:
        s = self.rt.settings.get()
        minutes = max(1.0, min(45.0, wait_real_s * s.time_scale / 60.0))
        step = PlanStep("linger", {"duration_minutes": minutes}, "fallback", label="pottering about")
        self.rt.world.enqueue([step])
        self.rt.advance_plan()

    # -- instincts (local, no API) --------------------------------------------
    def instinct(self) -> list[PlanStep] | None:
        rt = self.rt
        w = rt.world
        n, env = w.needs, w.env
        raw: dict | None = None
        reason = ""
        if env.is_night and not w.asleep:
            raw, reason = {"action": "sleep"}, "It's late; Kimi heads home to sleep."
        elif n.energy < 12:
            if env.hour >= 17:
                raw, reason = {"action": "sleep"}, "Kimi is exhausted and goes to bed early."
            else:
                raw, reason = {"action": "rest", "duration_minutes": 45}, "Kimi is worn out and needs a rest."
        elif n.hunger > 85:
            fav = (rt.character.favourites("food_preferences", 1) or [None])[0]
            raw, reason = {"action": "eat", "food": fav}, "Kimi's tummy rumbles loudly."
        if raw is None:
            return None
        try:
            va = validate_decision(raw, self.validation_context())
        except ActionRejected:
            return None
        rt.add_event("instinct", reason)
        return rt.handler.build_plan(va, "instinct")

    # -- local habits when the AI isn't being asked ----------------------------
    def _fallback(self, why: str) -> None:
        rt = self.rt
        w = rt.world
        n = w.needs
        here = w.location or HOME
        aff = rt.character.data.get("location_affinity", {})
        options: list[tuple[dict, float]] = [
            ({"action": "explore"}, 1.0 + n.curiosity / 40.0),
            ({"action": "observe", "duration_minutes": 25}, 1.0 + (n.social / 50.0 if here in ("cafe", "library", "print_shop") else 0)),
            ({"action": "rest", "duration_minutes": 30}, 0.5 + (100 - n.energy) / 40.0),
        ]
        others = [lid for lid in w.graph.locations if lid != here]
        if others:
            weights = [max(0.05, aff.get(lid, 0.3)) for lid in others]
            dest = rt.rng.choices(others, weights=weights, k=1)[0]
            options.append(({"action": "visit_location", "destination": dest, "duration_minutes": 30}, 1.2))
        if n.hunger > 55:
            options.append(({"action": "eat"}, 2.0 + n.hunger / 30.0))
        # Local habit: go and look at a curiosity here, preferring ones Kimi hasn't examined yet.
        spots = curiosity_spots()
        nearby = [c.id for c in CURIOSITIES if spots[c.id]["zone"] == here]
        if nearby:
            seen = rt.curiosity_visits()
            fresh = [cid for cid in nearby if cid not in seen] or nearby
            options.append(({"action": "examine", "curiosity_id": rt.rng.choice(fresh)}, 0.6 + n.curiosity / 60.0))
        raws, weights = zip(*options)
        raw = rt.rng.choices(raws, weights=weights, k=1)[0]
        try:
            va = validate_decision(dict(raw), self.validation_context())
        except ActionRejected:
            va = ValidatedAction("rest", {"duration_minutes": 20}, None)
        self._enqueue(rt.handler.build_plan(va, "fallback"))

    # -- AI decisions ------------------------------------------------------------
    def validation_context(self) -> ValidationContext:
        rt = self.rt
        w = rt.world
        allowed, reason = rt.research_status()
        return ValidationContext(
            graph=w.graph,
            current_location=w.location or w.destination or HOME,
            is_night=w.env.is_night,
            unread_notes={n["id"]: n["location"] for n in rt.inbox.unread(10)},
            creation_ids=rt.studio.ids(),
            research_allowed=allowed,
            research_block_reason=reason,
            sharing_enabled=rt.settings.get().external_sharing_enabled,
            web_check=rt.web_research_status,
            curiosity_zones={cid: sp["zone"] for cid, sp in curiosity_spots().items()},
        )

    def curiosity_lines(self, here: str, limit_here: int = 8, limit_elsewhere: int = 4) -> list[str]:
        """Curiosities near Kimi (with what it has noticed) and a few it hasn't examined yet."""
        rt = self.rt
        g = rt.world.graph
        spots = curiosity_spots()
        visits = rt.curiosity_visits()
        seen = len(visits)
        lines = [f"Kimi has examined {seen} of {len(CURIOSITIES)} curiosities."]
        nearby = [c for c in CURIOSITIES if spots[c.id]["zone"] == here]
        for c in nearby[:limit_here]:
            v = visits.get(c.id)
            if v:
                note = f"examined {v['visits']} time{'s' if v['visits'] != 1 else ''}; last noticed: {v['last_detail']}"
            else:
                note = "not examined yet"
            lines.append(f"[{c.id}] {c.name} (here): {note}")
        unseen = [c for c in CURIOSITIES if c.id not in visits and spots[c.id]["zone"] != here]
        if unseen:
            start = (rt.world.env.day * 7) % len(unseen)
            picks = (unseen[start:] + unseen[:start])[:limit_elsewhere]
            lines.append("Not examined yet elsewhere: " + "; ".join(
                f"[{c.id}] {c.name} (near {g.name(spots[c.id]['zone'])})" for c in picks) + ".")
        return lines

    def build_context(self) -> DecisionContext:
        rt = self.rt
        w = rt.world
        env, n = w.env, w.needs
        g = w.graph
        here = w.location or HOME
        places = []
        for loc in g.locations.values():
            if loc.id == here:
                head = f"here: {loc.name} [{loc.id}]"
            else:
                head = f"{loc.name} [{loc.id}], {g.travel_minutes(here, loc.id)} min walk"
            food = ""
            if loc.food and not (env.is_night and loc.id == "cafe"):
                food = f" Food: {', '.join(loc.food)}."
            closed = " (closed at night)" if env.is_night and loc.id == "cafe" else ""
            places.append(f"- {head}{closed}: {', '.join(loc.activities)}.{food}")

        events = [e for e in rt.recent_events if e["kind"] not in ("time",)][-8:]
        recent_events = [f"{e['clock']} {e['text']}" for e in events]

        unread_rows = rt.inbox.unread(3)
        unread = []
        visitors_ctx: set[str] = set()
        for row in unread_rows:
            visitors_ctx.add(row["visitor"])
            unread.append({
                "id": row["id"],
                "visitor": sanitize_name(row.get("display_name") or "an anonymous visitor") or "a visitor",
                "location": g.name(row["location"]),
                "received": _sim_label(row["sim_minute"]),
                "body": sanitize_untrusted(row["body"], 1200) or "(no words, just a picture)",
                "has_image": bool(row.get("image_path")),
                "image_description": sanitize_untrusted(row.get("image_description") or "", 300),
            })

        interests = [t for t, _ in rt.character.top_interests(4)]
        goals = [gl["text"] for gl in rt.character.active_goals()]
        query = " ".join([
            g.name(here), w.activity_label(), rt.character.mood, env.weather, *interests, *goals,
            *(u["body"][:300] for u in unread), *(e["text"] for e in events[-3:]),
        ])
        memories = rt.retriever.retrieve(query, location=here, visitors=visitors_ctx, k=8)
        mem_lines = [
            f"({_sim_label(m.sim_minute)}, {g.name(m.location) if m.location else 'somewhere'}"
            f"{', long-term' if m.tier == 'long' else ''}{f', x{m.recurrence}' if m.recurrence > 1 else ''}) {m.description}"
            for m in memories
        ]

        known = []
        for v in rt.visitors.all()[:6]:
            if v["familiarity"] < 0.2 and v["key"] not in visitors_ctx:
                continue
            fav = f"; usually at {g.name(v['favourite_location'])}" if v.get("favourite_location") else ""
            imp = f" Impression: {sanitize_untrusted(v['impression'], 150)}" if v.get("impression") else ""
            known.append(f"{sanitize_name(v['display_name'])}: {v['relationship']} ({v['note_count']} notes{fav}).{imp}")

        allowed, reason = rt.research_status()
        s = rt.settings.get()
        left = max(0, s.research_daily_limit - rt.research_done_today())
        limits = f"Research sessions left today: {left}" + ("" if allowed else f" (not now: {reason})") + "."
        shelves = ", ".join(SHELVES)
        limits += f" Library shelves: {shelves}."
        web_ok, web_why = rt.web_research_status()
        if web_ok:
            limits += (f" The speaking-tube (research_source wider_world) is available today, "
                       f"{max(0, s.web_search_daily_limit - rt.web_searches_today())} use(s) left, only for a strong "
                       "interest Kimi has already read about on the shelves.")
        else:
            limits += f" The speaking-tube is not available ({web_why})."
        if s.external_sharing_enabled:
            recent = rt.studio.list(5)
            listing = ", ".join(f"#{c.id} {c.title}" for c in recent) or "none yet"
            limits += f" Sharing creations is enabled (needs the human's approval). Recent creations: {listing}."
        else:
            limits += " Sharing creations: disabled."

        return DecisionContext(
            now=env.describe(),
            location=w.place_name,
            activity="nothing in particular right now" if not w.activity else w.activity_label(),
            needs=n.to_dict(),
            need_labels=n.labels(),
            mood=rt.character.mood,
            developing_self=rt.character.prompt_summary(env.day, {k: v.name for k, v in g.locations.items()}),
            places=places,
            recent_events=recent_events,
            memories=mem_lines,
            visitors_known=known,
            unread_notes=unread,
            recent_actions=list(self.recent_actions),
            curiosities=self.curiosity_lines(here),
            limits=limits,
            query_text=query,
        )

    def _request_decision(self) -> None:
        rt = self.rt
        ctx = self.build_context()
        vctx = self.validation_context()
        gen = self._generation
        self.last_decision_at = rt.mono()
        self.events_since_decision = 0
        rt.add_event("thinking", "Kimi pauses to think about what to do next.", store=False)
        self.in_flight = rt.submit_job(self._decision_job, ctx, vctx, on_done=lambda fut: self._on_decision(gen, fut))

    def _decision_job(self, ctx: DecisionContext, vctx: ValidationContext) -> DecisionOutcome:
        """Runs on the worker thread: only network calls and pure validation."""
        rt = self.rt
        raw = rt.engine.decide(ctx)
        try:
            va = validate_decision(raw, vctx)
        except ActionRejected as exc:
            return DecisionOutcome(raw=raw, action=None, rejected=exc.reason)
        payload: dict = {}
        if va.action == "research":
            payload = self._research_job(va, ctx)
        return DecisionOutcome(raw=raw, action=va, payload=payload)

    def _research_job(self, va: ValidatedAction, ctx: DecisionContext) -> dict:
        """Worker thread: read the chosen shelf, or (if every gate passed) ask the speaking-tube."""
        rt = self.rt
        topic = va.params["topic"]
        payload: dict = {}
        if va.params.get("source") == WIDER_WORLD:
            prior = rt._shelf_research_on(topic) or {}
            try:
                payload["web"] = rt.engine.web_research(
                    topic, sanitize_untrusted(prior.get("takeaway") or prior.get("title") or topic, 600),
                    ctx.developing_self)
                return payload
            except AIError as exc:
                log.info("Speaking-tube unavailable (%s); reading the encyclopedia instead", exc.message)
                va.params["source"] = "encyclopedia"
                va.params["web_declined"] = exc.message
        shelf = va.params.get("source") or "encyclopedia"
        try:
            findings = rt.researcher.investigate(topic, shelf)
            payload["findings"] = asdict(findings)
            try:
                payload["interpretation"] = rt.engine.interpret_research(
                    topic, findings.title, sanitize_untrusted(findings.extract, 1500), findings.url,
                    ctx.developing_self, findings.shelf_name)
            except AIError as exc:
                log.info("Research interpretation unavailable: %s", exc.message)
                payload["interpretation"] = None
        except ResearchUnavailable as exc:
            payload["error"] = str(exc)
        return payload

    def _schedule_next(self, quiet: bool) -> None:
        s = self.rt.settings.get()
        ceiling = max(1.0, s.decision_max_interval_s / max(1, s.decision_min_interval_s))
        self.idle_multiplier = min(ceiling, self.idle_multiplier * 1.5) if quiet else 1.0
        self.next_decision_at = self.rt.mono() + min(
            s.decision_max_interval_s, s.decision_min_interval_s * self.idle_multiplier
        )

    def _on_decision(self, gen: int, future) -> None:
        rt = self.rt
        if gen != self._generation:
            return  # cancelled (emergency stop or pause)
        self.in_flight = None
        exc = future.exception()
        if exc is not None:
            if isinstance(exc, AIError):
                rt.handler.log_action("decide", {}, "mind", "failed", reason=exc.message)
                if exc.kind == "budget":
                    rt.add_event("system", "Today's AI budget is used up. Kimi carries on by instinct until tomorrow.", importance=0.3)
                elif exc.kind != "stopped":
                    rt.add_event("system", f"Kimi couldn't gather its thoughts ({exc.message}). It carries on by instinct.")
            else:
                log.error("Decision job crashed", exc_info=exc)
                rt.handler.log_action("decide", {}, "mind", "failed", reason=f"{type(exc).__name__}")
            self._schedule_next(quiet=False)
            if self.autonomy_ok():
                self._fallback("AI unavailable")
            return
        outcome: DecisionOutcome = future.result()
        self.decisions_made += 1
        if outcome.action is None:
            action = str(outcome.raw.get("action", "?"))[:40]
            rt.handler.log_action(action, {k: str(v)[:80] for k, v in outcome.raw.items()
                                           if k != "content" and v not in (None, "", [])},
                                  "mind", "rejected", reason=outcome.rejected or "")
            rt.add_event("system", f"Kimi's idea ({action}) wasn't possible: {outcome.rejected}")
            self._schedule_next(quiet=False)
            if self.autonomy_ok():
                self._fallback("rejected idea")
            return
        if not self.autonomy_ok():
            return
        va = outcome.action
        self._apply_extras(va.extras)
        quiet = va.action in ("rest", "continue", "observe") and self.events_since_decision == 0
        self._schedule_next(quiet)
        self._enqueue(rt.handler.build_plan(va, "mind", outcome.payload))

    def _apply_extras(self, extras: dict) -> None:
        rt = self.rt
        ch = rt.character
        day = rt.world.env.day
        if extras.get("thought"):
            rt.set_thought(extras["thought"])
        if extras.get("mood"):
            ch.set_mood(extras["mood"])
        if extras.get("interest"):
            topic = ch.nudge_interest(extras["interest"], 0.08, "curiosity", day)
            if topic:
                rt.add_event("growth", f"Kimi is becoming curious about {topic}.", importance=0.3)
        if extras.get("new_goal") and ch.add_goal(extras["new_goal"], day):
            rt.add_event("growth", f"Kimi set itself a little goal: {extras['new_goal']}", importance=0.4)
        if extras.get("opinion_subject") and extras.get("opinion"):
            if ch.add_opinion(extras["opinion_subject"], extras["opinion"], day):
                rt.add_event("growth", f"Kimi decided something about {extras['opinion_subject']}: {extras['opinion']}")
        ch.save()
