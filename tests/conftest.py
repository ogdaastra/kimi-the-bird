"""Shared fixtures. Every test uses a mocked Haiku: no API credits are spent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import keyring  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402

from kimi import credentials  # noqa: E402
from kimi.actions.research import Findings, ResearchUnavailable  # noqa: E402
from kimi.ai.mock import ScriptedHaiku, mock_factory  # noqa: E402
from kimi.config import Paths  # noqa: E402

TEST_KEY = "sk-ant-api03-TESTKEY-abcdefghijklmnopqrstuvwxyz0123456789"


class MemoryKeyring(KeyringBackend):
    """In-memory stand-in for Windows Credential Manager."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        from keyring.errors import PasswordDeleteError

        if (service, username) not in self.store:
            raise PasswordDeleteError("missing")
        del self.store[(service, username)]


@pytest.fixture
def secure_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    credentials.trust_backend_for_tests(MemoryKeyring, "Test vault")
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def paths(tmp_path) -> Paths:
    return Paths(tmp_path / "data").ensure()


class FakeResearcher:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.topics: list[str] = []

    def investigate(self, topic: str) -> Findings:
        self.topics.append(topic)
        if self.fail:
            raise ResearchUnavailable("the books were all checked out")
        return Findings(topic=topic, title=topic.title(), url=f"https://en.wikipedia.org/wiki/{topic}",
                        extract=f"{topic.title()} is a fascinating subject with a long and interesting history.")


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def make_runtime(paths):
    from kimi.runtime import KimiRuntime

    created = []

    def factory(responder=None, *, key: str | None = TEST_KEY, researcher=None, path_override: Paths | None = None,
                **settings):
        responder = responder or ScriptedHaiku()
        rt = KimiRuntime(
            path_override or paths,
            key_provider=lambda: key,
            sdk_factory=mock_factory(responder),
            researcher=researcher or FakeResearcher(),
            seed=42,
            inline_jobs=True,
            client_sleep=lambda s: None,
        )
        defaults = {"decision_min_interval_s": 60, "decision_max_interval_s": 600, "min_request_gap_s": 0.5}
        defaults.update(settings)
        rt.update_settings(**defaults)
        rt.cognition.next_decision_at = 0
        rt.responder = responder
        created.append(rt)
        return rt

    yield factory
    for rt in created:
        try:
            rt.shutdown()
        except Exception:
            pass
