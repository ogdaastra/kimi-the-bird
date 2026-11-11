"""Logging with defence-in-depth secret redaction.

Kimi never logs its API key on purpose. As an extra safeguard every log
record passes through :class:`RedactingFilter`, which removes anything that
looks like an Anthropic key and any secret registered at runtime.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import threading
from pathlib import Path

_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}")
_registered: set[str] = set()
_reg_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Make sure ``value`` is redacted from all future log output."""
    if value and len(value) >= 8:
        with _reg_lock:
            _registered.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    text = _KEY_PATTERN.sub("[REDACTED]", text)
    with _reg_lock:
        secrets = list(_registered)
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, "[REDACTED]")
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            message = str(record.msg)
        record.msg = redact(message)
        record.args = ()
        if record.exc_info and record.exc_info[1] is not None:
            # Render the traceback now so it can be redacted too.
            formatter = logging.Formatter()
            record.exc_text = redact(formatter.formatException(record.exc_info))
            record.exc_info = None
        return True


_configured = False


def configure_logging(log_dir: Path | None, level: int = logging.INFO, console: bool = False) -> None:
    global _configured
    root = logging.getLogger("kimi")
    root.setLevel(level)
    if _configured:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redactor = RedactingFilter()
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "kimi.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        fh.addFilter(redactor)
        root.addHandler(fh)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch.addFilter(redactor)
        root.addHandler(ch)
    # The SDK's own loggers can include request details; keep them quiet and redacted.
    for name in ("anthropic", "httpx", "httpx2"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.addFilter(redactor)
    _configured = True
