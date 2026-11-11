"""Bramblewick's curiosities: the catalogue, where they sit, what Kimi knows, and examining them."""

from __future__ import annotations

import json
import math

import pytest

from kimi.actions.validators import ActionRejected, ValidationContext, validate_decision
from kimi.ai.mock import ScriptedHaiku, decision, make_response
from kimi.ai.prompts import SYSTEM_PROMPT, decision_schema
from kimi.world import layout3d
from kimi.world.curio3d import BUILDING_R, BUILDERS, POND_RADIUS, build_curiosities, curiosity_layout, curiosity_spots
from kimi.world.curiosities import BY_ID, CURIOSITIES, detail_for
from kimi.world.locations import LOCATIONS, LocationGraph
from kimi.world.mesh3d import _pond_centre, height


def test_there_are_loads_of_curiosities_and_each_is_complete():
    assert len(CURIOSITIES) >= 60
    assert len(BY_ID) == len(CURIOSITIES)          # unique ids
    assert len({c.name for c in CURIOSITIES}) == len(CURIOSITIES)
    for c in CURIOSITIES:
        assert c.kind in BUILDERS, c.id
        assert c.zone is None or c.zone in LOCATIONS
        assert len(c.what) > 30 and not c.what.endswith(".")
        assert len(c.details) == 3 and all(len(d) > 15 for d in c.details)
        assert c.tags


def test_details_unfold_one_per_visit_then_repeat():
    c = BY_ID["tiny_door"]
    assert [detail_for(c, n) for n in (1, 2, 3)] == list(c.details)
    assert detail_for(c, 4).startswith("It's as wonderful as ever")


def test_kimi_is_told_what_every_curiosity_is():
    for c in CURIOSITIES:
        assert f"[{c.id}] {c.name}" in SYSTEM_PROMPT
        assert c.what in SYSTEM_PROMPT
    schema = decision_schema()["properties"]
    ids = schema["curiosity_id"]["anyOf"][0]["enum"]
    assert set(ids) == set(BY_ID)
    assert "examine" in schema["action"]["enum"]


def test_curiosities_sit_in_sensible_free_places():
    spots = curiosity_spots()
    pond = _pond_centre()
    polys = layout3d.path_polylines()
    placed = []
    for c in CURIOSITIES:
        s = spots[c.id]
        assert s["zone"] in LOCATIONS
        kind = c.spot[0]
        if kind in ("near", "hill", "shore"):
            for p in layout3d.PLACES.values():
                if p.id != "square":
                    assert math.hypot(s["x"] - p.x, s["z"] - p.z) > BUILDING_R[p.id], (c.id, p.id)
            assert layout3d.distance_to_paths(s["x"], s["z"], polys) >= layout3d.PATH_WIDTH / 2, c.id
            assert math.hypot(s["x"] - pond[0], s["z"] - pond[1]) > POND_RADIUS, c.id
            placed.append((s["x"], s["z"], c.size / 2, c.id))
        if kind == "pond":
            assert math.hypot(s["x"] - pond[0], s["z"] - pond[1]) <= POND_RADIUS
        if kind in ("hill", "shore"):
            assert height(s["x"], s["z"]) > layout3d.WATER_LEVEL, c.id
        assert math.hypot(s["standX"], s["standZ"]) < layout3d.ISLAND_RADIUS + 50
    for i, (x, z, r, a) in enumerate(placed):
        for x2, z2, r2, b in placed[i + 1:]:
            assert math.hypot(x - x2, z - z2) >= r + r2, (a, b)


def test_curiosity_models_are_built():
    solid, glow = build_curiosities()
    assert solid.vertex_count > 20000 and solid.vertex_count % 3 == 0
    assert glow.vertex_count > 0
    assert len(solid.vertices) == solid.vertex_count * 10
    lay = curiosity_layout()
    assert len(lay) == len(CURIOSITIES) and all(item["y"] > 0 for item in lay)


def test_kimi_stands_in_front_of_what_it_examines():
    spot = curiosity_spots()["wishing_well"]
    t = layout3d.kimi_target({"location": spot["zone"], "action": "examine", "curiosity": "wishing_well"})
    assert (t["x"], t["z"]) == (spot["standX"], spot["standZ"])
    assert t["mode"] == "examine" and not t["wander"]
    # Kimi faces the well.
    hx, hz = math.sin(math.radians(t["heading"])), math.cos(math.radians(t["heading"]))
    dx, dz = spot["x"] - t["x"], spot["z"] - t["z"]
    assert hx * dx + hz * dz > 0


def test_examine_validation():
    g = LocationGraph()
    ctx = ValidationContext(graph=g, current_location="nest",
                            curiosity_zones={cid: s["zone"] for cid, s in curiosity_spots().items()})
    va = validate_decision(decision("examine", curiosity_id="giant_shell"), ctx)
    assert va.action == "examine" and va.required_location == "shrub" and va.params["curiosity"] == "giant_shell"
    va = validate_decision(decision("examine", curiosity_id="little_lighthouse"), ctx)
    assert va.required_location == curiosity_spots()["little_lighthouse"]["zone"]
    with pytest.raises(ActionRejected):
        validate_decision(decision("examine", curiosity_id="the_moon"), ctx)
    with pytest.raises(ActionRejected):
        validate_decision(decision("examine"), ctx)


class ExamineResponder:
    def __init__(self, cid):
        self.cid = cid
        self.scripted = ScriptedHaiku()

    def __call__(self, kwargs):
        props = set((((kwargs.get("output_config") or {}).get("format") or {}).get("schema") or {}).get("properties", {}))
        if "action" in props:
            return make_response(json.dumps(decision("examine", curiosity_id=self.cid, thought="Let me look closer.")))
        return self.scripted(kwargs)


def test_examining_a_curiosity_uncovers_details_and_memories(make_runtime):
    rt = make_runtime(ExamineResponder("tiny_door"), decision_min_interval_s=30)
    for _ in range(60):
        rt.advance_world(5, step=2.0)
        if rt.curiosity_visits().get("tiny_door", {}).get("visits", 0) >= 2:
            break
    v = rt.curiosity_visits()["tiny_door"]
    assert v["visits"] >= 2
    c = BY_ID["tiny_door"]
    texts = [m.description for m in rt.stm.recent(60)]
    assert any(c.name in t and c.details[0] in t for t in texts)
    assert any(c.details[1] in t for t in texts)
    goals = [g for g in rt.character.active_goals() if "every curiosity" in g["text"]]
    assert goals and goals[0]["progress"] == 1 and goals[0]["target"] == len(CURIOSITIES)


def test_decision_context_lists_nearby_curiosities(make_runtime):
    rt = make_runtime()
    ctx = rt.cognition.build_context()
    text = "\n".join(ctx.curiosities)
    assert "examined 0 of" in text
    nest_ids = [c.id for c in CURIOSITIES if curiosity_spots()[c.id]["zone"] == "nest"]
    assert f"[{nest_ids[0]}]" in text and "not examined yet" in text
    assert "Not examined yet elsewhere" in text


def test_exploring_can_notice_a_curiosity(make_runtime):
    rt = make_runtime()
    noticed = None
    for _ in range(20):
        noticed = rt.handler._notice_curiosity("shrine")
        if noticed:
            break
    assert noticed and noticed.startswith("Spotted")
    assert any("Spotted" in m.description for m in rt.stm.recent(5))


def test_pose_reports_the_curiosity_being_examined(make_runtime):
    rt = make_runtime(ExamineResponder("acorn_chimes"), decision_min_interval_s=30)
    for _ in range(40):
        rt.advance_world(2, step=1.0)
        if rt.pose()["action"] == "examine":
            break
    assert rt.pose()["action"] == "examine" and rt.pose()["curiosity"] == "acorn_chimes"


def test_scene_bridge_knows_about_curiosities():
    pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
    from kimi.ui.world3d.bridge import build_layout, compute_state

    lay = build_layout()
    assert len(lay["curiosities"]) == len(CURIOSITIES)
    assert lay["beacons"] and lay["beacons"][0]["y"] > 0
    st = compute_state({"location": "shrine", "action": "examine", "curiosity": "wishing_well", "hour": 10},
                       {"curiosities_seen": ["wishing_well"]}, {})
    assert st["mode"] == "examine" and st["curiosity"] == "wishing_well"
    assert st["curiositiesSeen"] == ["wishing_well"]


def test_system_prompt_leaves_room_for_the_situation():
    from kimi.ai.costs import estimate_tokens
    from kimi.config import Settings

    assert estimate_tokens(SYSTEM_PROMPT) < Settings().max_input_tokens - 3000
