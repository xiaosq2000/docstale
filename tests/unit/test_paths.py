from __future__ import annotations

import pytest

from docstale.paths import (
    SourcePattern,
    _compile,
    match_path,
    normalize_path,
    relative_path_error,
)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        # Every pattern is anchored to the repository root.
        ("pyproject.toml", "pyproject.toml", True),
        ("pyproject.toml", "nested/pyproject.toml", False),
        ("*.py", "app.py", True),
        ("*.py", "src/app.py", False),
        ("src/", "src/app.py", True),
        ("src/", "src/pkg/app.py", True),
        ("src/", "other/src/app.py", False),
        ("src/app.py", "src/app.py", True),
        ("src/app.py", "nested/src/app.py", False),
        # `*` stays within one segment; `**` spans zero or more.
        ("src/*.py", "src/app.py", True),
        ("src/*.py", "src/pkg/app.py", False),
        ("src/**/*.py", "src/app.py", True),
        ("src/**/*.py", "src/pkg/app.py", True),
        # Matching at any depth is opt-in through an explicit `**/` prefix.
        ("**/*.py", "app.py", True),
        ("**/*.py", "src/pkg/app.py", True),
        ("**/app.py", "app.py", True),
        ("**/app.py", "nested/app.py", True),
        # A leading `!` or `#` is an ordinary character, not gitignore
        # negation or a comment.
        ("!literal.py", "!literal.py", True),
        ("#literal.py", "#literal.py", True),
        # A bare directory name behaves like the same name with a trailing slash.
        ("src", "src/app.py", True),
        ("src", "src/pkg/app.py", True),
        # A literal directory pattern also names the directory itself, which
        # Git reports as one path for a submodule or a symlink.
        ("src/", "src", True),
        ("vendor/lib/", "vendor/lib", True),
        ("vendor/lib/", "vendor/library", False),
        # A glob cannot tell such a path from a file, so it matches only what
        # lies inside the directories it names.
        ("src/*/", "src/pkg", False),
        ("src/*/", "src/pkg/app.py", True),
    ],
)
def test_match_path(pattern: str, path: str, expected: bool) -> None:
    assert match_path(pattern, path) is expected


@pytest.mark.parametrize(
    ("pattern", "literal", "expected"),
    [
        (r"vendor/a\ b/", "vendor/a b", True),
        (r"vendor/\[lib\]/", "vendor/[lib]", True),
        (r"vendor/\[lib\]/", "vendor/l", False),
        (r"vendor/\*\?/", "vendor/*?", True),
        (r"vendor/a\ b/*/", "vendor/a b/lib", False),
        (r"vendor/a\ b/*/", "vendor/a b/lib/file", True),
        (r"vendor/\\[ab]/", "vendor/\\a", False),
        ("", "src/app.py", False),
        ("src/", "", False),
    ],
)
def test_compiled_patterns_unescape_only_literal_directories(
    pattern: str, literal: str, expected: bool
) -> None:
    assert SourcePattern(pattern).matches(literal) is expected


def test_pattern_compilation_is_cached() -> None:
    _compile.cache_clear()
    first = SourcePattern("src/*.py")
    second = SourcePattern("src/*.py")
    assert first.matches("src/app.py")
    assert second.matches("src/other.py")
    assert _compile.cache_info().misses == 1
    assert _compile.cache_info().hits == 1


def test_normalizes_windows_separators() -> None:
    assert normalize_path(r"src\package\app.py") == "src/package/app.py"
    assert normalize_path("./src////app.py") == "src/app.py"


def test_preserves_whitespace_in_git_paths() -> None:
    assert normalize_path(" source.py ") == " source.py "


@pytest.mark.parametrize(
    ("raw_path", "expected_fragment"),
    [
        ("../src", "`..`"),
        ("/src", "repository-relative"),
        ("./", "empty path"),
    ],
)
def test_rejects_unusable_path(raw_path: str, expected_fragment: str) -> None:
    error = relative_path_error("source", raw_path, normalize_path(raw_path))

    assert error is not None
    assert expected_fragment in error


def test_accepts_relative_path() -> None:
    assert relative_path_error("source", "src/app.py", "src/app.py") is None
