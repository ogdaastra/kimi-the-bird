"""Main window: header with status and controls, sidebar navigation, pages."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, MODEL_DISPLAY_NAME
from ..world.environment import WEATHER_LABELS
from . import theme
from .activity_view import ActivityPage
from .character_view import CharacterPage
from .creations_view import CreationsPage
from .diary_view import DiaryPage
from .memory_view import MemoryPage
from .settings import SettingsPage
from .visitors_view import VisitorsPage
from .widgets import StatusPill, button, kimi_icon, kimi_pixmap, label
from .world_view import WorldPage

PAGES = ("World", "Kimi", "Memories", "Diary", "Creations", "Visitors", "Activity", "Settings")


log = logging.getLogger("kimi.ui")

class MainWindow(QMainWindow):
    def __init__(self, runtime, *, mock: bool = False) -> None:
        super().__init__()
        self.rt = runtime
        self.mock = mock
        self.setWindowTitle(f"{APP_NAME} - a little bird in Bramblewick" + (" (offline mock)" if mock else ""))
        self.setWindowIcon(kimi_icon())
        self.resize(1320, 860)
        self.setMinimumSize(1020, 680)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # Header
        header = QFrame()
        header.setObjectName("Header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(kimi_pixmap(44, theme.tokens().surface_alt))
        hl.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = label(APP_NAME, heading=True, role="h1", wrap=False)
        self.subtitle = label("", role="caption", muted=True, wrap=False)
        self.subtitle.setAccessibleName("World time and weather")
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        hl.addLayout(titles)
        hl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        hl.addStretch(1)
        self.status = StatusPill()
        hl.addWidget(self.status)
        self.spend = label("", role="caption", muted=True, wrap=False)
        self.spend.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.spend.setToolTip(f"Estimated {MODEL_DISPLAY_NAME} spend today versus your daily limit")
        hl.addWidget(self.spend)
        self.pause_btn = button("Pause", tooltip="Freeze Kimi and its world (Ctrl+P)", slot=self.toggle_pause)
        hl.addWidget(self.pause_btn)
        self.stop_btn = button("■  Emergency stop", role="danger",
                               tooltip="Immediately stop all autonomous activity and AI requests (Ctrl+Shift+X)",
                               slot=self.emergency_stop)
        hl.addWidget(self.stop_btn)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("Sidebar")
        self.nav.setFixedWidth(196)
        self.nav.setAccessibleName("Sections")
        for i, name in enumerate(PAGES):
            item = QListWidgetItem(name)
            item.setToolTip(f"{name} (Ctrl+{i + 1})")
            item.setSizeHint(QSize(0, 42))
            self.nav.addItem(item)
        body.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.world_page = WorldPage(self.rt, mode=self.rt.settings.get().world_view)
        self.world_page.dismiss_btn.clicked.connect(self.rt.dismiss_highlight)
        self.settings_page = SettingsPage(self.rt, mock=mock)
        self.settings_page.theme_changed.connect(self._apply_theme)
        self.settings_page.motion_changed.connect(self.world_page.canvas.set_reduce_motion)
        self.settings_page.world_view_changed.connect(self.world_page.set_mode)
        self.pages = [
            self.world_page,
            CharacterPage(self.rt),
            MemoryPage(self.rt),
            DiaryPage(self.rt),
            CreationsPage(self.rt),
            VisitorsPage(self.rt),
            ActivityPage(self.rt),
            self.settings_page,
        ]
        for page in self.pages:
            self.stack.addWidget(page)
        body.addWidget(self.stack, 1)
        holder = QWidget()
        holder.setLayout(body)
        root.addWidget(holder, 1)

        self.nav.currentRowChanged.connect(self._switch)
        self.nav.setCurrentRow(0)
        for i in range(len(PAGES)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.nav.setCurrentRow(i))
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.toggle_pause)
        QShortcut(QKeySequence("Ctrl+Shift+X"), self, activated=self.emergency_stop)

        self.world_page.canvas.set_reduce_motion(self.rt.settings.get().reduce_motion)
        self._ticks = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(1000)
        self._refresh()

    # -- navigation & refresh ---------------------------------------------------
    def _switch(self, row: int) -> None:
        self.stack.setCurrentIndex(row)
        page = self.pages[row]
        refresh = getattr(page, "refresh", None)
        if refresh:
            refresh()

    def _refresh(self) -> None:
        try:
            s = self.rt.snapshot()
        except Exception:  # noqa: BLE001 - e.g. the database closing during shutdown
            if not self.rt.closed and self._ticks % 60 == 0:
                log.exception("Couldn't read Kimi's state for the screen")
            self._ticks += 1
            return
        self._ticks += 1
        weather = WEATHER_LABELS.get(s["weather"], s["weather"])
        self.subtitle.setText(f"Day {s['day']} · {s['clock']} · {s['time_of_day']} · {weather}, {s['temperature']:.0f}°C"
                              f" · {s['place_name']}")
        detail = s.get("ai_detail") or ""
        self.status.set_status(s["status"], s["status_text"], detail)
        self.spend.setText(f"${s['spent_today']:.3f} / ${s['budget']:.2f} today")
        self.pause_btn.setText("Resume" if s["paused"] else "Pause")
        self.stop_btn.setEnabled(not s["emergency_stopped"])
        unread, pending = s["unread_notes"], s["pending_approvals"]
        self.nav.item(5).setText(f"Visitors  ({unread})" if unread else "Visitors")
        self.nav.item(6).setText(f"Activity  ({pending})" if pending else "Activity")
        self.world_page.update_from(s)
        current = self.stack.currentWidget()
        if current is not self.world_page and self._ticks % 3 == 0:
            refresh = getattr(current, "refresh", None)
            if refresh and current is not self.settings_page:
                refresh()
            elif current is self.settings_page and self._ticks % 6 == 0:
                self.settings_page.refresh()

    def _apply_theme(self, mode: str) -> None:
        theme.apply_theme(QApplication.instance(), mode)
        self.world_page.canvas._bg = None
        for page in self.pages:
            page.update()

    # -- controls -------------------------------------------------------------------
    def toggle_pause(self) -> None:
        if self.rt.settings.get().paused:
            self.rt.resume()
        else:
            self.rt.pause()
        self._refresh()

    def emergency_stop(self) -> None:
        self.rt.emergency_stop()
        self.settings_page.load()
        self._refresh()
        self.status.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.timer.stop()
        event.accept()
