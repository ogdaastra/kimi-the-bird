"""Memory screen: short-term, long-term, important experiences and visitors."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..world.locations import LOCATIONS
from .widgets import label


def _when(sim_minute: float) -> str:
    day = int(sim_minute // 1440) + 1
    m = int(sim_minute % 1440)
    return f"Day {day} {m // 60:02d}:{m % 60:02d}"


def _place(lid: str | None) -> str:
    return LOCATIONS[lid].name if lid in LOCATIONS else (lid or "")


def _tree(headers: list[str], name: str) -> QTreeWidget:
    t = QTreeWidget()
    t.setHeaderLabels(headers)
    t.setRootIsDecorated(False)
    t.setAlternatingRowColors(True)
    t.setWordWrap(True)
    t.setUniformRowHeights(False)
    t.setAccessibleName(name)
    hdr = t.header()
    hdr.setStretchLastSection(False)
    for i in range(len(headers)):
        hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    return t


class MemoryPage(QWidget):
    MEM_HEADERS = ["When", "Where", "Memory", "Importance", "Times"]

    def __init__(self, runtime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rt = runtime
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label("Memories", heading=True, role="h1"))
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search memories…")
        self.search.setAccessibleName("Search memories")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search)
        lay.addLayout(top)
        self.summary = label("", muted=True)
        lay.addWidget(self.summary)

        self.tabs = QTabWidget()
        self.recent = _tree(self.MEM_HEADERS, "Recent memories")
        self.long = _tree(self.MEM_HEADERS, "Long-term memories")
        self.important = _tree(self.MEM_HEADERS, "Important experiences")
        self.visitors = _tree(["Visitor", "Relationship", "Notes", "Familiarity", "Usually at", "Kimi's impression"],
                              "Visitor relationships")
        for tree in (self.recent, self.long, self.important):
            tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.visitors.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.recent, "Recent (short-term)")
        self.tabs.addTab(self.long, "Long-term")
        self.tabs.addTab(self.important, "Important experiences")
        self.tabs.addTab(self.visitors, "Visitors")
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        lay.addWidget(self.tabs, 1)
        lay.addWidget(label("Short-term memories fade unless they matter or keep happening. Each night Kimi merges "
                            "duplicates and keeps important or recurring experiences for good.", role="caption", muted=True))

    def _fill(self, tree: QTreeWidget, memories) -> None:
        tree.clear()
        for m in memories:
            stars = "★" * max(1, round(m.importance * 5))
            item = QTreeWidgetItem([_when(m.sim_minute), _place(m.location), m.description, stars,
                                    f"×{m.recurrence}" if m.recurrence > 1 else ""])
            item.setToolTip(2, m.description)
            item.setToolTip(3, f"Importance {m.importance:.2f}, emotional significance {m.intensity:.2f}")
            item.setData(3, Qt.ItemDataRole.AccessibleTextRole, f"importance {m.importance:.2f}")
            tree.addTopLevelItem(item)

    def refresh(self) -> None:
        rt = self.rt
        q = self.search.text().strip()
        self.summary.setText(f"{rt.stm.count()} recent memories · {rt.ltm.count()} long-term memories")
        idx = self.tabs.currentIndex()
        if q:
            found = rt.stm.search(q, 200)
            if idx == 0:
                self._fill(self.recent, [m for m in found if m.tier == "short"])
            elif idx in (1, 2):
                self._fill(self.long if idx == 1 else self.important, [m for m in found if m.tier == "long"])
        elif idx == 0:
            self._fill(self.recent, rt.stm.recent(150))
        elif idx == 1:
            self._fill(self.long, rt.ltm.recent(150))
        elif idx == 2:
            self._fill(self.important, rt.ltm.important_experiences(40))
        if idx == 3:
            self.visitors.clear()
            for v in rt.visitors.all():
                if q and q.lower() not in v["display_name"].lower():
                    continue
                self.visitors.addTopLevelItem(QTreeWidgetItem([
                    v["display_name"], v["relationship"], str(v["note_count"]), f"{v['familiarity']:.2f}",
                    _place(v.get("favourite_location")), v.get("impression") or "",
                ]))
