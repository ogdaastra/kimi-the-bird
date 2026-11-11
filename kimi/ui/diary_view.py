"""Diary screen: Kimi's entries in chronological order, shown as journal pages."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout, QWidget

from ..world.locations import LOCATIONS
from . import theme
from .widgets import button, esc, label


class DiaryPage(QWidget):
    def __init__(self, runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rt = runtime
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label("Kimi's diary", heading=True, role="h1"))
        top.addStretch(1)
        top.addWidget(button("Open diary folder", slot=self._open_folder,
                             tooltip="The diary is also saved as Markdown files"))
        lay.addLayout(top)
        split = QSplitter()
        self.list = QListWidget()
        self.list.setAccessibleName("Diary entries")
        self.list.setMinimumWidth(240)
        self.list.currentRowChanged.connect(self._show)
        self.page = QTextBrowser()
        self.page.setObjectName("Paper")
        self.page.setAccessibleName("Diary page")
        self.page.setOpenExternalLinks(False)
        split.addWidget(self.list)
        split.addWidget(self.page)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 700])
        lay.addWidget(split, 1)
        self._entries = []
        self._count = -1

    def _open_folder(self) -> None:
        self.rt.paths.diary.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.rt.paths.diary)))

    def refresh(self) -> None:
        count = self.rt.diary.count()
        if count == self._count:
            return
        self._count = count
        self._entries = self.rt.diary.list(limit=500, chronological=True)
        self.list.blockSignals(True)
        self.list.clear()
        for e in self._entries:
            kind = "☾ " if e.kind == "reflection" else ""
            self.list.addItem(QListWidgetItem(f"{kind}Day {e.day} · {e.clock}\n{e.title}"))
        self.list.blockSignals(False)
        if self._entries:
            self.list.setCurrentRow(len(self._entries) - 1)
        else:
            self.page.setHtml("<p style='margin-top:40px; text-align:center'><i>Kimi hasn't written anything yet. "
                              "Entries will appear here when Kimi feels like writing.</i></p>")

    def _show(self, row: int) -> None:
        if not (0 <= row < len(self._entries)):
            return
        e = self._entries[row]
        t = theme.tokens()
        place = LOCATIONS[e.location].name if e.location in LOCATIONS else "somewhere"
        families = ", ".join(f"'{f}'" for f in theme.DIARY_FAMILIES)
        body = "".join(f"<p style='margin: 0 0 12px 0'>{esc(par)}</p>" for par in e.body.split("\n") if par.strip())
        label_kind = "Evening reflection" if e.kind == "reflection" else "Diary entry"
        self.page.setHtml(
            f"<div style=\"font-family: {families}; font-size: {theme.TYPE['reading'] + 1}pt; color: {t.paper_ink}; line-height: 150%;\">"
            f"<p style='color:{t.ink_muted}; font-family: Georgia, serif; font-size:{theme.TYPE['caption'] + 1}pt'>"
            f"{label_kind} · Day {e.day}, {e.clock} · {esc(place)}{' · feeling ' + esc(e.mood) if e.mood else ''}</p>"
            f"<h2 style='font-family: Georgia, serif; font-weight: 500'>{esc(e.title)}</h2>{body}</div>"
        )
