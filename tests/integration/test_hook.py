from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from docstale import state
from docstale.cli import main
from docstale.git import GitError
from docstale.state import BaselineStore, default_state_directory
from tests.support import add_submodule, commit_all, git, write_config

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class HookRunner:
    root: Path
    monkeypatch: pytest.MonkeyPatch
    capsys: pytest.CaptureFixture[str]

    def __call__(self, event: str = "Stop", session: str = "one") -> str:
        payload: dict[str, object] = {
            "hook_event_name": event,
            "session_id": session,
            "cwd": str(self.root),
        }
        if event == "Stop":
            payload["stop_hook_active"] = False
        self.monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        assert main(["hook"]) == 0
        captured = self.capsys.readouterr()
        assert captured.err == ""
        return captured.out

    def stamp(self, *arguments: str) -> None:
        self.monkeypatch.chdir(self.root)
        assert main(["stamp", *(arguments or ("--all",))]) == 0
        self.capsys.readouterr()


@pytest.fixture
def hook(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> HookRunner:
    """A repository whose documents are stamped in a committed lock."""
    runner = HookRunner(repository, monkeypatch, capsys)
    runner.stamp()
    commit_all(repository, "stamp")
    return runner


@pytest.mark.parametrize("staged", [False, True])
def test_existing_edits_do_not_prompt(hook: HookRunner, staged: bool) -> None:
    source = hook.root / "src/app.py"
    source.write_text("before the session", encoding="utf-8")
    (hook.root / "src/untracked.py").write_text("existing", encoding="utf-8")
    if staged:
        git(hook.root, "add", "src/app.py")
    assert hook("SessionStart") == ""
    source.touch()
    assert hook() == ""

    source.write_text("session edit", encoding="utf-8")
    response = json.loads(hook())
    assert response["decision"] == "block"
    # The reminder covers every change since the stamp, from any session.
    assert "  src/app.py\n  src/untracked.py\n" in response["reason"]
    assert "docstale-reviewer" in response["reason"]
    assert "docstale stamp <document>" in response["reason"]
    assert hook() == ""


def test_missing_baseline_initializes_silently(hook: HookRunner) -> None:
    source = hook.root / "src/app.py"
    source.write_text("existing", encoding="utf-8")
    assert hook() == ""
    assert hook() == ""
    source.write_text("later edit", encoding="utf-8")
    assert json.loads(hook())["decision"] == "block"


def test_unrelated_edits_are_silent(hook: HookRunner) -> None:
    assert hook("SessionStart") == ""
    (hook.root / "notes.txt").write_text("notes", encoding="utf-8")
    assert hook() == ""


def test_stamping_records_the_review_and_editing_does_not(hook: HookRunner) -> None:
    assert hook("SessionStart") == ""
    (hook.root / "src/app.py").write_text("new source", encoding="utf-8")
    (hook.root / "README.md").write_text("session documentation", encoding="utf-8")
    assert "README.md (changed since " in json.loads(hook())["reason"]

    hook.stamp("README.md")
    assert hook() == ""
    (hook.root / "src/app.py").write_text("another source edit", encoding="utf-8")
    assert json.loads(hook())["decision"] == "block"


def test_unstamped_documents_are_named(hook: HookRunner) -> None:
    (hook.root / "docstale.lock").unlink()
    assert hook("SessionStart") == ""
    (hook.root / "src/app.py").write_text("v2", encoding="utf-8")
    assert "README.md (never stamped)" in json.loads(hook())["reason"]


@pytest.mark.parametrize("change", ["add", "delete", "rename"])
def test_path_changes_are_reviewed(hook: HookRunner, change: str) -> None:
    assert hook("SessionStart") == ""
    source = hook.root / "src/app.py"
    if change == "add":
        (hook.root / "src/new.py").write_text("new", encoding="utf-8")
    elif change == "delete":
        source.unlink()
    else:
        source.rename(hook.root / "renamed.py")
    response = json.loads(hook())
    assert response["decision"] == "block"
    assert ("src/new.py" if change == "add" else "src/app.py") in response["reason"]


def test_reverting_clears_acknowledgement_but_keeps_baseline(hook: HookRunner) -> None:
    source = hook.root / "src/app.py"
    assert hook("SessionStart") == ""
    source.write_text("v2", encoding="utf-8")
    assert hook()
    assert hook() == ""
    source.write_text("v1", encoding="utf-8")
    assert hook() == ""
    source.write_text("v2", encoding="utf-8")
    assert hook()
    source.write_text("v3", encoding="utf-8")
    assert hook()


def test_committing_session_changes_does_not_hide_them(hook: HookRunner) -> None:
    assert hook("SessionStart") == ""
    (hook.root / "src/app.py").write_text("committed edit", encoding="utf-8")
    commit_all(hook.root, "session changes")
    assert json.loads(hook())["decision"] == "block"


def test_committing_existing_changes_does_not_prompt(hook: HookRunner) -> None:
    (hook.root / "src/app.py").write_text("existing edit", encoding="utf-8")
    assert hook("SessionStart") == ""
    commit_all(hook.root, "existing changes")
    assert hook() == ""


def test_sessions_have_independent_preserved_baselines(hook: HookRunner) -> None:
    assert hook("SessionStart", "one") == ""
    (hook.root / "src/app.py").write_text("v2", encoding="utf-8")
    assert hook("SessionStart", "two") == ""
    assert hook("Stop", "two") == ""
    # SessionStart also fires for resume and compaction, with the same ID.
    assert hook("SessionStart", "one") == ""
    assert hook("Stop", "one")
    assert hook("SessionStart", "one") == ""
    assert hook("Stop", "one") == ""


@pytest.mark.parametrize(
    "corrupt",
    [
        "{",
        '{"version": 99, "documents": {}}',
        '{"version": 1, "paths": {"src/app.py": "missing"}}',
    ],
)
def test_corrupt_baseline_is_replaced_silently(hook: HookRunner, corrupt: str) -> None:
    assert hook("SessionStart") == ""
    directory = default_state_directory(hook.root) / "baselines"
    next(directory.glob("*.json")).write_text(corrupt, encoding="utf-8")
    (hook.root / "src/app.py").write_text("v2", encoding="utf-8")
    assert hook() == ""
    (hook.root / "src/app.py").write_text("v3", encoding="utf-8")
    assert hook()


def test_configuration_changes_count_when_they_change_matched_files(
    hook: HookRunner,
) -> None:
    (hook.root / "other.py").write_text("v1", encoding="utf-8")
    assert hook("SessionStart") == ""
    write_config(hook.root, sources=("./src/",))
    assert hook() == ""
    write_config(hook.root, sources=("src/", "other.py"))
    assert "README.md" in json.loads(hook())["reason"]


def test_ignored_files_are_excluded(hook: HookRunner) -> None:
    (hook.root / ".gitignore").write_text("src/ignored.py\n", encoding="utf-8")
    hook.stamp()
    assert hook("SessionStart") == ""
    (hook.root / "src/ignored.py").write_text("ignored", encoding="utf-8")
    assert hook() == ""


def test_hook_works_before_first_commit(
    uncommitted_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hook = HookRunner(uncommitted_repository, monkeypatch, capsys)
    assert hook("SessionStart") == ""
    assert hook() == ""
    (hook.root / "src/app.py").write_text("v2", encoding="utf-8")
    assert hook()


def test_linked_worktree_has_its_own_baseline(hook: HookRunner, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    git(hook.root, "worktree", "add", "-b", "linked", str(linked))
    other = HookRunner(linked, hook.monkeypatch, hook.capsys)
    assert hook("SessionStart") == ""
    (linked / "src/app.py").write_text("before linked session", encoding="utf-8")
    assert other("SessionStart") == ""
    assert other() == ""
    assert hook() == ""
    (linked / "src/app.py").write_text("linked session edit", encoding="utf-8")
    assert other()
    assert hook() == ""
    assert default_state_directory(linked) != default_state_directory(hook.root)


def test_a_submodule_commit_prompts(
    hook: HookRunner, tmp_path_factory: pytest.TempPathFactory
) -> None:
    submodule = add_submodule(hook.root, tmp_path_factory.mktemp("library"))
    write_config(hook.root, sources=("vendor/lib/",))
    hook.stamp()
    assert hook("SessionStart") == ""
    (submodule / "lib.txt").write_text("edited", encoding="utf-8")
    assert hook() == ""
    commit_all(submodule, "second")
    assert "vendor/lib" in json.loads(hook())["reason"]


@pytest.mark.posix_only
def test_mode_changes_alone_do_not_prompt(hook: HookRunner) -> None:
    source = hook.root / "src/app.py"
    source.chmod(0o644)
    assert hook("SessionStart") == ""
    source.chmod(0o755)
    assert hook() == ""


@pytest.mark.posix_only
def test_symlink_targets_are_compared_without_reading_them(hook: HookRunner) -> None:
    source = hook.root / "src/app.py"
    source.unlink()
    source.symlink_to("missing-target")
    assert hook("SessionStart") == ""
    assert hook() == ""
    source.unlink()
    source.symlink_to("another-missing-target")
    assert hook()


def test_active_stop_never_reads_git_or_state(hook: HookRunner) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("active Stop must return before accessing Git or state")

    hook.monkeypatch.setattr("docstale.cli.resolve_root", fail)
    hook.monkeypatch.setattr(BaselineStore, "load", fail)
    hook.monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "one",
                    "cwd": str(hook.root),
                    "stop_hook_active": True,
                }
            )
        ),
    )
    assert main(["hook"]) == 0
    captured = hook.capsys.readouterr()
    assert captured.out == captured.err == ""


def test_resumed_session_start_does_not_read_files(hook: HookRunner) -> None:
    assert hook("SessionStart") == ""

    def fail(_root: Path) -> None:
        raise AssertionError("a resumed session keeps its baseline")

    hook.monkeypatch.setattr("docstale.cli.object_ids", fail)
    assert hook("SessionStart") == ""


def test_session_start_failure_uses_stderr(hook: HookRunner) -> None:
    def fail(_root: str) -> None:
        raise GitError("unavailable repository")

    hook.monkeypatch.setattr("docstale.cli.resolve_root", fail)
    hook.monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "one",
                    "cwd": str(hook.root),
                    "hook_event_name": "SessionStart",
                }
            )
        ),
    )
    assert main(["hook"]) == 0
    captured = hook.capsys.readouterr()
    assert captured.out == ""
    assert "unavailable repository" in captured.err


@pytest.mark.parametrize("event", ["SessionStart", "Stop"])
def test_disabled_hook_does_not_create_a_baseline(hook: HookRunner, event: str) -> None:
    directory = default_state_directory(hook.root)
    state.set_disabled(directory, disabled=True)
    assert hook(event) == ""
    assert not (directory / "baselines").exists()


@pytest.mark.parametrize("event", ["SessionStart", "Stop"])
def test_missing_config_does_not_create_a_baseline(
    hook: HookRunner, event: str
) -> None:
    (hook.root / "docstale.toml").unlink()
    assert hook(event) == ""
    assert not (default_state_directory(hook.root) / "baselines").exists()


@pytest.mark.parametrize("already_reported", [False, True])
def test_failed_description_does_not_acknowledge_unreported_fingerprints(
    hook: HookRunner, already_reported: bool
) -> None:
    assert hook("SessionStart") == ""
    source = hook.root / "src/app.py"
    if already_reported:
        source.write_text("v2", encoding="utf-8")
        assert hook()
    directory = default_state_directory(hook.root)
    baseline = next((directory / "baselines").glob("*.json"))
    baseline_content = baseline.read_bytes()
    before = {
        path.name: path.read_bytes() for path in (directory / "sessions").glob("*")
    }
    source.write_text("v3", encoding="utf-8")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise GitError("description unavailable")

    with hook.monkeypatch.context() as patch:
        patch.setattr("docstale.cli.changed_worktree_paths", fail)
        assert "description unavailable" in json.loads(hook())["reason"]
    after = {
        path.name: path.read_bytes() for path in (directory / "sessions").glob("*")
    }
    assert after == before
    assert baseline.read_bytes() == baseline_content
    assert "README.md" in json.loads(hook())["reason"]
    assert hook() == ""


@pytest.mark.parametrize("session", ["pi:one", "claude:one", "codex:one"])
def test_hook_guidance_respects_client_and_user_authorization(
    hook: HookRunner, session: str
) -> None:
    assert hook("SessionStart", session) == ""
    (hook.root / "src/app.py").write_text("v2", encoding="utf-8")
    reason = json.loads(hook("Stop", session))["reason"]
    assert ("docstale-reviewer" in reason) is (not session.startswith("pi:"))
    assert "read-only response or prohibits file edits" in reason
    assert "only report the affected documents" in reason
    assert "Do not edit files or run `docstale stamp`." in reason
    assert "Pass one or more document paths." in reason
    assert "New files that Git does not track do not appear in that diff." in reason
    assert "Read those files directly." in reason


def test_hook_orders_upstream_documents_before_downstream_documents(
    hook: HookRunner,
) -> None:
    for name in ("a.md", "b.md", "z.md"):
        (hook.root / name).write_text("docs", encoding="utf-8")
    (hook.root / "docstale.toml").write_text(
        '[documents]\n"a.md" = ["b.md", "src/"]\n'
        '"b.md" = ["z.md", "src/"]\n"z.md" = ["src/"]\n',
        encoding="utf-8",
    )
    hook.stamp()
    assert hook("SessionStart") == ""
    (hook.root / "src/app.py").write_text("v2", encoding="utf-8")
    reason = json.loads(hook())["reason"]
    assert reason.index("z.md (") < reason.index("b.md (") < reason.index("a.md (")


def test_stop_reports_a_git_failure(hook: HookRunner) -> None:
    assert hook("SessionStart") == ""

    def fail(_root: Path) -> None:
        raise GitError("object ids are unavailable")

    hook.monkeypatch.setattr("docstale.cli.object_ids", fail)
    response = json.loads(hook())
    assert response["decision"] == "block"
    assert "object ids are unavailable" in response["reason"]


@pytest.mark.posix_only
@pytest.mark.parametrize("name", ["line\nbreak.py", "a:b.py", "back\\slash.py"])
def test_baseline_preserves_git_file_names(hook: HookRunner, name: str) -> None:
    source = hook.root / "src" / name
    source.write_text("v1", encoding="utf-8")
    assert hook("SessionStart") == ""
    assert hook() == ""
    source.write_text("v2", encoding="utf-8")
    assert json.loads(hook())["decision"] == "block"
