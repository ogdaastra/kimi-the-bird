"""Kimi's world state: where it is, what it's doing, and its plan.

Movement is a journey along the location graph: Kimi walks leg by leg
through connected places and is "on the path" while travelling. It never
teleports.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from . import discoveries
from .environment import WET, Environment
from .locations import HOME, LocationGraph
from .needs import ACTIVITY_CLASS, Needs


@dataclass
class PlanStep:
    action: str
    params: dict = field(default_factory=dict)
    source: str = "mind"           # mind | instinct | fallback | user
    payload: dict = field(default_factory=dict)  # precomputed content/results
    label: str = ""
    log_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "action": self.action, "params": self.params, "source": self.source,
            "payload": self.payload, "label": self.label, "log_id": self.log_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlanStep":
        return cls(
            action=str(d.get("action", "rest")), params=dict(d.get("params") or {}),
            source=str(d.get("source", "mind")), payload=dict(d.get("payload") or {}),
            label=str(d.get("label", "")), log_id=d.get("log_id"),
        )


@dataclass
class Activity:
    step: PlanStep
    location: str
    started_minute: float
    duration: float
    label: str
    elapsed: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.duration - self.elapsed)

    @property
    def progress(self) -> float:
        return 1.0 if self.duration <= 0 else min(1.0, self.elapsed / self.duration)

    def to_dict(self) -> dict:
        return {
            "step": self.step.to_dict(), "location": self.location, "started_minute": self.started_minute,
            "duration": self.duration, "label": self.label, "elapsed": self.elapsed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Activity":
        return cls(
            step=PlanStep.from_dict(d["step"]), location=d["location"],
            started_minute=float(d.get("started_minute", 0)), duration=float(d.get("duration", 10)),
            label=str(d.get("label", "")), elapsed=float(d.get("elapsed", 0)),
        )


@dataclass
class Travel:
    path: list[str]
    step: PlanStep
    leg: int = 0
    leg_elapsed: float = 0.0

    def to_dict(self) -> dict:
        return {"path": self.path, "step": self.step.to_dict(), "leg": self.leg, "leg_elapsed": self.leg_elapsed}

    @classmethod
    def from_dict(cls, d: dict) -> "Travel":
        return cls(path=list(d["path"]), step=PlanStep.from_dict(d["step"]),
                   leg=int(d.get("leg", 0)), leg_elapsed=float(d.get("leg_elapsed", 0)))


@dataclass
class WorldEvent:
    kind: str                     # weather | time | passed | arrived | activity_done
    text: str = ""
    location: str | None = None
    data: Any = None


class World:
    def __init__(self, graph: LocationGraph | None = None, env: Environment | None = None,
                 needs: Needs | None = None, location: str = HOME, rng: random.Random | None = None) -> None:
        self.graph = graph or LocationGraph()
        self.env = env or Environment()
        self.needs = needs or Needs()
        self.location: str | None = location
        self.travel: Travel | None = None
        self.activity: Activity | None = None
        self.plan: list[PlanStep] = []
        self.asleep = False
        self.likes_rain = False
        self.rng = rng or random.Random()

    # -- state ----------------------------------------------------------
    @property
    def busy(self) -> bool:
        return bool(self.travel or self.activity or self.plan)

    @property
    def state_label(self) -> str:
        if self.asleep:
            return "sleeping"
        if self.travel:
            return "travelling"
        if self.activity:
            return "busy"
        return "idle"

    @property
    def place_name(self) -> str:
        if self.travel:
            a, b, _ = self.travel_progress()
            return f"on the path from {self.graph.name(a)} to {self.graph.name(b)}"
        return self.graph.name(self.location)

    @property
    def destination(self) -> str | None:
        return self.travel.path[-1] if self.travel else None

    def activity_label(self) -> str:
        if self.asleep:
            return "sleeping"
        if self.travel:
            return f"walking to {self.graph.name(self.travel.path[-1])}"
        if self.activity:
            return self.activity.label
        return "pottering about"

    def travel_progress(self) -> tuple[str, str, float]:
        assert self.travel is not None
        a = self.travel.path[self.travel.leg]
        b = self.travel.path[self.travel.leg + 1]
        leg_minutes = self.graph.adj[a][b]
        return a, b, min(1.0, self.travel.leg_elapsed / max(1e-6, leg_minutes))

    def position(self) -> tuple[float, float]:
        if self.travel:
            a, b, t = self.travel_progress()
            ax, ay = self.graph.get(a).position
            bx, by = self.graph.get(b).position
            return ax + (bx - ax) * t, ay + (by - ay) * t
        return self.graph.get(self.location or HOME).position

    # -- plan -----------------------------------------------------------
    def enqueue(self, steps: list[PlanStep]) -> None:
        self.plan.extend(steps)

    def clear_plan(self) -> list[PlanStep]:
        dropped = list(self.plan)
        self.plan.clear()
        return dropped

    def begin_travel(self, destination: str, step: PlanStep) -> int:
        """Start walking. Returns total minutes (0 if already there)."""
        if self.location is None:
            raise RuntimeError("Already travelling")
        path, minutes = self.graph.shortest_path(self.location, destination)
        if len(path) < 2:
            return 0
        self.activity = None
        self.travel = Travel(path=path, step=step)
        self.location = None
        return minutes

    def begin_activity(self, step: PlanStep, duration: float, label: str) -> Activity:
        self.activity = Activity(step=step, location=self.location or HOME,
                                 started_minute=self.env.minute, duration=max(1.0, duration), label=label)
        return self.activity

    def interrupt(self) -> list[PlanStep]:
        """Stop everything immediately (emergency stop). Kimi stays where it is."""
        dropped = self.clear_plan()
        if self.activity:
            dropped.insert(0, self.activity.step)
            self.activity = None
        if self.travel:
            # Stop at the nearest end of the current leg rather than mid-air.
            a, b, t = self.travel_progress()
            self.location = b if t >= 0.5 else a
            dropped.insert(0, self.travel.step)
            self.travel = None
        self.asleep = False
        return dropped

    # -- simulation -------------------------------------------------------
    def current_activity_class(self) -> str:
        if self.asleep:
            return "sleep"
        if self.travel:
            return "travel"
        if self.activity:
            return ACTIVITY_CLASS.get(self.activity.step.action, "idle")
        return "idle"

    def tick(self, minutes: float) -> list[WorldEvent]:
        events: list[WorldEvent] = [WorldEvent(kind, text) for kind, text in self.env.advance(minutes, self.rng)]
        activity_class = self.current_activity_class()

        if self.travel:
            remaining = minutes
            while self.travel and remaining > 0:
                a = self.travel.path[self.travel.leg]
                b = self.travel.path[self.travel.leg + 1]
                leg_minutes = self.graph.adj[a][b]
                need = leg_minutes - self.travel.leg_elapsed
                if remaining < need:
                    self.travel.leg_elapsed += remaining
                    remaining = 0
                    break
                remaining -= need
                self.travel.leg += 1
                self.travel.leg_elapsed = 0.0
                if self.travel.leg >= len(self.travel.path) - 1:
                    step = self.travel.step
                    self.location = b
                    self.travel = None
                    events.append(WorldEvent("arrived", f"Arrived at {self.graph.name(b)}.", b, step))
                else:
                    events.append(WorldEvent("passed", f"Passed through {self.graph.name(b)}.", b))
        elif self.activity:
            self.activity.elapsed += minutes
            if self.activity.elapsed >= self.activity.duration:
                done = self.activity
                self.activity = None
                events.append(WorldEvent("activity_done", "", done.location, done))

        place = self.location
        outdoors = place is None or not self.graph.get(place).indoor
        self.needs.tick(
            minutes,
            activity_class,
            with_company=discoveries.has_company(place, self.env.is_night),
            outdoors_in_bad_weather=outdoors and self.env.weather in WET and not self.asleep,
            likes_rain=self.likes_rain,
        )
        return events

    # -- persistence ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "env": self.env.to_dict(),
            "needs": self.needs.to_dict(),
            "location": self.location,
            "travel": self.travel.to_dict() if self.travel else None,
            "activity": self.activity.to_dict() if self.activity else None,
            "plan": [s.to_dict() for s in self.plan],
            "asleep": self.asleep,
        }

    @classmethod
    def from_dict(cls, d: dict, rng: random.Random | None = None) -> "World":
        graph = LocationGraph()
        w = cls(graph=graph, env=Environment.from_dict(d.get("env", {})),
                needs=Needs.from_dict(d.get("needs", {})), location=d.get("location") or HOME, rng=rng)
        if d.get("location") is None and d.get("travel"):
            try:
                w.travel = Travel.from_dict(d["travel"])
                w.location = None
            except (KeyError, TypeError, ValueError, AttributeError):
                w.travel = None
                w.location = HOME
        if w.location is not None and w.location not in graph:
            w.location = HOME
        if d.get("activity"):
            try:
                w.activity = Activity.from_dict(d["activity"])
            except (KeyError, TypeError, ValueError, AttributeError):
                w.activity = None
        w.plan = []
        for s in d.get("plan") or []:
            try:
                w.plan.append(PlanStep.from_dict(s))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        w.asleep = bool(d.get("asleep", False))
        return w
