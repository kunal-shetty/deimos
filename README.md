```
██████╗ ███████╗██╗███╗   ███╗ ██████╗ ███████╗
██╔══██╗██╔════╝██║████╗ ████║██╔═══██╗██╔════╝
██║  ██║█████╗  ██║██╔████╔██║██║   ██║███████╗
██║  ██║██╔══╝  ██║██║╚██╔╝██║██║   ██║╚════██║
██████╔╝███████╗██║██║ ╚═╝ ██║╚██████╔╝███████║
╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝
```

> **An autonomous coding agent for your terminal — powered by Groq, with persistent multi-layer memory and structured workflow planning.**

---

## Getting Started

Deimos is a terminal-based AI agent that thinks, plans, and executes code changes in your workspace.

### 1. Install

You need Python 3.11 or newer. Then run one line:

**macOS, Linux, WSL**
```bash
curl -fsSL https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.sh | sh
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.ps1 | iex
```

The installer puts Deimos in its own environment under `~/.deimos` and adds a `deimos` command
to your PATH. Open a new terminal afterwards, then run `deimos` in any project folder.

### 2. Add your keys

The first run asks for your [Groq API key](https://console.groq.com/keys) and saves it to
`~/.deimos/.env`. Run `deimos setup` any time to add or change keys:

| Key | Needed for |
|---|---|
| `GROQ_API_KEY` | Required: the model behind Deimos |
| `TAVILY_API_KEY` | Web search (optional) |
| `TYPESAFE_API_KEY` | Jev structured decisions; falls back to Groq without it (optional) |
| `SUPABASE_URL`, `SUPABASE_KEY`, `DEIMOS_USER_ID` | Long-term memory across sessions (optional) |

### 3. Long-term memory (optional)

Without Supabase, Deimos works normally but forgets everything when a session ends. To keep
memory between sessions, create a Supabase project, run the setup SQL from the
[Installation Guide](docs/installation.md), and add its details with `deimos setup`.

### Developing Deimos
```bash
git clone https://github.com/kunal-shetty/deimos && cd deimos
python -m pip install -e ".[dev]"
python -m pytest
```
A `.env` in the checkout is read too, so you can keep development keys there.

To check the agent loop itself, run the eval harness (see [evals/README.md](evals/README.md)):
```bash
python -m evals run            # deterministic, offline, ~1s
python -m evals serve          # dashboard on http://127.0.0.1:8421
```

---

## Features

- **Multi-Layer Memory**: Persistent semantic, episodic, and project-specific knowledge.
- **Workflow Planning**: Generates a dependency-aware DAG of tasks before executing.
- **Interactive Clarification**: Asks you questions to resolve ambiguities before starting work.
- **Web Integration**: Real-time web search and documentation extraction via Tavily.
- **Git Lifecycle**: Native support for Git operations and GitHub PR management.
- **Real-time Dashboard**: A FastAPI-powered web UI to monitor the agent's internal thoughts and memory.

## Basic Usage

```bash
# Start the agent (same as `deimos assemble`)
deimos

# Start with verbose tool output, or in a permission mode
deimos --verbose
deimos --mode auto-edit

# Add or change API keys
deimos setup

# Launch the monitoring dashboard
deimos dashboard

# Update Deimos to latest version
deimos update
```

## Documentation

For detailed guides, please refer to the `/docs` folder:
- [Installation & Setup](docs/installation.md) — SQL schemas and env config.
- [Architecture](docs/architecture.md) — Memory layers and agent loop.
- [User Guide](docs/user_guide.md) — Prompting tips and slash commands.
- [Developer Guide](docs/developer_guide.md) — Adding new tools and extending the core.
- [API Reference](docs/api_reference.md) — Dashboard API endpoints.

---

## Project Structure

```
deimos/
├── agent/             # Core logic, Planner, and Workflow engine
├── memory/            # Supabase-backed multi-layer memory
├── tools/             # Tool registry and specific tool implementations
├── commands/          # In-session slash commands (/resume, /reset, etc.)
├── web/              # FastAPI Dashboard
├── evals/             # Eval harness: sandboxed tasks, checks, traces, API
├── docs/              # Comprehensive project documentation
└── main.py            # Entry point and CLI dispatch
```

## Stack
- **LLM**: Groq (`openai/gpt-oss-120b` by default, switchable via `/model`)
- **Database**: Supabase (PostgreSQL)
- **UI**: prompt_toolkit (Terminal) & FastAPI (Web)
- **Search**: Tavily API
