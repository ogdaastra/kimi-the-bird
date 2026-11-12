"""World movement, needs, day/night and persistence."""

import random

from kimi.world.environment import Environment
from kimi.world.locations import LocationGraph
from kimi.world.needs import Needs
from kimi.world.world import PlanStep, World


def test_shortest_path_uses_connected_places():
    g = LocationGraph()
    path, minutes = g.shortest_path("nest", "cafe")
    assert path == ["nest", "shrub", "square", "cafe"]
    assert minutes == 6 + 7 + 5
    for a, b in zip(path, path[1:]):
        assert b in g.neighbours(a)


def test_movement_is_a_journey_not_a_teleport():
    w = World(rng=random.Random(1))
    total = w.begin_travel("cafe", PlanStep("move_to", {"destination": "cafe"}))
    assert total == 18
    assert w.location is None and w.state_label == "travelling"
    events = []
    positions = []
    for _ in range(36):
        events += w.tick(0.5)
        positions.append(w.position())
    kinds = [(e.kind, e.location) for e in events if e.kind in ("passed", "arrived")]
    assert kinds == [("passed", "shrub"), ("passed", "square"), ("arrived", "cafe")]
    assert w.location == "cafe" and w.travel is None
    # Position moves in small steps along the way.
    jumps = [abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(positions, positions[1:])]
    assert max(jumps) < 0.1


def test_interrupt_stops_at_a_place():
    w = World(rng=random.Random(1))
    w.begin_travel("cafe", PlanStep("move_to", {"destination": "cafe"}))
    w.tick(4)
    dropped = w.interrupt()
    assert w.location in ("nest", "shrub") and w.travel is None and dropped


def test_needs_evolve_gently():
    n = Needs(hunger=20, energy=80, curiosity=50, happiness=60, social=30)
    n.tick(120, "explore")
    assert n.hunger > 20 and n.energy < 80 and n.curiosity > 50 and n.social > 30
    tired = Needs(energy=20)
    tired.tick(60, "rest")
    assert tired.energy > 20
    sleeper = Needs(energy=10)
    sleeper.tick(480, "sleep")
    assert sleeper.energy >= 100 - 1e-9
    starving = Needs(hunger=99)
    starving.tick(600, "idle")
    assert starving.hunger == 100  # clamped, never beyond
    # Twelve hours idle does not make Kimi desperate.
    calm = Needs()
    calm.tick(12 * 60, "idle")
    assert calm.happiness > 30


def test_day_night_cycle():
    env = Environment(minute=12 * 60)
    assert not env.is_night and env.light_level == 1.0 and env.time_of_day == "afternoon"
    rng = random.Random(2)
    events = env.advance(11 * 60, rng)
    assert env.is_night and env.light_level < 0.5
    assert any(k == "time" and "Night" in t for k, t in events)
    env.advance(9 * 60, rng)
    assert env.day == 2 and not env.is_night


def test_world_state_round_trip():
    w = World(rng=random.Random(3))
    w.needs.hunger = 77
    w.begin_travel("library", PlanStep("move_to", {"destination": "library"}, log_id=5))
    w.tick(3)
    w.enqueue([PlanStep("research", {"topic": "owls"})])
    restored = World.from_dict(w.to_dict())
    assert restored.travel is not None and restored.travel.path == w.travel.path
    assert restored.travel.leg_elapsed == w.travel.leg_elapsed
    assert restored.needs.hunger == w.needs.hunger
    assert restored.plan[0].params == {"topic": "owls"}
    assert restored.env.minute == w.env.minute


def test_corrupted_state_falls_back_safely():
    w = World.from_dict({"location": "atlantis", "activity": {"bad": 1}, "plan": [None, 5]})
    assert w.location == "nest" and w.activity is None


def test_every_action_counts_towards_needs():
    from kimi.safety import ALLOWED_ACTIONS
    from kimi.world.needs import ACTIVITY_CLASS

    missing = [a for a in ALLOWED_ACTIONS if a not in ACTIVITY_CLASS]
    assert missing == []


def test_happiness_and_curiosity_have_soft_limits():
    n = Needs(happiness=95, curiosity=4)
    n.adjust(happiness=10, curiosity=-10)
    assert 95 < n.happiness < 97 and 3 < n.curiosity < 4      # small changes near the edges
    m = Needs(happiness=40, curiosity=60)
    m.adjust(happiness=10, curiosity=-10)
    assert m.happiness == 50 and m.curiosity == 50            # full changes in the middle
    k = Needs(curiosity=0)
    for _ in range(24):
        k.tick(60, "idle")
    assert k.curiosity > 30                                    # drifts back up on its own
