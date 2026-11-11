"""Reusable widgets and helpers for Kimi's interface."""

from __future__ import annotations

import html
from typing import Any, Callable

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

# ---------------------------------------------------------------------------
# Background work: run a function off the UI thread and get the result back.
# ---------------------------------------------------------------------------


class _Signals(QObject):
    done = Signal(object, object)  # result, error


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self) -> None:  # runs on a pool thread
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001
            self.signals.done.emit(None, exc)
        else:
            self.signals.done.emit(result, None)


_live: set[_Signals] = set()


def run_async(fn: Callable[[], Any], callback: Callable[[Any, Exception | None], None]) -> None:
    task = _Task(fn)
    signals = task.signals
    _live.add(signals)

    def finish(result: Any, error: Exception | None) -> None:
        _live.discard(signals)
        callback(result, error)

    signals.done.connect(finish)
    QThreadPool.globalInstance().start(task)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def button(text: str, role: str | None = None, tooltip: str | None = None, slot: Callable | None = None) -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def label(text: str = "", role: str = "body", muted: bool = False, wrap: bool = True, heading: bool = False,
          selectable: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setFont(theme.heading_font(role) if heading else theme.font(role))
    lab.setWordWrap(wrap)
    lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    if muted:
        lab.setObjectName("Muted")
    if selectable:
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


class Card(QFrame):
    """A rounded surface with an optional title."""

    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(16, 14, 16, 16)
        self.layout_.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            t.setFont(theme.heading_font("h2"))
            self.layout_.addWidget(t)

    def add(self, w: QWidget, stretch: int = 0) -> QWidget:
        self.layout_.addWidget(w, stretch)
        return w


class NeedBar(QWidget):
    """A labelled bar. Colour is paired with a number and a word, never colour alone."""

    def __init__(self, name: str, color_role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.color_role = color_role
        self.value = 0.0
        self.word = ""
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(name)

    def set_value(self, value: float, word: str) -> None:
        self.value = max(0.0, min(100.0, value))
        self.word = word
        self.setAccessibleDescription(f"{self.name}: {self.value:.0f} out of 100, {word}")
        self.setToolTip(f"{self.name}: {self.value:.0f}/100 ({word})")
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(260, 40)

    def paintEvent(self, _event) -> None:
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setFont(theme.font("body"))
        p.setPen(QColor(t.ink))
        p.drawText(QRectF(0, 0, w * 0.5, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.name)
        p.setPen(QColor(t.ink_muted))
        p.setFont(theme.font("caption"))
        p.drawText(QRectF(w * 0.4, 0, w * 0.6, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{self.word} · {self.value:.0f}")
        track = QRectF(0, 25, w, 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.surface_alt))
        p.drawRoundedRect(track, 4.5, 4.5)
        p.setBrush(QColor(getattr(t, self.color_role)))
        fill = QRectF(track.x(), track.y(), max(9.0, track.width() * self.value / 100.0), track.height())
        p.drawRoundedRect(fill, 4.5, 4.5)
        p.setPen(QPen(QColor(t.outline), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(track, 4.5, 4.5)


STATUS_STYLE = {
    "active": ("success", "●"),
    "sleeping": ("info", "☾"),
    "paused": ("warning", "❚❚"),
    "stopped": ("danger", "■"),
    "autonomy_off": ("warning", "○"),
    "disconnected": ("danger", "⚠"),
    "budget_paused": ("warning", "$"),
    "needs_key": ("danger", "⚠"),
}


class StatusPill(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Kimi status")
        self.set_status("active", "Active")

    def set_status(self, status: str, text: str, detail: str = "") -> None:
        t = theme.tokens()
        role, glyph = STATUS_STYLE.get(status, ("info", "●"))
        color = getattr(t, role)
        self.setText(f"{glyph}  {text}")
        self.setToolTip(detail or text)
        self.setStyleSheet(
            f"QLabel {{ color: {color}; background: {t.surface_alt}; border: 1px solid {color};"
            f" border-radius: 12px; padding: 4px 12px; font-weight: 600; }}"
        )
        self.setAccessibleDescription(f"Status: {text}. {detail}")


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {theme.tokens().outline};")
    return line


def row(*widgets: QWidget, spacing: int = 8, stretch_last: bool = False) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for item in widgets:
        lay.addWidget(item)
    if not stretch_last:
        lay.addStretch(1)
    return w


# ---------------------------------------------------------------------------
# Kimi's portrait (used for the window icon, setup screen and header)
# ---------------------------------------------------------------------------


def paint_kimi(p: QPainter, cx: float, cy: float, size: float, *, blink: bool = False, asleep: bool = False,
               facing: int = 1) -> None:
    """Draw Kimi, a small round slate-blue wren, centred at (cx, cy)."""
    s = size / 40.0
    p.save()
    p.translate(cx, cy)
    p.scale(s * facing, s)
    ink = QColor("#3d3027")
    p.setPen(QPen(ink, 1.6))
    # tail
    tail = QPainterPath(QPointF(-14, -4))
    tail.lineTo(-27, -15)
    tail.lineTo(-22, -1)
    tail.closeSubpath()
    p.setBrush(QColor("#5f7799"))
    p.drawPath(tail)
    # body
    p.setBrush(QColor("#7d95b8"))
    p.drawEllipse(QRectF(-18, -15, 36, 31))
    # chest
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#f6c6a3"))
    p.drawEllipse(QRectF(-4, -3, 20, 16))
    # wing
    p.setPen(QPen(ink, 1.2))
    p.setBrush(QColor("#647ea3"))
    p.drawEllipse(QRectF(-12, -6, 16, 11))
    # eye
    if asleep or blink:
        p.setPen(QPen(ink, 1.6))
        p.drawLine(QPointF(5, -7), QPointF(10, -7))
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2b2420"))
        p.drawEllipse(QPointF(7.5, -7), 2.6, 2.6)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(8.3, -7.8), 0.9, 0.9)
    # beak
    p.setPen(QPen(ink, 1.0))
    p.setBrush(QColor("#f0a347"))
    beak = QPainterPath(QPointF(16, -5))
    beak.lineTo(23, -2.5)
    beak.lineTo(16, 0)
    beak.closeSubpath()
    p.drawPath(beak)
    # legs
    p.setPen(QPen(QColor("#c98a4b"), 1.6))
    p.drawLine(QPointF(-3, 15), QPointF(-5, 21))
    p.drawLine(QPointF(5, 15), QPointF(6, 21))
    p.restore()


def kimi_pixmap(size: int = 64, background: str | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if background:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(background)))
        p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    paint_kimi(p, size * 0.48, size * 0.52, size * 0.78)
    p.end()
    return pm


def kimi_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(kimi_pixmap(s, "#f3ead6"))
    return icon


def empty_state(text: str) -> QLabel:
    lab = label(text, muted=True)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setMinimumHeight(80)
    return lab


def vbox(parent: QWidget | None = None, margins: tuple[int, int, int, int] = (0, 0, 0, 0), spacing: int = 10) -> QVBoxLayout:
    lay = QVBoxLayout(parent)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay
