"""Settings screen: API key, autonomy, cost controls, features, appearance and resets."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import MODEL_DISPLAY_NAME, MODEL_ID, credentials
from ..actions.sharing import valid_github_remote
from ..ai.claude_client import verify_api_key
from . import theme
from .widgets import Card, button, esc, label, run_async


def _form() -> tuple[QWidget, QFormLayout]:
    w = QWidget()
    f = QFormLayout(w)
    f.setContentsMargins(0, 0, 0, 0)
    f.setHorizontalSpacing(16)
    f.setVerticalSpacing(8)
    f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    return w, f


def _spin(lo: int, hi: int, suffix: str = "", step: int = 1) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    if suffix:
        s.setSuffix(suffix)
    s.setMaximumWidth(160)
    s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    s.setToolTip("Type a value, or use the arrow keys or mouse wheel")
    return s


def _dspin(lo: float, hi: float, decimals: int, step: float, prefix: str = "", suffix: str = "") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setPrefix(prefix)
    s.setSuffix(suffix)
    s.setMaximumWidth(160)
    s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    s.setToolTip("Type a value, or use the arrow keys or mouse wheel")
    return s


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    motion_changed = Signal(bool)
    world_view_changed = Signal(str)

    def __init__(self, runtime, parent: QWidget | None = None, *, mock: bool = False) -> None:
        super().__init__(parent)
        self.rt = runtime
        self.mock = mock
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("Page")
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 16, 16, 24)
        lay.setSpacing(14)
        lay.addWidget(label("Settings", heading=True, role="h1"))

        # --- API -----------------------------------------------------------
        api = Card("Anthropic API")
        self.api_status = label("")
        api.add(self.api_status)
        api.add(label(f"Model: <b>{MODEL_DISPLAY_NAME}</b> (<code>{MODEL_ID}</code>) - Kimi uses this model exclusively.",
                      role="body"))
        btns = QHBoxLayout()
        self.test_btn = button("Test connection", slot=self._test_connection)
        self.replace_btn = button("Replace key…", slot=self._replace_key)
        self.delete_btn = button("Delete key", slot=self._delete_key)
        for b in (self.test_btn, self.replace_btn, self.delete_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        h = QWidget()
        h.setLayout(btns)
        btns.setContentsMargins(0, 0, 0, 0)
        api.add(h)
        self.test_result = label("", role="caption", muted=True)
        api.add(self.test_result)
        lay.addWidget(api)

        # --- Autonomy ------------------------------------------------------------
        auto = Card("Autonomy")
        self.autonomous = QCheckBox("Autonomous mode - Kimi decides what to do by itself")
        self.autonomous.toggled.connect(self._toggle_autonomy)
        auto.add(self.autonomous)
        self.pause_btn = button("Pause", slot=self._toggle_pause)
        prow = QHBoxLayout()
        prow.addWidget(self.pause_btn)
        prow.addWidget(label("Freezes Kimi and its world. The red Emergency stop in the header stops all "
                             "autonomous activity and AI requests immediately.", role="caption", muted=True), 1)
        ph = QWidget()
        ph.setLayout(prow)
        prow.setContentsMargins(0, 0, 0, 0)
        auto.add(ph)
        w, f = _form()
        self.min_interval = _spin(1, 360, " min")
        self.max_interval = _spin(1, 1440, " min")
        self.time_scale = _dspin(0.5, 60, 1, 0.5, suffix=" × real time")
        self.decision_effort = QComboBox()
        self.reflection_effort = QComboBox()
        for c in (self.decision_effort, self.reflection_effort):
            c.addItems(["low", "medium", "high"])
            c.setMaximumWidth(160)
        f.addRow("Minimum time between AI decisions", self.min_interval)
        f.addRow("Longest quiet gap (adaptive idle)", self.max_interval)
        f.addRow("World speed", self.time_scale)
        f.addRow("Thinking effort for decisions", self.decision_effort)
        f.addRow("Thinking effort for nightly reflection", self.reflection_effort)
        auto.add(w)
        auto.add(label("Between AI decisions, movement, needs, weather and simple habits run locally for free. "
                       "When Kimi keeps choosing quiet activities and nothing happens, the gap between decisions "
                       "grows towards the longest quiet gap.", role="caption", muted=True))
        lay.addWidget(auto)

        # --- Cost ------------------------------------------------------------------
        cost = Card("Cost controls")
        self.usage = label("")
        cost.add(self.usage)
        w, f = _form()
        self.budget = _dspin(0.0, 100.0, 2, 0.05, prefix="$ ")
        self.max_requests = _spin(0, 5000, " requests")
        self.max_input = _spin(1000, 50000, " tokens", 500)
        self.decision_tokens = _spin(256, 8000, " tokens", 100)
        self.reflection_tokens = _spin(256, 8000, " tokens", 100)
        self.research_tokens = _spin(256, 8000, " tokens", 100)
        f.addRow("Daily spending limit", self.budget)
        f.addRow("Maximum requests per day", self.max_requests)
        f.addRow("Maximum request size", self.max_input)
        f.addRow("Maximum response (decisions)", self.decision_tokens)
        f.addRow("Maximum response (reflection)", self.reflection_tokens)
        f.addRow("Maximum response (research)", self.research_tokens)
        cost.add(w)
        cost.add(label("<b>Pricing used for estimates</b> (USD per million tokens - update these if Anthropic's "
                       "prices change):"))
        w, f = _form()
        self.price_in = _dspin(0, 1000, 3, 0.01, prefix="$ ")
        self.price_out = _dspin(0, 1000, 3, 0.01, prefix="$ ")
        self.cache_read = _dspin(0, 10, 2, 0.05, suffix=" × input")
        self.cache_write = _dspin(0, 10, 2, 0.05, suffix=" × input")
        f.addRow("Input tokens", self.price_in)
        f.addRow("Output tokens", self.price_out)
        f.addRow("Cache reads", self.cache_read)
        f.addRow("Cache writes (1 hour)", self.cache_write)
        cost.add(w)
        self.history = QTreeWidget()
        self.history.setHeaderLabels(["Day", "Requests", "Input tokens", "Output tokens", "Estimated cost"])
        self.history.setRootIsDecorated(False)
        self.history.setMaximumHeight(190)
        self.history.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history.setAccessibleName("Daily usage history")
        cost.add(self.history)
        cost.add(label("When the daily limit is reached, AI requests pause until midnight; the world and Kimi's "
                       "local instincts keep running. Every request is logged - there are no hidden calls.",
                       role="caption", muted=True))
        lay.addWidget(cost)

        # --- Features ------------------------------------------------------------------
        feat = Card("Features and permissions")
        self.research = QCheckBox("Library research: Kimi may look things up on trusted, free shelves when curious")
        feat.add(self.research)
        feat.add(label("Shelves: Wikipedia and Simple English Wikipedia, Wiktionary, iNaturalist (nature), NASA's "
                       "image library (stars), the Art Institute of Chicago (art) and Open Library (books). These are "
                       "free public APIs - no account, no key, no extra cost - visited politely and rarely.",
                       role="caption", muted=True))
        w, f = _form()
        self.research_limit = _spin(0, 50, " per day")
        self.research_contact = QLineEdit()
        self.research_contact.setPlaceholderText("optional, e.g. a website or email for the User-Agent")
        f.addRow("Research sessions", self.research_limit)
        f.addRow("Contact for User-Agent", self.research_contact)
        feat.add(w)
        self.web_search = QCheckBox("Let Kimi search the wider web now and then (Anthropic web search - costs extra)")
        self.web_search.setAccessibleDescription("Off by default. Gated by several conditions listed below.")
        feat.add(self.web_search)
        w, f = _form()
        self.web_limit = _spin(0, 5, " per day")
        self.web_price = _dspin(0, 1000, 2, 1.0, prefix="$ ", suffix=" per 1,000 searches")
        f.addRow("Wider-web searches", self.web_limit)
        f.addRow("Search price (estimate)", self.web_price)
        feat.add(w)
        feat.add(label("Kimi only uses the speaking-tube when <b>all</b> of these hold: this box is ticked; the "
                       "subject is one of Kimi's strong interests <i>and</i> Kimi has already read about it on the "
                       "trusted shelves; it hasn't used up today's searches; at least three hours have passed since "
                       "the last one; and today's spending plus the search's worst case stays under half the daily "
                       "limit. One search per session, never social media or forums. Each search costs about "
                       "$0.01, plus the result text it reads as input (a fraction of a cent with Haiku 5.5). Whatever "
                       "Kimi finds is treated as untrusted and the sources are kept in its memory.",
                       role="caption", muted=True))
        self.ask_human = QCheckBox("Let Kimi ask me for something now and then (a wish for its world, or a question)")
        feat.add(self.ask_human)
        w, f = _form()
        self.ask_limit = _spin(0, 2, " per day")
        f.addRow("Kimi's requests", self.ask_limit)
        feat.add(w)
        feat.add(label("Kimi's requests appear on the World screen (and on the web page). Wishes you agree to go on "
                       "<code>data\\wishlist.md</code>, to be built into Bramblewick later. Kimi can never ask for "
                       "money, accounts, passwords, files or personal details.", role="caption", muted=True))
        self.vision = QCheckBox("Look at pictures visitors leave (one small request per picture)")
        feat.add(self.vision)
        self.sharing = QCheckBox("Allow Kimi to ask to share creations (each share still needs your approval)")
        feat.add(self.sharing)
        w, f = _form()
        self.github = QLineEdit()
        self.github.setPlaceholderText("https://github.com/you/kimi-creations")
        f.addRow("GitHub repository (optional)", self.github)
        feat.add(w)
        feat.add(label("GitHub publishing uses Git's own credential manager; Kimi never sees your GitHub token. "
                       "Only creation files are ever published - never memories or visitor notes.",
                       role="caption", muted=True))
        lay.addWidget(feat)

        # --- Web page ---------------------------------------------------------------------
        web = Card("Web page")
        self.web_enabled = QCheckBox("Let me see Kimi in a web browser (served on this PC only)")
        web.add(self.web_enabled)
        w, f = _form()
        self.web_port = _spin(1024, 65535)
        f.addRow("Port", self.web_port)
        web.add(w)
        row = QHBoxLayout()
        self.passcode_btn = button("Set passcode…", slot=self.set_passcode)
        self.open_web_btn = button("Open in browser", slot=self.open_web)
        row.addWidget(self.passcode_btn)
        row.addWidget(self.open_web_btn)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        web.add(holder)
        self.web_status = label("")
        web.add(self.web_status)
        web.add(label(
            "The page shows Kimi on the map, its thoughts, needs, diary and curiosities, and lets you reply to its "
            "requests. It needs the passcode, which is kept in Windows Credential Manager.<br><br>"
            "<b>To see Kimi from anywhere, free:</b> install <b>Tailscale</b> (free personal plan) on this PC and on "
            "your phone and sign in to both with the same account. Then run this once in a terminal on this PC: "
            "<code>tailscale serve --bg --https=443 8765</code> (use your port if you changed it). Open the address "
            "it shows, like <code>https://your-pc.your-tailnet.ts.net</code>, on your phone. Only your own devices "
            "can reach it; it is never on the public internet. Full steps: <code>docs\\REMOTE_ACCESS.md</code>.",
            role="caption", muted=True))
        lay.addWidget(web)

        # --- Appearance ---------------------------------------------------------------
        look = Card("Appearance")
        w, f = _form()
        self.theme_box = QComboBox()
        self.theme_box.addItem("Match Windows", "system")
        self.theme_box.addItem("Daylight (light)", "light")
        self.theme_box.addItem("Lantern night (dark)", "dark")
        self.theme_box.setMaximumWidth(220)
        f.addRow("Theme", self.theme_box)
        self.world_view = QComboBox()
        self.world_view.addItem("3D world", "3d")
        self.world_view.addItem("Illustrated map", "map")
        self.world_view.setMaximumWidth(220)
        f.addRow("World screen shows", self.world_view)
        self.quality = QComboBox()
        self.quality.addItem("High (shadows, smooth edges)", "high")
        self.quality.addItem("Low (faster on older computers)", "low")
        self.quality.setMaximumWidth(260)
        f.addRow("3D quality", self.quality)
        look.add(w)
        self.reduce_motion = QCheckBox("Reduce motion (no hopping, rain or twinkling)")
        look.add(self.reduce_motion)
        lay.addWidget(look)

        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        self.revert_btn = button("Revert", slot=self.load)
        self.apply_btn = button("Apply changes", role="primary", slot=self.apply)
        apply_row.addWidget(self.revert_btn)
        apply_row.addWidget(self.apply_btn)
        h = QWidget()
        h.setLayout(apply_row)
        apply_row.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(h)
        self.applied = label("", role="caption", muted=True)
        self.applied.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.applied)

        # --- Data & reset ----------------------------------------------------------------
        data = Card("Data and reset")
        data.add(label(f"Kimi's world is stored in: <code>{esc(str(self.rt.paths.root))}</code>", selectable=True))
        rbtns = QHBoxLayout()
        rbtns.addWidget(button("Open data folder", slot=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.rt.paths.root)))))
        rbtns.addWidget(button("Reset world…", tooltip="Return Kimi to its nest on a fresh morning; memories are kept",
                               slot=self._reset_world))
        rbtns.addWidget(button("Reset everything…", role="danger",
                               tooltip="Erase memories, diary, character and world", slot=self._reset_everything))
        rbtns.addStretch(1)
        h = QWidget()
        h.setLayout(rbtns)
        rbtns.setContentsMargins(0, 0, 0, 0)
        data.add(h)
        lay.addWidget(data)
        lay.addStretch(1)
        self.load()

    # -- load / apply -----------------------------------------------------
    def load(self) -> None:
        s = self.rt.settings.get()
        self.autonomous.blockSignals(True)
        self.autonomous.setChecked(s.autonomous_enabled and not s.emergency_stopped)
        self.autonomous.blockSignals(False)
        self.min_interval.setValue(max(1, round(s.decision_min_interval_s / 60)))
        self.max_interval.setValue(max(1, round(s.decision_max_interval_s / 60)))
        self.time_scale.setValue(s.time_scale)
        self.decision_effort.setCurrentText(s.decision_effort)
        self.reflection_effort.setCurrentText(s.reflection_effort)
        self.budget.setValue(s.daily_budget_usd)
        self.max_requests.setValue(s.max_requests_per_day)
        self.max_input.setValue(s.max_input_tokens)
        self.decision_tokens.setValue(s.decision_max_tokens)
        self.reflection_tokens.setValue(s.reflection_max_tokens)
        self.research_tokens.setValue(s.research_max_tokens)
        self.price_in.setValue(s.price_input_per_mtok)
        self.price_out.setValue(s.price_output_per_mtok)
        self.cache_read.setValue(s.cache_read_multiplier)
        self.cache_write.setValue(s.cache_write_1h_multiplier)
        self.research.setChecked(s.research_enabled)
        self.research_limit.setValue(s.research_daily_limit)
        self.research_contact.setText(s.research_contact)
        self.web_search.setChecked(s.web_search_enabled)
        self.web_limit.setValue(s.web_search_daily_limit)
        self.web_price.setValue(s.price_web_search_per_1k)
        self.vision.setChecked(s.vision_enabled)
        self.sharing.setChecked(s.external_sharing_enabled)
        self.ask_human.setChecked(s.ask_human_enabled)
        self.ask_limit.setValue(s.ask_human_daily_limit)
        self.web_enabled.setChecked(s.web_enabled)
        self.web_port.setValue(s.web_port)
        self.github.setText(s.github_remote_url)
        idx = self.theme_box.findData(s.ui_theme)
        self.theme_box.setCurrentIndex(max(0, idx))
        self.reduce_motion.setChecked(s.reduce_motion)
        self.world_view.setCurrentIndex(max(0, self.world_view.findData(s.world_view)))
        self.quality.setCurrentIndex(max(0, self.quality.findData(s.graphics_quality)))
        self.applied.setText("")
        self.refresh()

    def apply(self) -> None:
        github = self.github.text().strip()
        if github and not valid_github_remote(github):
            QMessageBox.warning(self, "Settings", "The GitHub repository URL should look like "
                                                  "https://github.com/owner/repository")
            return
        before = self.rt.settings.get()
        s = self.rt.update_settings(
            decision_min_interval_s=self.min_interval.value() * 60,
            decision_max_interval_s=max(self.max_interval.value(), self.min_interval.value()) * 60,
            time_scale=self.time_scale.value(),
            decision_effort=self.decision_effort.currentText(),
            reflection_effort=self.reflection_effort.currentText(),
            daily_budget_usd=self.budget.value(),
            max_requests_per_day=self.max_requests.value(),
            max_input_tokens=self.max_input.value(),
            decision_max_tokens=self.decision_tokens.value(),
            reflection_max_tokens=self.reflection_tokens.value(),
            research_max_tokens=self.research_tokens.value(),
            price_input_per_mtok=self.price_in.value(),
            price_output_per_mtok=self.price_out.value(),
            cache_read_multiplier=self.cache_read.value(),
            cache_write_1h_multiplier=self.cache_write.value(),
            research_enabled=self.research.isChecked(),
            research_daily_limit=self.research_limit.value(),
            research_contact=self.research_contact.text().strip(),
            web_search_enabled=self.web_search.isChecked(),
            web_search_daily_limit=self.web_limit.value(),
            price_web_search_per_1k=self.web_price.value(),
            vision_enabled=self.vision.isChecked(),
            external_sharing_enabled=self.sharing.isChecked(),
            ask_human_enabled=self.ask_human.isChecked(),
            ask_human_daily_limit=self.ask_limit.value(),
            web_enabled=self.web_enabled.isChecked(),
            web_port=self.web_port.value(),
            github_remote_url=github,
            ui_theme=self.theme_box.currentData(),
            reduce_motion=self.reduce_motion.isChecked(),
            world_view=self.world_view.currentData(),
            graphics_quality=self.quality.currentData(),
        )
        if s.world_view != before.world_view:
            self.world_view_changed.emit(s.world_view)
        if s.ui_theme != before.ui_theme:
            self.theme_changed.emit(s.ui_theme)
        if s.reduce_motion != before.reduce_motion:
            self.motion_changed.emit(s.reduce_motion)
        self.applied.setText("Settings saved ✓")

    # -- live info -----------------------------------------------------------
    # -- web page ------------------------------------------------------------------------
    def set_passcode(self) -> None:
        first, ok = QInputDialog.getText(self, "Web page passcode",
                                         "Choose a passcode for Kimi's web page (at least 8 characters):",
                                         QLineEdit.EchoMode.Password)
        if not ok:
            return
        problem = credentials.passcode_problem(first)
        if problem:
            QMessageBox.warning(self, "Web page passcode", problem)
            return
        again, ok = QInputDialog.getText(self, "Web page passcode", "Type it once more:", QLineEdit.EchoMode.Password)
        if not ok:
            return
        if again != first:
            QMessageBox.warning(self, "Web page passcode", "Those didn't match. Nothing was changed.")
            return
        try:
            credentials.save_web_passcode(first)
        except (credentials.CredentialStorageError, ValueError) as exc:
            QMessageBox.warning(self, "Web page passcode", str(exc))
            return
        if self.rt.web is not None:
            self.rt.web.refresh_passcode()
        self.applied.setText("Web page passcode saved securely ✓")
        self.refresh()

    def open_web(self) -> None:
        running, url, _ = self.rt.web_status()
        if running:
            QDesktopServices.openUrl(QUrl(url))

    def _refresh_web(self) -> None:
        t = theme.tokens()
        running, url, problem = self.rt.web_status()
        has_pass = credentials.load_web_passcode() is not None
        self.passcode_btn.setText("Change passcode…" if has_pass else "Set passcode…")
        self.open_web_btn.setEnabled(running)
        if running and has_pass:
            text = f"Running at <b>{esc(url)}</b> (this PC only)."
        elif running:
            text = f"Running at {esc(url)}, but <span style='color:{t.danger}'>no passcode is set yet</span>, so it stays locked."
        elif problem:
            text = f"<span style='color:{t.danger}'>Not running: {esc(problem)}</span>"
        else:
            text = "Off."
        self.web_status.setText(text)

    def refresh(self) -> None:
        rt = self.rt
        t = theme.tokens()
        self._refresh_web()
        ok, storage = credentials.secure_storage_status()
        if self.mock:
            key_line = "Running with the offline mock (<code>--mock-ai</code>): no API key is used and no requests are sent."
        elif not ok:
            key_line = f"<span style='color:{t.danger}'>Secure storage unavailable: {esc(storage)}</span>"
        else:
            key_line = (f"A key is stored securely in {esc(storage)}." if credentials.has_api_key()
                        else f"<span style='color:{t.danger}'>No API key stored.</span> Kimi lives on instinct until you add one.")
        status = rt.client.status.replace("_", " ")
        detail = rt.client.status_detail
        self.api_status.setText(f"<p>{key_line}</p><p>Connection: <b>{esc(status)}</b>"
                                f"{' - ' + esc(detail) if detail else ''}</p>")
        self.delete_btn.setEnabled(not self.mock and ok)
        self.replace_btn.setEnabled(not self.mock and ok)
        self.test_btn.setEnabled(not self.mock)
        s = rt.settings.get()
        self.pause_btn.setText("Resume" if s.paused else "Pause")
        today = rt.ledger.today_stats()
        totals = rt.ledger.totals()
        searches = int(today.get("web_searches") or 0)
        search_note = f" (including {searches} web search{'es' if searches != 1 else ''})" if searches else ""
        self.usage.setText(
            f"Today: <b>${(today.get('cost') or 0):.4f}</b> of ${s.daily_budget_usd:.2f} · "
            f"{today.get('requests', 0)} requests{search_note}. All time: ${(totals.get('cost') or 0):.4f} over "
            f"{totals.get('requests', 0)} requests. <i>Estimates - check the Anthropic Console for billing.</i>"
        )
        self.history.clear()
        for d in rt.ledger.daily_stats(7):
            self.history.addTopLevelItem(QTreeWidgetItem([
                d["day"], str(d["requests"]), f"{d['input'] or 0:,}", f"{d['output'] or 0:,}", f"${(d['cost'] or 0):.4f}",
            ]))

    # -- actions ------------------------------------------------------------------
    def _toggle_autonomy(self, on: bool) -> None:
        if on and self.rt.settings.get().emergency_stopped:
            if QMessageBox.question(self, "Resume autonomy",
                                    "Emergency stop is active. Turn autonomous mode back on?") != QMessageBox.StandardButton.Yes:
                self.autonomous.blockSignals(True)
                self.autonomous.setChecked(False)
                self.autonomous.blockSignals(False)
                return
        self.rt.set_autonomous(on)

    def _toggle_pause(self) -> None:
        if self.rt.settings.get().paused:
            self.rt.resume()
        else:
            self.rt.pause()
        self.refresh()

    def _test_connection(self) -> None:
        key = credentials.load_api_key()
        if not key:
            self.test_result.setText("No key stored.")
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText("Testing…")

        def done(result, error) -> None:
            self.test_btn.setEnabled(True)
            if error is not None:
                self.test_result.setText(f"Test failed unexpectedly ({type(error).__name__}).")
                return
            self.test_result.setText(("✓ " if result.ok else "✕ ") + result.message)
            if result.ok:
                self.rt.reload_api_key()
            self.refresh()

        run_async(lambda: verify_api_key(key, ledger=self.rt.ledger), done)

    def _replace_key(self) -> None:
        from .setup_screen import SetupDialog

        if SetupDialog(self, replacing=True).exec():
            self.rt.reload_api_key()
            self.test_result.setText("✓ New key saved.")
            self.refresh()

    def _delete_key(self) -> None:
        if QMessageBox.question(self, "Delete API key",
                                "Remove the API key from Windows Credential Manager? Kimi will keep living on "
                                "instinct, without AI decisions, until you add a key again.") != QMessageBox.StandardButton.Yes:
            return
        try:
            credentials.delete_api_key()
        except credentials.CredentialStorageError as exc:
            QMessageBox.warning(self, "Delete API key", str(exc))
            return
        self.rt.reload_api_key()
        self.test_result.setText("Key deleted.")
        self.refresh()

    def _reset_world(self) -> None:
        if QMessageBox.question(self, "Reset world", "Send Kimi back to its nest on a fresh morning? "
                                "Memories, diary and personality are kept.") == QMessageBox.StandardButton.Yes:
            self.rt.reset_world()

    def _reset_everything(self) -> None:
        text, ok = QInputDialog.getText(self, "Reset everything",
                                        "This erases Kimi's memories, diary, personality, visitors and world.\n"
                                        "Files in the creations and diary folders stay on disk.\n\n"
                                        "Type RESET to confirm:")
        if ok and text.strip() == "RESET":
            self.rt.reset_everything()
            QMessageBox.information(self, "Reset everything", "Kimi has been reset and hatches anew.")
