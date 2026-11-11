"""Starts the desktop application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .. import APP_NAME, credentials
from ..config import Paths, SettingsStore
from ..memory.database import Database
from . import theme
from .widgets import kimi_icon

MOCK_KEY = "offline-mock-key-not-a-real-key"


def _initial_theme(paths: Paths) -> str:
    try:
        db = Database(paths.db)
        mode = SettingsStore(db).get().ui_theme
        db.close()
        return mode
    except Exception:  # noqa: BLE001
        return "system"


def run_gui(paths: Paths, mock: bool = False) -> int:
    from ..ai.mock import mock_factory
    from ..runtime import KimiRuntime
    from .setup_screen import SetupDialog
    from .window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(kimi_icon())
    theme.apply_theme(app, _initial_theme(paths))

    if not mock:
        ok, description = credentials.secure_storage_status()
        if not ok:
            QMessageBox.critical(
                None, APP_NAME,
                "Kimi needs Windows Credential Manager to store your Anthropic API key securely, but no secure "
                f"credential store is available.\n\n{description}\n\nKimi will not store the key in plaintext.",
            )
            return 2
        if not credentials.has_api_key():
            if SetupDialog().exec() != SetupDialog.DialogCode.Accepted:
                return 0

    runtime = KimiRuntime(
        paths,
        sdk_factory=mock_factory() if mock else None,
        key_provider=(lambda: MOCK_KEY) if mock else None,
    )
    runtime.start()
    window = MainWindow(runtime, mock=mock)
    window.show()
    app.commitDataRequest.connect(lambda *_: runtime.save())  # Windows log-off / shutdown
    try:
        return app.exec()
    finally:
        runtime.shutdown()
