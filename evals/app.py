"""
FastAPI service for the eval harness.

    python -m evals serve            ->  http://127.0.0.1:8421

    GET  /api/health                    live-mode availability, active run
    GET  /api/tasks                     the task catalogue
    POST /api/runs                      start a run {mode, task_ids?, model?}
    GET  /api/runs                      past runs (newest first)
    GET  /api/runs/{id}                 one run with per-task results
    GET  /api/runs/{id}/tasks/{task}    full detail: checks, trace, diffs
    GET  /api/compare?base=&head=       what changed between two runs
"""

from __future__ import annotations

import threading
import traceback
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from evals.runner import live_available, run_suite
from evals.store import RunStore
from evals.tasks import SUITE

HEAVY_FIELDS = ("trace", "tool_calls", "changed_files", "final_text")


class RunRequest(BaseModel):
    mode: Literal["scripted", "live"] = "scripted"
    task_ids: list[str] | None = None
    model: str | None = None


def _light(result: dict) -> dict:
    return {k: v for k, v in result.items() if k not in HEAVY_FIELDS}


def compare_runs(base: dict, head: dict) -> dict:
    """Per-task differences between two runs, so regressions stand out."""
    base_by_id = {r["task_id"]: r for r in base["results"]}
    head_by_id = {r["task_id"]: r for r in head["results"]}
    rows, regressions, fixes = [], [], []
    for task_id in sorted(set(base_by_id) | set(head_by_id)):
        b, h = base_by_id.get(task_id), head_by_id.get(task_id)
        b_status, h_status = (b or {}).get("status"), (h or {}).get("status")
        row = {
            "task_id": task_id, "base": b_status, "head": h_status,
            "tokens_delta": _tokens(h) - _tokens(b) if b and h else None,
            "llm_calls_delta": _metric(h, "llm_calls") - _metric(b, "llm_calls") if b and h else None,
        }
        rows.append(row)
        if b_status == "passed" and h_status in ("failed", "error"):
            regressions.append(task_id)
        elif b_status in ("failed", "error") and h_status == "passed":
            fixes.append(task_id)
    return {"base": base["id"], "head": head["id"], "regressions": regressions, "fixes": fixes, "tasks": rows}


def _metric(result: dict | None, key: str) -> int:
    return int(((result or {}).get("metrics") or {}).get(key) or 0)


def _tokens(result: dict | None) -> int:
    return _metric(result, "input_tokens") + _metric(result, "output_tokens")


def create_app(store: RunStore | None = None, runner=run_suite) -> FastAPI:
    """`runner` is injectable so tests can exercise the API without running agents."""
    store = store or RunStore()
    app = FastAPI(title="Deimos Evals")

    def execute(run_id: str, request: RunRequest, task_ids: list[str]):
        try:
            runner(task_ids, mode=request.mode, model=request.model,
                   on_result=lambda result: store.add_result(run_id, result))
            store.finish(run_id)
        except Exception as e:
            store.finish(run_id, error=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")

    @app.get("/api/health")
    def health():
        active = store.active()
        return {"ok": True, "live_available": live_available(), "active_run": active["id"] if active else None}

    @app.get("/api/tasks")
    def tasks():
        return [t.public() for t in SUITE]

    @app.post("/api/runs", status_code=202)
    def start_run(request: RunRequest):
        known = {t.id for t in SUITE}
        unknown = sorted(set(request.task_ids or []) - known)
        if unknown:
            raise HTTPException(400, f"unknown task ids: {', '.join(unknown)}")
        if request.mode == "live" and not live_available():
            raise HTTPException(400, "live mode needs GROQ_API_KEY to be set")
        task_ids = request.task_ids or [t.id for t in SUITE if request.mode == "live" or t.scripted]
        active = store.active()
        if active:
            raise HTTPException(409, f"run {active['id']} is still in progress")
        run = store.create(request.mode, request.model, task_ids)
        threading.Thread(target=execute, args=(run["id"], request, task_ids), daemon=True).start()
        return {"id": run["id"], "status": run["status"]}

    @app.get("/api/runs")
    def list_runs():
        return store.list()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run = store.get(run_id)
        if run is None:
            raise HTTPException(404, "no such run")
        return {**run, "results": [_light(r) for r in run["results"]]}

    @app.get("/api/runs/{run_id}/tasks/{task_id}")
    def get_task_result(run_id: str, task_id: str):
        run = store.get(run_id)
        if run is None:
            raise HTTPException(404, "no such run")
        for result in run["results"]:
            if result["task_id"] == task_id:
                return result
        raise HTTPException(404, "no such task in this run")

    @app.get("/api/compare")
    def compare(base: str, head: str):
        a, b = store.get(base), store.get(head)
        if a is None or b is None:
            raise HTTPException(404, "no such run")
        return compare_runs(a, b)

    @app.get("/", response_class=HTMLResponse)
    def home():
        return DASHBOARD_HTML

    return app


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Deimos Evals</title>
<style>
  :root { --bg:#0f172a; --panel:#1e293b; --line:#334155; --text:#e2e8f0; --dim:#94a3b8;
          --ok:#34d399; --bad:#f87171; --warn:#fbbf24; --accent:#38bdf8; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:14px/1.5 system-ui,sans-serif; }
  code,pre,.mono { font-family:ui-monospace,Menlo,Consolas,monospace; }
  header { display:flex; gap:12px; align-items:center; padding:14px 24px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
  header h1 { font-size:18px; margin:0 auto 0 0; } header h1 span { color:var(--accent); }
  button { background:var(--panel); color:var(--text); border:1px solid var(--line); padding:7px 14px; border-radius:8px; cursor:pointer; font:inherit; }
  button:hover:not(:disabled) { border-color:var(--accent); } button:disabled { opacity:.45; cursor:not-allowed; }
  button.primary { background:var(--accent); color:#04263a; border-color:var(--accent); font-weight:600; }
  main { display:grid; grid-template-columns:280px 1fr; min-height:calc(100vh - 62px); }
  @media (max-width:800px) { main { grid-template-columns:1fr; } }
  aside { border-right:1px solid var(--line); padding:14px; overflow:auto; }
  section { padding:20px 24px; overflow:auto; min-width:0; }
  .run { padding:10px 12px; border:1px solid var(--line); border-radius:10px; margin-bottom:8px; cursor:pointer; background:var(--panel); }
  .run.sel { border-color:var(--accent); } .run small { color:var(--dim); display:block; }
  .pill { display:inline-block; padding:1px 9px; border-radius:99px; font-size:11px; font-weight:700; text-transform:uppercase; }
  .passed,.done { background:#064e3b; color:var(--ok); } .failed,.error { background:#7f1d1d; color:var(--bad); }
  .skipped,.interrupted { background:#334155; color:var(--dim); } .running { background:#78350f; color:var(--warn); }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; margin-bottom:18px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
  .card b { display:block; font-size:20px; } .card span { color:var(--dim); font-size:12px; }
  table { width:100%; border-collapse:collapse; } th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--dim); font-weight:600; font-size:12px; } tr.task { cursor:pointer; } tr.task:hover { background:#1e293b80; }
  .detail { background:#0b1220; padding:14px 18px; }
  .detail h4 { margin:14px 0 6px; font-size:12px; color:var(--dim); text-transform:uppercase; letter-spacing:.05em; }
  .check { padding:3px 0; } .check.ok::before { content:"\\2713 "; color:var(--ok); } .check.no::before { content:"\\2717 "; color:var(--bad); }
  .check small { display:block; color:var(--bad); white-space:pre-wrap; margin-left:18px; }
  .ev { border-left:3px solid var(--line); padding:4px 10px; margin:4px 0; white-space:pre-wrap; word-break:break-word; }
  .ev.llm { border-color:var(--accent); } .ev.tool { border-color:var(--ok); } .ev.tool.bad { border-color:var(--bad); }
  .ev.permission { border-color:var(--warn); } .ev.error,.ev.crash,.ev.harness_error { border-color:var(--bad); }
  .ev .t { color:var(--dim); font-size:11px; } pre { background:#020617; padding:10px; border-radius:8px; overflow:auto; margin:6px 0; }
  .add { color:var(--ok); } .del { color:var(--bad); } .muted { color:var(--dim); }
  .banner { padding:10px 14px; border-radius:10px; margin-bottom:14px; background:#7f1d1d55; border:1px solid var(--bad); }
  select { background:var(--panel); color:var(--text); border:1px solid var(--line); padding:6px 8px; border-radius:8px; }
</style>
</head>
<body>
<header>
  <h1>Deimos <span>Evals</span></h1>
  <button id="run-scripted" class="primary">Run scripted suite</button>
  <button id="run-live" title="Needs GROQ_API_KEY">Run live suite</button>
</header>
<main>
  <aside><div id="runs"></div></aside>
  <section><div id="content"><p class="muted">Select a run, or start one.</p></div></section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let selected = null, openTask = null, timer = null, runsCache = [];

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}
const fmtTime = (t) => t ? new Date(t * 1000).toLocaleString() : "";
const pct = (s) => s.pass_rate == null ? "n/a" : Math.round(s.pass_rate * 100) + "%";

async function loadRuns() {
  runsCache = await api("/api/runs");
  $("runs").innerHTML = runsCache.map((r) => `
    <div class="run ${r.id === selected ? "sel" : ""}" data-id="${esc(r.id)}">
      <span class="pill ${esc(r.status)}">${esc(r.status)}</span> <b>${esc(r.mode)}</b>
      <small>${esc(fmtTime(r.created_at))}</small>
      <small>${r.summary.passed}/${r.summary.ran} passed &middot; ${esc(r.id)}</small>
    </div>`).join("") || '<p class="muted">No runs yet.</p>';
  document.querySelectorAll(".run").forEach((el) => el.onclick = () => select(el.dataset.id));
}

async function select(id) {
  selected = id; openTask = null; await render(); await loadRuns();
}

async function render() {
  if (!selected) return;
  clearTimeout(timer);
  const run = await api("/api/runs/" + encodeURIComponent(selected));
  const s = run.summary;
  const others = runsCache.filter((r) => r.id !== run.id && r.status !== "running");
  let html = "";
  if (run.error) html += `<div class="banner"><b>Run failed</b><pre>${esc(run.error)}</pre></div>`;
  html += `<div class="cards">
    <div class="card"><b>${pct(s)}</b><span>pass rate (${s.passed}/${s.ran})</span></div>
    <div class="card"><b>${s.failed + s.errors}</b><span>failed or errored</span></div>
    <div class="card"><b>${s.skipped}</b><span>skipped</span></div>
    <div class="card"><b>${(s.input_tokens + s.output_tokens).toLocaleString()}</b><span>tokens</span></div>
    <div class="card"><b>${s.duration_s}s</b><span>agent time</span></div>
  </div>
  <p>Compare with: <select id="cmp"><option value="">(none)</option>${others.map((r) => `<option value="${esc(r.id)}">${esc(r.mode)} &middot; ${esc(fmtTime(r.created_at))}</option>`).join("")}</select></p>
  <div id="cmp-out"></div>
  <table><thead><tr><th>Status</th><th>Task</th><th>Category</th><th>Checks</th><th>Model calls</th><th>Tools</th><th>Tokens</th><th>Time</th></tr></thead><tbody>`;
  for (const r of run.results) {
    const m = r.metrics || {}, ok = r.checks.filter((c) => c.passed).length;
    html += `<tr class="task" data-task="${esc(r.task_id)}">
      <td><span class="pill ${esc(r.status)}">${esc(r.status)}</span></td><td>${esc(r.name)}</td><td class="muted">${esc(r.category)}</td>
      <td>${ok}/${r.checks.length}</td><td>${m.llm_calls ?? ""}</td><td>${m.tool_calls ?? ""}</td>
      <td>${((m.input_tokens || 0) + (m.output_tokens || 0)).toLocaleString()}</td><td>${m.duration_s ?? ""}s</td></tr>
      <tr class="drow ${openTask === r.task_id ? "" : "hidden"}" data-for="${esc(r.task_id)}" style="${openTask === r.task_id ? "" : "display:none"}"><td colspan="8"><div class="detail">loading&hellip;</div></td></tr>`;
  }
  $("content").innerHTML = html + "</tbody></table>";
  document.querySelectorAll("tr.task").forEach((tr) => tr.onclick = () => toggle(tr.dataset.task));
  $("cmp").onchange = (e) => compare(e.target.value);
  if (openTask) loadDetail(openTask);
  if (run.status === "running") timer = setTimeout(async () => { await loadRuns(); await render(); }, 1500);
}

async function compare(base) {
  const out = $("cmp-out");
  if (!base) { out.innerHTML = ""; return; }
  const c = await api(`/api/compare?base=${encodeURIComponent(base)}&head=${encodeURIComponent(selected)}`);
  out.innerHTML = `<div class="card" style="margin-bottom:14px">
    <b class="${c.regressions.length ? "del" : "add"}">${c.regressions.length} regression(s), ${c.fixes.length} fixed</b>
    <span>${c.regressions.length ? "Regressed: " + c.regressions.map(esc).join(", ") : "No task that passed before fails now."}
    ${c.fixes.length ? "<br>Fixed: " + c.fixes.map(esc).join(", ") : ""}</span></div>`;
}

function toggle(taskId) {
  openTask = openTask === taskId ? null : taskId;
  document.querySelectorAll("tr.drow").forEach((tr) => tr.style.display = tr.dataset.for === openTask ? "" : "none");
  if (openTask) loadDetail(openTask);
}

function diffHtml(d) {
  return esc(d).split("\\n").map((l) => l.startsWith("+") && !l.startsWith("+++") ? `<span class="add">${l}</span>`
    : l.startsWith("-") && !l.startsWith("---") ? `<span class="del">${l}</span>` : l).join("\\n");
}

function eventHtml(e) {
  const t = `<span class="t">${e.t_ms}ms</span> `;
  if (e.type === "llm") return `<div class="ev llm">${t}<b>model ${esc(e.kind)}</b> &middot; ${e.input_tokens}\\u2192${e.output_tokens} tokens &middot; ${e.latency_ms}ms${e.tool_calls && e.tool_calls.length ? " &middot; calls " + esc(e.tool_calls.join(", ")) : ""}${e.text ? "<br>" + esc(e.text) : ""}${e.error ? '<br><span class="del">' + esc(e.error) + "</span>" : ""}</div>`;
  if (e.type === "tool") return `<div class="ev tool ${e.ok ? "" : "bad"}">${t}<b>${esc(e.name)}</b> <code>${esc(JSON.stringify(e.inputs)).slice(0, 300)}</code> &middot; ${e.duration_ms}ms<br>${esc(e.result).slice(0, 600)}</div>`;
  if (e.type === "permission") return `<div class="ev permission">${t}<b>permission</b> ${esc(e.title)}${e.danger ? " (dangerous)" : ""} &rarr; ${esc(e.answer)}</div>`;
  if (e.type === "assistant") return `<div class="ev">${t}<b>assistant</b> ${esc(e.text)}</div>`;
  return `<div class="ev ${esc(e.type)}">${t}<b>${esc(e.type)}</b> ${esc(e.message || JSON.stringify(e.stats || ""))}</div>`;
}

async function loadDetail(taskId) {
  const box = document.querySelector(`tr.drow[data-for="${CSS.escape(taskId)}"] .detail`);
  if (!box) return;
  const r = await api(`/api/runs/${encodeURIComponent(selected)}/tasks/${encodeURIComponent(taskId)}`);
  const events = r.trace.filter((e) => e.type !== "turn_end");
  box.innerHTML = `
    ${r.error ? `<div class="banner">${esc(r.error)}</div>` : ""}
    <h4>Checks</h4>${r.checks.map((c) => `<div class="check ${c.passed ? "ok" : "no"}"><code>${esc(c.name)}</code>${c.passed ? "" : "<small>" + esc(c.detail) + "</small>"}</div>`).join("") || '<span class="muted">none</span>'}
    <h4>Final answer</h4><div>${esc(r.final_text) || '<span class="muted">(none)</span>'}</div>
    <h4>Trace</h4>${events.map(eventHtml).join("")}
    <h4>Files changed</h4>${r.changed_files.map((f) => `<div><b>${esc(f.path)}</b> <span class="pill ${f.status === "created" ? "passed" : "running"}">${esc(f.status)}</span><pre>${diffHtml(f.diff)}</pre></div>`).join("") || '<span class="muted">none</span>'}`;
}

async function start(mode) {
  try {
    const r = await api("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) });
    await loadRuns(); await select(r.id);
  } catch (e) { alert(e.message); }
}

$("run-scripted").onclick = () => start("scripted");
$("run-live").onclick = () => start("live");
api("/api/health").then((h) => { $("run-live").disabled = !h.live_available; $("run-live").title = h.live_available ? "" : "Set GROQ_API_KEY to enable"; });
loadRuns().then(() => { if (runsCache[0]) select(runsCache[0].id); });
</script>
</body>
</html>
"""
