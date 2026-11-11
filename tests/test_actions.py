"""Action validation, safety boundaries, creative output and research access."""

import json
from xml.etree import ElementTree

import pytest

from kimi.actions.creative import CreativeStudio, render_drawing
from kimi.actions.research import ResearchUnavailable, WikipediaResearcher
from kimi.actions.sharing import valid_github_remote
from kimi.actions.validators import ActionRejected, ValidationContext, validate_decision
from kimi.ai.mock import decision
from kimi.ai.prompts import decision_schema
from kimi.config import SettingsStore
from kimi.memory.database import Database
from kimi.safety import ALLOWED_ACTIONS, SafetyViolation, check_url, safe_child_path
from kimi.world.locations import LocationGraph


@pytest.fixture
def ctx():
    return ValidationContext(graph=LocationGraph(), current_location="nest", unread_notes={7: "shrine"},
                             creation_ids={3}, research_allowed=True, sharing_enabled=False)


def test_required_actions_exist_and_schema_matches_allow_list():
    for name in ("move_to", "eat", "sleep", "rest", "explore", "read_note", "research", "write_diary",
                 "create_art", "reflect", "observe", "visit_location"):
        assert name in ALLOWED_ACTIONS
    schema = decision_schema()
    assert schema["properties"]["action"]["enum"] == list(ALLOWED_ACTIONS)
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("raw,action,location", [
    (decision("move_to", destination="cafe"), "move_to", None),
    (decision("visit_location", destination="library", duration_minutes=500), "visit_location", "library"),
    (decision("eat", food="Honey Crumpet", destination="cafe"), "eat", "cafe"),
    (decision("sleep"), "sleep", "nest"),
    (decision("rest", duration_minutes=5), "rest", None),
    (decision("explore", topic="mushrooms"), "explore", "shrub"),
    (decision("observe"), "observe", None),
    (decision("read_note", note_id=7, content="Thank you!"), "read_note", "shrine"),
    (decision("research", topic="Lighthouses of the world"), "research", "library"),
    (decision("write_diary", title="Today", content="A long enough diary entry about my day."), "write_diary", None),
    (decision("create_art", art_kind="drawing", title="Moss", drawing_elements=["kimi", "tree"]), "create_art", "print_shop"),
    (decision("reflect", content="Rain makes the moss smell new."), "reflect", None),
    (decision("leave_message", content="Hello visitors!"), "leave_message", "shrine"),
    (decision("continue"), "continue", None),
])
def test_valid_actions(ctx, raw, action, location):
    va = validate_decision(raw, ctx)
    assert va.action == action and va.required_location == location


def test_parameters_are_clamped_and_cleaned(ctx):
    va = validate_decision(decision("visit_location", destination="library", duration_minutes=500), ctx)
    assert va.params["duration_minutes"] == 120
    va = validate_decision(decision("research", topic="owls; rm -rf / <script>"), ctx)
    assert ";" not in va.params["topic"] and "<" not in va.params["topic"]
    va = validate_decision(decision("eat", food="a whole cow", destination="cafe"), ctx)
    assert va.params["food"] == "seed cake"  # not on the menu -> something that is


@pytest.mark.parametrize("name", ["run_shell", "exec_python", "send_email", "purchase", "install_package",
                                  "delete_file", "transfer_crypto", "publish_post", "dance", "", None])
def test_forbidden_and_unknown_actions_rejected(ctx, name):
    with pytest.raises(ActionRejected):
        validate_decision({"action": name}, ctx)


@pytest.mark.parametrize("raw,reason", [
    (decision("move_to", destination="the moon"), "destination"),
    (decision("write_diary", content="hi"), "diary"),
    (decision("create_art", art_kind="poem", title="x", content=""), "poem"),
    (decision("read_note", note_id=99), "not an unread note"),
    (decision("share_creation", creation_id=3), "disabled"),
    (decision("research", topic=""), "topic"),
])
def test_invalid_parameters_rejected(ctx, raw, reason):
    ctx.unread_notes = {7: "shrine", 8: "cafe"}
    with pytest.raises(ActionRejected) as exc:
        validate_decision(raw, ctx)
    assert reason in exc.value.reason


def test_research_quota_and_night_rules(ctx):
    ctx.research_allowed, ctx.research_block_reason = False, "enough research for today"
    with pytest.raises(ActionRejected, match="enough research"):
        validate_decision(decision("research", topic="owls"), ctx)
    ctx.is_night = True
    ctx.current_location = "square"
    va = validate_decision(decision("eat", food="seed cake", destination="cafe"), ctx)
    assert va.required_location == "nest"  # the cafe is closed at night


def test_extra_fields_are_ignored_never_executed(ctx):
    raw = decision("rest")
    raw["shell"] = "format c:"
    raw["python"] = "import os"
    va = validate_decision(raw, ctx)
    assert va.action == "rest" and "shell" not in json.dumps(va.params)


def test_handler_inserts_journey_before_remote_actions(make_runtime):
    rt = make_runtime()
    va = validate_decision(decision("research", topic="owls"), rt.cognition.validation_context())
    steps = rt.handler.build_plan(va, "mind")
    assert [s.action for s in steps] == ["move_to", "research"]
    assert steps[0].params == {"destination": "library"}


def test_drawings_are_safe_svg(tmp_path):
    svg = render_drawing('A <script>alert(1)</script> "title"', ["kimi", "moon", "stars", "unknown"], "caption & more", 1)
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    assert "<script" not in svg and "&lt;script&gt;" in svg


def test_creations_saved_inside_creations_folder(tmp_path):
    db = Database(tmp_path / "c.db")
    studio = CreativeStudio(db, tmp_path / "creations", lambda lid: "The Print Shop")
    story = studio.create(kind="story", title="../../../evil", content="Once upon a time there was a moss.",
                          elements=[], sim_minute=600, location="print_shop")
    drawing = studio.create(kind="drawing", title="Moss", content="Moss at dawn", elements=["kimi", "sun"],
                            sim_minute=700, location="print_shop")
    for c in (story, drawing):
        path = studio.path_of(c)
        assert path.exists() and (tmp_path / "creations").resolve() in path.parents
    assert "Once upon a time" in studio.path_of(story).read_text(encoding="utf-8")
    assert studio.path_of(drawing).suffix == ".svg"
    with pytest.raises(SafetyViolation):
        safe_child_path(tmp_path / "creations", "..", "outside.txt")
    db.close()


def test_url_safety():
    check_url("https://en.wikipedia.org/w/api.php")
    for bad in ("http://en.wikipedia.org/x", "https://evil.example.com/", "https://user:pw@en.wikipedia.org/",
                "file:///etc/passwd"):
        with pytest.raises(SafetyViolation):
            check_url(bad)


def test_github_remote_validation():
    assert valid_github_remote("https://github.com/someone/kimi-creations")
    assert valid_github_remote("git@github.com:someone/kimi-creations.git")
    assert not valid_github_remote("https://evil.example.com/repo")
    assert not valid_github_remote("https://github.com/someone/repo; rm -rf /")


class FakeResponse:
    def __init__(self, data, url, status=200, ctype="application/json", raw=None):
        self.status_code = status
        self.url = url
        self.headers = {"Content-Type": ctype}
        self._raw = raw if raw is not None else json.dumps(data).encode()

    def iter_content(self, chunk_size):
        for i in range(0, len(self._raw), chunk_size):
            yield self._raw[i:i + chunk_size]

    def close(self):
        pass


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def get(self, url, params=None, timeout=None, stream=None, headers=None):
        self.requests.append((url, params, headers))
        for prefix, response in self.routes:
            if url.startswith(prefix):
                return response(url) if callable(response) else response
        raise AssertionError(f"unexpected url {url}")


@pytest.fixture
def settings(tmp_path):
    db = Database(tmp_path / "r.db")
    yield SettingsStore(db)
    db.close()


def test_research_uses_public_api_politely(settings):
    search = FakeResponse({"query": {"search": [{"title": "Owl (disambiguation)"}, {"title": "Owl"}]}},
                          "https://en.wikipedia.org/w/api.php")
    session = FakeSession([
        ("https://en.wikipedia.org/w/api.php", search),
        ("https://en.wikipedia.org/api/rest_v1/page/summary/Owl_(disambiguation)",
         FakeResponse({"type": "disambiguation"}, "https://en.wikipedia.org/api/rest_v1/page/summary/Owl_(disambiguation)")),
        ("https://en.wikipedia.org/api/rest_v1/page/summary/Owl",
         FakeResponse({"type": "standard", "title": "Owl", "extract": "Owls are birds from the order Strigiformes, "
                       "which includes over 200 species of mostly solitary and nocturnal birds of prey.",
                       "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Owl"}}},
                      "https://en.wikipedia.org/api/rest_v1/page/summary/Owl")),
    ])
    r = WikipediaResearcher(settings, session=session, min_interval_s=0)
    findings = r.investigate("owls")
    assert findings.title == "Owl" and "Strigiformes" in findings.extract
    assert all("KimiAutonomousBird" in h["User-Agent"] for _, _, h in session.requests)


def test_research_refuses_untrusted_redirects_and_bad_content(settings):
    redirect = FakeResponse({"query": {"search": []}}, "https://evil.example.com/steal")
    r = WikipediaResearcher(settings, session=FakeSession([("https://en.wikipedia.org", redirect)]), min_interval_s=0)
    with pytest.raises(ResearchUnavailable):
        r.investigate("owls")
    html = FakeResponse(None, "https://en.wikipedia.org/w/api.php", ctype="text/html", raw=b"<html>")
    r = WikipediaResearcher(settings, session=FakeSession([("https://en.wikipedia.org", html)]), min_interval_s=0)
    with pytest.raises(ResearchUnavailable):
        r.investigate("owls")
    huge = FakeResponse(None, "https://en.wikipedia.org/w/api.php", raw=b"{" + b" " * 400_000 + b"}")
    r = WikipediaResearcher(settings, session=FakeSession([("https://en.wikipedia.org", huge)]), min_interval_s=0)
    with pytest.raises(ResearchUnavailable):
        r.investigate("owls")


def test_rate_limit_triggers_cooldown(settings):
    from kimi.actions.research import RateLimited

    limited = FakeResponse(None, "https://en.wikipedia.org/x", status=429, ctype="text/plain", raw=b"slow down")
    session = FakeSession([("https://en.wikipedia.org", limited)])
    r = WikipediaResearcher(settings, session=session, min_interval_s=0)
    with pytest.raises(RateLimited):
        r.investigate("owls")
    assert r.cooldown_remaining() > 60
    calls = len(session.requests)
    with pytest.raises(RateLimited):
        r.investigate("owls")
    assert len(session.requests) == calls  # no further requests during the cooldown


def test_runtime_respects_research_cooldown(make_runtime):
    class Cooling:
        def cooldown_remaining(self):
            return 600.0

        def investigate(self, topic):
            raise AssertionError("must not be called")

    rt = make_runtime(researcher=Cooling())
    allowed, reason = rt.research_status()
    assert not allowed and "Library" in reason
