"""The 3D world: layout, procedural meshes, scene state and the QML scene."""

import math
import os
import struct

import pytest

from kimi.world import layout3d, mesh3d
from kimi.world.locations import EDGES, LOCATIONS


# -- layout ---------------------------------------------------------------------------

def test_every_place_has_a_3d_home_inside_the_town():
    assert set(layout3d.PLACES) == set(LOCATIONS)
    for p in layout3d.PLACES.values():
        assert math.hypot(p.x, p.z) < layout3d.TOWN_RADIUS
        if p.id != "square":
            # The plaza lies between the building and the town square.
            sq = layout3d.PLACES["square"]
            assert math.hypot(p.plaza[0] - sq.x, p.plaza[1] - sq.z) < math.hypot(p.x - sq.x, p.z - sq.z)


def test_buildings_face_the_square():
    sq = layout3d.PLACES["square"]
    for p in layout3d.PLACES.values():
        if p.id == "square":
            continue
        fx, fz = layout3d.rotate_y(0, 1, p.facing)
        tx, tz = sq.x - p.x, sq.z - p.z
        assert (fx * tx + fz * tz) / math.hypot(tx, tz) > 0.99


def test_paths_connect_places_continuously():
    for a, b, _ in EDGES:
        start = layout3d.path_point(a, b, 0.0)
        end = layout3d.path_point(a, b, 1.0)
        assert start == pytest.approx(layout3d.path_point(b, a, 1.0))
        assert end == pytest.approx(layout3d.path_point(b, a, 0.0))
        pts = [layout3d.path_point(a, b, i / 50) for i in range(51)]
        steps = [math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:])]
        assert max(steps) < 3 * (sum(steps) / len(steps))  # smooth, no jumps


def test_kimi_target_walks_the_path_and_stands_at_activity_spots():
    walking = layout3d.kimi_target({"travel": {"from": "nest", "to": "shrub", "t": 0.5}})
    assert walking["moving"] and walking["mode"] == "walk"
    assert (walking["x"], walking["z"]) == pytest.approx(layout3d.path_point("nest", "shrub", 0.5))
    assert walking["viewYaw"] == pytest.approx(walking["heading"] + 180)
    reading = layout3d.kimi_target({"location": "shrine", "action": "read_note"})
    board = layout3d.landmarks()["noticeBoard"]
    assert math.hypot(reading["x"] - board["x"], reading["z"] - board["z"]) < 50
    assert reading["mode"] == "read" and not reading["wander"]
    asleep = layout3d.kimi_target({"location": "nest", "action": "rest", "asleep": True})
    assert asleep["mode"] == "sleep"
    exploring = layout3d.kimi_target({"location": "shrub", "action": "explore"})
    assert exploring["wander"] and exploring["radius"] > 100


@pytest.mark.parametrize("hour,weather", [(0, "sunny"), (6.5, "cloudy"), (12, "sunny"), (19.5, "rain"), (23, "snow"), (12, "foggy")])
def test_sky_state_is_well_formed(hour, weather):
    s = layout3d.sky_state(hour, weather)
    for key in ("skyTop", "skyHorizon", "skyBottom", "sunColor", "ambient", "fogColor"):
        assert s[key].startswith("#") and len(s[key]) == 7
    assert 0 <= s["night"] <= 1 and 0 <= s["sunBrightness"] <= 1
    assert s["fog"] == (weather == "foggy")


def test_day_and_night_differ():
    noon, midnight = layout3d.sky_state(12, "sunny"), layout3d.sky_state(0, "sunny")
    assert noon["night"] == 0 and midnight["night"] == 1
    assert noon["sunBrightness"] > 0.9 and midnight["sunBrightness"] == 0
    assert midnight["moonBrightness"] > noon["moonBrightness"]


# -- meshes ----------------------------------------------------------------------------

def test_town_meshes_are_valid_vertex_data():
    meshes = mesh3d.town_meshes()
    assert set(meshes) == {"terrain", "paths", "buildings", "glow", "nature", "curiosities", "water"}
    for name, mesh in meshes.items():
        assert mesh.vertex_count > 0 and mesh.vertex_count % 3 == 0, name
        raw = mesh.to_bytes()
        assert len(raw) == mesh.vertex_count * mesh3d.STRIDE_FLOATS * 4
        for i in range(0, mesh.vertex_count, max(1, mesh.vertex_count // 400)):
            v = struct.unpack_from("10f", raw, i * 40)
            assert all(math.isfinite(c) for c in v), name
            assert math.hypot(*v[3:6]) == pytest.approx(1.0, abs=1e-3), name  # unit normals
            assert all(0.0 <= c <= 1.0 for c in v[6:10]), name                # linear RGBA
            for axis in range(3):
                assert mesh.bounds_min[axis] - 1e-3 <= v[axis] <= mesh.bounds_max[axis] + 1e-3


def test_meshes_are_deterministic():
    a = mesh3d.build_nature()
    b = mesh3d.build_nature()
    assert a.vertex_count == b.vertex_count and a.to_bytes() == b.to_bytes()


def test_terrain_is_flat_in_town_and_hilly_outside():
    for p in layout3d.PLACES.values():
        assert mesh3d.height(p.x, p.z) == pytest.approx(0.0, abs=1e-6)
    rim = [mesh3d.height(math.cos(a) * 1080, math.sin(a) * 1080) for a in [i * 0.4 for i in range(16)]]
    assert max(rim) > 40
    assert mesh3d.height(1600, 0) < layout3d.WATER_LEVEL


def test_outward_faces_light_correctly():
    b = mesh3d.MeshBuilder()
    b.box(0, 0, 0, 10, 10, 10, mesh3d.rgb("#ffffff"))
    data = b.finish().to_bytes()
    for t in range(b.count // 3):
        v = [struct.unpack_from("10f", data, (t * 3 + k) * 40) for k in range(3)]
        centre = [sum(p[i] for p in v) / 3 for i in range(3)]
        normal = v[0][3:6]
        outward = (centre[0], centre[1] - 5, centre[2])
        assert sum(n * o for n, o in zip(normal, outward)) > 0


def test_camera_corridors_and_activity_spots_stay_clear():
    polys = layout3d.path_polylines()
    for x, z, *_ in mesh3d._village_houses():
        assert not mesh3d.in_view_corridor(x, z, 70)
        assert layout3d.distance_to_paths(x, z, polys) > 45
    for p in layout3d.PLACES.values():
        if p.id != "square":
            assert mesh3d.in_view_corridor(*p.local(0, p.radius + 200))


# -- scene state -------------------------------------------------------------------------

def test_scene_state_from_runtime_pose():
    from kimi.ui.world3d.bridge import compute_state

    pose = {"location": "cafe", "travel": None, "action": "eat", "asleep": False, "hour": 13.0, "weather": "rain"}
    snap = {"unread_notes": 2, "displayed_creations": 3, "thinking": True, "thought": None, "place_name": "The Cafe"}
    s = compute_state(pose, snap, {"quality": "low", "reduce_motion": True})
    assert s["mode"] == "eat" and s["rain"] == 1.0 and s["snow"] == 0.0
    assert s["unreadNotes"] == 2 and s["displayedCreations"] == 3 and s["thinking"]
    assert s["quality"] == "low" and s["reduceMotion"]


def test_thought_bubble_pops_only_for_new_thoughts():
    from kimi.ui.world3d.bridge import compute_state

    pose = {"location": "nest", "hour": 9.0, "weather": "sunny"}
    old = {"thought": {"text": "An old thought", "day": 1, "clock": "08:00"}}
    s1 = compute_state(pose, old, {}, compute_state(pose, None, {}))
    assert s1["thoughtSerial"] == 0  # remembered from before startup: no bubble
    s2 = compute_state(pose, old, {}, s1)
    assert s2["thoughtSerial"] == 0
    new = {"thought": {"text": "Ooh, a beetle!", "day": 1, "clock": "09:10"}}
    s3 = compute_state(pose, new, {}, s2)
    assert s3["thoughtSerial"] == 1 and s3["thought"] == "Ooh, a beetle!"


def test_runtime_pose(make_runtime):
    rt = make_runtime()
    pose = rt.pose()
    assert set(pose) == {"location", "travel", "action", "curiosity", "asleep", "hour", "weather"}
    rt.advance_world(30)
    pose = rt.pose()
    assert pose["location"] in LOCATIONS
    if pose["travel"]:
        assert 0 <= pose["travel"]["t"] <= 1


def test_new_display_settings_are_validated(tmp_path):
    from kimi.config import SettingsStore
    from kimi.memory.database import Database

    db = Database(tmp_path / "s.db")
    store = SettingsStore(db)
    assert store.get().world_view == "3d" and store.get().graphics_quality == "high"
    s = store.update(world_view="hologram", graphics_quality="ultra")
    assert s.world_view == "3d" and s.graphics_quality == "high"
    assert store.update(world_view="map", graphics_quality="low").world_view == "map"
    db.close()


# -- the QML scene (skipped where Qt Quick 3D can't load) ------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    pytest.importorskip("PySide6.QtQuick3D", exc_type=ImportError)
    return widgets.QApplication.instance() or widgets.QApplication([])


def _dispose(app, *widgets) -> None:
    """Delete Qt Quick widgets while the application is alive (avoids crashes at interpreter exit)."""
    from PySide6.QtCore import QEvent

    for w in widgets:
        w.close()
        w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_qml_scene_loads_without_errors(qt_app, make_runtime):
    from PySide6.QtQuickWidgets import QQuickWidget

    from kimi.ui.world3d.view import World3DView

    rt = make_runtime()
    view = World3DView(rt)
    assert view.status() == QQuickWidget.Status.Ready, [e.toString() for e in view.errors()]
    assert view.errors() == []
    root = view.rootObject()
    root.showTown()
    assert root.property("cameraMode") == "town"
    root.followKimi()
    assert root.property("cameraMode") == "follow"
    view.set_snapshot(rt.snapshot())
    view.show()
    view._poll()
    assert view.bridge.state["location"] in LOCATIONS
    _dispose(qt_app, view)


def test_world_page_falls_back_to_the_map(qt_app, make_runtime):
    from kimi.ui.world_view import WorldPage

    rt = make_runtime()
    page = WorldPage(rt, mode="3d")
    assert page.mode == "3d" and page.view3d is not None
    page.view3d.failed.emit("no graphics")
    assert page.mode == "map"
    assert not page.btn_3d.isEnabled() and "map" in page.view_note.text()
    page.update_from(rt.snapshot())
    map_page = WorldPage(rt, mode="map")
    assert map_page.mode == "map" and map_page.view3d is None
    _dispose(qt_app, page, map_page)
