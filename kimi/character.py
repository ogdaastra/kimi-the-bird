"""Kimi's persistent character sheet.

The base temperament is stable; interests, preferences, opinions and goals
develop slowly through experience. Trait drift is bounded so Kimi stays
recognisably itself.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

from .memory.text import keywords
from .safety import clean_text

MOODS = (
    "content", "cheerful", "curious", "playful", "calm", "sleepy", "thoughtful",
    "wistful", "proud", "delighted", "grumpy", "lonely", "peaceful", "excited",
)

MOOD_VALENCE = {
    "content": 0.4, "cheerful": 0.7, "curious": 0.5, "playful": 0.6, "calm": 0.3, "sleepy": 0.0,
    "thoughtful": 0.2, "wistful": -0.1, "proud": 0.7, "delighted": 0.9, "grumpy": -0.5,
    "lonely": -0.4, "peaceful": 0.5, "excited": 0.8,
}

DEFAULT_SHEET: dict[str, Any] = {
    "name": "Kimi",
    "species": "a tiny round wren with slate-blue feathers and a peach-coloured chest",
    "born_day": 1,
    "traits": {
        "curious": 0.80,
        "gentle": 0.72,
        "independent": 0.75,
        "playful": 0.58,
        "contemplative": 0.66,
        "shy with strangers": 0.45,
        "brave": 0.40,
    },
    "interests": {
        "moss and tiny plants": {"strength": 0.55, "since_day": 1, "source": "innate"},
        "clouds and weather": {"strength": 0.45, "since_day": 1, "source": "innate"},
        "old maps": {"strength": 0.30, "since_day": 1, "source": "innate"},
    },
    "location_affinity": {"nest": 0.6, "shrub": 0.55, "shrine": 0.4, "library": 0.4},
    "activity_affinity": {"explore": 0.5, "observe": 0.4, "create_art": 0.4},
    "food_preferences": {"blackberry tart": 0.3},
    "weather_feelings": {},
    "mood": {"label": "content", "since": 0.0},
    "opinions": [],
    "goals": [
        {"text": "Find out what lives deep inside the Shrub", "status": "active", "progress": 0, "since_day": 1},
        {"text": "Fill a sketchbook with ten drawings", "status": "active", "progress": 0, "target": 10, "since_day": 1},
    ],
    "trait_drift_today": {},
    "drift_day": 1,
}

MAX_INTERESTS = 14
MAX_OPINIONS = 30
MAX_ACTIVE_GOALS = 5
MAX_DAILY_TRAIT_DRIFT = 0.02


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _norm_topic(topic: str) -> str:
    return clean_text(topic, 60).strip(" .!?,;:").lower()


class CharacterSheet:
    KV_KEY = "character_sheet"

    def __init__(self, db) -> None:
        self.db = db
        self.lock = threading.RLock()
        stored = db.kv_get(self.KV_KEY)
        if isinstance(stored, dict):
            data = copy.deepcopy(DEFAULT_SHEET)
            data.update(stored)
            self.data = data
        else:
            self.data = copy.deepcopy(DEFAULT_SHEET)
            self.save()

    def save(self) -> None:
        with self.lock:
            self.db.kv_set(self.KV_KEY, self.data)

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.data)

    # -- basics -----------------------------------------------------------
    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def mood(self) -> str:
        return self.data["mood"]["label"]

    def set_mood(self, label: str | None) -> bool:
        if label not in MOODS:
            return False
        with self.lock:
            if self.data["mood"]["label"] != label:
                self.data["mood"] = {"label": label, "since": time.time()}
            return True

    # -- interests ----------------------------------------------------------
    def nudge_interest(self, topic: str, delta: float, source: str, day: int) -> str | None:
        t = _norm_topic(topic)
        if len(t) < 2:
            return None
        with self.lock:
            interests = self.data["interests"]
            if t not in interests:
                # "Mosses" and "moss" reinforce the existing "moss and tiny plants".
                new_kws = set(keywords(t))
                for existing in interests:
                    old_kws = set(keywords(existing))
                    if new_kws and old_kws and (new_kws <= old_kws or old_kws <= new_kws):
                        t = existing
                        break
            if t in interests:
                interests[t]["strength"] = round(_clamp(interests[t]["strength"] + delta), 3)
            else:
                if delta <= 0:
                    return None
                interests[t] = {"strength": round(_clamp(0.2 + delta), 3), "since_day": day, "source": source}
                if len(interests) > MAX_INTERESTS:
                    weakest = min(interests, key=lambda k: interests[k]["strength"])
                    del interests[weakest]
            return t

    def decay_interests(self, factor: float = 0.97) -> None:
        with self.lock:
            for topic in list(self.data["interests"]):
                info = self.data["interests"][topic]
                info["strength"] = round(info["strength"] * factor, 3)
                if info["strength"] < 0.08 and info.get("source") != "innate":
                    del self.data["interests"][topic]

    def top_interests(self, n: int = 5) -> list[tuple[str, float]]:
        items = sorted(self.data["interests"].items(), key=lambda kv: kv[1]["strength"], reverse=True)
        return [(k, v["strength"]) for k, v in items[:n]]

    def developing_interests(self, current_day: int, n: int = 4) -> list[tuple[str, float]]:
        items = [
            (k, v["strength"]) for k, v in self.data["interests"].items()
            if v.get("source") != "innate" and current_day - v.get("since_day", current_day) <= 7
        ]
        items.sort(key=lambda kv: kv[1], reverse=True)
        return items[:n]

    # -- preferences -------------------------------------------------------
    def _bump(self, table: str, key: str, delta: float) -> None:
        with self.lock:
            prefs = self.data.setdefault(table, {})
            prefs[key] = round(_clamp(prefs.get(key, 0.3) + delta, -1.0, 1.0), 3)

    def record_location_feeling(self, location: str, delta: float) -> None:
        self._bump("location_affinity", location, delta)

    def record_activity_outcome(self, activity: str, delta: float) -> None:
        self._bump("activity_affinity", activity, delta)

    def record_food(self, food: str, delta: float) -> None:
        self._bump("food_preferences", _norm_topic(food), delta)

    def record_weather_feeling(self, weather: str, delta: float) -> None:
        self._bump("weather_feelings", weather, delta)

    def food_score(self, food: str) -> float:
        return self.data.get("food_preferences", {}).get(_norm_topic(food), 0.3)

    @property
    def likes_rain(self) -> bool:
        feelings = self.data.get("weather_feelings", {})
        return max(feelings.get("rain", 0), feelings.get("drizzle", 0)) > 0.45

    def favourites(self, table: str, n: int = 3) -> list[str]:
        prefs = self.data.get(table, {})
        return [k for k, v in sorted(prefs.items(), key=lambda kv: kv[1], reverse=True)[:n] if v > 0.35]

    # -- traits -------------------------------------------------------------
    def nudge_trait(self, trait: str, delta: float, day: int) -> None:
        with self.lock:
            if self.data.get("drift_day") != day:
                self.data["drift_day"] = day
                self.data["trait_drift_today"] = {}
            drift = self.data["trait_drift_today"]
            used = drift.get(trait, 0.0)
            allowed = MAX_DAILY_TRAIT_DRIFT - abs(used)
            if allowed <= 0:
                return
            delta = max(-allowed, min(allowed, delta))
            traits = self.data["traits"]
            traits[trait] = round(_clamp(traits.get(trait, 0.5) + delta, 0.05, 0.95), 3)
            drift[trait] = used + delta

    # -- opinions and goals -------------------------------------------------
    def add_opinion(self, subject: str, opinion: str, day: int) -> bool:
        subject = clean_text(subject, 60)
        opinion = clean_text(opinion, 200)
        if len(subject) < 2 or len(opinion) < 4:
            return False
        with self.lock:
            ops = [o for o in self.data["opinions"] if o["subject"].lower() != subject.lower()]
            ops.append({"subject": subject, "opinion": opinion, "day": day})
            self.data["opinions"] = ops[-MAX_OPINIONS:]
            return True

    def add_goal(self, text: str, day: int) -> bool:
        text = clean_text(text, 120)
        if len(text) < 5:
            return False
        with self.lock:
            goals = self.data["goals"]
            if any(g["text"].lower() == text.lower() for g in goals):
                return False
            active = [g for g in goals if g["status"] == "active"]
            if len(active) >= MAX_ACTIVE_GOALS:
                return False
            goals.append({"text": text, "status": "active", "progress": 0, "since_day": day})
            self.data["goals"] = goals[-20:]
            return True

    def progress_goal(self, keyword: str, amount: int = 1) -> dict | None:
        """Advance the first active goal mentioning ``keyword``; complete it at its target."""
        with self.lock:
            for g in self.data["goals"]:
                if g["status"] == "active" and keyword.lower() in g["text"].lower():
                    g["progress"] = g.get("progress", 0) + amount
                    if g.get("target") and g["progress"] >= g["target"]:
                        g["status"] = "completed"
                    return dict(g)
        return None

    def complete_goal(self, index: int) -> dict | None:
        with self.lock:
            active = [g for g in self.data["goals"] if g["status"] == "active"]
            if 0 <= index < len(active):
                active[index]["status"] = "completed"
                return dict(active[index])
        return None

    def active_goals(self) -> list[dict]:
        return [dict(g) for g in self.data["goals"] if g["status"] == "active"]

    # -- prompt rendering ---------------------------------------------------
    def prompt_summary(self, current_day: int, location_names: dict[str, str]) -> str:
        with self.lock:
            d = self.data
            traits = ", ".join(
                f"{k} ({v:.2f})" for k, v in sorted(d["traits"].items(), key=lambda kv: kv[1], reverse=True)
            )
            interests = ", ".join(
                f"{t} ({'strong' if s >= 0.6 else 'growing' if s >= 0.35 else 'new'})"
                for t, s in self.top_interests(6)
            ) or "none yet"
            places = ", ".join(location_names.get(p, p) for p in self.favourites("location_affinity")) or "not sure yet"
            acts = ", ".join(self.favourites("activity_affinity")) or "not sure yet"
            foods = ", ".join(self.favourites("food_preferences")) or "not sure yet"
            weather = d.get("weather_feelings", {})
            weather_bits = ", ".join(
                f"{'likes' if v > 0.45 else 'dislikes' if v < 0.1 else 'neutral about'} {k}"
                for k, v in weather.items()
            )
            opinions = "; ".join(f"{o['subject']}: {o['opinion']}" for o in d["opinions"][-5:]) or "none yet"
            goals = "; ".join(
                f"{g['text']}" + (f" [{g.get('progress', 0)}/{g['target']}]" if g.get("target") else "")
                for g in self.active_goals()
            ) or "none right now"
            lines = [
                f"Traits now: {traits}.",
                f"Interests: {interests}.",
                f"Favourite places: {places}. Favourite activities: {acts}. Favourite foods: {foods}.",
            ]
            if weather_bits:
                lines.append(f"Weather feelings: {weather_bits}.")
            lines.append(f"Opinions: {opinions}.")
            lines.append(f"Personal goals: {goals}.")
            lines.append(f"Kimi has lived in Bramblewick for {max(1, current_day - d.get('born_day', 1) + 1)} day(s).")
            return "\n".join(lines)
