# Changelog

All notable changes to docstale will be recorded here. The project will follow
Semantic Versioning after its first stable release.

## Unreleased

### Fixed

- Agent hooks stay silent outside a Git repository. They do not produce repeated
  errors or request continuations there. Manual commands still report an error.

## 0.1.1

### Fixed

- `check` lists upstream documents first. It reports document dependency cycles
  as warnings and keeps a deterministic order for later documents.
- `stamp` accepts one or more document paths. It rejects a path that is not a
  configured document before it writes the lock.
- Source matches exclude `docstale.lock`, so a stamp cannot make its own
  document stale.

### Added

- A pi extension reuses `docstale hook` for session baselines and review
  reminders. Install it with `pi install git:github.com/xiaosq2000/docstale`
  after installing the Python command. It requests at most one review
  continuation per request and supports pi's non-interactive modes.
- `docstale.lock` records a fingerprint of each document's sources at its last
  review, and `docstale stamp` writes it. Run `docstale stamp --all` once to
  start a repository on the lock.
- A `docstale` pre-commit hook runs `docstale check`.
- The hook reminder suggests an optional `docstale-reviewer` subagent, and the
  repository provides Claude Code and Codex definitions. The Codex definition
  defaults to `gpt-6-luna` with `high` reasoning effort. Edit its native agent
  file to choose another model and effort. The subagent only reports a verdict.
  It does not edit or stamp documents.
- A `[sets]` table names source lists that documents include with `@name`.
- Document keys may be globs. A glob names every matching file, including files
  created later, and a document named by several keys watches the sources of
  all of them.
- A source that starts with `{dir}` is relative to the document's directory.
- `check` warns about sources that match no file and sets that no document
  uses, without changing its exit code.

### Changed

- Renamed the project from doc-sync to docstale, because "sync" suggested a
  document service. The command is `docstale`, and its files are
  `docstale.toml` and `docstale.lock`. Rename an existing `doc-sync.toml`, and
  update hook commands and pre-commit hook ids.
- `check` compares documents with the lock instead of a diff. A document needs
  review until it is stamped again, and editing it no longer counts as a
  review. Each JSON document adds `since` and `stamped`.
- The Stop hook reports a document whose fingerprint differs from both the lock
  and the session baseline, and stops once the document is stamped. Its
  reminder lists every source changed since the stamp. Baselines from earlier
  versions are replaced silently on the next hook call.
- A directory pattern without glob characters also matches a submodule or
  symlink at that path. A submodule counts when its commit changes and not when
  files inside it are edited.
- `check` validates the configuration. It fails when an exact document does not
  exist or a glob key matches no document.
- A source that starts with `@` names a set. Write `./@name` for a root path
  that starts with `@`.

### Removed

- `check --staged` and `check --base`. The lock gives one answer for the
  repository state, so there is no diff to select.
- The JSON schema for the configuration. No test kept it in step with the
  loader.
- `validate` and the `doc-sync-validate` pre-commit hook. `check` now does the
  same validation.

## 0.1.0a2

### Changed

- The automatic hook now compares files with a session baseline instead of
  `HEAD`, so pre-existing edits do not trigger reminders. Add SessionStart
  alongside Stop using the same `doc-sync hook` command. Without a baseline,
  the first hook call saves the current state silently and checks later edits.
- Replaced named rules with a `[documents]` table that maps each exact document
  path to its source patterns. Removed `config_version`, rule IDs, and rules
  that group several documents. The old configuration format is not accepted.
- Reduced the command surface to `check`, `validate`, `hook`, `disable`, and
  `enable`. Manual checks always answer and ignore the hook switch. Removed
  `review`, `status`, `init`, custom roots, custom configuration paths, custom
  state directories, explicit path files, and hook installation commands.
- Replaced agent specific hook commands with one shared `doc-sync hook` command
  for Claude Code and Codex. The hook now honors `stop_hook_active` before it
  reads Git or configuration state.
- Removed the OpenCode adapter and all code that edited agent configuration
  files. Agent setup now uses documented JSON entries.
- Replaced the public Python model and evaluation API with internal document and
  review records. JSON output now contains `status` and `documents`.
- Validation now requires configured documents to exist. Source patterns may be
  unmatched on the current branch.
