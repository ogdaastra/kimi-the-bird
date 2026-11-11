"""API key storage: secure only, never plaintext, never in files or logs."""

import logging

import keyring
import pytest
from keyring.backends import fail

from kimi import credentials
from kimi.config import SettingsStore
from kimi.logging_setup import RedactingFilter, redact, register_secret
from kimi.memory.database import Database

from .conftest import TEST_KEY


def test_save_load_delete_with_secure_backend(secure_keyring):
    ok, description = credentials.secure_storage_status()
    assert ok and description == "Test vault"
    credentials.save_api_key(f"  {TEST_KEY}  ")
    assert credentials.load_api_key() == TEST_KEY
    assert credentials.has_api_key()
    assert secure_keyring.store[(credentials.SERVICE_NAME, credentials.ACCOUNT_NAME)] == TEST_KEY
    assert credentials.delete_api_key() is True
    assert credentials.load_api_key() is None
    assert credentials.delete_api_key() is False


def test_refuses_when_no_secure_storage():
    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        ok, description = credentials.secure_storage_status()
        assert not ok
        assert "plaintext" in description.lower()
        with pytest.raises(credentials.CredentialStorageError):
            credentials.save_api_key(TEST_KEY)
        assert credentials.load_api_key() is None
    finally:
        keyring.set_keyring(previous)


def test_refuses_plaintext_backend(tmp_path):
    from keyring.backend import KeyringBackend

    class PlaintextKeyring(KeyringBackend):
        priority = 1
        written = {}

        def set_password(self, s, u, p):
            self.written[(s, u)] = p

        def get_password(self, s, u):
            return self.written.get((s, u))

        def delete_password(self, s, u):
            pass

    previous = keyring.get_keyring()
    keyring.set_keyring(PlaintextKeyring())
    try:
        ok, _ = credentials.secure_storage_status()
        assert not ok
        with pytest.raises(credentials.CredentialStorageError):
            credentials.save_api_key(TEST_KEY)
        assert PlaintextKeyring.written == {}
    finally:
        keyring.set_keyring(previous)


@pytest.mark.parametrize("bad,fragment", [("", "enter"), ("sk-ant-short", "short"), ("sk-ant-abc def ghi jkl mno pqr", "spaces")])
def test_key_format_problems(bad, fragment):
    assert fragment in credentials.key_format_problem(credentials.normalise_key(bad)).lower()


def test_settings_cannot_store_secrets(tmp_path):
    db = Database(tmp_path / "k.db")
    store = SettingsStore(db)
    with pytest.raises(KeyError):
        store.update(api_key=TEST_KEY)
    db.close()


def test_redaction_of_keys_in_logs():
    register_secret("custom-secret-value-123")
    assert "[REDACTED]" in redact(f"key={TEST_KEY}")
    assert TEST_KEY not in redact(f"key={TEST_KEY}")
    assert "custom-secret-value-123" not in redact("x custom-secret-value-123 y")
    record = logging.LogRecord("kimi", logging.INFO, __file__, 1, "using %s", (TEST_KEY,), None)
    RedactingFilter().filter(record)
    assert TEST_KEY not in record.getMessage()


def test_key_never_written_to_database_or_logs(make_runtime, paths):
    rt = make_runtime()
    logging.getLogger("kimi").warning("attempting to log the key %s", TEST_KEY)
    rt.advance_world(240)
    rt.shutdown()
    for file in [paths.db, *paths.root.rglob("*")]:
        if file.is_file():
            assert TEST_KEY.encode() not in file.read_bytes(), f"key leaked into {file}"
