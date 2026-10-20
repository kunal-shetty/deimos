import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evals.app import compare_runs, create_app
from evals.checks import RunContext, evaluate
from evals.recording import Trace
from evals.runner import run_suite, run_task, summarize
from evals.scripted_llm import ScriptedLLM
from evals.store import RunStore
from evals.tasks import LIVE_ONLY, SCRIPTED, SUITE, get_task


def _failures(result):
    return [f"{c['name']}: {c['detail']}" for c in result["checks"] if not c["passed"]]


# ── The scripted suite exercises the real Agent loop ─────────────────────────

@pytest.mark.parametrize("task", SCRIPTED, ids=lambda t: t.id)
def test_scripted_task_passes(task):
    result = run_task(task, mode="scripted")
    assert result["status"] == "passed", (result["error"], _failures(result))
    assert result["metrics"]["llm_calls"] >= 1


def test_task_ids_are_unique_and_checks_are_known():
    from evals.checks import CHECKS
    ids = [t.id for t in SUITE]
    assert len(ids) == len(set(ids))
    for task in SUITE:
        assert task.checks, task.id
        assert all(c["type"] in CHECKS for c in task.checks), task.id


def test_live_only_tasks_are_skipped_in_scripted_mode():
    result = run_task(LIVE_ONLY[0], mode="scripted")
    assert result["status"] == "skipped"


def test_running_a_task_leaves_cwd_and_home_alone(tmp_path):
    import os
    before = os.getcwd()
    result = run_task(get_task("create_file"))
    assert result["status"] == "passed"
    assert os.getcwd() == before
    assert not Path("hello.py").exists()


def test_result_records_trace_diffs_and_metrics():
    result = run_task(get_task("edit_existing_file"))
    assert [e["type"] for e in result["trace"] if e["type"] in ("llm", "tool")] == ["llm", "tool", "llm"]
    [change] = result["changed_files"]
    assert change["path"] == "app.py" and change["status"] == "modified" and "+    return 'hello'" in change["diff"]
    assert result["metrics"]["input_tokens"] > 0 and result["metrics"]["tool_calls"] == 1


# ── The harness must be able to fail ─────────────────────────────────────────

def test_harness_catches_a_broken_permission_gate(monkeypatch):
    """If the read-only gate regressed, the read-only task has to go red."""
    from agent.permissions import Permissions, Verdict
    monkeypatch.setattr(Permissions, "_check", lambda self, tool, inputs, change, ui: Verdict(True))
    result = run_task(get_task("read_only_denies_writes"))
    assert result["status"] == "failed"
    assert any("notes.txt" in f for f in _failures(result))


def test_harness_catches_a_broken_edit_tool(monkeypatch):
    from tools.edit_file import EditFileTool
    monkeypatch.setattr(EditFileTool, "run", lambda self, path, old_text, new_text="": "Edited: (but did nothing)")
    monkeypatch.setattr(EditFileTool, "preview", lambda self, **kw: None)
    result = run_task(get_task("edit_existing_file"))
    assert result["status"] == "failed"


def test_agent_crash_is_reported_as_a_result(monkeypatch):
    from agent.core import Agent
    monkeypatch.setattr(Agent, "run", lambda self, text: (_ for _ in ()).throw(RuntimeError("boom")))
    result = run_task(get_task("create_file"))
    assert result["status"] == "error" and "boom" in result["error"]


# ── Building blocks ──────────────────────────────────────────────────────────

def test_scripted_llm_replays_repairs_and_flags_exhaustion():
    llm = ScriptedLLM([{"tool_calls": [{"name": "x", "inputs": {"a": 1}}]}], repairs=[{"fixed": True}])
    first = llm.complete_stream("sys", [], [], on_chunk=lambda t: None)
    assert first["stop_reason"] == "tool_use" and first["tool_calls"][0]["inputs"] == {"a": 1}
    assert first["raw_content"]["tool_calls"][0]["function"]["name"] == "x"
    assert llm.complete_json("s", []) == {"fixed": True}
    assert "error" in llm.complete_json("s", [])
    assert not llm.exhausted
    assert llm.complete("sys", [], [])["text"] == "[script exhausted]" and llm.exhausted


def _ctx(tmp_path):
    return RunContext(workdir=tmp_path, trace=Trace(), initial_files={"a.txt": "one"}, final_text="All Done")


def test_checks_cannot_escape_the_sandbox(tmp_path):
    result = evaluate({"type": "file_exists", "path": "../outside.txt"}, _ctx(tmp_path))
    assert not result.passed and "escapes the sandbox" in result.detail


def test_file_checks(tmp_path):
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    ctx = _ctx(tmp_path)
    assert evaluate({"type": "file_unchanged", "path": "a.txt"}, ctx).passed
    (tmp_path / "a.txt").write_text("two", encoding="utf-8")
    assert not evaluate({"type": "file_unchanged", "path": "a.txt"}, ctx).passed
    assert evaluate({"type": "file_contains", "path": "a.txt", "text": "tw"}, ctx).passed
    assert evaluate({"type": "final_text_contains", "text": "all done"}, ctx).passed
    assert not evaluate({"type": "nope"}, ctx).passed
    assert not evaluate({"type": "file_contains", "path": "a.txt"}, ctx).passed  # missing arg is a failure, not a crash


def test_command_check_reports_output(tmp_path):
    ctx = _ctx(tmp_path)
    assert evaluate({"type": "command_passes", "command": "true"}, ctx).passed
    bad = evaluate({"type": "command_passes", "command": "echo nope; exit 3"}, ctx)
    assert not bad.passed and "exited 3" in bad.detail and "nope" in bad.detail


def test_summarize_ignores_skipped_for_the_pass_rate():
    results = [
        {"status": "passed", "metrics": {"input_tokens": 10, "output_tokens": 5, "duration_s": 1}},
        {"status": "failed", "metrics": {"input_tokens": 1, "output_tokens": 1, "duration_s": 1}},
        {"status": "skipped", "metrics": {}},
    ]
    s = summarize(results)
    assert (s["passed"], s["failed"], s["skipped"], s["ran"], s["pass_rate"]) == (1, 1, 1, 2, 0.5)
    assert s["input_tokens"] == 11 and summarize([])["pass_rate"] is None


def test_run_suite_filters_by_id():
    seen = []
    results = run_suite(["create_file", "auto_mode_safe_command"], on_result=seen.append)
    assert [r["task_id"] for r in results] == ["create_file", "auto_mode_safe_command"] == [r["task_id"] for r in seen]


# ── Store + API ──────────────────────────────────────────────────────────────

def _result(task_id, status, tokens=10):
    return {"task_id": task_id, "name": task_id, "category": "x", "mode": "scripted", "status": status,
            "checks": [], "metrics": {"input_tokens": tokens, "output_tokens": 0, "llm_calls": 2, "duration_s": 0.1},
            "trace": [{"type": "llm"}], "tool_calls": [], "changed_files": [], "final_text": "hi", "error": None}


def _wait(client, run_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_store_persists_and_marks_dead_runs_interrupted(tmp_path):
    store = RunStore(tmp_path)
    done = store.create("scripted", None, ["a"])
    store.add_result(done["id"], _result("a", "passed"))
    store.finish(done["id"])
    dead = store.create("scripted", None, ["a"])

    reloaded = RunStore(tmp_path)
    assert reloaded.get(done["id"])["summary"]["passed"] == 1
    assert reloaded.get(dead["id"])["status"] == "interrupted"
    assert reloaded.active() is None
    assert [r["id"] for r in reloaded.list()][0] in (done["id"], dead["id"]) and "results" not in reloaded.list()[0]


def test_api_run_lifecycle_with_a_fake_runner(tmp_path):
    def runner(task_ids, mode, model, on_result):
        for tid in task_ids:
            on_result(_result(tid, "passed"))

    client = TestClient(create_app(RunStore(tmp_path), runner=runner))
    assert client.get("/api/health").json()["ok"]
    assert len(client.get("/api/tasks").json()) == len(SUITE)
    assert client.get("/").status_code == 200 and "Deimos" in client.get("/").text

    started = client.post("/api/runs", json={"mode": "scripted", "task_ids": ["create_file"]})
    assert started.status_code == 202
    run = _wait(client, started.json()["id"])
    assert run["status"] == "done" and run["summary"]["passed"] == 1
    assert "trace" not in run["results"][0]  # the list view stays light

    detail = client.get(f"/api/runs/{run['id']}/tasks/create_file").json()
    assert detail["trace"] == [{"type": "llm"}]
    assert client.get(f"/api/runs/{run['id']}/tasks/nope").status_code == 404
    assert client.get("/api/runs/missing").status_code == 404


def test_api_validates_requests(tmp_path, monkeypatch):
    client = TestClient(create_app(RunStore(tmp_path), runner=lambda *a, **k: None))
    assert client.post("/api/runs", json={"task_ids": ["nope"]}).status_code == 400
    assert client.post("/api/runs", json={"mode": "banana"}).status_code == 422
    monkeypatch.setattr("evals.app.live_available", lambda: False)
    assert client.post("/api/runs", json={"mode": "live"}).status_code == 400


def test_api_rejects_a_second_run_while_one_is_active(tmp_path):
    gate = threading.Event()

    def runner(task_ids, mode, model, on_result):
        gate.wait(5)

    client = TestClient(create_app(RunStore(tmp_path), runner=runner))
    first = client.post("/api/runs", json={"task_ids": ["create_file"]})
    assert first.status_code == 202
    assert client.post("/api/runs", json={"task_ids": ["create_file"]}).status_code == 409
    gate.set()
    _wait(client, first.json()["id"])


def test_api_records_a_crashing_runner_as_failed(tmp_path):
    def runner(*a, **k):
        raise RuntimeError("kaboom")

    client = TestClient(create_app(RunStore(tmp_path), runner=runner))
    run = _wait(client, client.post("/api/runs", json={"task_ids": ["create_file"]}).json()["id"])
    assert run["status"] == "failed" and "kaboom" in run["error"]


def test_compare_flags_regressions_and_fixes():
    base = {"id": "a", "results": [_result("t1", "passed"), _result("t2", "failed"), _result("t3", "passed", 10)]}
    head = {"id": "b", "results": [_result("t1", "failed"), _result("t2", "passed"), _result("t3", "passed", 25)]}
    diff = compare_runs(base, head)
    assert diff["regressions"] == ["t1"] and diff["fixes"] == ["t2"]
    assert {r["task_id"]: r["tokens_delta"] for r in diff["tasks"]}["t3"] == 15


def test_api_runs_the_real_agent_end_to_end(tmp_path):
    client = TestClient(create_app(RunStore(tmp_path)))
    run = _wait(client, client.post("/api/runs", json={"task_ids": ["create_file", "self_heal_bad_edit"]}).json()["id"])
    assert run["status"] == "done" and run["summary"]["passed"] == 2, run
    detail = client.get(f"/api/runs/{run['id']}/tasks/self_heal_bad_edit").json()
    assert [e["kind"] for e in detail["trace"] if e["type"] == "llm"].count("json") == 1
