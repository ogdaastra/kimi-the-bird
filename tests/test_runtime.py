"""The autonomous loop, controls, budget behaviour, shutdown and crash recovery."""

import json

from kimi.ai.mock import ScriptedHaiku, decision, make_response
from kimi.config import Paths

from .helpers import Sequence


def api_calls(rt) -> list[dict]:
    return [c for c in rt.responder.calls] if hasattr(rt.responder, "calls") else []


def test_autonomous_loop_runs_and_acts(make_runtime):
    rt = make_runtime()
    rt.advance_world(6 * 60, step=2.0)
    rows = rt.db.query("SELECT action, source, status FROM action_log")
    mind_actions = {r["action"] for r in rows if r["source"] == "mind" and r["status"] == "completed"}
    assert len(mind_actions) >= 3
    assert rt.stm.count() > 3
    assert rt.ledger.today_stats()["requests"] >= 3
    assert rt.world.env.hour >= 13
    # Decisions are paced: far fewer API calls than ticks.
    assert rt.ledger.today_stats()["requests"] < 40


def test_decision_context_contains_required_information(make_runtime):
    rt = make_runtime()
    rt.advance_world(30)
    ctx = rt.cognition.build_context()
    from kimi.ai.prompts import render_decision_context

    text = render_decision_context(ctx)
    for part in ("<now>", "Location:", "hunger", "energy", "curiosity", "Interests:", "<places>",
                 "Weather:", "what would you naturally like to do next?"):
        assert part in text
    assert len(text) < 12_000  # bounded, never the whole database


def test_pause_freezes_world_and_ai(make_runtime):
    rt = make_runtime()
    rt.pause()
    minute = rt.world.env.minute
    rt.advance_world(120)
    assert rt.world.env.minute == minute
    assert rt.ledger.today_stats()["requests"] == 0
    assert rt.status() == "paused"
    rt.resume()
    rt.advance_world(30)
    assert rt.world.env.minute > minute


def test_emergency_stop_halts_everything(make_runtime):
    rt = make_runtime()
    rt.advance_world(60)
    before = rt.ledger.today_stats()["requests"]
    rt.emergency_stop()
    assert rt.status() == "stopped"
    assert rt.world.activity is None and rt.world.travel is None and not rt.world.plan
    rt.advance_world(240)
    assert rt.ledger.today_stats()["requests"] == before
    assert rt.world.activity is None
    statuses = {r["status"] for r in rt.db.query("SELECT status FROM action_log")}
    assert "interrupted" in statuses or before == 0
    rt.set_autonomous(True)
    rt.cognition.next_decision_at = 0
    rt.advance_world(30)
    assert rt.ledger.today_stats()["requests"] > before


def test_autonomy_off_means_no_ai_or_actions(make_runtime):
    rt = make_runtime()
    rt.set_autonomous(False)
    rt.advance_world(180)
    assert rt.ledger.today_stats()["requests"] == 0
    assert rt.db.scalar("SELECT COUNT(*) FROM action_log") == 0
    assert rt.status() == "autonomy_off"


def test_budget_limit_pauses_ai_but_world_continues(make_runtime):
    expensive = Sequence(make_response(json.dumps(decision("rest", duration_minutes=10)),
                                       input_tokens=150_000, output_tokens=20_000))
    rt = make_runtime(expensive, daily_budget_usd=0.02)
    rt.advance_world(4 * 60, step=2.0)
    assert len(expensive.calls) == 1  # one call, then the budget guard refuses more
    assert rt.status() == "budget_paused"
    assert rt.world.env.hour >= 11  # time kept flowing
    sources = {r["source"] for r in rt.db.query("SELECT source FROM action_log WHERE status='completed'")}
    assert "fallback" in sources  # Kimi kept living on local habits
    rt.update_settings(daily_budget_usd=5.0)
    rt.cognition.next_decision_at = 0
    rt.advance_world(30)
    assert len(expensive.calls) >= 2


def test_no_api_key_means_no_requests(make_runtime):
    responder = ScriptedHaiku()
    rt = make_runtime(responder, key=None)
    rt.advance_world(120)
    assert responder.calls == []
    assert rt.status() == "needs_key"
    assert rt.db.scalar("SELECT COUNT(*) FROM action_log WHERE source='fallback'") > 0


def test_rejected_model_action_is_logged_and_replaced(make_runtime):
    responder = Sequence(make_response(json.dumps({**decision("rest"), "action": "run_shell"})))
    rt = make_runtime(responder)
    rt.advance_world(10)
    row = rt.db.query_one("SELECT * FROM action_log WHERE status='rejected'")
    assert row is not None and "run_shell" in row["action"]
    assert rt.db.scalar("SELECT COUNT(*) FROM action_log WHERE source='fallback'") >= 1


def test_instincts_handle_night_and_hunger(make_runtime):
    rt = make_runtime()
    rt.world.env.minute = 22 * 60 + 30
    rt.advance_world(2)
    labels = [s.action for s in rt.world.plan] + ([rt.world.travel.step.action] if rt.world.travel else []) + \
        ([rt.world.activity.step.action] if rt.world.activity else [])
    assert "sleep" in labels or rt.world.asleep
    # Instincts are free: no decision request was needed (the nightly reflection may run).
    assert rt.db.scalar("SELECT COUNT(*) FROM api_usage WHERE purpose='decision'") == 0
    rt.world.interrupt()
    rt.world.env.minute = 2 * 1440 + 10 * 60
    rt.world.needs.hunger = 95
    rt.cognition.next_decision_at = 1e12
    rt.advance_world(1)
    planned = [s.action for s in rt.world.plan] + ([rt.world.activity.step.action] if rt.world.activity else []) + \
        ([rt.world.travel.step.action] if rt.world.travel else [])
    assert "eat" in planned or rt.world.travel is not None


def test_sleep_triggers_nightly_consolidation_and_reflection(make_runtime):
    rt = make_runtime()
    rt.advance_world(15 * 60, step=2.0)  # 08:00 -> 23:00
    assert rt.db.kv_get("last_consolidation") is not None
    reflections = [e for e in rt.diary.list() if e.kind == "reflection"]
    assert reflections and len(reflections[0].body) > 40
    assert rt.ltm.count() >= 1


def test_adaptive_idle_spacing(make_runtime):
    quiet = Sequence(make_response(json.dumps(decision("rest", duration_minutes=10))))
    rt = make_runtime(quiet, decision_min_interval_s=60, decision_max_interval_s=600)
    rt.advance_world(3 * 60, step=1.0)
    assert rt.cognition.idle_multiplier > 1.0
    gaps_ok = len(quiet.calls) < 3 * 60 / 4  # far fewer than one per minute of real time
    assert gaps_ok


def test_shutdown_and_restore(make_runtime, paths):
    rt = make_runtime()
    rt.advance_world(90)
    location, minute = rt.world.location, rt.world.env.minute
    hunger = rt.world.needs.hunger
    memories = rt.stm.count()
    rt.shutdown()
    rt2 = make_runtime()
    assert not rt2.recovered_from_crash
    assert rt2.world.location == location
    assert abs(rt2.world.env.minute - minute) < 1e-6
    assert abs(rt2.world.needs.hunger - hunger) < 0.01
    assert rt2.stm.count() >= memories


def test_recovery_after_crash(make_runtime, paths, tmp_path):
    rt = make_runtime()
    rt.advance_world(60)
    rt.save()
    saved_minute = rt.world.env.minute
    # Simulate a crash: the process dies without a clean shutdown.
    rt._stop.set()
    rt.closed = True
    rt.db.close()
    rt2 = make_runtime()
    assert rt2.recovered_from_crash
    assert abs(rt2.world.env.minute - saved_minute) < 1e-6
    assert any("unexpected shutdown" in e["text"] for e in rt2.recent_events)
    rt2.advance_world(60)  # carries on normally
    assert rt2.world.env.minute > saved_minute


def test_corrupted_world_state_does_not_prevent_startup(make_runtime, paths):
    rt = make_runtime()
    rt.shutdown()
    from kimi.memory.database import Database

    db = Database(paths.db)
    db.kv_set("world_state", {"env": "garbage", "needs": [1, 2], "location": 42})
    db.close()
    rt2 = make_runtime()
    assert rt2.world.location in rt2.world.graph.locations


def test_sharing_requires_explicit_approval(make_runtime):
    responder = Sequence(
        make_response(json.dumps(decision("create_art", art_kind="poem", title="Moss Song",
                                          content="Soft green hush beneath my feet, the moss and I are quiet."))),
        make_response(json.dumps(decision("share_creation", creation_id=1))),
        make_response(json.dumps(decision("rest", duration_minutes=60))),
    )
    rt = make_runtime(responder, external_sharing_enabled=True)
    rt.advance_world(4 * 60, step=1.0)
    pending = rt.outbox.pending()
    assert len(pending) == 1 and pending[0]["status"] == "pending"
    ok, message, url = rt.approve_share(pending[0]["id"], "email")
    assert ok and url.startswith("mailto:")  # a draft for the user to send - nothing is sent by Kimi
    assert rt.outbox.get(pending[0]["id"])["status"] == "approved"
