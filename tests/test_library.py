"""The Library: trusted shelves by default, the wider-web speaking-tube only when every gate passes."""

from __future__ import annotations

import json

import pytest

from kimi.actions.research import LibraryResearcher
from kimi.actions.validators import ValidationContext, validate_decision
from kimi.ai.claude_client import AIError, ClaudeClient
from kimi.ai.costs import UsageLedger
from kimi.ai.decision_engine import WEB_SEARCH_BLOCKED, web_search_tool
from kimi.ai.mock import ScriptedHaiku, decision, make_response, make_web_search_response, mock_factory
from kimi.config import SettingsStore
from kimi.memory.database import Database
from kimi.world.locations import LocationGraph

from .conftest import TEST_KEY, FakeClock
from .test_actions import FakeResponse, FakeSession


@pytest.fixture
def settings(tmp_path):
    db = Database(tmp_path / "lib.db")
    yield SettingsStore(db)
    db.close()


def researcher(settings, routes):
    session = FakeSession(routes)
    return LibraryResearcher(settings, session=session, min_interval_s=0), session


# -- the shelves ------------------------------------------------------------------------------

def test_nature_guide_reads_inaturalist(settings):
    r, session = researcher(settings, [
        ("https://api.inaturalist.org/v1/taxa/48", FakeResponse({"results": [{
            "id": 48, "name": "Bryophyta", "preferred_common_name": "Mosses", "rank": "phylum",
            "iconic_taxon_name": "Plantae", "observations_count": 123456,
            "wikipedia_summary": "<b>Mosses</b> are small, non-vascular flowerless plants."}]},
            "https://api.inaturalist.org/v1/taxa/48")),
        ("https://api.inaturalist.org/v1/taxa", FakeResponse({"results": [{"id": 48, "name": "Bryophyta"}]},
                                                            "https://api.inaturalist.org/v1/taxa")),
    ])
    f = r.investigate("moss", "nature_guide")
    assert f.source == "nature_guide" and f.shelf_name == "the nature field guide"
    assert f.title == "Mosses" and "non-vascular" in f.extract and "<b>" not in f.extract
    assert f.url == "https://www.inaturalist.org/taxa/48"
    assert all(u.startswith("https://api.inaturalist.org/") for u, _, _ in session.requests)


def test_star_atlas_art_folio_books_and_dictionary(settings):
    nasa = {"collection": {"items": [{"data": [{
        "nasa_id": "PIA01234", "title": "Saturn's F Ring", "date_created": "2004-07-01T00:00:00Z",
        "description": "The narrow F ring of Saturn is braided and clumpy, shepherded by tiny moons on either side."}]}]}}
    art = {"data": [{"id": 46327, "title": "America Windows", "artist_display": "Marc Chagall French, born Belarus",
                     "date_display": "1977", "medium_display": "Stained glass",
                     "short_description": "Chagall's luminous blue windows celebrate the arts and freedom."}]}
    books = {"docs": [{"key": "/works/OL1W", "title": "The Secret Life of Moss", "author_name": ["A. Botanist"],
                       "first_publish_year": 2001, "subject": ["Mosses", "Botany"]}]}
    words = {"en": [{"partOfSpeech": "Noun", "definitions": [
        {"definition": "<span>A small, cup-shaped hollow</span> in the ground."}]}]}
    r, _ = researcher(settings, [
        ("https://images-api.nasa.gov/search", FakeResponse(nasa, "https://images-api.nasa.gov/search")),
        ("https://api.artic.edu/", FakeResponse(art, "https://api.artic.edu/api/v1/artworks/search")),
        ("https://openlibrary.org/search.json", FakeResponse(books, "https://openlibrary.org/search.json")),
        ("https://en.wiktionary.org/", FakeResponse(words, "https://en.wiktionary.org/api/rest_v1/page/definition/dell")),
    ])
    stars = r.investigate("Saturn rings", "star_atlas")
    assert stars.source == "star_atlas" and stars.url == "https://images.nasa.gov/details/PIA01234"
    assert stars.extract.startswith("(2004)")
    folio = r.investigate("stained glass", "art_folio")
    assert folio.source == "art_folio" and "Chagall" in folio.extract and folio.url.endswith("/46327")
    cat = r.investigate("moss", "book_catalogue")
    assert cat.source == "book_catalogue" and "Secret Life of Moss" in cat.extract
    dell = r.investigate("dell", "dictionary")
    assert dell.source == "dictionary" and "cup-shaped" in dell.extract and "<span>" not in dell.extract


def test_a_failed_shelf_falls_back_to_the_encyclopedia(settings):
    summary = {"type": "standard", "title": "Moss", "extract": "Mosses are small, non-vascular flowerless plants "
               "in the taxonomic division Bryophyta.", "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Moss"}}}
    r, session = researcher(settings, [
        ("https://api.inaturalist.org/", FakeResponse({"results": []}, "https://api.inaturalist.org/v1/taxa")),
        ("https://en.wikipedia.org/api/rest_v1/page/summary/Moss",
         FakeResponse(summary, "https://en.wikipedia.org/api/rest_v1/page/summary/Moss")),
    ])
    f = r.investigate("moss", "nature_guide")
    assert f.source == "encyclopedia" and f.title == "Moss"


def test_unknown_shelf_means_the_encyclopedia(settings):
    summary = {"type": "standard", "title": "Owl", "extract": "Owls are birds from the order Strigiformes, which "
               "includes over 200 species."}
    r, session = researcher(settings, [("https://en.wikipedia.org/", FakeResponse(summary, "https://en.wikipedia.org/x"))])
    assert r.investigate("owl", "the_whole_internet").source == "encyclopedia"
    assert all(u.startswith("https://en.wikipedia.org/") for u, _, _ in session.requests)


# -- validation: wider_world quietly becomes the encyclopedia unless allowed ------------------------

def _vctx(web_check=None):
    return ValidationContext(graph=LocationGraph(), current_location="nest", web_check=web_check)


def test_research_source_validation():
    va = validate_decision(decision("research", topic="Moss"), _vctx())
    assert va.params["source"] == "encyclopedia"
    va = validate_decision(decision("research", topic="Moss", research_source="nature_guide"), _vctx())
    assert va.params["source"] == "nature_guide"
    va = validate_decision(decision("research", topic="Moss", research_source="made_up"), _vctx())
    assert va.params["source"] == "encyclopedia"
    va = validate_decision(decision("research", topic="Moss", research_source="wider_world"), _vctx())
    assert va.params["source"] == "encyclopedia" and "switched off" in va.params["web_declined"]
    va = validate_decision(decision("research", topic="Moss", research_source="wider_world"),
                           _vctx(lambda topic: (False, "not now")))
    assert va.params["source"] == "encyclopedia" and va.params["web_declined"] == "not now"
    va = validate_decision(decision("research", topic="Moss", research_source="wider_world"),
                           _vctx(lambda topic: (True, "")))
    assert va.params["source"] == "wider_world"


# -- the gates -------------------------------------------------------------------------------------

def _prepare_for_web(rt, topic="Moss"):
    rt.db.execute("INSERT INTO research_log(created_at, day, topic, title, source_url, summary, takeaway, source) "
                  "VALUES(?,?,?,?,?,?,?,?)", (rt.wall() - 20 * 60, rt.today(), topic, topic,
                                              "https://en.wikipedia.org/wiki/Moss", "x", "Moss drinks through its leaves.",
                                              "encyclopedia"))
    for _ in range(4):
        rt.character.nudge_interest("mosses", 0.12, "research", 1)


def test_web_search_is_off_by_default(make_runtime):
    rt = make_runtime()
    assert rt.settings.get().web_search_enabled is False
    ok, why = rt.web_research_status("Moss")
    assert not ok and "switched off" in why


def test_every_web_gate_is_enforced(make_runtime):
    rt = make_runtime(web_search_enabled=True, daily_budget_usd=1.0)
    ok, why = rt.web_research_status("Volcanoes")
    assert not ok and "shelves first" in why
    rt.db.execute("INSERT INTO research_log(created_at, day, topic, title, source) VALUES(?,?,?,?,?)",
                  (rt.wall() - 3600, rt.today(), "Volcanoes", "Volcano", "encyclopedia"))
    ok, why = rt.web_research_status("Volcanoes")
    assert not ok and "strong interests" in why
    for _ in range(4):
        rt.character.nudge_interest("volcanoes", 0.12, "research", 1)
    assert rt.web_research_status("Volcanoes") == (True, "")
    assert rt.web_research_status("Lighthouses")[0] is False   # never read about on the shelves

    # At least three hours between uses.
    rt.db.execute("INSERT INTO research_log(created_at, day, topic, title, source) VALUES(?,?,?,?,?)",
                  (rt.wall() - 30 * 60, rt.today(), "Volcanoes", "web", "wider_world"))
    ok, why = rt.web_research_status("Volcanoes")
    assert not ok and "rest" in why
    rt.db.execute("UPDATE research_log SET created_at=? WHERE source='wider_world'", (rt.wall() - 4 * 3600,))
    assert rt.web_research_status("Volcanoes")[0] is True

    # Daily limit.
    rt.update_settings(web_search_daily_limit=1)
    ok, why = rt.web_research_status("Volcanoes")
    assert not ok and "enough today" in why
    rt.update_settings(web_search_daily_limit=2)

    # Never more than half the daily budget.
    rt.update_settings(daily_budget_usd=0.02)
    ok, why = rt.web_research_status("Volcanoes")
    assert not ok and "budget" in why

    # Library research itself must be allowed.
    rt.update_settings(daily_budget_usd=1.0, research_enabled=False)
    assert rt.web_research_status("Volcanoes")[0] is False


def test_daily_web_limit_is_capped_at_five(make_runtime):
    rt = make_runtime(web_search_daily_limit=50)
    assert rt.settings.get().web_search_daily_limit == 5


class WebResponder:
    """Chooses wider-web research once, then behaves like the scripted Haiku."""

    def __init__(self, source="wider_world"):
        self.source = source
        self.scripted = ScriptedHaiku()
        self.calls: list[dict] = []
        self.decided = False

    def __call__(self, kwargs):
        self.calls.append(kwargs)
        props = set((((kwargs.get("output_config") or {}).get("format") or {}).get("schema") or {}).get("properties", {}))
        if "action" in props and not self.decided:
            self.decided = True
            return make_response(json.dumps(decision("research", topic="Moss", research_source=self.source,
                                                     thought="I still wonder how moss survives the dry days.")))
        return self.scripted(kwargs)


def _run_until(rt, predicate, minutes=360):
    for _ in range(int(minutes / 10)):
        rt.advance_world(10, step=2.0)
        if predicate():
            return True
    return False


def test_speaking_tube_end_to_end(make_runtime):
    responder = WebResponder()
    rt = make_runtime(responder, web_search_enabled=True, daily_budget_usd=1.0)
    _prepare_for_web(rt)
    assert _run_until(rt, lambda: rt.web_searches_today() > 0)
    row = rt.db.query_one("SELECT * FROM research_log WHERE source='wider_world'")
    assert "moss" in row["takeaway"].lower()
    citations = json.loads(row["citations"])
    assert citations and citations[0]["url"].startswith("https://")
    web_calls = [c for c in responder.calls if c.get("tools")]
    assert len(web_calls) == 1
    tool = web_calls[0]["tools"][0]
    assert tool["type"] == "web_search_20250305" and tool["max_uses"] == 1
    assert set(WEB_SEARCH_BLOCKED) <= set(tool["blocked_domains"])
    assert "format" not in web_calls[0]["output_config"]   # plain text, no structured output
    assert rt.ledger.web_searches_today() == 1
    usage = rt.db.query_one("SELECT cost_usd FROM api_usage WHERE purpose='web_research'")
    assert usage["cost_usd"] >= 0.01   # $10 per 1,000 searches
    assert any("speaking-tube" in m.description for m in rt.stm.recent(30))
    # The same day, a second use is blocked by the three-hour gap.
    assert rt.web_research_status("Moss")[0] is False


def test_speaking_tube_request_downgrades_to_the_encyclopedia(make_runtime):
    responder = WebResponder()
    rt = make_runtime(responder)              # web search left off (the default)
    assert _run_until(rt, lambda: bool(rt.researcher.topics))
    assert rt.researcher.shelves[0] == "encyclopedia"
    assert not any(c.get("tools") for c in responder.calls)
    assert rt.ledger.web_searches_today() == 0


def test_chosen_shelf_is_used_and_recorded(make_runtime):
    rt = make_runtime(WebResponder(source="nature_guide"))
    assert _run_until(rt, lambda: rt.db.scalar("SELECT COUNT(*) FROM research_log WHERE title IS NOT NULL", (), 0) > 0)
    assert rt.researcher.shelves[0] == "nature_guide"
    assert rt.db.scalar("SELECT source FROM research_log WHERE title IS NOT NULL") == "nature_guide"
    assert any("nature field guide" in m.description for m in rt.stm.recent(30))


# -- the client ------------------------------------------------------------------------------------

@pytest.fixture
def client_env(tmp_path):
    db = Database(tmp_path / "c.db")
    settings = SettingsStore(db)
    settings.update(min_request_gap_s=0.5, daily_budget_usd=1.0)
    ledger = UsageLedger(db, settings)
    clock = FakeClock()

    def make(responder):
        return ClaudeClient(lambda: TEST_KEY, ledger, settings, mock_factory(responder),
                            sleep=lambda s: clock.advance(s), mono=clock)

    yield make, ledger, settings
    db.close()


def test_client_web_search_request_citations_and_cost(client_env):
    make, ledger, settings = client_env
    calls = []

    def responder(kwargs):
        calls.append(kwargs)
        return make_web_search_response("Moss can dry out and wake again.")

    result = make(responder).complete(purpose="web_research", system="sys", user_content="moss?",
                                      max_tokens=500, schema=None, web_search=web_search_tool(1))
    assert calls[0]["tools"] == [web_search_tool(1)]
    assert result.citations[0]["url"].startswith("https://www.nhm.ac.uk")
    assert result.usage.web_searches == 1
    assert result.cost_usd >= 0.01
    assert ledger.web_searches_today() == 1


def test_client_refuses_web_search_with_structured_output(client_env):
    make, _, _ = client_env
    with pytest.raises(AIError) as err:
        make(lambda kw: make_web_search_response("x")).complete(
            purpose="web_research", system="s", user_content="u", max_tokens=100,
            schema={"type": "object", "properties": {}, "additionalProperties": False}, web_search=web_search_tool(1))
    assert err.value.kind == "bad_request"


def test_budget_guard_counts_the_search_fee(client_env):
    make, _, settings = client_env
    settings.update(daily_budget_usd=0.005)    # a plain request fits; a $0.01 search does not
    client = make(lambda kw: make_response("ok", input_tokens=20, output_tokens=5))
    client.complete(purpose="test", system="s", user_content="u", max_tokens=50, schema=None)
    with pytest.raises(AIError) as err:
        client.complete(purpose="web_research", system="s", user_content="u", max_tokens=50, schema=None,
                        web_search=web_search_tool(1))
    assert err.value.kind == "budget"
