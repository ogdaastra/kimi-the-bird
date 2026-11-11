"""Procedural low-poly meshes for the 3D Bramblewick.

Everything static in the town - the island, paths, buildings, trees,
flowers - is generated here as flat-shaded, vertex-coloured triangles and
merged into a handful of meshes, so the scene stays light to render.
Pure Python: the Qt side only uploads the arrays.

Vertex layout (40 bytes): position xyz, normal xyz, colour rgba (float32).
"""

from __future__ import annotations

import math
import random
from array import array
from dataclasses import dataclass
from functools import lru_cache

from .layout3d import (
    ISLAND_RADIUS,
    PATH_WIDTH,
    PLACES,
    SQUARE_RADIUS,
    TOWN_RADIUS,
    WATER_LEVEL,
    distance_to_paths,
    landmarks,
    path_polylines,
    rotate_y,
    to_world,
)

STRIDE_FLOATS = 10
Color = tuple[float, float, float, float]


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb(h: str, alpha: float = 1.0) -> Color:
    """Hex sRGB colour -> linear RGBA, which is what Qt Quick 3D expects for vertex colours."""
    return (srgb_to_linear(int(h[1:3], 16) / 255), srgb_to_linear(int(h[3:5], 16) / 255),
            srgb_to_linear(int(h[5:7], 16) / 255), alpha)


def shade(c: Color, f: float) -> Color:
    return (min(1.0, c[0] * f), min(1.0, c[1] * f), min(1.0, c[2] * f), c[3])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


@dataclass
class MeshData:
    vertices: array
    vertex_count: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]

    def to_bytes(self) -> bytes:
        return self.vertices.tobytes()


class MeshBuilder:
    def __init__(self) -> None:
        self.data = array("f")
        self.count = 0
        self.lo = [math.inf, math.inf, math.inf]
        self.hi = [-math.inf, -math.inf, -math.inf]

    # -- primitives ---------------------------------------------------------------
    def tri(self, a, b, c, color: Color, hint=None, colors: tuple[Color, Color, Color] | None = None) -> None:
        n = _cross(_sub(b, a), _sub(c, a))
        if hint is not None and (n[0] * hint[0] + n[1] * hint[1] + n[2] * hint[2]) < 0:
            b, c = c, b
            if colors:
                colors = (colors[0], colors[2], colors[1])
            n = (-n[0], -n[1], -n[2])
        n = _norm(n)
        cs = colors or (color, color, color)
        for p, col in ((a, cs[0]), (b, cs[1]), (c, cs[2])):
            self.data.extend((p[0], p[1], p[2], n[0], n[1], n[2], col[0], col[1], col[2], col[3]))
            for i in range(3):
                if p[i] < self.lo[i]:
                    self.lo[i] = p[i]
                if p[i] > self.hi[i]:
                    self.hi[i] = p[i]
        self.count += 3

    def quad(self, a, b, c, d, color: Color, hint=None) -> None:
        self.tri(a, b, c, color, hint)
        self.tri(a, c, d, color, hint)

    def finish(self) -> MeshData:
        if self.count == 0:
            return MeshData(array("f"), 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        return MeshData(self.data, self.count, tuple(self.lo), tuple(self.hi))

    # -- shapes (local frame rotated about Y by `rot` degrees around (x, z)) ------
    @staticmethod
    def _xf(x, y, z, rot, lx, ly, lz):
        rx, rz = rotate_y(lx, lz, rot)
        return (x + rx, y + ly, z + rz)

    def box(self, x, y, z, sx, sy, sz, color: Color, rot: float = 0.0, top: Color | None = None) -> None:
        hx, hz = sx / 2, sz / 2
        P = lambda lx, ly, lz: self._xf(x, y, z, rot, lx, ly, lz)  # noqa: E731
        c000, c100, c110, c010 = P(-hx, 0, -hz), P(hx, 0, -hz), P(hx, sy, -hz), P(-hx, sy, -hz)
        c001, c101, c111, c011 = P(-hx, 0, hz), P(hx, 0, hz), P(hx, sy, hz), P(-hx, sy, hz)
        ax = rotate_y(1, 0, rot)
        az = rotate_y(0, 1, rot)
        self.quad(c001, c101, c111, c011, shade(color, 1.0), (az[0], 0, az[1]))
        self.quad(c000, c010, c110, c100, shade(color, 0.86), (-az[0], 0, -az[1]))
        self.quad(c100, c110, c111, c101, shade(color, 0.93), (ax[0], 0, ax[1]))
        self.quad(c000, c001, c011, c010, shade(color, 0.9), (-ax[0], 0, -ax[1]))
        self.quad(c010, c011, c111, c110, top or shade(color, 1.05), (0, 1, 0))
        self.quad(c000, c100, c101, c001, shade(color, 0.7), (0, -1, 0))

    def cylinder(self, x, y, z, r0, r1, h, seg, color: Color, caps: bool = True, top: Color | None = None) -> None:
        ring0 = [(x + r0 * math.cos(2 * math.pi * i / seg), y, z + r0 * math.sin(2 * math.pi * i / seg)) for i in range(seg)]
        ring1 = [(x + r1 * math.cos(2 * math.pi * i / seg), y + h, z + r1 * math.sin(2 * math.pi * i / seg)) for i in range(seg)]
        for i in range(seg):
            j = (i + 1) % seg
            mid = (math.cos(2 * math.pi * (i + 0.5) / seg), 0.3 if r1 < r0 else 0.0, math.sin(2 * math.pi * (i + 0.5) / seg))
            col = shade(color, 0.88 + 0.12 * (0.5 + 0.5 * math.cos(2 * math.pi * (i + 0.5) / seg - 0.8)))
            if r1 <= 0.01:
                self.tri(ring0[i], ring0[j], (x, y + h, z), col, mid)
            else:
                self.quad(ring0[i], ring0[j], ring1[j], ring1[i], col, mid)
        if caps:
            for i in range(seg):
                j = (i + 1) % seg
                self.tri((x, y, z), ring0[i], ring0[j], shade(color, 0.7), (0, -1, 0))
                if r1 > 0.01:
                    self.tri((x, y + h, z), ring1[i], ring1[j], top or shade(color, 1.05), (0, 1, 0))

    def disc(self, x, y, z, r, seg, color: Color) -> None:
        for i in range(seg):
            a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
            self.tri((x, y, z), (x + r * math.cos(a0), y, z + r * math.sin(a0)),
                     (x + r * math.cos(a1), y, z + r * math.sin(a1)), color, (0, 1, 0))

    def icosphere(self, x, y, z, r, color: Color, subdiv: int = 1, squash=(1.0, 1.0, 1.0),
                  rng: random.Random | None = None, jitter: float = 0.0, variation: float = 0.08) -> None:
        verts, faces = _unit_icosphere(subdiv)
        pts = []
        for vx, vy, vz in verts:
            j = 1.0 + (rng.uniform(-jitter, jitter) if rng and jitter else 0.0)
            pts.append((x + vx * r * squash[0] * j, y + vy * r * squash[1] * j, z + vz * r * squash[2] * j))
        for i0, i1, i2 in faces:
            a, b, c = pts[i0], pts[i1], pts[i2]
            centre = ((a[0] + b[0] + c[0]) / 3 - x, (a[1] + b[1] + c[1]) / 3 - y, (a[2] + b[2] + c[2]) / 3 - z)
            f = 1.0 + (rng.uniform(-variation, variation) if rng else 0.0) + 0.06 * _norm(centre)[1]
            self.tri(a, b, c, shade(color, f), centre)

    def dome(self, x, y, z, r, seg, rings, color: Color) -> None:
        for k in range(rings):
            t0, t1 = (math.pi / 2) * k / rings, (math.pi / 2) * (k + 1) / rings
            for i in range(seg):
                a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
                p = lambda t, a: (x + r * math.cos(t) * math.cos(a), y + r * math.sin(t), z + r * math.cos(t) * math.sin(a))  # noqa: E731
                hint = (math.cos(a0), math.sin(t0), math.sin(a0))
                col = shade(color, 0.85 + 0.2 * math.sin(t1))
                if k == rings - 1:
                    self.tri(p(t0, a0), p(t0, a1), p(t1, a0), col, hint)
                else:
                    self.quad(p(t0, a0), p(t0, a1), p(t1, a1), p(t1, a0), col, hint)

    def gable_roof(self, x, y, z, w, d, h, color: Color, rot: float = 0.0, gable: Color | None = None) -> None:
        P = lambda lx, ly, lz: self._xf(x, y, z, rot, lx, ly, lz)  # noqa: E731
        hw, hd = w / 2, d / 2
        f0, f1, b0, b1 = P(-hw, 0, hd), P(hw, 0, hd), P(-hw, 0, -hd), P(hw, 0, -hd)
        r0, r1 = P(-hw, h, 0), P(hw, h, 0)
        fz = rotate_y(0, 1, rot)
        fx = rotate_y(1, 0, rot)
        self.quad(f0, f1, r1, r0, color, (fz[0], 1, fz[1]))
        self.quad(b0, r0, r1, b1, shade(color, 0.82), (-fz[0], 1, -fz[1]))
        g = gable or shade(color, 0.75)
        self.tri(f1, b1, r1, g, (fx[0], 0, fx[1]))
        self.tri(f0, r0, b0, g, (-fx[0], 0, -fx[1]))
        self.quad(f0, b0, b1, f1, shade(color, 0.55), (0, -1, 0))

    def pyramid(self, x, y, z, w, d, h, color: Color, rot: float = 0.0) -> None:
        P = lambda lx, ly, lz: self._xf(x, y, z, rot, lx, ly, lz)  # noqa: E731
        hw, hd = w / 2, d / 2
        c = [P(-hw, 0, -hd), P(hw, 0, -hd), P(hw, 0, hd), P(-hw, 0, hd)]
        apex = P(0, h, 0)
        for i in range(4):
            a, b = c[i], c[(i + 1) % 4]
            mid = ((a[0] + b[0]) / 2 - x, 0.5, (a[2] + b[2]) / 2 - z)
            self.tri(a, b, apex, shade(color, 0.85 + 0.05 * i), mid)
        self.quad(c[0], c[1], c[2], c[3], shade(color, 0.6), (0, -1, 0))


@lru_cache(maxsize=4)
def _unit_icosphere(subdiv: int):
    t = (1 + math.sqrt(5)) / 2
    verts = [_norm(v) for v in [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
                                (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
             (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
             (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    for _ in range(subdiv):
        cache: dict[tuple[int, int], int] = {}

        def mid(i, j):
            key = (min(i, j), max(i, j))
            if key not in cache:
                a, b = verts[i], verts[j]
                verts.append(_norm(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)))
                cache[key] = len(verts) - 1
            return cache[key]

        new = []
        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            new += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new
    return tuple(verts), tuple(faces)


# -- terrain --------------------------------------------------------------------------

def _hash(ix: int, iz: int, seed: int) -> float:
    h = (ix * 374761393 + iz * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 0xFFFF * 2 - 1


def value_noise(x: float, z: float, seed: int = 3) -> float:
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = x - ix, z - iz
    sx, sz = fx * fx * (3 - 2 * fx), fz * fz * (3 - 2 * fz)
    a, b = _hash(ix, iz, seed), _hash(ix + 1, iz, seed)
    c, d = _hash(ix, iz + 1, seed), _hash(ix + 1, iz + 1, seed)
    return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sz


def fbm(x: float, z: float) -> float:
    return 0.6 * value_noise(x, z) + 0.3 * value_noise(x * 2.1, z * 2.1, 7) + 0.1 * value_noise(x * 4.3, z * 4.3, 11)


def smoothstep(e0: float, e1: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def height(x: float, z: float) -> float:
    """Ground height: flat in town, rolling hills around it, a shore into the lake."""
    r = math.hypot(x, z)
    n = fbm(x * 0.0045, z * 0.0045)
    rim = smoothstep(TOWN_RADIUS, TOWN_RADIUS + 190, r)
    hill = (0.5 + 0.5 * n) * 175.0 * rim
    shore = smoothstep(ISLAND_RADIUS - 110, ISLAND_RADIUS + 110, r)
    return hill * (1 - shore) - 55.0 * shore


GRASS = rgb("#9cc77f")
GRASS_DARK = rgb("#7fae68")
HILL = rgb("#6f9a5a")
SAND = rgb("#e4d5a5")


def _terrain_color(x: float, z: float, h: float) -> Color:
    n = 0.5 + 0.5 * value_noise(x * 0.012, z * 0.012, 5)
    if h < WATER_LEVEL + 4:
        return shade(SAND, 0.95 + 0.08 * n)
    g = tuple(GRASS[i] + (GRASS_DARK[i] - GRASS[i]) * n for i in range(4))
    hill_mix = min(1.0, max(0.0, h / 150.0))
    return tuple(g[i] + (HILL[i] - g[i]) * hill_mix for i in range(4))  # type: ignore[return-value]


def build_terrain(size: float = 2900.0, cells: int = 96) -> MeshData:
    b = MeshBuilder()
    step = size / cells
    half = size / 2
    hs = [[height(-half + i * step, -half + j * step) for j in range(cells + 1)] for i in range(cells + 1)]
    for i in range(cells):
        for j in range(cells):
            x0, x1 = -half + i * step, -half + (i + 1) * step
            z0, z1 = -half + j * step, -half + (j + 1) * step
            if math.hypot((x0 + x1) / 2, (z0 + z1) / 2) > ISLAND_RADIUS + 260:
                continue
            p00, p10 = (x0, hs[i][j], z0), (x1, hs[i + 1][j], z0)
            p01, p11 = (x0, hs[i][j + 1], z1), (x1, hs[i + 1][j + 1], z1)
            c00, c10, c01, c11 = (_terrain_color(p[0], p[2], p[1]) for p in (p00, p10, p01, p11))
            b.tri(p00, p01, p11, c00, (0, 1, 0), (c00, c01, c11))
            b.tri(p00, p11, p10, c00, (0, 1, 0), (c00, c11, c10))
    return b.finish()


def build_paths() -> MeshData:
    b = MeshBuilder()
    dirt, edge = rgb("#dcc79d"), rgb("#bfa678")
    for line in path_polylines(40):
        for width, y, col in ((PATH_WIDTH + 10, 0.45, edge), (PATH_WIDTH, 0.8, dirt)):
            for (ax, az), (bx, bz) in zip(line, line[1:]):
                dx, dz = bx - ax, bz - az
                length = math.hypot(dx, dz) or 1.0
                ox, oz = -dz / length * width / 2, dx / length * width / 2
                f = 0.96 + 0.06 * value_noise(ax * 0.05, az * 0.05)
                b.quad((ax + ox, y, az + oz), (bx + ox, y, bz + oz), (bx - ox, y, bz - oz), (ax - ox, y, az - oz),
                       shade(col, f), (0, 1, 0))
    sq = PLACES["square"]
    b.disc(sq.x, 1.0, sq.z, SQUARE_RADIUS + 8, 28, rgb("#a99f8c"))
    b.disc(sq.x, 1.3, sq.z, SQUARE_RADIUS, 28, rgb("#d3cab8"))
    rng = random.Random(4)
    for _ in range(70):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(20, SQUARE_RADIUS - 10)
        b.disc(sq.x + r * math.cos(a), 1.6, sq.z + r * math.sin(a), rng.uniform(5, 9), 6, shade(rgb("#c3b9a5"), rng.uniform(0.92, 1.05)))
    return b.finish()


# -- buildings -------------------------------------------------------------------------

WALL = rgb("#f2e3c6")
STONE = rgb("#b9b3a5")
WOOD = rgb("#8a5a3c")
DARK = rgb("#4a3b2c")
GLASS = rgb("#ffffff")


def _house(b: MeshBuilder, glow: MeshBuilder, x, z, rot, w, h, d, wall: Color, roof: Color, door=WOOD,
           chimney: bool = True) -> None:
    def L(lx, lz):
        rx, rz = rotate_y(lx, lz, rot)
        return x + rx, z + rz

    b.box(x, 0, z, w + 10, 6, d + 10, STONE, rot)
    b.box(x, 6, z, w, h, d, wall, rot)
    b.gable_roof(x, 6 + h, z, d + 20, w + 22, h * 0.6, roof, rot + 90, gable=shade(wall, 0.9))
    dx, dz = L(0, d / 2 + 1)
    b.box(dx, 6, dz, w * 0.22, h * 0.5, 3, door, rot)
    for side in (-1, 1):
        wx, wz = L(side * w * 0.3, d / 2 + 1.2)
        glow.box(wx, 6 + h * 0.45, wz, w * 0.18, h * 0.24, 2, GLASS, rot)
        sx, sz = L(w / 2 + 1.2, side * d * 0.22)
        glow.box(sx, 6 + h * 0.45, sz, 2, h * 0.22, d * 0.16, GLASS, rot)
    if chimney:
        cx, cz = L(w * 0.28, -d * 0.18)
        b.box(cx, 6 + h * 0.8, cz, 14, h * 0.75, 14, rgb("#a0523e"), rot)


def _lamp(b: MeshBuilder, glow: MeshBuilder, x: float, z: float, h: float = 70.0) -> None:
    b.cylinder(x, 0, z, 3.0, 2.2, h, 6, DARK)
    b.box(x, h, z, 10, 3, 10, DARK)
    glow.icosphere(x, h + 9, z, 6.5, GLASS, subdiv=0)
    b.pyramid(x, h + 15, z, 14, 14, 8, DARK)


def build_buildings() -> tuple[MeshData, MeshData]:
    b, glow = MeshBuilder(), MeshBuilder()
    rng = random.Random(21)
    P = PLACES

    # The Nest: an old oak with a round hollow.
    n = P["nest"]
    b.cylinder(n.x, 0, n.z, 60, 40, 200, 10, rgb("#7a5236"), caps=False)
    for k in range(6):
        a = math.radians(k * 60 + 15)
        b.box(n.x + math.cos(a) * 52, 0, n.z + math.sin(a) * 52, 46, 18, 16, rgb("#6b4630"), -math.degrees(a))
    hx, hz = n.local(0, 52)
    b.box(hx, 22, hz, 46, 62, 14, rgb("#3a2a1f"), n.facing)
    nx, nz = n.local(0, 62)
    b.cylinder(nx, 0, nz, 26, 30, 8, 10, rgb("#b08a5a"))
    for dx, dy, dz, r in ((0, 270, 0, 115), (-75, 225, 30, 80), (80, 230, -20, 85), (20, 230, 85, 75), (-30, 245, -80, 80)):
        b.icosphere(n.x + dx, dy, n.z + dz, r, rgb("#5f8f55"), subdiv=1, rng=rng, jitter=0.12)
    lx, lz = n.local(38, 70)
    _lamp(b, glow, lx, lz, 46)

    # The Shrub: a huge tangled bush with berries.
    s = P["shrub"]
    for dx, dy, dz, r, col in ((0, 70, 0, 95, "#5d9157"), (-80, 45, 30, 62, "#6da567"), (75, 50, 25, 66, "#5d9157"),
                              (20, 40, 80, 58, "#79b071"), (-40, 55, -70, 64, "#669e60"), (60, 95, -40, 55, "#6da567")):
        b.icosphere(s.x + dx, dy, s.z + dz, r, rgb(col), subdiv=1, rng=rng, jitter=0.15)
    for _ in range(36):
        a, e = rng.uniform(0, 2 * math.pi), rng.uniform(0.2, 1.2)
        rr = rng.uniform(85, 105)
        b.icosphere(s.x + math.cos(a) * rr * math.cos(e) * 0.95, 30 + rr * math.sin(e) * 0.8,
                    s.z + math.sin(a) * rr * math.cos(e) * 0.95, 4.5, rgb("#7b2d5b"), subdiv=0)

    # The Shrine: stone shrine, porch pillars, notice board, lanterns.
    sh = P["shrine"]
    b.box(sh.x, 0, sh.z, 170, 12, 140, rgb("#a9a395"), sh.facing)
    b.box(sh.x, 12, sh.z, 100, 82, 76, STONE, sh.facing)
    b.gable_roof(sh.x, 94, sh.z, 136, 164, 52, rgb("#7f8f7a"), sh.facing + 90)
    for lx_, lz_ in ((-62, 52), (62, 52), (-62, -40), (62, -40)):
        px, pz = sh.local(lx_, lz_)
        b.cylinder(px, 12, pz, 6, 6, 82, 8, rgb("#cfc8b8"))
    dx, dz = sh.local(0, 39)
    b.box(dx, 12, dz, 34, 50, 3, rgb("#5a5148"), sh.facing)
    bx_, bz_ = sh.local(78, 62)
    for side in (-1, 1):
        ppx, ppz = rotate_y(side * 24, 0, sh.facing)
        b.box(bx_ + ppx, 0, bz_ + ppz, 5, 98, 5, WOOD, sh.facing)
    b.box(bx_, 52, bz_, 58, 44, 5, rgb("#a07850"), sh.facing)
    b.gable_roof(bx_, 98, bz_, 66, 16, 10, rgb("#7f8f7a"), sh.facing)
    for side in (-1, 1):
        lx, lz = sh.local(side * 70, 112)
        b.box(lx, 0, lz, 16, 34, 16, STONE, sh.facing)
        glow.box(lx, 34, lz, 12, 12, 12, GLASS, sh.facing)
        b.pyramid(lx, 46, lz, 22, 22, 12, STONE, sh.facing)

    # Town Square: fountain, benches and lamps.
    sq = P["square"]
    b.cylinder(sq.x, 1.6, sq.z, 44, 46, 18, 16, STONE, top=rgb("#a69f90"))
    b.cylinder(sq.x, 1.6, sq.z, 8, 7, 52, 8, rgb("#cfc8b8"))
    b.cylinder(sq.x, 50, sq.z, 6, 22, 8, 12, rgb("#cfc8b8"))
    for k in range(3):
        a = math.radians(30 + k * 120)
        bx2, bz2 = sq.x + math.cos(a) * 92, sq.z + math.sin(a) * 92
        rot = -math.degrees(a) + 90
        b.box(bx2, 10, bz2, 46, 4, 14, WOOD, rot)
        for side in (-1, 1):
            lx2, lz2 = rotate_y(side * 18, 0, rot)
            b.box(bx2 + lx2, 0, bz2 + lz2, 4, 10, 12, DARK, rot)
    for k in range(4):
        a = math.radians(45 + k * 90)
        _lamp(b, glow, sq.x + math.cos(a) * (SQUARE_RADIUS + 18), sq.z + math.sin(a) * (SQUARE_RADIUS + 18))

    # The Cafe: cream walls, red roof, striped awning, tables outside.
    c = P["cafe"]
    _house(b, glow, c.x, c.z, c.facing, 160, 112, 120, WALL, rgb("#c0624b"))
    for k in range(6):
        ax_, az_ = c.local(-62 + k * 24.8, 74)
        b.box(ax_, 84, az_, 24.8, 4, 34, rgb("#c0624b") if k % 2 == 0 else rgb("#fbf3df"), c.facing)
    for lx_, lz_ in ((70, 112), (-70, 128)):
        tx, tz = c.local(lx_, lz_)
        b.cylinder(tx, 0, tz, 3, 3, 30, 6, DARK)
        b.cylinder(tx, 30, tz, 16, 16, 3, 10, rgb("#f4f1ea"))
        b.cylinder(tx, 60, tz, 34, 0, 18, 8, rgb("#c0624b") if lx_ > 0 else rgb("#6a7fa8"), caps=False)
        b.cylinder(tx, 33, tz, 1.5, 1.5, 28, 4, DARK, caps=False)

    # The Print Shop: blue roof, a sign, an easel for displaying work.
    p = P["print_shop"]
    _house(b, glow, p.x, p.z, p.facing, 150, 120, 120, rgb("#e6e2d6"), rgb("#6a7fa8"))
    sx, sz = p.local(0, 64)
    b.box(sx, 100, sz, 70, 20, 4, rgb("#3f6e4e"), p.facing)
    ex, ez = p.local(-62, 88)
    for lx_ in (-14, 14):
        ox, oz = rotate_y(lx_, 0, p.facing)
        b.box(ex + ox, 0, ez + oz, 4, 70, 4, WOOD, p.facing)
    b.box(ex, 26, ez, 40, 4, 10, WOOD, p.facing)

    # The Library: round, domed, with columns and steps.
    lb = P["library"]
    b.cylinder(lb.x, 0, lb.z, 104, 104, 10, 18, rgb("#a9a395"))
    b.cylinder(lb.x, 10, lb.z, 92, 92, 118, 18, rgb("#e9dcc3"), caps=False)
    b.cylinder(lb.x, 128, lb.z, 100, 100, 8, 18, rgb("#d8ccb2"))
    b.dome(lb.x, 136, lb.z, 92, 18, 6, rgb("#9aa5b5"))
    glow.icosphere(lb.x, 236, lb.z, 10, GLASS, subdiv=0)
    for k in range(7):
        a = math.radians(lb.facing) + math.radians(-60 + k * 20)
        cx2, cz2 = lb.x + math.sin(a) * 106, lb.z + math.cos(a) * 106
        b.cylinder(cx2, 10, cz2, 6, 6, 118, 8, rgb("#f6f0e4"))
    for k in range(12):
        a = 2 * math.pi * k / 12
        glow.box(lb.x + math.cos(a) * 93, 70, lb.z + math.sin(a) * 93, 14, 30, 14, GLASS, -math.degrees(a))
    for k in range(3):
        sx2, sz2 = lb.local(0, 112 + k * 12)
        b.box(sx2, 0, sz2, 90 - k * 10, 10 - k * 3, 14, rgb("#cfc8b8"), lb.facing)

    # Village houses around the outskirts.
    for vx, vz, rot, wall, roof in _village_houses():
        _house(b, glow, vx, vz, rot, rng.uniform(80, 100), rng.uniform(64, 80), rng.uniform(72, 86), rgb(wall), rgb(roof))
    for (lx2, lz2) in _path_lamps():
        _lamp(b, glow, lx2, lz2, 64)
    return b.finish(), glow.finish()


_HOUSE_COLOURS = [("#f2e3c6", "#c0624b"), ("#e8d6cf", "#7a8f6a"), ("#dfe6e9", "#9a6a4a"), ("#f3e6b8", "#6a7fa8"),
                  ("#ecd9c6", "#8a5a7c"), ("#e3ecd8", "#b5653f"), ("#f0e0d0", "#5f7f99")]


@lru_cache(maxsize=1)
def _occupied() -> list[tuple[float, float, float]]:
    occ = []
    for p in PLACES.values():
        if p.id == "square":
            occ.append((p.x, p.z, SQUARE_RADIUS + 40))
        else:
            occ.append((p.x, p.z, p.radius + 70))
            occ.append((p.plaza[0], p.plaza[1], 60))
    occ.append((*_pond_centre(), 120))
    marks = landmarks()
    for c in marks["critters"]:
        occ.append((c["x"], c["z"], 30))
    for key in ("noticeBoard", "easel"):
        occ.append((marks[key]["x"], marks[key]["z"], 70))
    return occ


@lru_cache(maxsize=1)
def _pond_centre() -> tuple[float, float]:
    polys = path_polylines()
    tx, tz = to_world(0.30, 0.86)
    best, best_d = (tx, tz), -1.0
    for k in range(60):
        a, r = k * 2.4, 10 + k * 6
        x, z = tx + math.cos(a) * r, tz + math.sin(a) * r
        if math.hypot(x, z) > TOWN_RADIUS - 110:
            continue
        clearance = min([distance_to_paths(x, z, polys)] +
                        [math.hypot(x - p.x, z - p.z) - p.radius for p in PLACES.values() if p.id != "square"])
        if clearance > 130:
            return x, z
        if clearance > best_d:
            best, best_d = (x, z), clearance
    return best


def in_view_corridor(x: float, z: float, r: float = 0.0) -> bool:
    """True if (x, z) sits where the follow camera looks at Kimi from when Kimi is at a place.

    The camera views each place from its plaza side (place facing + 25 degrees), so nothing
    tall is placed in that wedge and buildings frame Kimi instead of hiding it.
    """
    for p in PLACES.values():
        if p.id == "square":
            continue
        dx, dz = x - p.plaza[0], z - p.plaza[1]
        dist = math.hypot(dx, dz)
        if dist > 480 + r:
            continue
        a = math.radians(p.facing + 25.0)
        cx, cz = math.sin(a), math.cos(a)
        along = dx * cx + dz * cz
        across = abs(-dx * cz + dz * cx)
        if along > -40 and across < 70 + r + along * 0.55:
            return True
    return False


def _free(x: float, z: float, r: float, occ, polys, path_clear: float, tall: bool = False) -> bool:
    for ox, oz, orr in occ:
        if math.hypot(x - ox, z - oz) < r + orr:
            return False
    if tall and in_view_corridor(x, z, r):
        return False
    return distance_to_paths(x, z, polys) >= path_clear + r


@lru_cache(maxsize=1)
def _village_houses() -> tuple:
    rng = random.Random(9)
    polys = path_polylines()
    occ = list(_occupied())
    houses = []
    for i in range(80):
        if len(houses) >= 7:
            break
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(560, TOWN_RADIUS - 70)
        x, z = math.cos(a) * r, math.sin(a) * r
        if _free(x, z, 70, occ, polys, 45, tall=True):
            rot = math.degrees(math.atan2(-x, -z)) + rng.uniform(-20, 20)
            wall, roof = _HOUSE_COLOURS[len(houses) % len(_HOUSE_COLOURS)]
            houses.append((x, z, rot, wall, roof))
            occ.append((x, z, 80))
    return tuple(houses)


@lru_cache(maxsize=1)
def _path_lamps() -> tuple:
    lamps = []
    for line in path_polylines(10):
        for idx in (5,):
            (ax, az), (bx, bz) = line[idx], line[idx + 1]
            dx, dz = bx - ax, bz - az
            length = math.hypot(dx, dz) or 1
            lamps.append((ax - dz / length * (PATH_WIDTH / 2 + 14), az + dx / length * (PATH_WIDTH / 2 + 14)))
    return tuple(lamps)


# -- nature ---------------------------------------------------------------------------------

def build_nature(seed: int = 5) -> MeshData:
    b = MeshBuilder()
    rng = random.Random(seed)
    polys = path_polylines()
    occ = list(_occupied()) + [(x, z, 80) for x, z, *_ in _village_houses()]
    occ += [(x, z, 14) for x, z in _path_lamps()]
    greens = ["#5f8f55", "#6fa36b", "#79b071", "#4f7f4a", "#86b96f"]
    placed = 0
    tries = 0
    while placed < 120 and tries < 4000:
        tries += 1
        rim = placed < 90
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(TOWN_RADIUS - 30, ISLAND_RADIUS - 60) if rim else rng.uniform(150, TOWN_RADIUS - 40)
        x, z = math.cos(a) * r, math.sin(a) * r
        if not _free(x, z, 30, occ, polys, 30, tall=True):
            continue
        y = height(x, z)
        if y < WATER_LEVEL + 6:
            continue
        s = rng.uniform(0.8, 1.35)
        if rng.random() < 0.35:
            b.cylinder(x, y, z, 7 * s, 5 * s, 40 * s, 6, rgb("#6b4630"))
            for k in range(3):
                b.cylinder(x, y + (34 + k * 30) * s, z, (46 - k * 11) * s, 0, 52 * s, 7, rgb(rng.choice(["#4f7f4a", "#5a8a52", "#46734a"])))
        else:
            b.cylinder(x, y, z, 9 * s, 6 * s, 70 * s, 6, rgb("#7a5236"))
            b.icosphere(x, y + 95 * s, z, 46 * s, rgb(rng.choice(greens)), subdiv=1, rng=rng, jitter=0.14)
            if rng.random() < 0.5:
                b.icosphere(x + 22 * s, y + 75 * s, z - 10 * s, 30 * s, rgb(rng.choice(greens)), subdiv=1, rng=rng, jitter=0.14)
        occ.append((x, z, 34 * s))
        placed += 1
    # bushes
    for _ in range(40):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(140, TOWN_RADIUS + 120)
        x, z = math.cos(a) * r, math.sin(a) * r
        if _free(x, z, 18, occ, polys, 18, tall=True):
            y = height(x, z)
            b.icosphere(x, y + 12, z, rng.uniform(16, 26), rgb(rng.choice(greens)), subdiv=1, squash=(1, 0.75, 1), rng=rng, jitter=0.15)
    # flowers in little clusters
    petals = ["#f4f1ea", "#f2b8c6", "#f7d35a", "#c9b3ec", "#ef8a62", "#9ccbf2"]
    for _ in range(60):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(80, TOWN_RADIUS + 60)
        cx, cz = math.cos(a) * r, math.sin(a) * r
        col = rgb(rng.choice(petals))
        for _k in range(rng.randint(4, 9)):
            x, z = cx + rng.uniform(-35, 35), cz + rng.uniform(-35, 35)
            if _free(x, z, 3, occ, polys, 10):
                y = height(x, z)
                b.cylinder(x, y, z, 0.8, 0.8, 9, 3, rgb("#4f8a4b"), caps=False)
                b.icosphere(x, y + 11, z, 4.2, col, subdiv=0)
    # grass tufts
    for _ in range(700):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(60, ISLAND_RADIUS - 80)
        x, z = math.cos(a) * r, math.sin(a) * r
        if _free(x, z, 2, occ, polys, 8):
            y = height(x, z)
            if y > WATER_LEVEL + 4:
                b.cylinder(x, y, z, rng.uniform(3, 5), 0, rng.uniform(8, 15), 3, rgb(rng.choice(["#6f9f5b", "#5f8f50", "#7aab62"])), caps=False)
    # rocks on the hills and shore
    for _ in range(45):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(TOWN_RADIUS, ISLAND_RADIUS + 60)
        x, z = math.cos(a) * r, math.sin(a) * r
        y = height(x, z)
        b.icosphere(x, y + 4, z, rng.uniform(10, 28), rgb(rng.choice(["#9a958a", "#8a857b", "#a8a296"])), subdiv=0,
                    squash=(1.2, 0.6, 1.0), rng=rng, jitter=0.2)
    # fences in front of village houses
    for vx, vz, rot, *_ in _village_houses():
        for k in range(-3, 4):
            fx, fz = rotate_y(k * 18, 72, rot)
            b.box(vx + fx, 0, vz + fz, 4, 26, 4, rgb("#efe6d2"), rot)
        rx, rz = rotate_y(0, 72, rot)
        b.box(vx + rx, 10, vz + rz, 112, 3, 3, rgb("#efe6d2"), rot)
        b.box(vx + rx, 19, vz + rz, 112, 3, 3, rgb("#efe6d2"), rot)
    return b.finish()


def build_water() -> MeshData:
    b = MeshBuilder()
    b.disc(0, WATER_LEVEL, 0, 9000, 48, rgb("#6fa8c8"))
    px, pz = _pond_centre()
    b.disc(px, 0.9, pz, 95, 24, rgb("#7fb9d6"))
    sq = PLACES["square"]
    b.disc(sq.x, 17, sq.z, 41, 16, rgb("#86c3df"))
    return b.finish()


def build_pond_rim() -> MeshData:
    b = MeshBuilder()
    px, pz = _pond_centre()
    rng = random.Random(12)
    for k in range(22):
        a = 2 * math.pi * k / 22
        b.icosphere(px + math.cos(a) * 100, 2, pz + math.sin(a) * 100, rng.uniform(8, 13), rgb("#a8a296"), subdiv=0,
                    squash=(1.2, 0.6, 1.0), rng=rng, jitter=0.15)
    for k in range(9):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(30, 75)
        b.disc(px + math.cos(a) * r, 1.6, pz + math.sin(a) * r, rng.uniform(7, 11), 7, rgb("#5f9f55"))
    return b.finish()


@lru_cache(maxsize=1)
def town_meshes() -> dict[str, MeshData]:
    """All static meshes of the town, built once and cached."""
    buildings, glow = build_buildings()
    nature = build_nature()
    rim = build_pond_rim()
    nature.vertices.extend(rim.vertices)
    nature = MeshData(nature.vertices, nature.vertex_count + rim.vertex_count,
                      tuple(min(a, b) for a, b in zip(nature.bounds_min, rim.bounds_min)),
                      tuple(max(a, b) for a, b in zip(nature.bounds_max, rim.bounds_max)))
    return {
        "terrain": build_terrain(),
        "paths": build_paths(),
        "buildings": buildings,
        "glow": glow,
        "nature": nature,
        "water": build_water(),
    }


def pond_centre() -> tuple[float, float]:
    return _pond_centre()
