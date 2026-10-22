# Contributing

Checked on: 2026-10-22.

Bug reports should include the command, configuration, Git state, expected
result, and actual result. Remove private paths and repository content from
logs before posting them.

## Development setup

Docstale requires Python 3.11 or newer, Git, and
[uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
```

The pi adapter tests also require Node.js 22.19 or newer and npm. They use
Node's built-in test runner and TypeScript support. They need no `npm install`
and make no model calls.

Run all checks before opening a pull request:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
npm test
uv run docstale check
```

To require full statement and branch coverage, run
`uv run pytest --cov --cov-fail-under=100`.

Ruff selects every rule, and ty treats every rule as an error. Both tools are
pinned in `uv.lock` and bounded in `pyproject.toml`. Upgrade them deliberately
and fix new findings in the same change.

## Documents

The repository runs docstale on itself. `docstale.toml` maps each document to
the code it describes, and CI runs `uv run docstale check`. After a change, run
that command, review each document it lists, update the document if needed, and
stamp it with `uv run docstale stamp <document>`. The agent hooks in `.claude/`
and `.codex/` run the development build from `.venv`, so run `uv sync
--all-groups` before starting an agent.

Pi loads `.pi/extensions/docstale.ts` after project trust. From the repository
root on POSIX systems, select the development executable before starting pi:

```bash
DOCSTALE_EXECUTABLE="$PWD/.venv/bin/docstale" pi
```

On Windows PowerShell:

```powershell
$env:DOCSTALE_EXECUTABLE = "$PWD\.venv\Scripts\docstale.exe"
pi
```

The extension otherwise uses `docstale` from `PATH`. `npm test` uses the
checkout's `.venv` executable by default. Set `DOCSTALE_EXECUTABLE` to test
another installation.

## Architecture

Docstale has one job. It reports documents whose sources changed since their
last recorded review, using the `[documents]` table in `docstale.toml` and the
fingerprints in `docstale.lock`.

- `config.py` parses the configuration, expands document globs, sets, and
  `{dir}`, orders document dependencies, and checks document targets.
- `paths.py` normalizes paths and caches compiled, anchored source patterns.
- `match.py` contains the pure matching and fingerprint functions.
- `lock.py` reads and writes `docstale.lock`.
- `render.py` writes the review report and the hook reminder.
- `git.py` discovers the repository, changed paths, and Git object ids.
- `hook.py` parses the shared SessionStart and Stop protocol.
- `state.py` stores session fingerprints, reminder state, and the local disable
  marker.
- `cli.py` implements `check`, `stamp`, `hook`, `disable`, and `enable`.
- `.pi/extensions/docstale.ts` translates pi lifecycle events into that hook
  protocol. Python still owns fingerprints, baseline storage, and review text.
- `package.json` exposes the adapter as a Git-installable Pi package.
- `tests/pi/` tests the adapter and the real CLI in temporary Git repositories.

Keep `match.py` and `Config.resolve()` free of Git, file access, hook input,
and command output.
Internal Python classes are implementation details and are not a public API.

## Contracts

Changes to configuration behavior, JSON output, exit codes, or agent hooks
must include contract tests and matching updates to the README or
`docs/reference.md`.

The stable exit codes are:

- `0` means the check passed or the hook completed.
- `1` means a manual command failed.
- `2` means one or more documents need review.
