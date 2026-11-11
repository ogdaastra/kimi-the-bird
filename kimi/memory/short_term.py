"""Short-term memory: recent experiences, most of which will fade."""

from __future__ import annotations

import time
from typing import Callable

from ..safety import clean_text
from .models import ACTIVE, Memory
from .text import jaccard, keyword_string, keywords


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


class ShortTermMemory:
    def __init__(self, db, wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.wall = wall

    def add(
        self,
        description: str,
        *,
        category: str,
        sim_minute: float,
        location: str | None = None,
        visitor: str | None = None,
        importance: float = 0.3,
        valence: float = 0.0,
        intensity: float = 0.0,
        dedupe_window_s: float = 6 * 3600,
    ) -> Memory:
        """Record an experience. Near-identical recent experiences bump recurrence instead."""
        description = clean_text(description, 600)
        if not description:
            raise ValueError("Empty memory")
        importance = _clamp(importance, 0.0, 1.0)
        valence = _clamp(valence, -1.0, 1.0)
        intensity = _clamp(intensity, 0.0, 1.0)
        kws = keywords(description)
        now = self.wall()
        with self.db.transaction():
            rows = self.db.query(
                f"SELECT * FROM memories WHERE tier='short' AND {ACTIVE} AND category=? "
                "AND COALESCE(location,'')=? AND COALESCE(visitor,'')=? AND last_seen_at>=? "
                "ORDER BY id DESC LIMIT 20",
                (category, location or "", visitor or "", now - dedupe_window_s),
            )
            for row in rows:
                existing = Memory.from_row(row)
                if jaccard(kws, existing.keywords) >= 0.75:
                    new_importance = min(1.0, max(existing.importance, importance) + 0.03)
                    self.db.execute(
                        "UPDATE memories SET recurrence=recurrence+1, last_seen_at=?, importance=?, "
                        "intensity=MAX(intensity, ?), valence=(valence+?)/2.0 WHERE id=?",
                        (now, new_importance, intensity, valence, existing.id),
                    )
                    return self.get(existing.id)
            cur = self.db.execute(
                "INSERT INTO memories(tier, created_at, sim_minute, description, location, category, visitor, "
                "importance, valence, intensity, recurrence, keywords, last_seen_at) "
                "VALUES('short',?,?,?,?,?,?,?,?,?,1,?,?)",
                (now, sim_minute, description, location, category, visitor, importance, valence,
                 intensity, " ".join(kws), now),
            )
            return self.get(cur.lastrowid)

    def get(self, memory_id: int) -> Memory:
        row = self.db.query_one("SELECT * FROM memories WHERE id=?", (memory_id,))
        if row is None:
            raise KeyError(memory_id)
        return Memory.from_row(row)

    def recent(self, limit: int = 20) -> list[Memory]:
        rows = self.db.query(
            f"SELECT * FROM memories WHERE tier='short' AND {ACTIVE} ORDER BY last_seen_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [Memory.from_row(r) for r in rows]

    def unconsolidated(self) -> list[Memory]:
        rows = self.db.query(
            f"SELECT * FROM memories WHERE tier='short' AND {ACTIVE} AND consolidated=0 ORDER BY id"
        )
        return [Memory.from_row(r) for r in rows]

    def count(self) -> int:
        return int(self.db.scalar(f"SELECT COUNT(*) FROM memories WHERE tier='short' AND {ACTIVE}", (), 0))

    def search(self, text: str, limit: int = 50) -> list[Memory]:
        like = f"%{text.strip()}%"
        rows = self.db.query(
            f"SELECT * FROM memories WHERE {ACTIVE} AND (description LIKE ? OR keywords LIKE ? OR visitor LIKE ?) "
            "ORDER BY id DESC LIMIT ?",
            (like, f"%{keyword_string(text)}%", like, limit),
        )
        return [Memory.from_row(r) for r in rows]
