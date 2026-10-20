"""
Command line for the eval harness.

    python -m evals list
    python -m evals run [--mode scripted|live] [--task ID ...] [--json out.json] [-v]
    python -m evals serve [--host 127.0.0.1] [--port 8421]

`run` exits 1 if any task fails or errors, so it can gate CI.
"""

from __future__ import annotations

import argparse
import json
import sys

from evals.runner import live_available, run_suite, summarize
from evals.tasks import SUITE

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _cmd_list(_args) -> int:
    for t in SUITE:
        kind = "scripted+live" if t.scripted else "live only"
        print(f"{t.id:36} {t.category:13} {kind:14} {t.name}")
    return 0


def _cmd_run(args) -> int:
    known = {t.id for t in SUITE}
    unknown = sorted(set(args.task or []) - known)
    if unknown:
        print(f"unknown task id(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    if args.mode == "live" and not live_available():
        print("live mode needs GROQ_API_KEY (set it in the environment or ~/.deimos/.env)", file=sys.stderr)
        return 2

    def show(r):
        colour = {"passed": GREEN, "failed": RED, "error": RED}.get(r["status"], DIM)
        m = r["metrics"]
        extra = f"{m.get('llm_calls', 0)} model calls, {m.get('tool_calls', 0)} tools, {m.get('duration_s', 0)}s" \
            if r["status"] != "skipped" else (r["error"] or "")
        print(f"{colour}{r['status']:8}{RESET} {r['task_id']:36} {DIM}{extra}{RESET}")
        if r["status"] in ("failed", "error") or args.verbose:
            if r["error"] and r["status"] != "skipped":
                print(f"         error: {r['error']}")
            for c in r["checks"]:
                if not c["passed"]:
                    print(f"         {RED}✗{RESET} {c['name']}")
                    for line in c["detail"].splitlines()[:6]:
                        print(f"             {line}")

    results = run_suite(args.task or None, mode=args.mode, model=args.model, on_result=show)
    summary = summarize(results)
    rate = "n/a" if summary["pass_rate"] is None else f"{summary['pass_rate']:.0%}"
    print(f"\n{summary['passed']}/{summary['ran']} passed ({rate}), {summary['skipped']} skipped, "
          f"{summary['input_tokens'] + summary['output_tokens']} tokens, {summary['duration_s']}s")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"mode": args.mode, "summary": summary, "results": results}, f, indent=2)
        print(f"wrote {args.json}")
    return 1 if summary["failed"] or summary["errors"] else 0


def _cmd_serve(args) -> int:
    import uvicorn
    from evals.app import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description="Deimos eval harness")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list tasks").set_defaults(fn=_cmd_list)

    run = sub.add_parser("run", help="run the suite")
    run.add_argument("--mode", choices=("scripted", "live"), default="scripted")
    run.add_argument("--task", action="append", help="task id (repeatable); default is all")
    run.add_argument("--model", help="live mode: override the model")
    run.add_argument("--json", help="write full results (traces included) to this file")
    run.add_argument("-v", "--verbose", action="store_true", help="show check details for passing tasks too")
    run.set_defaults(fn=_cmd_run)

    serve = sub.add_parser("serve", help="start the dashboard and API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8421)
    serve.set_defaults(fn=_cmd_serve)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
