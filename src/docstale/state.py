"""Private session fingerprints, reminder state, and hook disable state."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from docstale.fsutil import atomic_write
from docstale.git import git_metadata_path

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

STATE_VERSION = 2
BASELINE_VERSION = 2
_FINGERPRINT = re.compile(r"[0-9a-f]{16}")
DISABLED_MARKER = "disabled"
_DISABLED_NOTE = (
    "docstale is disabled for this checkout.\n"
    "Run `docstale enable` to enable its Stop hook.\n"
)


def default_state_directory(root: Path) -> Path:
    """Return the worktree-specific Git metadata directory for hook state."""
    return git_metadata_path(root, "docstale")


def is_disabled(state_directory: Path) -> bool:
    """Return whether the Stop hook is disabled for this checkout."""
    return (state_directory / DISABLED_MARKER).exists()


def set_disabled(state_directory: Path, *, disabled: bool) -> bool:
    """Set the Stop hook state and report whether it changed."""
    marker = state_directory / DISABLED_MARKER
    if disabled == marker.exists():
        return False
    if disabled:
        atomic_write(marker, _DISABLED_NOTE)
    else:
        marker.unlink(missing_ok=True)
    return True


def _session_path(state_directory: Path, session_id: str, *, category: str) -> Path:
    digest = hashlib.sha256(session_id.encode()).hexdigest()
    return state_directory / category / f"{digest}.json"


def _read_fingerprints(path: Path, version: int) -> dict[str, str] | None:
    """Read document fingerprints, or None for missing, corrupt, or old data."""
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        return None
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != version
        or not isinstance(documents := value.get("documents"), dict)
    ):
        return None
    fingerprints: dict[str, str] = {}
    for document, fingerprint in documents.items():
        if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
            return None
        fingerprints[document] = fingerprint
    return fingerprints


def _write_fingerprints(path: Path, version: int, values: Mapping[str, str]) -> None:
    content = json.dumps(
        {"version": version, "documents": dict(values)}, indent=2, sort_keys=True
    )
    atomic_write(path, content + "\n")


class BaselineStore:
    """Save document fingerprints at session start, apart from reminder state."""

    def __init__(self, state_directory: Path) -> None:
        """Create a store in worktree-specific Git metadata."""
        self.state_directory = state_directory

    def _path(self, session_id: str) -> Path:
        return _session_path(self.state_directory, session_id, category="baselines")

    def load(self, session_id: str) -> dict[str, str] | None:
        """Load a supported baseline, or return None for missing or corrupt data."""
        return _read_fingerprints(self._path(session_id), BASELINE_VERSION)

    def capture(self, *, session_id: str, fingerprints: Mapping[str, str]) -> None:
        """Atomically save fingerprints, which hold no file contents."""
        _write_fingerprints(self._path(session_id), BASELINE_VERSION, fingerprints)


class AcknowledgementStore:
    """Remember the fingerprint at which each document was last reported."""

    def __init__(self, state_directory: Path) -> None:
        """Create a store in a worktree-specific state directory."""
        self.state_directory = state_directory

    def _path(self, session_id: str) -> Path:
        return _session_path(self.state_directory, session_id, category="sessions")

    def unreported(
        self, *, session_id: str, candidates: Mapping[str, str]
    ) -> tuple[str, ...]:
        """Return candidates not yet reported, without changing reminder state."""
        reported = _read_fingerprints(self._path(session_id), STATE_VERSION) or {}
        return tuple(
            document
            for document, fingerprint in sorted(candidates.items())
            if reported.get(document) != fingerprint
        )

    def acknowledge(self, *, session_id: str, candidates: Mapping[str, str]) -> None:
        """Save candidates only after their review report is ready.

        Forget documents that stopped being candidates, so the same fingerprint
        can trigger another report if it returns later.
        """
        path = self._path(session_id)
        if (_read_fingerprints(path, STATE_VERSION) or {}) != candidates:
            _write_fingerprints(path, STATE_VERSION, candidates)

    def clear(self, session_id: str) -> None:
        """Clear reminder state for one session."""
        self._path(session_id).unlink(missing_ok=True)
