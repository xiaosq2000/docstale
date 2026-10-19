from __future__ import annotations

import json
import runpy
from typing import TYPE_CHECKING

import pytest

from docstale.cli import main
from docstale.lock import read_lock
from tests.support import commit_all, git, write_config

if TYPE_CHECKING:
    from pathlib import Path


def test_uncommitted_stamp_keeps_changes_before_head_in_the_report(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    assert main(["stamp", "--all"]) == 0
    commit_all(repository, "stamp")
    baseline = git(repository, "rev-parse", "HEAD")
    (repository / "src/app.py").write_text("v2", encoding="utf-8")
    commit_all(repository, "source change")
    assert main(["stamp", "README.md"]) == 0
    (repository / "src/new.py").write_text("new", encoding="utf-8")
    capsys.readouterr()

    assert main(["check", "--json"]) == 2

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["documents"] == [
        {
            "path": "README.md",
            "since": baseline,
            "sources": ["src/app.py", "src/new.py"],
            "stamped": True,
        }
    ]


@pytest.mark.parametrize("sources", [("src/", "other.py"), ("other.py",)])
def test_pattern_changes_explain_empty_source_lists_without_changing_json(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sources: tuple[str, ...],
) -> None:
    monkeypatch.chdir(repository)
    (repository / "other.py").write_text("unchanged", encoding="utf-8")
    assert main(["stamp", "--all"]) == 0
    commit_all(repository, "stamp and other source")
    baseline = git(repository, "rev-parse", "HEAD")
    write_config(repository, sources=sources)
    capsys.readouterr()

    assert main(["check"]) == 2
    text = capsys.readouterr().out
    assert "README.md (source list unavailable)" in text
    assert "changed since" not in text
    assert "Source patterns may have changed, or Git history may be incomplete." in text
    assert "Read the document and its configured sources directly." in text
    assert main(["check", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["documents"] == [
        {"path": "README.md", "since": baseline, "sources": [], "stamped": True}
    ]


def test_root_directory_template_does_not_watch_the_lock(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    write_config(repository, sources=("{dir}/", "docstale.lock"))
    commit_all(repository, "root directory sources")
    assert main(["stamp", "--all"]) == 0
    first = (repository / "docstale.lock").read_bytes()
    assert main(["check"]) == 0
    assert main(["stamp", "--all"]) == 0
    assert (repository / "docstale.lock").read_bytes() == first
    assert main(["check"]) == 0
    capsys.readouterr()
    (repository / "src/app.py").write_text("v2", encoding="utf-8")
    assert main(["check", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["documents"][0]["sources"] == [
        "src/app.py"
    ]


def test_unknown_stamp_paths_name_all_watching_documents_without_writing(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    (repository / "docstale.toml").write_text(
        '[documents]\n"README.md" = ["src/"]\n"api.md" = ["src/*.py"]\n',
        encoding="utf-8",
    )

    assert main(["stamp", "README.md", "./src\\app.py", "unknown.md"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "docstale error: not a configured document: "
        "`src/app.py` (watched by `README.md`, `api.md`), `unknown.md`\n"
    )
    assert not (repository / "docstale.lock").exists()


def test_orphan_warning_leaves_json_and_exit_code_unchanged(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    assert main(["stamp", "--all"]) == 0
    path = repository / "docstale.lock"
    with path.open("a", encoding="utf-8") as lock:
        lock.write('\n"removed.md" = "0000000000000000"\n')
    capsys.readouterr()

    assert main(["check", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"documents": [], "status": "pass"}
    assert captured.err == (
        "docstale warning: docstale.lock: `removed.md` is no longer configured. "
        "The next stamp will remove this entry\n"
    )
    assert "removed.md" in read_lock(path)
    assert main(["stamp", "README.md"]) == 0
    assert "removed.md" not in read_lock(path)
    capsys.readouterr()
    assert main(["check", "--json"]) == 0
    assert capsys.readouterr().err == ""


def test_check_orders_cascades_and_supports_batch_stamp(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    for name in ("a.md", "b.md", "z.md"):
        (repository / name).write_text("docs", encoding="utf-8")
    (repository / "docstale.toml").write_text(
        '[documents]\n"a.md" = ["b.md", "src/"]\n'
        '"b.md" = ["z.md", "src/"]\n"z.md" = ["src/"]\n',
        encoding="utf-8",
    )
    assert main(["check", "--json"]) == 2
    assert [
        item["path"] for item in json.loads(capsys.readouterr().out)["documents"]
    ] == ["z.md", "b.md", "a.md"]
    assert main(["stamp", "z.md", "b.md", "a.md"]) == 0
    assert capsys.readouterr().out == "stamped z.md\nstamped b.md\nstamped a.md\n"
    assert main(["check"]) == 0


def test_cycles_warn_without_failing_a_current_check(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    (repository / "api.md").write_text("api", encoding="utf-8")
    (repository / "docstale.toml").write_text(
        '[documents]\n"README.md" = ["api.md"]\n"api.md" = ["README.md"]\n',
        encoding="utf-8",
    )
    assert main(["stamp", "--all"]) == 0
    capsys.readouterr()

    assert main(["check", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"documents": [], "status": "pass"}
    assert "docstale warning:" in captured.err
    assert "document dependency cycle: `README.md`, `api.md`" in captured.err


def test_module_entrypoint_runs_the_cli(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(repository)
    monkeypatch.setattr("sys.argv", ["docstale", "stamp", "--all"])
    with pytest.raises(SystemExit, match="0"):
        runpy.run_module("docstale", run_name="__main__")
    assert capsys.readouterr().out == "stamped README.md\n"


def test_stamp_help_describes_multiple_document_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["stamp", "--help"])
    assert "One or more repository-relative document paths." in capsys.readouterr().out
