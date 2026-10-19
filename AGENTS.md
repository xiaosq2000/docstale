# docstale

Checked on: 2026-10-19.

Docstale reports documents whose sources changed since their last recorded
review, using TOML, a committed lockfile, and Git.
Keep it deterministic, with no LLM calls or heuristics and `pathspec` as its only
runtime dependency. Do not add command variants, agent installers, or a public
Python API without a demonstrated use case.

## Development

Setup and check commands are in [CONTRIBUTING.md](CONTRIBUTING.md#development-setup).
Local tests use temporary fixtures and Git repositories. You may run checks and
fix failures caused by the requested change without asking for approval at each
step. Keep tool upgrades deliberate and fix new findings in the same change.

This repository runs docstale on itself. Before finishing a change, review each
document that `uv run docstale check` lists, update it if needed, and stamp it.
Stamp a document only after reading it against the changed sources.

## Code boundaries

- Keep `match.py` and `Config.resolve()` free of Git, file access, hook input,
  and command output. `cli.py` passes in repository paths and object ids.
- Route all Git calls through `_run_git()` and human or JSON output through
  `cli.py`.
- Anchor source patterns to the repository root. Matching at any depth requires
  `**/`, and leading `!` and `#` are literal characters. A leading `@` names a
  set, and `{dir}` may only start a source.
- Exclude the document itself and root `docstale.lock` from source matches.
  Order documents upstream first, with deterministic path order for ties and cycles.

## Hook invariants

The [hook reference](docs/reference.md#agent-hook) defines session behavior and
error handling, and the [README](README.md#remind-your-coding-agent) defines
setup.

- Return immediately when `stop_hook_active` is true, before accessing Git,
  configuration, or state.
- Keep pi's staleness decisions and review text in Python. The adapter only
  translates lifecycle events and the hook protocol. Pi reminders must not
  suggest a `docstale-reviewer` subagent.
- A reminder does not authorize edits. For read-only requests, report affected
  documents without file edits or stamps.
- Save acknowledgements only after review entries are ready. A Git failure
  during report preparation must preserve the earlier acknowledgement state.
- Preserve earlier pi boundary entries. Request at most one review continuation
  per settled run. Never restart aborted or failed work.
- Keep session baselines separate from acknowledgements. Resume, compaction,
  and clearing acknowledgements must preserve the baseline.
- Store hook state under `git rev-parse --git-path docstale` so linked worktrees
  remain independent. The disable marker affects only hooks, never manual
  commands or their JSON status.

## Contract changes

Changes to configuration behavior, JSON output, exit codes, or hooks must include
contract tests and matching updates to the README or `docs/reference.md`. Mark
tests that require POSIX filesystem behavior with `@pytest.mark.posix_only` so
they skip on Windows.
