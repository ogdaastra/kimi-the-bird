"""Relevant-memory retrieval.

Instead of sending the whole database to Haiku, Kimi scores a bounded set
of candidate memories by keyword overlap, importance, recency, recurrence
and context (same place, same visitor) and sends only the best few.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Iterable

from .models import ACTIVE, Memory
from .text import keywords, overlap


class MemoryRetriever:
    W_KEYWORDS = 0.35
    W_IMPORTANCE = 0.25
    W_RECENCY = 0.20
    W_RECURRENCE = 0.10
    W_LOCATION = 0.08
    W_VISITOR = 0.15

    def __init__(self, db, wall: Callable[[], float] = time.time, candidate_limit: int = 400) -> None:
        self.db = db
        self.wall = wall
        self.candidate_limit = candidate_limit

    def _candidates(self) -> list[Memory]:
        rows = self.db.query(
            f"SELECT * FROM memories WHERE tier='short' AND {ACTIVE} ORDER BY last_seen_at DESC LIMIT ?",
            (self.candidate_limit,),
        )
        rows += self.db.query(
            f"SELECT * FROM memories WHERE tier='long' AND {ACTIVE} ORDER BY importance DESC LIMIT ?",
            (self.candidate_limit,),
        )
        return [Memory.from_row(r) for r in rows]

    def score(self, m: Memory, query_kws: list[str], location: str | None, visitors: set[str], now: float) -> float:
        age_h = max(0.0, (now - m.last_seen_at) / 3600.0)
        half_life = 36.0 if m.tier == "short" else 24.0 * 21
        recency = math.exp(-age_h * math.log(2) / half_life)
        rec = min(1.0, math.log1p(max(0, m.recurrence - 1)) / math.log(8))
        s = (
            self.W_KEYWORDS * overlap(query_kws, m.keywords)
            + self.W_IMPORTANCE * m.importance
            + self.W_RECENCY * recency
            + self.W_RECURRENCE * rec
        )
        if location and m.location == location:
            s += self.W_LOCATION
        if m.visitor and m.visitor in visitors:
            s += self.W_VISITOR
        if m.tier == "long":
            s += 0.03
        return s

    def retrieve(self, query_text: str, *, location: str | None = None, visitors: Iterable[str] = (),
                 k: int = 8, exclude_ids: Iterable[int] = (), mark_recalled: bool = True) -> list[Memory]:
        now = self.wall()
        query_kws = keywords(query_text, limit=30)
        vset = set(visitors)
        excluded = set(exclude_ids)
        scored = [
            (self.score(m, query_kws, location, vset, now), m)
            for m in self._candidates()
            if m.id not in excluded
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        chosen: list[Memory] = []
        seen_text: set[str] = set()
        for _, m in scored:
            key = m.description.lower()[:80]
            if key in seen_text:
                continue
            seen_text.add(key)
            chosen.append(m)
            if len(chosen) >= k:
                break
        if mark_recalled and chosen:
            self.db.executemany(
                "UPDATE memories SET last_recalled_at=?, recall_count=recall_count+1 WHERE id=?",
                [(now, m.id) for m in chosen],
            )
        return chosen
