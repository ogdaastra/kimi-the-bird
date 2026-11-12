"""Guards against Anthropic refusing Kimi's reply shapes (the 17-union-parameter bug, and its cousins).

Layers, each tested here:
1. Kimi's schemas satisfy Anthropic's published limits, with headroom.
2. The offline mock Haiku enforces the same limits, so any test that sends a bad shape fails.
3. The client checks before sending and remembers shapes Anthropic refused.
4. After an update, Kimi asks Anthropic once whether it accepts its shapes and says clearly if not.
5. Refusals are reported once, then Kimi backs off instead of retrying every few minutes.
"""

from __future__ import annotations

import json

import pytest

from kimi.actions.validators import ValidationContext, validate_decision
from kimi.ai.claude_client import AIError, ClaudeClient
from kimi.ai.costs import UsageLedger
from kimi.ai.mock import ScriptedHaiku, make_response, mock_factory, schema_rejection
from kimi.ai.prompts import decision_schema, image_schema, reflection_schema, research_schema
from kimi.ai.schema_rules import MAX_UNION_PARAMS, counts, schema_problems, within_kimi_budget
from kimi.config import SettingsStore
from kimi.memory.database import Database
from kimi.world.locations import LocationGraph

from .conftest import TEST_KEY, FakeClock
from .helpers import api_error

ALL = [decision_schema, research_schema, reflection_schema, image_schema]


def _nullable_props(n: int) -> dict:
    props = {f"f{i}": {"anyOf": [{"type": "string"}, {"type": "null"}]} for i in range(n)}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


# -- 1. Kimi's own schemas ----------------------------------------------------------------

@pytest.mark.parametrize("make", ALL)
def test_kimis_schemas_follow_anthropics_rules_with_headroom(make):
    schema = make()
    assert schema_problems([schema]) == []
    assert within_kimi_budget(schema) == []


def test_all_schemas_together_still_fit():
    # Even if one request ever carried several shapes, the combined total stays legal.
    assert schema_problems([m() for m in ALL]) == []


def test_the_bug_that_happened_is_caught():
    assert counts(_nullable_props(17))["unions"] == 17
    problems = schema_problems([_nullable_props(17)])
    assert any("17 parameters use anyOf" in p for p in problems)
    assert schema_problems([_nullable_props(MAX_UNION_PARAMS)]) == []


@pytest.mark.parametrize("bad, words", [
    ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}, "additionalProperties"),
    ({"type": "object", "properties": {"a": {"type": "integer", "minimum": 0}}, "required": ["a"],
      "additionalProperties": False}, "minimum"),
    ({"type": "object", "properties": {"a": {"type": "string", "maxLength": 9}}, "required": ["a"],
      "additionalProperties": False}, "maxLength"),
    ({"type": "object", "properties": {"a": {"type": "array", "items": {"type": "string"}, "minItems": 3}},
      "required": ["a"], "additionalProperties": False}, "minItems"),
    ({"type": "object", "properties": {"a": {"$ref": "http://example.com/s.json"}}, "required": ["a"],
      "additionalProperties": False}, "external"),
    ({"type": "object", "properties": {"a": {"enum": [{"x": 1}]}}, "required": ["a"],
      "additionalProperties": False}, "complex types"),
])
def test_other_published_rules(bad, words):
    assert any(words in p for p in schema_problems([bad]))


def test_optional_parameter_limit():
    props = {f"o{i}": {"type": "string"} for i in range(25)}
    schema = {"type": "object", "properties": props, "required": [], "additionalProperties": False}
    assert any("25 optional" in p for p in schema_problems([schema]))


def test_property_names_are_not_mistaken_for_keywords():
    schema = {"type": "object", "properties": {"minimum": {"type": "string"}, "pattern": {"type": "string"}},
              "required": ["minimum", "pattern"], "additionalProperties": False}
    assert schema_problems([schema]) == []


# -- 2. The mock enforces the rules -----------------------------------------------------------

def test_mock_api_refuses_bad_shapes_like_the_real_one():
    kwargs = {"output_config": {"format": {"type": "json_schema", "schema": _nullable_props(17)}}}
    err = schema_rejection(kwargs)
    assert err is not None and err.status_code == 400 and "anyOf" in err.message
    assert schema_rejection({"output_config": {"format": {"type": "json_schema", "schema": decision_schema()}}}) is None


# -- 3. The client ---------------------------------------------------------------------------------

@pytest.fixture
def client_env(tmp_path):
    db = Database(tmp_path / "s.db")
    settings = SettingsStore(db)
    settings.update(min_request_gap_s=0.5, daily_budget_usd=1.0)
    ledger = UsageLedger(db, settings)
    clock = FakeClock()

    def make(responder):
        return ClaudeClient(lambda: TEST_KEY, ledger, settings, mock_factory(responder),
                            sleep=lambda s: clock.advance(s), mono=clock)

    yield make, ledger
    db.close()


def test_client_never_sends_a_shape_that_breaks_the_rules(client_env):
    make, ledger = client_env
    calls = []
    client = make(lambda kw: calls.append(kw) or make_response("{}"))
    with pytest.raises(AIError) as err:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=100, schema=_nullable_props(17))
    assert err.value.kind == "schema" and "update Kimi" in err.value.message
    assert calls == [] and ledger.requests_today() == 0          # nothing was sent, nothing spent


def test_client_remembers_a_shape_anthropic_refused(client_env):
    make, _ = client_env
    calls = []
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
              "additionalProperties": False}

    def responder(kw):
        calls.append(kw)
        return api_error(__import__("anthropic").BadRequestError, 400, "Schema is too complex for compilation.")

    client = make(responder)
    with pytest.raises(AIError) as first:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=100, schema=schema)
    assert first.value.kind == "bad_request"
    with pytest.raises(AIError) as second:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=100, schema=schema)
    assert second.value.kind == "schema" and "refused" in second.value.message
    assert len(calls) == 1                                           # not sent again


def test_check_schema_results(client_env):
    make, _ = client_env
    ok_client = make(lambda kw: make_response('{"act', stop_reason="max_tokens", output_tokens=16))
    assert ok_client.check_schema("decisions", decision_schema()) == (True, "")
    refused = make(lambda kw: api_error(__import__("anthropic").BadRequestError, 400,
                                        "Schemas contains too many parameters with union types"))
    ok, why = refused.check_schema("decisions", decision_schema())
    assert ok is False and "union types" in why
    from .helpers import connection_error
    offline = make(lambda kw: connection_error())
    assert offline.check_schema("decisions", decision_schema())[0] is None


# -- 4. The self-check after an update ------------------------------------------------------------

def test_self_check_runs_once_per_update(make_runtime, paths):
    responder = ScriptedHaiku()
    rt = make_runtime(responder, schema_self_check=True)
    rt.advance_world(2, step=1.0)
    checks = [c for c in responder.calls if "Schema check" in str(c.get("system"))]
    assert len(checks) == 4
    stored = rt.db.kv_get(rt.SCHEMA_CHECK_KEY)
    assert stored["ok"] is True and stored["fingerprint"] == rt.reply_shapes_fingerprint()
    rt.shutdown()
    again = make_runtime(ScriptedHaiku(), schema_self_check=True)       # same data, same version
    again.advance_world(2, step=1.0)
    assert not [c for c in again.responder.calls if "Schema check" in str(c.get("system"))]


def test_self_check_explains_a_refusal(make_runtime):
    import anthropic

    def responder(kw):
        if "Schema check" in str(kw.get("system")) and "action" in json.dumps(kw.get("output_config")):
            return api_error(anthropic.BadRequestError, 400, "Schema is too complex for compilation.")
        return ScriptedHaiku()(kw)

    rt = make_runtime(responder, schema_self_check=True, autonomous_enabled=True)
    rt.advance_world(2, step=1.0)
    stored = rt.db.kv_get(rt.SCHEMA_CHECK_KEY)
    assert stored["ok"] is False and "decisions" in stored["refused"]
    assert any("Heads up" in h["text"] and "decisions" in h["text"] for h in rt.highlights)


# -- 5. Reported once, then back off ----------------------------------------------------------------

def test_refusals_are_reported_once_and_kimi_backs_off(make_runtime):
    import anthropic

    def responder(kw):
        return api_error(anthropic.BadRequestError, 400, "Schemas contains too many parameters with union types")

    rt = make_runtime(responder, decision_min_interval_s=60, decision_max_interval_s=3600)
    rt.advance_world(240, step=2.0)
    notes = [e for e in rt.recent_events if "being refused" in e["text"]]
    assert len(notes) == 1 and notes[0]["importance"] >= 0.7
    assert rt.cognition.idle_multiplier > 1.0                    # waiting longer between attempts


def test_enum_values_are_case_insensitive():
    ctx = ValidationContext(graph=LocationGraph(), current_location="nest")
    va = validate_decision({"action": "Visit_Location", "destination": "Shrub", "mood": "Curious",
                            "duration_minutes": 20}, ctx)
    assert va.action == "visit_location" and va.params["destination"] == "shrub"
    assert va.extras["mood"] == "curious"
