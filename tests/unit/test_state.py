from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from docstale.state import (
    AcknowledgementStore,
    BaselineStore,
    is_disabled,
    set_disabled,
)

if TYPE_CHECKING:
    from pathlib import Path

OLD = "1111111111111111"
NEW = "2222222222222222"


def test_reports_each_fingerprint_once_per_session(root: Path) -> None:
    store = AcknowledgementStore(root / "state")

    assert store.unreported(session_id="one", candidates={"README.md": OLD}) == (
        "README.md",
    )
    store.acknowledge(session_id="one", candidates={"README.md": OLD})
    assert store.unreported(session_id="one", candidates={"README.md": OLD}) == ()
    assert store.unreported(session_id="two", candidates={"README.md": OLD}) == (
        "README.md",
    )
    assert store.unreported(session_id="one", candidates={"README.md": NEW}) == (
        "README.md",
    )


def test_reports_only_documents_with_a_new_fingerprint(root: Path) -> None:
    store = AcknowledgementStore(root / "state")
    store.acknowledge(session_id="one", candidates={"README.md": OLD})

    assert store.unreported(
        session_id="one", candidates={"README.md": OLD, "docs/api.md": OLD}
    ) == ("docs/api.md",)


def test_a_document_that_stops_being_a_candidate_is_forgotten(root: Path) -> None:
    store = AcknowledgementStore(root / "state")
    store.acknowledge(session_id="one", candidates={"README.md": OLD})
    store.acknowledge(session_id="one", candidates={})

    assert store.unreported(session_id="one", candidates={"README.md": OLD}) == (
        "README.md",
    )


def test_nothing_to_report_writes_no_state(root: Path) -> None:
    store = AcknowledgementStore(root / "state")

    assert store.unreported(session_id="one", candidates={}) == ()
    store.acknowledge(session_id="one", candidates={})
    assert not (root / "state").exists()


def test_filtering_does_not_acknowledge_before_a_report_is_ready(root: Path) -> None:
    store = AcknowledgementStore(root / "state")
    for _ in range(2):
        assert store.unreported(session_id="one", candidates={"README.md": OLD}) == (
            "README.md",
        )
    assert not (root / "state").exists()
    store.acknowledge(session_id="one", candidates={"README.md": OLD})
    path = next((root / "state/sessions").glob("*.json"))
    modified = path.stat().st_mtime_ns
    store.acknowledge(session_id="one", candidates={"README.md": OLD})
    assert path.stat().st_mtime_ns == modified


def test_the_hook_switch_round_trips(root: Path) -> None:
    directory = root / "state"

    assert set_disabled(directory, disabled=True)
    assert is_disabled(directory)
    assert not set_disabled(directory, disabled=True)
    assert set_disabled(directory, disabled=False)
    assert not is_disabled(directory)


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"version": True, "documents": {}},
        {"version": 1, "paths": {"src/app.py": "missing"}},
        {"version": 2, "documents": []},
        {"version": 2, "documents": {"README.md": None}},
        {"version": 2, "documents": {"README.md": "not a fingerprint"}},
    ],
)
def test_baseline_rejects_invalid_state(root: Path, value: object) -> None:
    directory = root / "state"
    store = BaselineStore(directory)
    store.capture(session_id="one", fingerprints={"README.md": OLD})
    path = next((directory / "baselines").glob("*.json"))
    path.write_text(json.dumps(value), encoding="utf-8")

    assert store.load("one") is None


def test_baseline_round_trips_and_uses_safe_session_names(root: Path) -> None:
    directory = root / "state"
    store = BaselineStore(directory)
    session_id = "../outside/session"

    store.capture(session_id=session_id, fingerprints={"README.md": OLD})

    assert store.load(session_id) == {"README.md": OLD}
    path = next((directory / "baselines").glob("*.json"))
    assert len(path.stem) == 64
