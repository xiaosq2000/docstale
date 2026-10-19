from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from docstale.fsutil import atomic_write


def test_atomic_write_uses_utf8_and_lf_and_creates_parents(root: Path) -> None:
    target = root / "new/state.json"
    atomic_write(target, "ünïcode\nsecond line\n")
    assert target.read_bytes() == "ünïcode\nsecond line\n".encode()
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.posix_only
def test_atomic_write_preserves_existing_mode(root: Path) -> None:
    target = root / "state.json"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)
    atomic_write(target, "new\n")
    assert target.stat().st_mode & 0o777 == 0o640
    assert target.read_bytes() == b"new\n"


def test_atomic_write_removes_temporary_file_when_write_fails(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = root / "state.json"
    target.write_text("old", encoding="utf-8")
    temporary = tempfile.NamedTemporaryFile(  # noqa: SIM115
        "w", dir=root, delete=False, encoding="utf-8"
    )
    monkeypatch.setattr(temporary, "write", Mock(side_effect=OSError("write failed")))
    factory = Mock(return_value=temporary)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", factory)

    with pytest.raises(OSError, match="write failed"):
        atomic_write(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(root.iterdir()) == [target]
    assert factory.call_args.kwargs["newline"] == "\n"


@pytest.mark.parametrize("operation", ["chmod", "replace"])
def test_atomic_write_cleans_up_after_failure_before_replacement(
    root: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    target = root / "state.json"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(Path, operation, Mock(side_effect=OSError("failed")))

    with pytest.raises(OSError, match="failed"):
        atomic_write(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(root.iterdir()) == [target]


def test_atomic_write_does_not_stat_twice_or_unlink_after_replacement(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = root / "state.json"
    target.write_text("old", encoding="utf-8")
    original_stat = Path.stat
    stats: list[Path] = []

    def stat_once(path: Path, *, follow_symlinks: bool = True) -> object:
        if path == target:
            stats.append(path)
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", stat_once)
    unlink = Mock(side_effect=AssertionError("successful replacement needs no unlink"))
    monkeypatch.setattr(Path, "unlink", unlink)
    atomic_write(target, "new")
    assert stats == [target]
    unlink.assert_not_called()
