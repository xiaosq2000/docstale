from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from docstale.config import (
    Config,
    Entry,
    _documents,
    _normalized_candidates,
    validate_repository,
)
from docstale.match import fingerprint

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _config(sources: Mapping[str, tuple[str, ...]]) -> Config:
    return Config(
        entries=tuple(Entry(path, patterns, ()) for path, patterns in sources.items()),
        sets={},
    )


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ({"missing/*.md": ("src/",)}, ()),
        ({"a.md": ("z.md",), "z.md": ("src/",)}, ("z.md", "a.md")),
        (
            {
                "a.md": ("b.md", "c.md"),
                "b.md": ("z.md",),
                "c.md": ("z.md",),
                "z.md": ("src/",),
            },
            ("z.md", "b.md", "c.md", "a.md"),
        ),
        (
            {
                "a.md": ("b.md", "z.md"),
                "b.md": ("a.md",),
                "c.md": ("a.md", "b.md"),
                "x.md": ("src/",),
                "z.md": ("src/",),
            },
            ("x.md", "z.md", "a.md", "b.md", "c.md"),
        ),
        (
            {
                "a.md": ("b.md", "y.md", "z.md"),
                "b.md": ("a.md", "z.md"),
                "y.md": ("z.md",),
                "z.md": ("y.md",),
            },
            ("y.md", "z.md", "a.md", "b.md"),
        ),
        ({"self.md": ("self.md",)}, ("self.md",)),
    ],
)
def test_scc_topological_order_is_deterministic(
    sources: dict[str, tuple[str, ...]], expected: tuple[str, ...]
) -> None:
    for ordered in (sources, dict(reversed(tuple(sources.items())))):
        assert (
            tuple(document.path for document in _config(ordered).resolve(()))
            == expected
        )


def test_every_three_document_graph_respects_reachability_and_cycle_order() -> None:
    names = ("a.md", "b.md", "c.md")
    pairs = [
        (source, target) for source in names for target in names if source != target
    ]
    for mask in range(1 << len(pairs)):
        edges = {pair for index, pair in enumerate(pairs) if mask & (1 << index)}
        reachable = set(edges)
        for middle in names:
            reachable.update(
                (source, target)
                for source in names
                for target in names
                if (source, middle) in reachable and (middle, target) in reachable
            )
        sources = {
            target: ("src/", *(source for source in names if (source, target) in edges))
            for target in names
        }
        order = {
            document.path: index
            for index, document in enumerate(_config(sources).resolve(()))
        }
        for source, target in reachable:
            if source == target:
                continue
            if (target, source) not in reachable or source < target:
                assert order[source] < order[target]


def test_resolution_and_matching_do_not_access_git_files_or_output(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config({"guide.md": ("src/",)})

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pure resolution must not access Git or files")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", fail)
        patch.setattr(type(root), "open", fail)
        patch.setattr("docstale.git._run_git", fail)
        (document,) = config.resolve(("guide.md", "src/app.py"))
        assert len(fingerprint(document, {"src/app.py": "abc"})) == 16
    assert capsys.readouterr() == ("", "")


def test_long_dependency_chains_do_not_require_python_recursion() -> None:
    count = 1100
    sources = {
        f"{index:04}.md": (f"{index + 1:04}.md",) if index < count - 1 else ("src/",)
        for index in range(count)
    }
    documents = _config(sources).resolve(())
    assert tuple(document.path for document in documents) == tuple(reversed(sources))


def test_validation_and_resolution_reuse_candidate_and_glob_computations(
    root: Path,
) -> None:
    (root / "a.md").write_text("docs", encoding="utf-8")
    config = _config({"*.md": ("src/",)})
    paths = ("src/app.py", "a.md")
    _normalized_candidates.cache_clear()
    _documents.cache_clear()

    assert (
        validate_repository(
            config, root=root, config_path=root / "docstale.toml", paths=paths
        )
        == ()
    )
    config.resolve(paths)

    assert _normalized_candidates.cache_info().misses == 1
    assert _documents.cache_info().misses == 1


def test_validation_reports_each_cycle_but_not_self_matches(root: Path) -> None:
    sources = {
        "a.md": ("b.md",),
        "b.md": ("a.md",),
        "c.md": ("d.md",),
        "d.md": ("e.md",),
        "e.md": ("c.md",),
        "self.md": ("self.md",),
    }
    for name in sources:
        (root / name).write_text("docs", encoding="utf-8")
    warnings = validate_repository(
        _config(sources), root=root, config_path=root / "docstale.toml", paths=sources
    )
    assert len(warnings) == 2
    assert warnings[0].endswith("document dependency cycle: `a.md`, `b.md`")
    assert warnings[1].endswith("document dependency cycle: `c.md`, `d.md`, `e.md`")
