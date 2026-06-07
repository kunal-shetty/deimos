# Deimos

Autonomous coding agent for your terminal.

```
  ██████╗ ███████╗██╗███╗   ███╗ ██████╗ ███████╗
  ██╔══██╗██╔════╝██║████╗ ████║██╔═══██╗██╔════╝
  ██║  ██║█████╗  ██║██╔████╔██║██║   ██║███████╗
  ██║  ██║██╔══╝  ██║██║╚██╔╝██║██║   ██║╚════██║
  ██████╔╝███████╗██║██║ ╚═╝ ██║╚██████╔╝███████║
  ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝
```

## Setup

```bash
cd deimos
pip install -r requirements.txt
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

## Run

```bash
python main.py
```

With verbose tool output:
```bash
python main.py --verbose
```

## Usage

```
> build a React todo app
> write a Python script that scrapes HN headlines
> create a REST API in Express with /users and /posts
> exit
```

## File Structure

```
deimos/
├── main.py               # Entry point & REPL
├── config.py             # Config & env vars
├── agent/
│   ├── core.py           # Agent loop (think → act → observe)
│   └── context.py        # Message history manager
├── tools/
│   ├── base.py           # BaseTool abstract class
│   ├── read_file.py      # Read a file
│   ├── write_file.py     # Write/create a file
│   ├── run_command.py    # Execute shell commands
│   └── registry.py       # Tool registry & dispatcher
├── llm/
│   └── client.py         # LLM API wrapper (Anthropic)
├── ui/
│   └── terminal.py       # Terminal output, spinner, REPL
├── prompts/
│   └── system.txt        # System prompt for the agent
└── workspace/            # Generated files go here
```

## Adding a New Tool

1. Create `tools/my_tool.py` extending `BaseTool`
2. Implement `name`, `description`, `input_schema`, and `run()`
3. Import and add it in `tools/registry.py`

That's it — the agent will automatically use it.
