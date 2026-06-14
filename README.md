```
██████╗ ███████╗██╗███╗   ███╗ ██████╗ ███████╗
██╔══██╗██╔════╝██║████╗ ████║██╔═══██╗██╔════╝
██║  ██║█████╗  ██║██╔████╔██║██║   ██║███████╗
██║  ██║██╔══╝  ██║██║╚██╔╝██║██║   ██║╚════██║
██████╔╝███████╗██║██║ ╚═╝ ██║╚██████╔╝███████║
╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝
```

> **An autonomous coding agent for your terminal — powered by Groq, with persistent multi-layer memory so it actually knows who you are and what you're building.**

---

## What is Deimos?

Deimos is a terminal-based AI coding agent — you describe what you want built, and it thinks, writes files, runs shell commands, and iterates until the job is done. The key differentiator is **memory**: Deimos doesn't start from scratch every session. It persists your conversations to, extracts facts about you and your project over time, and injects that context into every new session automatically.

```
you: build a REST API in Express with /users and /posts
deimos: [thinks] → [writes files] → [runs npm install] → [runs node index.js] → done ✓
```

---

## How it works

The agent loop is the classic **think → act → observe** cycle:

1. Your message lands in a `Context` (message history manager).
2. The LLM (Groq / `llama-3.3-70b-versatile`) is called with the current context + available tools. (Will allow more models configuration in the future)
3. If the model wants to use a tool (read file, write file, run command), the tool executes and the result is fed back into context.
4. The cycle repeats until the model signals it's done.

---

## Memory architecture

Most agents are amnesiac — every session starts cold. Deimos has three memory layers that persist across sessions:

### Working Memory
Raw conversation messages are saved in real time. Use `/resume` inside the REPL to reload a previous session and pick up exactly where you left off.

### Episodic Memory
When a session ends, it's automatically summarised into a compact "episode." Older episodes are compressed further into archives. This gives Deimos a high-level history of your project's evolution without blowing the context window.

### Semantic Memory
After each session, key facts are extracted — your tech stack, preferences, decisions made, things to avoid — and stored as discrete entries. These are injected directly into the system prompt of every new session, so Deimos always has relevant background context without you having to re-explain yourself.

---

## In-session commands

Type `/` at the prompt to see all available commands (tab-complete works):

| Command | What it does |
|---|---|
| `/help` | List all commands |
| `/chats` | Browse past sessions |
| `/resume [id]` | Reload a previous session |
| `/reset` | Clear the current session and start fresh |
| `/memory` | View stored semantic facts |
| `/status` | Show current agent state (model, iterations, etc.) |
| `/model` | Switch the LLM model mid-session |
| `/exit` | Quit Deimos |

Plain aliases also work: `exit`, `quit`, `q`, `reset`, `clear`.

---

## Setup

**Prerequisites:** Python 3.10+, a [Groq API key](https://console.groq.com).

```bash
git clone https://github.com/kunal-shetty/deimos
cd deimos
pip install -r requirements.txt
```

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key

DEIMOS_USER_ID=your_uuid_from_users_table  # see note below

# Optional
LLM_MODEL=llama-3.3-70b-versatile          # default
MAX_ITERATIONS=30                           # default
```

> **DEIMOS_USER_ID:** Create a row in the `users` table and copy its `id` here. Deimos uses this to scope all memory to you.

---

## Run

```bash
deimos assemble
```

With verbose tool output (shows file contents and command results):

```bash
deimos assemble --verbose
```

---

## Example prompts

```
> build a React todo app
> write a Python script that scrapes HN headlines
> create a REST API in Express with /users and /posts
> add error handling to the file I created earlier
> /resume          ← continue from a previous session
> /memory          ← see what Deimos knows about you
```

---

## Project structure

```
deimos/
├── main.py                   # Entry point, REPL, command dispatch
├── config.py                 # Env vars, paths, model settings
├── core.py                   # Re-exports for backwards compat
│
├── agent/
│   ├── core.py               # The think → act → observe loop
│   └── context.py            # Message history manager
│
├── memory/
│   ├── manager.py            # Coordinates all three memory layers
│   ├── semantic.py           # Fact extraction & long-term knowledge
│   ├── episodic.py           # Session summarisation & archiving
│   ├── conversation.py       # Message persistence & session loading
│   ├── active.py             # Message scoring & importance ranking
│   └── supabase_client.py    # Supabase persistence layer
│
├── tools/
│   ├── base.py               # BaseTool abstract class
│   ├── read_file.py          # Read a file from workspace
│   ├── write_file.py         # Write/create a file in workspace
│   ├── run_command.py        # Execute shell commands
│   └── registry.py           # Tool registry & dispatcher
│
├── commands/                 # In-session slash commands (/resume, /reset, etc.)
├── llm/
│   └── client.py             # Groq API wrapper
├── ui/
│   └── terminal.py           # Spinner, prompt_toolkit REPL, syntax highlighting
├── prompts/
│   └── system.txt            # System prompt injected on every run
│
└── workspace/                # All agent-generated files land here
```

---

## Adding a new tool

1. Create `tools/my_tool.py` extending `BaseTool`:

```python
from tools.base import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful."
    input_schema = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "The input to process"}
        },
        "required": ["input"]
    }

    def run(self, input: str) -> str:
        return f"processed: {input}"
```

2. Register it in `tools/registry.py`:

```python
from tools.my_tool import MyTool

# Inside ToolRegistry.__init__:
self.register(MyTool())
```

That's it — the agent will automatically discover and use it.

---

## Stack

| Layer | Technology |
|---|---|
| LLM | [Groq](https://groq.com) — `llama-3.3-70b-versatile` |
| Terminal UI | [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) + [Pygments](https://pygments.org) |
| Language | Python 3.10+ |

---

## Why "Deimos"?

Deimos is one of Mars's two moons — the smaller, quieter one that stays in the background and gets the job done. Fitting for a coding agent.