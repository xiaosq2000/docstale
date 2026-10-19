"""Repository-relative path normalization and matching."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import PureWindowsPath

from pathspec.patterns.gitignore.basic import GitIgnoreBasicPattern


def normalize_path(path: str, *, keep_trailing_slash: bool = False) -> str:
    """Normalize a repository-relative path to slash-separated form."""
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if keep_trailing_slash:
        return normalized
    return normalized.rstrip("/")


def has_glob(pattern: str) -> bool:
    """Return whether a pattern contains supported glob syntax."""
    return any(character in pattern for character in "*?[")


def relative_path_error(location: str, raw_path: str, normalized: str) -> str | None:
    """Return why a configured path is not repository-relative, or None if it is."""
    if (
        raw_path.startswith("/")
        or normalized.startswith("/")
        or PureWindowsPath(raw_path).is_absolute()
    ):
        return f"{location} must be repository-relative"

    without_slash = normalized.rstrip("/")
    if not without_slash:
        return f"{location} must not normalize to an empty path"
    if any(segment in {".", ".."} for segment in without_slash.split("/")):
        return f"{location} must not contain `.` or `..` segments"
    return None


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> GitIgnoreBasicPattern | None:
    if not pattern:
        return None
    # Anchoring makes leading `!` and `#` literal, not negation or a comment.
    compiled = GitIgnoreBasicPattern(f"/{pattern}")
    return compiled if compiled.include else None


class SourcePattern:
    """A normalized source pattern compiled once for repeated matching."""

    __slots__ = ("_directory", "_pattern")

    def __init__(self, pattern: str) -> None:
        """Compile one normalized, repository-relative source pattern."""
        self._pattern = _compile(pattern)
        # Literal directories also name a submodule or symlink at that path.
        # Ignore escaped characters when looking for globs, then unescape the
        # directory that `{dir}` supplied. Actual globs still match only files
        # inside their directories.
        self._directory = (
            re.sub(r"\\(.)", r"\1", pattern.removesuffix("/"))
            if pattern.endswith("/") and not has_glob(re.sub(r"\\.", "", pattern))
            else None
        )

    def matches(self, normalized_path: str) -> bool:
        """Return whether an already-normalized path matches this pattern."""
        if not normalized_path or self._pattern is None:
            return False
        return (
            normalized_path == self._directory
            or self._pattern.match_file(normalized_path) is not None
        )


def match_path(pattern: str, path: str) -> bool:
    """Return whether a repository-relative path matches a source pattern."""
    normalized = normalize_path(pattern, keep_trailing_slash=pattern.endswith("/"))
    return SourcePattern(normalized).matches(normalize_path(path))
