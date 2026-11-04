"""Check a draft's citations against the fetch receipts of its session tree.

A grounded-citations ledger maps ``[n]`` to a URL, and ``sources.py verify``
proves the draft only cites ids the ledger handed out. It cannot prove the
URL behind an id was ever opened: a ledger entry can come from a remembered
link or a search snippet. `post_tool_call` writes a metadata-only
``research_fetch_receipt/v1`` line for each URL a session's web tools really
opened (`omh.plugin_bundle.omh.research_receipts`), and this module matches
each cited source against those receipts, in the session and in every
subagent session its delegation ledger names.

Each distinct cited id gets one status:

* ``fetched``: a ``fetched`` receipt for the ledger URL exists in the tree;
* ``search_only``: the URL was only listed by ``web_search``, never opened;
* ``missing``: no receipt, and the delegation ledger was read, so every
  child session was checked;
* ``child_unresolved``: no receipt, and the delegation ledger could not be
  read, so a child that opened the URL cannot be ruled out;
* ``not_in_ledger``: the draft cites an id the citation ledger does not hold.

URL identity is the grounded-citations normalization hashed exactly as the
receipt writer hashes it, so ``/abs/x`` and ``/pdf/x`` are two sources.
Coverage is an ``omh_reported_rate/v1`` over the distinct cited ids; zero
citations is ``percent: null``, never 0% or 100%.

A receipt proves the URL was opened in this session tree. It is not evidence
that the page supports the claim the draft makes from it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from ..plugin_bundle.omh.delegation_ledger import read_ledger
from ..plugin_bundle.omh.research_receipts import (
    KIND_FETCHED,
    KIND_SEARCH_LISTED,
    RECEIPT_SCHEMA_VERSION,
    receipt_path,
    url_display,
    url_key,
)
from ..quality.reported_rate import reported_rate

CITATION_RECEIPT_CHECK_SCHEMA_VERSION: Final = "citation_receipt_check/v1"
STATUS_FETCHED: Final = "fetched"
STATUS_SEARCH_ONLY: Final = "search_only"
STATUS_MISSING: Final = "missing"
STATUS_CHILD_UNRESOLVED: Final = "child_unresolved"
STATUS_NOT_IN_LEDGER: Final = "not_in_ledger"
CITATION_STATUSES: Final = (
    STATUS_FETCHED,
    STATUS_SEARCH_ONLY,
    STATUS_MISSING,
    STATUS_CHILD_UNRESOLVED,
    STATUS_NOT_IN_LEDGER,
)
# Text the grounded-citations rule never counts as a citation, dropped before the denominator is taken.
COVERAGE_EXCLUDED: Final = ("fenced_code_markers", "markdown_link_labels", "sources_block_lines")
CLAIM_BOUNDARY: Final = (
    "A fetch receipt proves the cited URL was opened by a web tool in this session tree "
    "(the session and the subagent sessions its delegation ledger names). It is not evidence "
    "that the page supports the claim the draft makes from it."
)
DRAFT_BYTE_LIMIT: Final = 4_000_000
LEDGER_BYTE_LIMIT: Final = 4_000_000
RECEIPT_BYTE_LIMIT: Final = 8_000_000

# Copied from grounded-citations `scripts/sources.py` (a user-installed Hermes skill, read only): a
# citation is `[n]` not followed by `(` or `:`, fenced code is skipped, and everything after the last
# `Sources` header is the sources block, not prose.
_CITE_RE: Final = re.compile(r"\[(\d{1,4})\](?![(:])")
_SOURCES_HEADER_RE: Final = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?sources:?(?:\*\*)?\s*$", re.IGNORECASE)
_FENCE_RE: Final = re.compile(r"^\s*(?:```|~~~)")


class ReceiptCheckInputError(ValueError):
    """A citation ledger, draft or receipt file that cannot be read as one."""


def draft_prose(text: str) -> str:
    """The draft's prose: no sources block after the last ``Sources`` header, no fenced code."""
    lines = text.splitlines()
    header_idx = -1
    for index, line in enumerate(lines):
        if _SOURCES_HEADER_RE.match(line):
            header_idx = index
    body = lines[:header_idx] if header_idx >= 0 else lines
    prose: list[str] = []
    in_fence = False
    for line in body:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            prose.append(line)
    return "\n".join(prose)


def cited_ids(text: str) -> list[int]:
    """Distinct cited ids in first-appearance order."""
    seen: dict[int, None] = {}
    for match in _CITE_RE.findall(draft_prose(text)):
        seen.setdefault(int(match), None)
    return list(seen)


def ledger_urls(ledger: object) -> dict[int, str]:
    """``id -> url`` from a grounded-citations ledger (``{"version": 1, "sources": [...]}``)."""
    if not isinstance(ledger, dict) or not isinstance(ledger.get("sources"), list):
        raise ReceiptCheckInputError("citation ledger has an unexpected shape: expected {\"sources\": [...]}")
    urls: dict[int, str] = {}
    for entry in ledger["sources"]:
        if not isinstance(entry, dict):
            continue
        source_id, url = entry.get("id"), entry.get("url")
        if isinstance(source_id, int) and not isinstance(source_id, bool) and isinstance(url, str) and url.strip():
            urls[source_id] = url
    return urls


def _read_text(path: Path, *, label: str, limit: int) -> str:
    try:
        if not path.is_file():
            raise ReceiptCheckInputError(f"{label} not found: {path}")
        if path.stat().st_size > limit:
            raise ReceiptCheckInputError(f"{label} is larger than {limit} bytes: {path}")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReceiptCheckInputError(f"{label} is unreadable ({type(exc).__name__}): {path}") from exc


def read_citation_ledger(path: Path) -> dict[int, str]:
    raw = _read_text(path, label="citation ledger", limit=LEDGER_BYTE_LIMIT)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ReceiptCheckInputError(f"citation ledger is not JSON: {path}") from exc
    return ledger_urls(data)


def read_draft(path: Path) -> str:
    return _read_text(path, label="draft", limit=DRAFT_BYTE_LIMIT)


def read_session_receipts(omh_home: Path, session_id: str) -> list[dict[str, str]]:
    """``{"kind", "url_key"}`` for every receipt line of one session; an absent file is no receipts.

    Lines that do not parse or carry another schema are skipped, the way the
    writer's own bound can cut a line it is rewriting.
    """
    path = receipt_path(omh_home, session_id)
    if path.is_symlink():
        raise ReceiptCheckInputError(f"receipt file is a symlink: {path}")
    if not path.exists():
        return []
    raw = _read_text(path, label="receipt file", limit=RECEIPT_BYTE_LIMIT)
    receipts: list[dict[str, str]] = []
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("schema_version") != RECEIPT_SCHEMA_VERSION:
            continue
        kind, key = row.get("kind"), row.get("url_key")
        if kind in (KIND_FETCHED, KIND_SEARCH_LISTED) and isinstance(key, str) and key:
            receipts.append({"kind": kind, "url_key": key})
    return receipts


def child_sessions(omh_home: Path, session_id: str) -> list[str] | None:
    """Child session ids from the session's delegation ledger; None when that ledger cannot be read."""
    record = read_ledger(omh_home, session_id)
    if record is None:
        return None
    children: dict[str, None] = {}
    for child in record.get("children", []):
        child_id = child.get("child_session_id") if isinstance(child, dict) else None
        if isinstance(child_id, str) and child_id and child_id != session_id:
            children.setdefault(child_id, None)
    return list(children)


def build_citation_receipt_check(
    *,
    ledger: Mapping[int, str],
    draft_text: str,
    session_id: str,
    receipts_by_session: Mapping[str, Sequence[Mapping[str, str]]],
    children_resolved: bool,
) -> dict[str, Any]:
    """The ``citation_receipt_check/v1`` payload; pure, so every status is testable without a store."""
    fetched_in: dict[str, list[str]] = {}
    listed_in: dict[str, list[str]] = {}
    for sid, receipts in receipts_by_session.items():
        for receipt in receipts:
            target = fetched_in if receipt.get("kind") == KIND_FETCHED else listed_in
            sessions = target.setdefault(str(receipt.get("url_key")), [])
            if sid not in sessions:
                sessions.append(sid)
    citations: list[dict[str, Any]] = []
    for source_id in cited_ids(draft_text):
        url = ledger.get(source_id)
        if url is None:
            citations.append({"id": source_id, "status": STATUS_NOT_IN_LEDGER, "url_display": "", "sessions": []})
            continue
        key = url_key(url)
        if key in fetched_in:
            status, sessions = STATUS_FETCHED, fetched_in[key]
        elif key in listed_in:
            status, sessions = STATUS_SEARCH_ONLY, listed_in[key]
        else:
            status, sessions = (STATUS_MISSING if children_resolved else STATUS_CHILD_UNRESOLVED), []
        citations.append({"id": source_id, "status": status, "url_display": url_display(url), "sessions": sorted(sessions)})
    counts = {status: sum(1 for row in citations if row["status"] == status) for status in CITATION_STATUSES}
    coverage = reported_rate(
        numerator=counts[STATUS_FETCHED],
        denominator=len(citations),
        numerator_of=[STATUS_FETCHED],
        denominator_of="cited_sources",
        excluded=COVERAGE_EXCLUDED,
    )
    return {
        "schema_version": CITATION_RECEIPT_CHECK_SCHEMA_VERSION,
        "session_id": session_id,
        "sessions_checked": sorted(receipts_by_session),
        "delegation_ledger": "read" if children_resolved else "unreadable",
        "citations": citations,
        "counts": counts,
        "coverage": coverage.to_payload(),
        "all_fetched": bool(citations) and counts[STATUS_FETCHED] == len(citations),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def check_draft_receipts(*, omh_home: Path, session_id: str, citations_path: Path, draft_path: Path) -> dict[str, Any]:
    """Read the ledger, the draft and the session tree's receipts, then build the check."""
    ledger = read_citation_ledger(citations_path)
    draft_text = read_draft(draft_path)
    children = child_sessions(omh_home, session_id)
    sessions = [session_id, *(children or [])]
    receipts = {sid: read_session_receipts(omh_home, sid) for sid in sessions}
    return build_citation_receipt_check(
        ledger=ledger,
        draft_text=draft_text,
        session_id=session_id,
        receipts_by_session=receipts,
        children_resolved=children is not None,
    )


__all__ = [
    "CITATION_RECEIPT_CHECK_SCHEMA_VERSION",
    "CITATION_STATUSES",
    "CLAIM_BOUNDARY",
    "COVERAGE_EXCLUDED",
    "ReceiptCheckInputError",
    "build_citation_receipt_check",
    "check_draft_receipts",
    "child_sessions",
    "cited_ids",
    "draft_prose",
    "ledger_urls",
    "read_citation_ledger",
    "read_draft",
    "read_session_receipts",
]
