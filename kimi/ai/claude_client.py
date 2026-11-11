"""The only module that talks to the Anthropic API.

Responsibilities: sending requests to Claude Haiku 5.5 with the official
SDK, retrying temporary failures with exponential backoff, honouring rate
limits, tracking tokens and estimated cost, enforcing request-size and daily
budget limits, and refusing to make any request when it should not.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, NamedTuple

from .. import MODEL_DISPLAY_NAME, MODEL_ID
from ..config import SettingsStore
from .costs import BudgetExceeded, TokenUsage, UsageLedger, cost_of, estimate_tokens, next_local_midnight, worst_case_cost

log = logging.getLogger("kimi.ai")

STATUS_NOT_CONFIGURED = "not_configured"
STATUS_READY = "ready"            # key present, not yet used this session
STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"
STATUS_INVALID_KEY = "invalid_key"
STATUS_BUDGET_PAUSED = "budget_paused"
STATUS_HALTED = "halted"


class AIError(Exception):
    def __init__(self, kind: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = retryable


@dataclass
class AIResult:
    text: str
    data: dict | None
    usage: TokenUsage
    cost_usd: float
    stop_reason: str | None
    request_id: str | None = None
    latency_ms: int = 0
    citations: list = field(default_factory=list)


class KeyTestResult(NamedTuple):
    ok: bool
    message: str
    kind: str


SDKFactory = Callable[..., Any]


def default_sdk_factory(api_key: str, max_retries: int = 0, timeout: float = 60.0):
    import anthropic

    # Retries are handled by ClaudeClient so every attempt is visible to the
    # budget guard and the usage log.
    return anthropic.Anthropic(api_key=api_key, max_retries=max_retries, timeout=timeout)


def _classify(exc: Exception) -> AIError:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return AIError("auth", "The API key was rejected (authentication failed).")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AIError("permission", "The API key does not have permission to use Claude Haiku 5.5.")
    if isinstance(exc, anthropic.NotFoundError):
        return AIError("not_found", f"The model {MODEL_ID} was not found for this account.")
    if isinstance(exc, anthropic.RateLimitError):
        return AIError("rate_limit", "Anthropic is rate limiting requests right now.", retryable=True)
    if isinstance(exc, anthropic.BadRequestError):
        msg = getattr(exc, "message", str(exc))
        return AIError("bad_request", f"The request was refused: {msg}")
    if isinstance(exc, anthropic.APITimeoutError):
        return AIError("timeout", "The request to Anthropic timed out.", retryable=True)
    if isinstance(exc, anthropic.APIConnectionError):
        return AIError("connection", "Could not reach Anthropic. Check your internet connection.", retryable=True)
    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", 0) or 0
        if status == 529:
            return AIError("overloaded", "Anthropic's service is temporarily overloaded.", retryable=True)
        if status >= 500:
            return AIError("server", f"Anthropic's service had a temporary problem ({status}).", retryable=True)
        return AIError("api_error", f"Anthropic returned an error ({status}): {getattr(exc, 'message', '')}")
    return AIError("unknown", f"Unexpected error: {type(exc).__name__}")


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _usage_from(response: Any, cache_ttl: str) -> TokenUsage:
    u = getattr(response, "usage", None)

    def g(name: str) -> int:
        try:
            return int(getattr(u, name, 0) or 0)
        except (TypeError, ValueError):
            return 0

    server = getattr(u, "server_tool_use", None)
    try:
        searches = int(getattr(server, "web_search_requests", 0) or 0)
    except (TypeError, ValueError):
        searches = 0
    return TokenUsage(
        input_tokens=g("input_tokens"),
        output_tokens=g("output_tokens"),
        cache_read_tokens=g("cache_read_input_tokens"),
        cache_write_tokens=g("cache_creation_input_tokens"),
        cache_ttl=cache_ttl,
        web_searches=searches,
    )


def _citations_of(response: Any) -> list[dict]:
    """Web-search citations attached to text blocks (url, title, cited text)."""
    seen: dict[str, dict] = {}
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) != "text":
            continue
        for c in getattr(block, "citations", None) or []:
            url = str(getattr(c, "url", "") or "")
            if url.startswith("https://") and url not in seen:
                seen[url] = {"url": url[:300], "title": str(getattr(c, "title", "") or "")[:160],
                             "cited_text": str(getattr(c, "cited_text", "") or "")[:200]}
    return list(seen.values())[:6]


def _text_of(response: Any) -> str:
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def verify_api_key(api_key: str, sdk_factory: SDKFactory | None = None, ledger: UsageLedger | None = None) -> KeyTestResult:
    """Send one minimal request to check that ``api_key`` works with Haiku 5.5."""
    from ..credentials import key_format_problem, normalise_key

    key = normalise_key(api_key)
    problem = key_format_problem(key)
    if problem:
        return KeyTestResult(False, problem, "format")
    factory = sdk_factory or default_sdk_factory
    started = time.monotonic()
    try:
        client = factory(api_key=key, max_retries=1, timeout=30.0)
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=8,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the word OK."}],
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a readable message
        err = _classify(exc)
        if ledger is not None:
            ledger.record("key_test", MODEL_ID, None, 0.0, False, err.kind)
        if err.kind == "rate_limit":
            # A 429 is only returned after authentication succeeds.
            return KeyTestResult(True, "Key accepted. Anthropic is rate limiting right now, so Kimi will pace itself.", "ok")
        hints = {
            "auth": " Check that you copied the whole key from the Anthropic Console.",
            "connection": " Kimi needs internet access to reach api.anthropic.com.",
            "timeout": " Try again in a moment.",
            "server": " Try again in a moment.",
            "overloaded": " Try again in a moment.",
        }
        return KeyTestResult(False, err.message + hints.get(err.kind, ""), err.kind)
    usage = _usage_from(response, "5m")
    if ledger is not None:
        cost = cost_of(usage, ledger.settings.get())
        ledger.record("key_test", MODEL_ID, usage, cost, True, latency_ms=int((time.monotonic() - started) * 1000),
                      request_id=getattr(response, "_request_id", None))
    return KeyTestResult(True, f"Connected. Your key works with {MODEL_DISPLAY_NAME}.", "ok")


class ClaudeClient:
    def __init__(
        self,
        key_provider: Callable[[], str | None],
        ledger: UsageLedger,
        settings: SettingsStore,
        sdk_factory: SDKFactory | None = None,
        sleep: Callable[[float], None] | None = None,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        self._key_provider = key_provider
        self.ledger = ledger
        self.settings = settings
        self._factory = sdk_factory or default_sdk_factory
        self._sleep = sleep
        self._wall = wall
        self._mono = mono
        self._lock = threading.RLock()
        self._halted = threading.Event()
        self._sdk = None
        self._sdk_key_hash: str | None = None
        self._bad_key_hash: str | None = None
        self._status = STATUS_NOT_CONFIGURED
        self._status_detail = ""
        self._last_request_at = -1e9
        self._failure_streak = 0
        self._cooldown_until = 0.0
        self._budget_paused_until = 0.0
        self.last_error: AIError | None = None
        self._refresh_key_status()

    # -- status -----------------------------------------------------------
    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def _refresh_key_status(self) -> str | None:
        key = self._key_provider()
        with self._lock:
            if not key:
                self._status = STATUS_NOT_CONFIGURED
                self._status_detail = "No API key configured."
                self._sdk = None
                self._sdk_key_hash = None
            elif self._status == STATUS_NOT_CONFIGURED:
                self._status = STATUS_READY
                self._status_detail = ""
        return key

    @property
    def status(self) -> str:
        with self._lock:
            if self._halted.is_set():
                return STATUS_HALTED
            if self._status == STATUS_BUDGET_PAUSED and self._wall() >= self._budget_paused_until:
                self._status = STATUS_READY
            if self._status == STATUS_DISCONNECTED and self._mono() >= self._cooldown_until:
                # Cooldown over; the next request will try to reconnect.
                pass
            return self._status

    @property
    def status_detail(self) -> str:
        with self._lock:
            return self._status_detail

    def reload_key(self) -> None:
        """Call after the key is saved, replaced or deleted."""
        with self._lock:
            self._sdk = None
            self._sdk_key_hash = None
            self._bad_key_hash = None
            self._failure_streak = 0
            self._cooldown_until = 0.0
            self._status = STATUS_NOT_CONFIGURED
        self._refresh_key_status()

    def clear_budget_pause(self) -> None:
        with self._lock:
            self._budget_paused_until = 0.0
            if self._status == STATUS_BUDGET_PAUSED:
                self._status = STATUS_READY

    def halt(self) -> None:
        """Emergency stop: abort retries and refuse all further requests."""
        self._halted.set()

    def resume(self) -> None:
        self._halted.clear()

    def availability(self) -> tuple[bool, str]:
        """Cheap check (no network) of whether a request could be attempted now."""
        if self._halted.is_set():
            return False, "AI requests are stopped."
        status = self.status
        if status == STATUS_NOT_CONFIGURED:
            return False, "No API key configured."
        if status == STATUS_INVALID_KEY:
            return False, "The stored API key was rejected. Replace it in Settings."
        if status == STATUS_BUDGET_PAUSED:
            return False, "Daily budget reached; AI paused until midnight."
        with self._lock:
            if self._mono() < self._cooldown_until:
                return False, "Waiting before reconnecting to Anthropic."
        return True, ""

    # -- requests ---------------------------------------------------------
    def _wait(self, seconds: float) -> bool:
        """Sleep, returning True if an emergency stop happened meanwhile."""
        if seconds <= 0:
            return self._halted.is_set()
        if self._sleep is not None:
            self._sleep(seconds)
            return self._halted.is_set()
        return self._halted.wait(seconds)

    def _get_sdk(self, key: str):
        h = self._hash(key)
        with self._lock:
            if self._sdk is None or self._sdk_key_hash != h:
                self._sdk = self._factory(api_key=key, max_retries=0, timeout=60.0)
                self._sdk_key_hash = h
            return self._sdk

    def cache_ttl(self) -> str:
        s = self.settings.get()
        # With decisions minutes apart a 5-minute cache would usually expire
        # between calls; a 1-hour cache costs 2x to write but 0.1x to read.
        return "1h" if s.decision_min_interval_s >= 120 else "5m"

    def complete(
        self,
        *,
        purpose: str,
        system: str,
        user_content: str | list,
        max_tokens: int,
        effort: str = "low",
        schema: dict | None = None,
        thinking: str = "adaptive",
        web_search: dict | None = None,
    ) -> AIResult:
        """Send one request. ``web_search`` (opt-in callers only) adds Anthropic's
        server-side web search tool; its ``max_uses`` caps searches and is priced
        into the worst-case budget check."""
        if self._halted.is_set():
            raise AIError("stopped", "AI requests are stopped.")
        key = self._refresh_key_status()
        if not key:
            raise AIError("not_configured", "No API key configured.")
        key_hash = self._hash(key)
        s = self.settings.get()
        with self._lock:
            if self._bad_key_hash == key_hash:
                raise AIError("auth", "The stored API key was rejected. Replace it in Settings.")
            if self._mono() < self._cooldown_until:
                raise AIError("connection", "Waiting before reconnecting to Anthropic.", retryable=True)

        # Request size guard.
        user_text = user_content if isinstance(user_content, str) else json.dumps(
            [b for b in user_content if isinstance(b, dict) and b.get("type") == "text"]
        )
        est_input = estimate_tokens(system) + estimate_tokens(user_text)
        if not isinstance(user_content, str):
            est_input += 1600 * sum(1 for b in user_content if isinstance(b, dict) and b.get("type") == "image")
        if est_input > s.max_input_tokens:
            raise AIError("too_large", f"Request too large (~{est_input} tokens, limit {s.max_input_tokens}).")
        max_tokens = max(16, min(int(max_tokens), 8000))

        # Budget guard (worst case: full max_tokens output).
        ttl = self.cache_ttl()
        max_searches = int(web_search.get("max_uses", 1)) if web_search else 0
        try:
            self.ledger.check_budget(worst_case_cost(est_input, max_tokens, s, ttl, max_searches=max_searches,
                                                     search_tokens=25_000 * max_searches))
        except BudgetExceeded as exc:
            with self._lock:
                self._status = STATUS_BUDGET_PAUSED
                self._status_detail = exc.reason
                self._budget_paused_until = next_local_midnight(self._wall())
            raise AIError("budget", exc.reason) from None
        if self._status == STATUS_BUDGET_PAUSED:
            self.clear_budget_pause()

        cache_control: dict[str, Any] = {"type": "ephemeral"}
        if ttl == "1h":
            cache_control["ttl"] = "1h"
        output_config: dict[str, Any] = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        request = {
            "model": MODEL_ID,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": cache_control}],
            "messages": [{"role": "user", "content": user_content}],
            "output_config": output_config,
            "thinking": {"type": "adaptive"} if thinking == "adaptive" else {"type": "disabled"},
        }
        if web_search:
            if schema is not None:
                raise AIError("bad_request", "Web search requests return plain text, not structured JSON.")
            request["tools"] = [dict(web_search)]

        attempts = max(1, s.max_retries + 1)
        last_err: AIError | None = None
        for attempt in range(attempts):
            # Hard floor between requests, whatever the caller does.
            gap = s.min_request_gap_s - (self._mono() - self._last_request_at)
            if gap > 0 and self._wait(gap):
                raise AIError("stopped", "AI requests are stopped.")
            if self._halted.is_set():
                raise AIError("stopped", "AI requests are stopped.")
            self._last_request_at = self._mono()
            started = self._mono()
            try:
                response = self._get_sdk(key).messages.create(**request)
            except Exception as exc:  # noqa: BLE001
                err = _classify(exc)
                last_err = err
                self.ledger.record(purpose, MODEL_ID, None, 0.0, False, err.kind,
                                   int((self._mono() - started) * 1000))
                log.warning("API %s failed (attempt %d/%d): %s", purpose, attempt + 1, attempts, err.message)
                if err.kind == "auth":
                    with self._lock:
                        self._bad_key_hash = key_hash
                        self._status = STATUS_INVALID_KEY
                        self._status_detail = err.message
                    self.last_error = err
                    raise err from None
                if not err.retryable or attempt == attempts - 1:
                    break
                delay = min(60.0, 2.0 * (2 ** attempt)) + random.uniform(0, 1.0)
                hinted = _retry_after(exc)
                if hinted is not None:
                    delay = max(delay, min(hinted, 300.0))
                if self._wait(delay):
                    raise AIError("stopped", "AI requests are stopped.") from None
                continue

            latency = int((self._mono() - started) * 1000)
            usage = _usage_from(response, ttl)
            cost = cost_of(usage, self.settings.get())
            stop_reason = getattr(response, "stop_reason", None)
            request_id = getattr(response, "_request_id", None)
            self.ledger.record(purpose, MODEL_ID, usage, cost, stop_reason != "refusal",
                               "refusal" if stop_reason == "refusal" else None, latency, request_id)
            with self._lock:
                self._status = STATUS_CONNECTED
                self._status_detail = ""
                self._failure_streak = 0
                self._cooldown_until = 0.0
            if stop_reason == "refusal":
                err = AIError("refusal", "Claude declined this request.")
                self.last_error = err
                raise err
            text = _text_of(response)
            citations = _citations_of(response) if web_search else []
            data = None
            if schema is not None:
                try:
                    data = json.loads(text)
                    if not isinstance(data, dict):
                        raise ValueError("not an object")
                except ValueError:
                    reason = "cut off at max_tokens" if stop_reason == "max_tokens" else "not valid JSON"
                    err = AIError("invalid_response", f"Haiku's response was {reason}.")
                    self.last_error = err
                    raise err from None
            self.last_error = None
            return AIResult(text=text, data=data, usage=usage, cost_usd=cost,
                            stop_reason=stop_reason, request_id=request_id, latency_ms=latency,
                            citations=citations)

        assert last_err is not None
        if last_err.retryable:
            with self._lock:
                self._failure_streak += 1
                cooldown = min(1800.0, 30.0 * (2 ** (self._failure_streak - 1)))
                self._cooldown_until = self._mono() + cooldown
                self._status = STATUS_DISCONNECTED
                self._status_detail = f"{last_err.message} Retrying in {int(cooldown)}s."
        self.last_error = last_err
        raise last_err
