"""Kimi asking the human for something: limits, safety, replies, wishlist, expiry."""

from __future__ import annotations

import json

import pytest

from kimi.actions.validators import ActionRejected, ValidationContext, validate_decision
from kimi.ai.mock import ScriptedHaiku, decision, make_response
from kimi.ai.prompts import SYSTEM_PROMPT, decision_schema
from kimi.requests import EXPIRE_AFTER_S, MIN_GAP_S, request_problem
from kimi.world.locations import LocationGraph


def _ctx(allowed=True, why=""):
    return ValidationContext(graph=LocationGraph(), current_location="nest", ask_allowed=allowed, ask_block_reason=why)


def test_kimi_knows_about_asking():
    assert "ask_human" in SYSTEM_PROMPT and "wishlist" in SYSTEM_PROMPT
    props = decision_schema()["properties"]
    assert "ask_human" in props["action"]["enum"]
    assert props["request_kind"]["anyOf"][0]["enum"] == ["artefact", "information"]


def test_ask_validation():
    va = validate_decision(decision("ask_human", request_kind="artefact", title="A little swing",
                                    content="Could there be a swing by the pond? I'd love to sway over the lilies."), _ctx())
    assert va.action == "ask_human" and va.params["kind"] == "artefact" and va.required_location is None
    with pytest.raises(ActionRejected, match="today"):
        validate_decision(decision("ask_human", request_kind="information", title="Stars",
                                   content="What are stars made of, really?"), _ctx(False, "asked today"))
    with pytest.raises(ActionRejected):
        validate_decision(decision("ask_human", title="Stars", content="What are stars made of, really?"), _ctx())
    with pytest.raises(ActionRejected):
        validate_decision(decision("ask_human", request_kind="information", title="Hi", content="?"), _ctx())


@pytest.mark.parametrize("text", [
    "Could you tell me your password?", "What is your email address?", "Please buy me some seeds",
    "Can you send me money for a hat", "What's the API key?", "Could you download a game for me",
    "Where you live, is it near the sea?", "Can I look through your camera?",
])
def test_kimi_can_never_ask_for_things_outside_its_world(text):
    assert request_problem("information", "A question", text) is not None
    with pytest.raises(ActionRejected, match="outside Bramblewick"):
        validate_decision(decision("ask_human", request_kind="information", title="A question", content=text), _ctx())


def test_harmless_requests_pass():
    assert request_problem("information", "The sea", "What is the sea like? I've only seen the lake.") is None
    assert request_problem("artefact", "A tiny bridge", "Could there be a tiny bridge over the pond?") is None
    assert request_problem("information", "Keys", "How do keys open locks?") is None


class AskResponder:
    def __init__(self, kind="information", title="The sea", content="What is the sea like? I've only seen the lake."):
        self.body = decision("ask_human", request_kind=kind, title=title, content=content, thought="I wonder...")
        self.scripted = ScriptedHaiku()
        self.asked = 0

    def __call__(self, kwargs):
        props = set((((kwargs.get("output_config") or {}).get("format") or {}).get("schema") or {}).get("properties", {}))
        if "action" in props and "Asking the human (ask_human) is possible" in kwargs["messages"][-1]["content"]:
            self.asked += 1
            return make_response(json.dumps(self.body))
        return self.scripted(kwargs)


def _run_until_request(rt, minutes=240):
    for _ in range(minutes // 5):
        rt.advance_world(5, step=2.0)
        if rt.requests.open_request():
            return rt.requests.open_request()
    return None


def test_question_answer_becomes_a_memory(make_runtime):
    rt = make_runtime(AskResponder())
    req = _run_until_request(rt)
    assert req and req["kind"] == "information" and req["title"] == "The sea"
    assert rt.snapshot()["request"]["id"] == req["id"]
    assert any(h["kind"] == "request" for h in rt.highlights)
    # One open request at a time, and the daily limit (1) is used up.
    assert rt.ask_status()[0] is False
    ok, _ = rt.answer_request(req["id"], "wishlist")
    assert not ok                                  # wrong reply type for a question
    ok, msg = rt.answer_request(req["id"], "answer", "It's like the lake, but it never ends and it tastes of salt.")
    assert ok
    assert rt.requests.get(req["id"])["status"] == "answered"
    assert any("tastes of salt" in m.description for m in rt.stm.recent(10))
    lines = rt.cognition.request_lines()
    assert any("<human_reply>" in line and "salt" in line for line in lines)
    assert rt.answer_request(req["id"], "answer", "again")[0] is False


def test_wishes_go_on_the_wishlist(make_runtime):
    rt = make_runtime(AskResponder("artefact", "A little swing", "Could there be a swing by the pond, please?"))
    req = _run_until_request(rt)
    assert req and req["kind"] == "artefact"
    ok, _ = rt.answer_request(req["id"], "wishlist", "Lovely idea!")
    assert ok
    text = rt.paths.wishlist.read_text(encoding="utf-8")
    assert "A little swing" in text and "Lovely idea!" in text and "swing by the pond" in text
    assert any("wishlist" in m.description for m in rt.stm.recent(10))


def test_decline_and_expiry(make_runtime):
    rt = make_runtime()
    rid = rt.requests.create("artefact", "A hot-air balloon", "A balloon to see the whole island from above!", 1, "nest")
    ok, _ = rt.answer_request(rid, "decline", "Maybe one day")
    assert ok and rt.requests.get(rid)["status"] == "declined"
    rid2 = rt.requests.create("information", "Rain", "Where does rain come from before it falls?", 1, "nest")
    rt.db.execute("UPDATE human_requests SET created_at=? WHERE id=?", (rt.wall() - EXPIRE_AFTER_S - 10, rid2))
    rt.expire_requests()
    assert rt.requests.get(rid2)["status"] == "expired"
    assert any("didn't get round" in m.description for m in rt.stm.recent(10))


def test_limits(make_runtime):
    rt = make_runtime()
    assert rt.ask_status() == (True, "")
    rt.update_settings(ask_human_daily_limit=9)
    assert rt.settings.get().ask_human_daily_limit == 2      # twice a day at the very most
    rid = rt.requests.create("information", "Owls", "How do owls see in the dark?", 1, "nest")
    assert "waiting" in rt.ask_status()[1]
    rt.answer_request(rid, "answer", "Huge eyes that gather every bit of light.")
    assert "few hours" in rt.ask_status()[1]                  # six hours between requests
    rt.db.execute("UPDATE human_requests SET created_at=?", (rt.wall() - MIN_GAP_S - 5,))
    assert rt.ask_status()[0] is True                         # second of two today
    rt.requests.create("information", "Moths", "Why do moths love lanterns?", 1, "nest")
    rt.db.execute("UPDATE human_requests SET status='answered', created_at=?", (rt.wall() - MIN_GAP_S - 5,))
    assert "already asked" in rt.ask_status()[1]
    rt.update_settings(ask_human_enabled=False)
    assert "turned off" in rt.ask_status()[1]
