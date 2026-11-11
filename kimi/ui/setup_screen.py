"""First-launch setup: enter, test and securely save the Anthropic API key."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, MODEL_DISPLAY_NAME, MODEL_ID, credentials
from ..ai.claude_client import verify_api_key
from . import theme
from .widgets import Card, button, kimi_icon, kimi_pixmap, label, run_async

STATES = {
    "idle": ("info", "○", "Not tested yet"),
    "testing": ("warning", "◔", "Testing your key with Claude Haiku 5.5…"),
    "ok": ("success", "✓", "Connected"),
    "error": ("danger", "✕", "Not connected"),
}


class SetupDialog(QDialog):
    """Shown on first launch (and from Settings to replace the key)."""

    def __init__(self, parent: QWidget | None = None, *, replacing: bool = False, sdk_factory=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - Setup")
        self.setWindowIcon(kimi_icon())
        self.setModal(True)
        self.setMinimumWidth(560)
        self._sdk_factory = sdk_factory
        self._verified_key: str | None = None
        self._busy = False
        self._pending_save = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        top = QHBoxLayout()
        portrait = QLabel()
        portrait.setPixmap(kimi_pixmap(84, theme.tokens().surface_alt))
        portrait.setAccessibleName("Kimi, a small blue bird")
        top.addWidget(portrait, 0, Qt.AlignmentFlag.AlignTop)
        heading = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setFont(theme.heading_font("display"))
        title.setAccessibleName("Application title: Kimi")
        heading.addWidget(title)
        intro = label(
            f"Kimi is a small autonomous bird who lives in a little town on your computer. "
            f"Kimi thinks with <b>{MODEL_DISPLAY_NAME}</b> ({MODEL_ID}) from Anthropic, using your own API key. "
            "Your key is stored in Windows Credential Manager - never in files - and you can set a daily "
            "spending limit in Settings.",
            muted=False,
        )
        intro.setTextFormat(Qt.TextFormat.RichText)
        heading.addWidget(intro)
        top.addLayout(heading, 1)
        outer.addLayout(top)

        card = Card()
        key_label = QLabel("Enter your Anthropic API key")
        key_label.setFont(theme.font("body", weight=QFont.Weight.DemiBold))
        card.add(key_label)
        field_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-ant-…")
        self.key_edit.setAccessibleName("Enter your Anthropic API key")
        self.key_edit.setClearButtonEnabled(True)
        self.key_edit.textChanged.connect(self._key_changed)
        key_label.setBuddy(self.key_edit)
        field_row.addWidget(self.key_edit, 1)
        self.reveal = QToolButton()
        self.reveal.setText("Show")
        self.reveal.setCheckable(True)
        self.reveal.setToolTip("Temporarily show the characters you typed")
        self.reveal.setAccessibleName("Show key characters")
        self.reveal.toggled.connect(self._toggle_reveal)
        field_row.addWidget(self.reveal)
        wrap = QWidget()
        wrap.setLayout(field_row)
        field_row.setContentsMargins(0, 0, 0, 0)
        card.add(wrap)
        get_key = label('Don\'t have a key? Create one at <a href="https://console.anthropic.com/settings/keys">'
                        "console.anthropic.com</a>.", role="caption", muted=True)
        get_key.setOpenExternalLinks(True)
        get_key.setTextFormat(Qt.TextFormat.RichText)
        card.add(get_key)

        status_row = QHBoxLayout()
        self.status_icon = QLabel()
        self.status_icon.setFixedWidth(24)
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_text = label("", wrap=True)
        self.status_text.setAccessibleName("Connection status")
        status_row.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        status_row.addWidget(self.status_text, 1)
        status_wrap = QWidget()
        status_wrap.setLayout(status_row)
        status_row.setContentsMargins(0, 4, 0, 0)
        card.add(status_wrap)
        outer.addWidget(card)

        ok, description = credentials.secure_storage_status()
        self.storage_ok = ok
        storage = label(
            (f"Secure storage: {description}." if ok else f"Secure storage unavailable: {description}"),
            role="caption", muted=ok,
        )
        if not ok:
            storage.setStyleSheet(f"color: {theme.tokens().danger};")
        outer.addWidget(storage)

        buttons = QHBoxLayout()
        self.cancel_btn = button("Cancel" if replacing else "Quit", slot=self.reject)
        self.test_btn = button("Test API key", tooltip="Send one tiny request to check the key", slot=self.test_key)
        self.save_btn = button("Save and continue", role="primary",
                               tooltip="Test the key if needed, then store it in Windows Credential Manager",
                               slot=self.save_and_continue)
        self.save_btn.setDefault(True)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.test_btn)
        buttons.addWidget(self.save_btn)
        outer.addLayout(buttons)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.reject)

        self._set_state("idle")
        if not ok:
            self._set_state("error", "Kimi can't store your key securely on this computer, so it won't save it. "
                                     + description)
            self.save_btn.setEnabled(False)
        self.key_edit.setFocus()

    # -- state ------------------------------------------------------------
    def _set_state(self, state: str, message: str | None = None) -> None:
        t = theme.tokens()
        role, glyph, default = STATES[state]
        color = getattr(t, role)
        self.status_icon.setText(glyph)
        self.status_icon.setStyleSheet(f"color: {color}; font-size: 15pt; font-weight: 700;")
        if message is None:
            prefix = default
        elif state == "error":
            prefix = f"{default}: {message}"
        else:
            prefix = message
        self.status_text.setText(prefix)
        self.status_text.setStyleSheet(f"color: {color if state in ('error',) else t.ink};")
        self.status_text.setAccessibleDescription(prefix)

    def _toggle_reveal(self, shown: bool) -> None:
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        self.reveal.setText("Hide" if shown else "Show")

    def _key_changed(self) -> None:
        self._verified_key = None
        if not self._busy:
            self._set_state("idle")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.test_btn.setEnabled(not busy)
        self.save_btn.setEnabled(not busy and self.storage_ok)
        self.key_edit.setEnabled(not busy)

    # -- actions ------------------------------------------------------------
    def test_key(self) -> None:
        key = credentials.normalise_key(self.key_edit.text())
        problem = credentials.key_format_problem(key)
        if problem:
            self._set_state("error", problem)
            return
        self._set_busy(True)
        self._set_state("testing")
        factory = self._sdk_factory
        run_async(lambda: verify_api_key(key, sdk_factory=factory), lambda r, e: self._tested(key, r, e))

    def _tested(self, key: str, result, error: Exception | None) -> None:
        self._set_busy(False)
        if error is not None or result is None:
            self._set_state("error", f"Unexpected problem while testing ({type(error).__name__}).")
            self._pending_save = False
            return
        if result.ok:
            self._verified_key = key
            self._set_state("ok", result.message)
            if self._pending_save:
                self._pending_save = False
                self._store(key)
        else:
            self._pending_save = False
            self._set_state("error", result.message)

    def save_and_continue(self) -> None:
        if not self.storage_ok:
            return
        key = credentials.normalise_key(self.key_edit.text())
        if self._verified_key and self._verified_key == key:
            self._store(key)
        else:
            self._pending_save = True
            self.test_key()

    def _store(self, key: str) -> None:
        try:
            credentials.save_api_key(key)
        except (credentials.CredentialStorageError, ValueError) as exc:
            QMessageBox.critical(self, APP_NAME, f"Your key could not be saved securely.\n\n{exc}")
            return
        self.key_edit.clear()
        self.accept()
