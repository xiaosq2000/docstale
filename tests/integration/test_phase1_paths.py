from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from docstale.cli import main
from tests.support import add_submodule, commit_all, git

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("directory", ["package name", "package [name]"])
def test_directory_templates_match_submodules_below_escaped_directories(
    repository: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    directory: str,
) -> None:
    add_submodule(repository, tmp_path_factory.mktemp("library"))
    package = repository / "packages" / directory
    package.mkdir(parents=True)
    (package / "README.md").write_text("package docs", encoding="utf-8")
    path = f"packages/{directory}/vendor"
    git(repository, "mv", "vendor/lib", path)
    (repository / "docstale.toml").write_text(
        '[documents]\n"packages/*/README.md" = ["{dir}/vendor/"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(repository)
    assert main(["stamp", "--all"]) == 0
    commit_all(repository, "stamp package")
    capsys.readouterr()
    submodule = repository / path
    (submodule / "lib.txt").write_text("v2", encoding="utf-8")
    commit_all(submodule, "library change")

    assert main(["check", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["documents"][0]["sources"] == [path]


@pytest.mark.posix_only
@pytest.mark.parametrize("directory", ["package name", "package [name]"])
def test_directory_templates_match_symlinks_below_escaped_directories(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    directory: str,
) -> None:
    package = repository / "packages" / directory
    package.mkdir(parents=True)
    (package / "README.md").write_text("package docs", encoding="utf-8")
    link = package / "vendor"
    link.symlink_to("missing-target")
    (repository / "docstale.toml").write_text(
        '[documents]\n"packages/*/README.md" = ["{dir}/vendor/"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(repository)
    assert main(["stamp", "--all"]) == 0
    commit_all(repository, "stamp package")
    capsys.readouterr()
    link.unlink()
    link.symlink_to("another-target")

    assert main(["check", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["documents"][0]["sources"] == [
        f"packages/{directory}/vendor"
    ]


def test_shallow_history_explains_unavailable_changed_sources(
    repository: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    assert main(["stamp", "--all"]) == 0
    commit_all(repository, "stamp")
    (repository / "src/app.py").write_text("v2", encoding="utf-8")
    commit_all(repository, "source change")
    shallow = tmp_path / "shallow"
    git(repository, "clone", "--depth=1", repository.as_uri(), str(shallow))
    monkeypatch.chdir(shallow)
    capsys.readouterr()

    assert main(["check"]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "README.md (source list unavailable)" in captured.out
    assert "Git history may be incomplete." in captured.out
    assert "changed since" not in captured.out
