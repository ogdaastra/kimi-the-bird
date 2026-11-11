"""Paths and user-adjustable settings.

Settings are ordinary, non-secret configuration and are stored in Kimi's
SQLite database. The Anthropic API key is deliberately *not* a setting: it
lives only in Windows Credential Manager (see ``kimi.credentials``).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_data_root() -> Path:
    """Where Kimi keeps its world. Override with the KIMI_HOME variable."""
    env = os.environ.get("KIMI_HOME")
    return Path(env).expanduser() if env else PROJECT_ROOT / "data"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def db(self) -> Path:
        return self.root / "kimi.db"

    @property
    def visitors(self) -> Path:
        return self.root / "visitors"

    @property
    def inbox(self) -> Path:
        return self.visitors / "inbox"

    @property
    def archive(self) -> Path:
        return self.visitors / "archive"

    @property
    def rejected(self) -> Path:
        return self.visitors / "rejected"

    @property
    def creations(self) -> Path:
        return self.root / "creations"

    @property
    def diary(self) -> Path:
        return self.root / "diary"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def lock_file(self) -> Path:
        return self.root / "kimi.lock"

    def ensure(self) -> "Paths":
        for p in (
            self.root,
            self.inbox,
            self.archive,
            self.rejected,
            self.creations,
            self.diary,
            self.logs,
        ):
            p.mkdir(parents=True, exist_ok=True)
        return self


EFFORT_LEVELS = ("low", "medium", "high")


@dataclass
class Settings:
    # --- Autonomy -------------------------------------------------------
    autonomous_enabled: bool = True
    emergency_stopped: bool = False
    paused: bool = False

    # --- Pacing (real seconds) -----------------------------------------
    decision_min_interval_s: int = 180   # never ask Haiku more often than this
    decision_max_interval_s: int = 1200  # adaptive idle ceiling
    min_request_gap_s: float = 2.0       # hard floor between any two API requests
    time_scale: float = 4.0              # world minutes per real minute

    # --- Cost controls --------------------------------------------------
    daily_budget_usd: float = 0.25
    max_requests_per_day: int = 300
    max_input_tokens: int = 6000         # maximum estimated request size
    decision_max_tokens: int = 2000      # maximum response size per call type
    reflection_max_tokens: int = 2500
    research_max_tokens: int = 1200
    vision_max_tokens: int = 800
    decision_effort: str = "low"
    reflection_effort: str = "medium"
    max_retries: int = 4

    # Pricing is an *estimate* the user can edit when Anthropic's prices change.
    price_input_per_mtok: float = 0.10
    price_output_per_mtok: float = 0.50
    price_input_long_per_mtok: float = 0.50
    price_output_long_per_mtok: float = 2.50
    long_context_threshold_tokens: int = 100_000
    cache_read_multiplier: float = 0.1
    cache_write_5m_multiplier: float = 1.25
    cache_write_1h_multiplier: float = 2.0

    # --- Features -------------------------------------------------------
    research_enabled: bool = True
    research_daily_limit: int = 6
    research_contact: str = ""           # optional contact appended to User-Agent
    vision_enabled: bool = True
    external_sharing_enabled: bool = False  # drafts only; sending always needs approval
    github_remote_url: str = ""
    inbox_poll_s: float = 5.0

    # --- Appearance -----------------------------------------------------
    ui_theme: str = "system"             # system | light | dark
    reduce_motion: bool = False


_RANGES: dict[str, tuple[float, float]] = {
    "decision_min_interval_s": (30, 6 * 3600),
    "decision_max_interval_s": (60, 24 * 3600),
    "min_request_gap_s": (0.5, 600),
    "time_scale": (0.5, 60),
    "daily_budget_usd": (0.0, 100.0),
    "max_requests_per_day": (0, 5000),
    "max_input_tokens": (1000, 50_000),
    "decision_max_tokens": (256, 8000),
    "reflection_max_tokens": (256, 8000),
    "research_max_tokens": (256, 8000),
    "vision_max_tokens": (128, 4000),
    "max_retries": (0, 8),
    "price_input_per_mtok": (0.0, 1000.0),
    "price_output_per_mtok": (0.0, 1000.0),
    "price_input_long_per_mtok": (0.0, 1000.0),
    "price_output_long_per_mtok": (0.0, 1000.0),
    "long_context_threshold_tokens": (1000, 10_000_000),
    "cache_read_multiplier": (0.0, 10.0),
    "cache_write_5m_multiplier": (0.0, 10.0),
    "cache_write_1h_multiplier": (0.0, 10.0),
    "research_daily_limit": (0, 50),
    "inbox_poll_s": (1.0, 600.0),
}

# Names that must never be stored as settings, as a guard against a future
# change accidentally persisting a secret in SQLite.
_FORBIDDEN_SETTING_WORDS = ("api_key", "apikey", "access_token", "auth_token", "secret", "password", "credential")


def _coerce(name: str, value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int):
        value = int(float(value))
    elif isinstance(default, float):
        value = float(value)
    elif isinstance(default, str):
        value = str(value)
    if name in _RANGES:
        lo, hi = _RANGES[name]
        value = type(default)(min(max(value, lo), hi))
    if name in ("decision_effort", "reflection_effort") and value not in EFFORT_LEVELS:
        value = default
    if name == "ui_theme" and value not in ("system", "light", "dark"):
        value = default
    return value


def validate_settings(s: Settings) -> Settings:
    defaults = Settings()
    values = {}
    for f in fields(Settings):
        try:
            values[f.name] = _coerce(f.name, getattr(s, f.name), getattr(defaults, f.name))
        except (TypeError, ValueError):
            values[f.name] = getattr(defaults, f.name)
    out = Settings(**values)
    if out.decision_max_interval_s < out.decision_min_interval_s:
        out.decision_max_interval_s = out.decision_min_interval_s
    return out


class SettingsStore:
    """Thread-safe settings persisted in the ``settings`` table."""

    def __init__(self, db) -> None:
        self._db = db
        self._lock = threading.RLock()
        self._settings = self._load()

    def _load(self) -> Settings:
        defaults = Settings()
        known = {f.name for f in fields(Settings)}
        values = asdict(defaults)
        for row in self._db.query("SELECT key, value FROM settings"):
            if row["key"] in known:
                try:
                    values[row["key"]] = json.loads(row["value"])
                except (TypeError, ValueError):
                    pass
        return validate_settings(Settings(**values))

    def get(self) -> Settings:
        with self._lock:
            return replace(self._settings)

    def update(self, **changes: Any) -> Settings:
        known = {f.name for f in fields(Settings)}
        for key in changes:
            if key not in known:
                raise KeyError(f"Unknown setting: {key}")
            if any(word in key.lower() for word in _FORBIDDEN_SETTING_WORDS):
                raise ValueError("Secrets must never be stored as settings")
        with self._lock:
            new = validate_settings(replace(self._settings, **changes))
            with self._db.transaction():
                for key in changes:
                    self._db.execute(
                        "INSERT INTO settings(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(getattr(new, key))),
                    )
            self._settings = new
            return replace(new)

    def reset(self) -> Settings:
        with self._lock:
            self._db.execute("DELETE FROM settings")
            self._settings = Settings()
            return replace(self._settings)
