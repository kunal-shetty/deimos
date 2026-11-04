# Contributing to Deimos

Thanks for helping out. Small, focused pull requests are the easiest to review
and the quickest to merge.

## Set up

You need Python 3.11 or newer. You do not need an API key to run the tests.

```bash
git clone https://github.com/kunal-shetty/deimos && cd deimos
python -m pip install -e ".[dev]"
python -m pytest
python -m evals run
```

`python -m evals run` drives the real agent loop with a scripted model. It needs no
network and takes a few seconds. See [evals/README.md](evals/README.md).

To try your change by hand, run `deimos` in a throwaway project. It reads a `.env`
in the checkout, so you can keep development keys there. That file is ignored by git.

## Find something to work on

- Issues labelled
  [good first issue](https://github.com/kunal-shetty/deimos/labels/good%20first%20issue)
  are small and self-contained.
- [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md) lists known weaknesses.
- For anything large, open an issue or a discussion first so we can agree on the
  approach before you spend time on it.

## Where things live

| Path | What it does |
|---|---|
| `agent/` | Agent loop, planner, permissions, hooks, verification, checkpoints |
| `tools/` | Tools the model can call |
| `commands/` | Slash commands |
| `llm/` | Model client and structured decisions |
| `memory/` | Long-term memory (Supabase) |
| `ui/` | Terminal interface |
| `evals/` | Scripted and live evaluation harness |

To add a tool, follow the [developer guide](docs/developer_guide.md).

## Before you open a pull request

- Add a test for new behaviour or for the bug you fixed. If you change the agent
  loop, tools or permissions, add a scripted task in `evals/tasks.py` too.
- Run `python -m pytest` and `python -m evals run`. CI runs both on Linux, macOS and
  Windows, so avoid POSIX-only commands in tests.
- Add a line under `Unreleased` in [CHANGELOG.md](CHANGELOG.md) if users will notice
  the change.
- Do not use emojis in terminal output or docs. Use plain markers, colour or weight.
- Never commit API keys or a real `.env`.

## Security

Please report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).

By contributing, you agree that your work is licensed under the
[MIT License](LICENSE).
