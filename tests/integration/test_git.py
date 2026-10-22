from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from docstale.git import (
    GitError,
    NotGitRepositoryError,
    changed_worktree_paths,
    file_at_commit,
    head_commit,
    last_change_commit,
    object_ids,
    resolve_root,
)
from tests.support import add_submodule, commit_all, git

if TYPE_CHECKING:
    from pathlib import Path


def _blob_id(root: Path, content: bytes) -> str:
    """Return the id Git gives these exact bytes, without filters."""
    result = subprocess.run(
        ["git", "-C", str(root), "hash-object", "--stdin", "--no-filters"],
        input=content,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode().strip()


def test_reports_staged_and_untracked_paths_before_the_first_commit(
    empty_repository: Path,
) -> None:
    (empty_repository / "staged.txt").write_text("new", encoding="utf-8")
    git(empty_repository, "add", "staged.txt")
    (empty_repository / "untracked.txt").write_text("new", encoding="utf-8")

    assert changed_worktree_paths(empty_repository) == ("staged.txt", "untracked.txt")


def test_reports_staged_unstaged_untracked_and_deleted_paths(
    empty_repository: Path,
) -> None:
    for name in ("staged.txt", "unstaged.txt", "deleted.txt"):
        (empty_repository / name).write_text("old", encoding="utf-8")
    commit_all(empty_repository)

    (empty_repository / "staged.txt").write_text("new", encoding="utf-8")
    git(empty_repository, "add", "staged.txt")
    (empty_repository / "unstaged.txt").write_text("new", encoding="utf-8")
    (empty_repository / "untracked.txt").write_text("new", encoding="utf-8")
    (empty_repository / "deleted.txt").unlink()

    assert changed_worktree_paths(empty_repository) == (
        "deleted.txt",
        "staged.txt",
        "unstaged.txt",
        "untracked.txt",
    )


def test_reports_paths_changed_since_a_commit(empty_repository: Path) -> None:
    (empty_repository / "one.txt").write_text("one", encoding="utf-8")
    commit_all(empty_repository)
    base = git(empty_repository, "rev-parse", "HEAD")
    (empty_repository / "two.txt").write_text("two", encoding="utf-8")
    commit_all(empty_repository, "second")
    (empty_repository / "three.txt").write_text("three", encoding="utf-8")

    assert changed_worktree_paths(empty_repository, base) == ("three.txt", "two.txt")


@pytest.mark.posix_only
def test_preserves_newline_in_file_name(empty_repository: Path) -> None:
    (empty_repository / "initial.txt").write_text("initial", encoding="utf-8")
    commit_all(empty_repository)
    unusual = "line\nbreak.txt"
    (empty_repository / unusual).write_text("content", encoding="utf-8")

    assert changed_worktree_paths(empty_repository) == (unusual,)


def test_reports_a_submodule_commit_but_not_edits_inside_it(
    empty_repository: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    submodule = add_submodule(empty_repository, tmp_path_factory.mktemp("library"))

    (submodule / "lib.txt").write_text("edited", encoding="utf-8")
    assert changed_worktree_paths(empty_repository) == ()

    commit_all(submodule, "second")
    assert changed_worktree_paths(empty_repository) == ("vendor/lib",)


def test_head_commit_is_none_before_the_first_commit(empty_repository: Path) -> None:
    assert head_commit(empty_repository) is None

    (empty_repository / "one.txt").write_text("one", encoding="utf-8")
    commit_all(empty_repository)

    assert head_commit(empty_repository) == git(empty_repository, "rev-parse", "HEAD")


def test_finds_the_commit_that_last_added_a_text(empty_repository: Path) -> None:
    assert last_change_commit(empty_repository, "notes.txt", "alpha") is None
    notes = empty_repository / "notes.txt"
    notes.write_text("alpha\n", encoding="utf-8")
    commit_all(empty_repository)
    added = git(empty_repository, "rev-parse", "HEAD")
    notes.write_text("alpha\nbeta\n", encoding="utf-8")
    commit_all(empty_repository, "second")

    assert last_change_commit(empty_repository, "notes.txt", "alpha") == added
    assert last_change_commit(empty_repository, "notes.txt", "gamma") is None


def test_object_ids_use_git_ids_for_tracked_changed_and_untracked_files(
    empty_repository: Path,
) -> None:
    root = empty_repository
    for name in ("same.txt", "edited.txt", "deleted.txt"):
        (root / name).write_text(name, encoding="utf-8")
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    commit_all(root)
    (root / "edited.txt").write_text("new content", encoding="utf-8")
    (root / "deleted.txt").unlink()
    (root / "untracked.txt").write_text("untracked", encoding="utf-8")
    (root / "ignored.txt").write_text("ignored", encoding="utf-8")

    ids = object_ids(root)

    assert ids == {
        ".gitignore": _blob_id(root, b"ignored.txt\n"),
        "edited.txt": _blob_id(root, b"new content"),
        "same.txt": _blob_id(root, b"same.txt"),
        "untracked.txt": _blob_id(root, b"untracked"),
    }


def test_object_ids_hash_a_conflicted_file_from_the_working_tree(
    empty_repository: Path,
) -> None:
    root = empty_repository
    notes = root / "notes.txt"
    notes.write_text("base\n", encoding="utf-8")
    commit_all(root)
    git(root, "switch", "-q", "-c", "other")
    notes.write_text("theirs\n", encoding="utf-8")
    commit_all(root, "theirs")
    git(root, "switch", "-q", "-")
    notes.write_text("ours\n", encoding="utf-8")
    commit_all(root, "ours")
    with pytest.raises(subprocess.CalledProcessError):
        git(root, "merge", "-q", "other")

    ids = object_ids(root)

    # Git's filters apply, so line endings do not change the id.
    assert ids == {"notes.txt": git(root, "hash-object", "--", "notes.txt")}
    sides = {git(root, "rev-parse", f":{stage}:notes.txt") for stage in (1, 2, 3)}
    assert ids["notes.txt"] not in sides


def test_object_ids_apply_line_ending_conversion(empty_repository: Path) -> None:
    git(empty_repository, "config", "core.autocrlf", "true")
    (empty_repository / "notes.txt").write_bytes(b"one\r\ntwo\r\n")

    assert object_ids(empty_repository) == {
        "notes.txt": _blob_id(empty_repository, b"one\ntwo\n")
    }


@pytest.mark.posix_only
def test_object_ids_hash_a_symlink_by_its_target(empty_repository: Path) -> None:
    (empty_repository / "target.txt").write_text("target", encoding="utf-8")
    (empty_repository / "link").symlink_to("target.txt")
    untracked = object_ids(empty_repository)["link"]
    commit_all(empty_repository)

    assert untracked == git(empty_repository, "rev-parse", ":link")
    assert untracked == _blob_id(empty_repository, b"target.txt")


def test_object_ids_follow_the_checked_out_submodule_commit(
    empty_repository: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    submodule = add_submodule(empty_repository, tmp_path_factory.mktemp("library"))
    recorded = git(empty_repository, "rev-parse", ":vendor/lib")
    assert object_ids(empty_repository)["vendor/lib"] == recorded

    (submodule / "lib.txt").write_text("edited", encoding="utf-8")
    assert object_ids(empty_repository)["vendor/lib"] == recorded

    commit_all(submodule, "second")
    assert object_ids(empty_repository)["vendor/lib"] == git(
        submodule, "rev-parse", "HEAD"
    )


def test_committed_file_reading_distinguishes_absence_and_git_errors(
    repository: Path,
) -> None:
    commit = git(repository, "rev-parse", "HEAD")
    assert file_at_commit(repository, commit, "README.md") == "docs"
    assert file_at_commit(repository, commit, "docstale.lock") is None
    with pytest.raises(GitError):
        file_at_commit(repository, "invalid-commit", "README.md")


def test_committed_files_must_be_utf8(repository: Path) -> None:
    (repository / "bad.lock").write_bytes(bytes([255]))
    commit_all(repository, "invalid encoding")
    with pytest.raises(GitError, match="not UTF-8 text"):
        file_at_commit(repository, git(repository, "rev-parse", "HEAD"), "bad.lock")


def test_changed_paths_reuse_supplied_untracked_paths(repository: Path) -> None:
    (repository / "new.py").write_text("new", encoding="utf-8")
    assert changed_worktree_paths(repository, untracked=()) == ()
    assert changed_worktree_paths(repository, untracked=("new.py",)) == ("new.py",)
    with pytest.raises(GitError):
        changed_worktree_paths(repository, "invalid-commit", untracked=())


def test_git_execution_errors_are_reported(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("git unavailable")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(GitError, match="could not execute git: git unavailable"):
        resolve_root(str(root))


def test_object_ids_skip_directories_that_replace_a_tracked_file(
    repository: Path,
) -> None:
    source = repository / "src/app.py"
    source.unlink()
    source.mkdir()
    assert "src/app.py" not in object_ids(repository)
    git(source, "init", "-q")
    assert "src/app.py" not in object_ids(repository)


@pytest.mark.parametrize(
    "diagnostic",
    [
        b"fatal: not a git repository (or any of the parent directories): .git\n",
        b"fatal: not a git repository (or any parent up to mount point /)\n"
        b"Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set).\n",
        b"trace: git rev-parse --show-toplevel\n"
        b"fatal: not a git repository (or any of the parent directories): .git\n",
    ],
)
def test_discovery_classifies_missing_repositories_with_a_fixed_locale(
    root: Path, monkeypatch: pytest.MonkeyPatch, diagnostic: bytes
) -> None:
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")

    def run(
        command: list[str], **options: object
    ) -> subprocess.CompletedProcess[bytes]:
        assert options["env"] == {**os.environ, "LC_ALL": "C"}
        return subprocess.CompletedProcess(command, 128, stdout=b"", stderr=diagnostic)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(NotGitRepositoryError):
        resolve_root(str(root))
    assert os.environ["LC_ALL"] == "zh_CN.UTF-8"


def test_git_failure_is_not_an_empty_change_set(root: Path) -> None:
    with pytest.raises(NotGitRepositoryError):
        resolve_root(str(root))
