"""Strict Git-backed repository discovery."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from docstale.errors import DocstaleError

# Paths per `git hash-object` call, which keeps the command line short.
_HASH_BATCH = 200


class GitError(DocstaleError, RuntimeError):
    """Raised when docstale cannot query repository state."""


class NotGitRepositoryError(GitError):
    """Raised when Git discovery finds no repository."""


def _run_git(
    root: Path,
    arguments: list[str],
    *,
    stdin: bytes | None = None,
    env: dict[str, str] | None = None,
) -> bytes:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(root), *arguments],  # noqa: S607
            input=stdin,
            env=env,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise GitError(f"could not execute git: {exc}") from exc
    if result.returncode != 0:
        detail = os.fsdecode(result.stderr).strip() or "unknown git error"
        # Missing repositories mention the parent-directory search. Invalid
        # explicit Git directories have a different diagnostic and remain errors.
        error = (
            NotGitRepositoryError
            if any(
                line.startswith(b"fatal: not a git repository (")
                for line in result.stderr.splitlines()
            )
            else GitError
        )
        raise error(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _nul_paths(output: bytes) -> tuple[str, ...]:
    return tuple(os.fsdecode(raw_path) for raw_path in output.split(b"\0") if raw_path)


def resolve_root(raw_root: str | None = None) -> Path:
    """Resolve and validate the Git repository root."""
    candidate = Path(raw_root).resolve() if raw_root else Path.cwd().resolve()
    # Only discovery needs a fixed diagnostic language. Keep the caller's
    # locale for other commands, including those that invoke Git filters.
    output = _run_git(
        candidate,
        ["rev-parse", "--show-toplevel"],
        env={**os.environ, "LC_ALL": "C"},
    )
    return Path(os.fsdecode(output).strip()).resolve()


def head_commit(root: Path) -> str | None:
    """Return the commit at HEAD, or None before the first commit."""
    try:
        output = _run_git(root, ["rev-parse", "--verify", "HEAD"])
    except GitError:
        return None
    return os.fsdecode(output).strip()


def last_change_commit(root: Path, path: str, text: str) -> str | None:
    """Return the latest commit that changed how often `text` occurs in `path`."""
    try:
        output = _run_git(root, ["log", "-1", "--format=%H", f"-S{text}", "--", path])
    except GitError:
        # Before the first commit there is no history to search.
        return None
    return os.fsdecode(output).strip() or None


def file_at_commit(root: Path, commit: str, path: str) -> str | None:
    """Read a UTF-8 file at a commit, or None when that tree has no such path."""
    if not _run_git(root, ["ls-tree", "-z", commit, "--", path]):
        return None
    content = _run_git(root, ["show", f"{commit}:{path}"])
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitError(f"{path} at {commit} is not UTF-8 text: {exc}") from exc


def untracked_paths(root: Path) -> tuple[str, ...]:
    """Return non-ignored untracked paths."""
    return _nul_paths(
        _run_git(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    )


def changed_worktree_paths(
    root: Path, commit: str | None = None, *, untracked: tuple[str, ...] | None = None
) -> tuple[str, ...]:
    """Return paths changed since a commit, HEAD by default, and untracked paths."""
    # A submodule counts when its commit changes, not when files inside it are
    # edited.
    diff = ["diff", "--name-only", "-z", "--ignore-submodules=dirty"]
    try:
        tracked = _nul_paths(_run_git(root, [*diff, commit or "HEAD", "--"]))
    except GitError:
        if commit is not None:
            raise
        # Unborn HEAD: the index is the only thing there is to compare against.
        # Asking first would cost an extra `git` spawn on every agent hook fire.
        tracked = _nul_paths(_run_git(root, ["diff", "--cached", "--name-only", "-z"]))
    changed = {*tracked, *(untracked_paths(root) if untracked is None else untracked)}
    return tuple(sorted(changed))


def object_ids(root: Path) -> dict[str, str]:
    """Return the Git object id of every tracked or non-ignored untracked path.

    Unchanged files keep their index ids. Changed and untracked files are hashed
    with Git's filters, so the ids agree across clones and platforms. A symlink
    is hashed by its target and a submodule by its checked-out commit. Deleted
    paths are left out.
    """
    ids: dict[str, str] = {}
    changed: set[str] = set()
    for entry in _nul_paths(_run_git(root, ["ls-files", "--stage", "-z"])):
        info, _, path = entry.partition("\t")
        _mode, object_id, stage = info.split(" ")
        if stage == "0":
            ids[path] = object_id
        else:
            # A conflicted path has one entry per side and conflict markers in
            # the working tree.
            changed.add(path)
    changed.update(
        _nul_paths(
            _run_git(root, ["diff", "--name-only", "-z", "--ignore-submodules=dirty"])
        )
    )
    changed.update(
        path
        for path in untracked_paths(root)
        # Git lists an untracked nested repository as a directory.
        if not path.endswith("/")
    )

    files: list[str] = []
    for path in sorted(changed):
        ids.pop(path, None)
        if (object_id := _special_object_id(root, path, files)) is not None:
            ids[path] = object_id
    for start in range(0, len(files), _HASH_BATCH):
        batch = files[start : start + _HASH_BATCH]
        output = os.fsdecode(_run_git(root, ["hash-object", "--", *batch]))
        ids.update(zip(batch, output.split(), strict=True))
    return ids


def _special_object_id(root: Path, path: str, files: list[str]) -> str | None:
    """Hash a changed symlink or submodule, or queue a regular file for hashing."""
    location = root / path
    try:
        mode = location.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISREG(mode):
        files.append(path)
        return None
    if stat.S_ISLNK(mode):
        # `git hash-object` would follow the link, but Git stores its target.
        target = os.fsencode(location.readlink())
        return os.fsdecode(
            _run_git(root, ["hash-object", "--stdin"], stdin=target)
        ).strip()
    if stat.S_ISDIR(mode) and (location / ".git").exists():
        try:
            output = _run_git(location, ["rev-parse", "--verify", "HEAD"])
        except GitError:
            return None
        return os.fsdecode(output).strip()
    return None


def git_metadata_path(root: Path, relative_path: str) -> Path:
    """Resolve a worktree-aware path inside Git metadata."""
    output = _run_git(root, ["rev-parse", "--git-path", relative_path])
    path = Path(os.fsdecode(output).strip())
    return path.resolve() if path.is_absolute() else (root / path).resolve()
