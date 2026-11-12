"""Smoke tests for the desktop interface (skipped where Qt cannot load)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="Qt is not loadable in this environment",
                                exc_type=ImportError)

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from kimi.ai.mock import make_response, mock_factory  # noqa: E402

from .helpers import Sequence, auth_error  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from kimi.ui import theme

    application = QApplication.instance() or QApplication([])
    theme.apply_theme(application, "light")
    return application


def _wait(app):
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(5):
        app.processEvents()


def test_setup_screen_elements(app, secure_keyring):
    from kimi.ui.setup_screen import SetupDialog

    dlg = SetupDialog(sdk_factory=mock_factory(Sequence(make_response("OK"))))
    assert dlg.key_edit.echoMode() == QLineEdit.EchoMode.Password
    assert dlg.key_edit.accessibleName() == "Enter your Anthropic API key"
    assert dlg.test_btn.text() == "Test API key"
    assert dlg.save_btn.text() == "Save and continue"
    assert "Not tested" in dlg.status_text.text()
    dlg.test_key()  # empty key
    assert "enter" in dlg.status_text.text().lower()


def test_setup_test_save_and_continue(app, secure_keyring):
    from kimi import credentials
    from kimi.ui.setup_screen import SetupDialog

    from .conftest import TEST_KEY

    dlg = SetupDialog(sdk_factory=mock_factory(Sequence(make_response("OK"))))
    dlg.key_edit.setText(TEST_KEY)
    dlg.save_and_continue()
    _wait(app)
    assert credentials.load_api_key() == TEST_KEY
    assert dlg.result() == SetupDialog.DialogCode.Accepted
    assert dlg.key_edit.text() == ""


def test_setup_invalid_key_not_saved(app, secure_keyring):
    from kimi import credentials
    from kimi.ui.setup_screen import SetupDialog

    from .conftest import TEST_KEY

    dlg = SetupDialog(sdk_factory=mock_factory(Sequence(auth_error())))
    dlg.key_edit.setText(TEST_KEY)
    dlg.save_and_continue()
    _wait(app)
    assert credentials.load_api_key() is None
    assert "Not connected" in dlg.status_text.text()


def test_main_window_pages_and_controls(app, make_runtime):
    from kimi.ui.window import PAGES, MainWindow

    rt = make_runtime()
    rt.advance_world(120)
    win = MainWindow(rt, mock=True)
    win.show()
    for i in range(len(PAGES)):
        win.nav.setCurrentRow(i)
        app.processEvents()
    win._refresh()
    assert win.status.text().endswith("Active")
    win.toggle_pause()
    assert rt.settings.get().paused and "Paused" in win.status.text()
    win.toggle_pause()
    win.emergency_stop()
    assert rt.status() == "stopped" and not win.stop_btn.isEnabled()
    win.close()


def test_kimi_asks_card_and_web_settings(app, make_runtime, secure_keyring):
    from kimi.ui.window import MainWindow

    rt = make_runtime()
    rid = rt.requests.create("artefact", "A little swing", "Could there be a swing by the pond?", 1, "nest")
    win = MainWindow(rt, mock=True)
    win.show()
    win._refresh()
    page = win.world_page
    assert not page.ask_card.isHidden() and page.ask_yes.text() == "Add to wishlist"
    assert "swing by the pond" in page.ask_body.text()
    page.ask_text.setPlainText("Yes please!")
    page.ask_yes.click()
    assert rt.requests.get(rid)["status"] == "wishlisted"
    assert "A little swing" in rt.paths.wishlist.read_text(encoding="utf-8")
    sp = win.settings_page
    sp.refresh()
    assert sp.web_status.text() == "Off." and not sp.open_web_btn.isEnabled()
    assert sp.passcode_btn.text() == "Set passcode…"
    assert sp.ask_human.isChecked() and sp.ask_limit.value() == 1
    win.close()
