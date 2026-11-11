"""World clock, day/night cycle and weather - all simulated locally."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

MINUTES_PER_DAY = 1440

WEATHER_STATES = ("sunny", "cloudy", "breezy", "drizzle", "rain", "foggy", "snow")
WEATHER_LABELS = {
    "sunny": "sunny",
    "cloudy": "cloudy",
    "breezy": "breezy",
    "drizzle": "light drizzle",
    "rain": "rain",
    "foggy": "foggy",
    "snow": "light snow",
}
_TRANSITIONS = {
    "sunny":   {"sunny": 0.62, "cloudy": 0.2, "breezy": 0.15, "foggy": 0.03},
    "cloudy":  {"cloudy": 0.45, "sunny": 0.22, "drizzle": 0.15, "breezy": 0.1, "foggy": 0.05, "rain": 0.03},
    "breezy":  {"breezy": 0.45, "sunny": 0.25, "cloudy": 0.25, "drizzle": 0.05},
    "drizzle": {"drizzle": 0.4, "rain": 0.2, "cloudy": 0.3, "foggy": 0.1},
    "rain":    {"rain": 0.45, "drizzle": 0.35, "cloudy": 0.2},
    "foggy":   {"foggy": 0.4, "cloudy": 0.35, "sunny": 0.15, "drizzle": 0.1},
    "snow":    {"snow": 0.5, "cloudy": 0.4, "foggy": 0.1},
}
WET = {"drizzle", "rain", "snow"}


def time_of_day_label(hour: float) -> str:
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


@dataclass
class Environment:
    minute: float = 8 * 60.0          # world minutes since Day 1 00:00 (Kimi starts at 08:00)
    weather: str = "sunny"
    temperature: float = 14.0
    _last_weather_hour: int = -1

    # -- clock ----------------------------------------------------------
    @property
    def day(self) -> int:
        return int(self.minute // MINUTES_PER_DAY) + 1

    @property
    def minute_of_day(self) -> float:
        return self.minute % MINUTES_PER_DAY

    @property
    def hour(self) -> float:
        return self.minute_of_day / 60.0

    @property
    def clock_label(self) -> str:
        m = int(self.minute_of_day)
        return f"{m // 60:02d}:{m % 60:02d}"

    @property
    def time_of_day(self) -> str:
        return time_of_day_label(self.hour)

    @property
    def is_night(self) -> bool:
        return self.hour >= 21.5 or self.hour < 5.5

    @property
    def light_level(self) -> float:
        """0 = darkest night, 1 = full daylight (smooth for the UI)."""
        h = self.hour
        # Sunrise ~6:00, sunset ~20:00, smooth transitions.
        if 7 <= h <= 19:
            return 1.0
        if 5 <= h < 7:
            return 0.15 + 0.85 * (h - 5) / 2
        if 19 < h <= 21:
            return 1.0 - 0.85 * (h - 19) / 2
        return 0.15

    def minutes_until(self, hour: float) -> float:
        target = hour * 60
        now = self.minute_of_day
        delta = target - now
        if delta <= 0:
            delta += MINUTES_PER_DAY
        return delta

    def describe(self) -> str:
        return (
            f"Day {self.day}, {self.clock_label} ({self.time_of_day}). "
            f"Weather: {WEATHER_LABELS.get(self.weather, self.weather)}, {self.temperature:.0f}°C."
        )

    # -- simulation -------------------------------------------------------
    def _base_temperature(self) -> float:
        # Gentle seasonal wave over a 28-day cycle plus a daily curve.
        season = 11 + 7 * math.sin(2 * math.pi * (self.day % 28) / 28)
        daily = 4 * math.sin(2 * math.pi * (self.hour - 9) / 24)
        return season + daily

    def advance(self, minutes: float, rng: random.Random) -> list[tuple[str, str]]:
        """Advance the clock. Returns (kind, text) events."""
        events: list[tuple[str, str]] = []
        before_tod = self.time_of_day
        before_day = self.day
        self.minute += minutes
        hour_index = int(self.minute // 60)
        if self._last_weather_hour < 0:
            self._last_weather_hour = hour_index
        while self._last_weather_hour < hour_index:
            self._last_weather_hour += 1
            new = self._next_weather(rng)
            if new != self.weather:
                self.weather = new
                events.append(("weather", _weather_change_text(new)))
        target = self._base_temperature() + (-2 if self.weather in WET else 0) + (-1 if self.weather == "foggy" else 0)
        self.temperature += (target - self.temperature) * min(1.0, minutes / 90.0)
        if self.weather == "snow" and self.temperature > 3:
            self.weather = "drizzle"
        if self.day != before_day:
            events.append(("time", f"A new day begins in Bramblewick: Day {self.day}."))
        tod = self.time_of_day
        if tod != before_tod:
            text = {
                "dawn": "The sky is turning pale; dawn is coming.",
                "morning": "Morning light spills over the rooftops.",
                "afternoon": "The afternoon settles in.",
                "evening": "Evening shadows grow long and lanterns flicker on.",
                "night": "Night falls over Bramblewick and the stars come out.",
            }[tod]
            events.append(("time", text))
        return events

    def _next_weather(self, rng: random.Random) -> str:
        table = dict(_TRANSITIONS.get(self.weather, _TRANSITIONS["cloudy"]))
        if self.temperature < 2 and self.weather in ("cloudy", "drizzle"):
            table["snow"] = table.get("snow", 0) + 0.25
        states, weights = zip(*table.items())
        return rng.choices(states, weights=weights, k=1)[0]

    def to_dict(self) -> dict:
        return {
            "minute": self.minute,
            "weather": self.weather,
            "temperature": self.temperature,
            "last_weather_hour": self._last_weather_hour,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Environment":
        env = cls(
            minute=float(d.get("minute", 8 * 60)),
            weather=d.get("weather", "sunny") if d.get("weather") in WEATHER_STATES else "sunny",
            temperature=float(d.get("temperature", 14.0)),
        )
        env._last_weather_hour = int(d.get("last_weather_hour", -1))
        return env


def _weather_change_text(weather: str) -> str:
    return {
        "sunny": "The clouds part and sunshine warms the cobbles.",
        "cloudy": "Soft grey clouds drift over the town.",
        "breezy": "A breeze picks up, rustling the Shrub's leaves.",
        "drizzle": "A light drizzle begins to fall.",
        "rain": "It's raining properly now; puddles gather in the square.",
        "foggy": "Fog rolls in and softens everything.",
        "snow": "Tiny snowflakes start drifting down.",
    }.get(weather, f"The weather turns {weather}.")
