"""Visitor relationships and the Shrine message board."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ..safety import clean_text, safe_child_path, sanitize_name, sanitize_output, slugify

ANONYMOUS = "an anonymous visitor"


def visitor_key(name: str) -> str:
    return sanitize_name(name).lower() or "anonymous"


def relationship_label(familiarity: float) -> str:
    if familiarity >= 0.7:
        return "friend"
    if familiarity >= 0.45:
        return "familiar face"
    if familiarity >= 0.2:
        return "acquaintance"
    return "stranger"


class VisitorRegistry:
    def __init__(self, db, wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.wall = wall

    def register_note(self, name: str, location: str) -> dict:
        display = sanitize_name(name) or ANONYMOUS
        key = visitor_key(display)
        now = self.wall()
        row = self.db.query_one("SELECT * FROM visitors WHERE key=?", (key,))
        if row is None:
            self.db.execute(
                "INSERT INTO visitors(key, display_name, first_seen, last_seen, note_count, familiarity, favourite_location) "
                "VALUES(?,?,?,?,1,0.15,?)",
                (key, display, now, now, location),
            )
        else:
            # Favourite location = where most of their notes were left.
            fav = self.db.scalar(
                "SELECT location FROM visitor_notes WHERE visitor=? GROUP BY location ORDER BY COUNT(*) DESC LIMIT 1",
                (key,), location,
            )
            self.db.execute(
                "UPDATE visitors SET last_seen=?, note_count=note_count+1, familiarity=MIN(1.0, familiarity+0.12), "
                "favourite_location=? WHERE key=?",
                (now, fav, key),
            )
        return self.get(key)

    def register_read(self, key: str, impression: str | None) -> None:
        if impression:
            self.db.execute("UPDATE visitors SET impression=?, familiarity=MIN(1.0, familiarity+0.05) WHERE key=?",
                            (clean_text(impression, 150), key))
        else:
            self.db.execute("UPDATE visitors SET familiarity=MIN(1.0, familiarity+0.05) WHERE key=?", (key,))

    def get(self, key: str) -> dict:
        row = self.db.query_one("SELECT * FROM visitors WHERE key=?", (key,))
        if row is None:
            raise KeyError(key)
        d = dict(row)
        d["relationship"] = relationship_label(d["familiarity"])
        return d

    def all(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM visitors ORDER BY familiarity DESC, last_seen DESC")
        out = []
        for r in rows:
            d = dict(r)
            d["relationship"] = relationship_label(d["familiarity"])
            out.append(d)
        return out


class MessageBoard:
    def __init__(self, db, inbox: Path, wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.inbox = inbox
        self.wall = wall

    def post_visitor_note(self, name: str, location_name: str, message: str) -> Path:
        """Used by the local message board UI: drops a note into the inbox folder,
        so it goes through exactly the same untrusted-input pipeline as any file."""
        message = clean_text(message, 4000)
        if not message:
            raise ValueError("The note is empty")
        display = sanitize_name(name) or "Anonymous"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = safe_child_path(self.inbox, f"board-{stamp}-{slugify(display, 20)}.txt")
        n = 1
        while path.exists():
            n += 1
            path = safe_child_path(self.inbox, f"board-{stamp}-{slugify(display, 20)}-{n}.txt")
        text = f"From: {display}\nLocation: {clean_text(location_name, 40)}\n\n{message}\n"
        tmp = path.with_suffix(".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return path

    def post_kimi_message(self, body: str, location: str, sim_minute: float, in_reply_to: int | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO board_messages(created_at, sim_minute, author, location, body, in_reply_to) VALUES(?,?,?,?,?,?)",
            (self.wall(), sim_minute, "Kimi", location, sanitize_output(body, 500), in_reply_to),
        )
        return cur.lastrowid

    def feed(self, limit: int = 60) -> list[dict]:
        notes = self.db.query(
            "SELECT id, received_at AS at, sim_minute, v.display_name AS author, location, body, image_path, "
            "image_description, read_at, 'visitor' AS kind, NULL AS in_reply_to FROM visitor_notes n "
            "LEFT JOIN visitors v ON v.key = n.visitor ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        msgs = self.db.query(
            "SELECT id, created_at AS at, sim_minute, author, location, body, NULL AS image_path, "
            "NULL AS image_description, NULL AS read_at, 'kimi' AS kind, in_reply_to FROM board_messages "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        items = [dict(r) for r in notes] + [dict(r) for r in msgs]
        items.sort(key=lambda d: d["at"])
        return items[-limit:]
