"""Custom Qt Quick 3D geometry: the procedural town meshes and the sky dome.

Registered for QML as ``import Kimi3D`` (types ``TownMesh`` and ``SkyDome``).
"""

from __future__ import annotations

import math
from array import array

from PySide6.QtCore import Property, QByteArray, Signal
from PySide6.QtGui import QColor, QVector3D
from PySide6.QtQml import QmlElement
from PySide6.QtQuick3D import QQuick3DGeometry

from ...world.mesh3d import srgb_to_linear, town_meshes

QML_IMPORT_NAME = "Kimi3D"
QML_IMPORT_MAJOR_VERSION = 1

_A = QQuick3DGeometry.Attribute


def _upload(geom: QQuick3DGeometry, data: bytes, lo, hi) -> None:
    geom.clear()
    if data:
        geom.setStride(40)
        geom.setVertexData(QByteArray(data))
        geom.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        geom.setBounds(QVector3D(*lo), QVector3D(*hi))
        geom.addAttribute(_A.Semantic.PositionSemantic, 0, _A.ComponentType.F32Type)
        geom.addAttribute(_A.Semantic.NormalSemantic, 12, _A.ComponentType.F32Type)
        geom.addAttribute(_A.Semantic.ColorSemantic, 24, _A.ComponentType.F32Type)
    geom.update()


@QmlElement
class TownMesh(QQuick3DGeometry):
    """One of the static town meshes, chosen by name (terrain, paths, buildings, glow, nature, water)."""

    meshNameChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._name = ""

    def _get_name(self) -> str:
        return self._name

    def _set_name(self, name: str) -> None:
        if name == self._name:
            return
        self._name = name
        mesh = town_meshes().get(name)
        if mesh is None:
            _upload(self, b"", (0, 0, 0), (0, 0, 0))
        else:
            _upload(self, mesh.to_bytes(), mesh.bounds_min, mesh.bounds_max)
        self.meshNameChanged.emit()

    meshName = Property(str, _get_name, _set_name, notify=meshNameChanged)


@QmlElement
class SkyDome(QQuick3DGeometry):
    """A large inward-facing sphere whose vertex colours fade from horizon to zenith."""

    colorsChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._top = QColor("#6aa6e0")
        self._horizon = QColor("#cfe6f2")
        self._bottom = QColor("#3c5a3a")
        self._radius = 7000.0
        self._rebuild()

    def _rebuild(self) -> None:
        r = self._radius
        rings, seg = 14, 28
        top, hor, bot = (tuple(srgb_to_linear(c) for c in col.getRgbF()[:3])
                         for col in (self._top, self._horizon, self._bottom))

        def colour(lat: float):
            if lat >= 0:
                t = min(1.0, (lat / (math.pi / 2)) ** 0.6)
                return tuple(hor[i] + (top[i] - hor[i]) * t for i in range(3)) + (1.0,)
            t = min(1.0, -lat / 0.35)
            return tuple(hor[i] + (bot[i] - hor[i]) * t for i in range(3)) + (1.0,)

        data = array("f")
        for k in range(rings):
            lat0 = -math.pi / 2 + math.pi * k / rings
            lat1 = -math.pi / 2 + math.pi * (k + 1) / rings
            for i in range(seg):
                a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
                quad = [(lat0, a0), (lat0, a1), (lat1, a1), (lat1, a0)]
                pts = [(r * math.cos(la) * math.cos(lo), r * math.sin(la), r * math.cos(la) * math.sin(lo)) for la, lo in quad]
                cols = [colour(la) for la, _ in quad]
                for idx in (0, 2, 1, 0, 3, 2):  # inward winding
                    p = pts[idx]
                    n = (-p[0] / r, -p[1] / r, -p[2] / r)
                    data.extend((*p, *n, *cols[idx]))
        _upload(self, data.tobytes(), (-r, -r, -r), (r, r, r))

    def _getter(attr):
        return lambda self: getattr(self, attr)

    def _setter(attr):
        def setter(self, value) -> None:
            value = QColor(value)
            if value != getattr(self, attr):
                setattr(self, attr, value)
                self._rebuild()
                self.colorsChanged.emit()
        return setter

    topColor = Property(QColor, _getter("_top"), _setter("_top"), notify=colorsChanged)
    horizonColor = Property(QColor, _getter("_horizon"), _setter("_horizon"), notify=colorsChanged)
    bottomColor = Property(QColor, _getter("_bottom"), _setter("_bottom"), notify=colorsChanged)
