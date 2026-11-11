"""The places of Bramblewick and the paths between them."""

from __future__ import annotations

import heapq
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    kind: str
    description: str
    activities: tuple[str, ...]
    position: tuple[float, float]   # normalised map coordinates for the UI
    indoor: bool = False
    food: tuple[str, ...] = ()


LOCATIONS: dict[str, Location] = {
    loc.id: loc
    for loc in (
        Location(
            "nest", "The Nest", "home",
            "Kimi's cosy home, tucked into the roots of an old oak and lined with moss and thistledown.",
            ("sleep", "rest", "reflect", "write_diary", "observe"),
            (0.13, 0.70), indoor=True, food=("dried rosehips",),
        ),
        Location(
            "shrub", "The Shrub", "nature",
            "An enormous tangled shrub full of beetles, berries, cobwebs and hidden hollows.",
            ("explore", "observe", "rest", "reflect", "eat"),
            (0.27, 0.40), food=("wild blackberries", "clover seeds"),
        ),
        Location(
            "shrine", "The Shrine", "quiet",
            "A small mossy stone shrine with wind chimes and a notice board where visitors leave notes and little gifts.",
            ("read_note", "leave_message", "reflect", "observe", "rest", "explore", "write_diary"),
            (0.50, 0.15),
        ),
        Location(
            "square", "Town Square", "hub",
            "A cobbled square with a chattering fountain. Most paths in Bramblewick meet here.",
            ("observe", "rest", "explore"),
            (0.53, 0.50),
        ),
        Location(
            "cafe", "The Cafe", "social",
            "A warm, crooked cafe run by Marigold the hedgehog, smelling of toast and honey.",
            ("eat", "rest", "observe", "write_diary", "reflect"),
            (0.80, 0.30), indoor=True,
            food=("seed cake", "honey crumpet", "millet porridge", "blackberry tart",
                  "dandelion tea", "toasted sunflower seeds"),
        ),
        Location(
            "print_shop", "The Print Shop", "creative",
            "An old print shop with an iron press, ink-stained drawing tables and a wall for displaying work.",
            ("create_art", "write_diary", "observe", "reflect", "share_creation", "rest"),
            (0.82, 0.72), indoor=True,
        ),
        Location(
            "library", "The Library", "study",
            "A dusty, round library kept by Professor Quill, an elderly owl who never seems to sleep.",
            ("research", "reflect", "write_diary", "observe", "rest"),
            (0.50, 0.84), indoor=True,
        ),
    )
}

# (from, to, travel minutes for a small bird)
EDGES: tuple[tuple[str, str, int], ...] = (
    ("nest", "shrub", 6),
    ("shrub", "square", 7),
    ("shrub", "shrine", 9),
    ("shrine", "square", 8),
    ("square", "cafe", 5),
    ("square", "print_shop", 6),
    ("square", "library", 6),
    ("library", "print_shop", 5),
    ("nest", "library", 11),
)

ART_LOCATION = "print_shop"
RESEARCH_LOCATION = "library"
NOTE_LOCATION = "shrine"
HOME = "nest"


class LocationGraph:
    def __init__(self, locations: dict[str, Location] = LOCATIONS, edges=EDGES) -> None:
        self.locations = locations
        self.adj: dict[str, dict[str, int]] = {lid: {} for lid in locations}
        for a, b, minutes in edges:
            self.adj[a][b] = minutes
            self.adj[b][a] = minutes

    def __contains__(self, lid: object) -> bool:
        return lid in self.locations

    def get(self, lid: str) -> Location:
        return self.locations[lid]

    def name(self, lid: str | None) -> str:
        if lid is None:
            return "somewhere along the path"
        loc = self.locations.get(lid)
        return loc.name if loc else lid

    def neighbours(self, lid: str) -> dict[str, int]:
        return dict(self.adj[lid])

    def shortest_path(self, start: str, goal: str) -> tuple[list[str], int]:
        if start == goal:
            return [start], 0
        dist = {start: 0}
        prev: dict[str, str] = {}
        heap = [(0, start)]
        while heap:
            d, node = heapq.heappop(heap)
            if node == goal:
                break
            if d > dist.get(node, 1 << 30):
                continue
            for nxt, w in self.adj[node].items():
                nd = d + w
                if nd < dist.get(nxt, 1 << 30):
                    dist[nxt] = nd
                    prev[nxt] = node
                    heapq.heappush(heap, (nd, nxt))
        if goal not in dist:
            raise ValueError(f"No path from {start} to {goal}")
        path = [goal]
        while path[-1] != start:
            path.append(prev[path[-1]])
        path.reverse()
        return path, dist[goal]

    def travel_minutes(self, start: str, goal: str) -> int:
        return self.shortest_path(start, goal)[1]

    def nearest_with(self, start: str, predicate) -> str | None:
        best, best_d = None, 1 << 30
        for lid, loc in self.locations.items():
            if predicate(loc):
                d = self.travel_minutes(start, lid)
                if d < best_d:
                    best, best_d = lid, d
        return best
