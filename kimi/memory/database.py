"""SQLite persistence for everything Kimi is and remembers.

One connection is shared between threads and guarded by a re-entrant lock.
WAL journaling keeps writes durable and makes recovery after a crash
automatic.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tier TEXT NOT NULL CHECK(tier IN ('short', 'long')),
    created_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    description TEXT NOT NULL,
    location TEXT,
    category TEXT NOT NULL,
    visitor TEXT,
    importance REAL NOT NULL,
    valence REAL NOT NULL DEFAULT 0,
    intensity REAL NOT NULL DEFAULT 0,
    recurrence INTEGER NOT NULL DEFAULT 1,
    keywords TEXT NOT NULL DEFAULT '',
    last_seen_at REAL NOT NULL,
    last_recalled_at REAL,
    recall_count INTEGER NOT NULL DEFAULT 0,
    promoted_at REAL,
    merged_into INTEGER,
    forgotten INTEGER NOT NULL DEFAULT 0,
    consolidated INTEGER NOT NULL DEFAULT 0,
    source_ids TEXT
);
CREATE INDEX IF NOT EXISTS idx_mem_tier ON memories(tier, forgotten, merged_into, created_at);
CREATE INDEX IF NOT EXISTS idx_mem_visitor ON memories(visitor);
CREATE TABLE IF NOT EXISTS diary(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    location TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    mood TEXT,
    kind TEXT NOT NULL DEFAULT 'entry'
);
CREATE TABLE IF NOT EXISTS creations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    file_path TEXT,
    location TEXT,
    displayed INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS visitors(
    key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    note_count INTEGER NOT NULL DEFAULT 0,
    familiarity REAL NOT NULL DEFAULT 0,
    impression TEXT NOT NULL DEFAULT '',
    favourite_location TEXT
);
CREATE TABLE IF NOT EXISTS visitor_notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    visitor TEXT NOT NULL,
    location TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    image_path TEXT,
    image_description TEXT,
    read_at REAL,
    kimi_reply TEXT
);
CREATE TABLE IF NOT EXISTS board_messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    author TEXT NOT NULL,
    location TEXT NOT NULL,
    body TEXT NOT NULL,
    in_reply_to INTEGER
);
CREATE TABLE IF NOT EXISTS action_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    action TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS api_usage(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    day TEXT NOT NULL,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    success INTEGER NOT NULL,
    error_kind TEXT,
    latency_ms INTEGER,
    request_id TEXT,
    web_searches INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON api_usage(day);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    location TEXT,
    importance REAL NOT NULL DEFAULT 0.1
);
CREATE TABLE IF NOT EXISTS discoveries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    sim_minute REAL NOT NULL,
    location TEXT NOT NULL,
    item TEXT NOT NULL,
    description TEXT NOT NULL,
    rarity TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    day TEXT NOT NULL,
    topic TEXT NOT NULL,
    title TEXT,
    source_url TEXT,
    summary TEXT,
    takeaway TEXT,
    source TEXT NOT NULL DEFAULT 'encyclopedia',
    citations TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS curiosity_visits(
    curiosity TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    first_day INTEGER NOT NULL DEFAULT 1,
    visits INTEGER NOT NULL DEFAULT 0,
    last_detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS human_requests(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    day TEXT NOT NULL,
    sim_day INTEGER NOT NULL DEFAULT 1,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    location TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    reply TEXT,
    replied_at REAL
);
CREATE TABLE IF NOT EXISTS outbox(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    decided_at REAL,
    result TEXT
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None, timeout=10
        )
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA)
            self.conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._migrate()
        self._depth = 0
        self.closed = False

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        added = {
            "research_log": (("source", "TEXT NOT NULL DEFAULT 'encyclopedia'"), ("citations", "TEXT NOT NULL DEFAULT '[]'")),
            "api_usage": (("web_searches", "INTEGER NOT NULL DEFAULT 0"),),
        }
        for table, columns in added.items():
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    # -- basic operations -------------------------------------------------
    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq) -> None:
        with self.lock:
            self.conn.executemany(sql, seq)

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | list = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None or row[0] is None:
            return default
        return row[0]

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    # -- key/value store for structured state -----------------------------
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM kv WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value), time.time()),
        )

    def kv_delete(self, key: str) -> None:
        self.execute("DELETE FROM kv WHERE key=?", (key,))

    def checkpoint(self) -> None:
        with self.lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self.conn.close()
            self.closed = True
