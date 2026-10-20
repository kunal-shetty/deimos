"""Run persistence: JSON files on disk plus an in-memory index."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

from evals.runner import summarize

DEFAULT_DIR = Path(__file__).parent / "results"


class RunStore:
    def __init__(self, directory: str | Path | None = None):
        self.dir = Path(directory or os.getenv("EVAL_RESULTS_DIR") or DEFAULT_DIR)
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not self.dir.is_dir():
            return
        for path in self.dir.glob("*.json"):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(run, dict) and run.get("id"):
                if run.get("status") == "running":  # the process died mid-run
                    run["status"] = "interrupted"
                self._runs[run["id"]] = run

    def _save(self, run: dict):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / f".{run['id']}.tmp"
            tmp.write_text(json.dumps(run), encoding="utf-8")
            tmp.replace(self.dir / f"{run['id']}.json")
        except OSError:
            pass  # results stay in memory; a read-only disk shouldn't kill the run

    def create(self, mode: str, model: str | None, task_ids: list[str]) -> dict:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        run = {
            "id": run_id, "mode": mode, "model": model or ("scripted" if mode == "scripted" else None),
            "status": "running", "created_at": time.time(), "finished_at": None,
            "task_ids": task_ids, "results": [], "summary": summarize([]), "error": None,
        }
        with self._lock:
            self._runs[run_id] = run
            self._save(run)
        return run

    def add_result(self, run_id: str, result: dict):
        with self._lock:
            run = self._runs[run_id]
            run["results"].append(result)
            run["summary"] = summarize(run["results"])
            self._save(run)

    def finish(self, run_id: str, error: str | None = None):
        with self._lock:
            run = self._runs[run_id]
            run["status"] = "failed" if error else "done"
            run["error"] = error
            run["finished_at"] = time.time()
            self._save(run)

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> list[dict]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r["created_at"], reverse=True)
            return [{k: v for k, v in r.items() if k != "results"} for r in runs]

    def active(self) -> dict | None:
        with self._lock:
            return next((r for r in self._runs.values() if r["status"] == "running"), None)
