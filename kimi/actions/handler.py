"""Executes validated plan steps and applies their effects.

Each action has a handler for starting it (setting Kimi's activity or
journey) and for completing it (changing needs, writing memories, creating
files). Only actions in the allow-list reach this module, and every
start/finish is recorded in the action log.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ..safety import check_action_name, sanitize_output
from ..world import discoveries
from ..world.curiosities import BY_ID as CURIOSITIES
from ..world.curiosities import CURIOSITIES as ALL_CURIOSITIES
from ..world.curiosities import detail_for
from ..world.locations import HOME
from .research import SHELVES
from ..world.world import Activity, PlanStep
from .validators import ValidatedAction

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime import KimiRuntime

log = logging.getLogger("kimi.actions")

DURATIONS = {
    "eat": 20, "read_note": 12, "research": 45, "write_diary": 25, "reflect": 15,
    "leave_message": 10, "share_creation": 10,
}
ART_DURATIONS = {"drawing": 60, "diary_illustration": 45, "story": 50, "poem": 35, "project": 70}

LABELS = {
    "eat": "eating {food}",
    "sleep": "sleeping",
    "rest": "resting",
    "explore": "exploring",
    "observe": "watching the world go by",
    "read_note": "reading a visitor's note",
    "research": "reading about {topic}",
    "write_diary": "writing in the diary",
    "create_art": "making a {art_kind}",
    "reflect": "thinking quietly",
    "leave_message": "pinning a message to the board",
    "share_creation": "preparing something to share",
    "continue": "carrying on",
    "visit_location": "spending time here",
    "examine": "looking closely at a curiosity",
    "linger": "pottering about",
}

RARITY_EFFECT = {
    "common": (0.30, 0.20, 0.35, 4),
    "uncommon": (0.50, 0.40, 0.60, 8),
    "rare": (0.80, 0.70, 0.90, 15),
}


CURIOSITY_GOAL = "Visit every curiosity in Bramblewick"

# Local-only activities the model can never request (validators reject them).
INTERNAL_ACTIONS = ("linger",)


def _check(step: PlanStep) -> None:
    if step.action in INTERNAL_ACTIONS and step.source != "mind":
        return
    check_action_name(step.action)


class _Blank(dict):
    """format_map helper: missing or empty parameters render as 'something'."""

    def __missing__(self, key: str) -> str:
        return "something"

    def __getitem__(self, key: str):
        value = super().get(key)
        return "something" if value in (None, "") else value


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


class ActionHandler:
    def __init__(self, rt: "KimiRuntime") -> None:
        self.rt = rt

    # -- logging ------------------------------------------------------------
    def log_action(self, action: str, params: dict, source: str, status: str, result: str = "", reason: str = "") -> int:
        cur = self.rt.db.execute(
            "INSERT INTO action_log(created_at, sim_minute, action, params, source, status, result, reason) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (self.rt.wall(), self.rt.world.env.minute, action, json.dumps(params, default=str)[:2000], source,
             status, result[:1000], reason[:500]),
        )
        return cur.lastrowid

    def update_log(self, log_id: int | None, status: str, result: str = "") -> None:
        if log_id:
            self.rt.db.execute("UPDATE action_log SET status=?, result=? WHERE id=?", (status, result[:1000], log_id))

    # -- planning -------------------------------------------------------------
    def build_plan(self, va: ValidatedAction, source: str, payload: dict | None = None) -> list[PlanStep]:
        check_action_name(va.action)
        world = self.rt.world
        here = world.location or world.destination or HOME
        steps: list[PlanStep] = []
        if va.required_location and va.required_location != here:
            steps.append(PlanStep("move_to", {"destination": va.required_location}, source,
                                  label=f"walk to {world.graph.name(va.required_location)}"))
        steps.append(PlanStep(va.action, dict(va.params), source, payload=dict(payload or {}),
                              label=va.describe()))
        return steps

    # -- starting -------------------------------------------------------------
    def start(self, step: PlanStep) -> None:
        _check(step)
        world = self.rt.world
        params = step.params
        if step.log_id is None:
            step.log_id = self.log_action(step.action, params, step.source, "started")

        if step.action == "move_to":
            minutes = world.begin_travel(params["destination"], step)
            if minutes == 0:
                self.update_log(step.log_id, "completed", "Already there.")
            else:
                self.rt.add_event("travel", f"Kimi sets off for {world.graph.name(params['destination'])}.")
            return

        here = world.location or HOME
        if step.action == "sleep":
            duration = world.env.minutes_until(6.5) if (world.env.hour >= 18 or world.env.hour < 6) else 60
            world.asleep = True
            world.begin_activity(step, max(30, duration), "sleeping")
            self.rt.add_event("activity", "Kimi tucks its head under a wing and falls asleep.")
            self.rt.on_sleep_started()
            return

        if step.action == "create_art":
            duration = ART_DURATIONS.get(params.get("art_kind", "drawing"), 60)
        elif step.action in DURATIONS:
            duration = DURATIONS[step.action]
        else:
            duration = int(params.get("duration_minutes") or 30)
        label = LABELS.get(step.action, step.action).format_map(_Blank(params))
        if step.action == "explore" and params.get("topic"):
            label = f"exploring, hoping to find {params['topic']}"
        if step.action == "examine" and params.get("curiosity") in CURIOSITIES:
            label = f"looking closely at {CURIOSITIES[params['curiosity']].name}"
        if step.action == "research" and params.get("source") == "wider_world":
            label = f"asking the speaking-tube about {params.get('topic', 'something')}"
        elif step.action == "research" and params.get("source") in SHELVES and params.get("source") != "encyclopedia":
            label = f"reading about {params.get('topic', 'something')} in {SHELVES[params['source']]}"
        world.begin_activity(step, duration, label)
        if step.action not in ("continue", "linger"):
            self.rt.add_event("activity", f"Kimi starts {label} at {world.graph.name(here)}.")

    # -- arrivals -------------------------------------------------------------
    def on_arrival(self, step: PlanStep, location: str) -> None:
        name = self.rt.world.graph.name(location)
        self.update_log(step.log_id, "completed", f"Arrived at {name}.")
        if step.source == "mind" and not self.rt.world.plan:
            self.rt.stm.add(f"Walked to {name}.", category="travel", sim_minute=self.rt.world.env.minute,
                            location=location, importance=0.1, valence=0.1)

    # -- completion ------------------------------------------------------------
    def complete(self, activity: Activity) -> str:
        step = activity.step
        try:
            _check(step)
            method = getattr(self, f"_finish_{step.action}", None)
            result = method(activity) if method else "Done."
        except Exception as exc:  # noqa: BLE001 - one failed action must not crash the world
            log.exception("Action %s failed", step.action)
            self.update_log(step.log_id, "failed", f"{type(exc).__name__}: {exc}")
            return "failed"
        self.update_log(step.log_id, "completed", result)
        return result

    # Helpers
    def _mem(self, text: str, category: str, *, importance: float, valence: float = 0.2, intensity: float = 0.1,
             visitor: str | None = None, location: str | None = None):
        loc = location or self.rt.world.location
        return self.rt.stm.add(text, category=category, sim_minute=self.rt.world.env.minute, location=loc,
                               visitor=visitor, importance=importance, valence=valence, intensity=intensity)

    def _place(self, activity: Activity) -> str:
        return self.rt.world.graph.name(activity.location)

    # Individual actions
    def _finish_eat(self, a: Activity) -> str:
        rt = self.rt
        food = a.step.params.get("food") or "a snack"
        base = rt.character.food_score(food)
        enjoyment = max(-1.0, min(1.0, base + rt.rng.uniform(-0.25, 0.35)))
        filling = 15 if "tea" in food else 55
        rt.world.needs.adjust(hunger=-filling, happiness=4 + 6 * enjoyment, energy=3)
        rt.character.record_food(food, 0.05 if enjoyment > 0.35 else -0.03)
        comment = "It was delicious." if enjoyment > 0.6 else "It was nice." if enjoyment > 0.25 else "Not my favourite."
        self._mem(f"Ate {_article(food)} {food} at {self._place(a)}. {comment}", "food",
                  importance=0.2 + 0.2 * abs(enjoyment), valence=enjoyment - 0.2, intensity=0.1)
        rt.add_event("activity", f"Kimi finishes {_article(food)} {food}. {comment}")
        return f"Ate {food}. {comment}"

    def _finish_sleep(self, a: Activity) -> str:
        rt = self.rt
        rt.world.asleep = False
        rt.add_event("activity", "Kimi wakes up, fluffs its feathers and blinks at the day.")
        recent = rt.stm.recent(15)
        if recent and rt.rng.random() < 0.35:
            m = rt.rng.choice(recent)
            text = m.description.rstrip(".")
            self._mem(f"Dreamt about this: {text[0].lower() + text[1:]}, but everything was made of moss.",
                      "dream", importance=0.3, valence=0.3, intensity=0.2, location=HOME)
        return "Woke up."

    def _finish_rest(self, a: Activity) -> str:
        return "Rested."

    def _finish_linger(self, a: Activity) -> str:
        return "Pottered about."

    def _finish_continue(self, a: Activity) -> str:
        return "Carried on."

    def _finish_explore(self, a: Activity) -> str:
        rt = self.rt
        loc = a.location
        find = discoveries.roll_discovery(loc, rt.rng, rt.world.needs.curiosity, a.step.params.get("topic"))
        if loc == "shrub":
            rt.character.progress_goal("Shrub")
        noticed = self._notice_curiosity(loc)
        if find is None and noticed:
            return noticed
        if find is None:
            seen = discoveries.observe(loc, rt.world.env.is_night, rt.rng)
            self._mem(f"Explored {self._place(a)} but found nothing special. {seen}", "observation",
                      importance=0.15, valence=0.1)
            rt.world.needs.adjust(curiosity=3)
            return "Found nothing special."
        importance, intensity, valence, joy = RARITY_EFFECT[find.rarity]
        rt.db.execute(
            "INSERT INTO discoveries(created_at, sim_minute, location, item, description, rarity) VALUES(?,?,?,?,?,?)",
            (rt.wall(), rt.world.env.minute, loc, find.item, find.description, find.rarity),
        )
        self._mem(f"Found {find.description} at {self._place(a)}.", "discovery",
                  importance=importance, valence=valence, intensity=intensity)
        rt.world.needs.adjust(happiness=joy, curiosity=6)
        rt.character.record_location_feeling(loc, 0.02 if find.rarity == "common" else 0.05)
        rt.add_event("discovery", f"Kimi found {find.description}!", importance=importance)
        return f"Found {find.item} ({find.rarity})."

    def _notice_curiosity(self, loc: str) -> str | None:
        """While exploring, Kimi sometimes spots a curiosity it hasn't looked at closely yet."""
        from ..world.curio3d import curiosity_spots

        rt = self.rt
        visits = rt.curiosity_visits()
        spots = curiosity_spots()
        unseen = [c for c in ALL_CURIOSITIES if spots[c.id]["zone"] == loc and c.id not in visits]
        if not unseen or rt.rng.random() > 0.5:
            return None
        c = rt.rng.choice(unseen)
        self._mem(f"Spotted {c.name} near {rt.world.graph.name(loc)}: {c.what}. I'd like to look at it properly.",
                  "discovery", importance=0.35, valence=0.4, intensity=0.2)
        rt.add_event("discovery", f"Kimi spots {c.name} and makes a note to look closer.", importance=0.3)
        rt.world.needs.adjust(curiosity=4, happiness=2)
        return f"Spotted {c.name}."

    def _finish_examine(self, a: Activity) -> str:
        rt = self.rt
        cid = a.step.params.get("curiosity")
        c = CURIOSITIES.get(cid)
        if c is None:
            return "Nothing there."
        before = int(rt.curiosity_visits().get(cid, {}).get("visits", 0))
        n = before + 1
        detail = detail_for(c, n)
        rt.record_curiosity_visit(cid, detail)
        place = self._place(a)
        day = rt.world.env.day
        first, last_secret = n == 1, n == len(c.details)
        if first:
            self._mem(f"Looked closely at {c.name} near {place} for the first time: {c.what}. {detail}", "curiosity",
                      importance=0.55, valence=0.55, intensity=0.4)
            rt.add_event("discovery", f"Kimi examines {c.name} for the first time. {detail}", importance=0.55)
            rt.world.needs.adjust(curiosity=-10, happiness=6)
            rt.character.nudge_interest(c.tags[0], 0.05, "curiosity", day)
            rt.character.ensure_goal(CURIOSITY_GOAL, len(ALL_CURIOSITIES), day)
            goal = rt.character.progress_goal("every curiosity")
            if goal and goal.get("status") == "completed":
                rt.add_event("growth", "Kimi has looked closely at every curiosity in Bramblewick!", importance=0.9)
        else:
            weight = 0.45 if last_secret else 0.35 if n <= len(c.details) else 0.2
            self._mem(f"Went back to {c.name} near {place}. {detail}", "curiosity",
                      importance=weight, valence=0.45, intensity=0.25)
            rt.add_event("discovery", f"Kimi visits {c.name} again. {detail}", importance=0.6 if last_secret else 0.3)
            rt.world.needs.adjust(curiosity=-6, happiness=4 if n <= len(c.details) else 2)
        rt.character.record_location_feeling(a.location, 0.01)
        rt.character.save()
        return f"Examined {c.name} (visit {n})."

    def _finish_observe(self, a: Activity) -> str:
        rt = self.rt
        seen = discoveries.observe(a.location, rt.world.env.is_night, rt.rng)
        self._mem(f"At {self._place(a)}: {seen}", "observation", importance=0.15, valence=0.2)
        if discoveries.has_company(a.location, rt.world.env.is_night):
            rt.world.needs.adjust(social=-5)
        rt.add_event("observation", seen)
        return seen

    def _finish_visit_location(self, a: Activity) -> str:
        result = self._finish_observe(a)
        self.rt.character.record_location_feeling(a.location, 0.01)
        return result

    def _finish_read_note(self, a: Activity) -> str:
        rt = self.rt
        p = a.step.params
        note = rt.inbox.get(int(p["note_id"]))
        if note.get("read_at"):
            return "Already read."
        reply = p.get("reply")
        rt.inbox.mark_read(note["id"], reply)
        name = note.get("display_name") or "an anonymous visitor"
        snippet = (note["body"] or "").replace("\n", " ")
        snippet = snippet[:160] + ("…" if len(snippet) > 160 else "")
        text = f"Read a note from {name} at {rt.world.graph.name(note['location'])}"
        text += f": “{snippet}”" if snippet else "."
        if note.get("image_description"):
            text += f" They left a picture: {note['image_description']}"
        if reply:
            text += f" I replied: “{reply[:120]}”"
            rt.board.post_kimi_message(reply, note["location"], rt.world.env.minute, in_reply_to=note["id"])
        self._mem(text, "visitor", importance=0.6, valence=0.45, intensity=0.4, visitor=note["visitor"],
                  location=note["location"])
        rt.visitors.register_read(note["visitor"], p.get("visitor_impression"))
        rt.world.needs.adjust(social=-25, happiness=6)
        rt.add_event("visitor", f"Kimi read {name}'s note" + (" and pinned a reply." if reply else "."), importance=0.5)
        return f"Read note {note['id']} from {name}."

    def _finish_research(self, a: Activity) -> str:
        rt = self.rt
        topic = a.step.params.get("topic", "something")
        payload = a.step.payload
        findings = payload.get("findings")
        interp = payload.get("interpretation")
        if payload.get("web"):
            return self._finish_web_research(a, topic, payload["web"])
        if not findings:
            why = payload.get("error") or "the books were no help"
            self._mem(f"Tried to research {topic} at the Library, but {why}.", "research", importance=0.2, valence=-0.1)
            rt.db.execute("INSERT INTO research_log(created_at, day, topic, summary) VALUES(?,?,?,?)",
                          (rt.wall(), rt.today(), topic, f"unsuccessful: {why}"))
            return f"Research on {topic} found nothing."
        takeaway = (interp or {}).get("takeaway") or findings["extract"][:240]
        importance = {"low": 0.35, "medium": 0.55, "high": 0.75}.get((interp or {}).get("importance"), 0.5)
        feeling = (interp or {}).get("feeling", "intrigued")
        valence = {"delighted": 0.8, "moved": 0.6, "intrigued": 0.5, "puzzled": 0.0, "unimpressed": -0.2}.get(feeling, 0.4)
        shelf = findings.get("source") or "encyclopedia"
        shelf_name = SHELVES.get(shelf, "the encyclopedia")
        rt.db.execute(
            "INSERT INTO research_log(created_at, day, topic, title, source_url, summary, takeaway, source) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (rt.wall(), rt.today(), topic, findings["title"], findings["url"], findings["extract"][:1500], takeaway,
             shelf),
        )
        self._mem(f"Researched {topic} in {shelf_name} at the Library ({findings['title']}): {takeaway}", "research",
                  importance=importance, valence=valence, intensity=0.3 + 0.4 * (importance > 0.6))
        day = rt.world.env.day
        rt.character.nudge_interest(topic, 0.12, "research", day)
        follow = (interp or {}).get("follow_up_interest")
        if follow:
            rt.character.nudge_interest(follow, 0.06, "research", day)
        rt.world.needs.adjust(curiosity=-15, happiness=5)
        rt.add_event("discovery", f"Kimi learned about {findings['title']}: {takeaway[:140]}", importance=importance)
        return f"Researched {topic}."

    def _finish_web_research(self, a: Activity, topic: str, web: dict) -> str:
        """Record what the speaking-tube (wider-web search) found. The text is untrusted-derived."""
        rt = self.rt
        text = sanitize_output(web.get("text") or "", 900)
        citations = [c for c in (web.get("citations") or []) if str(c.get("url", "")).startswith("https://")][:6]
        first = citations[0] if citations else {}
        rt.db.execute(
            "INSERT INTO research_log(created_at, day, topic, title, source_url, summary, takeaway, source, citations) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (rt.wall(), rt.today(), topic, sanitize_output(first.get("title") or "the wider world", 160),
             first.get("url"), text, text, "wider_world", json.dumps(citations)[:4000]),
        )
        where = f" (from {sanitize_output(first.get('title'), 80)})" if first.get("title") else ""
        self._mem(f"Asked the Library's speaking-tube about {topic}{where}: {text}", "research",
                  importance=0.75, valence=0.6, intensity=0.6)
        day = rt.world.env.day
        rt.character.nudge_interest(topic, 0.1, "research", day)
        rt.world.needs.adjust(curiosity=-20, happiness=6)
        rt.add_event("discovery", f"Kimi used the speaking-tube to learn more about {topic}: {text[:140]}",
                     importance=0.6)
        return f"Researched {topic} in the wider world."

    def _finish_write_diary(self, a: Activity) -> str:
        rt = self.rt
        p = a.step.params
        entry = rt.diary.add(p.get("title") or "A page from my diary", p["content"], sim_minute=rt.world.env.minute,
                             location=a.location, mood=rt.character.mood)
        self._mem(f"Wrote in my diary: “{entry.title}”.", "diary", importance=0.2, valence=0.3)
        rt.world.needs.adjust(happiness=2)
        rt.add_event("diary", f"Kimi wrote a diary entry: “{entry.title}”.", importance=0.4)
        return f"Diary entry {entry.id}."

    def _finish_create_art(self, a: Activity) -> str:
        rt = self.rt
        p = a.step.params
        creation = rt.studio.create(kind=p["art_kind"], title=p["title"], content=p.get("content", ""),
                                    elements=p.get("elements") or [], sim_minute=rt.world.env.minute,
                                    location=a.location)
        kind = creation.kind.replace("_", " ")
        self._mem(f"Made {_article(kind)} {kind} called “{creation.title}” at the Print Shop.", "creation",
                  importance=0.5, valence=0.6, intensity=0.4)
        rt.world.needs.adjust(happiness=8)
        rt.character.record_activity_outcome("create_art", 0.02)
        if creation.kind in ("drawing", "diary_illustration"):
            rt.character.progress_goal("drawing")
        rt.add_event("creation", f"Kimi made something new: {_article(kind)} {kind} called “{creation.title}”.",
                     importance=0.75)
        return f"Created {creation.kind} {creation.id}."

    def _finish_reflect(self, a: Activity) -> str:
        p = a.step.params
        self._mem(f"I thought about this: {p['content']}", "reflection", importance=0.45, valence=0.2, intensity=0.3)
        self.rt.world.needs.adjust(happiness=2)
        self.rt.add_event("thought", f"Kimi reflects: {p['content'][:160]}")
        return "Reflected."

    def _finish_leave_message(self, a: Activity) -> str:
        rt = self.rt
        content = a.step.params["content"]
        rt.board.post_kimi_message(content, a.location, rt.world.env.minute)
        self._mem(f"Pinned a message on the Shrine board: “{content[:120]}”", "message", importance=0.3, valence=0.3)
        rt.add_event("visitor", f"Kimi pinned a message on the Shrine board: “{content[:120]}”", importance=0.4)
        return "Message pinned."

    def _finish_share_creation(self, a: Activity) -> str:
        rt = self.rt
        creation = rt.studio.get(int(a.step.params["creation_id"]))
        item = rt.outbox.draft(
            "share_creation", f"Share “{creation.title}”",
            f"Kimi would like to share its {creation.kind.replace('_', ' ')} “{creation.title}”.\n\n{creation.body}",
            {"creation_id": creation.id},
        )
        self._mem(f"Asked if I could share “{creation.title}” with the world.", "creation", importance=0.3, valence=0.3)
        rt.add_event("approval", f"Kimi would like to share “{creation.title}”. It's waiting for your approval.",
                     importance=0.6)
        return f"Outbox item {item} awaiting approval."
