"""Hosts the Qt Quick 3D scene inside the widgets app."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QSizePolicy

from . import geometry  # noqa: F401  - registers the Kimi3D QML types
from .bridge import World3DBridge

log = logging.getLogger("kimi.ui.world3d")

QML_DIR = Path(__file__).resolve().parent.parent / "qml"
SCENE = QML_DIR / "World3D.qml"


class World3DView(QQuickWidget):
    """The 3D Bramblewick. Emits ``failed(reason)`` if 3D can't run here."""

    failed = Signal(str)

    def __init__(self, runtime=None, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.bridge = World3DBridge(self)
        self._snapshot: dict | None = None
        self._prefs = {"quality": "high", "reduce_motion": False}
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(520, 380)
        self.setAccessibleName("3D view of Bramblewick")
        self.sceneGraphError.connect(lambda _err, message: self._fail(f"graphics error: {message}"))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        if not hasattr(self, "setInitialProperties"):  # QQuickWidget gained this in Qt 6.11
            self.ok = False
            QTimer.singleShot(0, lambda: self._fail("the 3D view needs PySide6 6.11 or newer"))
            return
        self.setInitialProperties({"bridge": self.bridge})
        self.setSource(QUrl.fromLocalFile(str(SCENE)))
        self.ok = self.status() == QQuickWidget.Status.Ready
        if not self.ok:
            errors = "; ".join(e.toString() for e in self.errors())[:500]
            log.warning("3D scene failed to load: %s", errors)
            QTimer.singleShot(0, lambda: self._fail(errors or "the 3D scene could not be loaded"))
            return
        self.timer.start(125)

    def _fail(self, reason: str) -> None:
        self.ok = False
        self.timer.stop()
        self.failed.emit(reason)

    def set_preferences(self, quality: str, reduce_motion: bool) -> None:
        self._prefs = {"quality": quality, "reduce_motion": reduce_motion}

    def set_snapshot(self, snap: dict) -> None:
        self._snapshot = snap
        if self.runtime is None:
            self._push(self._pose_from_snapshot(snap))

    @staticmethod
    def _pose_from_snapshot(snap: dict) -> dict:
        return {"location": snap.get("location"), "travel": snap.get("travel"), "action": None,
                "asleep": snap.get("asleep"), "hour": snap.get("hour", 12.0), "weather": snap.get("weather", "sunny")}

    def _poll(self) -> None:
        if not self.ok or not self.isVisible():
            return
        if self.runtime is not None:
            try:
                pose = self.runtime.pose()
            except Exception:  # noqa: BLE001 - runtime closing
                return
            self._push(pose)

    def _push(self, pose: dict) -> None:
        self.bridge.update(pose, self._snapshot, self._prefs)
