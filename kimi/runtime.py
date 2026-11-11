"""KimiRuntime: owns Kimi's world and runs it.

A background "world thread" ticks the local simulation twice a second
(time, weather, needs, movement, activities, visitor inbox). Slow work -
calls to Claude Haiku 5.5 and research requests - runs on a separate worker
thread so neither the world nor the interface ever freezes. State is saved
to SQLite every few seconds and on shutdown; after a crash Kimi resumes from
the last save.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Callable

from . import credentials
from .actions.creative import CreativeStudio
from .actions.handler import ActionHandler
from .actions.research import WikipediaResearcher
from .actions.sharing import Outbox, ProjectsRepo, mailto_url, valid_github_remote
from .ai.claude_client import AIError, ClaudeClient
from .ai.costs import UsageLedger, local_day
from .ai.decision_engine import DecisionEngine
from .character import CharacterSheet
from .cognition import CognitiveLoop
from .config import Paths, SettingsStore
from .diary import Diary
from .memory.consolidation import MemoryConsolidator, local_reflection
from .memory.database import Database
from .memory.long_term import LongTermMemory
from .memory.retrieval import MemoryRetriever
from .memory.short_term import ShortTermMemory
from .safety import safe_child_path, sanitize_output
from .visitors.board import MessageBoard, VisitorRegistry
from .visitors.inbox import VisitorInbox
from .world.locations import HOME
from .world.world import World

log = logging.getLogger("kimi.runtime")


class InlineJobs:
    """Runs jobs immediately on the calling thread (tests and demos)."""

    def submit(self, fn: Callable, *args: Any) -> Future:
        fut: Future = Future()
        try:
            fut.set_result(fn(*args))
        except BaseException as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut

    def shutdown(self) -> None:
        pass


class ThreadJobs:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kimi-mind")

    def submit(self, fn: Callable, *args: Any) -> Future:
        return self._pool.submit(fn, *args)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


STATUS_TEXT = {
    "active": "Active",
    "sleeping": "Sleeping",
    "paused": "Paused",
    "stopped": "Stopped",
    "autonomy_off": "Autonomy off",
    "disconnected": "Disconnected",
    "budget_paused": "Budget reached",
    "needs_key": "No API key",
}


class KimiRuntime:
    TICK_S = 0.5
    SAVE_EVERY_S = 10.0

    def __init__(
        self,
        paths: Paths,
        *,
        key_provider: Callable[[], str | None] | None = None,
        sdk_factory=None,
        researcher=None,
        seed: int | None = None,
        inline_jobs: bool = False,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
        client_sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.paths = paths.ensure()
        self.wall = wall
        self._base_mono = mono
        self._virtual_s = 0.0   # extra elapsed time added by advance_world()
        self.lock = threading.RLock()
        self.db = Database(paths.db)
        self.settings = SettingsStore(self.db)
        self.rng = random.Random(seed)

        self.character = CharacterSheet(self.db)
        self.stm = ShortTermMemory(self.db, wall)
        self.ltm = LongTermMemory(self.db, wall)
        self.retriever = MemoryRetriever(self.db, wall)
        self.consolidator = MemoryConsolidator(self.db, self.stm, self.ltm, self.character, wall)

        self.world = self._load_world()
        self.world.likes_rain = self.character.likes_rain
        self.diary = Diary(self.db, paths.diary, self.place_name, wall)
        self.studio = CreativeStudio(self.db, paths.creations, self.place_name, wall)
        self.visitors = VisitorRegistry(self.db, wall)
        self.board = MessageBoard(self.db, paths.inbox, wall)
        self.inbox = VisitorInbox(paths, self.db, self.visitors, wall)
        self.outbox = Outbox(self.db, wall)
        self.projects = ProjectsRepo(paths.projects, paths.creations)
        self.researcher = researcher or WikipediaResearcher(self.settings)

        self.ledger = UsageLedger(self.db, self.settings, wall)
        self.client = ClaudeClient(key_provider or credentials.load_api_key, self.ledger, self.settings,
                                   sdk_factory, sleep=client_sleep, wall=wall, mono=self.mono)
        self.engine = DecisionEngine(self.client, self.settings)

        self.recent_events: deque[dict] = deque(maxlen=80)
        for row in reversed(self.db.query("SELECT * FROM events ORDER BY id DESC LIMIT 40")):
            self.recent_events.append(self._event_dict(row["id"], row["kind"], row["text"], row["sim_minute"], row["importance"]))
        self.highlights: deque[dict] = deque(maxlen=10)
        self.last_thought: dict | None = self.db.kv_get("last_thought")
        self._last_consolidated_day = int(self.db.kv_get("last_consolidated_day", 0) or 0)

        self.handler = ActionHandler(self)
        self.cognition = CognitiveLoop(self)
        self.jobs = InlineJobs() if inline_jobs else ThreadJobs()
        self._pending: list[tuple[Future, Callable[[Future], None]]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick = self.mono()
        self._last_inbox_scan = -1e9
        self._last_save = self.mono()
        self.recovered_from_crash = False
        self.closed = False
        self._recover()

    def mono(self) -> float:
        """Monotonic seconds, including time simulated with advance_world()."""
        return self._base_mono() + self._virtual_s

    # -- startup & recovery ---------------------------------------------------
    def _load_world(self) -> World:
        state = self.db.kv_get("world_state")
        if isinstance(state, dict):
            try:
                w = World.from_dict(state, rng=self.rng)
            except Exception:  # noqa: BLE001 - corrupted state must not prevent startup
                log.exception("World state was unreadable; starting a fresh day at the Nest")
                w = World(rng=self.rng)
        else:
            w = World(rng=self.rng)
        if w.asleep and not (w.activity and w.activity.step.action == "sleep"):
            w.asleep = False
        return w

    def _recover(self) -> None:
        first_run = self.db.kv_get("world_state") is None
        was_clean = bool(self.db.kv_get("clean_shutdown", True))
        if first_run:
            self.add_event("system", "Kimi wakes up in its nest for the very first time.", importance=0.6)
            self.stm.add("Woke up in my nest in Bramblewick for the very first time. Everything smells of moss.",
                         category="milestone", sim_minute=self.world.env.minute, location=HOME,
                         importance=0.85, valence=0.6, intensity=0.7)
        elif not was_clean:
            self.recovered_from_crash = True
            log.warning("Previous session did not shut down cleanly; recovered from last save")
            self.add_event("system", "Kimi's world was restored after an unexpected shutdown.", importance=0.4)
            # Steps started but never finished were interrupted by the crash.
            self.db.execute("UPDATE action_log SET status='interrupted' WHERE status='started' AND id NOT IN (?, ?)",
                            (self._live_log_id(), self._live_log_id(travel=True)))
        self.db.kv_set("clean_shutdown", False)
        self.db.kv_set("session_started", self.wall())
        self.save()

    def _live_log_id(self, travel: bool = False) -> int:
        w = self.world
        if travel and w.travel and w.travel.step.log_id:
            return int(w.travel.step.log_id)
        if not travel and w.activity and w.activity.step.log_id:
            return int(w.activity.step.log_id)
        return -1

    # -- threads -----------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._last_tick = self.mono()
        self._thread = threading.Thread(target=self._run, name="kimi-world", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.TICK_S):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - keep Kimi alive whatever happens
                log.exception("World tick failed")

    def submit_job(self, fn: Callable, *args: Any, on_done: Callable[[Future], None]) -> Future:
        fut = self.jobs.submit(fn, *args)
        with self.lock:
            # Callbacks always run on the world thread at the start of the next tick,
            # so callers can record the future before its result is applied.
            self._pending.append((fut, on_done))
        return fut

    def _collect_jobs(self) -> None:
        with self.lock:
            done = [(f, cb) for f, cb in self._pending if f.done()]
            if not done:
                return
            self._pending = [(f, cb) for f, cb in self._pending if not f.done()]
            for fut, cb in done:
                if fut.cancelled():
                    continue
                try:
                    cb(fut)
                except Exception:  # noqa: BLE001
                    log.exception("Job callback failed")

    def wait_for_jobs(self, timeout: float = 30.0) -> None:
        """Block until background jobs finish (used by demos and tests)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                pending = [f for f, _ in self._pending]
            if not pending:
                return
            if all(f.done() for f in pending):
                self._collect_jobs()
                continue
            time.sleep(0.05)

    # -- simulation ----------------------------------------------------------------
    def tick(self, real_dt: float | None = None) -> None:
        now = self.mono()
        if real_dt is None:
            real_dt = min(5.0, max(0.0, now - self._last_tick))
        self._last_tick = now
        with self.lock:
            self._collect_jobs()
            s = self.settings.get()
            if s.paused:
                return
            sim = real_dt * s.time_scale / 60.0
            while sim > 1e-9:
                chunk = min(sim, 2.0)
                sim -= chunk
                self._advance(chunk)
            if now - self._last_inbox_scan >= s.inbox_poll_s:
                self._last_inbox_scan = now
                self.scan_inbox()
            self.cognition.update()
            if now - self._last_save >= self.SAVE_EVERY_S:
                self.save()

    def advance_world(self, sim_minutes: float, step: float = 1.0) -> None:
        """Advance the world by a number of world-minutes as if that much real time had
        passed (tests and demos). Background jobs are collected along the way."""
        s = self.settings.get()
        remaining = sim_minutes
        while remaining > 1e-9:
            chunk = min(step, remaining)
            remaining -= chunk
            real_dt = chunk * 60.0 / s.time_scale
            self._virtual_s += real_dt
            self.tick(real_dt=real_dt)

    def _advance(self, minutes: float) -> None:
        self.world.likes_rain = self.character.likes_rain
        for ev in self.world.tick(minutes):
            if ev.kind in ("weather", "time"):
                self.add_event(ev.kind, ev.text)
            elif ev.kind == "passed":
                self.add_event("travel", f"Kimi hops through {self.world.graph.name(ev.location)}.", store=False)
            elif ev.kind == "arrived":
                self.add_event("travel", f"Kimi arrives at {self.world.graph.name(ev.location)}.")
                self.handler.on_arrival(ev.data, ev.location)
            elif ev.kind == "activity_done":
                self.handler.complete(ev.data)
        self.advance_plan()

    def advance_plan(self) -> None:
        w = self.world
        if not self.cognition.autonomy_ok():
            return
        guard = 0
        while not w.travel and not w.activity and w.plan and guard < 10:
            guard += 1
            step = w.plan.pop(0)
            self.handler.start(step)

    # -- visitors ---------------------------------------------------------------
    def scan_inbox(self) -> list:
        notes, rejected = self.inbox.scan(self.world.env.minute)
        g = self.world.graph
        for n in notes:
            snippet = n.body.replace("\n", " ")
            snippet = snippet[:140] + ("…" if len(snippet) > 140 else "")
            desc = f"{n.visitor_name} left a note at {g.name(n.location)}"
            desc += f": “{snippet}”" if snippet else ""
            desc += " (with a picture)" if n.image_path else ""
            self.stm.add(desc, category="note_arrival", sim_minute=self.world.env.minute, location=n.location,
                         visitor=n.visitor_key, importance=0.5, valence=0.3, intensity=0.3)
            self.add_event("visitor", f"A note from {n.visitor_name} appeared at {g.name(n.location)}.", importance=0.55)
            self.cognition.notify_event()
            if n.image_path and self.settings.get().vision_enabled and self.client.availability()[0]:
                self.submit_job(self._describe_image_job, n.id, n.image_path, g.name(n.location),
                                on_done=self._on_image_described)
        for name in rejected:
            self.add_event("visitor", f"Something Kimi didn't recognise ({name[:40]}) was left in the inbox; it left it alone.")
        return notes

    def _describe_image_job(self, note_id: int, rel_path: str, location_name: str) -> tuple[int, str]:
        data = safe_child_path(self.paths.root, rel_path).read_bytes()
        result = self.engine.describe_image(data, "image/png", location_name)
        return note_id, sanitize_output(result.get("description", ""), 300)

    def _on_image_described(self, fut: Future) -> None:
        exc = fut.exception()
        if exc is not None:
            log.info("Image description unavailable: %s", getattr(exc, "message", exc))
            return
        note_id, description = fut.result()
        if description:
            self.inbox.set_image_description(note_id, description)

    # -- research quota ------------------------------------------------------------
    def today(self) -> str:
        return local_day(self.wall())

    def research_done_today(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM research_log WHERE day=?", (self.today(),), 0))

    def research_status(self) -> tuple[bool, str]:
        s = self.settings.get()
        if not s.research_enabled:
            return False, "research is turned off in Settings"
        if self.research_done_today() >= s.research_daily_limit:
            return False, "Kimi has done enough research for today"
        cooldown = getattr(self.researcher, "cooldown_remaining", lambda: 0.0)()
        if cooldown > 0:
            return False, f"the Library is closed for a while (about {int(cooldown // 60) + 1} min)"
        last = self.db.scalar("SELECT MAX(created_at) FROM research_log", (), None)
        if last and self.wall() - float(last) < 15 * 60:
            return False, "Kimi researched something very recently and wants to digest it first"
        return True, ""

    # -- consolidation ---------------------------------------------------------------
    def on_sleep_started(self) -> None:
        self.maybe_consolidate()

    def maybe_consolidate(self) -> None:
        env = self.world.env
        reflect_day = env.day if env.hour >= 12 else env.day - 1
        if reflect_day < 1 or self._last_consolidated_day >= reflect_day:
            return
        if not (env.hour >= 21 or env.hour < 5 or (self.world.asleep and env.hour >= 18)):
            return
        self._last_consolidated_day = reflect_day
        self.db.kv_set("last_consolidated_day", reflect_day)
        report = self.consolidator.consolidate(reflect_day, env.minute)
        self.add_event("memory", f"As Kimi drifts off it sorts through the day: {report.promoted} memories kept for good, "
                                 f"{report.merged} merged, {report.forgotten} faded.", importance=0.3)
        highlights = [m.description for m in report.highlights]
        stats = (f"memories reviewed {report.reviewed}, kept {report.promoted}, merged {report.merged}, "
                 f"faded {report.forgotten}")
        if highlights and self.cognition.autonomy_ok() and self.client.availability()[0]:
            summary = self.character.prompt_summary(env.day, {k: v.name for k, v in self.world.graph.locations.items()})
            goals = [g["text"] for g in self.character.active_goals()]
            self.submit_job(self.engine.reflect, reflect_day, highlights, summary, goals, stats,
                            on_done=lambda fut: self._on_reflection(reflect_day, report, fut))
        else:
            self._write_reflection(reflect_day, "End of the day", local_reflection(report, self.place_name), None)

    def _on_reflection(self, day: int, report, fut: Future) -> None:
        exc = fut.exception()
        if exc is not None:
            self._write_reflection(day, "End of the day", local_reflection(report, self.place_name), None)
            return
        data = fut.result()
        ch = self.character
        if data.get("mood"):
            ch.set_mood(data["mood"])
        if data.get("interest"):
            ch.nudge_interest(data["interest"], 0.06, "reflection", day)
        if data.get("opinion_subject") and data.get("opinion"):
            ch.add_opinion(data["opinion_subject"], data["opinion"], day)
        if data.get("new_goal"):
            ch.add_goal(data["new_goal"], day)
        if isinstance(data.get("completed_goal_number"), int):
            goal = ch.complete_goal(data["completed_goal_number"] - 1)
            if goal:
                self.add_event("growth", f"Kimi achieved a goal: {goal['text']}", importance=0.7)
        ch.save()
        self._write_reflection(day, data.get("title") or "End of the day", data.get("reflection") or "", data.get("mood"))

    def _write_reflection(self, day: int, title: str, text: str, mood: str | None) -> None:
        text = sanitize_output(text, 2500)
        if len(text) < 10:
            return
        self.diary.add(title, text, sim_minute=self.world.env.minute, location=self.world.location,
                       mood=mood or self.character.mood, kind="reflection")
        self.ltm.add(f"Day {day} reflection: {text[:300]}", category="reflection", sim_minute=self.world.env.minute,
                     location=self.world.location, importance=0.55, valence=0.3, intensity=0.3)
        self.add_event("diary", f"Kimi wrote its evening reflection for Day {day}.", importance=0.4)

    # -- events & thoughts --------------------------------------------------------------
    def _event_dict(self, eid: int | None, kind: str, text: str, sim_minute: float, importance: float) -> dict:
        m = int(sim_minute % 1440)
        return {"id": eid, "kind": kind, "text": text, "day": int(sim_minute // 1440) + 1,
                "clock": f"{m // 60:02d}:{m % 60:02d}", "importance": importance}

    def add_event(self, kind: str, text: str, importance: float = 0.1, store: bool = True) -> dict:
        minute = self.world.env.minute
        eid = None
        if store:
            cur = self.db.execute(
                "INSERT INTO events(created_at, sim_minute, kind, text, location, importance) VALUES(?,?,?,?,?,?)",
                (self.wall(), minute, kind, text[:500], self.world.location, importance),
            )
            eid = cur.lastrowid
            if eid and eid % 500 == 0:
                self.db.execute("DELETE FROM events WHERE id < ?", (eid - 3000,))
        ev = self._event_dict(eid, kind, text[:500], minute, importance)
        with self.lock:
            self.recent_events.append(ev)
            if importance >= 0.7:
                self.highlights.append(ev)
        log.info("[%s] %s", kind, text[:200])
        return ev

    def set_thought(self, text: str) -> None:
        env = self.world.env
        self.last_thought = {"text": text, "day": env.day, "clock": env.clock_label}
        self.db.kv_set("last_thought", self.last_thought)
        self.add_event("thought", f"“{text}”", store=True)

    def dismiss_highlight(self) -> None:
        with self.lock:
            if self.highlights:
                self.highlights.popleft()

    def place_name(self, lid: str | None) -> str:
        return self.world.graph.name(lid) if lid else "somewhere in Bramblewick"

    # -- controls ------------------------------------------------------------------------
    def pause(self) -> None:
        with self.lock:
            self.settings.update(paused=True)
            self.cognition.cancel()
            self.add_event("system", "Paused. Kimi and its world are frozen in time.", importance=0.2)
            self.save()

    def resume(self) -> None:
        with self.lock:
            self.settings.update(paused=False)
            self._last_tick = self.mono()
            self.add_event("system", "Resumed. Time flows again in Bramblewick.", importance=0.2)

    def emergency_stop(self) -> None:
        with self.lock:
            self.settings.update(emergency_stopped=True, autonomous_enabled=False)
            self.client.halt()
            self.cognition.cancel()
            dropped = self.world.interrupt()
            for step in dropped:
                self.handler.update_log(step.log_id, "interrupted", "Emergency stop")
            self.add_event("system", "EMERGENCY STOP: all autonomous activity and AI requests have stopped.", importance=0.5)
            self.save()

    def set_autonomous(self, enabled: bool) -> None:
        with self.lock:
            if enabled:
                self.settings.update(autonomous_enabled=True, emergency_stopped=False)
                self.client.resume()
                self.cognition.next_decision_at = self.mono() + 3.0
                self.add_event("system", "Autonomous mode is on. Kimi will decide for itself again.", importance=0.2)
            else:
                self.settings.update(autonomous_enabled=False)
                self.cognition.cancel()
                self.add_event("system", "Autonomous mode is off. Kimi will finish what it's doing and then wait.",
                               importance=0.2)

    def reload_api_key(self) -> None:
        self.client.reload_key()
        self.cognition.next_decision_at = min(self.cognition.next_decision_at, self.mono() + 3.0)

    def update_settings(self, **changes: Any):
        s = self.settings.update(**changes)
        if "daily_budget_usd" in changes or "max_requests_per_day" in changes:
            self.client.clear_budget_pause()
        return s

    # -- approvals -----------------------------------------------------------------------
    def approve_share(self, item_id: int, method: str) -> tuple[bool, str, str | None]:
        item = self.outbox.get(item_id)
        if item["status"] != "pending":
            return False, "This item has already been handled.", None
        creation = self.studio.get(int(item["payload"].get("creation_id", -1)))
        if method == "email":
            path = self.studio.path_of(creation)
            body = (creation.body if creation.kind not in ("drawing", "diary_illustration")
                    else f"Kimi made a drawing called “{creation.title}”. The picture is saved at:\n{path}")
            url = mailto_url(f"Something Kimi made: {creation.title}", body)
            self.outbox.mark(item_id, "approved", "Opened as an email draft in your mail program.")
            self.add_event("approval", f"You approved sharing “{creation.title}” by email (draft opened).")
            return True, "An email draft has been opened in your mail program. Nothing is sent until you send it.", url
        if method == "github":
            remote = self.settings.get().github_remote_url
            if not remote or not valid_github_remote(remote):
                return False, "Set a GitHub repository URL in Settings first.", None
            if not self.projects.git_available():
                return False, "Git is not installed, so Kimi can't publish to GitHub.", None
            path = self.studio.path_of(creation)
            if path is None or not path.exists():
                return False, "The creation's file is missing.", None
            try:
                self.projects.add_creation(path, creation.title)
                ok, output = self.projects.push(remote)
            except Exception as exc:  # noqa: BLE001
                ok, output = False, f"{type(exc).__name__}: {exc}"
            self.outbox.mark(item_id, "done" if ok else "failed", output)
            self.add_event("approval", f"Publishing “{creation.title}” to GitHub {'succeeded' if ok else 'failed'}.")
            return ok, output or ("Published." if ok else "Push failed."), None
        return False, "Unknown approval method.", None

    def reject_share(self, item_id: int) -> None:
        self.outbox.mark(item_id, "rejected", "Declined by you.")
        self.add_event("approval", "You declined a sharing request. Kimi doesn't mind.")

    # -- resets ----------------------------------------------------------------------------
    def reset_world(self) -> None:
        with self.lock:
            self.cognition.cancel()
            self.world = World(rng=self.rng)
            self.add_event("system", "The world was reset. Kimi is back in its nest on a fresh morning.", importance=0.3)
            self.save()

    def reset_everything(self) -> None:
        """Erase Kimi's memories, diary, character and world. API usage history is kept
        so the daily budget can't be bypassed; creation and diary files stay on disk."""
        with self.lock:
            self.cognition.cancel()
            with self.db.transaction():
                for table in ("memories", "diary", "creations", "visitors", "visitor_notes", "board_messages",
                              "action_log", "events", "discoveries", "research_log", "outbox", "kv"):
                    self.db.execute(f"DELETE FROM {table}")
            self.character = CharacterSheet(self.db)
            self.consolidator.character = self.character
            self.world = World(rng=self.rng)
            self.recent_events.clear()
            self.highlights.clear()
            self.last_thought = None
            self._last_consolidated_day = 0
            self.cognition.recent_actions.clear()
            self.db.kv_set("clean_shutdown", False)
            self.add_event("system", "Kimi has been reset and hatches anew.", importance=0.5)
            self.save()

    # -- status & snapshot -------------------------------------------------------------------
    def status(self) -> str:
        s = self.settings.get()
        if s.emergency_stopped:
            return "stopped"
        if s.paused:
            return "paused"
        if not s.autonomous_enabled:
            return "autonomy_off"
        if self.world.asleep:
            return "sleeping"
        ai = self.client.status
        if ai == "not_configured":
            return "needs_key"
        if ai in ("invalid_key", "disconnected"):
            return "disconnected"
        if ai == "budget_paused":
            return "budget_paused"
        return "active"

    def snapshot(self) -> dict:
        with self.lock:
            w = self.world
            env = w.env
            s = self.settings.get()
            status = self.status()
            travel = None
            if w.travel:
                a, b, t = w.travel_progress()
                travel = {"from": a, "to": b, "t": t, "destination": w.travel.path[-1]}
            return {
                "status": status,
                "status_text": STATUS_TEXT.get(status, status),
                "ai_status": self.client.status,
                "ai_detail": self.client.status_detail,
                "thinking": self.cognition.in_flight is not None,
                "day": env.day,
                "clock": env.clock_label,
                "hour": env.hour,
                "time_of_day": env.time_of_day,
                "light": env.light_level,
                "weather": env.weather,
                "temperature": env.temperature,
                "location": w.location,
                "place_name": w.place_name,
                "activity": w.activity_label(),
                "activity_progress": w.activity.progress if w.activity else None,
                "travel": travel,
                "position": w.position(),
                "asleep": w.asleep,
                "needs": w.needs.to_dict(),
                "need_labels": w.needs.labels(),
                "mood": self.character.mood,
                "thought": dict(self.last_thought) if self.last_thought else None,
                "events": list(self.recent_events)[-40:],
                "highlight": dict(self.highlights[0]) if self.highlights else None,
                "plan": [st.label or st.action for st in w.plan],
                "unread_notes": int(self.db.scalar("SELECT COUNT(*) FROM visitor_notes WHERE read_at IS NULL", (), 0)),
                "pending_approvals": int(self.db.scalar("SELECT COUNT(*) FROM outbox WHERE status='pending'", (), 0)),
                "spent_today": self.ledger.spent_today(),
                "budget": s.daily_budget_usd,
                "next_decision_in": self.cognition.seconds_until_next(),
                "paused": s.paused,
                "autonomous": s.autonomous_enabled,
                "emergency_stopped": s.emergency_stopped,
                "time_scale": s.time_scale,
                "displayed_creations": int(self.db.scalar("SELECT COUNT(*) FROM creations WHERE displayed=1", (), 0)),
            }

    # -- persistence -------------------------------------------------------------------------
    def save(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.db.kv_set("world_state", self.world.to_dict())
            self.character.save()
            self._last_save = self.mono()

    def shutdown(self, timeout: float = 5.0) -> None:
        if self.closed:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self.client.halt()
        self.jobs.shutdown()
        with self.lock:
            self.save()
            self.db.kv_set("clean_shutdown", True)
            self.db.kv_set("last_shutdown", self.wall())
            self.closed = True
            self.db.close()
        log.info("Kimi's world saved; shutdown complete")
