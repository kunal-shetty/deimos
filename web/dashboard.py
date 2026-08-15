"""
Local web dashboard for Deimos.

Run with: deimos dashboard
Then open http://127.0.0.1:8420 in a browser.

Read-only views into:
  - Past conversations + episodic/semantic/project memory (from Supabase)
  - Plans created in the current project (.deimos/plans/)
  - Basic session usage stats (token/message counts, stored locally)

This is intentionally read-only and local-only (binds to 127.0.0.1) —
it's a debugging/inspection tool, not a remote API surface.
"""

import os
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import DEIMOS_USER_ID, SUPABASE_URL, SUPABASE_KEY

app = FastAPI(title="Deimos Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8420", "http://localhost:8420"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ── API endpoints ────────────────────────────────────────────────────────────

@app.get("/api/conversations")
def get_conversations(limit: int = 30):
    if not DEIMOS_USER_ID:
        raise HTTPException(status_code=503, detail="DEIMOS_USER_ID not configured")
    client = _get_supabase()
    result = (
        client.table("conversations")
        .select("id, title, started_at, ended_at")
        .eq("user_id", DEIMOS_USER_ID)
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


@app.get("/api/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str):
    client = _get_supabase()
    result = (
        client.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    return result.data


@app.get("/api/memory/facts")
def get_facts():
    if not DEIMOS_USER_ID:
        raise HTTPException(status_code=503, detail="DEIMOS_USER_ID not configured")
    client = _get_supabase()
    result = (
        client.table("semantic_memories")
        .select("key, value, confidence, frequency, last_updated")
        .eq("user_id", DEIMOS_USER_ID)
        .order("confidence", desc=True)
        .execute()
    )
    return result.data


@app.get("/api/memory/projects")
def get_project_facts():
    if not DEIMOS_USER_ID:
        raise HTTPException(status_code=503, detail="DEIMOS_USER_ID not configured")
    client = _get_supabase()
    result = (
        client.table("project_memories")
        .select("project_name, key, value, confidence, last_updated")
        .eq("user_id", DEIMOS_USER_ID)
        .order("project_name")
        .execute()
    )
    grouped: dict[str, list] = {}
    for row in result.data:
        grouped.setdefault(row["project_name"], []).append(row)
    return grouped


@app.get("/api/memory/episodic")
def get_episodic(limit: int = 10):
    if not DEIMOS_USER_ID:
        raise HTTPException(status_code=503, detail="DEIMOS_USER_ID not configured")
    client = _get_supabase()
    result = (
        client.table("episodic_memories")
        .select("summary, created_at")
        .eq("user_id", DEIMOS_USER_ID)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


@app.get("/api/plans")
def get_plans(project_dir: str = None):
    """List plans from .deimos/plans/ in the given directory (or cwd)."""
    base_dir = Path(project_dir or os.getcwd()) / ".deimos" / "plans"
    if not base_dir.is_dir():
        return []

    plans = []
    for fname in sorted(os.listdir(base_dir), reverse=True):
        if fname.endswith(".json"):
            try:
                with open(base_dir / fname, "r", encoding="utf-8") as f:
                    plans.append(json.load(f))
            except Exception:
                continue
    return plans


@app.get("/api/status")
def get_status():
    return {
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_KEY),
        "user_id_configured": bool(DEIMOS_USER_ID),
        "cwd": os.getcwd(),
    }


# ── Dashboard HTML ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard_home():
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Deimos Dashboard</title>
<style>
  :root {
    --bg: #0b0f14; --panel: #11161d; --border: #1e2730;
    --cyan: #5fd7ff; --cyan-dim: #5f87af; --text: #d6dde3; --grey: #6b7686;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg); color: var(--text); font-family: 'SF Mono', Menlo, Consolas, monospace;
    margin: 0; padding: 24px; font-size: 14px;
  }
  h1 { color: var(--cyan); font-size: 18px; margin-bottom: 4px; }
  .subtitle { color: var(--grey); margin-bottom: 24px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
  .tab {
    padding: 8px 16px; cursor: pointer; color: var(--grey); border-bottom: 2px solid transparent;
  }
  .tab.active { color: var(--cyan); border-bottom-color: var(--cyan); }
  .panel { display: none; }
  .panel.active { display: block; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 16px; margin-bottom: 12px;
  }
  .card-title { color: var(--cyan); font-weight: bold; margin-bottom: 6px; }
  .card-meta { color: var(--grey); font-size: 12px; margin-bottom: 8px; }
  .bar { background: var(--border); border-radius: 4px; height: 6px; overflow: hidden; margin-top: 4px; }
  .bar-fill { background: var(--cyan); height: 100%; }
  .empty { color: var(--grey); font-style: italic; padding: 20px; }
  pre { white-space: pre-wrap; color: var(--text); }
  .step { padding: 4px 0; color: var(--text); }
  .step-num { color: var(--cyan-dim); margin-right: 8px; }
</style>
</head>
<body>
  <h1>◆ Deimos Dashboard</h1>
  <div class="subtitle" id="subtitle">loading...</div>

  <div class="tabs">
    <div class="tab active" data-tab="conversations">Conversations</div>
    <div class="tab" data-tab="memory">Memory</div>
    <div class="tab" data-tab="projects">Projects</div>
    <div class="tab" data-tab="plans">Plans</div>
  </div>

  <div class="panel active" id="conversations"><div class="empty">Loading...</div></div>
  <div class="panel" id="memory"><div class="empty">Loading...</div></div>
  <div class="panel" id="projects"><div class="empty">Loading...</div></div>
  <div class="panel" id="plans"><div class="empty">Loading...</div></div>

<script>
document.querySelectorAll('.tab').forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.add('active');
  };
});

async function loadStatus() {
  const r = await fetch('/api/status');
  const s = await r.json();
  document.getElementById('subtitle').textContent =
    `${s.cwd}  ·  Supabase: ${s.supabase_configured ? 'connected' : 'not configured'}`;
}

async function loadConversations() {
  const el = document.getElementById('conversations');
  try {
    const r = await fetch('/api/conversations');
    const data = await r.json();
    if (!data.length) { el.innerHTML = '<div class="empty">No conversations yet.</div>'; return; }
    el.innerHTML = data.map(c => `
      <div class="card">
        <div class="card-title">${c.title || '(untitled)'}</div>
        <div class="card-meta">${(c.started_at || '').slice(0,16).replace('T',' ')} · ${c.id}</div>
      </div>
    `).join('');
  } catch (e) { el.innerHTML = `<div class="empty">Error: ${e}</div>`; }
}

async function loadMemory() {
  const el = document.getElementById('memory');
  try {
    const r = await fetch('/api/memory/facts');
    const data = await r.json();
    if (!data.length) { el.innerHTML = '<div class="empty">No facts stored yet.</div>'; return; }
    el.innerHTML = data.map(f => `
      <div class="card">
        <div class="card-title">${f.key}</div>
        <div>${f.value}</div>
        <div class="bar"><div class="bar-fill" style="width:${f.confidence*100}%"></div></div>
        <div class="card-meta">confidence ${f.confidence} · seen ${f.frequency}×</div>
      </div>
    `).join('');
  } catch (e) { el.innerHTML = `<div class="empty">Error: ${e}</div>`; }
}

async function loadProjects() {
  const el = document.getElementById('projects');
  try {
    const r = await fetch('/api/memory/projects');
    const data = await r.json();
    const names = Object.keys(data);
    if (!names.length) { el.innerHTML = '<div class="empty">No project memory yet.</div>'; return; }
    el.innerHTML = names.map(name => `
      <div class="card">
        <div class="card-title">${name}</div>
        ${data[name].map(f => `<div>${f.key}: ${f.value}</div>`).join('')}
      </div>
    `).join('');
  } catch (e) { el.innerHTML = `<div class="empty">Error: ${e}</div>`; }
}

async function loadPlans() {
  const el = document.getElementById('plans');
  try {
    const r = await fetch('/api/plans');
    const data = await r.json();
    if (!data.length) { el.innerHTML = '<div class="empty">No plans in this directory yet.</div>'; return; }
    el.innerHTML = data.map(p => `
      <div class="card">
        <div class="card-title">${p.title} <span class="card-meta">[${p.status}]</span></div>
        <div class="card-meta">${p.task}</div>
        ${p.steps.map((s, i) => `<div class="step"><span class="step-num">${i+1}.</span>${s}</div>`).join('')}
      </div>
    `).join('');
  } catch (e) { el.innerHTML = `<div class="empty">Error: ${e}</div>`; }
}

loadStatus();
loadConversations();
loadMemory();
loadProjects();
loadPlans();
</script>
</body>
</html>"""