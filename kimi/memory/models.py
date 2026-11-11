"""Memory record shared by both memory tiers."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class Memory:
    id: int
    tier: str
    created_at: float
    sim_minute: float
    description: str
    location: str | None
    category: str
    visitor: str | None
    importance: float
    valence: float
    intensity: float
    recurrence: int
    keywords: list[str] = field(default_factory=list)
    last_seen_at: float = 0.0
    recall_count: int = 0
    source_ids: list[int] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Memory":
        try:
            sources = json.loads(row["source_ids"]) if row["source_ids"] else []
        except (TypeError, ValueError):
            sources = []
        return cls(
            id=row["id"], tier=row["tier"], created_at=row["created_at"], sim_minute=row["sim_minute"],
            description=row["description"], location=row["location"], category=row["category"],
            visitor=row["visitor"], importance=row["importance"], valence=row["valence"],
            intensity=row["intensity"], recurrence=row["recurrence"],
            keywords=(row["keywords"] or "").split(), last_seen_at=row["last_seen_at"],
            recall_count=row["recall_count"], source_ids=sources,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "tier": self.tier, "created_at": self.created_at, "sim_minute": self.sim_minute,
            "description": self.description, "location": self.location, "category": self.category,
            "visitor": self.visitor, "importance": round(self.importance, 3), "valence": round(self.valence, 3),
            "intensity": round(self.intensity, 3), "recurrence": self.recurrence,
        }


ACTIVE = "forgotten=0 AND merged_into IS NULL"
