"""Long-term memory: experiences important or recurring enough to keep."""

from __future__ import annotations

import json
import time
from typing import Callable

from ..safety import clean_text
from .models import ACTIVE, Memory
from .text import keywords


class LongTermMemory:
    def __init__(self, db, wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.wall = wall

    def promote(self, memory_id: int, importance_boost: float = 0.0) -> None:
        self.db.execute(
            "UPDATE memories SET tier='long', promoted_at=?, importance=MIN(1.0, importance+?) "
            "WHERE id=? AND tier='short'",
            (self.wall(), importance_boost, memory_id),
        )

    def add(self, description: str, *, category: str, sim_minute: float, location: str | None = None,
            visitor: str | None = None, importance: float = 0.6, valence: float = 0.0,
            intensity: float = 0.3, recurrence: int = 1, source_ids: list[int] | None = None) -> Memory:
        description = clean_text(description, 800)
        now = self.wall()
        cur = self.db.execute(
            "INSERT INTO memories(tier, created_at, sim_minute, description, location, category, visitor, "
            "importance, valence, intensity, recurrence, keywords, last_seen_at, promoted_at, consolidated, source_ids) "
            "VALUES('long',?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (now, sim_minute, description, location, category, visitor, max(0.0, min(1.0, importance)),
             valence, intensity, recurrence, " ".join(keywords(description)), now, now,
             json.dumps(source_ids or [])),
        )
        return self.get(cur.lastrowid)

    def upsert_relationship(self, visitor_key: str, description: str, *, sim_minute: float,
                            location: str | None, recurrence: int, importance: float) -> Memory:
        row = self.db.query_one(
            f"SELECT id FROM memories WHERE tier='long' AND category='relationship' AND visitor=? AND {ACTIVE}",
            (visitor_key,),
        )
        if row is None:
            return self.add(description, category="relationship", sim_minute=sim_minute, location=location,
                            visitor=visitor_key, importance=importance, valence=0.5, intensity=0.5,
                            recurrence=recurrence)
        self.db.execute(
            "UPDATE memories SET description=?, keywords=?, recurrence=?, importance=MAX(importance, ?), "
            "last_seen_at=?, location=COALESCE(?, location) WHERE id=?",
            (clean_text(description, 800), " ".join(keywords(description)), recurrence, importance,
             self.wall(), location, row["id"]),
        )
        return self.get(row["id"])

    def get(self, memory_id: int) -> Memory:
        row = self.db.query_one("SELECT * FROM memories WHERE id=?", (memory_id,))
        if row is None:
            raise KeyError(memory_id)
        return Memory.from_row(row)

    def all(self, limit: int = 200) -> list[Memory]:
        rows = self.db.query(
            f"SELECT * FROM memories WHERE tier='long' AND {ACTIVE} ORDER BY importance DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [Memory.from_row(r) for r in rows]

    def recent(self, limit: int = 50) -> list[Memory]:
        rows = self.db.query(
            f"SELECT * FROM memories WHERE tier='long' AND {ACTIVE} ORDER BY COALESCE(promoted_at, created_at) DESC LIMIT ?",
            (limit,),
        )
        return [Memory.from_row(r) for r in rows]

    def important_experiences(self, limit: int = 10) -> list[Memory]:
        rows = self.db.query(
            f"SELECT * FROM memories WHERE tier='long' AND {ACTIVE} AND category != 'relationship' "
            "ORDER BY (importance + 0.5*intensity) DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [Memory.from_row(r) for r in rows]

    def about_visitor(self, visitor_key: str, limit: int = 10) -> list[Memory]:
        rows = self.db.query(
            f"SELECT * FROM memories WHERE {ACTIVE} AND visitor=? ORDER BY tier='long' DESC, id DESC LIMIT ?",
            (visitor_key, limit),
        )
        return [Memory.from_row(r) for r in rows]

    def count(self) -> int:
        return int(self.db.scalar(f"SELECT COUNT(*) FROM memories WHERE tier='long' AND {ACTIVE}", (), 0))
