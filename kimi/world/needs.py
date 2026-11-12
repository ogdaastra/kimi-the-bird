"""Kimi's needs, simulated locally between AI decisions.

All values are 0-100. Hunger and social interest grow over time (higher
means hungrier / more in the mood for company). Energy is spent by activity
and restored by rest and sleep. Curiosity is Kimi's drive to explore and
learn: exploring sparks it, research and creating satisfy it. Happiness
drifts gently towards a comfortable baseline.

Rates are deliberately mild so Kimi never needs constant care.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# Per world-hour rates, by activity class.
_ENERGY = {
    "sleep": +14.0, "rest": +8.0, "eat": +2.0, "idle": -1.5, "social": -2.0,
    "travel": -5.0, "explore": -6.0, "creative": -4.0, "study": -4.0, "reflective": -1.5,
}
_HUNGER = {"sleep": +1.5, "eat": 0.0}
_CURIOSITY = {
    "sleep": -1.0, "rest": +1.5, "idle": +2.0, "social": +1.0, "travel": +1.5,
    "explore": +4.0, "creative": -8.0, "study": -10.0, "reflective": -2.0, "eat": +0.5,
}
_SOCIAL = {"social": -8.0, "sleep": +0.5}

ACTIVITY_CLASS = {
    "sleep": "sleep",
    "rest": "rest",
    "linger": "idle",
    "idle": "idle",
    "continue": "idle",
    "travel": "travel",
    "move_to": "travel",
    "visit_location": "idle",
    "explore": "explore",
    "eat": "eat",
    "observe": "idle",
    "read_note": "social",
    "leave_message": "social",
    "create_art": "creative",
    "write_diary": "reflective",
    "reflect": "reflective",
    "research": "study",
    "share_creation": "creative",
    "examine": "explore",
    "ask_human": "reflective",
}

# Happiness and curiosity have soft limits: a boost does less the higher the value already is
# (and a drain less the lower it is), so they move around the middle instead of sitting at 0 or 100.
SOFT = ("happiness", "curiosity")


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


@dataclass
class Needs:
    hunger: float = 25.0
    energy: float = 80.0
    curiosity: float = 60.0
    happiness: float = 65.0
    social: float = 35.0

    def tick(self, minutes: float, activity_class: str = "idle", *, with_company: bool = False,
             outdoors_in_bad_weather: bool = False, likes_rain: bool = False) -> None:
        h = minutes / 60.0
        self.hunger = _clamp(self.hunger + _HUNGER.get(activity_class, 5.0) * h)
        self.energy = _clamp(self.energy + _ENERGY.get(activity_class, -2.0) * h)
        curiosity_drift = (55.0 - self.curiosity) * 0.04 * h   # gently back towards a natural level
        self.curiosity = _clamp(self.curiosity + _CURIOSITY.get(activity_class, 1.0) * h + curiosity_drift)
        social_rate = _SOCIAL.get(activity_class, 2.0)
        if with_company and activity_class not in ("sleep",):
            social_rate = min(social_rate, -4.0)
        self.social = _clamp(self.social + social_rate * h)

        # Happiness: mean reversion towards 62 plus gentle pressures.
        target = 62.0
        delta = (target - self.happiness) * 0.08 * h
        if self.hunger > 85:
            delta -= 2.0 * h
        if self.energy < 12:
            delta -= 2.0 * h
        if self.social > 88:
            delta -= 1.0 * h
        if outdoors_in_bad_weather:
            delta += (1.0 if likes_rain else -1.5) * h
        self.happiness = _clamp(self.happiness + delta)

    def adjust(self, **changes: float) -> None:
        for name, delta in changes.items():
            value = getattr(self, name)
            if name in SOFT:
                room = (100.0 - value) if delta > 0 else value
                delta *= min(1.0, room / 50.0)
            setattr(self, name, _clamp(value + delta))

    def labels(self) -> dict[str, str]:
        def band(v: float, words: tuple[str, str, str, str, str]) -> str:
            return words[min(4, int(v // 20))]

        return {
            "hunger": band(self.hunger, ("full", "satisfied", "peckish", "hungry", "very hungry")),
            "energy": band(self.energy, ("exhausted", "tired", "fine", "lively", "full of energy")),
            "curiosity": band(self.curiosity, ("incurious", "mildly curious", "curious", "very curious", "bursting with curiosity")),
            "happiness": band(self.happiness, ("low", "a bit flat", "okay", "content", "joyful")),
            "social": band(self.social, ("wanting solitude", "content alone", "open to company", "wanting company", "lonely")),
        }

    def to_dict(self) -> dict:
        return {k: round(v, 2) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: dict) -> "Needs":
        n = cls()
        for k in asdict(n):
            if k in d:
                try:
                    setattr(n, k, _clamp(float(d[k])))
                except (TypeError, ValueError):
                    pass
        return n
