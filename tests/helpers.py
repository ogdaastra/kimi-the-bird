"""Helpers for building SDK errors and responses in tests."""

from __future__ import annotations

import anthropic
import httpx2

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def api_error(cls, status: int, message: str = "error", headers: dict | None = None):
    resp = httpx2.Response(status, request=REQUEST, headers=headers or {},
                           json={"type": "error", "error": {"type": "x", "message": message}})
    return cls(message, response=resp, body=None)


def auth_error():
    return api_error(anthropic.AuthenticationError, 401, "invalid x-api-key")


def rate_limit(retry_after: str | None = None):
    return api_error(anthropic.RateLimitError, 429, "rate limited",
                     {"retry-after": retry_after} if retry_after else None)


def overloaded():
    return api_error(anthropic.OverloadedError, 529, "overloaded")


def connection_error():
    return anthropic.APIConnectionError(request=REQUEST)


class Sequence:
    """A responder that returns/raises the given items in order, then repeats the last."""

    def __init__(self, *items) -> None:
        self.items = list(items)
        self.calls: list[dict] = []

    def __call__(self, kwargs):
        self.calls.append(kwargs)
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        return item
