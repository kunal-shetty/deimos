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

## 🚀 Getting Started

Deimos is a terminal-based AI agent that thinks, plans, and executes code changes in your workspace.

### 1. Quick Install (Unix/Bash/WSL)
```bash
curl -sSL https://deimos.sh/install | sh
```

### 2. Manual Install (Windows/PowerShell)
```powershell
git clone https://github.com/kunal-shetty/deimos
cd deimos
python -m venv .venv
.\.venv\Scripts\activate
pip install .
```

### 3. Configuration
Create a `.env` file in the root directory:
```env
GROQ_API_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
DEIMOS_USER_ID=your-user-uuid
```

### 4. Database Setup
Deimos requires a Supabase instance for its memory. Please run the setup SQL provided in the [Installation Guide](docs/installation.md).

---

## 🛠️ Features

- **Multi-Layer Memory**: Persistent semantic, episodic, and project-specific knowledge.
- **Workflow Planning**: Generates a dependency-aware DAG of tasks before executing.
- **Interactive Clarification**: Asks you questions to resolve ambiguities before starting work.
- **Web Integration**: Real-time web search and documentation extraction via Tavily.
- **Git Lifecycle**: Native support for Git operations and GitHub PR management.
- **Real-time Dashboard**: A FastAPI-powered web UI to monitor the agent's internal thoughts and memory.

## ⌨️ Basic Usage

```bash
# Start the agent
deimos assemble

# Start with verbose tool output
deimos assemble --verbose

# Launch the monitoring dashboard
deimos dashboard

# Update Deimos to latest version
deimos update
```

## 📖 Documentation

For detailed guides, please refer to the `/docs` folder:
- [Installation & Setup](docs/installation.md) — SQL schemas and env config.
- [Architecture](docs/architecture.md) — Memory layers and agent loop.
- [User Guide](docs/user_guide.md) — Prompting tips and slash commands.
- [Developer Guide](docs/developer_guide.md) — Adding new tools and extending the core.
- [API Reference](docs/api_reference.md) — Dashboard API endpoints.

---

## 🏗️ Project Structure

```
deimos/
├── agent/             # Core logic, Planner, and Workflow engine
├── memory/            # Supabase-backed multi-layer memory
├── tools/             # Tool registry and specific tool implementations
├── commands/          # In-session slash commands (/resume, /reset, etc.)
├── web/              # FastAPI Dashboard
├── docs/              # Comprehensive project documentation
└── main.py            # Entry point and CLI dispatch
```

## Stack
- **LLM**: Groq (`llama-3.3-70b-versatile`)
- **Database**: Supabase (PostgreSQL)
- **UI**: prompt_toolkit (Terminal) & FastAPI (Web)
- **Search**: Tavily API
