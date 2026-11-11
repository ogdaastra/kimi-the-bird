"""The Claude Haiku 5.5 client: auth, responses, retries, budgets, limits."""

import json

import pytest

from kimi import MODEL_ID
from kimi.ai.claude_client import (
    STATUS_BUDGET_PAUSED,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_INVALID_KEY,
    AIError,
    ClaudeClient,
    verify_api_key,
)
from kimi.ai.costs import TokenUsage, UsageLedger, cost_of
from kimi.ai.mock import make_response, mock_factory
from kimi.config import Settings, SettingsStore
from kimi.memory.database import Database

from .conftest import TEST_KEY, FakeClock
from .helpers import Sequence, auth_error, connection_error, overloaded, rate_limit

SCHEMA = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"],
          "additionalProperties": False}


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path / "k.db")
    settings = SettingsStore(db)
    settings.update(min_request_gap_s=0.5)
    ledger = UsageLedger(db, settings)
    sleeps: list[float] = []
    clock = FakeClock()

    def make(responder, key=TEST_KEY):
        return ClaudeClient(lambda: key, ledger, settings, mock_factory(responder),
                            sleep=lambda s: (sleeps.append(s), clock.advance(s)), mono=clock)

    yield make, ledger, settings, sleeps, clock
    db.close()


def ok_json(data=None, **kw):
    return make_response(json.dumps(data or {"action": "rest"}), **kw)


# -- API key test (setup screen) ---------------------------------------------------------

def test_verify_api_key_success_uses_haiku_minimally():
    responder = Sequence(make_response("OK", input_tokens=12, output_tokens=2))
    result = verify_api_key(TEST_KEY, sdk_factory=mock_factory(responder))
    assert result.ok and "Haiku 5.5" in result.message
    call = responder.calls[0]
    assert call["model"] == MODEL_ID == "claude-haiku-5-5"
    assert call["max_tokens"] <= 16
    assert call["thinking"] == {"type": "disabled"}


def test_verify_api_key_invalid_key():
    result = verify_api_key(TEST_KEY, sdk_factory=mock_factory(Sequence(auth_error())))
    assert not result.ok and result.kind == "auth"
    assert "rejected" in result.message
    assert TEST_KEY not in result.message


def test_verify_api_key_requires_input():
    result = verify_api_key("   ", sdk_factory=mock_factory(Sequence(make_response("OK"))))
    assert not result.ok and result.kind == "format"


def test_verify_api_key_rate_limited_means_authenticated():
    assert verify_api_key(TEST_KEY, sdk_factory=mock_factory(Sequence(rate_limit()))).ok


def test_verify_api_key_offline():
    result = verify_api_key(TEST_KEY, sdk_factory=mock_factory(Sequence(connection_error())))
    assert not result.ok and result.kind == "connection"


# -- Successful responses -------------------------------------------------------------------

def test_successful_structured_response_and_usage_tracking(env):
    make, ledger, settings, _, _ = env
    responder = Sequence(ok_json({"action": "explore"}, input_tokens=1000, output_tokens=200, cache_read=500))
    client = make(responder)
    result = client.complete(purpose="decision", system="sys", user_content="hello", max_tokens=500,
                             effort="low", schema=SCHEMA)
    assert result.data == {"action": "explore"}
    assert client.status == STATUS_CONNECTED
    req = responder.calls[0]
    assert req["model"] == "claude-haiku-5-5"
    assert req["system"][0]["cache_control"]["type"] == "ephemeral"
    assert req["output_config"]["format"]["schema"] == SCHEMA
    assert req["output_config"]["effort"] == "low"
    assert req["thinking"] == {"type": "adaptive"}
    assert "temperature" not in req
    stats = ledger.today_stats()
    assert stats["requests"] == 1 and stats["input"] == 1000 and stats["output"] == 200
    expected = cost_of(TokenUsage(1000, 200, 500, 0, client.cache_ttl()), settings.get())
    assert stats["cost"] == pytest.approx(expected)


def test_cost_estimate_uses_editable_pricing():
    s = Settings(price_input_per_mtok=0.10, price_output_per_mtok=0.50)
    assert cost_of(TokenUsage(100_000, 0), s) == pytest.approx(0.01)
    assert cost_of(TokenUsage(0, 1_000_000), s) == pytest.approx(0.50)
    assert cost_of(TokenUsage(0, 0, cache_read_tokens=100_000), s) == pytest.approx(0.001)  # 0.1x cache reads
    s2 = Settings(price_input_per_mtok=1.0, price_output_per_mtok=1.0)
    assert cost_of(TokenUsage(100_000, 0), s2) == pytest.approx(0.1)
    long_prompt = TokenUsage(150_000, 0)
    assert cost_of(long_prompt, s) == pytest.approx(150_000 * 0.50 / 1e6)  # long-context rate card


# -- Errors and retries -----------------------------------------------------------------------

def test_retries_temporary_failures_with_exponential_backoff(env):
    make, ledger, *_ = env
    sleeps = env[3]
    client = make(Sequence(overloaded(), connection_error(), ok_json()))
    result = client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert result.data == {"action": "rest"}
    backoffs = [s for s in sleeps if s > 1.0]
    assert len(backoffs) == 2 and backoffs[1] > backoffs[0]
    rows = ledger.recent(5)
    assert [r["success"] for r in reversed(rows)] == [0, 0, 1]


def test_rate_limit_retry_after_is_honoured(env):
    make, _, _, sleeps, _ = env
    client = make(Sequence(rate_limit("20"), ok_json()))
    client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert max(sleeps) >= 20


def test_invalid_key_stops_requests(env):
    make, *_ = env
    responder = Sequence(auth_error())
    client = make(responder)
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300)
    assert exc.value.kind == "auth"
    assert client.status == STATUS_INVALID_KEY
    with pytest.raises(AIError):
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300)
    assert len(responder.calls) == 1  # the bad key is not retried


def test_refusal_is_handled(env):
    make, *_ = env
    client = make(Sequence(make_response("", stop_reason="refusal")))
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert exc.value.kind == "refusal"


def test_truncated_json_is_rejected(env):
    make, *_ = env
    client = make(Sequence(make_response('{"action": "res', stop_reason="max_tokens")))
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert exc.value.kind == "invalid_response"


def test_disconnects_then_reconnects_after_cooldown(env):
    make, _, settings, _, clock = env
    settings.update(max_retries=1)
    responder = Sequence(connection_error(), connection_error(), ok_json())
    client = make(responder)
    with pytest.raises(AIError):
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert client.status == STATUS_DISCONNECTED
    assert client.availability()[0] is False
    clock.advance(31)
    assert client.availability()[0] is True
    assert client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA).data
    assert client.status == STATUS_CONNECTED


# -- Cost controls --------------------------------------------------------------------------

def test_daily_budget_blocks_requests(env):
    make, ledger, settings, _, _ = env
    responder = Sequence(ok_json(input_tokens=200_000, output_tokens=10_000))
    client = make(responder)
    settings.update(daily_budget_usd=0.01, max_input_tokens=6000)
    client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert ledger.spent_today() > 0.01
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert exc.value.kind == "budget"
    assert client.status == STATUS_BUDGET_PAUSED
    assert len(responder.calls) == 1
    settings.update(daily_budget_usd=5.0)
    client.clear_budget_pause()
    client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert len(responder.calls) == 2


def test_worst_case_estimate_prevents_overspend(env):
    make, ledger, settings, _, _ = env
    settings.update(daily_budget_usd=0.0)
    responder = Sequence(ok_json())
    client = make(responder)
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert exc.value.kind == "budget" and responder.calls == []


def test_max_requests_per_day(env):
    make, _, settings, _, _ = env
    settings.update(max_requests_per_day=2)
    responder = Sequence(ok_json())
    client = make(responder)
    for _ in range(2):
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300, schema=SCHEMA)
    assert exc.value.kind == "budget"


def test_request_size_limit(env):
    make, _, settings, _, _ = env
    settings.update(max_input_tokens=1000)
    responder = Sequence(ok_json())
    client = make(responder)
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="x" * 20_000, max_tokens=300)
    assert exc.value.kind == "too_large" and responder.calls == []


def test_response_size_is_capped(env):
    make, *_ = env
    responder = Sequence(ok_json())
    make(responder).complete(purpose="decision", system="s", user_content="u", max_tokens=999_999, schema=SCHEMA)
    assert responder.calls[0]["max_tokens"] <= 8000


def test_halt_blocks_everything(env):
    make, *_ = env
    responder = Sequence(ok_json())
    client = make(responder)
    client.halt()
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300)
    assert exc.value.kind == "stopped" and responder.calls == []


def test_no_key_no_requests(env):
    make, *_ = env
    responder = Sequence(ok_json())
    client = make(responder, key=None)
    assert client.availability() == (False, "No API key configured.")
    with pytest.raises(AIError) as exc:
        client.complete(purpose="decision", system="s", user_content="u", max_tokens=300)
    assert exc.value.kind == "not_configured" and responder.calls == []
