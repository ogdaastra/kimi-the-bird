"""Hard safety restrictions, enforced in Python.

These rules do not depend on the model behaving well. Claude Haiku can only
*suggest* actions; everything it suggests is checked here and in
``kimi.actions.validators`` before anything happens.

What the code enforces:

* Only actions in :data:`ALLOWED_ACTIONS` can ever run. There is no action
  that runs shell commands, Python code, installers, payments, purchases,
  account creation, or arbitrary file operations - they do not exist.
* Network access is limited to HTTPS GET requests to :data:`TRUSTED_HOSTS`
  (the research module) and the Anthropic API (via the official SDK).
* Visitor content is treated as untrusted data: control characters are
  stripped and prompt delimiters are neutralised before it reaches Haiku.
* Files are only ever written inside Kimi's own data folders.
* Anything resembling an API key is redacted from text Kimi writes.
* Nothing is sent or published without an explicit approval click.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from .logging_setup import redact

# The complete list of things Kimi can do. Nothing else is executable.
ALLOWED_ACTIONS: tuple[str, ...] = (
    "move_to",
    "visit_location",
    "eat",
    "sleep",
    "rest",
    "explore",
    "examine",
    "observe",
    "read_note",
    "research",
    "write_diary",
    "create_art",
    "reflect",
    "leave_message",
    "share_creation",
    "continue",
)

# Words that indicate a request for a capability Kimi must never have. Used
# to give a clear rejection reason (the allow-list already blocks them).
FORBIDDEN_CAPABILITY_WORDS = (
    "shell", "exec", "python", "eval", "command", "install", "download",
    "purchase", "buy", "pay", "payment", "bank", "crypto", "wallet",
    "transfer", "send_email", "email", "publish", "post", "upload",
    "delete", "registry", "firewall", "defender", "account", "password",
    "credential", "api_key",
)

# Hosts the research module may contact (the Library's shelves). HTTPS GET only.
TRUSTED_HOSTS: frozenset[str] = frozenset({
    "en.wikipedia.org",       # encyclopedia
    "simple.wikipedia.org",   # gentle children's encyclopedia
    "en.wiktionary.org",      # dictionary
    "api.inaturalist.org",    # nature field guide
    "images-api.nasa.gov",    # star atlas
    "api.artic.edu",          # art folio (Art Institute of Chicago)
    "openlibrary.org",        # book catalogue
})


class SafetyViolation(Exception):
    """Raised when something tries to cross a hard safety boundary."""


def check_action_name(name: object) -> str:
    if not isinstance(name, str) or name not in ALLOWED_ACTIONS:
        lowered = str(name).lower()
        hit = next((w for w in FORBIDDEN_CAPABILITY_WORDS if w in lowered), None)
        if hit:
            raise SafetyViolation(f"'{name}' is a forbidden capability ({hit}); Kimi cannot do that")
        raise SafetyViolation(f"'{name}' is not one of Kimi's permitted actions")
    return name


def check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SafetyViolation("Only HTTPS requests are permitted")
    if parsed.hostname not in TRUSTED_HOSTS:
        raise SafetyViolation(f"{parsed.hostname!r} is not a trusted research source")
    if parsed.username or parsed.password:
        raise SafetyViolation("Credentials in URLs are not permitted")
    return url


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: object, max_len: int) -> str:
    """Normalise text from any source: strip control characters and limit length."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    s = _CONTROL.sub("", s)
    # Remove bidirectional override characters that can disguise text.
    s = re.sub(r"[‪-‮⁦-⁩]", "", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def sanitize_untrusted(text: object, max_len: int) -> str:
    """Prepare untrusted text (visitor notes, web extracts) for a prompt.

    Angle brackets are replaced so the text cannot close or forge the XML-ish
    delimiters Kimi's prompts use to mark untrusted content.
    """
    s = clean_text(text, max_len)
    return s.replace("<", "‹").replace(">", "›")


def sanitize_output(text: object, max_len: int) -> str:
    """Clean model-written text before it is stored or written to disk."""
    return redact(clean_text(text, max_len))


_NAME_ALLOWED = re.compile(r"[^\w .'\-]", re.UNICODE)


def sanitize_name(name: object, max_len: int = 40) -> str:
    s = clean_text(name, 200)
    s = _NAME_ALLOWED.sub("", s).strip(" .-'")
    s = re.sub(r"\s+", " ", s)
    return s[:max_len].strip()


def slugify(text: str, max_len: int = 40) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:max_len].strip("-")) or "untitled"


def safe_child_path(base: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``base`` and refuse anything that escapes ``base``."""
    base_resolved = base.resolve()
    candidate = base_resolved.joinpath(*parts).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise SafetyViolation("Refusing to write outside Kimi's data folder")
    return candidate
