# Technical Debt & Roadmap

This document tracks known architectural weaknesses, bugs, and planned improvements for Deimos.

## ✅ Resolved (September 2026)

- [x] **Missing plan-mode UI methods**: `agent.core` called `ui.print_plan()`, `ui.plan_confirmed()`, `ui.plan_rejected()`, and `ui.print_plans()` — none existed on `TerminalUI`, so any multi-step plan or `/plans` crashed with `AttributeError`. All four implemented with box-drawn plan display.
- [x] **Missing `beautifulsoup4` dependency**: `tools/web_fetch.py` imports `bs4` but it wasn't declared in `pyproject.toml`/`requirements.txt`, so a fresh install crashed at `ToolRegistry` import time. Added to both.
- [x] **Stale duplicate root files**: root-level `base.py` and `core.py` were leftover copies of `tools/base.py` and an old agent loop; they shadowed imports and confused tooling. Deleted.
- [x] **Self-healing retry bug** (`agent/core.py`): the retry counter was incremented twice per failed fix attempt (once inside `except`, once after), halving the effective retries; also raw JSON fences from the LLM weren't stripped before `json.loads`. Fixed.
- [x] **Blocking importance scoring**: every user message triggered a synchronous LLM call (`memory/active.py`) before the agent loop could start — adding seconds of latency per turn. Now scored on a background daemon thread; the stored row is patched when the result lands (`ConversationStore.update_message_importance`).
- [x] **`/reset` left `active_plan` set**: after a reset, workflow status from a stale plan kept being injected into context. Cleared in `Agent.reset()`.
- [x] **Windows encoding crash**: Unicode box-drawing/emoji in the TUI raised `UnicodeEncodeError` when stdout wasn't UTF-8 (piped output, cp1252 console). `ui/terminal.py` now force-reconfigures stdout/stderr to UTF-8.
- [x] **Typewriter effect**: removed the char-by-char delay (≈10ms/char made long answers crawl); replaced with immediate markdown rendering after stream end.

## 🔴 Critical Gaps (Remaining)

- [ ] **Context window management**: `Context` grows unbounded; long sessions will eventually exceed the model's context. Needs summarization/truncation of old turns.
- [ ] **Dashboard dead without DB**: agent pushes events to `http://host:port/api/push` on every turn even when the dashboard isn't running (0.1s timeout each — silent but wasteful). Consider a push-enabled flag or in-proc event bus.
- [ ] **Tool error handling**: tool failures are plain strings matched by prefix (`"Error:"`); structured error objects would make agent recovery much more reliable.
- [ ] **`update_message_importance` match fragility**: the async scorer patches the last message via a `LIKE` on content prefix; special characters (`%`, `_`) are escaped only for `%`. Consider storing a client-side message id instead.

## 🟡 Medium Priority

- **Prompt hardcoding**: many prompts live in code (`planner.py`, `memory/*.py`); should be moved to `prompts/` config files.
- **Memory compression logic**: the episodic archive process is simple; could use more sophisticated summarization strategies.
- **DAG enforcement**: `Planner` trusts the LLM that plan steps form a valid DAG; no cycle detection or dependency validation.
- **`run_update()` git pull**: runs `git pull` blindly — dirty working trees will conflict. Should stash/abort gracefully.
- **Streaming tool-call display**: tool calls assembled from streamed deltas aren't shown until complete; could show live "calling tool…" state.

## 🟢 Low Priority / Future Ideas

- **Multi-provider support**: OpenAI or Anthropic APIs alongside Groq (the client already speaks OpenAI wire format).
- **Local LLM integration**: Ollama or LocalAI.
- **Enhanced dashboard**: graph visualization of the Workflow DAG.
- **Parallel tool execution**: independent tool calls in one turn could run concurrently.
- **Streaming markdown rendering**: render markdown incrementally during streaming (currently re-renders once at stream end).

---
*Convention: Use `TODO:` and `FIXME:` markers in code to flag issues for inclusion here.*
