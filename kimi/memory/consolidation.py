"""Nightly memory consolidation.

Runs locally (no API) for merging, promotion, forgetting and preference
updates. Writing the day's reflection is a separate, optional single Haiku
call made by the runtime; without it a local reflection is written instead.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from .models import ACTIVE, Memory
from .text import jaccard

# Which activity a memory category reflects, for preference learning.
CATEGORY_ACTIVITY = {
    "discovery": "explore",
    "observation": "observe",
    "creation": "create_art",
    "research": "research",
    "diary": "write_diary",
    "reflection": "reflect",
    "food": "eat",
    "visitor": "read_note",
    "rest": "rest",
}


@dataclass
class ConsolidationReport:
    day: int
    reviewed: int = 0
    merged: int = 0
    promoted: int = 0
    forgotten: int = 0
    reinforced: int = 0
    preference_changes: list[str] = field(default_factory=list)
    highlights: list[Memory] = field(default_factory=list)


class MemoryConsolidator:
    MERGE_SIMILARITY = 0.5
    PROMOTE_IMPORTANCE = 0.7
    PROMOTE_RECURRENCE = 3
    PROMOTE_INTENSITY = 0.7
    FORGET_AGE_S = 3 * 86400
    FORGET_IMPORTANCE = 0.25
    MAX_ACTIVE_SHORT = 500

    def __init__(self, db, stm, ltm, character, wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.stm = stm
        self.ltm = ltm
        self.character = character
        self.wall = wall

    @staticmethod
    def _same_context(a: Memory, b: Memory) -> bool:
        return a.category == b.category and a.location == b.location and a.visitor == b.visitor

    def _merge_group(self, group: list[Memory]) -> Memory:
        head = group[0]
        rest = group[1:]
        total = sum(m.recurrence for m in group)
        importance = min(1.0, max(m.importance for m in group) + 0.04 * len(rest))
        intensity = max(m.intensity for m in group)
        valence = sum(m.valence for m in group) / len(group)
        sources = sorted({*head.source_ids, *(m.id for m in rest)})
        self.db.execute(
            "UPDATE memories SET recurrence=?, importance=?, intensity=?, valence=?, source_ids=?, "
            "last_seen_at=MAX(last_seen_at, ?) WHERE id=?",
            (total, importance, intensity, valence, json.dumps(sources),
             max(m.last_seen_at for m in group), head.id),
        )
        self.db.executemany("UPDATE memories SET merged_into=? WHERE id=?", [(head.id, m.id) for m in rest])
        head.recurrence, head.importance, head.intensity, head.valence = total, importance, intensity, valence
        return head

    def consolidate(self, day: int, sim_minute: float) -> ConsolidationReport:
        report = ConsolidationReport(day=day)
        with self.db.transaction():
            memories = self.stm.unconsolidated()
            report.reviewed = len(memories)

            # 1. Merge duplicates and near-duplicates.
            groups: list[list[Memory]] = []
            for m in memories:
                for g in groups:
                    if self._same_context(g[0], m) and jaccard(g[0].keywords, m.keywords) >= self.MERGE_SIMILARITY:
                        g.append(m)
                        break
                else:
                    groups.append([m])
            survivors: list[Memory] = []
            for g in groups:
                if len(g) > 1:
                    report.merged += len(g) - 1
                    survivors.append(self._merge_group(g))
                else:
                    survivors.append(g[0])

            # 2. Reinforce existing long-term memories that recurred today.
            long_terms = self.ltm.all(limit=400)
            remaining: list[Memory] = []
            for m in survivors:
                match = next(
                    (lt for lt in long_terms if self._same_context(lt, m) and jaccard(lt.keywords, m.keywords) >= self.MERGE_SIMILARITY),
                    None,
                )
                if match is not None:
                    self.db.execute(
                        "UPDATE memories SET recurrence=recurrence+?, importance=MIN(1.0, importance+0.03), "
                        "last_seen_at=? WHERE id=?",
                        (m.recurrence, self.wall(), match.id),
                    )
                    self.db.execute("UPDATE memories SET merged_into=? WHERE id=?", (match.id, m.id))
                    report.reinforced += 1
                else:
                    remaining.append(m)

            # 3. Promote what matters; trivial one-off events stay short-term.
            for m in remaining:
                if (
                    m.importance >= self.PROMOTE_IMPORTANCE
                    or m.recurrence >= self.PROMOTE_RECURRENCE
                    or m.intensity >= self.PROMOTE_INTENSITY
                    or (m.visitor and m.recurrence >= 2)
                ):
                    boost = 0.05 if m.recurrence >= self.PROMOTE_RECURRENCE else 0.0
                    self.ltm.promote(m.id, importance_boost=boost)
                    report.promoted += 1

            # 4. Relationship memories for recurring visitors.
            for row in self.db.query("SELECT * FROM visitors WHERE note_count >= 2"):
                place = row["favourite_location"]
                desc = (
                    f"I know {row['display_name']}. They have left me {row['note_count']} notes"
                    + (f", usually at {place.replace('_', ' ').title()}" if place else "")
                    + "."
                    + (f" {row['impression']}" if row["impression"] else "")
                )
                self.ltm.upsert_relationship(
                    row["key"], desc, sim_minute=sim_minute, location=place,
                    recurrence=row["note_count"], importance=min(1.0, 0.5 + 0.08 * row["note_count"]),
                )

            # 5. Mark reviewed, then let trivial old memories fade.
            if memories:
                self.db.executemany("UPDATE memories SET consolidated=1 WHERE id=?", [(m.id,) for m in memories])
            cutoff = self.wall() - self.FORGET_AGE_S
            cur = self.db.execute(
                f"UPDATE memories SET forgotten=1 WHERE tier='short' AND {ACTIVE} AND consolidated=1 "
                "AND importance < ? AND recurrence < 2 AND intensity < 0.5 AND created_at < ?",
                (self.FORGET_IMPORTANCE, cutoff),
            )
            report.forgotten += cur.rowcount or 0
            overflow = self.db.query(
                f"SELECT id FROM memories WHERE tier='short' AND {ACTIVE} ORDER BY last_seen_at DESC LIMIT -1 OFFSET ?",
                (self.MAX_ACTIVE_SHORT,),
            )
            if overflow:
                self.db.executemany("UPDATE memories SET forgotten=1 WHERE id=?", [(r["id"],) for r in overflow])
                report.forgotten += len(overflow)

        # 6. Update preferences and traits from the day's experiences.
        report.preference_changes = self._learn_preferences(memories, day)
        ranked = sorted(memories, key=lambda m: m.importance + 0.5 * m.intensity + 0.05 * m.recurrence, reverse=True)
        seen: set[int] = set()
        for m in ranked:
            if m.id not in seen:
                report.highlights.append(m)
                seen.add(m.id)
            if len(report.highlights) >= 8:
                break
        self.db.kv_set("last_consolidation", {"day": day, "at": self.wall(), "report": {
            "reviewed": report.reviewed, "merged": report.merged, "promoted": report.promoted,
            "forgotten": report.forgotten, "reinforced": report.reinforced,
        }})
        return report

    def _learn_preferences(self, memories: list[Memory], day: int) -> list[str]:
        changes: list[str] = []
        ch = self.character
        by_location: dict[str, list[float]] = defaultdict(list)
        by_activity: dict[str, list[float]] = defaultdict(list)
        counts: dict[str, int] = defaultdict(int)
        for m in memories:
            weight = m.recurrence
            if m.location:
                by_location[m.location].extend([m.valence] * weight)
            act = CATEGORY_ACTIVITY.get(m.category)
            if act:
                by_activity[act].extend([m.valence] * weight)
            counts[m.category] += weight
        for loc, vals in by_location.items():
            avg = sum(vals) / len(vals)
            if abs(avg) >= 0.15:
                ch.record_location_feeling(loc, round(0.06 * avg, 3))
                changes.append(f"{'warmer' if avg > 0 else 'cooler'} feelings about {loc}")
        for act, vals in by_activity.items():
            avg = sum(vals) / len(vals)
            if abs(avg) >= 0.15:
                ch.record_activity_outcome(act, round(0.05 * avg, 3))
                changes.append(f"{'enjoys' if avg > 0 else 'less keen on'} {act}")
        if counts["discovery"] + counts["research"] >= 3:
            ch.nudge_trait("curious", 0.01, day)
        if counts["creation"] >= 2:
            ch.nudge_trait("playful", 0.005, day)
        if counts["visitor"] >= 2:
            ch.nudge_trait("shy with strangers", -0.01, day)
        if counts["reflection"] + counts["diary"] >= 2:
            ch.nudge_trait("contemplative", 0.005, day)
        ch.decay_interests(0.97)
        ch.save()
        return changes


def local_reflection(report: ConsolidationReport, place_name: Callable[[str | None], str]) -> str:
    """A simple reflection used when Haiku isn't available."""
    if not report.highlights:
        return "A quiet day. Not much happened, and that was nice too. I'll see what tomorrow brings."
    parts = ["Today I remember:"]
    for m in report.highlights[:4]:
        parts.append(f"- {m.description}")
    tail = "I'm sleepy now. Tomorrow I'd like to go back to " + place_name(report.highlights[0].location) + "."
    parts.append(tail)
    return "\n".join(parts)
