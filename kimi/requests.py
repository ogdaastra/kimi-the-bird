"""Kimi's rare requests to the human who looks after it.

Kimi may ask for one of two things, at most once or twice a day:

* ``artefact`` - something it would love to have in Bramblewick. If the human
  agrees, the wish goes on the *wishlist* (``data/wishlist.md``) to be built
  later; nothing is added to the world automatically.
* ``information`` - a topic it wants the human to explain. The answer becomes
  one of Kimi's memories.

Kimi can never ask for anything outside its world: money, accounts,
passwords or keys, files, personal details. :func:`request_problem` rejects
such requests before they ever reach the human.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .ai.costs import local_day
from .config import Paths
from .safety import safe_child_path, sanitize_output

KINDS = ("artefact", "information")
OPEN, ANSWERED, WISHLISTED, DECLINED, EXPIRED = "open", "answered", "wishlisted", "declined", "expired"
EXPIRE_AFTER_S = 3 * 24 * 3600
MIN_GAP_S = 6 * 3600

# Things Kimi must never ask for, whatever it's phrased as.
_FORBIDDEN = re.compile(
    r"\b(" + "|".join([
        r"passwords?", r"passcodes?", r"pin codes?", r"api ?keys?", r"secret keys?", r"tokens?", r"log ?ins?",
        r"sign ?in", r"accounts?", r"banks?", r"bank details", r"credit cards?", r"debit cards?", r"card numbers?",
        r"payments?", r"pay (?:me|for)", r"money", r"cash", r"buy", r"purchases?", r"gift cards?", r"crypto\w*",
        r"bitcoin", r"wallets?", r"e-?mail(?: address)?", r"phone numbers?", r"home address", r"your address",
        r"where you live", r"your (?:real |full )?name", r"surname", r"birthday", r"date of birth",
        r"social security", r"install\w*", r"download\w*", r"run (?:a|this|the) program", r"open (?:a|this|the) file",
        r"your files?", r"your computer", r"your pc", r"webcam", r"camera", r"microphone",
    ]) + r")\b",
    re.IGNORECASE,
)


def request_problem(kind: str, title: str, body: str) -> str | None:
    """Why a request can't be sent, or None if it's fine."""
    if kind not in KINDS:
        return "Kimi can only ask for an artefact or for information"
    if len(title) < 2:
        return "A request needs a short title"
    if len(body) < 10:
        return "A request needs a few words explaining it"
    hit = _FORBIDDEN.search(f"{title} {body}")
    if hit:
        return f"Kimi can't ask for anything outside Bramblewick (mentions “{hit.group(0)}”)"
    return None


@dataclass
class Outcome:
    ok: bool
    message: str


class HumanRequests:
    def __init__(self, db, paths: Paths, wall=time.time) -> None:
        self.db = db
        self.paths = paths
        self.wall = wall

    # -- reading -------------------------------------------------------------------
    def get(self, rid: int) -> dict | None:
        row = self.db.query_one("SELECT * FROM human_requests WHERE id=?", (rid,))
        return dict(row) if row else None

    def open_request(self) -> dict | None:
        row = self.db.query_one("SELECT * FROM human_requests WHERE status=? ORDER BY id DESC LIMIT 1", (OPEN,))
        return dict(row) if row else None

    def recent(self, limit: int = 10) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM human_requests ORDER BY id DESC LIMIT ?", (limit,))]

    def resolved_since(self, since_wall: float, limit: int = 3) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM human_requests WHERE status != ? AND COALESCE(replied_at, created_at) >= ? "
            "ORDER BY id DESC LIMIT ?", (OPEN, since_wall, limit))]

    def asked_today(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM human_requests WHERE day=?", (local_day(self.wall()),), 0))

    def last_asked_at(self) -> float | None:
        v = self.db.scalar("SELECT MAX(created_at) FROM human_requests", (), None)
        return float(v) if v is not None else None

    def status(self, enabled: bool, daily_limit: int) -> tuple[bool, str]:
        if not enabled:
            return False, "asking the human is turned off in Settings"
        if daily_limit <= 0 or self.asked_today() >= daily_limit:
            return False, "Kimi has already asked the human for something today"
        if self.open_request():
            return False, "Kimi is still waiting for an answer to its last request"
        last = self.last_asked_at()
        if last is not None and self.wall() - last < MIN_GAP_S:
            return False, "Kimi asked for something only a few hours ago"
        return True, ""

    # -- writing -------------------------------------------------------------------
    def create(self, kind: str, title: str, body: str, sim_day: int, location: str | None) -> int:
        now = self.wall()
        cur = self.db.execute(
            "INSERT INTO human_requests(created_at, day, sim_day, kind, title, body, location) VALUES(?,?,?,?,?,?,?)",
            (now, local_day(now), sim_day, kind, title, body, location),
        )
        return int(cur.lastrowid)

    def resolve(self, rid: int, status: str, reply: str | None) -> None:
        self.db.execute("UPDATE human_requests SET status=?, reply=?, replied_at=? WHERE id=?",
                        (status, reply, self.wall(), rid))

    def due_to_expire(self) -> list[dict]:
        cutoff = self.wall() - EXPIRE_AFTER_S
        return [dict(r) for r in self.db.query(
            "SELECT * FROM human_requests WHERE status=? AND created_at < ?", (OPEN, cutoff))]

    def wishlist_items(self) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM human_requests WHERE status=? ORDER BY id", (WISHLISTED,))]

    def write_wishlist(self) -> None:
        """Rewrite ``data/wishlist.md`` from every approved wish."""
        items = self.wishlist_items()
        lines = [
            "# Kimi's wishlist",
            "",
            "Things Kimi asked to have in Bramblewick, which you agreed to. Bring this list to Claude",
            "(or whoever builds Kimi's world) and they can be added to the town as real objects.",
            "",
        ]
        if not items:
            lines.append("_Nothing yet._")
        for it in items:
            when = time.strftime("%Y-%m-%d", time.localtime(it["replied_at"] or it["created_at"]))
            lines.append(f"- [ ] **{sanitize_output(it['title'], 80)}** (asked on Kimi's day {it['sim_day']}, "
                         f"approved {when}, request #{it['id']})")
            lines.append(f"  - Kimi said: “{sanitize_output(it['body'], 400)}”")
            if it.get("reply"):
                lines.append(f"  - Your note: “{sanitize_output(it['reply'], 400)}”")
        path = safe_child_path(self.paths.root, "wishlist.md")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
