from __future__ import annotations

from docstale.config import Document
from docstale.match import (
    Review,
    fingerprint,
    matched_paths,
    stale_documents,
)
from docstale.render import build_review_message

README = Document("README.md", ("README.md", "src/"))
IDS = {"README.md": "a1", "src/app.py": "b1", "tests/test_app.py": "c1"}


def test_a_document_never_matches_itself() -> None:
    assert matched_paths(README, IDS) == ("src/app.py",)


def test_the_root_lock_is_never_a_source_even_for_broad_patterns() -> None:
    document = Document("README.md", ("**", "docstale.lock"))
    ids = {"README.md": "a", "docstale.lock": "b", "src/app.py": "c"}
    assert matched_paths(document, ids) == ("src/app.py",)
    assert fingerprint(document, ids) == fingerprint(
        document, {**ids, "docstale.lock": "changed"}
    )
    assert matched_paths(document, (*ids, "nested/docstale.lock")) == (
        "nested/docstale.lock",
        "src/app.py",
    )


def test_a_fingerprint_covers_only_matched_sources() -> None:
    original = fingerprint(README, IDS)

    assert fingerprint(README, {**IDS, "tests/test_app.py": "c2"}) == original
    assert fingerprint(README, {**IDS, "README.md": "a2"}) == original
    assert fingerprint(README, {**IDS, "src/app.py": "b2"}) != original
    assert fingerprint(README, {**IDS, "src/new.py": "d1"}) != original
    assert len(original) == 16


def test_documents_are_stale_until_the_lock_records_their_fingerprint() -> None:
    api = Document("docs/api.md", ("src/",))
    lock = {"README.md": fingerprint(README, IDS)}

    assert stale_documents((README, api), IDS, lock) == (api,)


def test_message_names_documents_and_sources() -> None:
    message = build_review_message((Review("README.md", ("src/app.py",)),))

    assert "README.md\n  src/app.py" in message


def test_empty_source_diagnostics_never_suggest_a_history_heading() -> None:
    message = build_review_message(
        (Review("a.md", (), since="abc"), Review("b.md", ()))
    )
    assert "a.md (source list unavailable)" in message
    assert "b.md (source list unavailable)" in message
    assert "changed since" not in message
    assert "Read the document and its configured sources directly." in message


def test_message_says_since_when_and_whether_a_document_was_stamped() -> None:
    message = build_review_message(
        (
            Review("README.md", ("src/app.py",), since="0123456789abcdef"),
            Review("docs/api.md", (), stamped=False),
        )
    )

    assert "README.md (changed since 0123456789ab)\n  src/app.py" in message
    assert "docs/api.md (never stamped)" in message
    assert "docstale stamp <document>" in message
