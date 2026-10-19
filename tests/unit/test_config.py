from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from docstale.config import (
    Config,
    ConfigError,
    Document,
    MissingConfigError,
    load_config,
    validate_repository,
)
from docstale.match import matched_paths
from tests.support import write_config

if TYPE_CHECKING:
    from pathlib import Path


def _load(root: Path, content: str) -> Config:
    path = root / "docstale.toml"
    path.write_text(content, encoding="utf-8")
    return load_config(path)


def _validate(root: Path, path: Path, paths: tuple[str, ...]) -> tuple[str, ...]:
    return validate_repository(
        load_config(path), root=root, config_path=path, paths=paths
    )


def test_resolves_documents_in_stable_path_order(root: Path) -> None:
    config = _load(root, '[documents]\n"z.md" = ["z/"]\n"a.md" = ["common.py", "a/"]\n')

    assert config.resolve(()) == (
        Document(path="a.md", sources=("a/", "common.py")),
        Document(path="z.md", sources=("z/",)),
    )


def test_sets_insert_shared_sources(root: Path) -> None:
    config = _load(
        root,
        '[sets]\nbuild = ["pixi.toml", "pyproject.toml"]\n\n'
        '[documents]\n"README.md" = ["@build", "src/"]\n"docs/dev.md" = ["@build"]\n',
    )

    assert config.resolve(()) == (
        Document(path="README.md", sources=("pixi.toml", "pyproject.toml", "src/")),
        Document(path="docs/dev.md", sources=("pixi.toml", "pyproject.toml")),
    )


def test_glob_keys_name_every_matching_document(root: Path) -> None:
    config = _load(root, '[documents]\n"packages/*/README.md" = ["{dir}/"]\n')

    documents = config.resolve(
        (
            "README.md",
            "packages/a/README.md",
            "packages/a/src/app.py",
            "packages/b/README.md",
            "packages/b/nested/README.md",
        )
    )

    assert documents == (
        Document(path="packages/a/README.md", sources=("packages/a/",)),
        Document(path="packages/b/README.md", sources=("packages/b/",)),
    )


def test_a_document_named_by_several_keys_watches_all_of_their_sources(
    root: Path,
) -> None:
    config = _load(
        root,
        '[documents]\n"docs/*.md" = ["docs/"]\n"docs/api.md" = ["src/api/", "docs/"]\n',
    )

    assert config.resolve(("docs/api.md", "docs/guide.md")) == (
        Document(path="docs/api.md", sources=("docs/", "src/api/")),
        Document(path="docs/guide.md", sources=("docs/",)),
    )


@pytest.mark.parametrize(
    ("document", "source", "expected"),
    [
        ("packages/a/README.md", "{dir}/", "packages/a/"),
        ("packages/a/README.md", "{dir}", "packages/a"),
        ("packages/a/README.md", "{dir}/src/*.py", "packages/a/src/*.py"),
        ("packages/a/docs/guide.md", "{dir}/../", "packages/a/"),
        ("packages/a/docs/guide.md", "{dir}/../../shared/", "packages/shared/"),
        ("README.md", "{dir}/src/", "src/"),
        ("README.md", "{dir}/", "**"),
    ],
)
def test_directory_templates_resolve_for_each_document(
    root: Path, document: str, source: str, expected: str
) -> None:
    config = _load(
        root, f"[documents]\n{json.dumps(document)} = [{json.dumps(source)}]\n"
    )

    assert config.resolve(()) == (Document(path=document, sources=(expected,)),)


def test_directory_templates_keep_glob_characters_literal(root: Path) -> None:
    config = _load(root, '[documents]\n"app/*/README.md" = ["{dir}/"]\n')

    documents = config.resolve(("app/[id]/README.md",))

    (document,) = documents
    assert matched_paths(document, ("app/[id]/page.tsx", "app/i/page.tsx")) == (
        "app/[id]/page.tsx",
    )


def test_unmatched_sources_normalizes_its_own_candidate_paths(root: Path) -> None:
    config = _load(root, '[documents]\n"README.md" = ["src/", "gone.py"]\n')
    assert config.unmatched_sources(("./src/app.py",)) == (
        "document `README.md` source `gone.py`",
    )


def test_an_absent_file_has_a_distinct_error(root: Path) -> None:
    with pytest.raises(MissingConfigError, match="does not exist"):
        load_config(root / "docstale.toml")


def test_a_broken_file_is_not_reported_as_missing(root: Path) -> None:
    path = root / "docstale.toml"
    path.write_text("[documents\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="TOML parse error") as caught:
        load_config(path)

    assert not isinstance(caught.value, MissingConfigError)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("config_version = 1\n[documents]\n", "unknown key"),
        ("[documents]\n", "non-empty"),
        ('[documents]\n"README.md" = []\n', "non-empty array"),
        ('[documents]\n"README.md" = [1]\n', "non-empty string"),
        ('[documents]\n"/README.md" = ["src/"]\n', "repository-relative"),
        ('[documents]\n"docs/" = ["src/"]\n', "not a directory"),
        ('[documents]\n"{dir}/README.md" = ["src/"]\n', "cannot use `{dir}`"),
        ('[documents]\n"README.md" = ["../src"]\n', "`..`"),
        (
            '[documents]\n"README.md" = ["src/", "./src/"]\n',
            "duplicate source",
        ),
        (
            '[documents]\n"README.md" = ["src/"]\n"./README.md" = ["lib/"]\n',
            "duplicate document key",
        ),
        ('sets = ["src/"]\n[documents]\n"README.md" = ["src/"]\n', "must be a table"),
        (
            '[sets]\nBuild = ["src/"]\n[documents]\n"README.md" = ["src/"]\n',
            "lowercase",
        ),
        (
            '[sets]\nbuild = []\n[documents]\n"README.md" = ["src/"]\n',
            "non-empty array",
        ),
        (
            '[sets]\nall = ["@build"]\nbuild = ["src/"]\n'
            '[documents]\n"README.md" = ["@all"]\n',
            "cannot name another set",
        ),
        ('[documents]\n"README.md" = ["@build"]\n', "unknown set `@build`"),
        ('[documents]\n"README.md" = ["@Build"]\n', "`@name`"),
        (
            '[sets]\nbuild = ["src/"]\n[documents]\n"README.md" = ["@build", "@build"]\n',
            "duplicate source",
        ),
        ('[documents]\n"README.md" = ["src/{dir}/"]\n', "first path segment"),
        ('[documents]\n"README.md" = ["{dir}src/"]\n', "first path segment"),
        ('[documents]\n"README.md" = ["{dir}/./src/"]\n', "`.` segments"),
        ('[documents]\n"README.md" = ["{dir}/../"]\n', "outside the repository"),
        ('[documents]\n"**/README.md" = ["{dir}/../"]\n', "outside the repository"),
        (
            '[sets]\nparent = ["{dir}/../"]\n[documents]\n"README.md" = ["@parent"]\n',
            "outside the repository",
        ),
    ],
    ids=[
        "unknown-root-key",
        "empty-documents",
        "empty-sources",
        "non-string-source",
        "absolute-document",
        "directory-document",
        "template-document",
        "parent-source",
        "duplicate-source",
        "duplicate-document",
        "sets-not-a-table",
        "invalid-set-name",
        "empty-set",
        "nested-set",
        "unknown-set",
        "invalid-set-reference",
        "duplicate-set-reference",
        "template-not-leading",
        "template-without-separator",
        "template-dot-segment",
        "template-above-root",
        "glob-template-above-root",
        "set-template-above-root",
    ],
)
def test_rejects_invalid_config(
    root: Path, content: str, expected_message: str
) -> None:
    path = root / "docstale.toml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError, match=expected_message):
        load_config(path)


def test_repository_validation_requires_exact_documents(repository: Path) -> None:
    path = write_config(repository, document="docs/missing.md")

    with pytest.raises(ConfigError, match=r"docs/missing\.md.*does not exist"):
        _validate(repository, path, ())


def test_repository_validation_requires_glob_keys_to_match(repository: Path) -> None:
    path = write_config(repository, document="docs/*.md")

    with pytest.raises(ConfigError, match=r"docs/\*\.md.*matches no document"):
        _validate(repository, path, ("README.md", "src/app.py"))


def test_repository_validation_warns_about_unmatched_sources(
    repository: Path,
) -> None:
    path = write_config(repository, sources=("src/", "future/**/*.py"))

    warnings = _validate(repository, path, ("README.md", "src/app.py"))

    assert warnings == (
        f"{path}: document `README.md` source `future/**/*.py` matches no file",
    )


def test_repository_validation_reports_set_sources_and_unused_sets(
    root: Path,
) -> None:
    (root / "README.md").write_text("docs", encoding="utf-8")
    path = root / "docstale.toml"
    path.write_text(
        '[sets]\nshared = ["src/", "gone.py"]\nidle = ["src/"]\n\n'
        '[documents]\n"README.md" = ["@shared"]\n',
        encoding="utf-8",
    )

    warnings = _validate(root, path, ("README.md", "src/app.py"))

    assert warnings == (
        f"{path}: set `shared` source `gone.py` matches no file",
        f"{path}: set `idle` is not used",
    )


def test_a_template_is_unmatched_only_when_no_document_matches(root: Path) -> None:
    path = root / "docstale.toml"
    path.write_text(
        '[documents]\n"decks/*/index.md" = ["{dir}/main.tex", "{dir}/gone.bib"]\n',
        encoding="utf-8",
    )

    warnings = _validate(
        root, path, ("decks/a/index.md", "decks/a/main.tex", "decks/b/index.md")
    )

    assert warnings == (
        f"{path}: document `decks/*/index.md` source `{{dir}}/gone.bib` "
        "matches no file",
    )
