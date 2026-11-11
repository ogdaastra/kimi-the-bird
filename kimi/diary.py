"""Kimi's diary: a personal record, stored in SQLite and mirrored to Markdown."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .safety import safe_child_path, sanitize_output


@dataclass
class DiaryEntry:
    id: int
    created_at: float
    sim_minute: float
    location: str | None
    title: str
    body: str
    mood: str | None
    kind: str

    @property
    def day(self) -> int:
        return int(self.sim_minute // 1440) + 1

    @property
    def clock(self) -> str:
        m = int(self.sim_minute % 1440)
        return f"{m // 60:02d}:{m % 60:02d}"


class Diary:
    def __init__(self, db, folder: Path, location_name: Callable[[str | None], str],
                 wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.folder = folder
        self.location_name = location_name
        self.wall = wall

    def add(self, title: str, body: str, *, sim_minute: float, location: str | None,
            mood: str | None = None, kind: str = "entry") -> DiaryEntry:
        title = sanitize_output(title, 80) or "A page from my diary"
        body = sanitize_output(body, 4000)
        if len(body) < 10:
            raise ValueError("Diary entry too short")
        cur = self.db.execute(
            "INSERT INTO diary(created_at, sim_minute, location, title, body, mood, kind) VALUES(?,?,?,?,?,?,?)",
            (self.wall(), sim_minute, location, title, body, mood, kind),
        )
        entry = self.get(cur.lastrowid)
        self._mirror(entry)
        return entry

    def _mirror(self, entry: DiaryEntry) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = safe_child_path(self.folder, f"day-{entry.day:04d}.md")
            new_file = not path.exists()
            with path.open("a", encoding="utf-8") as fh:
                if new_file:
                    fh.write(f"# Kimi's diary - Day {entry.day}\n\n")
                where = self.location_name(entry.location)
                label = "Evening reflection" if entry.kind == "reflection" else entry.title
                fh.write(f"## {label}\n*{entry.clock}, {where}*")
                if entry.mood:
                    fh.write(f" *- feeling {entry.mood}*")
                fh.write(f"\n\n{entry.body}\n\n")
        except OSError:
            pass  # The database copy is authoritative.

    def get(self, entry_id: int) -> DiaryEntry:
        row = self.db.query_one("SELECT * FROM diary WHERE id=?", (entry_id,))
        if row is None:
            raise KeyError(entry_id)
        return DiaryEntry(**{k: row[k] for k in row.keys()})

    def list(self, limit: int = 200, offset: int = 0, chronological: bool = True) -> list[DiaryEntry]:
        rows = self.db.query("SELECT * FROM diary ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        entries = [DiaryEntry(**{k: r[k] for k in r.keys()}) for r in rows]
        if chronological:
            entries.reverse()
        return entries

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM diary", (), 0))

    def latest(self) -> DiaryEntry | None:
        entries = self.list(limit=1)
        return entries[0] if entries else None
