"""Kimi's creations: stories, poems, little projects and drawings.

Drawings are rendered locally as SVG from a fixed vocabulary of elements
that Haiku chooses. The model never writes SVG or markup directly, so a
drawing can't contain scripts or links.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from ..safety import safe_child_path, sanitize_output, slugify

KIND_FOLDERS = {
    "drawing": "drawings",
    "diary_illustration": "illustrations",
    "story": "stories",
    "poem": "poems",
    "project": "projects",
}
DRAWING_KINDS = ("drawing", "diary_illustration")

INK = "#4a3b2c"


@dataclass
class Creation:
    id: int
    created_at: float
    sim_minute: float
    kind: str
    title: str
    body: str
    file_path: str | None
    location: str | None
    displayed: int

    @property
    def day(self) -> int:
        return int(self.sim_minute // 1440) + 1


# --------------------------------------------------------------------------
# SVG element painters. Each returns SVG markup centred on (x, y) at scale s.
# --------------------------------------------------------------------------

def _g(x: float, y: float, s: float, body: str, rot: float = 0.0) -> str:
    return f'<g transform="translate({x:.1f} {y:.1f}) rotate({rot:.1f}) scale({s:.2f})">{body}</g>'


def _sun(r):
    rays = "".join(
        f'<line x1="0" y1="-30" x2="0" y2="-40" transform="rotate({a})" stroke="#e8a33d" stroke-width="4" stroke-linecap="round"/>'
        for a in range(0, 360, 30)
    )
    return f'{rays}<circle r="24" fill="#f7c948" stroke="#e8a33d" stroke-width="3"/>'


def _moon(r):
    return '<circle r="22" fill="#f4ecc2"/><circle cx="10" cy="-6" r="19" fill="#2c3766"/>'


def _stars(r):
    pts = []
    for _ in range(9):
        x, y = r.uniform(-90, 90), r.uniform(-25, 25)
        pts.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r.uniform(1.2, 2.6):.1f}" fill="#fff6c8"/>')
    return "".join(pts)


def _cloud(r):
    return ('<g fill="#ffffff" stroke="#c9d6e0" stroke-width="2"><ellipse cx="-18" cy="4" rx="22" ry="14"/>'
            '<ellipse cx="6" cy="-6" rx="24" ry="18"/><ellipse cx="28" cy="5" rx="18" ry="12"/></g>')


def _rain(r):
    return "".join(
        f'<line x1="{x}" y1="{y}" x2="{x - 4}" y2="{y + 12}" stroke="#6c9cc4" stroke-width="2" stroke-linecap="round"/>'
        for x, y in ((-30, 10), (-12, 22), (6, 8), (22, 24), (36, 12), (-22, 38), (14, 40))
    )


def _snow(r):
    return "".join(f'<circle cx="{r.uniform(-40, 40):.0f}" cy="{r.uniform(0, 45):.0f}" r="3" fill="#ffffff" stroke="#d7e3ec"/>'
                   for _ in range(10))


def _tree(r):
    return (f'<rect x="-6" y="-10" width="12" height="40" fill="#8a5a3c" stroke="{INK}" stroke-width="2"/>'
            '<circle cx="0" cy="-30" r="30" fill="#6fa36b" stroke="#3f6e44" stroke-width="2"/>'
            '<circle cx="-18" cy="-14" r="18" fill="#7cb377"/><circle cx="18" cy="-16" r="18" fill="#7cb377"/>')


def _shrub(r):
    berries = "".join(f'<circle cx="{r.uniform(-24, 24):.0f}" cy="{r.uniform(-20, 4):.0f}" r="3" fill="#7b2d5b"/>' for _ in range(6))
    return ('<ellipse cx="0" cy="-8" rx="34" ry="24" fill="#5d9157" stroke="#3f6e44" stroke-width="2"/>'
            '<ellipse cx="-20" cy="0" rx="18" ry="14" fill="#6da567"/>' + berries)


def _flower(r):
    color = r.choice(["#f28fad", "#f7c948", "#b38de0", "#f4f1ea", "#ef8a62"])
    petals = "".join(f'<ellipse cx="0" cy="-9" rx="5" ry="9" fill="{color}" transform="rotate({a})"/>' for a in range(0, 360, 60))
    return (f'<line x1="0" y1="0" x2="0" y2="34" stroke="#4f8a4b" stroke-width="3"/>'
            f'<g>{petals}<circle r="5" fill="#f2b53c"/></g>')


def _mushroom(r):
    return ('<rect x="-6" y="0" width="12" height="18" rx="4" fill="#f4ead8" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M-22 2 Q0 -28 22 2 Z" fill="#d9534f" stroke="#4a3b2c" stroke-width="2"/>'
            '<circle cx="-8" cy="-8" r="3" fill="#fff"/><circle cx="7" cy="-11" r="2.5" fill="#fff"/>')


def _grass(r):
    return "".join(f'<path d="M{x} 10 Q{x + 3} -6 {x + r.uniform(-6, 6):.0f} -14" stroke="#5f9b55" stroke-width="2.5" fill="none" stroke-linecap="round"/>'
                   for x in range(-30, 31, 8))


def _bird(r):
    return '<path d="M-14 0 Q-7 -9 0 0 Q7 -9 14 0" stroke="#4a3b2c" stroke-width="3" fill="none" stroke-linecap="round"/>'


def _kimi(r):
    return ('<ellipse cx="0" cy="0" rx="24" ry="20" fill="#7d95b8" stroke="#4a3b2c" stroke-width="2"/>'
            '<ellipse cx="6" cy="6" rx="13" ry="10" fill="#f6c6a3"/>'
            '<path d="M-22 -4 L-36 -12 L-32 2 Z" fill="#5f7799" stroke="#4a3b2c" stroke-width="1.5"/>'
            '<circle cx="10" cy="-6" r="3.2" fill="#2b2420"/><circle cx="11" cy="-7" r="1" fill="#fff"/>'
            '<path d="M22 -2 L31 1 L22 4 Z" fill="#f0a347"/>'
            '<line x1="-4" y1="19" x2="-6" y2="27" stroke="#c98a4b" stroke-width="2"/>'
            '<line x1="6" y1="19" x2="7" y2="27" stroke="#c98a4b" stroke-width="2"/>')


def _cat(r):
    return ('<ellipse cx="0" cy="8" rx="20" ry="14" fill="#3b3b44"/><circle cx="0" cy="-12" r="12" fill="#3b3b44"/>'
            '<path d="M-10 -20 L-8 -32 L-2 -22 Z M10 -20 L8 -32 L2 -22 Z" fill="#3b3b44"/>'
            '<circle cx="-4" cy="-13" r="2" fill="#f7d35a"/><circle cx="4" cy="-13" r="2" fill="#f7d35a"/>'
            '<path d="M18 12 Q32 4 26 -10" stroke="#3b3b44" stroke-width="4" fill="none" stroke-linecap="round"/>')


def _owl(r):
    return ('<ellipse cx="0" cy="0" rx="18" ry="24" fill="#9c7a5a" stroke="#4a3b2c" stroke-width="2"/>'
            '<circle cx="-7" cy="-8" r="7" fill="#fdf3dc"/><circle cx="7" cy="-8" r="7" fill="#fdf3dc"/>'
            '<circle cx="-7" cy="-8" r="3" fill="#2b2420"/><circle cx="7" cy="-8" r="3" fill="#2b2420"/>'
            '<path d="M-3 0 L0 5 L3 0 Z" fill="#f0a347"/>')


def _hedgehog(r):
    spikes = "".join(f'<line x1="0" y1="0" x2="0" y2="-26" stroke="#6b4f3a" stroke-width="3" transform="rotate({a})"/>' for a in range(-80, 81, 16))
    return (f'<g>{spikes}</g><ellipse cx="0" cy="0" rx="24" ry="15" fill="#8a6a50"/>'
            '<ellipse cx="22" cy="5" rx="9" ry="7" fill="#e8cfae"/><circle cx="24" cy="2" r="1.8" fill="#2b2420"/>')


def _frog(r):
    return ('<ellipse cx="0" cy="4" rx="18" ry="12" fill="#6fb35b" stroke="#3f6e44" stroke-width="2"/>'
            '<circle cx="-8" cy="-8" r="6" fill="#6fb35b"/><circle cx="8" cy="-8" r="6" fill="#6fb35b"/>'
            '<circle cx="-8" cy="-8" r="2.5" fill="#2b2420"/><circle cx="8" cy="-8" r="2.5" fill="#2b2420"/>')


def _snail(r):
    return ('<path d="M-22 10 L20 10 Q26 10 26 4 L22 4" fill="#d9c49c" stroke="#4a3b2c" stroke-width="2"/>'
            '<circle cx="-2" cy="-2" r="13" fill="#c98a4b" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M-2 -2 m-6 0 a6 6 0 1 1 6 6 a3 3 0 1 1 -3 -3" fill="none" stroke="#4a3b2c" stroke-width="1.5"/>')


def _butterfly(r):
    c = r.choice(["#f28fad", "#f7c948", "#8fb7f2", "#b38de0"])
    return (f'<ellipse cx="-9" cy="-5" rx="9" ry="7" fill="{c}"/><ellipse cx="9" cy="-5" rx="9" ry="7" fill="{c}"/>'
            f'<ellipse cx="-7" cy="6" rx="6" ry="5" fill="{c}"/><ellipse cx="7" cy="6" rx="6" ry="5" fill="{c}"/>'
            '<line x1="0" y1="-10" x2="0" y2="10" stroke="#4a3b2c" stroke-width="2"/>')


def _fish(r):
    return ('<ellipse cx="0" cy="0" rx="18" ry="9" fill="#ef8a62" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M16 0 L28 -8 L28 8 Z" fill="#ef8a62" stroke="#4a3b2c" stroke-width="2"/><circle cx="-9" cy="-2" r="2" fill="#2b2420"/>')


def _house(r):
    roof = r.choice(["#c0624b", "#6a7fa8", "#8a6a50"])
    return (f'<rect x="-26" y="-10" width="52" height="40" fill="#f2e3c6" stroke="{INK}" stroke-width="2"/>'
            f'<path d="M-32 -8 L0 -36 L32 -8 Z" fill="{roof}" stroke="{INK}" stroke-width="2"/>'
            '<rect x="-6" y="10" width="12" height="20" fill="#8a5a3c"/><rect x="-20" y="0" width="10" height="10" fill="#f7d35a"/>')


def _shrine(r):
    return ('<rect x="-20" y="-6" width="40" height="34" fill="#b8b2a3" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M-30 -6 L0 -28 L30 -6 Z" fill="#7f8f7a" stroke="#4a3b2c" stroke-width="2"/>'
            '<rect x="-8" y="6" width="16" height="22" fill="#5a5148"/>')


def _lantern(r):
    return ('<line x1="0" y1="-30" x2="0" y2="-16" stroke="#4a3b2c" stroke-width="2"/>'
            '<rect x="-9" y="-16" width="18" height="24" rx="5" fill="#f7c948" stroke="#c0624b" stroke-width="2"/>'
            '<circle r="18" fill="#f7c948" opacity="0.2"/>')


def _cup(r):
    return ('<path d="M-14 -10 L14 -10 L10 14 L-10 14 Z" fill="#f4f1ea" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M14 -4 Q24 0 13 8" fill="none" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M-4 -16 Q0 -24 -2 -30 M4 -16 Q8 -24 6 -30" stroke="#c9c2b4" stroke-width="2" fill="none"/>')


def _book(r):
    return ('<path d="M-24 -12 L0 -6 L24 -12 L24 12 L0 18 L-24 12 Z" fill="#c0624b" stroke="#4a3b2c" stroke-width="2"/>'
            '<line x1="0" y1="-6" x2="0" y2="18" stroke="#4a3b2c" stroke-width="2"/>')


def _leaf(r):
    c = r.choice(["#6fa36b", "#e0a03c", "#c0624b"])
    return (f'<path d="M0 -20 Q16 0 0 20 Q-16 0 0 -20 Z" fill="{c}" stroke="#4a3b2c" stroke-width="1.5"/>'
            '<line x1="0" y1="-18" x2="0" y2="22" stroke="#4a3b2c" stroke-width="1.2"/>')


def _feather(r):
    return ('<path d="M0 -26 Q14 -6 0 24 Q-10 -6 0 -26 Z" fill="#6c9cc4" stroke="#4a3b2c" stroke-width="1.5"/>'
            '<line x1="0" y1="-24" x2="0" y2="30" stroke="#4a3b2c" stroke-width="1.5"/>')


def _pond(r):
    return ('<ellipse cx="0" cy="0" rx="60" ry="16" fill="#8fc1d8" stroke="#5f8fa8" stroke-width="2"/>'
            '<path d="M-30 0 Q-20 -4 -10 0 M10 4 Q20 0 30 4" stroke="#ffffff" stroke-width="2" fill="none"/>')


def _hill(r):
    return '<path d="M-120 30 Q0 -60 120 30 Z" fill="#8fbf7a" stroke="#5f8f55" stroke-width="2"/>'


def _mountain(r):
    return ('<path d="M-90 40 L-10 -60 L70 40 Z" fill="#9aa5b5" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M-26 -40 L-10 -60 L6 -40 L-4 -36 L-10 -44 L-18 -36 Z" fill="#ffffff"/>')


def _boat(r):
    return ('<path d="M-28 0 L28 0 L18 14 L-18 14 Z" fill="#8a5a3c" stroke="#4a3b2c" stroke-width="2"/>'
            '<line x1="0" y1="0" x2="0" y2="-34" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M2 -32 L22 -6 L2 -6 Z" fill="#f4f1ea" stroke="#4a3b2c" stroke-width="1.5"/>')


def _heart(r):
    return '<path d="M0 12 C-26 -6 -12 -26 0 -12 C12 -26 26 -6 0 12 Z" fill="#e8687f" stroke="#4a3b2c" stroke-width="2"/>'


def _spiral(r):
    return ('<path d="M0 0 m0 -2 a2 2 0 1 1 -2 2 a6 6 0 1 1 6 -6 a10 10 0 1 1 -10 10 a16 16 0 1 1 16 -16" '
            'fill="none" stroke="#b38de0" stroke-width="2.5" stroke-linecap="round"/>')


def _key(r):
    return ('<circle cx="-14" cy="0" r="8" fill="none" stroke="#c9a23c" stroke-width="4"/>'
            '<line x1="-6" y1="0" x2="20" y2="0" stroke="#c9a23c" stroke-width="4"/>'
            '<line x1="14" y1="0" x2="14" y2="7" stroke="#c9a23c" stroke-width="3"/><line x1="19" y1="0" x2="19" y2="6" stroke="#c9a23c" stroke-width="3"/>')


def _shell(r):
    return ('<path d="M0 14 L-20 -6 Q0 -22 20 -6 Z" fill="#f2c9b4" stroke="#4a3b2c" stroke-width="2"/>'
            '<path d="M0 14 L-10 -14 M0 14 L0 -17 M0 14 L10 -14" stroke="#4a3b2c" stroke-width="1.2"/>')


PAINTERS: dict[str, Callable[[random.Random], str]] = {
    "sun": _sun, "moon": _moon, "stars": _stars, "cloud": _cloud, "rain": _rain, "snow": _snow,
    "tree": _tree, "shrub": _shrub, "flower": _flower, "mushroom": _mushroom, "grass": _grass,
    "bird": _bird, "kimi": _kimi, "cat": _cat, "owl": _owl, "hedgehog": _hedgehog, "frog": _frog,
    "snail": _snail, "butterfly": _butterfly, "fish": _fish, "house": _house, "shrine": _shrine,
    "lantern": _lantern, "cup": _cup, "book": _book, "leaf": _leaf, "feather": _feather,
    "pond": _pond, "hill": _hill, "mountain": _mountain, "boat": _boat, "heart": _heart,
    "spiral": _spiral, "key": _key, "shell": _shell,
}
SKY = {"sun", "moon", "stars", "cloud", "rain", "snow", "bird"}
BACKDROP = {"hill", "mountain"}
FLOATING = {"butterfly", "heart", "spiral", "leaf", "feather", "lantern"}


def render_drawing(title: str, elements: list[str], caption: str, seed: int) -> str:
    r = random.Random(seed)
    w, h = 480, 380
    els = [e for e in elements if e in PAINTERS][:12] or ["kimi", "flower"]
    night = "moon" in els or ("stars" in els and "sun" not in els)
    sky_top, sky_bottom = ("#1f2a52", "#45568a") if night else ("#bfe3f5", "#fdf3dc")
    ground = "#4c6b55" if night else "#a7cf8e"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        '<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{sky_top}"/><stop offset="1" stop-color="{sky_bottom}"/></linearGradient></defs>',
        f'<rect width="{w}" height="{h}" fill="#fbf6ea"/>',
        f'<rect x="14" y="14" width="{w - 28}" height="{h - 84}" rx="10" fill="url(#sky)" stroke="{INK}" stroke-width="2"/>',
    ]
    for e in [e for e in els if e in BACKDROP]:
        parts.append(_g(r.uniform(140, 340), 228, r.uniform(1.0, 1.4), PAINTERS[e](r)))
    parts.append(f'<path d="M14 230 Q240 {r.uniform(196, 222):.0f} {w - 14} 232 L{w - 14} {h - 70} L14 {h - 70} Z" '
                 f'fill="{ground}" stroke="{INK}" stroke-width="2"/>')
    sky_slots = [60, 160, 260, 360, 420]
    r.shuffle(sky_slots)
    for e in [e for e in els if e in SKY]:
        x = sky_slots.pop() if sky_slots else r.uniform(60, 420)
        y = 90 if e in ("stars",) else r.uniform(60, 110)
        if e == "rain" or e == "snow":
            y = r.uniform(120, 150)
        parts.append(_g(x, y, r.uniform(0.8, 1.1), PAINTERS[e](r)))
    ground_els = [e for e in els if e not in SKY and e not in BACKDROP and e not in FLOATING]
    n = max(1, len(ground_els))
    for i, e in enumerate(ground_els):
        x = 70 + (w - 140) * (i + 0.5) / n + r.uniform(-14, 14)
        y = 262 + r.uniform(-8, 14)
        scale = 1.15 if e in ("kimi", "house", "tree", "shrine") else r.uniform(0.85, 1.05)
        if e == "pond":
            y, scale = 285, 1.0
        parts.append(_g(x, y, scale, PAINTERS[e](r), r.uniform(-4, 4)))
    for e in [e for e in els if e in FLOATING]:
        parts.append(_g(r.uniform(80, 400), r.uniform(150, 200), r.uniform(0.8, 1.1), PAINTERS[e](r), r.uniform(-15, 15)))
    parts.append(f'<text x="{w / 2}" y="{h - 42}" text-anchor="middle" font-family="Georgia, serif" font-size="20" '
                 f'fill="{INK}">{escape(title[:60])}</text>')
    if caption:
        parts.append(f'<text x="{w / 2}" y="{h - 18}" text-anchor="middle" font-family="Georgia, serif" font-style="italic" '
                     f'font-size="13" fill="#7a6a58">{escape(caption[:90])}</text>')
    parts.append("</svg>")
    return "".join(parts)


class CreativeStudio:
    def __init__(self, db, folder: Path, location_name: Callable[[str | None], str],
                 wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.folder = folder
        self.location_name = location_name
        self.wall = wall

    def create(self, *, kind: str, title: str, content: str, elements: list[str],
               sim_minute: float, location: str | None) -> Creation:
        if kind not in KIND_FOLDERS:
            raise ValueError(f"Unknown creation kind {kind}")
        title = sanitize_output(title, 80) or f"Untitled {kind}"
        content = sanitize_output(content, 4000)
        day = int(sim_minute // 1440) + 1
        cur = self.db.execute(
            "INSERT INTO creations(created_at, sim_minute, kind, title, body, location) VALUES(?,?,?,?,?,?)",
            (self.wall(), sim_minute, kind, title, content, location),
        )
        cid = cur.lastrowid
        sub = KIND_FOLDERS[kind]
        stem = f"day-{day:04d}-{slugify(title)}-{cid}"
        target_dir = safe_child_path(self.folder, sub)
        target_dir.mkdir(parents=True, exist_ok=True)
        if kind in DRAWING_KINDS:
            seed = int(hashlib.sha256(f"{title}|{cid}".encode()).hexdigest()[:8], 16)
            svg = render_drawing(title, elements, content, seed)
            path = safe_child_path(self.folder, sub, stem + ".svg")
            path.write_text(svg, encoding="utf-8")
        else:
            where = self.location_name(location)
            text = f"# {title}\n\n*A {kind} by Kimi - Day {day}, {where}*\n\n{content}\n"
            path = safe_child_path(self.folder, sub, stem + ".md")
            path.write_text(text, encoding="utf-8")
        rel = str(path.relative_to(self.folder.resolve()))
        self.db.execute("UPDATE creations SET file_path=? WHERE id=?", (rel, cid))
        return self.get(cid)

    def get(self, cid: int) -> Creation:
        row = self.db.query_one("SELECT * FROM creations WHERE id=?", (cid,))
        if row is None:
            raise KeyError(cid)
        return Creation(**{k: row[k] for k in row.keys()})

    def path_of(self, creation: Creation) -> Path | None:
        if not creation.file_path:
            return None
        return safe_child_path(self.folder, creation.file_path)

    def list(self, limit: int = 100) -> list[Creation]:
        rows = self.db.query("SELECT * FROM creations ORDER BY id DESC LIMIT ?", (limit,))
        return [Creation(**{k: r[k] for k in r.keys()}) for r in rows]

    def ids(self) -> set[int]:
        return {r["id"] for r in self.db.query("SELECT id FROM creations")}

    def count(self, kind: str | None = None) -> int:
        if kind:
            return int(self.db.scalar("SELECT COUNT(*) FROM creations WHERE kind=?", (kind,), 0))
        return int(self.db.scalar("SELECT COUNT(*) FROM creations", (), 0))

    def set_displayed(self, cid: int, displayed: bool) -> None:
        self.db.execute("UPDATE creations SET displayed=? WHERE id=?", (1 if displayed else 0, cid))
