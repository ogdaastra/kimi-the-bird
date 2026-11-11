"""Bridge between Kimi's runtime and the QML 3D scene.

Exposes a read-only ``layout`` (static positions) and a ``state`` map that
the view refreshes several times a second. QML only animates; all
decisions still come from the runtime.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal

from ...world import layout3d
from ...world.environment import WEATHER_LABELS
from ...world.mesh3d import pond_centre


def build_layout() -> dict:
    marks = layout3d.landmarks()
    px, pz = pond_centre()
    return {
        "places": layout3d.labels(),
        "noticeBoard": marks["noticeBoard"],
        "easel": marks["easel"],
        "fountain": marks["fountain"],
        "chimney": marks["chimney"],
        "critters": marks["critters"],
        "lights": marks["lights"],
        "pond": {"x": px, "z": pz},
        "shrub": {"x": layout3d.PLACES["shrub"].x, "z": layout3d.PLACES["shrub"].z},
        "islandRadius": layout3d.ISLAND_RADIUS,
    }


def compute_state(pose: dict, snap: dict | None, prefs: dict, previous: dict | None = None) -> dict:
    """Pure function: runtime pose + snapshot -> scene state (testable without Qt)."""
    target = layout3d.kimi_target(pose)
    hour = float(pose.get("hour", 12.0))
    weather = pose.get("weather", "sunny")
    sky = layout3d.sky_state(hour, weather)
    state = {
        "kimiX": target["x"],
        "kimiZ": target["z"],
        "kimiHeading": target["heading"] if target["heading"] is not None else -999.0,
        "moving": target["moving"],
        "wander": target["wander"],
        "wanderRadius": target["radius"],
        "viewYaw": target["viewYaw"],
        "mode": target["mode"],
        "asleep": bool(pose.get("asleep")),
        "location": pose.get("location") or "",
        "hour": hour,
        "weather": weather,
        "weatherLabel": WEATHER_LABELS.get(weather, weather),
        "rain": {"rain": 1.0, "drizzle": 0.4}.get(weather, 0.0),
        "snow": 1.0 if weather == "snow" else 0.0,
        "quality": prefs.get("quality", "high"),
        "reduceMotion": bool(prefs.get("reduce_motion", False)),
        **sky,
    }
    snap = snap or {}
    state["unreadNotes"] = int(snap.get("unread_notes", (previous or {}).get("unreadNotes", 0)) or 0)
    state["displayedCreations"] = int(snap.get("displayed_creations", (previous or {}).get("displayedCreations", 0)) or 0)
    state["thinking"] = bool(snap.get("thinking", (previous or {}).get("thinking", False)))
    thought = snap.get("thought") or (previous or {}).get("thoughtData")
    state["thoughtData"] = thought
    state["thought"] = (thought or {}).get("text", "")
    key = f"{(thought or {}).get('day')}-{(thought or {}).get('clock')}-{state['thought'][:20]}"
    prev_key = (previous or {}).get("thoughtKey")
    serial = (previous or {}).get("thoughtSerial", 0)
    primed = bool((previous or {}).get("primed"))
    if thought and key != prev_key and primed:  # never pop a bubble for an old thought at startup
        serial += 1
    state["thoughtKey"] = key
    state["thoughtSerial"] = serial
    state["primed"] = primed or bool(snap)
    state["placeName"] = snap.get("place_name", (previous or {}).get("placeName", ""))
    state["activity"] = snap.get("activity", (previous or {}).get("activity", ""))
    return state


class World3DBridge(QObject):
    stateChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = build_layout()
        self._state = compute_state({"location": "nest", "hour": 8.0, "weather": "sunny"}, None, {})

    def _get_state(self) -> dict:
        return self._state

    def _get_layout(self) -> dict:
        return self._layout

    state = Property("QVariantMap", _get_state, notify=stateChanged)
    layout = Property("QVariantMap", _get_layout, constant=True)

    def update(self, pose: dict, snap: dict | None, prefs: dict) -> None:
        self._state = compute_state(pose, snap, prefs, self._state)
        self.stateChanged.emit()
