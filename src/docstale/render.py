"""Render document review results for people and agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from docstale.match import Review

_REVIEW_GUIDANCE = (
    "Review each document and update it if the listed source changes altered "
    "durable facts.\n"
    "For a listed source, `git diff <commit> -- <source>` shows changes since "
    "the commit in the document's heading.\n"
    "New files that Git does not track do not appear in that diff. "
    "Read those files directly."
)
_STAMP_GUIDANCE = (
    "Record each review with `docstale stamp <document> ...`, even when no update "
    "is needed. Pass one or more document paths."
)
_READ_ONLY_GUIDANCE = (
    "If the user requests a read-only response or prohibits file edits, only "
    "report the affected documents. Do not edit files or run `docstale stamp`."
)
CHECK_GUIDANCE = f"{_REVIEW_GUIDANCE}\n{_STAMP_GUIDANCE}"
PI_HOOK_GUIDANCE = (
    f"{_READ_ONLY_GUIDANCE}\nOtherwise:\n{_REVIEW_GUIDANCE}\n{_STAMP_GUIDANCE}"
)
HOOK_GUIDANCE = (
    f"{_READ_ONLY_GUIDANCE}\nOtherwise:\n{_REVIEW_GUIDANCE}\n"
    "If a `docstale-reviewer` subagent is available, run one for each document. "
    "Update the documents it reports as affected. Ask the user about those it "
    "reports as unsure.\n"
    f"{_STAMP_GUIDANCE}"
)


def _heading(review: Review) -> str:
    if not review.stamped:
        return f"{review.document} (never stamped)"
    if not review.sources:
        return f"{review.document} (source list unavailable)"
    if review.since is not None:
        return f"{review.document} (changed since {review.since[:12]})"
    return review.document


def build_review_message(
    reviews: Iterable[Review], *, guidance: str = CHECK_GUIDANCE
) -> str:
    """Build a review request from pending documents."""
    lines = ["Documentation needs review.", ""]
    for review in reviews:
        lines.append(_heading(review))
        lines.extend(f"  {source}" for source in review.sources)
        if review.stamped and not review.sources:
            lines.extend(
                (
                    "  The fingerprint changed, but no changed source paths are available.",
                    "  Source patterns may have changed, or Git history may be incomplete.",
                    "  Read the document and its configured sources directly.",
                )
            )
    lines.extend(["", guidance])
    return "\n".join(lines)
