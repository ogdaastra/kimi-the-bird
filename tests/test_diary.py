"""Diary entries are stored, mirrored to Markdown, and read back chronologically."""

import pytest

from kimi.diary import Diary
from kimi.memory.database import Database

from .conftest import TEST_KEY


@pytest.fixture
def diary(tmp_path):
    db = Database(tmp_path / "d.db")
    d = Diary(db, tmp_path / "diary", lambda lid: {"shrub": "The Shrub"}.get(lid, "somewhere"))
    yield d, tmp_path / "diary"
    db.close()


def test_diary_entry_created_and_mirrored(diary):
    d, folder = diary
    e = d.add("A green beetle", "Today I met a beetle that shone like glass. I watched it for ages.",
              sim_minute=1440 + 600, location="shrub", mood="delighted")
    assert e.id and e.day == 2 and e.clock == "10:00"
    text = (folder / "day-0002.md").read_text(encoding="utf-8")
    assert "A green beetle" in text and "The Shrub" in text and "delighted" in text


def test_diary_is_chronological(diary):
    d, _ = diary
    for i in range(3):
        d.add(f"Entry {i}", f"This is diary entry number {i} and it is long enough.", sim_minute=i * 60, location=None)
    titles = [e.title for e in d.list()]
    assert titles == ["Entry 0", "Entry 1", "Entry 2"]
    assert d.latest().title == "Entry 2"


def test_diary_rejects_empty_and_redacts_secrets(diary):
    d, _ = diary
    with pytest.raises(ValueError):
        d.add("x", "short", sim_minute=0, location=None)
    e = d.add("Oops", f"Someone wrote {TEST_KEY} on the board, how odd.", sim_minute=0, location=None)
    assert TEST_KEY not in e.body and "[REDACTED]" in e.body
