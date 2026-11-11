"""Visitor inbox: notes and pictures dropped into ``data/visitors/inbox``.

Every file is untrusted. Files are never executed or opened with other
programs. Text is decoded, size-limited and sanitised; images are verified
and re-encoded by Pillow; anything else is moved to ``rejected`` without
being read. Processed files are moved to ``archive``.

Optional headers at the top of a text note::

    From: Alice
    Location: Shrine

    Hello Kimi! ...
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..safety import clean_text, safe_child_path, sanitize_name
from ..world.locations import LOCATIONS, NOTE_LOCATION
from .board import ANONYMOUS, VisitorRegistry, visitor_key

log = logging.getLogger("kimi.visitors")

TEXT_EXT = {".txt", ".md"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_TEXT_BYTES = 20_000
MAX_IMAGE_BYTES = 8_000_000
MAX_BODY_CHARS = 4000
SETTLE_SECONDS = 1.0
IGNORED_SUFFIXES = (".part", ".tmp", ".crdownload", ".partial")


@dataclass
class VisitorNote:
    id: int
    visitor_key: str
    visitor_name: str
    location: str
    body: str
    image_path: str | None
    original_name: str


def _location_from(hint: str) -> str:
    h = hint.strip().lower().replace("the ", "").replace("-", " ").replace("_", " ")
    for loc in LOCATIONS.values():
        names = {loc.id.replace("_", " "), loc.name.lower().replace("the ", "")}
        if h in names or any(h.startswith(n) for n in names):
            return loc.id
    return NOTE_LOCATION


def parse_note(text: str) -> tuple[str, str, str]:
    """Return (visitor name, location id, body). Headers are optional."""
    lines = text.splitlines()
    name, location = "", NOTE_LOCATION
    body_start = 0
    for i, line in enumerate(lines[:6]):
        stripped = line.strip()
        if not stripped or stripped == "---":
            body_start = i + 1
            break
        key, sep, value = stripped.partition(":")
        k = key.strip().lower()
        if sep and k in ("from", "name", "author", "visitor"):
            name = value.strip()
            body_start = i + 1
        elif sep and k in ("location", "at", "place", "where"):
            location = _location_from(value)
            body_start = i + 1
        else:
            break
    body = "\n".join(lines[body_start:]).strip()
    return sanitize_name(name), location, clean_text(body, MAX_BODY_CHARS)


class VisitorInbox:
    def __init__(self, paths, db, registry: VisitorRegistry, wall: Callable[[], float] = time.time) -> None:
        self.paths = paths
        self.db = db
        self.registry = registry
        self.wall = wall

    # -- helpers -----------------------------------------------------------
    def _archive_target(self, folder: Path, name: str) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "._- ")[:80] or "item"
        target = safe_child_path(folder, f"{stamp}_{safe}")
        n = 1
        while target.exists():
            n += 1
            target = safe_child_path(folder, f"{stamp}_{n}_{safe}")
        return target

    def _move(self, path: Path, folder: Path) -> Path:
        target = self._archive_target(folder, path.name)
        os.replace(path, target)
        return target

    def _settled(self, path: Path) -> bool:
        try:
            return (self.wall() - path.stat().st_mtime) >= SETTLE_SECONDS
        except OSError:
            return False

    def _process_image(self, data: bytes) -> tuple[bytes, str] | None:
        """Verify an image with Pillow and re-encode a safe, small PNG copy."""
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            return None
        try:
            with Image.open(io.BytesIO(data)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(data)) as img:
                if img.width * img.height > 40_000_000:
                    return None
                img = img.convert("RGB")
                img.thumbnail((512, 512))
                out = io.BytesIO()
                img.save(out, format="PNG", optimize=True)
                return out.getvalue(), "image/png"
        except Exception:  # noqa: BLE001 - anything malformed is rejected
            return None

    # -- main entry point --------------------------------------------------
    def scan(self, sim_minute: float) -> tuple[list[VisitorNote], list[str]]:
        """Process new files. Returns (new notes, rejected file names)."""
        new_notes: list[VisitorNote] = []
        rejected: list[str] = []
        try:
            entries = sorted(self.paths.inbox.iterdir(), key=lambda p: p.name)
        except FileNotFoundError:
            self.paths.inbox.mkdir(parents=True, exist_ok=True)
            return new_notes, rejected

        images = {p.stem.lower(): p for p in entries if p.is_file() and p.suffix.lower() in IMAGE_EXT}
        paired_images: set[Path] = set()

        for path in entries:
            if not path.is_file() or path.name.startswith((".", "~$")) or path.name.lower().endswith(IGNORED_SUFFIXES):
                continue
            if path.is_symlink():
                rejected.append(path.name)
                self._move(path, self.paths.rejected)
                continue
            if not self._settled(path):
                continue
            suffix = path.suffix.lower()
            if suffix not in TEXT_EXT and suffix not in IMAGE_EXT:
                # Never opened, never executed.
                rejected.append(path.name)
                self._move(path, self.paths.rejected)
                log.info("Rejected unrecognised visitor file type: %s", path.name)
                continue
            if suffix in IMAGE_EXT and path in paired_images:
                continue
            if suffix in IMAGE_EXT and path.stem.lower() in {p.stem.lower() for p in entries if p.suffix.lower() in TEXT_EXT}:
                continue  # handled with its text note
            try:
                note = self._process_file(path, images, paired_images, sim_minute)
            except Exception:  # noqa: BLE001 - one bad file must not stop the inbox
                log.exception("Failed to process visitor file %s", path.name)
                if path.exists():
                    rejected.append(path.name)
                    self._move(path, self.paths.rejected)
                continue
            if note is None:
                rejected.append(path.name)
            elif note.id > 0:
                new_notes.append(note)
        return new_notes, rejected

    def _process_file(self, path: Path, images: dict[str, Path], paired: set[Path], sim_minute: float) -> VisitorNote | None:
        suffix = path.suffix.lower()
        size = path.stat().st_size
        limit = MAX_TEXT_BYTES if suffix in TEXT_EXT else MAX_IMAGE_BYTES
        if size > limit:
            self._move(path, self.paths.rejected)
            return None
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if self.db.query_one("SELECT id FROM visitor_notes WHERE file_hash=?", (digest,)):
            self._move(path, self.paths.archive)  # duplicate (e.g. after a crash mid-move)
            return VisitorNote(0, "", "", "", "", None, path.name)

        image_rel = None
        if suffix in TEXT_EXT:
            text = raw.decode("utf-8-sig", errors="replace")
            name, location, body = parse_note(text)
            partner = images.get(path.stem.lower())
            if partner is not None and partner.stat().st_size <= MAX_IMAGE_BYTES:
                image_rel = self._store_image(partner.read_bytes(), partner.name)
                paired.add(partner)
                self._move(partner, self.paths.archive)
            if not body and image_rel is None:
                self._move(path, self.paths.rejected)
                return None
        else:
            name, location, body = "", NOTE_LOCATION, ""
            image_rel = self._store_image(raw, path.name)
            if image_rel is None:
                self._move(path, self.paths.rejected)
                return None

        display = name or ANONYMOUS
        key = visitor_key(display) if name else "anonymous"
        with self.db.transaction():
            cur = self.db.execute(
                "INSERT INTO visitor_notes(received_at, sim_minute, file_hash, original_name, visitor, location, body, image_path) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (self.wall(), sim_minute, digest, clean_text(path.name, 120), key, location, body, image_rel),
            )
            note_id = cur.lastrowid
            self.registry.register_note(display if name else "Anonymous", location)
        self._move(path, self.paths.archive)
        return VisitorNote(note_id, key, display, location, body, image_rel, path.name)

    def _store_image(self, data: bytes, original: str) -> str | None:
        processed = self._process_image(data)
        if processed is None:
            return None
        png, _ = processed
        target = self._archive_target(self.paths.archive, Path(original).stem + "-kimi.png")
        target.write_bytes(png)
        return str(target.relative_to(self.paths.root.resolve()))

    def unread(self, limit: int = 5) -> list[dict]:
        rows = self.db.query(
            "SELECT n.*, v.display_name FROM visitor_notes n LEFT JOIN visitors v ON v.key=n.visitor "
            "WHERE read_at IS NULL ORDER BY id LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def get(self, note_id: int) -> dict:
        row = self.db.query_one(
            "SELECT n.*, v.display_name FROM visitor_notes n LEFT JOIN visitors v ON v.key=n.visitor WHERE n.id=?",
            (note_id,),
        )
        if row is None:
            raise KeyError(note_id)
        return dict(row)

    def mark_read(self, note_id: int, reply: str | None) -> None:
        self.db.execute("UPDATE visitor_notes SET read_at=?, kimi_reply=? WHERE id=?", (self.wall(), reply, note_id))

    def set_image_description(self, note_id: int, description: str) -> None:
        self.db.execute("UPDATE visitor_notes SET image_description=? WHERE id=?", (clean_text(description, 400), note_id))
