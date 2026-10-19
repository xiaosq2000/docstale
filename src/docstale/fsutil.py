"""Filesystem primitives used by hook state."""

from __future__ import annotations

from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """Replace a file in one step, preserving its mode when it already exists."""
    import tempfile  # noqa: PLC0415 — keeps ~2.6 ms off every agent hook fire

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = path.stat().st_mode
    except FileNotFoundError:
        existing_mode = None
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        if existing_mode is not None:
            temporary_path.chmod(existing_mode)
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
