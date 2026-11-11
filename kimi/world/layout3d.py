"""Where everything sits in the 3D Bramblewick, and where Kimi should be.

Pure Python (no Qt), so it can be tested anywhere. Coordinates follow Qt
Quick 3D: Y is up and the ground is the XZ plane. One unit is roughly a
centimetre at Kimi's scale. Each building faces its *plaza*, the open spot
in front of it towards the town square, and paths run between plazas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .locations import EDGES, LOCATIONS

SCALE_X = 1800.0
SCALE_Z = 1600.0
TOWN_RADIUS = 880.0          # flat, buildable town area
ISLAND_RADIUS = 1250.0       # beyond this the land dips into the lake
WATER_LEVEL = -6.0
SQUARE_RADIUS = 125.0
PATH_WIDTH = 34.0

FOOTPRINT = {"nest": 95.0, "shrub": 105.0, "shrine": 85.0, "square": 0.0,
             "cafe": 95.0, "print_shop": 95.0, "library": 105.0}
LABEL_HEIGHT = {"nest": 330.0, "shrub": 190.0, "shrine": 200.0, "square": 120.0,
                "cafe": 230.0, "print_shop": 230.0, "library": 260.0}


def to_world(nx: float, ny: float) -> tuple[float, float]:
    return (nx - 0.5) * SCALE_X, (ny - 0.5) * SCALE_Z


def rotate_y(x: float, z: float, degrees: float) -> tuple[float, float]:
    """Rotate (x, z) about Y the way Qt Quick 3D's eulerRotation.y does (local +Z -> (sin, cos))."""
    a = math.radians(degrees)
    return x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)


def heading_to(dx: float, dz: float) -> float:
    """Euler Y rotation (degrees) that turns local +Z towards (dx, dz)."""
    return math.degrees(math.atan2(dx, dz))


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    x: float
    z: float
    facing: float          # building's front (local +Z) points this way
    radius: float
    plaza: tuple[float, float]

    def local(self, lx: float, lz: float) -> tuple[float, float]:
        """Convert a point in the building's local frame to world XZ."""
        rx, rz = rotate_y(lx, lz, self.facing)
        return self.x + rx, self.z + rz


def _build_places() -> dict[str, Place]:
    sqx, sqz = to_world(*LOCATIONS["square"].position)
    places: dict[str, Place] = {}
    for lid, loc in LOCATIONS.items():
        x, z = to_world(*loc.position)
        r = FOOTPRINT[lid]
        if lid == "square":
            places[lid] = Place(lid, loc.name, x, z, 0.0, r, (x, z))
            continue
        dx, dz = sqx - x, sqz - z
        d = math.hypot(dx, dz) or 1.0
        ux, uz = dx / d, dz / d
        plaza = (x + ux * (r + 60.0), z + uz * (r + 60.0))
        places[lid] = Place(lid, loc.name, x, z, heading_to(ux, uz), r, plaza)
    return places


PLACES: dict[str, Place] = _build_places()


# -- paths ---------------------------------------------------------------------

def _endpoint(lid: str, other: str) -> tuple[float, float]:
    """Paths meet the square at the edge of its cobbles, and other places at their plaza."""
    p = PLACES[lid]
    if lid != "square":
        return p.plaza
    ox, oz = PLACES[other].plaza
    dx, dz = ox - p.x, oz - p.z
    d = math.hypot(dx, dz) or 1.0
    return p.x + dx / d * (SQUARE_RADIUS - 20), p.z + dz / d * (SQUARE_RADIUS - 20)


def path_control(a: str, b: str) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Quadratic Bezier (start, control, end) for the path between a and b, in canonical order."""
    a, b = sorted((a, b))
    p0 = _endpoint(a, b)
    p1 = _endpoint(b, a)
    mx, mz = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dz) or 1.0
    bend = (0.10 if (len(a) + len(b)) % 2 else -0.10) * length
    c = (mx - dz / length * bend, mz + dx / length * bend)
    return p0, c, p1


def _bezier(p0, c, p1, t: float) -> tuple[float, float]:
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
            u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])


def path_point(frm: str, to: str, t: float) -> tuple[float, float]:
    t = max(0.0, min(1.0, t))
    p0, c, p1 = path_control(frm, to)
    canonical = sorted((frm, to))[0] == frm
    return _bezier(p0, c, p1, t if canonical else 1 - t)


def path_heading(frm: str, to: str, t: float) -> float:
    a = path_point(frm, to, max(0.0, t - 0.01))
    b = path_point(frm, to, min(1.0, t + 0.01))
    return heading_to(b[0] - a[0], b[1] - a[1])


def path_polylines(samples: int = 36) -> list[list[tuple[float, float]]]:
    lines = []
    for a, b, _ in EDGES:
        p0, c, p1 = path_control(a, b)
        lines.append([_bezier(p0, c, p1, i / samples) for i in range(samples + 1)])
    return lines


def distance_to_paths(x: float, z: float, polylines: list[list[tuple[float, float]]]) -> float:
    best = 1e9
    for line in polylines:
        for (ax, az), (bx, bz) in zip(line, line[1:]):
            vx, vz = bx - ax, bz - az
            l2 = vx * vx + vz * vz or 1e-9
            t = max(0.0, min(1.0, ((x - ax) * vx + (z - az) * vz) / l2))
            px, pz = ax + vx * t, az + vz * t
            best = min(best, math.hypot(x - px, z - pz))
    return best


# -- landmarks used by the scene ------------------------------------------------------

def landmarks() -> dict:
    """Positions of dynamic scene details (notice board, easel, townsfolk, lamps…)."""
    shrine, cafe, ps, lib, nest, sq = (PLACES[k] for k in ("shrine", "cafe", "print_shop", "library", "nest", "square"))
    board = shrine.local(78, 62)
    easel = ps.local(-62, 88)
    return {
        "noticeBoard": {"x": board[0], "z": board[1], "facing": shrine.facing},
        "easel": {"x": easel[0], "z": easel[1], "facing": ps.facing},
        "fountain": {"x": sq.x, "z": sq.z},
        "chimney": dict(zip(("x", "z"), cafe.local(45, -20))) | {"y": 205.0},
        "critters": [
            {"kind": "hedgehog", "name": "Marigold", **dict(zip(("x", "z"), cafe.local(-48, 104))), "facing": cafe.facing},
            {"kind": "owl", "name": "Professor Quill", **dict(zip(("x", "z"), lib.local(62, 146))), "facing": lib.facing},
            {"kind": "cat", "name": "Ink", **dict(zip(("x", "z"), ps.local(56, 96))), "facing": ps.facing},
        ],
        "lights": [
            {"x": sq.x + 70, "z": sq.z + 70, "y": 75.0},
            {"x": cafe.plaza[0], "z": cafe.plaza[1], "y": 90.0},
            {"x": shrine.plaza[0], "z": shrine.plaza[1], "y": 70.0},
            {"x": nest.plaza[0], "z": nest.plaza[1], "y": 60.0},
        ],
    }


def labels() -> list[dict]:
    return [{"id": p.id, "name": p.name, "x": p.x, "y": LABEL_HEIGHT[p.id], "z": p.z} for p in PLACES.values()]


# -- Kimi's pose ------------------------------------------------------------------------

WANDER_ACTIONS = {"explore", "observe", "visit_location", "linger", "rest", "continue"}
MODE_FOR_ACTION = {
    "sleep": "sleep", "eat": "eat", "read_note": "read", "leave_message": "read", "create_art": "create",
    "share_creation": "create", "research": "research", "write_diary": "write", "reflect": "write",
    "rest": "rest", "explore": "explore", "observe": "observe", "visit_location": "observe",
    "linger": "idle", "continue": "idle",
}


def activity_spot(location: str, action: str | None) -> tuple[float, float, float | None]:
    """Where Kimi stands for an activity, and which way it faces (None = free)."""
    p = PLACES.get(location) or PLACES["nest"]
    if action == "sleep" and location == "nest":
        x, z = p.local(0, p.radius * 0.62)
        return x, z, p.facing
    if action in ("read_note", "leave_message") and location == "shrine":
        x, z = p.local(78, 96)
        return x, z, p.facing + 180
    if action in ("create_art", "share_creation") and location == "print_shop":
        x, z = p.local(-62, 120)
        return x, z, p.facing + 180
    if action == "research" and location == "library":
        x, z = p.local(0, p.radius + 22)
        return x, z, p.facing + 180
    if action == "eat" and location == "cafe":
        x, z = p.local(70, 104)
        return x, z, p.facing + 90
    if location == "square":
        return p.x + 70, p.z + 48, None
    return p.plaza[0], p.plaza[1], None


def kimi_target(pose: dict) -> dict:
    """Turn the runtime's pose (location / travel / action / asleep) into a 3D target."""
    travel = pose.get("travel")
    if travel:
        x, z = path_point(travel["from"], travel["to"], travel["t"])
        heading = path_heading(travel["from"], travel["to"], travel["t"])
        return {"x": x, "z": z, "heading": heading, "moving": True, "wander": False, "radius": 0.0, "mode": "walk",
                "viewYaw": heading + 180.0}
    action = pose.get("action")
    location = pose.get("location") or "nest"
    if pose.get("asleep"):
        action = "sleep"
    x, z, facing = activity_spot(location, action)
    wander = action in WANDER_ACTIONS and not pose.get("asleep")
    radius = 0.0
    if wander:
        radius = 130.0 if (action == "explore" and location == "shrub") else 70.0
    place = PLACES.get(location) or PLACES["nest"]
    # Look from the plaza side in a three-quarter view, so the building frames Kimi instead of hiding it.
    view_yaw = 30.0 if place.id == "square" else place.facing + 25.0
    return {"x": x, "z": z, "heading": facing, "moving": False, "wander": wander, "radius": radius,
            "mode": MODE_FOR_ACTION.get(action or "", "idle"), "viewYaw": view_yaw}


# -- sky and light ----------------------------------------------------------------------

_SKY_KEYS = [
    # hour, top, horizon, sun colour
    (0.0, "#0b1430", "#1d2a50", "#000000"),
    (5.0, "#0e1838", "#283563", "#000000"),
    (6.2, "#5b7fb8", "#f4b38a", "#ffc58f"),
    (7.8, "#6aa6e0", "#cfe6f2", "#fff3dd"),
    (17.2, "#6aa6e0", "#d6e8f0", "#fff1d8"),
    (19.3, "#4a5f9c", "#f39a6b", "#ff9a5a"),
    (21.0, "#141d40", "#2d3566", "#000000"),
    (24.0, "#0b1430", "#1d2a50", "#000000"),
]
_OVERCAST = {"cloudy": 0.35, "drizzle": 0.5, "rain": 0.6, "snow": 0.45, "foggy": 0.3, "breezy": 0.08}


def _rgb(h: str) -> tuple[float, float, float]:
    return int(h[1:3], 16) / 255, int(h[3:5], 16) / 255, int(h[5:7], 16) / 255


def _hex(c: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in c)


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ca, cb)))


def light_level(hour: float) -> float:
    if 7 <= hour <= 19:
        return 1.0
    if 5 <= hour < 7:
        return 0.15 + 0.85 * (hour - 5) / 2
    if 19 < hour <= 21:
        return 1.0 - 0.85 * (hour - 19) / 2
    return 0.15


def sky_state(hour: float, weather: str) -> dict:
    hour = hour % 24
    for (h0, t0, z0, s0), (h1, t1, z1, s1) in zip(_SKY_KEYS, _SKY_KEYS[1:]):
        if h0 <= hour <= h1:
            f = (hour - h0) / (h1 - h0)
            top, horizon, sun = _mix(t0, t1, f), _mix(z0, z1, f), _mix(s0, s1, f)
            break
    overcast = _OVERCAST.get(weather, 0.0)
    grey = "#8f98a3"
    night = 1.0 - (light_level(hour) - 0.15) / 0.85
    if overcast:
        top = _mix(top, _mix(grey, "#20263a", night), overcast)
        horizon = _mix(horizon, _mix("#b9c0c7", "#2a3047", night), overcast)
    elevation = 70.0 * math.sin(math.pi * (hour - 6.0) / 13.0) if 6.0 <= hour <= 19.0 else -20.0
    azimuth = -90.0 + 180.0 * (hour - 6.0) / 13.0
    sun_brightness = max(0.0, min(1.0, elevation / 22.0)) * (1.0 - 0.45 * overcast)
    return {
        "skyTop": top,
        "skyHorizon": horizon,
        "skyBottom": _mix(horizon, "#26331f", 0.7),
        "sunColor": sun if sun != "#000000" else "#ffd9a8",
        "sunElevation": elevation,
        "sunAzimuth": azimuth,
        "sunBrightness": round(sun_brightness, 3),
        "moonBrightness": round(0.32 * night, 3),
        "ambient": _mix(_mix("#c9d6e3", "#22305a", night), grey, overcast * 0.5),
        "night": round(night, 3),
        "fog": weather == "foggy",
        "fogColor": _mix("#d8dde2", "#2a3047", night),
        "cloudiness": overcast,
    }
