# Deimos

Autonomous coding agent for your terminal, enhanced with a multi-layer memory system.

```
  ██████╗ ███████╗██╗███╗   ███╗ ██████╗ ███████╗
  ██╔══██╗██╔════╝██║████╗ ████║██╔═══██╗██╔════╝
  ██║  ██║█████╗  ██║██╔████╔██║██║   ██║███████╗
  ██║  ██║██╔══╝  ██║██║╚██╔╝██║██║   ██║╚════██║
  ██████╔╝███████╗██║██║ ╚═╝ ██║╚██████╔╝███████║
  ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝
```

## Memory Layer

Deimos isn't just a stateless agent; it possesses a sophisticated memory architecture that allows it to learn about you and your project over time.

- **Working Memory**: Real-time persistence of conversations. Resume past sessions and pick up exactly where you left off.
- **Episodic Memory**: Automatically summarizes completed conversations into "episodes" and compresses them into archives, providing a high-level history of your project's evolution.
- **Semantic Memory**: Extracts and stores discrete facts, preferences, and project-specific knowledge, which are injected into the system prompt for every new session.

## Setup

```bash
cd deimos
pip install -r requirements.txt
cp .env.example .env # Create your .env file
```

Add the following to your `.env`:
- `GROQ_API_KEY`: Your Groq API key.
- `SUPABASE_URL`: Your Supabase project URL.
- `SUPABASE_KEY`: Your Supabase service role key.
- `DEIMOS_USER_ID`: Your unique user ID in the Supabase `users` table.

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
├── memory/
│   ├── manager.py        # Memory coordinator (Working/Episodic/Semantic)
│   ├── semantic.py       # Fact extraction & long-term knowledge
│   ├── episodic.py       # Session summarization & archiving
│   ├── conversation.py   # Message persistence & session management
│   ├── active.py         # Message scoring & importance analysis
│   └── supabase_client.py# Persistence layer (Supabase)
├── tools/
│   ├── base.py           # BaseTool abstract class
│   ├── read_file.py      # Read a file
│   ├── write_file.py     # Write/create a file
│   ├── run_command.py    # Execute shell commands
│   └── registry.py       # Tool registry & dispatcher
├── llm/
│   └── client.py         # LLM API wrapper (Anthropic/Groq)
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
