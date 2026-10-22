from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import pytest

from docstale.cli import main
from docstale.lock import entry_line
from tests.support import commit_all, git, write_config

if TYPE_CHECKING:
    from pathlib import Path

BROKEN_CONFIG = "[documents\n"
PACKAGE_CONFIG = '[documents]\n"packages/*/README.md" = ["{dir}/"]\n'


def _package_repository(root: Path) -> Path:
    """Commit one package with a README that watches its own directory."""
    (root / "packages/a/src").mkdir(parents=True)
    (root / "packages/a/README.md").write_text("docs", encoding="utf-8")
    (root / "packages/a/src/app.py").write_text("v1", encoding="utf-8")
    (root / "docstale.toml").write_text(PACKAGE_CONFIG, encoding="utf-8")
    commit_all(root)
    return root / "packages/a/src/app.py"


def _hook_payload(
    root: Path,
    *,
    session_id: str = "session-1",
    active: bool = False,
    event: str = "Stop",
) -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "cwd": str(root),
            "stop_hook_active": active,
            "hook_event_name": event,
        }
    )


def _start_session(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(_hook_payload(root, event="SessionStart"))
    )
    assert main(["hook"]) == 0
    assert capsys.readouterr().out == ""


def _run(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, str]:
    exit_code = main(list(arguments))
    return exit_code, capsys.readouterr().out


def test_json_check_has_a_small_stable_contract(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(repository)
    assert _run(capsys, "stamp", "--all") == (0, "stamped README.md\n")
    commit_all(repository, "stamp")
    stamp_commit = git(repository, "rev-parse", "HEAD")
    (repository / "src/app.py").write_text("v2", encoding="utf-8")
    commit_all(repository, "change")
    (repository / "src/new.py").write_text("new", encoding="utf-8")

    exit_code, output = _run(capsys, "check", "--json")

    assert exit_code == 2
    assert json.loads(output) == {
        "status": "review_required",
        "documents": [
            {
                "path": "README.md",
                "since": stamp_commit,
                "sources": ["src/app.py", "src/new.py"],
                "stamped": True,
            }
        ],
    }


def test_check_lists_documents_that_were_never_stamped(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(repository)

    exit_code, output = _run(capsys, "check", "--json")

    assert exit_code == 2
    assert json.loads(output)["documents"] == [
        {"path": "README.md", "since": None, "sources": [], "stamped": False}
    ]


def test_a_stamp_lasts_until_the_sources_change(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = repository / "src/app.py"
    monkeypatch.chdir(repository)
    assert _run(capsys, "stamp", "README.md")[0] == 0
    assert _run(capsys, "check") == (0, "docstale: no documents need review\n")

    (repository / "README.md").write_text("edited docs", encoding="utf-8")
    assert _run(capsys, "check")[0] == 0

    source.write_text("v2", encoding="utf-8")
    exit_code, output = _run(capsys, "check")
    assert exit_code == 2
    assert "README.md (changed since " in output
    assert "  src/app.py" in output

    source.write_text("v1", encoding="utf-8")
    assert _run(capsys, "check")[0] == 0


def test_check_expands_glob_keys_and_directory_templates(
    empty_repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _package_repository(empty_repository)
    monkeypatch.chdir(empty_repository)
    assert _run(capsys, "stamp", "--all")[0] == 0
    source.write_text("v2", encoding="utf-8")

    exit_code, output = _run(capsys, "check", "--json")

    assert exit_code == 2
    (document,) = json.loads(output)["documents"]
    assert document["path"] == "packages/a/README.md"
    assert document["sources"] == ["packages/a/src/app.py"]


def test_a_conflicting_lock_entry_needs_review(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(repository)
    assert _run(capsys, "stamp", "--all")[0] == 0
    lock = repository / "docstale.lock"
    entry = lock.read_text(encoding="utf-8").splitlines()[-1]
    other = entry_line("README.md", "0" * 16)
    lock.write_text(
        f"<<<<<<< ours\n{entry}\n=======\n{other}\n>>>>>>> theirs\n", encoding="utf-8"
    )
    assert _run(capsys, "check")[0] == 2

    assert _run(capsys, "stamp", "README.md")[0] == 0
    assert "<<<<<<<" not in lock.read_text(encoding="utf-8")
    assert _run(capsys, "check")[0] == 0


def test_stamp_drops_entries_for_documents_no_longer_configured(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = repository / "docstale.lock"
    lock.write_text('"docs/removed.md" = "0000000000000000"\n', encoding="utf-8")
    monkeypatch.chdir(repository)

    assert _run(capsys, "stamp", "--all")[0] == 0

    assert "docs/removed.md" not in lock.read_text(encoding="utf-8")
    assert '"README.md" = ' in lock.read_text(encoding="utf-8")


def test_stamp_requires_configured_documents_or_all(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(repository)

    for arguments in (
        ["stamp"],
        ["stamp", "README.md", "--all"],
        ["stamp", "docs/missing.md"],
    ):
        assert main(arguments) == 1
        assert "docstale error:" in capsys.readouterr().err
    assert not (repository / "docstale.lock").exists()


def test_check_always_confirms_a_pass(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(repository)
    assert _run(capsys, "stamp", "--all")[0] == 0

    exit_code, output = _run(capsys, "check")

    assert exit_code == 0
    assert "no documents need review" in output


def test_hook_blocks_once_for_the_same_session_state(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _start_session(repository, capsys, monkeypatch)
    (repository / "src/app.py").write_text("v2", encoding="utf-8")
    payload = _hook_payload(repository)

    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    first_exit = main(["hook"])
    first_output = capsys.readouterr().out

    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    second_exit = main(["hook"])
    second_output = capsys.readouterr().out

    assert first_exit == 0
    assert json.loads(first_output)["decision"] == "block"
    assert "README.md" in json.loads(first_output)["reason"]
    assert second_exit == 0
    assert second_output == ""


def test_hook_expands_glob_keys(
    empty_repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _package_repository(empty_repository)
    _start_session(empty_repository, capsys, monkeypatch)
    source.write_text("v2", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(_hook_payload(empty_repository)))

    exit_code = main(["hook"])

    assert exit_code == 0
    assert "packages/a/README.md" in json.loads(capsys.readouterr().out)["reason"]


def test_active_stop_hook_never_blocks_again(
    empty_repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (empty_repository / "docstale.toml").write_text(BROKEN_CONFIG, encoding="utf-8")
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(_hook_payload(empty_repository, active=True))
    )

    exit_code = main(["hook"])

    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_hook_resolves_a_repository_from_a_nested_payload_cwd(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _start_session(repository, capsys, monkeypatch)
    (repository / "src/app.py").write_text("v2", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(_hook_payload(repository / "src")))

    exit_code = main(["hook"])

    assert exit_code == 0
    assert "README.md" in json.loads(capsys.readouterr().out)["reason"]


def test_hook_is_silent_without_a_configuration(
    empty_repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(_hook_payload(empty_repository)))

    exit_code = main(["hook"])

    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_hook_reports_a_broken_configuration_as_blocking_json(
    empty_repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (empty_repository / "docstale.toml").write_text(BROKEN_CONFIG, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(_hook_payload(empty_repository)))

    exit_code = main(["hook"])

    response = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert response["decision"] == "block"
    assert "TOML parse error" in response["reason"]


def test_disabling_affects_the_hook_but_not_manual_checks(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (repository / "src/app.py").write_text("v2", encoding="utf-8")
    monkeypatch.chdir(repository)

    assert main(["disable"]) == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(_hook_payload(repository)))
    assert main(["hook"]) == 0
    assert capsys.readouterr().out == ""

    assert main(["check"]) == 2
    assert "README.md" in capsys.readouterr().out


def test_check_fails_when_a_document_does_not_exist(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(repository, document="docs/missing.md")
    monkeypatch.chdir(repository)

    exit_code = main(["check"])

    assert exit_code == 1
    assert "`docs/missing.md` does not exist" in capsys.readouterr().err


def test_check_warns_about_unmatched_sources_without_failing(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(repository, sources=("src/", "gone/"))
    monkeypatch.chdir(repository)
    assert main(["stamp", "--all"]) == 0
    capsys.readouterr()

    exit_code = main(["check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "docstale: no documents need review\n"
    (warning,) = captured.err.splitlines()
    assert warning.startswith("docstale warning: ")
    assert warning.endswith(
        "docstale.toml: document `README.md` source `gone/` matches no file"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["check"],
        ["check", "--json"],
        ["stamp", "--all"],
        ["disable"],
        ["enable"],
    ],
)
def test_manual_commands_fail_outside_a_git_repository(
    root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    monkeypatch.chdir(root)
    assert main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "docstale error:" in captured.err
    assert "not a git repository" in captured.err


def test_manual_error_uses_stderr_and_exit_one(
    empty_repository: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(empty_repository)

    exit_code = main(["check"])

    assert exit_code == 1
    assert "docstale error:" in capsys.readouterr().err
