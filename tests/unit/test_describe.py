from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock, call

from docstale.cli import _describe
from docstale.config import Document
from docstale.lock import entry_line, render_lock
from docstale.match import Review

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_describe_reuses_head_committed_lock_untracked_paths_and_diffs(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    documents = tuple(Document(name, ("src/",)) for name in ("a.md", "b.md", "c.md"))
    lock = dict.fromkeys((document.path for document in documents), "1" * 16)
    committed = {"a.md": "2" * 16, "b.md": "3" * 16}
    history = {entry_line("a.md", committed["a.md"]): "old"}
    head = Mock(return_value="head")
    snapshot = Mock(return_value=render_lock(committed))
    untracked = Mock(return_value=("src/new.py",))
    changed = Mock(return_value=("src/new.py",))
    monkeypatch.setattr("docstale.cli.head_commit", head)
    monkeypatch.setattr("docstale.cli.file_at_commit", snapshot)
    monkeypatch.setattr("docstale.cli.untracked_paths", untracked)
    monkeypatch.setattr("docstale.cli.changed_worktree_paths", changed)
    monkeypatch.setattr(
        "docstale.cli.last_change_commit", lambda _root, _path, text: history.get(text)
    )

    reviews = _describe(root, documents, lock)

    assert [review.since for review in reviews] == ["old", "head", "head"]
    assert all(review.sources == ("src/new.py",) for review in reviews)
    head.assert_called_once_with(root)
    snapshot.assert_called_once_with(root, "head", "docstale.lock")
    untracked.assert_called_once_with(root)
    assert changed.call_args_list == [
        call(root, "old", untracked=("src/new.py",)),
        call(root, "head", untracked=("src/new.py",)),
    ]


def test_describe_caches_absent_head_before_the_first_commit(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = Mock(return_value=None)
    snapshot = Mock(side_effect=AssertionError("no committed tree exists"))
    monkeypatch.setattr("docstale.cli.head_commit", head)
    monkeypatch.setattr("docstale.cli.file_at_commit", snapshot)
    monkeypatch.setattr("docstale.cli.last_change_commit", Mock(return_value=None))
    monkeypatch.setattr(
        "docstale.cli.untracked_paths", Mock(return_value=("src/app.py",))
    )
    monkeypatch.setattr(
        "docstale.cli.changed_worktree_paths", Mock(return_value=("src/app.py",))
    )

    reviews = _describe(
        root,
        (Document("a.md", ("src/",)), Document("b.md", ("src/",))),
        {"a.md": "1" * 16, "b.md": "2" * 16},
    )

    assert all(review.since is None for review in reviews)
    head.assert_called_once_with(root)
    snapshot.assert_not_called()


def test_never_stamped_documents_need_no_history_queries(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = Mock(side_effect=AssertionError("unstamped documents need no history"))
    monkeypatch.setattr("docstale.cli.head_commit", head)
    assert _describe(root, (Document("a.md", ("src/",)),), {}) == (
        Review("a.md", (), stamped=False),
    )
