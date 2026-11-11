"""Visitors screen: a local message board and the inbox folder."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..world.locations import LOCATIONS
from . import theme
from .widgets import Card, button, esc, label


class VisitorsPage(QWidget):
    def __init__(self, runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rt = runtime
        self.setObjectName("Page")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(12)
        compose = Card("Leave Kimi a note")
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Your name (optional)")
        self.name.setMaxLength(40)
        self.where = QComboBox()
        for lid in ("shrine", "cafe", "shrub", "square", "library", "print_shop", "nest"):
            self.where.addItem(LOCATIONS[lid].name, lid)
        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("Write something for Kimi…")
        self.message.setMinimumHeight(120)
        self.message.setTabChangesFocus(True)
        form.addRow("Name", self.name)
        form.addRow("Leave it at", self.where)
        form.addRow("Message", self.message)
        holder = QWidget()
        holder.setLayout(form)
        form.setContentsMargins(0, 0, 0, 0)
        compose.add(holder)
        self.send_btn = button("Leave note", role="primary", slot=self._send)
        compose.add(self.send_btn)
        compose.add(label("Kimi will find your note in its own time - it doesn't drop everything for visitors.",
                          role="caption", muted=True))
        left.addWidget(compose)

        inbox = Card("Visitor inbox folder")
        inbox.add(label("Anyone with access to this computer can also leave notes by dropping a <b>.txt</b> file "
                        "(optionally with a matching <b>.png/.jpg</b> picture) into the inbox folder. "
                        "Start a note with <i>From: Name</i> and <i>Location: Cafe</i> lines if you like."))
        inbox.add(label("Files are treated as untrusted: they are read as plain text, never opened or run, "
                        "and anything else is set aside in the 'rejected' folder.", role="caption", muted=True))
        inbox.add(button("Open inbox folder", slot=self._open_inbox))
        left.addWidget(inbox)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(380)
        outer.addWidget(lw)

        board = Card("The Shrine board")
        self.feed = QTextBrowser()
        self.feed.setAccessibleName("Message board")
        board.add(self.feed, 1)
        outer.addWidget(board, 1)
        self._sig = None

    def _open_inbox(self) -> None:
        self.rt.paths.inbox.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.rt.paths.inbox)))

    def _send(self) -> None:
        text = self.message.toPlainText().strip()
        if not text:
            self.message.setFocus()
            return
        try:
            self.rt.board.post_visitor_note(self.name.text(), self.where.currentText(), text)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Kimi", f"The note couldn't be left: {exc}")
            return
        self.message.clear()
        self.send_btn.setText("Note left ✓")
        from PySide6.QtCore import QTimer

        QTimer.singleShot(2500, lambda: self.send_btn.setText("Leave note"))

    def refresh(self) -> None:
        items = self.rt.board.feed(80)
        sig = (len(items), items[-1]["id"] if items else None, items[-1].get("read_at") if items else None)
        if sig == self._sig:
            return
        self._sig = sig
        t = theme.tokens()
        if not items:
            self.feed.setHtml("<p style='text-align:center; margin-top:40px'><i>The board is empty. Notes from "
                              "visitors and Kimi's replies will appear here.</i></p>")
            return
        parts = []
        for it in items:
            day = int(it["sim_minute"] // 1440) + 1
            place = LOCATIONS[it["location"]].name if it["location"] in LOCATIONS else it["location"]
            if it["kind"] == "kimi":
                bg, who, align = t.accent_soft, "Kimi", "right"
            else:
                bg, who, align = t.surface_alt, esc(it["author"] or "Anonymous"), "left"
            status = ""
            if it["kind"] == "visitor":
                status = " · read by Kimi" if it.get("read_at") else " · not read yet"
            pic = ""
            if it.get("image_path"):
                pic = "<br><i>[picture attached" + (f": {esc(it['image_description'])}" if it.get("image_description") else "") + "]</i>"
            body = esc(it["body"]).replace("\n", "<br>")
            parts.append(
                f"<table align='{align}' width='82%' cellspacing='0' cellpadding='10' bgcolor='{bg}' "
                f"style='border: 1px solid {t.outline}; margin-top: 4px; margin-bottom: 4px;'><tr><td>"
                f"<b>{who}</b> <span style='color:{t.ink_muted}'>· Day {day} · {esc(place)}{status}</span><br>{body}{pic}"
                "</td></tr></table><br clear='all'>"
            )
        self.feed.setHtml("".join(parts))
        self.feed.verticalScrollBar().setValue(self.feed.verticalScrollBar().maximum())
