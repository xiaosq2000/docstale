"""Load, validate, and resolve docstale configuration."""

from __future__ import annotations

import heapq
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

from docstale.errors import DocstaleError
from docstale.match import matched_paths
from docstale.paths import SourcePattern, has_glob, normalize_path, relative_path_error

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

CONFIG_FILENAME = "docstale.toml"
DIRECTORY = "{dir}"
_ROOT_KEYS = {"documents", "sets"}
_SET_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
# Characters that gitignore syntax would not read literally in a directory name.
_SPECIAL = re.compile(r"([\\*?\[\] ])")


class ConfigError(DocstaleError, ValueError):
    """Raised when the docstale configuration is invalid."""


class MissingConfigError(ConfigError):
    """Raised when no docstale configuration exists."""


@dataclass(frozen=True)
class Document:
    """A document and the source patterns that may affect it."""

    path: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
    """One `[documents]` key with its sources and set names as written."""

    key: str
    sources: tuple[str, ...]
    set_names: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    """Validated docstale configuration."""

    entries: tuple[Entry, ...]
    sets: dict[str, tuple[str, ...]]

    def resolve(self, paths: Iterable[str]) -> tuple[Document, ...]:
        """Expand document globs, sets, and `{dir}` against repository paths."""
        return self._resolve_candidates(_candidates(paths))

    def _resolve_candidates(self, candidates: tuple[str, ...]) -> tuple[Document, ...]:
        sources: dict[str, set[str]] = {}
        for _origin, document, pattern in self._expand(candidates):
            sources.setdefault(document, set()).add(pattern)
        documents = tuple(
            Document(path=path, sources=tuple(sorted(patterns)))
            for path, patterns in sorted(sources.items())
        )
        by_path = {document.path: document for document in documents}
        return tuple(
            by_path[path]
            for component in _dependency_components(documents)
            for path in component
        )

    def unmatched_sources(self, paths: Iterable[str]) -> tuple[str, ...]:
        """Describe each configured source that matches no repository path."""
        return self._unmatched_sources(_candidates(paths))

    def _unmatched_sources(self, candidates: tuple[str, ...]) -> tuple[str, ...]:
        patterns: dict[str, set[str]] = {}
        for origin, _document, pattern in self._expand(candidates):
            patterns.setdefault(origin, set()).add(pattern)
        unique = {pattern for found in patterns.values() for pattern in found}
        matched = {pattern: _matches_any(pattern, candidates) for pattern in unique}
        return tuple(
            origin
            for origin, found in patterns.items()
            if not any(matched[pattern] for pattern in found)
        )

    def unused_sets(self) -> tuple[str, ...]:
        """Return the names of sets that no document uses."""
        used = {name for entry in self.entries for name in entry.set_names}
        return tuple(name for name in self.sets if name not in used)

    def _expand(self, candidates: tuple[str, ...]) -> Iterator[tuple[str, str, str]]:
        """Yield the origin, document, and resolved pattern of every source."""
        for entry in self.entries:
            origins = [
                *(
                    (f"document `{entry.key}` source `{source}`", source)
                    for source in entry.sources
                ),
                *(
                    (f"set `{name}` source `{source}`", source)
                    for name in entry.set_names
                    for source in self.sets[name]
                ),
            ]
            for document in _documents(entry.key, candidates):
                for origin, source in origins:
                    yield origin, document, _resolve(source, document)


def _candidates(paths: Iterable[str]) -> tuple[str, ...]:
    return _normalized_candidates(tuple(paths))


@lru_cache(maxsize=128)
def _normalized_candidates(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({normalize_path(path) for path in paths if path}))


@lru_cache(maxsize=1024)
def _documents(key: str, candidates: tuple[str, ...]) -> tuple[str, ...]:
    """Return an exact key itself, or every candidate that a glob key matches."""
    if not has_glob(key):
        return (key,)
    pattern = SourcePattern(key)
    return tuple(path for path in candidates if pattern.matches(path))


def _finish_order(edges: dict[str, set[str]]) -> tuple[str, ...]:
    """Return DFS finish order without recursion."""
    visited: set[str] = set()
    finished: list[str] = []
    for path in sorted(edges):
        if path in visited:
            continue
        visited.add(path)
        stack = [(path, iter(sorted(edges[path])))]
        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                finished.append(node)
                stack.pop()
            elif neighbor not in visited:
                visited.add(neighbor)
                stack.append((neighbor, iter(sorted(edges[neighbor]))))

    return tuple(finished)


def _strong_components(edges: dict[str, set[str]]) -> tuple[tuple[str, ...], ...]:
    """Find SCCs with iterative Kosaraju passes, without a recursion limit."""
    reverse: dict[str, set[str]] = {path: set() for path in edges}
    for upstream, downstreams in edges.items():
        for downstream in downstreams:
            reverse[downstream].add(upstream)
    visited: set[str] = set()
    components: list[tuple[str, ...]] = []
    for path in reversed(_finish_order(edges)):
        if path in visited:
            continue
        pending = [path]
        visited.add(path)
        component: list[str] = []
        while pending:
            node = pending.pop()
            component.append(node)
            for neighbor in sorted(reverse[node]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    pending.append(neighbor)
        components.append(tuple(sorted(component)))
    return tuple(components)


@lru_cache(maxsize=128)
def _dependency_components(
    documents: tuple[Document, ...],
) -> tuple[tuple[str, ...], ...]:
    """Order the SCC condensation DAG, with lexical ties and upstreams first."""
    edges: dict[str, set[str]] = {document.path: set() for document in documents}
    for document in documents:
        for upstream in matched_paths(document, edges):
            edges[upstream].add(document.path)
    components = _strong_components(edges)
    owner = {path: component for component in components for path in component}
    outgoing: dict[tuple[str, ...], set[tuple[str, ...]]] = {
        component: set() for component in components
    }
    incoming = dict.fromkeys(components, 0)
    for upstream, downstreams in edges.items():
        source = owner[upstream]
        for downstream in downstreams:
            target = owner[downstream]
            if source != target and target not in outgoing[source]:
                outgoing[source].add(target)
                incoming[target] += 1
    ready = [component for component in components if not incoming[component]]
    heapq.heapify(ready)
    ordered: list[tuple[str, ...]] = []
    while ready:
        component = heapq.heappop(ready)
        ordered.append(component)
        for target in sorted(outgoing[component]):
            incoming[target] -= 1
            if not incoming[target]:
                heapq.heappush(ready, target)
    return tuple(ordered)


def _matches_any(pattern: str, candidates: tuple[str, ...]) -> bool:
    compiled = SourcePattern(pattern)
    return any(compiled.matches(path) for path in candidates)


def _resolve(source: str, document: str) -> str:
    """Replace a leading `{dir}` with the document's directory."""
    if not source.startswith(DIRECTORY):
        return source
    # Escaping keeps a directory such as `app/[id]` literal inside the pattern.
    segments = [
        _SPECIAL.sub(r"\\\1", segment)
        for segment in document.rpartition("/")[0].split("/")
        if segment
    ]
    for segment in source.removeprefix(DIRECTORY).split("/"):
        if segment == "..":
            # Loading rejects templates that climb above the repository root.
            segments.pop()
        elif segment:
            segments.append(segment)
    if not segments:
        return "**"
    return "/".join(segments) + ("/" if source.endswith("/") else "")


def _climb(template: str) -> int:
    """Return how many directories a `{dir}` template climbs above its start."""
    level = lowest = 0
    for segment in template.removeprefix(DIRECTORY).split("/"):
        if segment == "..":
            level -= 1
            lowest = min(lowest, level)
        elif segment:
            level += 1
    return -lowest


def _depth(key: str) -> int:
    """Return the fewest directories above any document that a key names."""
    return sum(segment != "**" for segment in key.split("/")[:-1])


def _unknown_keys(config_path: Path, value: dict[str, Any]) -> None:
    unknown = sorted(set(value) - _ROOT_KEYS)
    if unknown:
        rendered = ", ".join(f"`{key}`" for key in unknown)
        raise ConfigError(f"{config_path}: unknown key(s): {rendered}")


def _document_key(config_path: Path, raw_key: str) -> str:
    location = f"{config_path}: document `{raw_key}`"
    normalized = normalize_path(raw_key)
    if error := relative_path_error(location, raw_key, normalized):
        raise ConfigError(error)
    if raw_key.endswith("/"):
        raise ConfigError(f"{location} must name files, not a directory")
    if DIRECTORY in normalized:
        raise ConfigError(f"{location} cannot use `{DIRECTORY}`")
    return normalized


def _source(location: str, raw_source: str) -> str:
    normalized = normalize_path(
        raw_source, keep_trailing_slash=raw_source.endswith("/")
    )
    template = normalized.startswith(DIRECTORY)
    rest = normalized.removeprefix(DIRECTORY)
    if DIRECTORY in rest or (template and rest and not rest.startswith("/")):
        raise ConfigError(
            f"{location} may use `{DIRECTORY}` only as its first path segment"
        )
    if not template:
        if error := relative_path_error(location, raw_source, normalized):
            raise ConfigError(error)
    elif "." in rest.split("/"):
        raise ConfigError(f"{location} must not contain `.` segments")
    return normalized


def _source_list(
    location: str, raw_sources: object, *, sets_allowed: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Validate written sources and separate them from `@name` set references."""
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError(f"{location} must have a non-empty array of sources")

    sources: list[str] = []
    set_names: list[str] = []
    for index, raw_source in enumerate(raw_sources, start=1):
        source_location = f"{location} source #{index}"
        if not isinstance(raw_source, str) or not raw_source:
            raise ConfigError(f"{source_location} must be a non-empty string")
        if not raw_source.startswith("@"):
            sources.append(_source(source_location, raw_source))
        elif not sets_allowed:
            raise ConfigError(f"{source_location} cannot name another set")
        elif _SET_NAME.fullmatch(raw_source[1:]):
            set_names.append(raw_source[1:])
        else:
            raise ConfigError(
                f"{source_location} must name a set as `@name`; "
                f"write `./{raw_source}` for a path"
            )

    written = [*sources, *(f"@{name}" for name in set_names)]
    duplicates = sorted(
        source for source, count in Counter(written).items() if count > 1
    )
    if duplicates:
        rendered = ", ".join(f"`{source}`" for source in duplicates)
        raise ConfigError(f"{location} contains duplicate source(s): {rendered}")
    return tuple(sources), tuple(set_names)


def _sets(config_path: Path, raw_sets: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw_sets, dict):
        raise ConfigError(f"{config_path}: `sets` must be a table")
    sets: dict[str, tuple[str, ...]] = {}
    for name, raw_sources in cast("dict[str, object]", raw_sets).items():
        location = f"{config_path}: set `{name}`"
        if not _SET_NAME.fullmatch(name):
            raise ConfigError(
                f"{location} must use lowercase letters, digits, `-`, and `_`"
            )
        sets[name], _ = _source_list(location, raw_sources, sets_allowed=False)
    return sets


def _entry(
    config_path: Path, key: str, raw_sources: object, sets: dict[str, tuple[str, ...]]
) -> Entry:
    location = f"{config_path}: document `{key}`"
    sources, set_names = _source_list(location, raw_sources, sets_allowed=True)
    for name in set_names:
        if name not in sets:
            raise ConfigError(f"{location} names unknown set `@{name}`")
    depth = _depth(key)
    for source in (*sources, *(item for name in set_names for item in sets[name])):
        if source.startswith(DIRECTORY) and _climb(source) > depth:
            raise ConfigError(
                f"{location} source `{source}` can reach outside the repository"
            )
    return Entry(key=key, sources=sources, set_names=set_names)


def load_config(config_path: Path) -> Config:
    """Load and validate a docstale TOML file."""
    if not config_path.is_file():
        raise MissingConfigError(f"{config_path}: configuration file does not exist")
    try:
        with config_path.open("rb") as config_file:
            raw_config = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path}: TOML parse error: {exc}") from exc

    _unknown_keys(config_path, raw_config)
    sets = _sets(config_path, raw_config.get("sets", {}))
    raw_documents_value = raw_config.get("documents")
    if not isinstance(raw_documents_value, dict) or not raw_documents_value:
        raise ConfigError(f"{config_path}: expected a non-empty `[documents]` table")
    raw_documents = cast("dict[str, object]", raw_documents_value)

    entries: list[Entry] = []
    seen_keys: set[str] = set()
    for raw_key, raw_sources in raw_documents.items():
        key = _document_key(config_path, raw_key)
        if key in seen_keys:
            raise ConfigError(f"{config_path}: duplicate document key `{key}`")
        seen_keys.add(key)
        entries.append(_entry(config_path, key, raw_sources, sets))
    return Config(entries=tuple(entries), sets=sets)


def validate_repository(
    config: Config, *, root: Path, config_path: Path, paths: Iterable[str]
) -> tuple[str, ...]:
    """Validate configuration against the repository and return warnings.

    Every exact document must exist and every glob key must match a document.
    Unmatched sources and unused sets are only warnings, because a shared
    configuration may name files that exist on another branch.
    """
    candidates = _candidates(paths)
    problems: list[str] = []
    for entry in config.entries:
        if not has_glob(entry.key):
            if not (root / entry.key).is_file():
                problems.append(f"  - `{entry.key}` does not exist")
        elif not _documents(entry.key, candidates):
            problems.append(f"  - `{entry.key}` matches no document")
    if problems:
        detail = "\n".join(problems)
        raise ConfigError(f"{config_path}: invalid documents:\n{detail}")
    return (
        *(
            f"{config_path}: {origin} matches no file"
            for origin in config._unmatched_sources(candidates)  # noqa: SLF001
        ),
        *(f"{config_path}: set `{name}` is not used" for name in config.unused_sets()),
        *(
            f"{config_path}: document dependency cycle: "
            + ", ".join(f"`{path}`" for path in component)
            for component in _dependency_components(
                tuple(
                    sorted(
                        config._resolve_candidates(candidates),  # noqa: SLF001
                        key=lambda document: document.path,
                    )
                )
            )
            if len(component) > 1
        ),
    )
