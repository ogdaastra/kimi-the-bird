"""Two-tier memory: creation, retrieval, consolidation and persistence."""

import time

import pytest

from kimi.character import CharacterSheet
from kimi.memory.consolidation import MemoryConsolidator
from kimi.memory.database import Database
from kimi.memory.long_term import LongTermMemory
from kimi.memory.retrieval import MemoryRetriever
from kimi.memory.short_term import ShortTermMemory
from kimi.visitors.board import VisitorRegistry


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


@pytest.fixture
def mem(tmp_path):
    db = Database(tmp_path / "m.db")
    clock = Clock()
    stm, ltm = ShortTermMemory(db, clock), LongTermMemory(db, clock)
    character = CharacterSheet(db)
    yield db, stm, ltm, MemoryRetriever(db, clock), MemoryConsolidator(db, stm, ltm, character, clock), clock, character
    db.close()


def test_memory_creation_with_all_fields(mem):
    db, stm, *_ = mem
    m = stm.add("Found a blue feather in the Shrub.", category="discovery", sim_minute=600, location="shrub",
                importance=0.5, valence=0.6, intensity=0.4)
    assert m.tier == "short" and m.location == "shrub" and m.recurrence == 1
    assert m.importance == 0.5 and m.valence == 0.6 and m.intensity == 0.4
    assert "feather" in m.keywords
    with pytest.raises(ValueError):
        stm.add("   ", category="x", sim_minute=0)


def test_recurring_experience_increments_recurrence(mem):
    _, stm, *_ = mem
    a = stm.add("Ate a seed cake at the Cafe.", category="food", sim_minute=1, location="cafe")
    b = stm.add("Ate a seed cake at the Cafe.", category="food", sim_minute=2, location="cafe")
    c = stm.add("Read a book about owls at the Library.", category="research", sim_minute=3, location="library")
    assert a.id == b.id and b.recurrence == 2
    assert c.id != a.id
    assert stm.count() == 2


def test_retrieval_prefers_relevant_memories(mem):
    _, stm, ltm, retriever, *_ = mem
    for i in range(30):
        stm.add(f"Watched pebble number {i} roll down the path.", category="observation", sim_minute=i,
                location="square", importance=0.1)
    stm.add("Alice left a note about owls at the Shrine.", category="visitor", sim_minute=40, location="shrine",
            visitor="alice", importance=0.6)
    ltm.add("Researched owls: they can turn their heads very far.", category="research", sim_minute=50,
            importance=0.7)
    results = retriever.retrieve("owls at the shrine", location="shrine", visitors={"alice"}, k=3)
    assert len(results) == 3
    texts = [m.description for m in results]
    assert texts[0].startswith("Alice left a note")
    assert any("owls" in t for t in texts[1:])


def test_consolidation_merges_promotes_and_forgets(mem):
    db, stm, ltm, _, consolidator, clock, _ = mem
    registry = VisitorRegistry(db, clock)
    # Recurring visitor at the shrine on separate occasions (outside the dedupe window).
    for i in range(3):
        db.execute("INSERT INTO visitor_notes(received_at, sim_minute, file_hash, original_name, visitor, location, body) "
                   "VALUES(?,?,?,?,?,?,?)", (clock.t, i, f"h{i}", "n.txt", "alice", "shrine", "hi"))
        registry.register_note("Alice", "shrine")
        stm.add(f"Read a note from Alice at the Shrine about the wind chimes ({['a', 'b', 'c'][i]}).",
                category="visitor", sim_minute=i, location="shrine", visitor="alice", importance=0.5)
        clock.t += 7 * 3600
    important = stm.add("Found a rare brass key half buried in leaves.", category="discovery", sim_minute=10,
                        location="shrub", importance=0.8, intensity=0.7)
    trivial = stm.add("Saw a leaf.", category="observation", sim_minute=11, location="square", importance=0.1)
    report = consolidator.consolidate(day=1, sim_minute=1300)
    assert report.merged == 2
    assert report.promoted >= 2
    promoted_ids = {m.id for m in ltm.all()}
    assert important.id in promoted_ids
    alice_long = ltm.about_visitor("alice")
    assert any(m.category == "relationship" and "Alice" in m.description for m in alice_long)
    assert any(m.tier == "long" and m.recurrence >= 3 for m in alice_long if m.category == "visitor")
    assert trivial.id not in promoted_ids
    # Trivial memories fade after a few days.
    clock.t += 4 * 86400
    report2 = consolidator.consolidate(day=5, sim_minute=7000)
    assert report2.forgotten >= 1
    assert all(m.id != trivial.id for m in stm.recent(100))


def test_long_term_reinforcement_across_days(mem):
    db, stm, ltm, _, consolidator, clock, _ = mem
    stm.add("Watched the sunset from the Shrine steps.", category="observation", sim_minute=1, location="shrine",
            importance=0.8)
    consolidator.consolidate(day=1, sim_minute=1300)
    first = ltm.all()[0]
    clock.t += 86400
    stm.add("Watched the sunset from the Shrine steps again.", category="observation", sim_minute=1500,
            location="shrine", importance=0.3)
    report = consolidator.consolidate(day=2, sim_minute=2700)
    assert report.reinforced == 1
    assert ltm.get(first.id).recurrence == 2


def test_consolidation_updates_preferences(mem):
    _, stm, _, _, consolidator, _, character = mem
    before = character.data["location_affinity"].get("shrub", 0.3)
    for i in range(3):
        stm.add(f"Found something wonderful at the Shrub ({i} {'xyz'[i]}).", category="discovery", sim_minute=i,
                location="shrub", valence=0.9, importance=0.5)
    report = consolidator.consolidate(day=1, sim_minute=1300)
    assert character.data["location_affinity"]["shrub"] > before
    assert report.preference_changes


def test_memories_survive_restart(tmp_path):
    db = Database(tmp_path / "p.db")
    ShortTermMemory(db).add("Met a frog.", category="discovery", sim_minute=5, location="shrub", importance=0.4)
    db.close()
    db2 = Database(tmp_path / "p.db")
    assert ShortTermMemory(db2).recent(5)[0].description == "Met a frog."
    db2.close()
