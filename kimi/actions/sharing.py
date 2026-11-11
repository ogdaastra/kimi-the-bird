"""Approval-gated sharing of creations.

Kimi may *prepare* things to share; it can never send or publish them.
Every outgoing action waits in the outbox until the user explicitly
approves it in the Activity screen:

* Email: approval opens a pre-filled draft in the user's own mail program.
  Kimi has no email credentials and cannot send anything itself.
* GitHub (optional): creations are copied into a local Git repository and
  committed locally; ``git push`` runs only when the user clicks approve.
  Kimi never handles GitHub tokens: pushing uses Git's own credential
  manager (on Windows, Git Credential Manager stores tokens in Windows
  Credential Manager).

Only files from Kimi's creations folder can be shared. Visitor notes,
memories and the diary are never copied into the repository.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from ..safety import SafetyViolation, safe_child_path, sanitize_output

_GITHUB_URL = re.compile(
    r"^(https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+?(\.git)?|git@github\.com:[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+?\.git)$"
)


class Outbox:
    def __init__(self, db, wall: Callable[[], float] = time.time) -> None:
        self.db = db
        self.wall = wall

    def draft(self, kind: str, title: str, body: str, payload: dict | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO outbox(created_at, kind, title, body, payload, status) VALUES(?,?,?,?,?, 'pending')",
            (self.wall(), kind, sanitize_output(title, 120), sanitize_output(body, 6000), json.dumps(payload or {})),
        )
        return cur.lastrowid

    def get(self, item_id: int) -> dict:
        row = self.db.query_one("SELECT * FROM outbox WHERE id=?", (item_id,))
        if row is None:
            raise KeyError(item_id)
        d = dict(row)
        d["payload"] = json.loads(d["payload"] or "{}")
        return d

    def pending(self) -> list[dict]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM outbox WHERE status='pending' ORDER BY id")]

    def recent(self, limit: int = 30) -> list[dict]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM outbox ORDER BY id DESC LIMIT ?", (limit,))]

    def mark(self, item_id: int, status: str, result: str = "") -> None:
        self.db.execute("UPDATE outbox SET status=?, decided_at=?, result=? WHERE id=?",
                        (status, self.wall(), sanitize_output(result, 1000), item_id))


def mailto_url(subject: str, body: str, to: str = "") -> str:
    """A mailto: link the user's own mail program opens as an unsent draft."""
    return f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body[:1800])}"


def valid_github_remote(url: str) -> bool:
    return bool(_GITHUB_URL.match(url.strip()))


class ProjectsRepo:
    def __init__(self, root: Path, creations_root: Path) -> None:
        self.root = root
        self.creations_root = creations_root

    @staticmethod
    def git_available() -> bool:
        return shutil.which("git") is not None

    def _git(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        # Fixed argument lists only; never a shell, never model-provided text as arguments.
        return subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=timeout,
            shell=False, check=False,
        )

    def ensure_repo(self) -> None:
        if not self.git_available():
            raise RuntimeError("Git is not installed, so GitHub sharing is unavailable.")
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git("init")
            (self.root / "README.md").write_text(
                "# Kimi's creations\n\nDrawings, stories and poems made by Kimi, a small autonomous digital bird.\n",
                encoding="utf-8",
            )
            self._git("add", "README.md")
            self._git("-c", "user.name=Kimi", "-c", "user.email=kimi@localhost", "commit", "-m", "Start Kimi's portfolio")

    def add_creation(self, creation_file: Path, title: str) -> str:
        """Copy a creation into the repo and commit locally. Returns the commit summary."""
        source = creation_file.resolve()
        creations_root = self.creations_root.resolve()
        if creations_root not in source.parents:
            raise SafetyViolation("Only Kimi's own creations can be shared")
        self.ensure_repo()
        rel = source.relative_to(creations_root)
        target = safe_child_path(self.root, "creations", *rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self._git("add", str(target.relative_to(self.root.resolve())))
        message = f"Add {re.sub(r'[^A-Za-z0-9 ,.!?-]', '', title)[:60] or 'a creation'}"
        result = self._git("-c", "user.name=Kimi", "-c", "user.email=kimi@localhost", "commit", "-m", message)
        return (result.stdout or result.stderr).strip()[:300]

    def push(self, remote_url: str) -> tuple[bool, str]:
        """Push local commits. Only ever called after explicit user approval."""
        if not valid_github_remote(remote_url):
            return False, "The GitHub remote URL in Settings doesn't look like a GitHub repository URL."
        self.ensure_repo()
        result = self._git("push", remote_url.strip(), "HEAD", timeout=180)
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output[-600:]
