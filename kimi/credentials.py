"""Secure storage of the Anthropic API key.

The key is stored with the ``keyring`` library, which on Windows uses the
Windows Credential Manager. The key is never written to SQLite, JSON,
logs, source code or configuration files. If no secure credential store is
available this module refuses to store the key rather than silently falling
back to plaintext.
"""

from __future__ import annotations

import logging

from .logging_setup import register_secret

log = logging.getLogger("kimi.credentials")

SERVICE_NAME = "Kimi-the-Bird"
ACCOUNT_NAME = "anthropic-api-key"

# Backends that store secrets in an OS-protected vault.
_SECURE_BACKENDS = {
    "keyring.backends.Windows.WinVaultKeyring": "Windows Credential Manager",
    "keyring.backends.macOS.Keyring": "macOS Keychain",
    "keyring.backends.SecretService.Keyring": "Secret Service (GNOME Keyring)",
    "keyring.backends.kwallet.DBusKeyring": "KWallet",
    "keyring.backends.libsecret.Keyring": "libsecret",
}
# Tests may register an in-memory backend here; never used in production.
_TRUSTED_EXTRA: dict[str, str] = {}

_INSECURE_MARKERS = ("fail", "null", "plaintext", "file", "encrypted", "uncrypted")


class CredentialStorageError(Exception):
    """Secure credential storage is unavailable or failed."""


def _qualname(obj: object) -> str:
    cls = type(obj)
    return f"{cls.__module__}.{cls.__name__}"


def trust_backend_for_tests(backend_cls: type, label: str = "Test vault") -> None:
    _TRUSTED_EXTRA[f"{backend_cls.__module__}.{backend_cls.__name__}"] = label


def secure_storage_status() -> tuple[bool, str]:
    """Return ``(available, description)`` for the active credential store."""
    try:
        import keyring
    except Exception as exc:  # pragma: no cover - dependency missing
        return False, f"The keyring library is not installed ({exc})."
    kr = keyring.get_keyring()
    candidates = list(getattr(kr, "backends", None) or [kr])
    secure_labels = []
    for backend in candidates:
        name = _qualname(backend)
        if name in _SECURE_BACKENDS or name in _TRUSTED_EXTRA:
            secure_labels.append(_SECURE_BACKENDS.get(name) or _TRUSTED_EXTRA[name])
        elif any(marker in name.lower() for marker in _INSECURE_MARKERS):
            return False, (
                f"The only available credential store ({name}) is not secure. "
                "Kimi will not store your API key in plaintext."
            )
    if secure_labels:
        return True, secure_labels[0]
    return False, (
        "No secure credential store was found. On Windows, Kimi uses Windows "
        "Credential Manager; make sure you are running Kimi as a normal desktop "
        "user. Kimi will not store your API key in plaintext."
    )


def _require_secure() -> None:
    ok, description = secure_storage_status()
    if not ok:
        raise CredentialStorageError(description)


def normalise_key(raw: str) -> str:
    return (raw or "").strip()


def key_format_problem(key: str) -> str | None:
    """Return a human-readable problem with the key's shape, or ``None``."""
    if not key:
        return "Please enter your Anthropic API key."
    if any(ch.isspace() for ch in key):
        return "The key contains spaces or line breaks. Paste just the key."
    if len(key) < 20:
        return "That key looks too short. Copy the whole key from the Anthropic Console."
    return None


def save_api_key(key: str) -> None:
    key = normalise_key(key)
    problem = key_format_problem(key)
    if problem:
        raise ValueError(problem)
    _require_secure()
    import keyring
    from keyring.errors import KeyringError

    try:
        keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, key)
    except KeyringError as exc:
        raise CredentialStorageError(f"Could not save the key securely: {exc}") from None
    register_secret(key)
    log.info("API key saved to secure credential storage")


def load_api_key() -> str | None:
    ok, _ = secure_storage_status()
    if not ok:
        return None
    import keyring
    from keyring.errors import KeyringError

    try:
        key = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
    except KeyringError as exc:
        log.warning("Could not read credential store: %s", exc)
        return None
    if key:
        register_secret(key)
    return key or None


def has_api_key() -> bool:
    return load_api_key() is not None


def delete_api_key() -> bool:
    _require_secure()
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError

    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
    except PasswordDeleteError:
        return False
    except KeyringError as exc:
        raise CredentialStorageError(f"Could not delete the key: {exc}") from None
    log.info("API key deleted from secure credential storage")
    return True
