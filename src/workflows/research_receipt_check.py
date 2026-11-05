"""Check a draft's citations against the fetch receipts of its session tree.

A grounded-citations ledger maps ``[n]`` to a URL, and ``sources.py verify``
proves the draft only cites ids the ledger handed out. It cannot prove the
URL behind an id was ever opened: a ledger entry can come from a remembered
link or a search snippet. `post_tool_call` writes a metadata-only
``research_fetch_receipt/v1`` line for each URL a session's web tools really
opened (`omh.plugin_bundle.omh.research_receipts`), and this module matches
each cited source against those receipts across the session tree: the
session, the earlier segments Hermes' rotating compaction moved the same
conversation out of (`live_session.compaction_ancestors`, read-only), and
every subagent session each segment's delegation ledger names.

Each distinct cited id gets one status:

* ``fetched``: a ``fetched`` receipt for the ledger URL exists in the tree;
* ``search_only``: the URL was only listed by ``web_search``, never opened;
* ``missing``: no receipt, and the whole tree was resolved: every segment's
  delegation ledger was read or does not exist (no child was ever started
  there), and the compaction walk reached the conversation's first segment;
* ``child_unresolved``: no receipt, and part of the tree could not be
  resolved: a delegation ledger that exists but cannot be read (unparseable,
  a symlink, oversize), or a compaction walk that stopped unverified, so a
  session that opened the URL cannot be ruled out;
* ``not_in_ledger``: the draft cites an id the citation ledger does not hold.

URL identity is the grounded-citations normalization hashed exactly as the
receipt writer hashes it, so ``/abs/x`` and ``/pdf/x`` are two sources. A
ledger URL also matches in the ASCII form Hermes' URL tools request and
report (`tools/url_safety.normalize_url_for_request`: IDNA host,
percent-encoded path and query), a deterministic encoding rather than an
alias guess; a redirect target never matches the URL that redirected to it.
Coverage is an ``omh_reported_rate/v1`` over the distinct cited ids; zero
citations is ``percent: null``, never 0% or 100%.

A receipt write the hook refused leaves no receipt, so its URL reads as
unfetched; the per-session ``receipt_refusals`` count says when that happened.

A receipt proves the URL was opened in this session tree. It is not evidence
that the page supports the claim the draft makes from it.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Final, Mapping, Sequence
from urllib.parse import quote, urlsplit, urlunsplit

from ..plugin_bundle.omh.delegation_ledger import ledger_path, read_ledger
from ..plugin_bundle.omh.live_session import compaction_ancestors
from ..plugin_bundle.omh.research_receipts import (
    KIND_FETCHED,
    KIND_SEARCH_LISTED,
    RECEIPT_SCHEMA_VERSION,
    REFUSAL_BYTE_LIMIT,
    REFUSAL_COUNT_LIMIT,
    receipt_path,
    refusal_path,
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
LEDGER_READ: Final = "read"
LEDGER_ABSENT: Final = "absent"
LEDGER_UNREADABLE: Final = "unreadable"
CLAIM_BOUNDARY: Final = (
    "A fetch receipt proves the cited URL was opened by a web tool in this session tree "
    "(the session, its earlier compaction segments, and the subagent sessions their delegation ledgers name). "
    "A URL matches as the citation ledger holds it or in the ASCII form Hermes' URL tools request; a redirect "
    "target is never matched to the URL that redirected to it, so a citation of the pre-redirect URL reads as "
    "missing. It is not evidence that the page supports the claim the draft makes from it."
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
# Copied from Hermes `tools/url_safety.py` `normalize_url_for_request` (read only): the safe set and the
# whitespace repair after the scheme separator.
_REQUEST_SAFE: Final = "/%:@!$&'()*+,;="
_SCHEME_GAP_RE: Final = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)\s+")


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


def request_normalized_url(url: str) -> str:
    """The ASCII URL Hermes' URL tools request for ``url`` (`tools/url_safety.normalize_url_for_request`).

    Copied, not imported: Hermes is the host, not a dependency. IDNA-encode
    the host and percent-encode non-ASCII path, query and fragment text,
    keeping existing escapes and URL syntax; anything that is not an http(s)
    URL is returned stripped and otherwise unchanged.
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    raw = _SCHEME_GAP_RE.sub(r"\1", raw)
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
    except ValueError:
        return raw
    if parsed.scheme.lower() not in ("http", "https"):
        return raw
    netloc = parsed.netloc
    if hostname:
        try:
            ascii_host = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            ascii_host = hostname
        if ascii_host != hostname:
            netloc = netloc.replace(hostname, ascii_host, 1)
    return urlunsplit((
        parsed.scheme,
        netloc,
        quote(parsed.path, safe=_REQUEST_SAFE),
        quote(parsed.query, safe=_REQUEST_SAFE + "?"),
        quote(parsed.fragment, safe=_REQUEST_SAFE + "?"),
    ))


def ledger_url_keys(url: str) -> tuple[str, ...]:
    """The receipt keys a ledger URL matches: as written, then as Hermes requests it (one key when they agree)."""
    keys = [url_key(url)]
    requested = url_key(request_normalized_url(url))
    if requested not in keys:
        keys.append(requested)
    return tuple(keys)


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


def read_refusals(omh_home: Path, session_id: str) -> int | None:
    """How many receipt writes the hook refused for one session: 0 with no sidecar, None when it cannot be read."""
    path = refusal_path(omh_home, session_id)
    try:
        if path.is_symlink():
            return None
        if not path.exists():
            return 0
        with path.open("rb") as handle:
            raw = handle.read(REFUSAL_BYTE_LIMIT + 1)
        if len(raw) > REFUSAL_BYTE_LIMIT:
            return None
        return min(max(0, int(raw.strip() or b"0")), REFUSAL_COUNT_LIMIT)
    except (OSError, ValueError):
        return None


def child_sessions(omh_home: Path, session_id: str) -> tuple[list[str], str]:
    """Child session ids from the session's delegation ledger, and how that ledger read.

    ``absent``: no ledger file, so no child was ever started under the
    session (the ledger is created by the first ``subagent_start``) and
    there is no child to miss. ``unreadable``: a file is there but is not a
    readable ledger (unparseable, a symlink, oversize, another session's), so
    a child it names cannot be ruled out. ``read``: its children are listed.
    """
    if not os.path.lexists(ledger_path(omh_home, session_id)):
        return [], LEDGER_ABSENT
    record = read_ledger(omh_home, session_id)
    if record is None:
        return [], LEDGER_UNREADABLE
    children: dict[str, None] = {}
    for child in record.get("children", []):
        child_id = child.get("child_session_id") if isinstance(child, dict) else None
        if isinstance(child_id, str) and child_id and child_id != session_id:
            children.setdefault(child_id, None)
    return list(children), LEDGER_READ


def earlier_segments(hermes_home: Path, session_id: str) -> tuple[list[str], bool]:
    """The earlier compaction segments of ``session_id``'s conversation, nearest first, and whether the walk resolved.

    The TUI's own walk (`tui/panels.earlier_segments`): an unverified answer
    keeps only the segments it verified and reports the walk as unresolved.
    """
    try:
        answer = compaction_ancestors(str(hermes_home), session_id)
    except (OSError, ValueError):
        return [], False
    found = answer.get("ancestors")
    segments = [item for item in found if isinstance(item, str) and item] if isinstance(found, list) else []
    return segments, answer.get("status") == "resolved"


def build_citation_receipt_check(
    *,
    ledger: Mapping[int, str],
    draft_text: str,
    session_id: str,
    receipts_by_session: Mapping[str, Sequence[Mapping[str, str]]],
    delegation_ledgers: Mapping[str, str],
    segments: Sequence[str] = (),
    segments_resolved: bool = True,
    receipt_refusals: Mapping[str, int | None] | None = None,
) -> dict[str, Any]:
    """The ``citation_receipt_check/v1`` payload; pure, so every status is testable without a store.

    ``delegation_ledgers`` maps each conversation segment to how its ledger
    read (``read``/``absent``/``unreadable``); ``segments`` is the
    conversation's segments, ``session_id`` first. An unmatched citation is
    ``missing`` only when no ledger was unreadable and the segment walk
    resolved; otherwise ``child_unresolved``.
    """
    fetched_in: dict[str, list[str]] = {}
    listed_in: dict[str, list[str]] = {}
    for sid, receipts in receipts_by_session.items():
        for receipt in receipts:
            target = fetched_in if receipt.get("kind") == KIND_FETCHED else listed_in
            sessions = target.setdefault(str(receipt.get("url_key")), [])
            if sid not in sessions:
                sessions.append(sid)
    ledger_states = set(delegation_ledgers.values())
    if LEDGER_UNREADABLE in ledger_states or not ledger_states:
        ledger_state = LEDGER_UNREADABLE
    elif LEDGER_READ in ledger_states:
        ledger_state = LEDGER_READ
    else:
        ledger_state = LEDGER_ABSENT
    tree_resolved = ledger_state != LEDGER_UNREADABLE and segments_resolved
    citations: list[dict[str, Any]] = []
    for source_id in cited_ids(draft_text):
        url = ledger.get(source_id)
        if url is None:
            citations.append({"id": source_id, "status": STATUS_NOT_IN_LEDGER, "url_display": "", "sessions": []})
            continue
        keys = ledger_url_keys(url)
        fetched = sorted({sid for key in keys for sid in fetched_in.get(key, ())})
        listed = sorted({sid for key in keys for sid in listed_in.get(key, ())})
        if fetched:
            status, sessions = STATUS_FETCHED, fetched
        elif listed:
            status, sessions = STATUS_SEARCH_ONLY, listed
        else:
            status, sessions = (STATUS_MISSING if tree_resolved else STATUS_CHILD_UNRESOLVED), []
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
        "segments": list(segments) or [session_id],
        "segments_resolved": segments_resolved,
        "delegation_ledger": ledger_state,
        "delegation_ledgers": dict(sorted(delegation_ledgers.items())),
        "receipt_refusals": dict(sorted((receipt_refusals or {}).items())),
        "citations": citations,
        "counts": counts,
        "coverage": coverage.to_payload(),
        "all_fetched": bool(citations) and counts[STATUS_FETCHED] == len(citations),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def check_draft_receipts(
    *, omh_home: Path, hermes_home: Path, session_id: str, citations_path: Path, draft_path: Path
) -> dict[str, Any]:
    """Read the ledger, the draft and the session tree's receipts, then build the check."""
    ledger = read_citation_ledger(citations_path)
    draft_text = read_draft(draft_path)
    ancestors, segments_resolved = earlier_segments(hermes_home, session_id)
    segments = list(dict.fromkeys([session_id, *ancestors]))
    sessions: dict[str, None] = dict.fromkeys(segments)
    ledgers: dict[str, str] = {}
    for segment in segments:
        children, ledgers[segment] = child_sessions(omh_home, segment)
        sessions.update(dict.fromkeys(children))
    receipts = {sid: read_session_receipts(omh_home, sid) for sid in sessions}
    refusals = {sid: read_refusals(omh_home, sid) for sid in sessions}
    return build_citation_receipt_check(
        ledger=ledger,
        draft_text=draft_text,
        session_id=session_id,
        receipts_by_session=receipts,
        delegation_ledgers=ledgers,
        segments=segments,
        segments_resolved=segments_resolved,
        receipt_refusals=refusals,
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
    "earlier_segments",
    "ledger_url_keys",
    "ledger_urls",
    "read_citation_ledger",
    "read_draft",
    "read_refusals",
    "read_session_receipts",
    "request_normalized_url",
]
