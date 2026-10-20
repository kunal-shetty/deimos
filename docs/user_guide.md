# User Guide

Welcome to Deimos. This guide will help you get the most out of your autonomous coding agent.

## 1. Starting a Session

Run `deimos assemble` to start the agent. You can use flags to customize the session:
- `--verbose`: See full tool output previews.
- `--no-plan`: Skip the planning phase for simple tasks.

## 2. Using Slash Commands

Deimos supports several in-session commands to manage your experience:

### Session Management
- `/help`: Show all available commands.
- `/reset`: Clear current context (memory is preserved).
- `/exit`: Save session and quit.
- `/status`: Show current session info (working dir, models, decision backend, plan mode).

### Project Instructions
- `/init [--force]`: Explore the project and write a `DEIMOS.md` with its commands, layout and conventions.
- `/instructions`: List the `DEIMOS.md` files loaded into this session.

Deimos loads `~/.deimos/DEIMOS.md` plus every `DEIMOS.md` from the filesystem root down to the
working directory; the closest one takes precedence. Edit them freely — `/reset` reloads them.

### Memory & Projects
- `/memory`: Show what Deimos remembers about you globally.
- `/projects`: List all projects Deimos knows about.
- `/project <name>`: Show specific memory for a project.
- `/title <text>`: Rename the current conversation.

### Planning
- `/plan [on|off]`: Toggle the planning phase.
- `/plans`: List all plans created in the current project.
- `/plan-reject`: Reject a pending plan and ask the agent to rethink.

### System
- `/model <name>`: Switch the LLM model (e.g., `gpt-4o`, `claude-3-5-sonnet`).
- `/verbose`: Toggle verbose tool outputs.
- `/clear-screen`: Clear the terminal.

### Long Sessions
- Tool outputs longer than `tool_output_limit` characters (default 8000, set in
  `.deimos/settings.json`) are shortened to their start and end; the full text is saved under
  `.deimos/outputs/` and the agent can page through it with `read_file`.
- When the conversation outgrows the context window, older messages are folded into a running
  summary that stays in the prompt, and are archived to episodic memory.

## 3. Prompting Tips

Deimos is an autonomous agent, but it works best when given clear constraints.

### Good Prompts
- **Specific**: "Refactor the `Agent.run` method in `agent/core.py` to support async tool calls, ensuring that no breaking changes are made to the `BaseTool` interface."
- **Iterative**: "First, analyze the current implementation of the memory system. Then, suggest three ways to improve the compression logic. Finally, implement the best one."
- **Constraint-based**: "Implement a new tool for reading PDF files, but do not add any new external dependencies to `pyproject.toml`."

### Dealing with Ambiguity
If a request is too broad (e.g., "Fix the bugs in the project"), Deimos will enter a **Clarification Phase**. It will ask you specific questions to narrow down the scope before it starts planning. Answer these questions to get a more accurate result.

## 4. The Planning Process

When `plan_mode` is on, Deimos follows these steps:
1. **Analysis**: Analyzes your request.
2. **Proposal**: Generates a detailed plan (Workflow DAG).
3. **Confirmation**: Awaits your approval. You can simply reply "Yes", "Proceed", or provide feedback to refine the plan.
4. **Execution**: Executes the tasks in the plan, updating the dashboard in real-time.
