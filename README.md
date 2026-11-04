<h1 align="center">DEIMOS</h1>

<p align="center"><strong>An open-source coding agent for your terminal that runs your tests before it calls the job done.</strong></p>

<p align="center">
  <a href="https://github.com/kunal-shetty/deimos/actions/workflows/ci.yml"><img src="https://github.com/kunal-shetty/deimos/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/kunal-shetty/deimos/releases/latest"><img src="https://img.shields.io/github/v/release/kunal-shetty/deimos" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

<p align="center">
  <a href="https://kunal-shetty.github.io/deimos/demo.html"><img src="site/demo.gif" alt="80 second recording: Deimos installs in one command, fixes a bug, has a wrong fix caught by the tests, plans a feature, undoes it and stops at a destructive command" width="820"></a>
</p>

<p align="center">
  <a href="https://kunal-shetty.github.io/deimos/demo.html"><strong>Open the live demo</strong></a> to pause, scrub and copy text from the recording.<br>
  <sub>Recorded from the real installed program: tools, prompts, checkpoints and pytest ran for real. Model replies and model decisions were scripted so the recording is repeatable.</sub>
</p>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.sh | sh
```

On Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.ps1 | iex
```

You need Python 3.11 or newer and a [Groq API key](https://console.groq.com/keys). Then run `deimos`
in any project folder.

## Why Deimos

- **It checks its own work.** After editing, Deimos runs your test command and sends failures back
  to the agent, so "done" is not just the model's opinion.
- **You stay in control.** By default every edit shows a diff, every command asks first, and destructive
  commands get a red warning. Move up to `auto-edit` or `auto` when you trust the task.
- **Mistakes are cheap.** Each turn is checkpointed, and `/undo` restores the files.
- **Bigger jobs start with a plan.** You read the steps before anything runs.
- **Behaviour is tested.** `python -m evals run` drives the real agent loop through 12 scripted
  tasks with no API key.

---

## Getting Started

Deimos is a terminal-based AI agent that thinks, plans, and executes code changes in your workspace.

The installer puts Deimos in its own environment under `~/.deimos` and adds a `deimos` command
to your PATH. Open a new terminal afterwards, then run `deimos` in any project folder.

### 1. Add your keys

The first run asks for your [Groq API key](https://console.groq.com/keys) and saves it to
`~/.deimos/.env`. Run `deimos setup` any time to add or change keys:

| Key | Needed for |
|---|---|
| `GROQ_API_KEY` | Required: the model behind Deimos |
| `TAVILY_API_KEY` | Web search (optional) |
| `TYPESAFE_API_KEY` | Jev structured decisions; falls back to Groq without it (optional) |
| `SUPABASE_URL`, `SUPABASE_KEY`, `DEIMOS_USER_ID` | Long-term memory across sessions (optional) |

### 2. Long-term memory (optional)

Without Supabase, Deimos works normally but forgets everything when a session ends. To keep
memory between sessions, create a Supabase project, run the setup SQL from the
[Installation Guide](docs/installation.md), and add its details with `deimos setup`.

### Developing Deimos

See [CONTRIBUTING.md](CONTRIBUTING.md).
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

## License

[MIT](LICENSE)
