"""Pure matching of repository paths to documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docstale.lock import LOCK_FILENAME
from docstale.paths import SourcePattern

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from docstale.config import Document

FINGERPRINT_LENGTH = 16


@dataclass(frozen=True)
class Review:
    """One document that needs review and the changed sources behind it."""

    document: str
    sources: tuple[str, ...]
    since: str | None = None
    stamped: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "path": self.document,
            "since": self.since,
            "sources": list(self.sources),
            "stamped": self.stamped,
        }


def matched_paths(document: Document, paths: Iterable[str]) -> tuple[str, ...]:
    """Return matched sources, excluding the document and docstale's lock."""
    patterns = tuple(SourcePattern(source) for source in document.sources)
    return tuple(
        sorted(
            path
            for path in paths
            if path not in {document.path, LOCK_FILENAME}
            and any(pattern.matches(path) for pattern in patterns)
        )
    )


def fingerprint(document: Document, object_ids: Mapping[str, str]) -> str:
    """Hash the path and object id of every file that a document's sources match."""
    digest = hashlib.sha256()
    for path in matched_paths(document, object_ids):
        digest.update(f"{path}\0{object_ids[path]}\0".encode(errors="surrogateescape"))
    return digest.hexdigest()[:FINGERPRINT_LENGTH]


def stale_documents(
    documents: Iterable[Document],
    object_ids: Mapping[str, str],
    lock: Mapping[str, str],
) -> tuple[Document, ...]:
    """Return documents whose fingerprint differs from the one in the lock."""
    return tuple(
        document
        for document in documents
        if lock.get(document.path) != fingerprint(document, object_ids)
    )
