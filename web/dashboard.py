"""
Local web dashboard for Deimos.

Run with: deimos dashboard
Then open http://127.0.0.1:8420 in a browser.

Now features real-time updates via WebSockets and a modern UI powered by Tailwind CSS.
"""

import os
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import DEIMOS_USER_ID, SUPABASE_URL, SUPABASE_KEY

app = FastAPI(title="Deimos Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket Management ──────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Endpoint for the agent to push updates to the dashboard
@app.post("/api/push")
async def push_update(update: dict):
    await manager.broadcast(update)
    return {"status": "ok"}

# ── API endpoints ────────────────────────────────────────────────────────────

def _get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

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

@app.get("/", response_class=HTMLResponse)
def dashboard_home():
    return DASHBOARD_HTML

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Deimos Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Fira+Code:wght@400;500&display=swap');
        body { font-family: 'Inter', sans-serif; background-color: #0f172a; color: #e2e8f0; }
        .mono { font-family: 'Fira Code', monospace; }
        .glass { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); }
        .tab-active { border-bottom: 2px solid #38bdf8; color: #38bdf8; }
        .scrollbar-hide::-webkit-scrollbar { display: none; }
    </style>
</head>
<body class="min-h-screen flex flex-col">
    <!-- Header -->
    <header class="glass sticky top-0 z-50 px-6 py-4 flex justify-between items-center border-b border-slate-700">
        <div class="flex items-center gap-3">
            <div class="w-8 h-8 bg-sky-500 rounded-lg flex items-center justify-center text-white font-bold">D</div>
            <h1 class="text-xl font-bold tracking-tight text-white">Deimos <span class="text-sky-400">Dashboard</span></h1>
        </div>
        <div id="status-pill" class="px-3 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700">
            Connecting...
        </div>
    </header>

    <div class="flex flex-1 overflow-hidden">
        <!-- Sidebar -->
        <nav class="w-64 glass border-r border-slate-700 flex flex-col p-4 gap-2">
            <button data-tab="conversations" class="tab-btn active flex items-center gap-3 px-3 py-2 rounded-md transition-all hover:bg-slate-800 text-slate-300 hover:text-white group">
                <i class="fa-solid fa-comments text-slate-500 group-hover:text-sky-400"></i> Conversations
            </button>
            <button data-tab="memory" class="tab-btn flex items-center gap-3 px-3 py-2 rounded-md transition-all hover:bg-slate-800 text-slate-300 hover:text-white group">
                <i class="fa-solid fa-brain text-slate-500 group-hover:text-sky-400"></i> Semantic Memory
            </button>
            <button data-tab="projects" class="tab-btn flex items-center gap-3 px-3 py-2 rounded-md transition-all hover:bg-slate-800 text-slate-300 hover:text-white group">
                <i class="fa-solid fa-folder-open text-slate-500 group-hover:text-sky-400"></i> Projects
            </button>
            <button data-tab="plans" class="tab-btn flex items-center gap-3 px-3 py-2 rounded-md transition-all hover:bg-slate-800 text-slate-300 hover:text-white group">
                <i class="fa-solid fa-list-check text-slate-500 group-hover:text-sky-400"></i> Workflows
            </button>
            <div class="mt-auto pt-4 border-t border-slate-700">
                <div id="cwd-display" class="text-[10px] text-slate-500 mono truncate px-2">Loading directory...</div>
            </div>
        </nav>

        <!-- Main Content -->
        <main class="flex-1 overflow-y-auto p-6 bg-slate-900/50 scrollbar-hide">
            <div id="conversations" class="panel hidden space-y-4"></div>
            <div id="memory" class="panel hidden space-y-4"></div>
            <div id="projects" class="panel hidden space-y-4"></div>
            <div id="plans" class="panel hidden space-y-4"></div>

            <!-- Real-time Feed Overlay -->
            <div id="live-feed" class="fixed bottom-6 right-6 w-96 glass rounded-xl shadow-2xl border border-sky-500/30 flex flex-col max-h-[400px] hidden">
                <div class="px-4 py-2 border-b border-slate-700 flex justify-between items-center bg-slate-800/50 rounded-t-xl">
                    <span class="text-xs font-bold text-sky-400 flex items-center gap-2">
                        <span class="relative flex h-2 w-2">
                            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                            <span class="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                        </span>
                        LIVE AGENT FEED
                    </span>
                    <button onclick="document.getElementById('live-feed').classList.add('hidden')" class="text-slate-500 hover:text-white">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
                <div id="feed-content" class="p-4 overflow-y-auto text-xs mono space-y-2 scrollbar-hide"></div>
            </div>
        </main>
    </div>

    <script>
        // --- State Management ---
        let currentTab = 'conversations';

        // --- WebSocket Connection ---
        const ws = new WebSocket(`ws://${window.location.host}/ws`);

        ws.onopen = () => {
            document.getElementById('status-pill').textContent = 'Connected';
            document.getElementById('status-pill').classList.replace('bg-slate-800', 'bg-sky-900/30');
            document.getElementById('status-pill').classList.replace('text-slate-400', 'text-sky-400');
        };

        ws.onclose = () => {
            document.getElementById('status-pill').textContent = 'Disconnected';
            document.getElementById('status-pill').classList.replace('bg-sky-900/30', 'bg-slate-800');
            document.getElementById('status-pill').classList.replace('text-sky-400', 'text-slate-400');
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleLiveUpdate(data);
        };

        function handleLiveUpdate(data) {
            const feed = document.getElementById('live-feed');
            const content = document.getElementById('feed-content');
            feed.classList.remove('hidden');

            const entry = document.createElement('div');
            entry.className = 'p-2 rounded bg-slate-800/50 border border-slate-700 animate-in slide-in-from-right-2 duration-200';

            let label = 'SYSTEM';
            let color = 'text-slate-400';

            if (data.type === 'thought') { label = 'THINK'; color = 'text-sky-400'; }
            else if (data.type === 'tool') { label = 'TOOL'; color = 'text-emerald-400'; }
            else if (data.type === 'result') { label = 'OBS'; color = 'text-amber-400'; }
            else if (data.type === 'workflow') { label = 'PLAN'; color = 'text-purple-400'; }

            entry.innerHTML = `
                <div class="flex justify-between items-center mb-1">
                    <span class="text-[10px] font-bold ${color}">${label}</span>
                    <span class="text-[9px] text-slate-600">${new Date().toLocaleTimeString()}</span>
                </div>
                <div class="text-slate-300">${data.message}</div>
            `;
            content.appendChild(entry);
            content.scrollTop = content.scrollHeight;
        }

        // --- UI Logic ---
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('bg-slate-800', 'text-white'));
                btn.classList.add('bg-slate-800', 'text-white');

                document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));
                const activePanel = document.getElementById(btn.dataset.tab);
                activePanel.classList.remove('hidden');
                currentTab = btn.dataset.tab;
                loadTabContent(currentTab);
            };
        });

        async function loadTabContent(tab) {
            const el = document.getElementById(tab);
            el.innerHTML = '<div class="flex justify-center p-12"><i class="fa-solid fa-circle-notch animate-spin text-sky-500 text-2xl"></i></div>';

            try {
                let endpoint = '';
                if (tab === 'conversations') endpoint = '/api/conversations';
                else if (tab === 'memory') endpoint = '/api/memory/facts';
                else if (tab === 'projects') endpoint = '/api/memory/projects';
                else if (tab === 'plans') endpoint = '/api/plans';

                const r = await fetch(endpoint);
                const data = await r.json();
                renderTab(tab, data);
            } catch (e) {
                el.innerHTML = `<div class="text-center p-12 text-red-400">Error loading data: ${e}</div>`;
            }
        }

        function renderTab(tab, data) {
            const el = document.getElementById(tab);
            if (!data || (Array.isArray(data) && data.length === 0)) {
                el.innerHTML = '<div class="text-center p-12 text-slate-500 italic">No data available.</div>';
                return;
            }

            if (tab === 'conversations') {
                el.innerHTML = data.map(c => `
                    <div class="glass p-4 rounded-xl flex justify-between items-center hover:border-sky-500/50 transition-colors cursor-pointer group">
                        <div>
                            <div class="font-semibold text-white group-hover:text-sky-400 transition-colors">${c.title || '(untitled)'}</div>
                            <div class="text-xs text-slate-500">${(c.started_at || '').slice(0,16).replace('T',' ')} · ${c.id}</div>
                        </div>
                        <i class="fa-solid fa-chevron-right text-slate-600 group-hover:text-sky-400 transition-all translate-x-0 group-hover:translate-x-1"></i>
                    </div>
                `).join('');
            } else if (tab === 'memory') {
                el.innerHTML = data.map(f => `
                    <div class="glass p-4 rounded-xl">
                        <div class="flex justify-between items-start mb-2">
                            <div class="font-bold text-sky-400 mono text-sm">${f.key}</div>
                            <div class="text-[10px] px-2 py-0.5 rounded bg-sky-900/30 text-sky-400 border border-sky-800">conf ${f.confidence}</div>
                        </div>
                        <div class="text-slate-300 text-sm">${f.value}</div>
                        <div class="mt-3 w-full bg-slate-800 h-1 rounded-full overflow-hidden">
                            <div class="bg-sky-500 h-full" style="width:${f.confidence*100}%"></div>
                        </div>
                    </div>
                `).join('');
            } else if (tab === 'projects') {
                const names = Object.keys(data);
                el.innerHTML = names.map(name => `
                    <div class="glass p-4 rounded-xl mb-4">
                        <div class="text-white font-bold mb-3 flex items-center gap-2">
                            <i class="fa-solid fa-folder text-sky-500"></i> ${name}
                        </div>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                            ${data[name].map(f => `
                                <div class="bg-slate-800/50 p-2 rounded border border-slate-700">
                                    <div class="text-[10px] text-slate-500 uppercase font-bold">${f.key}</div>
                                    <div class="text-sm text-slate-300">${f.value}</div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `).join('');
            } else if (tab === 'plans') {
                el.innerHTML = data.map(p => `
                    <div class="glass p-5 rounded-xl border-l-4 ${p.status === 'completed' ? 'border-l-emerald-500' : 'border-l-sky-500'}">
                        <div class="flex justify-between items-start mb-3">
                            <div>
                                <div class="text-white font-bold text-lg">${p.title}</div>
                                <div class="text-xs text-slate-500 mono">${p.id} · ${p.status}</div>
                            </div>
                            <div class="px-2 py-1 rounded text-[10px] font-bold uppercase ${p.status === 'completed' ? 'bg-emerald-900/30 text-emerald-400' : 'bg-sky-900/30 text-sky-400'}">
                                ${p.status}
                            </div>
                        </div>
                        <div class="text-sm text-slate-400 mb-4 italic">"${p.task}"</div>
                        <div class="space-y-2">
                            ${p.steps.map((s, i) => {
                                const isStepObj = typeof s === 'object';
                                const desc = isStepObj ? s.description : s;
                                const status = isStepObj ? s.status : 'pending';
                                const color = status === 'completed' ? 'text-emerald-400' : 'text-slate-500';
                                return `
                                    <div class="flex items-start gap-3 text-sm">
                                        <i class="fa-solid ${status === 'completed' ? 'fa-circle-check text-emerald-500' : 'fa-circle text-slate-700'} mt-1"></i>
                                        <span class="${status === 'completed' ? 'text-slate-400 line-through' : 'text-slate-300'}">${desc}</span>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                `).join('');
            }
        }

        async function loadStatus() {
            const r = await fetch('/api/status');
            const s = await r.json();
            document.getElementById('cwd-display').textContent = s.cwd;
        }

        // Init
        loadStatus();
        loadTabContent('conversations');
    </script>
</body>
</html>
"""
