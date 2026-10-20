"""
Deimos eval harness.

Runs the real Agent loop against small sandboxed projects and grades the
outcome with deterministic checks (files, tool calls, commands, permissions).

Two modes:
  scripted  a fake LLM replays a fixed script, so the agent's own machinery
            (tool dispatch, permissions, self-healing, verification, undo)
            is tested quickly, offline and without flakiness. Safe for CI.
  live      the real model drives the same tasks, which measures the model
            and prompt together (needs GROQ_API_KEY).

    python -m evals run --mode scripted
    python -m evals serve            # dashboard on http://127.0.0.1:8421
"""
