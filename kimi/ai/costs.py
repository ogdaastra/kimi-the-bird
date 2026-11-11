"""Token accounting, cost estimation and the daily budget guard.

Prices come from editable settings (defaults reflect Anthropic's published
Claude Haiku 5.5 rates when this was written) so they can be updated without
code changes. All costs shown in the app are estimates.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import Settings, SettingsStore


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cache_ttl: str = "5m"

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (Haiku 5.5's tokenizer is ~3.2 chars/token for English)."""
    return max(1, math.ceil(len(text or "") / 3.2))


def _rates(prompt_tokens: int, s: Settings) -> tuple[float, float]:
    long_ctx = prompt_tokens > s.long_context_threshold_tokens
    in_rate = (s.price_input_long_per_mtok if long_ctx else s.price_input_per_mtok) / 1e6
    out_rate = (s.price_output_long_per_mtok if long_ctx else s.price_output_per_mtok) / 1e6
    return in_rate, out_rate


def cost_of(usage: TokenUsage, s: Settings) -> float:
    in_rate, out_rate = _rates(usage.prompt_tokens, s)
    write_mult = s.cache_write_1h_multiplier if usage.cache_ttl == "1h" else s.cache_write_5m_multiplier
    return (
        usage.input_tokens * in_rate
        + usage.cache_read_tokens * in_rate * s.cache_read_multiplier
        + usage.cache_write_tokens * in_rate * write_mult
        + usage.output_tokens * out_rate
    )


def worst_case_cost(est_input_tokens: int, max_tokens: int, s: Settings, cache_ttl: str = "5m") -> float:
    """Upper bound for a request: every input token written to cache, full max_tokens out."""
    in_rate, out_rate = _rates(est_input_tokens, s)
    write_mult = s.cache_write_1h_multiplier if cache_ttl == "1h" else s.cache_write_5m_multiplier
    return est_input_tokens * in_rate * max(1.0, write_mult) + max_tokens * out_rate


def local_day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts if ts is not None else time.time()))


def next_local_midnight(ts: float) -> float:
    dt = datetime.fromtimestamp(ts)
    midnight = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


class BudgetExceeded(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UsageLedger:
    """Records every API request and enforces daily limits."""

    def __init__(self, db, settings: SettingsStore, wall=time.time) -> None:
        self.db = db
        self.settings = settings
        self.wall = wall

    def record(
        self,
        purpose: str,
        model: str,
        usage: TokenUsage | None,
        cost: float,
        success: bool,
        error_kind: str | None = None,
        latency_ms: int | None = None,
        request_id: str | None = None,
    ) -> None:
        u = usage or TokenUsage()
        now = self.wall()
        self.db.execute(
            "INSERT INTO api_usage(created_at, day, purpose, model, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, cost_usd, success, error_kind, latency_ms, request_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now, local_day(now), purpose, model, u.input_tokens, u.output_tokens,
                u.cache_read_tokens, u.cache_write_tokens, cost, 1 if success else 0,
                error_kind, latency_ms, request_id,
            ),
        )

    def spent_today(self) -> float:
        return float(self.db.scalar(
            "SELECT SUM(cost_usd) FROM api_usage WHERE day=?", (local_day(self.wall()),), 0.0
        ))

    def requests_today(self) -> int:
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM api_usage WHERE day=?", (local_day(self.wall()),), 0
        ))

    def check_budget(self, estimated_cost: float) -> None:
        s = self.settings.get()
        if self.requests_today() >= s.max_requests_per_day:
            raise BudgetExceeded(
                f"Daily request limit reached ({s.max_requests_per_day} requests)."
            )
        spent = self.spent_today()
        if spent + estimated_cost > s.daily_budget_usd:
            raise BudgetExceeded(
                f"Daily budget reached: ${spent:.4f} spent of ${s.daily_budget_usd:.2f}."
            )

    def today_stats(self) -> dict:
        row = self.db.query_one(
            "SELECT COUNT(*) AS requests, COALESCE(SUM(input_tokens),0) AS input, "
            "COALESCE(SUM(output_tokens),0) AS output, COALESCE(SUM(cache_read_tokens),0) AS cache_read, "
            "COALESCE(SUM(cache_write_tokens),0) AS cache_write, COALESCE(SUM(cost_usd),0) AS cost, "
            "COALESCE(SUM(success),0) AS ok FROM api_usage WHERE day=?",
            (local_day(self.wall()),),
        )
        return dict(row) if row else {}

    def daily_stats(self, days: int = 7) -> list[dict]:
        rows = self.db.query(
            "SELECT day, COUNT(*) AS requests, SUM(input_tokens) AS input, SUM(output_tokens) AS output, "
            "SUM(cache_read_tokens) AS cache_read, SUM(cost_usd) AS cost FROM api_usage "
            "GROUP BY day ORDER BY day DESC LIMIT ?",
            (days,),
        )
        return [dict(r) for r in rows]

    def totals(self) -> dict:
        row = self.db.query_one(
            "SELECT COUNT(*) AS requests, COALESCE(SUM(input_tokens),0) AS input, "
            "COALESCE(SUM(output_tokens),0) AS output, COALESCE(SUM(cost_usd),0) AS cost FROM api_usage"
        )
        return dict(row) if row else {}

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.db.query("SELECT * FROM api_usage ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]
