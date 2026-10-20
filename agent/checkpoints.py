"""
Checkpoints: per-turn snapshots of files before the agent changes them.

Each agent turn (one user request) gets a checkpoint. Before an edit tool
touches a file for the first time in that turn, its original bytes are
copied into .deimos/checkpoints/<id>/ (or it's recorded as "didn't exist").
/undo restores the most recent checkpoint: changed files get their original
content back and files the agent created are deleted.

Only changes made through edit tools are tracked; side effects of shell
commands (run_command) are not.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field

CHECKPOINT_DIR_NAME = os.path.join(".deimos", "checkpoints")
KEEP_CHECKPOINTS = 20
MANIFEST = "manifest.json"


@dataclass
class Checkpoint:
    id: str
    label: str
    created_at: float
    files: dict[str, dict] = field(default_factory=dict)  # abs path -> {"existed", "backup"}

    @property
    def paths(self) -> list[str]:
        return sorted(self.files)


@dataclass
class UndoResult:
    checkpoint: Checkpoint
    restored: list[str]
    deleted: list[str]
    failed: list[str]


class CheckpointStore:
    def __init__(self, cwd: str | None = None):
        self.root = os.path.abspath(os.path.join(cwd or os.getcwd(), CHECKPOINT_DIR_NAME))
        self._current: Checkpoint | None = None
        self._last_ns = 0
        self._lock = threading.Lock()  # sub-agents snapshot from several threads

    # ── Recording ────────────────────────────────────────────────────────────

    def begin(self, label: str):
        """Start a new checkpoint for the next agent turn (created lazily on first snapshot)."""
        self._current = Checkpoint(id=self._next_id(), label=" ".join(label.split())[:100], created_at=time.time())

    def _next_id(self) -> str:
        """Sortable, strictly increasing id: local time plus nanoseconds within the second."""
        ns = time.time_ns()
        if ns <= self._last_ns:  # coarse clocks can repeat a reading
            ns = self._last_ns + 1
        self._last_ns = ns
        return time.strftime("%Y%m%d-%H%M%S", time.localtime(ns // 1_000_000_000)) + f"-{ns % 1_000_000_000:09d}"

    def snapshot(self, paths: list[str]):
        """Record the current state of each path, once per checkpoint."""
        with self._lock:
            self._snapshot(paths)

    def _snapshot(self, paths: list[str]):
        if self._current is None:
            self.begin("(untitled)")
        cp = self._current
        for path in paths:
            key = os.path.abspath(path)
            if key in cp.files:
                continue
            entry = {"existed": os.path.isfile(key), "backup": None}
            if entry["existed"]:
                backup = f"{len(cp.files):04d}-{os.path.basename(key)}"
                os.makedirs(self._dir(cp.id), exist_ok=True)
                shutil.copy2(key, os.path.join(self._dir(cp.id), backup))
                entry["backup"] = backup
            cp.files[key] = entry
            self._write_manifest(cp)
        self._prune()

    # ── Listing and undo ─────────────────────────────────────────────────────

    def list(self) -> list[Checkpoint]:
        """Checkpoints that changed files, newest first."""
        if not os.path.isdir(self.root):
            return []
        found = []
        for name in sorted(os.listdir(self.root), reverse=True):
            cp = self._read_manifest(name)
            if cp and cp.files:
                found.append(cp)
        return found

    def undo(self) -> UndoResult | None:
        """Restore the newest checkpoint and remove it. Returns None if there is nothing to undo."""
        checkpoints = self.list()
        if not checkpoints:
            return None
        cp = checkpoints[0]
        restored, deleted, failed = [], [], []
        for path, entry in cp.files.items():
            try:
                if entry["existed"]:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    shutil.copy2(os.path.join(self._dir(cp.id), entry["backup"]), path)
                    restored.append(path)
                elif os.path.exists(path):
                    os.remove(path)
                    deleted.append(path)
            except OSError:
                failed.append(path)
        if not failed:
            shutil.rmtree(self._dir(cp.id), ignore_errors=True)
        if self._current and self._current.id == cp.id:
            self._current = None
        return UndoResult(cp, sorted(restored), sorted(deleted), sorted(failed))

    # ── Storage ──────────────────────────────────────────────────────────────

    def _dir(self, checkpoint_id: str) -> str:
        return os.path.join(self.root, checkpoint_id)

    def _write_manifest(self, cp: Checkpoint):
        os.makedirs(self._dir(cp.id), exist_ok=True)
        with open(os.path.join(self._dir(cp.id), MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"id": cp.id, "label": cp.label, "created_at": cp.created_at, "files": cp.files}, f, indent=2)

    def _read_manifest(self, checkpoint_id: str) -> Checkpoint | None:
        try:
            with open(os.path.join(self._dir(checkpoint_id), MANIFEST), "r", encoding="utf-8") as f:
                data = json.load(f)
            return Checkpoint(data["id"], data.get("label", ""), data.get("created_at", 0), data.get("files", {}))
        except (OSError, ValueError, KeyError):
            return None

    def _prune(self):
        names = sorted(os.listdir(self.root)) if os.path.isdir(self.root) else []
        for old in names[:-KEEP_CHECKPOINTS]:
            shutil.rmtree(os.path.join(self.root, old), ignore_errors=True)
