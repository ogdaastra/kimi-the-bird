"""The main world screen: a painted map of Bramblewick and Kimi's status."""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..world.curio3d import curiosity_layout
from ..world.environment import WEATHER_LABELS
from ..world.layout3d import SCALE_X, SCALE_Z
from ..world.locations import EDGES, LOCATIONS
from . import theme
from .widgets import Card, NeedBar, button, esc, label, paint_kimi

INK = QColor("#3d3027")

EVENT_ICONS = {
    "discovery": "✦", "creation": "✎", "visitor": "✉", "diary": "❦", "thought": "❝", "travel": "➝",
    "weather": "☁", "time": "◷", "system": "⚙", "instinct": "♥", "growth": "❀", "memory": "❖",
    "approval": "✓", "observation": "◦", "activity": "•", "thinking": "…", "request": "✿", "human": "♡",
}


# Where Kimi stands at each place (in map units), clear of labels and props.
STAND_OFFSETS = {
    "nest": (1.0, 0.0), "shrub": (1.05, 0.2), "shrine": (-1.05, 0.25), "square": (1.1, 0.05),
    "cafe": (-1.05, 0.3), "print_shop": (-1.05, 0.3), "library": (1.1, 0.3),
}


def _edge_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


class WorldCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(520, 380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Map of Bramblewick")
        self.snap: dict | None = None
        self.reduce_motion = False
        self._bg: QPixmap | None = None
        self._bg_key = None
        self._pos: QPointF | None = None
        self._last_frame = time.monotonic()
        self._t0 = time.monotonic()
        self._facing = 1
        self._drops: list[list[float]] = []
        self._rng = random.Random(3)
        self._bubble_text = ""
        self._bubble_until = 0.0
        self._last_thought = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._frame)
        self.timer.start(33)

    # -- data ---------------------------------------------------------------
    def set_snapshot(self, snap: dict) -> None:
        thought = snap.get("thought")
        if thought and thought != self._last_thought:
            if self._last_thought is not None:
                self._bubble_text = thought["text"]
                self._bubble_until = time.monotonic() + 9.0
            self._last_thought = thought
        self.snap = snap
        self.setAccessibleDescription(f"Kimi is at {snap['place_name']}, {snap['activity']}.")
        if self.reduce_motion:
            self.update()

    def set_reduce_motion(self, on: bool) -> None:
        self.reduce_motion = on
        self.timer.setInterval(250 if on else 33)

    # -- geometry -------------------------------------------------------------
    def _map(self, nx: float, ny: float) -> QPointF:
        m = 46.0
        return QPointF(m + nx * (self.width() - 2 * m), m + 10 + ny * (self.height() - 2 * m - 20))

    def _unit(self) -> float:
        return max(26.0, min(self.width(), self.height()) / 9.0)

    def _curve(self, a: str, b: str) -> tuple[QPointF, QPointF, QPointF]:
        a, b = _edge_key(a, b)
        p0 = self._map(*LOCATIONS[a].position)
        p1 = self._map(*LOCATIONS[b].position)
        mid = (p0 + p1) / 2
        dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
        length = math.hypot(dx, dy) or 1.0
        bend = 0.12 * length if (len(a) + len(b)) % 2 else -0.12 * length
        c = QPointF(mid.x() - dy / length * bend, mid.y() + dx / length * bend)
        return p0, c, p1

    def _on_curve(self, frm: str, to: str, t: float) -> QPointF:
        a, _ = _edge_key(frm, to)
        p0, c, p1 = self._curve(frm, to)
        tt = t if frm == a else 1 - t
        u = 1 - tt
        return p0 * (u * u) + c * (2 * u * tt) + p1 * (tt * tt)

    def _target_pos(self) -> QPointF:
        s = self.snap
        if not s:
            return self._map(*LOCATIONS["nest"].position)
        tr = s.get("travel")
        if tr:
            return self._on_curve(tr["from"], tr["to"], tr["t"])
        loc = LOCATIONS.get(s.get("location") or "nest", LOCATIONS["nest"])
        p = self._map(*loc.position)
        dx, dy = STAND_OFFSETS.get(loc.id, (1.0, 0.25))
        return QPointF(p.x() + self._unit() * dx, p.y() + self._unit() * dy)

    # -- animation ----------------------------------------------------------------
    def _frame(self) -> None:
        now = time.monotonic()
        dt = min(0.25, now - self._last_frame)
        self._last_frame = now
        target = self._target_pos()
        if self._pos is None or self.reduce_motion:
            self._pos = target
        else:
            k = min(1.0, dt * 5.0)
            dx = target.x() - self._pos.x()
            if abs(dx) > 0.5:
                self._facing = 1 if dx > 0 else -1
            self._pos = QPointF(self._pos.x() + dx * k, self._pos.y() + (target.y() - self._pos.y()) * k)
        if not self.reduce_motion:
            self._update_particles(dt)
        self.update()

    def _update_particles(self, dt: float) -> None:
        weather = (self.snap or {}).get("weather", "sunny")
        w, h = self.width(), self.height()
        target = {"rain": 140, "drizzle": 60, "snow": 80}.get(weather, 0)
        while len(self._drops) < target:
            self._drops.append([self._rng.uniform(0, w), self._rng.uniform(-h, 0), self._rng.uniform(0.7, 1.3)])
        if len(self._drops) > target:
            del self._drops[target:]
        speed = 70 if weather == "snow" else 420 if weather == "rain" else 260
        for d in self._drops:
            d[1] += speed * d[2] * dt
            d[0] += (12 if weather == "snow" else -40) * dt * math.sin(d[1] / 40.0 if weather == "snow" else 1)
            if d[1] > h:
                d[0], d[1] = self._rng.uniform(0, w), self._rng.uniform(-40, 0)

    def resizeEvent(self, event) -> None:
        self._bg = None
        self._pos = None
        super().resizeEvent(event)

    # -- painting -------------------------------------------------------------------
    def _background(self) -> QPixmap:
        key = (self.width(), self.height(), theme.tokens().name)
        if self._bg is not None and self._bg_key == key:
            return self._bg
        pm = QPixmap(self.size())
        pm.fill(QColor(theme.tokens().window))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(8, 8, self.width() - 16, self.height() - 16)
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        grad.setColorAt(0, QColor("#cfe3b0"))
        grad.setColorAt(1, QColor("#a9cc8a"))
        p.setPen(QPen(QColor("#8aa86f"), 2))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, 18, 18)
        rng = random.Random(11)
        # meadow texture
        p.setPen(QPen(QColor(90, 130, 70, 90), 1.4))
        for _ in range(int(self.width() * self.height() / 2600)):
            x, y = rng.uniform(r.left() + 10, r.right() - 10), rng.uniform(r.top() + 10, r.bottom() - 10)
            p.drawLine(QPointF(x, y), QPointF(x + rng.uniform(-2, 2), y - rng.uniform(3, 7)))
        # flowers
        for _ in range(int(self.width() * self.height() / 9000)):
            x, y = rng.uniform(r.left() + 14, r.right() - 14), rng.uniform(r.top() + 14, r.bottom() - 14)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(rng.choice(["#f4f1ea", "#f2b8c6", "#f7d35a", "#c9b3ec"])))
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)
        # a little pond and some trees
        u = self._unit()
        pond = self._map(0.33, 0.83)
        p.setPen(QPen(QColor("#6f9fb8"), 2))
        p.setBrush(QColor("#9cc9dd"))
        p.drawEllipse(pond, u * 1.1, u * 0.45)
        p.setPen(QPen(QColor("#ffffff"), 1.5))
        p.drawArc(QRectF(pond.x() - u * 0.5, pond.y() - u * 0.15, u * 0.6, u * 0.2), 0, 180 * 16)
        for nx, ny in ((0.06, 0.25), (0.93, 0.1), (0.96, 0.92), (0.68, 0.95), (0.3, 0.08), (0.7, 0.12), (0.04, 0.95)):
            c = self._map(nx, ny)
            p.setPen(QPen(QColor("#6b4a33"), 2))
            p.setBrush(QColor("#8a5a3c"))
            p.drawRect(QRectF(c.x() - 3, c.y(), 6, u * 0.35))
            p.setPen(QPen(QColor("#4c7a47"), 1.5))
            p.setBrush(QColor("#6fa36b"))
            p.drawEllipse(QPointF(c.x(), c.y() - u * 0.05), u * 0.32, u * 0.3)
        # paths
        for a, b, _ in EDGES:
            p0, c, p1 = self._curve(a, b)
            path = QPainterPath(p0)
            path.quadTo(c, p1)
            p.setPen(QPen(QColor("#b79d74"), u * 0.32, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(QPen(QColor("#e8d8b4"), u * 0.24, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(QColor("#cdb88f"), 1.4, Qt.PenStyle.DashLine))
            p.drawPath(path)
        p.end()
        self._bg, self._bg_key = pm, key
        return pm

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._background())
        s = self.snap or {}
        light = float(s.get("light", 1.0))
        now = time.monotonic() - self._t0
        u = self._unit()

        for lid, loc in LOCATIONS.items():
            self._draw_place(p, lid, self._map(*loc.position), u, light, now, s)

        self._draw_curiosities(p, u, now, s)

        for lid, loc in LOCATIONS.items():
            self._draw_label(p, loc.name, self._map(*loc.position), u, lid == s.get("location"))

        self._draw_kimi(p, u, now, s)
        self._draw_weather(p, s, now)

        # Night overlay, clipped to the map
        if light < 0.999:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(8, 8, self.width() - 16, self.height() - 16), 18, 18)
            p.setClipPath(clip)
            p.fillRect(self.rect(), QColor(18, 24, 58, int((1 - light) * 150)))
            if light < 0.6:
                rng = random.Random(5)
                for _ in range(70):
                    x, y = rng.uniform(16, self.width() - 16), rng.uniform(16, self.height() * 0.55)
                    tw = 0.5 + 0.5 * math.sin(now * rng.uniform(1, 3) + x)
                    alpha = int((0.6 - light) / 0.6 * 200 * (tw if not self.reduce_motion else 1))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 246, 200, max(0, alpha)))
                    p.drawEllipse(QPointF(x, y), 1.4, 1.4)
                # windows glow on top of the overlay
                for lid, loc in LOCATIONS.items():
                    if loc.indoor or lid == "shrine":
                        c = self._map(*loc.position)
                        g = QRadialGradient(c, u * 1.3)
                        g.setColorAt(0, QColor(255, 210, 120, int((0.6 - light) * 160)))
                        g.setColorAt(1, QColor(255, 210, 120, 0))
                        p.setBrush(QBrush(g))
                        p.drawEllipse(c, u * 1.3, u * 1.3)
            p.setClipping(False)

        self._draw_bubble(p, u, now, s)
        p.end()

    _CURIO = None

    def _draw_curiosities(self, p: QPainter, u: float, now: float, s: dict) -> None:
        """Little markers for the curiosities: gold once Kimi has examined them."""
        if WorldCanvas._CURIO is None:
            WorldCanvas._CURIO = [(c["id"], c["x"] / SCALE_X + 0.5, c["z"] / SCALE_Z + 0.5) for c in curiosity_layout()]
        seen = set(s.get("curiosities_seen") or [])
        current = s.get("curiosity")
        r = max(2.5, u * 0.09)
        for cid, nx, ny in WorldCanvas._CURIO:
            if not (0.025 < nx < 0.975 and 0.03 < ny < 0.97):
                continue
            c = self._map(nx, ny)
            if cid == current:
                pulse = 1.0 if self.reduce_motion else 1.0 + 0.25 * math.sin(now * 4)
                p.setPen(QPen(QColor("#e8b73a"), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, r * 2.4 * pulse, r * 2.4 * pulse)
            p.setPen(QPen(QColor("#6b4a33"), 1.1))
            p.setBrush(QColor("#e8b73a") if cid in seen else QColor("#fbf3df"))
            diamond = QPainterPath(QPointF(c.x(), c.y() - r))
            for dx, dy in ((r, 0), (0, r), (-r, 0), (0, -r)):
                diamond.lineTo(QPointF(c.x() + dx, c.y() + dy))
            p.drawPath(diamond)

    def _draw_label(self, p: QPainter, text: str, c: QPointF, u: float, current: bool) -> None:
        f = theme.font("caption", theme.HEADING_FAMILIES, QFont.Weight.DemiBold)
        f.setPointSizeF(max(8.5, min(11.0, u / 6.0)))
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 18
        h = fm.height() + 6
        r = QRectF(c.x() - w / 2, c.y() + u * 0.78, w, h)
        p.setPen(QPen(QColor("#8a6f4f") if not current else QColor("#3f6e4e"), 2 if current else 1.2))
        p.setBrush(QColor("#fbf3df") if not current else QColor("#eef5e6"))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(INK)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_place(self, p: QPainter, lid: str, c: QPointF, u: float, light: float, now: float, s: dict) -> None:
        lit = light < 0.65
        window = QColor("#ffd479") if lit else QColor("#cfe6f2")
        p.save()
        p.translate(c)
        pen = QPen(INK, 1.8)
        p.setPen(pen)
        if lid == "nest":
            p.setBrush(QColor("#8a5a3c"))
            trunk = QPainterPath(QPointF(-u * 0.35, u * 0.6))
            trunk.cubicTo(QPointF(-u * 0.25, 0), QPointF(-u * 0.3, -u * 0.3), QPointF(-u * 0.2, -u * 0.5))
            trunk.lineTo(QPointF(u * 0.2, -u * 0.5))
            trunk.cubicTo(QPointF(u * 0.3, -u * 0.3), QPointF(u * 0.25, 0), QPointF(u * 0.35, u * 0.6))
            trunk.closeSubpath()
            p.drawPath(trunk)
            p.setBrush(QColor("#5f8f55"))
            for dx, dy, r in ((-0.45, -0.75, 0.45), (0.4, -0.8, 0.45), (0, -1.05, 0.55)):
                p.drawEllipse(QPointF(dx * u, dy * u), r * u, r * u * 0.85)
            p.setBrush(QColor("#3b2a1f") if not lit else QColor("#7a5a2a"))
            p.drawEllipse(QPointF(0, u * 0.12), u * 0.16, u * 0.2)
        elif lid == "shrub":
            p.setPen(QPen(QColor("#3f6e44"), 1.8))
            for dx, dy, r, col in ((-0.4, 0.1, 0.42, "#5d9157"), (0.35, 0.05, 0.45, "#5d9157"),
                                   (0, -0.25, 0.55, "#6da567"), (-0.1, 0.25, 0.4, "#79b071")):
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(dx * u, dy * u), r * u, r * u * 0.85)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#7b2d5b"))
            for dx, dy in ((-0.3, -0.1), (0.2, -0.3), (0.35, 0.15), (-0.05, 0.1), (0.05, -0.45)):
                p.drawEllipse(QPointF(dx * u, dy * u), u * 0.05, u * 0.05)
        elif lid == "shrine":
            p.setBrush(QColor("#b9b3a5"))
            p.drawRect(QRectF(-u * 0.45, -u * 0.2, u * 0.9, u * 0.75))
            roof = QPainterPath(QPointF(-u * 0.7, -u * 0.18))
            roof.quadTo(QPointF(0, -u * 0.55), QPointF(u * 0.7, -u * 0.18))
            roof.lineTo(QPointF(u * 0.55, -u * 0.32))
            roof.quadTo(QPointF(0, -u * 0.75), QPointF(-u * 0.55, -u * 0.32))
            roof.closeSubpath()
            p.setBrush(QColor("#7f8f7a"))
            p.drawPath(roof)
            p.setBrush(QColor("#5a5148") if not lit else QColor("#e8b85c"))
            p.drawRect(QRectF(-u * 0.14, u * 0.1, u * 0.28, u * 0.45))
            # notice board with notes
            p.setBrush(QColor("#a07850"))
            p.drawRect(QRectF(u * 0.55, -u * 0.05, u * 0.42, u * 0.32))
            p.drawLine(QPointF(u * 0.76, u * 0.27), QPointF(u * 0.76, u * 0.55))
            unread = int(s.get("unread_notes", 0) or 0)
            p.setPen(QPen(INK, 1))
            for i in range(min(4, unread + 1)):
                flutter = 0 if self.reduce_motion else math.sin(now * 3 + i) * 1.5
                p.setBrush(QColor("#fffaf0") if i < unread else QColor("#e9dcc0"))
                p.drawRect(QRectF(u * (0.58 + 0.09 * i), -u * 0.02 + flutter, u * 0.08, u * 0.11))
            if unread:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#a83b2a"))
                p.drawEllipse(QPointF(u * 0.98, -u * 0.1), u * 0.13, u * 0.13)
                p.setPen(QColor("#ffffff"))
                f = theme.font("caption")
                f.setPointSizeF(max(7.0, u / 8))
                f.setBold(True)
                p.setFont(f)
                p.drawText(QRectF(u * 0.85, -u * 0.23, u * 0.26, u * 0.26), Qt.AlignmentFlag.AlignCenter, str(unread))
            # chimes
            p.setPen(QPen(QColor("#c9a23c"), 1.5))
            sway = 0 if self.reduce_motion else math.sin(now * 2) * 2
            for i in range(3):
                x = -u * 0.5 + i * u * 0.08
                p.drawLine(QPointF(x, -u * 0.22), QPointF(x + sway, -u * 0.05 - i * 2))
        elif lid == "square":
            p.setPen(QPen(QColor("#8d8170"), 1.5))
            p.setBrush(QColor("#d9cfbd"))
            p.drawEllipse(QPointF(0, 0), u * 0.75, u * 0.5)
            p.setBrush(QColor("#b8ad9b"))
            p.drawEllipse(QPointF(0, 0), u * 0.32, u * 0.2)
            p.setBrush(QColor("#9cc9dd"))
            p.drawEllipse(QPointF(0, 0), u * 0.24, u * 0.13)
            p.setPen(QPen(QColor("#ffffff"), 2))
            phase = 0 if self.reduce_motion else (now * 2) % 1.0
            for side in (-1, 1):
                arc = QPainterPath(QPointF(0, -u * 0.12))
                arc.quadTo(QPointF(side * u * 0.12, -u * (0.45 + 0.05 * math.sin(phase * 6.28))),
                           QPointF(side * u * 0.22, -u * 0.05))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(arc)
        elif lid in ("cafe", "print_shop", "library"):
            if lid == "library":
                p.setBrush(QColor("#e9dcc3"))
                p.drawRect(QRectF(-u * 0.6, -u * 0.25, u * 1.2, u * 0.8))
                p.setBrush(QColor("#9aa5b5"))
                p.drawChord(QRectF(-u * 0.6, -u * 0.75, u * 1.2, u * 1.0), 0, 180 * 16)
                p.setBrush(QColor("#f4ecd8"))
                for i in range(4):
                    p.drawRect(QRectF(-u * 0.5 + i * u * 0.3, -u * 0.2, u * 0.12, u * 0.7))
                p.setBrush(window)
                p.drawEllipse(QPointF(0, -u * 0.48), u * 0.12, u * 0.12)
            else:
                roof_col = "#c0624b" if lid == "cafe" else "#6a7fa8"
                p.setBrush(QColor("#f2e3c6"))
                p.drawRect(QRectF(-u * 0.55, -u * 0.25, u * 1.1, u * 0.8))
                roof = QPainterPath(QPointF(-u * 0.68, -u * 0.22))
                roof.lineTo(QPointF(0, -u * 0.8))
                roof.lineTo(QPointF(u * 0.68, -u * 0.22))
                roof.closeSubpath()
                p.setBrush(QColor(roof_col))
                p.drawPath(roof)
                p.setBrush(QColor("#8a5a3c"))
                p.drawRect(QRectF(-u * 0.12, u * 0.15, u * 0.24, u * 0.4))
                p.setBrush(window)
                p.drawRect(QRectF(-u * 0.45, -u * 0.12, u * 0.22, u * 0.2))
                p.drawRect(QRectF(u * 0.23, -u * 0.12, u * 0.22, u * 0.2))
                if lid == "cafe":
                    for i in range(5):
                        p.setBrush(QColor("#c0624b") if i % 2 == 0 else QColor("#fbf3df"))
                        p.drawRect(QRectF(-u * 0.55 + i * u * 0.22, u * 0.08, u * 0.22, u * 0.1))
                    p.setPen(QPen(QColor(255, 255, 255, 170), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    for i in range(2):
                        rise = 0 if self.reduce_motion else (now * 0.6 + i * 0.5) % 1.0
                        x = u * 0.35 + math.sin((now + i) * 2) * 3
                        p.drawArc(QRectF(x, -u * (0.9 + rise * 0.5), u * 0.18, u * 0.18), 0, 270 * 16)
                    p.setPen(QPen(INK, 1.8))
                else:
                    p.setBrush(QColor("#fbf3df"))
                    p.drawRect(QRectF(-u * 0.3, -u * 0.55, u * 0.6, u * 0.18))
                    shown = int(s.get("displayed_creations", 0) or 0)
                    for i in range(min(5, shown)):
                        p.setBrush(QColor(["#f2b8c6", "#9cc9dd", "#f7d35a", "#c9b3ec", "#a7cf8e"][i]))
                        p.drawRect(QRectF(u * (0.62 + (i % 2) * 0.16), -u * 0.2 + (i // 2) * u * 0.2, u * 0.13, u * 0.15))
        p.restore()

    def _draw_kimi(self, p: QPainter, u: float, now: float, s: dict) -> None:
        if self._pos is None:
            self._pos = self._target_pos()
        size = max(30.0, u * 0.95)
        travelling = bool(s.get("travel"))
        asleep = bool(s.get("asleep"))
        bob = 0.0
        if not self.reduce_motion:
            bob = -abs(math.sin(now * 9)) * size * 0.18 if travelling else math.sin(now * 2.2) * size * 0.025
        pos = QPointF(self._pos.x(), self._pos.y() + bob)
        # shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(40, 50, 30, 60))
        p.drawEllipse(QPointF(self._pos.x(), self._pos.y() + size * 0.55), size * 0.42, size * 0.1)
        blink = (now % 4.3) < 0.13 and not self.reduce_motion
        paint_kimi(p, pos.x(), pos.y(), size, blink=blink, asleep=asleep, facing=self._facing)
        if asleep:
            p.setPen(QColor("#f4ecd8"))
            f = theme.heading_font("h2")
            for i in range(3):
                phase = 0 if self.reduce_motion else (now * 0.5 + i / 3) % 1.0
                f.setPointSizeF(9 + i * 2)
                p.setFont(f)
                p.setPen(QColor(244, 236, 216, int(255 * (1 - phase))))
                p.drawText(QPointF(pos.x() + size * 0.35 + i * 8, pos.y() - size * 0.5 - phase * 26 - i * 8), "z")

    def _draw_weather(self, p: QPainter, s: dict, now: float) -> None:
        weather = s.get("weather", "sunny")
        if weather in ("cloudy", "drizzle", "rain", "breezy", "snow"):
            n = 4 if weather in ("cloudy", "rain") else 2
            for i in range(n):
                x = ((now * (8 + i * 3) + i * 230) % (self.width() + 300)) - 150
                if self.reduce_motion:
                    x = 80 + i * 220
                y = 40 + (i % 2) * 40
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 150 if weather != "rain" else 120))
                for dx, dy, r in ((0, 0, 30), (28, -10, 36), (60, 2, 26)):
                    p.drawEllipse(QPointF(x + dx, y + dy), r, r * 0.7)
        if weather == "foggy":
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0, QColor(240, 240, 235, 60))
            g.setColorAt(1, QColor(240, 240, 235, 150))
            p.fillRect(self.rect(), QBrush(g))
        if self._drops:
            if weather == "snow":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 220))
                for x, y, k in self._drops:
                    p.drawEllipse(QPointF(x, y), 2.2 * k, 2.2 * k)
            else:
                p.setPen(QPen(QColor(120, 160, 200, 170), 1.3))
                length = 12 if weather == "rain" else 6
                for x, y, k in self._drops:
                    p.drawLine(QPointF(x, y), QPointF(x - 3, y + length * k))

    def _draw_bubble(self, p: QPainter, u: float, now: float, s: dict) -> None:
        if self._pos is None:
            return
        text = ""
        if s.get("thinking"):
            dots = 1 + int(now * 2.5) % 3 if not self.reduce_motion else 3
            text = "·" * dots
        elif time.monotonic() < self._bubble_until and self._bubble_text:
            text = self._bubble_text if len(self._bubble_text) <= 90 else self._bubble_text[:88] + "…"
        if not text:
            return
        f = theme.font("caption", italic=not s.get("thinking"))
        f.setPointSizeF(10.0)
        p.setFont(f)
        fm = p.fontMetrics()
        max_w = min(280, self.width() * 0.45)
        rect = fm.boundingRect(0, 0, int(max_w), 400, int(Qt.TextFlag.TextWordWrap), text)
        w, h = max(44, rect.width() + 22), rect.height() + 14
        size = max(30.0, u * 0.95)
        x = min(max(10.0, self._pos.x() - w / 2 + size * 0.3), self.width() - w - 10)
        y = max(10.0, self._pos.y() - size * 0.75 - h - 14)
        r = QRectF(x, y, w, h)
        p.setPen(QPen(INK, 1.4))
        p.setBrush(QColor(255, 252, 244, 240))
        p.drawRoundedRect(r, 12, 12)
        p.drawEllipse(QPointF(self._pos.x() + 4, y + h + 6), 4, 4)
        p.drawEllipse(QPointF(self._pos.x() + 1, y + h + 13), 2.5, 2.5)
        p.setPen(INK)
        p.drawText(r.adjusted(11, 7, -11, -7), int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter), text)


class WorldPage(QWidget):
    """The 3D world (or illustrated map) on the left, Kimi's status on the right."""

    def __init__(self, runtime=None, parent: QWidget | None = None, *, mode: str = "3d") -> None:
        super().__init__(parent)
        self.rt = runtime
        self.view3d = None
        self.view3d_error = ""
        self.setObjectName("Page")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 8, 8)
        self.banner_text = label("", wrap=True)
        self.banner_text.setAccessibleName("Something Kimi wants to show you")
        bl.addWidget(self.banner_text, 1)
        self.dismiss_btn = button("Lovely!", tooltip="Dismiss")
        bl.addWidget(self.dismiss_btn)
        self.banner.hide()
        left.addWidget(self.banner)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(6)
        self.btn_3d = button("3D world", tooltip="Explore Bramblewick in 3D")
        self.btn_map = button("Map", tooltip="The illustrated map (lighter on older computers)")
        for b in (self.btn_3d, self.btn_map):
            b.setCheckable(True)
            toggle_row.addWidget(b)
        self.view_note = label("", role="caption", muted=True)
        toggle_row.addWidget(self.view_note, 1)
        left.addLayout(toggle_row)
        self.btn_3d.clicked.connect(lambda: self.set_mode("3d"))
        self.btn_map.clicked.connect(lambda: self.set_mode("map"))

        self.stack = QStackedWidget()
        self.canvas = WorldCanvas()
        self.stack.addWidget(self.canvas)
        left.addWidget(self.stack, 1)
        outer.addLayout(left, 1)

        side = QVBoxLayout()
        side.setSpacing(12)

        # Kimi's rare request to you (an artefact for its world, or information).
        self.ask_card = Card("Kimi asks…")
        self.ask_card.setObjectName("AskCard")
        self.ask_title = label("")
        self.ask_title.setFont(theme.font("body", weight=QFont.Weight.DemiBold))
        self.ask_body = label("")
        self.ask_body.setFont(theme.font("body", italic=True))
        self.ask_body.setAccessibleName("What Kimi is asking")
        self.ask_text = QPlainTextEdit()
        self.ask_text.setMaximumHeight(70)
        self.ask_text.setAccessibleName("Your reply to Kimi")
        ask_buttons = QHBoxLayout()
        self.ask_yes = button("Send answer", role="primary", slot=lambda: self._reply("yes"))
        self.ask_no = button("Not now", slot=lambda: self._reply("decline"))
        ask_buttons.addWidget(self.ask_yes)
        ask_buttons.addWidget(self.ask_no)
        ask_buttons.addStretch(1)
        self.ask_msg = label("", role="caption", muted=True)
        for w in (self.ask_title, self.ask_body, self.ask_text):
            self.ask_card.add(w)
        holder = QWidget()
        holder.setLayout(ask_buttons)
        ask_buttons.setContentsMargins(0, 0, 0, 0)
        self.ask_card.add(holder)
        self.ask_card.add(self.ask_msg)
        self.ask_card.hide()
        self._ask_id = None
        self._ask_kind = None
        side.addWidget(self.ask_card)

        now_card = Card()
        self.place = label("", heading=True, role="h1")
        self.place.setAccessibleName("Kimi's location")
        self.activity = label("")
        self.activity.setAccessibleName("Kimi's current activity")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        self.progress.setRange(0, 100)
        self.when = label("", role="caption", muted=True)
        now_card.add(self.place)
        now_card.add(self.activity)
        now_card.add(self.progress)
        now_card.add(self.when)
        side.addWidget(now_card)

        thought_card = Card("Kimi's thoughts")
        self.thought = label("")
        self.thought.setFont(theme.font("body", italic=True))
        self.thought.setAccessibleName("Kimi's latest thought")
        self.next_thought = label("", role="caption", muted=True)
        thought_card.add(self.thought)
        thought_card.add(self.next_thought)
        side.addWidget(thought_card)

        needs_card = Card("How Kimi feels")
        self.mood = label("")
        needs_card.add(self.mood)
        self.bars = {
            "hunger": NeedBar("Hunger", "hunger"),
            "energy": NeedBar("Energy", "energy"),
            "curiosity": NeedBar("Curiosity", "curiosity"),
            "happiness": NeedBar("Happiness", "happiness"),
            "social": NeedBar("Social interest", "social"),
        }
        for bar in self.bars.values():
            needs_card.add(bar)
        side.addWidget(needs_card)

        events_card = Card("Recently in Bramblewick")
        self.events = QTextBrowser()
        self.events.setAccessibleName("Recent events")
        self.events.setMinimumHeight(140)
        self.events.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.events.setOpenLinks(False)
        events_card.add(self.events, 1)
        side.addWidget(events_card, 1)

        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(340)
        outer.addWidget(side_w)
        self._last_event_id = None
        self.mode = "map"
        self.set_mode(mode)

    # -- 3D / map -------------------------------------------------------------------
    def _ensure_3d(self) -> bool:
        if self.view3d is not None:
            return self.view3d.ok
        if self.view3d_error:
            return False
        try:
            from .world3d.view import World3DView
        except Exception as exc:  # noqa: BLE001 - Qt Quick 3D missing or unloadable
            self.view3d_error = f"3D isn't available here ({type(exc).__name__})."
            return False
        self.view3d = World3DView(self.rt)
        self.view3d.failed.connect(self._on_3d_failed)
        self.stack.addWidget(self.view3d)
        if not self.view3d.ok:
            self.view3d_error = "The 3D scene couldn't be loaded on this computer."
            return False
        return True

    def _on_3d_failed(self, reason: str) -> None:
        self.view3d_error = "3D isn't working on this computer, so here's the map instead."
        if self.mode == "3d":
            self.set_mode("map")

    def set_mode(self, mode: str) -> None:
        if mode == "3d" and not self._ensure_3d():
            mode = "map"
        self.mode = mode
        self.stack.setCurrentWidget(self.view3d if mode == "3d" else self.canvas)
        self.btn_3d.setChecked(mode == "3d")
        self.btn_map.setChecked(mode == "map")
        self.btn_3d.setEnabled(not self.view3d_error)
        if self.view3d_error:
            self.btn_3d.setToolTip(self.view3d_error)
        self.view_note.setText(self.view3d_error if mode == "map" and self.view3d_error else "")

    def _show_request(self, req: dict | None) -> None:
        if not req or req.get("status") != "open":
            if self._ask_id is not None and not self.ask_msg.text():
                self.ask_card.hide()
            if not req:
                self._ask_id = None
            return
        if req["id"] == self._ask_id:
            return
        self._ask_id, self._ask_kind = req["id"], req["kind"]
        wish = req["kind"] == "artefact"
        self.ask_title.setText(f"A wish: {req['title']}" if wish else f"A question about {req['title']}")
        self.ask_body.setText(f"“{req['body']}”")
        self.ask_text.clear()
        self.ask_text.setPlaceholderText("A note for Kimi (optional)" if wish else "Your answer")
        self.ask_yes.setText("Add to wishlist" if wish else "Send answer")
        self.ask_msg.setText("If you agree, it goes on Kimi's wishlist (data\\wishlist.md) to be built later."
                             if wish else "")
        self.ask_card.show()

    def _reply(self, which: str) -> None:
        if self.rt is None or self._ask_id is None:
            return
        action = "decline" if which == "decline" else ("wishlist" if self._ask_kind == "artefact" else "answer")
        ok, message = self.rt.answer_request(self._ask_id, action, self.ask_text.toPlainText())
        self.ask_msg.setText(message)
        if ok:
            self._ask_id = None
            self.ask_text.clear()
            QTimer.singleShot(2500, lambda: (self.ask_msg.setText(""), self.ask_card.hide()) if self._ask_id is None else None)

    def update_from(self, s: dict) -> None:
        self.canvas.set_snapshot(s)
        self._show_request(s.get("request"))
        if self.view3d is not None and self.view3d.ok:
            self.view3d.set_preferences(s.get("graphics_quality", "high"), bool(s.get("reduce_motion")))
            self.view3d.set_snapshot(s)
        self.place.setText(s["place_name"] if not s.get("travel") else "On the path")
        act = s["activity"]
        self.activity.setText(act[0].upper() + act[1:] if act else "")
        prog = s.get("activity_progress")
        self.progress.setVisible(prog is not None)
        if prog is not None:
            self.progress.setValue(int(prog * 100))
        weather = WEATHER_LABELS.get(s["weather"], s["weather"])
        self.when.setText(f"Day {s['day']} · {s['clock']} · {s['time_of_day']} · {weather}, {s['temperature']:.0f}°C")
        t = s.get("thought")
        self.thought.setText(f"“{t['text']}”" if t else "Kimi hasn't shared a thought yet.")
        if s.get("thinking"):
            self.next_thought.setText("Kimi is thinking about what to do next…")
        elif s["status"] in ("active",):
            secs = int(s.get("next_decision_in", 0))
            self.next_thought.setText(
                "Kimi will decide what to do next when it finishes this." if secs <= 0
                else f"Next big decision in about {max(1, secs // 60)} min (local instincts run in between)."
            )
        else:
            self.next_thought.setText({
                "sleeping": "Kimi is asleep. It will wake in the morning.",
                "paused": "Paused - the world is frozen in time.",
                "stopped": "Emergency stop is active. Re-enable autonomy in Settings.",
                "autonomy_off": "Autonomous mode is off.",
                "disconnected": "Can't reach Claude right now; Kimi carries on by instinct.",
                "budget_paused": "Today's AI budget is used up; Kimi carries on by instinct.",
                "needs_key": "No API key - Kimi lives on instinct until you add one in Settings.",
            }.get(s["status"], ""))
        self.mood.setText(f"Mood: <b>{s['mood']}</b>")
        for key, bar in self.bars.items():
            bar.set_value(s["needs"][key], s["need_labels"][key])
        events = [e for e in s["events"] if e["kind"] != "thinking"]
        last_id = (events[-1]["id"], events[-1]["text"]) if events else None
        if last_id != self._last_event_id:
            self._last_event_id = last_id
            muted = theme.tokens().ink_muted
            rows = []
            for e in reversed(events[-25:]):
                icon = EVENT_ICONS.get(e["kind"], "•")
                text = esc(e["text"])
                if e["importance"] >= 0.5:
                    text = f"<b>{text}</b>"
                rows.append(f"<p style='margin:0 0 7px 0'>{icon} <span style='color:{muted}'>{e['clock']}</span> {text}</p>")
            self.events.setHtml("".join(rows))
        h = s.get("highlight")
        if h:
            self.banner_text.setText(f"<b>Kimi has something to show you</b> — {h['text']}")
            self.banner.show()
        else:
            self.banner.hide()
