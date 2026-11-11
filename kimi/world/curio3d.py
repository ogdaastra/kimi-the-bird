"""Where Bramblewick's curiosities sit, and their little low-poly models.

Placement is deterministic: each curiosity's hint (see ``curiosities.py``)
is resolved to a free spot that keeps clear of buildings, paths, plazas,
townsfolk and every other curiosity. Trees and bushes are planted *after*
the curiosities and avoid them.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from .curiosities import CURIOSITIES, Curiosity
from .layout3d import (
    ISLAND_RADIUS,
    PATH_WIDTH,
    PLACES,
    SQUARE_RADIUS,
    WATER_LEVEL,
    activity_spot,
    distance_to_paths,
    heading_to,
    landmarks,
    path_polylines,
    rotate_y,
)
from .mesh3d import (
    MeshBuilder,
    MeshData,
    _path_lamps,
    _pond_centre,
    _village_houses,
    height,
    in_view_corridor,
    rgb,
    shade,
    shrub_surface,
)

POND_RADIUS = 100.0
# Curiosity sizes in the catalogue are "Kimi-relative"; the models are drawn this much larger
# so they read well from the follow camera. A few things are meant to be tiny.
MODEL_SCALE = 1.6
SMALL_KINDS = {"tiny_door": 1.1, "coin": 1.0, "stepping_stones": 1.0}


def model_size(c: Curiosity) -> float:
    return c.size * SMALL_KINDS.get(c.kind, MODEL_SCALE)
BUILDING_R = {"nest": 82.0, "shrub": 118.0, "shrine": 112.0, "cafe": 108.0, "print_shop": 108.0, "library": 112.0}


# -- placement --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _base_occupancy() -> tuple[tuple[float, float, float], ...]:
    occ: list[tuple[float, float, float]] = []
    for p in PLACES.values():
        if p.id == "square":
            occ.append((p.x, p.z, 50.0))
            for k in range(3):  # benches
                a = math.radians(30 + k * 120)
                occ.append((p.x + math.cos(a) * 92, p.z + math.sin(a) * 92, 28.0))
            for k in range(4):  # lamps
                a = math.radians(45 + k * 90)
                occ.append((p.x + math.cos(a) * (SQUARE_RADIUS + 18), p.z + math.sin(a) * (SQUARE_RADIUS + 18), 10.0))
            occ.append((p.x + 70, p.z + 48, 16.0))
            continue
        occ.append((p.x, p.z, BUILDING_R[p.id]))
        occ.append((p.plaza[0], p.plaza[1], 42.0))
        for action in ("read_note", "create_art", "research", "eat", "sleep"):
            x, z, _ = activity_spot(p.id, action)
            if (x, z) != p.plaza:
                occ.append((x, z, 16.0))
    cafe, lib, sh, nest = PLACES["cafe"], PLACES["library"], PLACES["shrine"], PLACES["nest"]
    for lx, lz in ((70, 112), (-70, 128)):  # cafe tables under umbrellas
        occ.append((*cafe.local(lx, lz), 36.0))
    occ.append((*lib.local(0, 128), 50.0))  # library steps
    for side in (-1, 1):
        occ.append((*sh.local(side * 70, 112), 14.0))  # shrine lanterns
    occ.append((*nest.local(38, 70), 10.0))
    occ.append((*nest.local(0, 62), 32.0))
    marks = landmarks()
    occ.append((marks["noticeBoard"]["x"], marks["noticeBoard"]["z"], 36.0))
    occ.append((marks["easel"]["x"], marks["easel"]["z"], 28.0))
    for c in marks["critters"]:
        occ.append((c["x"], c["z"], 22.0))
    for x, z, *_ in _village_houses():
        occ.append((x, z, 96.0))
    for x, z in _path_lamps():
        occ.append((x, z, 10.0))
    return tuple(occ)


def _clearance_ok(x, z, r, occ, polys, tall) -> bool:
    for ox, oz, orr in occ:
        if math.hypot(x - ox, z - oz) < r + orr:
            return False
    if tall and in_view_corridor(x, z, r):
        return False
    return distance_to_paths(x, z, polys) >= PATH_WIDTH / 2 + 5 + r


def _search(x0, z0, r, occ, polys, tall, land=False) -> tuple[float, float]:
    best, best_score = (x0, z0), -1e9
    for k in range(500):
        rad = 5.0 * math.sqrt(k) * 1.6
        a = k * 2.39996
        x, z = x0 + math.cos(a) * rad, z0 + math.sin(a) * rad
        if land and height(x, z) < WATER_LEVEL + 12:
            continue
        if _clearance_ok(x, z, r, occ, polys, tall):
            return x, z
        score = min([math.hypot(x - ox, z - oz) - orr - r for ox, oz, orr in occ] or [0.0])
        if score > best_score:
            best, best_score = (x, z), score
    return best


def _shore_point(angle_deg: float) -> tuple[float, float]:
    ux, uz = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    r = ISLAND_RADIUS - 220
    while r < ISLAND_RADIUS + 200:
        if height(ux * r, uz * r) < WATER_LEVEL + 7:
            return ux * (r - 10), uz * (r - 10)
        r += 4
    return ux * ISLAND_RADIUS, uz * ISLAND_RADIUS


def _ground(x: float, z: float, r: float) -> float:
    samples = [height(x, z)] + [height(x + math.cos(a) * r, z + math.sin(a) * r) for a in (0, 1.57, 3.14, 4.71)]
    return min(samples)


def _nearest_place(x: float, z: float) -> str:
    return min(PLACES.values(), key=lambda p: math.hypot(x - p.plaza[0], z - p.plaza[1])).id


@lru_cache(maxsize=1)
def curiosity_spots() -> dict[str, dict]:
    """Resolved position, facing, standing spot and zone for every curiosity."""
    polys = path_polylines()
    occ = list(_base_occupancy())
    pond = _pond_centre()
    occ.append((pond[0], pond[1], POND_RADIUS + 14))
    spots: dict[str, dict] = {}
    for c in CURIOSITIES:
        kind = c.spot[0]
        size = model_size(c)
        r = size / 2 + 6
        stand_d = size / 2 + 12
        if kind in ("near", "attach"):
            p = PLACES[c.zone]
            ang, dist = c.spot[1], c.spot[2]
            if kind == "attach" and p.id == "shrub":
                world_ang = p.facing + ang
                dist = shrub_surface(world_ang) - 4
            lx, lz = math.sin(math.radians(ang)) * dist, math.cos(math.radians(ang)) * dist
            x0, z0 = p.local(lx, lz)
            if kind == "attach":
                x, z = x0, z0
            else:
                x, z = _search(x0, z0, r, occ, polys, c.tall)
            rot = heading_to(x - p.x, z - p.z)
            if kind == "attach" and len(c.spot) > 3:
                stand_d = c.spot[3] - dist
            y = 0.0
        elif kind == "pond":
            ang, rr = c.spot[1], c.spot[2]
            x = pond[0] + math.cos(math.radians(ang)) * rr
            z = pond[1] + math.sin(math.radians(ang)) * rr
            rot = heading_to(math.cos(math.radians(ang)), math.sin(math.radians(ang)))
            stand_d = POND_RADIUS + 16 - rr
            y = 0.0
        elif kind == "shore":
            x0, z0 = _shore_point(c.spot[1])
            x, z = _search(x0, z0, r, occ, polys, c.tall)
            rot = heading_to(-x, -z)
            y = _ground(x, z, size / 2)
        else:  # hill
            ang, rr = c.spot[1], c.spot[2]
            x0, z0 = math.cos(math.radians(ang)) * rr, math.sin(math.radians(ang)) * rr
            x, z = _search(x0, z0, r, occ, polys, c.tall, land=True)
            rot = heading_to(-x, -z)
            y = _ground(x, z, size / 2)
        fx, fz = math.sin(math.radians(rot)), math.cos(math.radians(rot))
        sx, sz = x + fx * stand_d, z + fz * stand_d
        zone = c.zone or _nearest_place(sx, sz)
        if kind not in ("attach", "pond"):
            occ.append((x, z, r + 4))
        spots[c.id] = {"id": c.id, "name": c.name, "kind": c.kind, "x": x, "y": y, "z": z, "rot": rot,
                       "standX": sx, "standZ": sz, "zone": zone, "size": size, "tall": c.tall}
    return spots


def occupied_by_curiosities() -> list[tuple[float, float, float]]:
    """Circles (x, z, r) that trees, bushes and rocks must keep clear of."""
    out = []
    for s in curiosity_spots().values():
        out.append((s["x"], s["z"], s["size"] / 2 + 10))
        out.append((s["standX"], s["standZ"], 14.0))
    return out


def view_corridors() -> list[tuple[float, float, float]]:
    """Circles along the line the follow camera looks from while Kimi examines each curiosity.

    Trees and bushes stay out of them, so nothing tall stands between the camera and Kimi.
    """
    out = []
    for s in curiosity_spots().values():
        a = math.radians(s["rot"] + 28.0)
        dx, dz = math.sin(a), math.cos(a)
        for d in (40, 90, 140, 190, 240, 290):
            out.append((s["standX"] + dx * d, s["standZ"] + dz * d, 24 + d * 0.2))
    return out


# -- models -------------------------------------------------------------------------------

C = {k: rgb(v) for k, v in {
    "wood": "#8a5a3c", "darkwood": "#5e3d28", "wood2": "#a8754d", "bark": "#6b4630", "stone": "#b9b3a5",
    "dstone": "#8f8a7f", "moss": "#5f8f45", "moss2": "#86b35c", "brass": "#c9a24a", "bronze": "#a8743a",
    "iron": "#4a4a50", "red": "#c4483a", "cream": "#f4ecd8", "white": "#f7f4ee", "green_door": "#3f8f5a",
    "thread": "#d8d0c0", "acorn": "#a86a32", "acorn_cap": "#6b4a2a", "rings": "#d9b98a", "glass": "#bfdde8",
    "label": "#f2e2b8", "root": "#7a5236", "dark": "#2e2620", "shell": "#e9d8b8", "shell2": "#b98a5a",
    "silk": "#f2f2f2", "black": "#222222", "berry": "#6b2a5b", "seed": "#e2cf9a", "grass": "#8ccf6a",
    "stem": "#f1ece0", "cap": "#efe3c8", "moth": "#d9cdb4", "water": "#4f86a8", "deepwater": "#3d6f8f",
    "roofred": "#b5523e", "roofgreen": "#6f8f6a", "ribbon1": "#e85d75", "ribbon2": "#f2b84b", "ribbon3": "#5fb0d9",
    "ribbon4": "#7cc06a", "ribbon5": "#f7f4ee", "ribbon6": "#ef8a62", "leaf": "#6fa36b", "boxblue": "#6a8fb5",
    "postgreen": "#3f6e4e", "clockface": "#f6f1e3", "statue": "#a8a49a", "statue_light": "#d4d0c6",
    "paving": "#cfc6b4", "chalk": "#fbfbf7", "postred": "#c7392f", "gold": "#e8b73a", "teablue": "#4f7fc0",
    "slate": "#2f3b36", "wicker": "#c79a5a", "bikegreen": "#4d8a6a", "soil": "#6b4a32", "mint": "#5fae6a",
    "thyme": "#7f9f5a", "yellow": "#f2cf3a", "silver": "#c8cdd2", "ink": "#1d2230", "kiteyellow": "#f2c84b",
    "orange": "#ef8a3a", "planet_blue": "#5b7fb0", "sun": "#f5c542", "ocean": "#4f7fb0", "land": "#7fb06a",
    "quill": "#f4f1ea", "lily": "#5f9f4f", "frog": "#6fae4a", "pink": "#f2a0b8", "walnut": "#8a6034",
    "reed": "#6f9a4a", "cattail": "#6b4426", "whitewash": "#ece6d8", "roofbrown": "#7a5236", "bottle": "#3f8f6a",
    "cork": "#c49a6a", "boat": "#7b5a3e", "crab": "#e0703a", "shirt": "#6a7fa8", "sack": "#d9c49a",
    "straw": "#d9b45a", "scorch": "#5a4a3a", "inner": "#3a2a1f", "rock": "#a39e92", "lichen": "#c9c47a",
    "copper": "#5fa58f", "paint1": "#e2483a", "paint2": "#ef8a3a", "paint3": "#f2cf3a", "paint4": "#5fae5a",
    "paint5": "#4f7fc0", "paint6": "#7a5ab0",
}.items()}

RIBBONS = [C[f"ribbon{i}"] for i in range(1, 7)]
JAMS = [rgb(h) for h in ("#b8283a", "#e2483a", "#ef8a3a", "#f2b84b", "#7a2a5a", "#5a2a6a", "#c94a6a", "#e86a4a",
                          "#a8c84a", "#f2d86a", "#8a1a2a", "#d95a8a")]


class _L:
    """Local frame of one curiosity: +Z faces whoever comes to look at it."""

    def __init__(self, x: float, y: float, z: float, rot: float) -> None:
        self.x, self.y, self.z, self.rot = x, y, z, rot

    def p(self, lx: float, ly: float, lz: float) -> tuple[float, float, float]:
        rx, rz = rotate_y(lx, lz, self.rot)
        return (self.x + rx, self.y + ly, self.z + rz)

    def v(self, lx: float, ly: float, lz: float) -> tuple[float, float, float]:
        rx, rz = rotate_y(lx, lz, self.rot)
        return (rx, ly, rz)

    def gy(self, lx: float, lz: float) -> float:
        """Local height of the ground under a local point."""
        x, _, z = self.p(lx, 0, lz)
        return height(x, z) - self.y

    def box(self, b, lx, ly, lz, sx, sy, sz, col, drot=0.0, top=None):
        x, y, z = self.p(lx, ly, lz)
        b.box(x, y, z, sx, sy, sz, col, self.rot + drot, top)

    def cyl(self, b, lx, ly, lz, r0, r1, h, seg, col, caps=True, top=None):
        x, y, z = self.p(lx, ly, lz)
        b.cylinder(x, y, z, r0, r1, h, seg, col, caps, top)

    def sphere(self, b, lx, ly, lz, r, col, subdiv=0, squash=(1.0, 1.0, 1.0), rng=None, jitter=0.0):
        x, y, z = self.p(lx, ly, lz)
        b.icosphere(x, y, z, r, col, subdiv=subdiv, squash=squash, rng=rng, jitter=jitter)

    def disc(self, b, lx, ly, lz, r, seg, col):
        x, y, z = self.p(lx, ly, lz)
        b.disc(x, y, z, r, seg, col)

    def tube(self, b, p0, p1, r0, r1, seg, col, caps=True, inward=False):
        b.tube(self.p(*p0), self.p(*p1), r0, r1, seg, col, caps, inward)

    def beam(self, b, p0, p1, w, col, h=None, side=None):
        b.beam(self.p(*p0), self.p(*p1), w, col, h, self.v(*side) if side else None)

    def roof(self, b, lx, ly, lz, w, d, h, col, drot=0.0):
        x, y, z = self.p(lx, ly, lz)
        b.gable_roof(x, y, z, w, d, h, col, self.rot + drot)

    def tri2(self, b, a, c, d, col):
        """A two-sided triangle (for sails, kites and umbrellas)."""
        pa, pc, pd = self.p(*a), self.p(*c), self.p(*d)
        n = _tri_normal(pa, pc, pd)
        b.tri(pa, pc, pd, col, n)
        b.tri(pa, pc, pd, shade(col, 0.8), (-n[0], -n[1], -n[2]))

    def ring(self, b, centre, radius, plane, seg, w, col, h=None):
        """A polygonal ring of beams. plane 'xy' stands upright facing +Z, 'xz' lies flat."""
        cx, cy, cz = centre
        pts = []
        for i in range(seg + 1):
            a = 2 * math.pi * i / seg
            if plane == "xy":
                pts.append((cx + math.cos(a) * radius, cy + math.sin(a) * radius, cz))
            elif plane == "zy":
                pts.append((cx, cy + math.sin(a) * radius, cz + math.cos(a) * radius))
            else:
                pts.append((cx + math.cos(a) * radius, cy, cz + math.sin(a) * radius))
        side = (0, 0, 1) if plane == "xy" else (1, 0, 0) if plane == "zy" else (0, 1, 0)
        for p0, p1 in zip(pts, pts[1:]):
            self.beam(b, p0, p1, w, col, h, side=side)


def _tri_normal(a, b, c):
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(k * k for k in n)) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)


# Each builder draws one model around its local origin. s is the curiosity's size.

def m_tiny_door(b, g, L, s, rng):
    L.box(b, 0, 0, -2, s, s * 1.45, 8, C["darkwood"])
    L.box(b, 0, 0, 2.2, s * 0.74, s * 1.22, 1.2, C["green_door"])
    L.sphere(b, s * 0.22, s * 0.6, 3.2, s * 0.09, C["brass"])
    L.box(b, 0, 0, s * 0.55, s * 0.8, 0.5, s * 0.5, C["grass"])
    L.sphere(g, 0, s * 1.05, 2.4, s * 0.1, C["white"])


def m_acorn_chimes(b, g, L, s, rng):
    H = s * 2.6
    L.tube(b, (0, 0, 0), (0, H, 0), 1.4, 1.1, 5, C["wood"])
    L.beam(b, (0, H - 2, 0), (s * 1.0, H + 3, s * 0.2), 1.6, C["wood"])
    L.beam(b, (s * 0.5, H + 0.5, 0.1), (s * 0.7, H + 5, s * 0.1), 1.0, C["wood"])
    for k in range(6):
        t = (k + 0.5) / 6
        ax, ay, az = s * t, H - 2 + 5 * t, s * 0.2 * t
        drop = 5 + (k % 3) * 3
        L.beam(b, (ax, ay, az), (ax, ay - drop, az), 0.35, C["thread"])
        L.sphere(b, ax, ay - drop - 2.2, az, 1.9, C["acorn"], squash=(0.85, 1.15, 0.85))
        L.cyl(b, ax, ay - drop - 1.2, az, 2.0, 1.2, 1.2, 6, C["acorn_cap"])


def m_stump_chair(b, g, L, s, rng):
    r = s * 0.42
    L.cyl(b, 0, 0, 0, r * 1.1, r, s * 0.42, 9, C["bark"], top=C["rings"])
    L.box(b, 0, s * 0.42, -r * 0.55, r * 1.7, s * 0.55, r * 0.6, C["moss"])
    for side in (-1, 1):
        L.box(b, side * r * 0.75, s * 0.42, r * 0.05, r * 0.42, s * 0.22, r * 1.4, C["moss2"])
    L.cyl(b, 0, s * 0.42, 0, r * 0.9, r * 0.85, 2.0, 9, C["moss2"])
    L.sphere(b, r * 0.6, s * 0.95, -r * 0.6, r * 0.3, C["moss"], squash=(1, 0.6, 1))


def m_jar(b, g, L, s, rng):
    L.sphere(b, 0, 1, 0, s * 0.6, C["stone"], squash=(1.2, 0.35, 1.0))
    top = 1 + s * 0.6 * 0.35 * 0.9
    L.cyl(b, 0, top, 0, s * 0.26, s * 0.26, s * 0.55, 10, C["glass"])
    L.cyl(b, 0, top + s * 0.55, 0, s * 0.2, s * 0.2, s * 0.08, 10, C["glass"])
    L.cyl(b, 0, top + s * 0.63, 0, s * 0.23, s * 0.23, s * 0.08, 10, C["brass"])
    L.box(b, 0, top + s * 0.18, s * 0.25, s * 0.3, s * 0.18, 0.6, C["label"])
    L.sphere(b, 0, top + s * 0.86, 0, s * 0.12, C["white"], squash=(1.4, 0.8, 1.0))


def m_mitten_twig(b, g, L, s, rng):
    L.beam(b, (0, 0, 0), (s * 0.25, s * 2.3, 0), 1.6, C["bark"])
    L.beam(b, (s * 0.18, s * 1.7, 0), (s * 0.85, s * 2.2, 0), 1.1, C["bark"])
    L.beam(b, (s * 0.7, s * 2.12, 0), (s * 0.7, s * 1.86, 0), 0.4, C["thread"])
    L.box(b, s * 0.7, s * 1.0, 0, s * 0.5, s * 0.72, s * 0.22, C["red"])
    L.box(b, s * 1.0, s * 1.2, 0, s * 0.16, s * 0.34, s * 0.2, C["red"])
    L.box(b, s * 0.7, s * 1.68, 0, s * 0.56, s * 0.2, s * 0.26, C["cream"])


def m_root_loops(b, g, L, s, rng):
    pts = []
    for k in range(16):
        a = k * 0.9
        rr = s * (0.12 + 0.024 * k)
        pts.append((math.cos(a) * rr, 0.0, math.sin(a) * rr))
    for p0, p1 in zip(pts, pts[1:]):
        mid = ((p0[0] + p1[0]) / 2, 3.2, (p0[2] + p1[2]) / 2)
        L.beam(b, p0, mid, 2.4, C["root"])
        L.beam(b, mid, p1, 2.4, C["root"])
    L.sphere(b, 0, 1.2, 0, 2.0, C["white"], squash=(1, 0.7, 1))
    for k in (3, 8, 12):
        x, _, z = pts[k]
        L.sphere(b, x, 0.9, z, 1.0, C["black"], squash=(1.3, 0.6, 0.9))


def m_hollow_arch(b, g, L, s, rng):
    L.box(b, 0, 0, -3, s * 0.8, s * 1.05, 6, C["dark"])
    for k in range(9):
        a = math.pi * k / 8
        L.sphere(b, math.cos(a) * s * 0.55, math.sin(a) * s * 1.0, 0, s * 0.24, C["moss"], subdiv=1, rng=rng, jitter=0.15)
    L.disc(b, 0, 0.4, s * 0.5, s * 0.55, 10, C["moss2"])
    L.sphere(g, s * 0.56, s * 0.95, 3, 1.7, C["white"])
    L.sphere(b, s * 0.56, s * 0.95 + 2.2, 3, 1.4, C["shell"])


def m_big_shell(b, g, L, s, rng):
    for k in range(7):
        f = 0.78 ** k
        a = math.radians(k * 65)
        col = C["shell"] if k % 2 == 0 else C["shell2"]
        L.sphere(b, math.cos(a) * s * 0.12 * f, s * 0.28 + (1 - f) * s * 0.62, math.sin(a) * s * 0.12 * f,
                 s * 0.36 * f, col, subdiv=1)
    L.sphere(b, 0, s * 0.22, s * 0.3, s * 0.15, C["dark"], squash=(1, 0.8, 0.5))


def m_web_frame(b, g, L, s, rng):
    H = s * 1.6
    L.beam(b, (-s * 0.5, 0, 0), (-s * 0.6, H, 0), 1.4, C["bark"])
    L.beam(b, (s * 0.5, 0, 0), (s * 0.62, H * 0.95, 0), 1.4, C["bark"])
    cy = H * 0.55
    spokes = [(math.cos(2 * math.pi * k / 10) * s * 0.5, cy + math.sin(2 * math.pi * k / 10) * H * 0.4) for k in range(10)]
    for x, y in spokes:
        L.beam(b, (0, cy, 0), (x, y, 0), 0.3, C["silk"], side=(0, 0, 1))
    for f in (0.35, 0.65, 0.92):
        ring = [(x * f, cy + (y - cy) * f) for x, y in spokes]
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            L.beam(b, (x0, y0, 0), (x1, y1, 0), 0.25, C["silk"], side=(0, 0, 1))
    L.sphere(b, s * 0.05, cy + 1, 0.6, 1.2, C["black"])
    for x, y in spokes[::3]:
        L.sphere(g, x * 0.65, cy + (y - cy) * 0.65, 0.3, 0.5, C["white"])


def m_pebble_line(b, g, L, s, rng):
    length = s * 1.6
    L.box(b, 0, 0, 0, length, 0.5, 4.5, rgb("#c9b48a"))
    for i in range(14):
        x = -length / 2 + i * length / 13
        for side in (-1, 1):
            L.sphere(b, x, 0.6, side * 3.2, 1.1, C["stone"])
    for k in range(5):
        L.sphere(b, -length / 2 + (k + 0.5) * length / 5, 0.9, 0, 1.0, C["black"], squash=(1.3, 0.6, 0.9))
    L.sphere(b, length / 2 + 4, 2, 0, 4.5, C["dstone"], squash=(1, 0.7, 1))


def m_scale(b, g, L, s, rng):
    L.box(b, 0, 0, 0, s * 0.6, 2, s * 0.4, C["bronze"])
    L.cyl(b, 0, 2, 0, 1.2, 1.0, s * 0.9, 6, C["brass"])
    L.beam(b, (-s * 0.55, s * 0.95, 0), (s * 0.55, s * 0.92, 0), 1.2, C["brass"])
    for side, dy in ((-1, 0.0), (1, -1.5)):
        px = side * s * 0.5
        L.beam(b, (px, s * 0.93, 0), (px, s * 0.55 + dy, 0), 0.3, C["brass"])
        L.cyl(b, px, s * 0.5 + dy, 0, s * 0.2, s * 0.24, 1.6, 10, C["brass"])
    for k in range(4):
        L.sphere(b, -s * 0.5 + (k % 2 - 0.5) * 2.4, s * 0.5 + 2.8 + (k // 2) * 1.6, (k % 3 - 1) * 1.2, 1.3, C["berry"])
    for k in range(3):
        L.sphere(b, s * 0.5 + (k - 1) * 1.6, s * 0.5 - 1.5 + 2.0, 0, 0.8, C["seed"])


def m_mushroom_ring(b, g, L, s, rng):
    L.disc(b, 0, 0.35, 0, s * 0.42, 14, C["grass"])
    for k in range(13):
        a = 2 * math.pi * k / 13
        px, pz = math.cos(a) * s * 0.45, math.sin(a) * s * 0.45
        h = 3.4 + (k % 3) * 0.8
        L.cyl(b, px, 0, pz, 0.9, 0.8, h, 5, C["stem"], caps=False)
        L.cyl(b, px, h, pz, 2.6, 0.4, 1.8, 7, C["cap"])


def m_jar_lantern(b, g, L, s, rng):
    H = s * 2.4
    L.beam(b, (0, 0, 0), (0.5, H, 0), 1.2, C["bark"])
    L.beam(b, (0.5, H, 0), (s * 0.7, H + 1.5, 0), 0.9, C["bark"])
    L.beam(b, (s * 0.65, H + 1, 0), (s * 0.65, H - 2.5, 0), 0.3, C["thread"])
    L.cyl(g, s * 0.65, H - 2.5 - s * 0.45, 0, s * 0.22, s * 0.22, s * 0.45, 8, C["white"])
    L.cyl(b, s * 0.65, H - 2.5 - 0.6, 0, s * 0.24, s * 0.24, 0.8, 8, C["brass"])
    for k in range(4):
        a = k * 1.7
        L.box(b, s * 0.65 + math.cos(a) * s * 0.45, H - 3 - s * 0.2 + k * 1.2, math.sin(a) * s * 0.45,
              2.2, 0.3, 1.2, C["moth"], drot=k * 47)


def m_well(b, g, L, s, rng):
    r = s * 0.42
    L.cyl(b, 0, 0, 0, r, r, s * 0.4, 12, C["stone"], top=C["dstone"])
    L.disc(b, 0, s * 0.4 + 0.2, 0, r * 0.78, 12, C["deepwater"])
    for side in (-1, 1):
        L.box(b, side * r * 0.9, s * 0.4, 0, 2.4, s * 0.75, 2.4, C["wood"])
    L.roof(b, 0, s * 1.15, 0, r * 2.4, r * 1.6, s * 0.35, C["roofred"])
    L.beam(b, (-r, s * 0.95, 0), (r, s * 0.95, 0), 1.0, C["wood"])
    L.beam(b, (0, s * 0.95, 0), (0, s * 0.68, 0), 0.3, C["thread"])
    L.cyl(b, 0, s * 0.55, 0, 2.6, 3.0, 3.4, 8, C["wood"])
    for k in range(10):
        a = 2 * math.pi * k / 10
        L.sphere(b, math.cos(a) * r * 0.86, s * 0.4 + 0.4, math.sin(a) * r * 0.86, 0.7, C["chalk"])


def m_stone_circle(b, g, L, s, rng):
    heights = (0.55, 0.75, 0.95, 1.1, 0.85, 0.65, 1.0)
    for k, hf in enumerate(heights):
        a = 2 * math.pi * k / 7 + 0.3
        px, pz = math.cos(a) * s * 0.45, math.sin(a) * s * 0.45
        L.box(b, px, 0, pz, s * 0.14, s * hf, s * 0.09, shade(C["stone"], 0.9 + 0.04 * (k % 3)),
              drot=-math.degrees(a) + 90)
    L.cyl(b, 0, 0, 0, s * 0.12, s * 0.11, 1.5, 7, C["dstone"])


def m_ribbon_tree(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.08, s * 0.06, s * 1.2, 6, C["bark"])
    L.sphere(b, 0, s * 1.45, 0, s * 0.5, C["leaf"], subdiv=1, rng=rng, jitter=0.12)
    for k in range(14):
        a = 2 * math.pi * k / 14
        rr, top = s * 0.38, s * 1.12
        L.beam(b, (math.cos(a) * rr, top, math.sin(a) * rr),
               (math.cos(a) * rr * 1.05, top - s * (0.35 + 0.2 * (k % 3)), math.sin(a) * rr * 1.05),
               1.4, RIBBONS[k % len(RIBBONS)], h=0.3)


def m_bell_frame(b, g, L, s, rng):
    H = s * 1.9
    for side in (-1, 1):
        L.box(b, side * s * 0.45, 0, 0, 2.6, H, 2.6, C["wood"])
    L.box(b, 0, H, 0, s * 1.1, 2.6, 3.2, C["wood"])
    L.roof(b, 0, H + 2.6, 0, s * 1.25, 6, 4, C["roofgreen"])
    L.beam(b, (0, H, 0), (0, H - s * 0.1, 0), 0.6, C["iron"])
    L.cyl(b, 0, H - s * 0.62, 0, s * 0.28, s * 0.16, s * 0.5, 12, C["bronze"], caps=False)
    L.sphere(b, 0, H - s * 0.12, 0, s * 0.17, C["bronze"], squash=(1, 0.6, 1))
    L.cyl(b, 0, H - s * 0.66, 0, s * 0.31, s * 0.3, 1.0, 12, C["bronze"])


def m_flat_stone(b, g, L, s, rng):
    L.sphere(b, 0, 0.5, 0, s * 0.55, C["stone"], subdiv=1, squash=(1.25, 0.18, 1.0))
    top = 0.5 + s * 0.55 * 0.18
    L.disc(b, 0, top + 0.05, -1, s * 0.16, 9, C["dstone"])
    L.disc(b, 0, top + 0.08, -1, s * 0.11, 8, C["water"])
    for k in range(4):
        L.disc(b, (k - 1.5) * s * 0.1, top - 0.05, -1 + s * 0.24, s * 0.05, 6, C["dstone"])
    L.disc(b, s * 0.36, top - 0.4, s * 0.12, s * 0.05, 6, C["dstone"])


def m_swap_box(b, g, L, s, rng):
    H = s * 1.6
    L.box(b, 0, 0, 0, 2.2, H, 2.2, C["wood"])
    L.box(b, 0, H, 0, s * 0.9, s * 0.6, s * 0.6, C["boxblue"])
    L.roof(b, 0, H + s * 0.6, 0, s * 1.05, s * 0.75, s * 0.3, C["roofred"])
    L.box(b, 0, H + s * 0.08, s * 0.3, s * 0.6, s * 0.42, 0.6, C["darkwood"])
    L.sphere(b, s * 0.2, H + s * 0.3, s * 0.32, 0.6, C["brass"])


def m_sundial(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.22, s * 0.18, s * 0.75, 8, C["stone"])
    top = s * 0.75 + 1.6
    L.cyl(b, 0, s * 0.75, 0, s * 0.45, s * 0.45, 1.6, 12, C["dstone"], top=rgb("#9fae8a"))
    L.beam(b, (0, top, -s * 0.3), (0, top + s * 0.32, -s * 0.05), 1.0, C["bronze"])
    L.beam(b, (0, top + s * 0.32, -s * 0.05), (0, top, s * 0.15), 1.0, C["bronze"])
    for k in range(8):
        a = math.pi * k / 7
        L.box(b, math.cos(a) * s * 0.36, top, -math.sin(a) * s * 0.36 + s * 0.05, 1.0, 0.3, 1.0, C["dark"])
    L.sphere(b, s * 0.3, top, s * 0.2, s * 0.1, C["moss"], squash=(1, 0.5, 1))


def m_clock_post(b, g, L, s, rng):
    H = s * 4.2
    L.cyl(b, 0, 0, 0, s * 0.32, s * 0.3, 3, 8, C["postgreen"])
    L.cyl(b, 0, 0, 0, s * 0.22, s * 0.16, H, 8, C["postgreen"])
    L.box(b, 0, H, 0, s * 0.95, s * 0.95, s * 0.5, C["postgreen"])
    cy = H + s * 0.47
    for zf, flip in ((s * 0.26, 1), (-s * 0.26, -1)):
        L.box(b, 0, H + s * 0.08, zf, s * 0.78, s * 0.78, 0.6, C["clockface"])
        for ang, ln in ((128.5, s * 0.22), (102.0, s * 0.33)):
            a = math.radians(ang)
            z = zf + 0.5 * flip
            L.beam(b, (0, cy, z), (math.sin(a) * ln * flip, cy + math.cos(a) * ln, z), 0.8, C["dark"], h=0.4)
    L.sphere(b, 0, H + s * 0.95 + 1.5, 0, 1.6, C["brass"])


def m_statue(b, g, L, s, rng):
    L.box(b, 0, 0, 0, s * 0.9, s * 0.6, s * 0.9, C["stone"])
    L.box(b, 0, s * 0.6, 0, s, 1.5, s, C["dstone"])
    L.box(b, 0, s * 0.2, s * 0.45, s * 0.5, s * 0.2, 0.6, C["bronze"])
    y0 = s * 0.6 + 1.5
    st, light = C["statue"], C["statue_light"]
    L.sphere(b, 0, y0 + s * 0.45, 0, s * 0.34, st, subdiv=1, squash=(1, 1.25, 0.9))
    L.sphere(b, 0, y0 + s * 0.98, s * 0.05, s * 0.2, st, subdiv=1)
    L.sphere(b, 0, y0 + s * 0.94, s * 0.22, s * 0.09, st)
    L.box(b, 0, y0 + s * 0.9, s * 0.02, s * 0.07, s * 0.28, s * 0.4, light)
    for side in (-1, 1):
        L.sphere(b, side * s * 0.13, y0 + s * 1.15, 0, s * 0.06, st)
        L.sphere(b, side * s * 0.15, y0 + 2, s * 0.1, s * 0.1, st, squash=(1, 0.6, 1.3))
    L.beam(b, (s * 0.25, y0 + s * 0.6, 0), (s * 0.42, y0 + s * 0.95, s * 0.1), s * 0.09, st)
    L.box(b, s * 0.44, y0 + s * 0.95, s * 0.1, s * 0.14, s * 0.04, s * 0.14, st)
    L.box(g, s * 0.44, y0 + s * 0.99, s * 0.1, s * 0.1, s * 0.13, s * 0.1, C["white"])
    L.box(b, s * 0.44, y0 + s * 1.12, s * 0.1, s * 0.15, s * 0.04, s * 0.15, st)
    L.sphere(b, s * 0.44, y0 + s * 1.2, s * 0.1, s * 0.05, C["pink"])
    L.box(b, -s * 0.3, y0 + s * 0.45, s * 0.22, s * 0.24, s * 0.3, s * 0.06, st, drot=20)


def m_signpost(b, g, L, s, rng):
    H = s * 3.6
    L.beam(b, (0, 0, 0), (s * 0.25, H, 0), 2.0, C["wood"])
    for frac, yaw, col in ((0.88, 30, C["cream"]), (0.74, -65, rgb("#e8d9b0")), (0.6, 140, rgb("#f0e2c2"))):
        cx, cy = s * 0.25 * frac, H * frac
        dx, dz = rotate_y(1, 0, yaw)
        end = (cx + dx * s * 1.1, cy, dz * s * 1.1)
        L.beam(b, (cx - dx * 1.5, cy, -dz * 1.5), end, 1.0, col, h=s * 0.32)
        L.tube(b, end, (end[0] + dx * s * 0.28, cy, end[2] + dz * s * 0.28), s * 0.22, 0.0, 4, col)
    L.sphere(b, s * 0.25, H + 1.2, 0, 1.6, C["darkwood"])


def m_chalk_map(b, g, L, s, rng):
    L.box(b, 0, 0, 0, s * 1.0, 1.4, s * 0.8, C["paving"])
    y = 1.42
    L.ring(b, (0, y, 0), s * 0.34, "xz", 14, 0.7, C["chalk"], h=0.12)
    for (x, z, col) in ((-0.15, -0.1, "red"), (0.12, -0.15, "boxblue"), (0.05, 0.14, "moss2"), (-0.18, 0.12, "brass"),
                        (0.2, 0.05, "pink"), (0.0, 0.0, "stone")):
        L.disc(b, x * s, y + 0.06, z * s, s * 0.045, 6, C[col])
        L.beam(b, (0, y + 0.03, 0), (x * s, y + 0.03, z * s), 0.5, C["chalk"], h=0.08)
    L.disc(b, s * 0.36, y + 0.05, -s * 0.28, s * 0.07, 8, C["ocean"])
    L.disc(b, -s * 0.42, y + 0.05, s * 0.3, s * 0.04, 6, C["planet_blue"])
    L.beam(b, (s * 0.38, y + 0.05, s * 0.18), (s * 0.42, y + 0.05, s * 0.26), 0.6, C["chalk"], h=0.08)
    L.disc(b, s * 0.4, y + 0.06, s * 0.31, 0.5, 5, C["chalk"])


def m_carved_bench(b, g, L, s, rng):
    L.box(b, 0, s * 0.38, 0, s * 1.5, s * 0.08, s * 0.42, C["wood"])
    for lx in (-0.6, 0.6):
        for lz in (-0.15, 0.15):
            L.box(b, lx * s, 0, lz * s, s * 0.08, s * 0.38, s * 0.08, C["darkwood"])
    L.box(b, 0, s * 0.46, -s * 0.19, s * 1.5, s * 0.48, s * 0.06, C["wood2"])
    for k in range(12):
        L.box(b, (-0.6 + (k % 4) * 0.36) * s + (k // 4) * 2, s * (0.58 + 0.1 * (k // 4)), -s * 0.155,
              s * 0.16, s * 0.03, 0.4, C["cream"])


def m_post_box(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.38, s * 0.38, s * 0.12, 12, C["postred"])
    L.cyl(b, 0, 0, 0, s * 0.34, s * 0.32, s * 1.15, 12, C["postred"])
    x, y, z = L.p(0, s * 1.15, 0)
    b.dome(x, y, z, s * 0.33, 12, 3, C["postred"])
    L.box(b, 0, s * 0.85, s * 0.31, s * 0.32, s * 0.06, 1.0, C["black"])
    L.box(b, 0, s * 0.5, s * 0.32, s * 0.22, s * 0.16, 0.6, C["cream"])


def m_umbrella(b, g, L, s, rng):
    H = s * 1.2
    L.beam(b, (0, 0, 0), (0.6, H + s * 0.15, 0), 0.9, C["dark"])
    apex = (0.6, H + s * 0.18, 0)
    rim = [(0.6 + math.cos(2 * math.pi * k / 8) * s * 0.62, H - s * 0.18, math.sin(2 * math.pi * k / 8) * s * 0.62)
           for k in range(8)]
    for k in range(8):
        L.tri2(b, apex, rim[k], rim[(k + 1) % 8], C["red"] if k % 2 == 0 else C["cream"])
    L.beam(b, (0, 0, 0), (-1.2, 1.5, 0), 0.9, C["dark"])


def m_coin(b, g, L, s, rng):
    L.cyl(b, 0, 17.05, 0, s * 0.7, s * 0.7, 0.5, 12, C["gold"], top=rgb("#f7d36a"))


def m_teapot_post(b, g, L, s, rng):
    H = s * 1.7
    L.box(b, 0, 0, 0, 2.2, H, 2.2, C["wood"])
    L.box(b, 0, H, 0, s * 0.62, 1.2, s * 0.62, C["wood"])
    base = H + 1.2
    L.sphere(b, 0, base + s * 0.3, 0, s * 0.4, C["teablue"], subdiv=1, squash=(1.1, 0.8, 1.1))
    L.cyl(b, 0, base + s * 0.58, 0, s * 0.2, s * 0.16, s * 0.08, 10, C["teablue"])
    L.sphere(b, 0, base + s * 0.7, 0, s * 0.06, C["cream"])
    L.tube(b, (s * 0.35, base + s * 0.22, 0), (s * 0.7, base + s * 0.52, 0), s * 0.09, s * 0.05, 6, C["teablue"])
    L.beam(b, (-s * 0.38, base + s * 0.45, 0), (-s * 0.6, base + s * 0.4, 0), 1.2, C["teablue"])
    L.beam(b, (-s * 0.6, base + s * 0.4, 0), (-s * 0.55, base + s * 0.12, 0), 1.2, C["teablue"])
    L.beam(b, (-s * 0.55, base + s * 0.12, 0), (-s * 0.36, base + s * 0.15, 0), 1.2, C["teablue"])
    L.box(b, 0, base + s * 0.36, s * 0.42, s * 0.3, s * 0.04, 0.6, C["cream"])


def m_chalkboard(b, g, L, s, rng):
    bot, top = (0, s * 0.1, s * 0.18), (0, s * 1.5, 0)
    L.beam(b, (0, 0, s * 0.2), top, s * 1.08, C["wood"], h=0.8)
    L.beam(b, (bot[0], bot[1], bot[2] + 0.5), (top[0], top[1] - s * 0.06, 0.5), s * 0.96, C["slate"], h=0.4)
    L.beam(b, (0, 0, -s * 0.38), top, s * 1.0, C["wood"], h=0.8)
    n = (0.0, 0.128, 0.992)
    for k, col in enumerate(("chalk", "yellow", "chalk", "pink", "chalk", "moss2", "chalk", "chalk")):
        t = 0.2 + 0.1 * k
        u = (k % 3 - 1) * s * 0.28
        y = bot[1] + (top[1] - bot[1]) * t
        z = bot[2] * (1 - t) + 0.9
        L.box(b, u, y, z + n[2] * 0.2, s * (0.16 if col == "chalk" else 0.08), 0.5, 0.3, C[col])


def m_birdbath(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.3, s * 0.3, 1.5, 10, C["stone"])
    L.cyl(b, 0, 1.5, 0, s * 0.12, s * 0.1, s * 0.6, 8, C["stone"])
    top = 1.5 + s * 0.6
    L.cyl(b, 0, top, 0, s * 0.15, s * 0.48, s * 0.16, 12, C["stone"], top=C["water"])
    for k in range(9):
        a = 2 * math.pi * k / 9
        L.box(b, math.cos(a) * s * 0.44, top + s * 0.16, math.sin(a) * s * 0.44, 0.9, 0.5, 0.9, C["seed"], drot=k * 33)
    L.sphere(b, 0, top + s * 0.17, 0, 0.8, rgb("#5a3a1a"))


def m_jar_pyramid(b, g, L, s, rng):
    L.box(b, 0, 0, 0, s * 1.0, s * 0.25, s * 0.4, C["wood"])
    r, h = s * 0.075, s * 0.18
    pitch = r * 2.15
    y0 = s * 0.25
    idx = 0
    for row in range(6):
        n = 6 - row
        for i in range(n):
            x = (i - (n - 1) / 2) * pitch
            y = y0 + row * (h + 0.45)
            col = rgb("#f08a4a") if row == 5 else JAMS[idx % len(JAMS)]
            L.cyl(b, x, y, 0, r, r, h, 7, col)
            L.cyl(b, x, y + h, 0, r * 0.9, r * 0.9, 0.45, 7, C["gold"])
            idx += 1


def m_bicycle(b, g, L, s, rng):
    R = s * 0.3
    cy = R + 0.6
    col = C["bikegreen"]
    for cx in (-s * 0.5, s * 0.5):
        L.ring(b, (cx, cy, 0), R, "xy", 12, 1.0, C["dark"], h=1.4)
        for k in range(3):
            a = math.pi * k / 3
            L.beam(b, (cx - math.cos(a) * R, cy - math.sin(a) * R, 0), (cx + math.cos(a) * R, cy + math.sin(a) * R, 0),
                   0.25, C["silver"], side=(0, 0, 1))
    rear, front = (-s * 0.5, cy, 0), (s * 0.5, cy, 0)
    seat, head, pedal = (-s * 0.12, cy + R * 1.15, 0), (s * 0.36, cy + R * 1.25, 0), (0, cy, 0)
    for p0, p1 in ((rear, seat), (seat, head), (head, front), (rear, pedal), (pedal, seat), (pedal, head)):
        L.beam(b, p0, p1, 1.2, col)
    L.box(b, seat[0], seat[1] + 0.6, 0, s * 0.18, 1.2, s * 0.1, C["dark"])
    L.beam(b, (head[0], head[1] + 2, -s * 0.18), (head[0], head[1] + 2, s * 0.18), 0.9, C["dark"])
    L.box(b, s * 0.56, cy + R * 1.0, 0, s * 0.32, s * 0.22, s * 0.3, C["wicker"])
    L.box(b, s * 0.56, cy + R * 1.0 + s * 0.12, 0, s * 0.24, 1.2, s * 0.22, C["red"])
    L.box(b, s * 0.44, cy + R * 1.33, s * 0.05, 1.2, 1.2, 1.2, C["brass"])


def m_herb_patch(b, g, L, s, rng):
    L.box(b, 0, 0, 0, s * 1.0, 1.6, s * 0.6, C["soil"])
    for i in range(5):
        for j in range(3):
            x, z = (i - 2) * s * 0.19, (j - 1) * s * 0.18
            col = C["mint"] if j == 0 else C["thyme"] if j == 1 else rgb("#6f9f4a")
            L.sphere(b, x, 2.6, z, 2.0 + 0.3 * ((i + j) % 3), col, squash=(1, 0.8, 1), rng=rng, jitter=0.15)
    for k in range(4):
        x, z = (k - 1.5) * s * 0.22, s * 0.27
        L.beam(b, (x, 1.6, z), (x, 5.5, z), 0.3, C["mint"])
        L.sphere(b, x, 5.8, z, 0.9, C["yellow"])
    sx, sz = s * 0.42, -s * 0.22
    L.beam(b, (sx, 1.6, sz), (sx, 9, sz), 0.5, C["silver"])
    L.sphere(b, sx, 9.8, sz, 1.1, C["silver"], squash=(1, 1.3, 0.5))
    L.beam(b, (sx - 2, 7.5, sz), (sx + 2, 7.5, sz), 0.4, C["silver"])
    L.beam(b, (-s * 0.42, 1.6, s * 0.2), (-s * 0.42, 6, s * 0.2), 0.4, C["wood"])
    L.box(b, -s * 0.42, 5.2, s * 0.2 + 0.4, 3, 1.6, 0.3, C["label"])


_LETTERS = {
    "K": [((0, 0), (0, 1)), ((0.05, 0.5), (1, 1)), ((0.3, 0.62), (1, 0))],
    "W": [((0, 1), (0.25, 0)), ((0.25, 0), (0.5, 0.65)), ((0.5, 0.65), (0.75, 0)), ((0.75, 0), (1, 1))],
    "E": [((0, 0), (0, 1)), ((0, 1), (1, 1)), ((0, 0.5), (0.8, 0.5)), ((0, 0), (1, 0))],
    "Z": [((0, 1), (1, 1)), ((1, 1), (1, 0.5)), ((1, 0.5), (0, 0.5)), ((0, 0.5), (0, 0)), ((0, 0), (1, 0))],
}


def m_big_letters(b, g, L, s, rng):
    hl, wl = s * 1.0, s * 0.55
    th = s * 0.17
    colours = (C["cream"], C["red"], C["boxblue"], C["yellow"])
    for n, (ch, col) in enumerate(zip("KWEZ", colours)):
        cx = (n - 1.5) * s * 0.78
        for (u0, v0), (u1, v1) in _LETTERS[ch]:
            p0 = (cx + (u0 - 0.5) * wl, th / 2 + v0 * (hl - th), -v0 * hl * 0.12)
            p1 = (cx + (u1 - 0.5) * wl, th / 2 + v1 * (hl - th), -v1 * hl * 0.12)
            if abs(u1 - u0) < 1e-6 and abs(v1 - v0) < 1e-6:
                continue
            ex = ((p1[0] - p0[0]), (p1[1] - p0[1]), (p1[2] - p0[2]))
            length = math.sqrt(sum(k * k for k in ex)) or 1
            pad = th / 2 / length
            q0 = tuple(p0[k] - ex[k] * pad for k in range(3))
            q1 = tuple(p1[k] + ex[k] * pad for k in range(3))
            L.beam(b, q0, q1, s * 0.14, col, h=th, side=(0, 0.12, 1))


def m_puddle(b, g, L, s, rng):
    for dx, dz, r in ((0, 0, 0.5), (0.35, 0.15, 0.3), (-0.3, 0.2, 0.32), (0.1, -0.35, 0.28), (-0.25, -0.25, 0.22)):
        L.disc(b, dx * s, 0.35, dz * s, r * s, 10, C["ink"])
    for dx, dz in ((0.1, 0.05), (-0.18, 0.12), (0.25, -0.1)):
        L.disc(g, dx * s, 0.45, dz * s, s * 0.03, 5, C["white"])


def m_kite_pole(b, g, L, s, rng):
    H = s * 4.4
    L.cyl(b, 0, 0, 0, 1.6, 1.2, H, 6, C["wood"])
    cx, cy, cz = s * 0.4, H - s * 0.1, 1.0
    top, right, bot, left = (cx, cy + s * 0.55, cz), (cx + s * 0.38, cy + s * 0.1, cz), (cx, cy - s * 0.5, cz), (cx - s * 0.38, cy + s * 0.1, cz)
    centre = (cx, cy + s * 0.05, cz)
    for k, (p0, p1) in enumerate(((top, right), (right, bot), (bot, left), (left, top))):
        L.tri2(b, centre, p0, p1, C["red"] if k % 2 == 0 else C["kiteyellow"])
    L.beam(b, top, bot, 0.5, C["wood"])
    L.beam(b, left, right, 0.5, C["wood"])
    prev = bot
    for k in range(6):
        nxt = (bot[0] + (2.5 if k % 2 == 0 else -2.5), bot[1] - (k + 1) * s * 0.28, cz)
        L.beam(b, prev, nxt, 0.3, C["thread"])
        L.box(b, nxt[0], nxt[1] - 0.6, cz, 2.4, 1.2, 0.4, RIBBONS[k % len(RIBBONS)])
        prev = nxt
    L.beam(b, centre, (0, H, 0), 0.25, C["thread"])


def m_wheel_planter(b, g, L, s, rng):
    r = s * 0.45
    L.disc(b, 0, 1.0, 0, r * 0.95, 12, C["soil"])
    L.ring(b, (0, 1.8, 0), r, "xz", 12, 1.6, C["iron"], h=2.4)
    L.cyl(b, 0, 0, 0, s * 0.08, s * 0.08, 3.5, 8, C["iron"])
    for k in range(6):
        a = math.pi * k / 3
        L.beam(b, (0, 2.2, 0), (math.cos(a) * r, 2.2, math.sin(a) * r), 1.0, C["iron"])
    cols = (C["orange"], C["red"], C["yellow"])
    for k in range(14):
        a = 2 * math.pi * k / 14 + 0.2
        rr = r * (0.35 + 0.4 * (k % 3) / 2)
        L.disc(b, math.cos(a) * rr, 2.6, math.sin(a) * rr, 1.8, 6, C["leaf"])
        L.sphere(b, math.cos(a) * rr, 3.4, math.sin(a) * rr, 1.2, cols[k % 3])


def m_poster_board(b, g, L, s, rng):
    for side in (-1, 1):
        L.box(b, side * s * 0.62, 0, 0, 2.2, s * 1.55, 2.2, C["darkwood"])
    L.box(b, 0, s * 0.45, 0, s * 1.2, s * 1.0, 1.6, C["wood2"])
    L.roof(b, 0, s * 1.55, 0, s * 1.4, 4, 3, C["roofgreen"])
    posters = ((-0.35, 0.62, 0.42, 0.5, "cream"), (0.2, 0.7, 0.5, 0.42, "ribbon3"), (-0.1, 0.9, 0.36, 0.3, "ribbon2"),
               (0.35, 1.1, 0.34, 0.3, "pink"), (-0.38, 1.12, 0.36, 0.32, "label"), (0.05, 0.5, 0.3, 0.26, "ribbon4"))
    for k, (x, y, w, h, col) in enumerate(posters):
        L.box(b, x * s, y * s, 0.85 + k * 0.08, w * s, h * s, 0.3, C[col])
        L.box(b, x * s, (y + h * 0.55) * s, 0.9 + k * 0.08 + 0.2, w * s * 0.6, 0.6, 0.2, C["dark"])


def m_pot_steps(b, g, L, s, rng):
    cols = [C["paint1"], C["paint2"], C["paint3"], C["paint4"], C["paint5"], C["paint6"], C["silver"]]
    for k, col in enumerate(cols):
        t = k / 6
        x = (t - 0.5) * s * 1.6
        z = math.sin(t * math.pi) * s * 0.35
        L.cyl(b, x, 0, z, s * 0.1, s * 0.09, s * 0.14, 9, col)
        L.disc(b, x + s * 0.12, 0.25, z + s * 0.05, s * 0.05, 6, col)


def m_telescope(b, g, L, s, rng):
    top = (0, s * 1.15, 0)
    for a in (90, 210, 330):
        x, z = math.cos(math.radians(a)) * s * 0.4, math.sin(math.radians(a)) * s * 0.4
        L.beam(b, top, (x, 0, z), 1.2, C["wood"])
    L.tube(b, (-s * 0.35, s * 1.0, s * 0.25), (s * 0.5, s * 1.55, -s * 0.35), s * 0.1, s * 0.14, 8, C["brass"])
    L.tube(b, (-s * 0.35, s * 1.0, s * 0.25), (-s * 0.48, s * 0.92, s * 0.34), s * 0.05, s * 0.05, 6, C["bronze"])
    for t in (0.35, 0.7):
        p = (-s * 0.35 + s * 0.85 * t, s * 1.0 + s * 0.55 * t, s * 0.25 - s * 0.6 * t)
        q = (p[0] + s * 0.04, p[1] + s * 0.026, p[2] - s * 0.028)
        L.tube(b, p, q, s * 0.135 + 0.6, s * 0.135 + 0.6, 8, C["bronze"])


def m_book_box(b, g, L, s, rng):
    H = s * 1.5
    L.box(b, 0, 0, 0, 2.2, H, 2.2, C["wood"])
    L.box(b, 0, H, 0, s * 0.95, s * 0.8, s * 0.5, C["roofred"])
    L.roof(b, 0, H + s * 0.8, 0, s * 1.1, s * 0.65, s * 0.32, C["darkwood"])
    L.box(g, 0, H + s * 0.08, s * 0.24, s * 0.8, s * 0.62, 0.5, C["white"])
    for k, col in enumerate((C["paint5"], C["paint1"], C["paint4"], C["paint3"], C["paint6"])):
        L.box(b, (k - 2) * s * 0.15, H + s * 0.1, s * 0.27, s * 0.11, s * (0.36 + 0.06 * (k % 2)), s * 0.12, col)


def m_orrery(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.3, s * 0.32, 1.5, 10, C["darkwood"])
    L.cyl(b, 0, 1.5, 0, s * 0.05, s * 0.05, s * 0.8, 6, C["brass"])
    L.sphere(g, 0, s * 0.95, 0, s * 0.12, C["white"], subdiv=1)
    planets = ((0.22, "stone", 0.035, 20), (0.32, "pink", 0.045, 95), (0.42, "ocean", 0.05, 170), (0.52, "red", 0.04, 240),
               (0.64, "brass", 0.07, 310), (0.76, "planet_blue", 0.055, 45))
    for k, (dist, col, r, ang) in enumerate(planets):
        y = s * (0.8 + 0.03 * k)
        a = math.radians(ang)
        end = (math.cos(a) * dist * s, y, math.sin(a) * dist * s)
        L.beam(b, (0, y, 0), end, 0.5, C["brass"])
        L.beam(b, end, (end[0], y + 2, end[2]), 0.4, C["brass"])
        L.sphere(b, end[0], y + 2 + r * s, end[2], r * s, C[col], subdiv=1)
        if col == "brass":
            L.disc(b, end[0], y + 2 + r * s, end[2], r * s * 1.8, 10, C["cream"])


def m_flat_rock(b, g, L, s, rng):
    L.sphere(b, 0, 2, 0, s * 0.55, rgb("#b3a996"), subdiv=1, squash=(1.2, 0.42, 1.0), rng=rng, jitter=0.04)
    L.disc(b, 0, 2 + s * 0.55 * 0.42 - 0.2, 0, s * 0.14, 8, rgb("#9c937f"))
    L.sphere(b, -s * 0.4, 1.5, s * 0.2, s * 0.12, C["moss"], squash=(1, 0.5, 1))


def m_globe_stand(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.3, s * 0.2, 2, 8, C["darkwood"])
    L.cyl(b, 0, 2, 0, s * 0.06, s * 0.06, s * 0.7, 6, C["darkwood"])
    cy = s * 1.05
    L.sphere(b, 0, cy, 0, s * 0.32, C["ocean"], subdiv=2)
    for dx, dy, dz in ((0.6, 0.4, 0.7), (-0.8, 0.1, 0.5), (0.2, -0.5, 0.8), (-0.3, 0.7, -0.6), (0.9, -0.2, -0.3)):
        n = math.sqrt(dx * dx + dy * dy + dz * dz)
        L.sphere(b, dx / n * s * 0.3, cy + dy / n * s * 0.3, dz / n * s * 0.3, s * 0.1, C["land"], squash=(1, 0.8, 1))
    L.ring(b, (0, cy, 0), s * 0.37, "xy", 14, 0.8, C["brass"])
    L.beam(b, (-s * 0.1, cy + s * 0.3, s * 0.12), (s * 0.15, cy - s * 0.05, s * 0.29), 0.3, C["dark"])


def m_inkwell(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.42, s * 0.4, s * 0.32, 12, C["stone"])
    L.cyl(b, 0, s * 0.32, 0, s * 0.4, s * 0.18, s * 0.14, 12, C["stone"])
    L.cyl(b, 0, s * 0.46, 0, s * 0.18, s * 0.2, s * 0.1, 10, C["stone"], top=rgb("#3a5a8a"))
    p0, p1 = (s * 0.05, s * 0.45, 0), (s * 0.45, s * 1.6, -s * 0.25)
    L.tube(b, p0, p1, 0.7, 0.3, 5, C["quill"])
    mid = tuple(p0[k] + (p1[k] - p0[k]) * 0.45 for k in range(3))
    L.beam(b, mid, p1, 0.4, C["quill"], h=s * 0.22, side=(0, 0, 1))


def m_lily_pad(b, g, L, s, rng):
    L.disc(b, 0, 1.3, 0, s * 0.9, 12, C["lily"])
    L.sphere(b, 0, 3.4, 0, 3.0, C["frog"], squash=(1, 0.75, 1.1))
    for side in (-1, 1):
        L.sphere(b, side * 1.4, 5.4, 1.4, 1.1, C["frog"])
        L.sphere(b, side * 1.4, 5.6, 2.3, 0.45, C["black"])
    L.sphere(b, s * 0.68, 1.9, 0, 1.4, C["pink"])
    L.sphere(b, s * 0.68, 2.9, 0, 0.7, C["yellow"])


def m_walnut_boat(b, g, L, s, rng):
    L.sphere(b, 0, 1.0, 0, s * 0.45, C["walnut"], subdiv=1, squash=(1.2, 0.45, 1.0), rng=rng, jitter=0.08)
    L.beam(b, (0, 1.5, 0), (0, s * 1.4, 0), 0.6, C["wood"])
    L.tri2(b, (0, s * 1.35, 0.4), (0, s * 0.35, 0.4), (s * 0.55, s * 0.45, 0.4), C["leaf"])
    L.sphere(b, -s * 0.22, 2.6, 0, 1.1, C["black"])


def m_stepping_stones(b, g, L, s, rng):
    for i in range(7):
        x = -84 + i * 28
        y = 1.6 if i == 3 else 1.0
        L.sphere(b, x, y, (i % 2) * 4 - 2, 6.5, shade(C["stone"], 0.92 + 0.03 * (i % 3)), subdiv=1,
                 squash=(1.1, 0.32, 1.0), rng=rng, jitter=0.08)


def m_reeds(b, g, L, s, rng):
    for k in range(14):
        a, rr = rng.uniform(0, 2 * math.pi), rng.uniform(0, s * 0.45)
        x, z = math.cos(a) * rr, math.sin(a) * rr
        h = rng.uniform(16, 30)
        L.cyl(b, x, 0, z, 0.7, 0.4, h, 4, C["reed"], caps=False)
        if k % 2 == 0:
            L.cyl(b, x, h - 5, z, 1.2, 1.2, 5, 6, C["cattail"])
    for k in range(5):
        a = rng.uniform(0, 2 * math.pi)
        L.beam(b, (0, 0, 0), (math.cos(a) * 8, 14, math.sin(a) * 8), 1.4, C["reed"], h=0.3)


def m_lighthouse(b, g, L, s, rng):
    H = s * 3.6
    L.cyl(b, 0, 0, 0, s * 0.6, s * 0.55, s * 0.25, 10, C["stone"])
    y = s * 0.25
    bands = 5
    for k in range(bands):
        r0 = s * (0.42 - 0.14 * k / bands)
        r1 = s * (0.42 - 0.14 * (k + 1) / bands)
        h = (H - s * 0.25) / bands
        L.cyl(b, 0, y, 0, r0, r1, h, 10, C["red"] if k % 2 == 0 else C["white"], caps=False)
        y += h
    L.cyl(b, 0, H, 0, s * 0.4, s * 0.4, 1.6, 10, C["dark"])
    L.cyl(g, 0, H + 1.6, 0, s * 0.22, s * 0.22, s * 0.35, 8, C["white"])
    for k in range(4):
        a = math.pi / 2 * k + math.pi / 4
        L.beam(b, (math.cos(a) * s * 0.23, H + 1.6, math.sin(a) * s * 0.23),
               (math.cos(a) * s * 0.23, H + 1.6 + s * 0.35, math.sin(a) * s * 0.23), 0.8, C["dark"])
    L.cyl(b, 0, H + 1.6 + s * 0.35, 0, s * 0.3, 0.0, s * 0.3, 8, C["red"])
    L.box(b, 0, s * 0.25, s * 0.38, s * 0.18, s * 0.32, 2, C["darkwood"])


def m_windmill(b, g, L, s, rng):
    H = s * 2.6
    L.cyl(b, 0, 0, 0, s * 0.5, s * 0.34, H, 8, C["whitewash"])
    L.cyl(b, 0, H, 0, s * 0.4, 0.0, s * 0.42, 8, C["roofbrown"])
    L.box(b, 0, 0, s * 0.46, s * 0.24, s * 0.45, 2.5, C["darkwood"])
    L.box(g, 0, H * 0.55, s * 0.4, s * 0.14, s * 0.18, 2, C["white"])
    hub = (0, H * 0.9, s * 0.56)
    L.tube(b, (0, H * 0.9, s * 0.3), hub, s * 0.07, s * 0.07, 6, C["darkwood"])
    for k in range(4):
        a = math.radians(45 + 90 * k)
        ux, uy = math.cos(a), math.sin(a)
        tip = (hub[0] + ux * s * 1.45, hub[1] + uy * s * 1.45, hub[2])
        L.beam(b, hub, tip, 1.0, C["darkwood"], h=1.4, side=(0, 0, 1))
        px, py = -uy * s * 0.17, ux * s * 0.17
        p0 = (hub[0] + ux * s * 0.35 + px, hub[1] + uy * s * 0.35 + py, hub[2] + 0.4)
        p1 = (hub[0] + ux * s * 1.4 + px, hub[1] + uy * s * 1.4 + py, hub[2] + 0.4)
        L.beam(b, p0, p1, 0.5, C["cream"], h=s * 0.3, side=(0, 0, 1))


def m_bottle(b, g, L, s, rng):
    def bottle(ox, oz, yaw, scale, cork):
        def P(lx):
            dx, dz = rotate_y(lx * scale, 0, yaw)
            return (ox + dx, s * 0.2 * scale, oz + dz)
        L.tube(b, P(-s * 0.5), P(s * 0.25), s * 0.2 * scale, s * 0.2 * scale, 8, C["bottle"])
        L.tube(b, P(s * 0.25), P(s * 0.42), s * 0.2 * scale, s * 0.08 * scale, 8, C["bottle"], caps=False)
        L.tube(b, P(s * 0.42), P(s * 0.62), s * 0.08 * scale, s * 0.08 * scale, 6, C["bottle"])
        L.tube(b, P(s * 0.62), P(s * 0.72), s * 0.075 * scale, s * 0.075 * scale, 6, cork)
    bottle(0, 0, 0, 1.0, C["cork"])
    bottle(s * 0.3, s * 0.65, 35, 0.8, C["red"])


def m_rowboat(b, g, L, s, rng):
    r = s * 0.24
    L.tube(b, (-s * 0.45, 1.5, 0), (s * 0.3, 1.5, 0), r, r, 10, C["boat"])
    L.tube(b, (s * 0.3, 1.5, 0), (s * 0.62, 2.5, 0), r, 0.0, 10, C["boat"])
    L.beam(b, (-s * 0.45, 1.5 + r, 0), (s * 0.58, 2.0 + r * 0.6, 0), 1.2, C["darkwood"])
    L.beam(b, (-s * 0.2, 1.5 + r * 0.7, r * 0.7), (s * 0.3, 1.5 + r * 0.7, r * 0.7), 0.8, C["cream"])
    for k in range(3):
        L.sphere(b, -s * 0.52 - k * 3, 1.0, r * 0.4 - k * 2.5, 1.4, C["crab"], squash=(1.3, 0.6, 1))
    for k in range(5):
        L.sphere(b, -s * 0.5, 0.8, -r * 0.9 + k * 2.2, 1.0, C["shell"], squash=(1, 0.6, 1))


def m_treehouse(b, g, L, s, rng):
    L.cyl(b, 0, 0, 0, s * 0.22, s * 0.17, s * 2.7, 8, C["bark"])
    for dx, dy, dz, r in ((0, 3.0, 0, 0.78), (-0.55, 2.6, 0.25, 0.5), (0.6, 2.7, -0.2, 0.55)):
        L.sphere(b, dx * s, dy * s, dz * s, r * s, C["leaf"], subdiv=1, rng=rng, jitter=0.14)
    py = s * 1.5
    L.box(b, 0, py, 0, s * 1.15, 2, s * 1.0, C["wood"])
    L.box(b, 0, py + 2, -s * 0.05, s * 0.8, s * 0.6, s * 0.7, C["wood2"])
    L.roof(b, 0, py + 2 + s * 0.6, -s * 0.05, s * 0.95, s * 0.9, s * 0.32, C["roofred"])
    L.box(g, s * 0.15, py + 2 + s * 0.25, s * 0.31, s * 0.18, s * 0.16, 0.5, C["white"])
    L.box(b, -s * 0.2, py + 2 + s * 0.12, s * 0.31, s * 0.18, s * 0.36, 0.6, C["darkwood"])
    L.box(b, s * 0.35, py + 2, s * 0.48, s * 0.3, s * 0.12, 0.6, C["cream"])
    for side in (-1, 1):
        L.beam(b, (side * s * 0.12, py, s * 0.5), (side * s * 0.12, 0, s * 0.62), 0.6, C["thread"])
    for k in range(7):
        t = (k + 0.5) / 7
        L.beam(b, (-s * 0.12, py * (1 - t), s * (0.5 + 0.12 * t)), (s * 0.12, py * (1 - t), s * (0.5 + 0.12 * t)),
               0.8, C["wood"])


def m_scarecrow(b, g, L, s, rng):
    H = s * 2.6
    L.box(b, 0, 0, 0, 2.2, H * 0.8, 2.2, C["wood"])
    L.box(b, 0, H * 0.3, 0, s * 0.55, H * 0.42, s * 0.3, C["shirt"])
    L.beam(b, (-s * 0.72, H * 0.67, 0), (s * 0.72, H * 0.67, 0), s * 0.2, C["shirt"])
    for side in (-1, 1):
        for k in range(3):
            L.beam(b, (side * s * 0.72, H * 0.67, 0), (side * s * (0.82 + 0.03 * k), H * (0.6 + 0.04 * k), (k - 1) * 1.2),
                   0.5, C["straw"])
    L.box(b, 0, H * 0.74, 0, s * 0.42, s * 0.1, s * 0.36, C["red"])
    L.beam(b, (s * 0.12, H * 0.76, s * 0.16), (s * 0.18, H * 0.55, s * 0.2), s * 0.1, C["red"], h=0.6)
    L.sphere(b, 0, H * 0.86, 0, s * 0.24, C["sack"], subdiv=1)
    L.sphere(b, -s * 0.09, H * 0.88, s * 0.21, s * 0.04, C["ocean"])
    L.sphere(b, s * 0.09, H * 0.88, s * 0.21, s * 0.04, C["wood"])
    L.cyl(b, 0, H * 0.94, 0, s * 0.42, s * 0.42, 1.0, 10, C["straw"])
    L.cyl(b, 0, H * 0.94 + 1, 0, s * 0.2, s * 0.17, s * 0.24, 10, C["straw"])
    L.sphere(b, s * 0.55, H * 0.67 + s * 0.15, 0, 1.6, C["planet_blue"])


def m_skep(b, g, L, s, rng):
    L.box(b, 0, 0, 0, s * 0.9, s * 0.35, s * 0.9, C["wood"])
    bands = 6
    y = s * 0.35
    for k in range(bands):
        r0 = s * 0.42 * math.cos(k / bands * math.pi / 2)
        r1 = s * 0.42 * math.cos((k + 1) / bands * math.pi / 2)
        h = s * 0.13
        L.cyl(b, 0, y, 0, r0, max(r1, 0.0), h, 10, shade(C["straw"], 0.9 + 0.1 * (k % 2)), caps=(k == 0))
        y += h
    L.box(b, 0, s * 0.35, s * 0.38, s * 0.18, s * 0.1, 2, C["dark"])
    for k in range(6):
        a = k * 1.1
        L.sphere(b, math.cos(a) * s * 0.55, s * (0.5 + 0.1 * (k % 3)), math.sin(a) * s * 0.55, 0.7, C["yellow"])


def m_glow_rock(b, g, L, s, rng):
    L.disc(b, 0, 0.4, 0, s * 0.9, 10, C["scorch"])
    for k in range(10):
        a = 2 * math.pi * k / 10
        L.sphere(b, math.cos(a) * s * 0.9, 0.6, math.sin(a) * s * 0.9, s * 0.12, C["soil"], squash=(1, 0.5, 1))
    L.sphere(g, 0, s * 0.3, 0, s * 0.38, C["white"], subdiv=1, rng=rng, jitter=0.15)


def m_log(b, g, L, s, rng):
    r = s * 0.3
    p0, p1 = (-s * 0.7, r * 0.85, 0), (s * 0.7, r * 0.85, 0)
    L.tube(b, p0, p1, r, r * 0.95, 10, C["bark"], caps=False)
    L.tube(b, p0, p1, r * 0.75, r * 0.72, 10, C["inner"], caps=False, inward=True)
    ax = L.v(1, 0, 0)
    b.annulus(L.p(*p1), ax, r * 0.95, r * 0.72, 10, C["rings"])
    b.annulus(L.p(*p0), (-ax[0], -ax[1], -ax[2]), r, r * 0.75, 10, C["rings"])
    for k in range(4):
        L.sphere(b, (k - 1.5) * s * 0.3, r * 1.75, (k % 2 - 0.5) * 2, r * 0.35, C["moss2"], squash=(1, 0.45, 1))
    for k in range(3):
        x = (k - 1) * s * 0.35
        L.cyl(b, x, r * 1.7, r * 0.5, 0.4, 0.4, 2.0, 4, C["stem"], caps=False)
        L.cyl(b, x, r * 1.7 + 2, r * 0.5, 1.4, 0.2, 1.0, 6, C["orange"])
    for k in range(4):
        L.sphere(g, (k - 1.5) * s * 0.28, r * 0.9 + (k % 2) * 2, (k % 3 - 1) * 2, 0.5, C["white"])


def m_lone_gate(b, g, L, s, rng):
    for side in (-1, 1):
        L.box(b, side * s * 0.55, 0, 0, 3.2, s * 1.25, 3.2, C["wood2"])
        L.sphere(b, side * s * 0.55, s * 1.25 + 1.4, 0, 1.8, C["wood2"])
    white = C["white"]
    for y in (0.3, 0.62, 0.95):
        L.beam(b, (-s * 0.5, s * y, 0), (s * 0.5, s * y, 0), 1.0, white, h=2.0)
    for x in (-0.5, -0.17, 0.17, 0.5):
        L.beam(b, (s * x, s * 0.2, 0), (s * x, s * 1.05, 0), 1.0, white, h=1.8, side=(0, 0, 1))
    L.beam(b, (-s * 0.5, s * 0.3, 0.4), (s * 0.5, s * 0.95, 0.4), 1.0, white, h=1.8, side=(0, 0, 1))
    L.box(b, s * 0.45, s * 0.6, 1.0, 1.2, 1.6, 1.0, C["iron"])


def m_boulder(b, g, L, s, rng):
    cy, rx, ry, rz = s * 0.32, s * 0.55, s * 0.44, s * 0.52
    L.sphere(b, 0, cy, 0, s * 0.55, C["rock"], subdiv=1, squash=(1.0, 0.8, 0.95))

    def surf(x, y):
        k = 1 - (x / rx) ** 2 - ((y - cy) / ry) ** 2
        return rz * math.sqrt(max(0.0, k)) + 0.2

    for side in (-1, 1):
        x, y = side * s * 0.15, s * 0.5
        L.sphere(b, x, y, surf(x, y), s * 0.055, C["moss"], squash=(1, 1, 0.5))
    for k in range(7):
        a = math.pi * (0.15 + 0.7 * k / 6)
        x, y = math.cos(a) * s * 0.22, s * 0.36 - math.sin(a) * s * 0.11
        L.sphere(b, x, y, surf(x, y), s * 0.045, C["moss"], squash=(1, 1, 0.5))
    for k in range(4):
        a = k * 1.7
        L.sphere(b, math.cos(a) * s * 0.25, cy + ry * 0.85, math.sin(a) * s * 0.25 - s * 0.1, s * 0.08, C["lichen"],
                 squash=(1, 0.4, 1))


def m_picnic(b, g, L, s, rng):
    n = 5
    cell = s * 0.9 / n
    for i in range(n):
        for j in range(n):
            x, z = (i - (n - 1) / 2) * cell, (j - (n - 1) / 2) * cell
            col = C["red"] if (i + j) % 2 == 0 else C["cream"]
            L.box(b, x, L.gy(x, z) + 0.15, z, cell, 0.5, cell, col)
    bx, bz = s * 0.18, -s * 0.12
    by = L.gy(bx, bz) + 0.6
    L.box(b, bx, by, bz, s * 0.3, s * 0.2, s * 0.22, C["wicker"])
    L.beam(b, (bx - s * 0.12, by + s * 0.2, bz), (bx, by + s * 0.36, bz), 0.7, C["wicker"])
    L.beam(b, (bx, by + s * 0.36, bz), (bx + s * 0.12, by + s * 0.2, bz), 0.7, C["wicker"])
    ax, az = -s * 0.15, s * 0.12
    L.sphere(b, ax, L.gy(ax, az) + 2.2, az, 1.8, C["red"])
    kx, kz = -s * 0.2, -s * 0.18
    L.box(b, kx, L.gy(kx, kz) + 0.6, kz, s * 0.16, 1.2, s * 0.12, C["paint5"], drot=15)
    L.box(b, s * 0.05, L.gy(s * 0.05, s * 0.2) + 0.65, s * 0.2, s * 0.1, 0.2, s * 0.07, C["white"], drot=-10)


def m_weathervane(b, g, L, s, rng):
    H = s * 3.6
    L.cyl(b, 0, -2, 0, s * 0.3, s * 0.25, 3, 7, C["stone"])
    L.cyl(b, 0, 0, 0, 1.2, 0.9, H, 6, C["iron"])
    for a in (0, 90):
        dx, dz = rotate_y(1, 0, a)
        L.beam(b, (-dx * s * 0.4, H * 0.85, -dz * s * 0.4), (dx * s * 0.4, H * 0.85, dz * s * 0.4), 0.7, C["iron"])
    for a in (0, 90, 180, 270):
        dx, dz = rotate_y(1, 0, a)
        L.sphere(b, dx * s * 0.42, H * 0.85, dz * s * 0.42, 0.9, C["brass"])
    y = H + 2.5
    cop = C["copper"]
    L.tube(b, (0, y, s * 0.4), (0, y, 0), s * 0.03, s * 0.16, 8, cop, caps=False)
    L.tube(b, (0, y, 0), (0, y, -s * 0.38), s * 0.16, s * 0.02, 8, cop, caps=False)
    L.tri2(b, (0, y, s * 0.38), (0, y + s * 0.2, s * 0.6), (0, y - s * 0.2, s * 0.6), cop)
    L.tri2(b, (0, y + s * 0.12, -s * 0.05), (0, y + s * 0.3, s * 0.12), (0, y + s * 0.14, s * 0.2), cop)
    L.sphere(b, s * 0.08, y + s * 0.04, -s * 0.22, 0.6, C["black"])
    L.beam(b, (0, H, 0), (0, y - s * 0.12, 0), 0.6, C["iron"])


BUILDERS = {name[2:]: fn for name, fn in list(globals().items()) if name.startswith("m_") and callable(fn)}


def build_curiosities() -> tuple[MeshData, MeshData]:
    """Meshes for every curiosity: (solid parts, glowing parts)."""
    b, g = MeshBuilder(), MeshBuilder()
    spots = curiosity_spots()
    for c in CURIOSITIES:
        sp = spots[c.id]
        builder = BUILDERS.get(c.kind)
        if builder is None:  # pragma: no cover - guarded by a test
            continue
        rng = random.Random(sum(ord(ch) for ch in c.id))
        builder(b, g, _L(sp["x"], sp["y"], sp["z"], sp["rot"]), sp["size"], rng)
    return b.finish(), g.finish()


def curiosity_layout() -> list[dict]:
    """What the 3D view needs to label curiosities: id, name, label position and zone."""
    out = []
    for c in CURIOSITIES:
        sp = curiosity_spots()[c.id]
        label_y = sp["y"] + _label_height(c, sp["size"])
        out.append({"id": c.id, "name": c.name, "x": sp["x"], "y": label_y, "z": sp["z"],
                    "standX": sp["standX"], "standZ": sp["standZ"], "zone": sp["zone"]})
    return out


def _label_height(c: Curiosity, size: float) -> float:
    tall = {"lighthouse": 3.6 * 1.25, "windmill": 2.6 * 1.6, "treehouse": 3.6, "clock_post": 5.4, "kite_pole": 5.2,
            "signpost": 4.0, "scarecrow": 2.9, "weathervane": 4.2, "statue": 2.4, "stone_circle": 1.4,
            "ribbon_tree": 2.2, "bell_frame": 2.3, "acorn_chimes": 3.2, "mitten_twig": 2.6, "jar_lantern": 2.9,
            "web_frame": 1.9, "well": 1.7}
    if c.kind == "coin":
        return 30.0
    return size * tall.get(c.kind, 1.0) + 10.0
