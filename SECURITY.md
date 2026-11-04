# Security

Deimos runs shell commands and edits files on your machine, so security reports
are especially welcome.

## Reporting a vulnerability

Please report privately through
[GitHub security advisories](https://github.com/kunal-shetty/deimos/security/advisories/new),
not in a public issue. Include the steps to reproduce and the version from
`deimos --version`.

## What counts

Reports that matter most here:

- A way to run a command or change a file without the approval your permission
  mode requires
- Project files (such as `DEIMOS.md` or `.deimos/settings.json`) that run commands
  before you have approved them
- API keys leaking into logs, traces or the dashboard

Only the latest release is supported.
