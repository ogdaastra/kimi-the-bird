"""Creations screen: drawings, stories, poems and projects Kimi has made."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .widgets import Card, button, esc, label

KIND_LABEL = {"drawing": "Drawing", "diary_illustration": "Diary illustration", "story": "Story",
              "poem": "Poem", "project": "Project"}


class AspectSvg(QSvgWidget):
    """An SVG view that keeps the drawing's aspect ratio."""

    def paintEvent(self, event) -> None:
        r = self.renderer()
        if r.isValid():
            r.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        super().paintEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(480, 380)


class CreationsPage(QWidget):
    def __init__(self, runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rt = runtime
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label("Things Kimi has made", heading=True, role="h1"))
        top.addStretch(1)
        top.addWidget(button("Open creations folder", slot=self._open_folder))
        lay.addLayout(top)

        split = QSplitter()
        self.list = QListWidget()
        self.list.setAccessibleName("Creations")
        self.list.setMinimumWidth(240)
        self.list.currentRowChanged.connect(self._show)
        split.addWidget(self.list)

        right = Card()
        self.title = label("", heading=True, role="h1")
        self.meta = label("", role="caption", muted=True)
        right.add(self.title)
        right.add(self.meta)
        self.stack = QStackedWidget()
        self.svg = AspectSvg()
        self.svg.setAccessibleName("Drawing preview")
        self.text = QTextBrowser()
        self.text.setObjectName("Paper")
        self.text.setAccessibleName("Text preview")
        self.empty = label("Kimi hasn't made anything yet. It might feel creative at the Print Shop soon.", muted=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.svg)
        self.stack.addWidget(self.text)
        self.stack.addWidget(self.empty)
        right.add(self.stack, 1)
        actions = QHBoxLayout()
        self.displayed = QCheckBox("Display at the Print Shop")
        self.displayed.toggled.connect(self._toggle_displayed)
        actions.addWidget(self.displayed)
        actions.addStretch(1)
        self.open_btn = button("Open file", slot=self._open_file)
        actions.addWidget(self.open_btn)
        holder = QWidget()
        holder.setLayout(actions)
        actions.setContentsMargins(0, 0, 0, 0)
        right.add(holder)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 700])
        lay.addWidget(split, 1)
        self._items = []
        self._count = -1

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.rt.paths.creations)))

    def refresh(self) -> None:
        count = self.rt.studio.count()
        if count == self._count:
            return
        self._count = count
        self._items = self.rt.studio.list(200)
        self.list.blockSignals(True)
        self.list.clear()
        for c in self._items:
            self.list.addItem(QListWidgetItem(f"{c.title}\n{KIND_LABEL.get(c.kind, c.kind)} · Day {c.day}"))
        self.list.blockSignals(False)
        if self._items:
            self.list.setCurrentRow(0)
        else:
            self.title.setText("Nothing yet")
            self.meta.setText("")
            self.stack.setCurrentWidget(self.empty)
            self.open_btn.setEnabled(False)
            self.displayed.setEnabled(False)

    def _current(self):
        row = self.list.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def _show(self, _row: int) -> None:
        c = self._current()
        if c is None:
            return
        self.title.setText(c.title)
        self.meta.setText(f"{KIND_LABEL.get(c.kind, c.kind)} · made on Day {c.day} at {self.rt.place_name(c.location)}")
        self.open_btn.setEnabled(bool(c.file_path))
        self.displayed.setEnabled(True)
        self.displayed.blockSignals(True)
        self.displayed.setChecked(bool(c.displayed))
        self.displayed.blockSignals(False)
        path = self.rt.studio.path_of(c)
        if c.kind in ("drawing", "diary_illustration") and path and path.exists():
            self.svg.load(str(path))
            self.stack.setCurrentWidget(self.svg)
        else:
            t = theme.tokens()
            paras = "".join(f"<p>{esc(p)}</p>" for p in c.body.split("\n") if p.strip())
            self.text.setHtml(f"<div style='font-family: Georgia, serif; font-size: {theme.TYPE['reading']}pt; "
                              f"color: {t.paper_ink}; line-height: 150%'>{paras}</div>")
            self.stack.setCurrentWidget(self.text)

    def _toggle_displayed(self, on: bool) -> None:
        c = self._current()
        if c is not None:
            self.rt.studio.set_displayed(c.id, on)
            c.displayed = 1 if on else 0

    def _open_file(self) -> None:
        c = self._current()
        path = self.rt.studio.path_of(c) if c else None
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
