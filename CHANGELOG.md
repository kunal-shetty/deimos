# Changelog

Notable changes to Deimos. This project follows
[Semantic Versioning](https://semver.org/).

## Unreleased

## 0.2.0 - 2026-11-04

First tagged release.

### Added

- Permission modes with diff previews before edits
- File checkpoints and `/undo` for each agent turn
- Verification loop: runs your tests before a turn can finish and sends failures
  back to the agent
- Hooks around tool calls, configured in `settings.json`
- Parallel sub-agents
- Plan mode with a dependency graph of steps that you approve before work starts
- One-line installers for macOS, Linux, WSL and Windows, plus `deimos setup`
- Optional long-term memory on Supabase, with Postgres full-text recall
- `DEIMOS.md` project instructions, tool output limits and a rolling session summary
- Settings file and a fast model for side jobs
- Eval harness with sandboxed tasks, deterministic checks, traces and a dashboard
- Terminal interface with slash commands
- MIT license, CI on Linux, macOS and Windows, contributing guide and issue templates

### Changed

- Deimos now works without Supabase; long-term memory is off until you connect it
- Tests no longer need a real `GROQ_API_KEY`
- Scripted evals now run on Windows, where `python3` does not exist

### Fixed

- Startup crash, context trimming, self-healing retries and plan tracking
- The website's install button pointed at a domain this project does not control; it
  now uses the official installer on GitHub
