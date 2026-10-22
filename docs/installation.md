# Installation

Checked on: 2026-10-22.

Docstale requires Python 3.11 or newer and Git.

## Install the command

Install with `uv`:

```bash
uv tool install git+https://github.com/xiaosq2000/docstale.git
docstale --help
```

Or install with `pipx`:

```bash
pipx install git+https://github.com/xiaosq2000/docstale.git
docstale --help
```

For a source checkout, run one of the following commands from the directory
that contains `pyproject.toml`:

```bash
uv tool install .
pipx install .
```

For project development, use `uv sync --all-groups` instead. It creates an
editable install and installs the test, lint, and type checking tools.

## Upgrade

Upgrade the installed command with the same tool:

```bash
uv tool install --force git+https://github.com/xiaosq2000/docstale.git
pipx upgrade docstale
```

Docstale does not edit agent configuration. A command change therefore requires
you to update the hook entries in `.claude/settings.json` or `.codex/hooks.json`.
For pi, update `DOCSTALE_EXECUTABLE` if the executable path changes.

Update copied reviewer definitions separately. Preserve your custom `model`
and, for Codex, `model_reasoning_effort` values when replacing a definition.

## Pi extension

Install the Python command first. Then install the extension with pi 1.0.2 or
newer:

```bash
pi install git:github.com/xiaosq2000/docstale
```

Add `--local` for a project install. Review the extension before granting project
trust. Project installations load only after pi trusts the project. Automated
runs can use `--approve` to grant trust for that invocation.

The Pi package contains only the adapter. It does not install Python, Git, or
the `docstale` command. You do not need an npm install or compilation step to
use the extension.

For a one-session test from a source checkout, run:

```bash
pi --extension ./.pi/extensions/docstale.ts
```

A trusted source checkout already loads `.pi/extensions/docstale.ts`
automatically. Use the development executable as described in
[Contributing](../CONTRIBUTING.md#documents).

To update an unpinned extension install, run:

```bash
pi update git:github.com/xiaosq2000/docstale
```

Update the Python command separately. Add `@<tag-or-commit>` to the Git package
source if you need a pinned extension revision.

## Move from doc-sync

Docstale is the new name of doc-sync, and it reads only its own files. To move a
repository:

1. Run `git mv doc-sync.toml docstale.toml`. Rename `doc-sync.lock` to
   `docstale.lock` the same way if it exists.
2. Replace `doc-sync hook` with `docstale hook` in `.claude/settings.json` and
   `.codex/hooks.json`.
3. Replace `doc-sync validate` with `docstale check`, and replace the
   `doc-sync-validate` or `doc-sync-check` pre-commit hook with `docstale`.
4. Uninstall doc-sync, install docstale, and run `docstale stamp --all` if the
   repository has no lock yet.

Docstale ignores hook state under `git rev-parse --git-path doc-sync`, so you can
remove that directory.

## Remove docstale

First, remove the `docstale hook` entries from each Claude Code or Codex
configuration where you added them. If you installed the optional reviewer,
remove `.claude/agents/docstale-reviewer.md` or
`.codex/agents/docstale-reviewer.toml` as applicable.

For pi, remove the extension:

```bash
pi remove git:github.com/xiaosq2000/docstale
```

Add `--local` if you installed it for one project. If you copied the extension,
remove that file instead. Then remove the Python command:

```bash
uv tool uninstall docstale
pipx uninstall docstale
```

The repository files `docstale.toml` and `docstale.lock` remain in place. Hook
state remains under `git rev-parse --git-path docstale`. Remove these paths
yourself if you no longer need them.

## Troubleshooting

- If `docstale` is not found after a `uv` install, run `uv tool update-shell`
  and open a new shell.
- If it is not found after a `pipx` install, run `pipx ensurepath` and open a
  new shell.
- Run manual commands inside a Git worktree. Agent hooks stay silent outside
  a Git repository.
- If a Codex hook does not run, open `/hooks` and check its trust state.
- If Codex cannot load the reviewer, check that your version supports native
  `.codex/agents/*.toml` files. Check the model and reasoning effort in the
  definition, then restart Codex.
- If a project-local pi extension does not load, check project trust with
  `/trust`.
- If pi cannot start docstale, check its `PATH` or set `DOCSTALE_EXECUTABLE`
  to the executable's full path. Do not include arguments in the value.
- If pi reports an unsupported extension event, upgrade pi to 1.0.2 or newer.
