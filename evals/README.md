# Deimos evals

A harness that runs the **real** Deimos `Agent` loop against small sandboxed
projects and grades what happened with deterministic checks. It answers two
different questions, so it has two modes.

| Mode | Who drives the agent | What it tells you | Needs |
|---|---|---|---|
| `scripted` | A fake LLM replaying a fixed script | Did the agent's own machinery break? (tool dispatch, permissions, self-healing, verification, undo, truncation) | nothing, ~1 second, no network |
| `live` | The real model (Groq) | Does the model plus the prompt actually solve the tasks? | `GROQ_API_KEY` |

Scripted runs are deterministic, so a red task means a code regression and
they are safe to run in CI. Live runs are the benchmark: run one before and
after a prompt, tool-description or model change and compare.

## Usage

```bash
python -m evals list
python -m evals run                         # scripted suite, exits 1 on any failure
python -m evals run --task verify_gate_catches_bad_fix -v
python -m evals run --mode live --model openai/gpt-oss-20b --json out.json
python -m evals serve                       # dashboard + API on http://127.0.0.1:8421
```

The dashboard starts runs, shows per-task checks, a step-by-step trace (every
model call with tokens and latency, every tool call with its result, every
permission prompt), the diffs the agent produced, and compares two runs so
regressions stand out.

## How a task runs

1. A temp directory is created and filled with the task's files.
2. The agent runs there with `NullMemory`, a recording UI and a fixed answer
   for permission prompts (`approve`). `~/.deimos` is replaced by an empty
   directory so personal settings or instructions can't leak into results.
3. The safety and "does this change need tests" deciders are stubbed so
   nothing calls the network to decide those.
4. The checks run against the sandbox and the trace. The temp directory is
   deleted.

Runs are serialised behind a lock because the agent works relative to the
process working directory.

## Writing a task

```python
Task(
    id="edit_existing_file", name="Edit an existing file", category="tools",
    description="edit_file replaces an exact, unique match.",
    prompt="Make greet() return 'hello'.",
    files={"app.py": "def greet():\n    return 'hi'\n"},
    permission_mode="auto-edit",
    script=[                                    # omit for a live-only task
        {"tool_calls": [{"name": "edit_file", "inputs": {...}}]},
        {"text": "Done."},                      # a turn without tool calls ends the turn
    ],
    repairs=[...],                              # answers for the self-healing loop
    checks=[{"type": "file_contains", "path": "app.py", "text": "return 'hello'"}],
)
```

Check types live in `checks.py`: file checks (`file_exists`, `file_contains`,
`file_equals`, `file_unchanged`, ...), tool checks (`tool_called`,
`tool_result_contains`, `max_tool_calls`), model-call budgets
(`max_llm_calls`), permission checks (`permission_requests`,
`permission_request`), and `command_passes` to run a command in the sandbox
(for example the project's own tests).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | whether live mode is available, active run |
| `GET /api/tasks` | task catalogue |
| `POST /api/runs` | start a run `{"mode": "scripted", "task_ids": [...], "model": null}` (409 if one is running) |
| `GET /api/runs` / `GET /api/runs/{id}` | past runs / one run's results |
| `GET /api/runs/{id}/tasks/{task}` | checks, trace, diffs, final answer |
| `GET /api/compare?base=&head=` | regressions, fixes and token deltas between two runs |

Results are saved as JSON in `evals/results/` (override with `EVAL_RESULTS_DIR`).

## Limits

- Scripted mode proves the machinery, not the model. A green scripted suite says nothing about answer quality.
- Live tasks are small on purpose. Treat a pass rate as a regression signal, not a leaderboard score, and run each live task more than once before drawing conclusions because model output varies.
- Only the main agent loop is covered. Sub-agents (`delegate`), plan mode and memory are not exercised yet.
