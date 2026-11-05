"""`omh research receipts verify`: are a draft's cited sources ones the session tree really opened?

Agent-facing infrastructure for the research skills: after grounded-citations'
`sources.py verify`, a skill runs this to report how many cited sources a web
tool actually fetched. Normal users ask Hermes for research; they never need
this command.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from ..installer import OmhError
from ..quality.reported_rate import format_reported_rate, reported_rate
from ..workflows.research_receipt_check import (
    CITATION_RECEIPT_CHECK_SCHEMA_VERSION,
    CITATION_STATUSES,
    STATUS_FETCHED,
    ReceiptCheckInputError,
    check_draft_receipts,
)
from .common import _command_hermes_session_id, _paths, _print_json, _wants_json


def _receipts_verify_exit_code(payload: Any) -> int:
    """0 only when every cited source was fetched in the session tree.

    1 for anything else the check can report: a cited source that is
    ``missing``, ``search_only``, ``child_unresolved`` or ``not_in_ledger``,
    and a draft that cites nothing at all -- an empty check is not a passed
    one, and a skill reading only the status must not report coverage it never
    measured. 2 is what `main` returns for an OmhError (no session, an
    unreadable ledger, draft or receipt file), so a caller can tell "the check
    could not run" from "the check ran and found a gap".

    Generic failure signals -- a refused or interrupted run, or a unit
    carrying a failure kind -- are never success either, so this mapper
    cannot be passed by ignoring them.
    """
    summary = payload if isinstance(payload, dict) else {}
    if summary.get("refused") or summary.get("interrupted"):
        return 1
    units = summary.get("units")
    if isinstance(units, list) and any(isinstance(unit, dict) and unit.get("failure_kind") for unit in units):
        return 1
    if summary.get("schema_version") == CITATION_RECEIPT_CHECK_SCHEMA_VERSION or "citations" in summary:
        citations = summary.get("citations")
        if not isinstance(citations, list) or not citations:
            return 1
        if summary.get("all_fetched") is not True:
            return 1
        if any(not isinstance(row, dict) or row.get("status") != STATUS_FETCHED for row in citations):
            return 1
    return 0


def _session_from_args(args: argparse.Namespace) -> tuple[str, str, bool]:
    """``(session, source, override)``: the session checked, ``flag`` or ``env``, and whether
    ``--session`` names a session other than this command's own ``HERMES_SESSION_ID``."""
    flag = str(args.session or "").strip()
    env = _command_hermes_session_id()
    session = flag or env
    if not session:
        raise OmhError("no session: pass --session ID or run inside a Hermes session that sets HERMES_SESSION_ID")
    return session, ("flag" if flag else "env"), bool(flag and env and flag != env)


def cmd_research_receipts_verify(args: argparse.Namespace) -> int:
    session, source, override = _session_from_args(args)
    paths = _paths(args)
    try:
        payload = check_draft_receipts(
            omh_home=Path(paths.omh_home),
            hermes_home=Path(paths.hermes_home),
            session_id=session,
            citations_path=Path(args.citations).expanduser(),
            draft_path=Path(args.draft).expanduser(),
        )
    except ReceiptCheckInputError as exc:
        raise OmhError(str(exc)) from exc
    payload["session_source"] = source
    if override:
        # Read-only, but it lets a draft pass on another session's receipts: say so where a reader looks.
        payload["session_override"] = True
        print(
            f"omh: note: --session {session} is not this command's HERMES_SESSION_ID; "
            "checking another session's receipts",
            file=sys.stderr,
        )
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_render_text(payload))
    return _receipts_verify_exit_code(payload)


def _render_text(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    rate = reported_rate(
        numerator=coverage["numerator"],
        denominator=coverage["denominator"],
        numerator_of=coverage["numerator_of"],
        denominator_of=coverage["denominator_of"],
        excluded=coverage["excluded"],
    )
    segments = "resolved" if payload["segments_resolved"] else "unresolved"
    lines = [
        f"fetched coverage: {format_reported_rate(rate)}",
        f"sessions checked: {len(payload['sessions_checked'])} (delegation ledger {payload['delegation_ledger']}; "
        f"{len(payload['segments'])} conversation segment(s), walk {segments})",
    ]
    refused = {sid: n for sid, n in payload["receipt_refusals"].items() if n != 0}
    if refused:
        shown = ", ".join(f"{sid} {'unreadable' if n is None else n}" for sid, n in refused.items())
        lines.append(f"receipt writes refused: {shown}")
    counts = payload["counts"]
    lines.append("counts: " + ", ".join(f"{status} {counts[status]}" for status in CITATION_STATUSES))
    for row in payload["citations"]:
        shown = f" {row['url_display']}" if row["url_display"] else ""
        lines.append(f"  [{row['id']}] {row['status']}{shown}")
    if not payload["citations"]:
        lines.append("no citations found in the draft")
    lines.append("receipts OK" if payload["all_fetched"] else "receipt check failed")
    lines.append(payload["claim_boundary"])
    return "\n".join(lines)


def _add_research_commands(sub) -> None:
    research = sub.add_parser(
        "research",
        help="Agent infrastructure: check research drafts against the session's fetch receipts.",
        description=(
            "Agent-facing backend for the research skills. Normal use is asking Hermes for research; "
            "these commands verify what a session's web tools really opened."
        ),
    )
    research_sub = research.add_subparsers(dest="research_command", required=True)
    receipts = research_sub.add_parser(
        "receipts",
        help="Fetch receipts (research_fetch_receipt/v1) recorded by post_tool_call for web tools.",
    )
    receipts_sub = receipts.add_subparsers(dest="receipts_command", required=True)
    verify = receipts_sub.add_parser(
        "verify",
        help="Check every citation in a draft against the session tree's fetch receipts; exit 0 only when all were fetched.",
        description=(
            "Match each [n] the draft cites, through the grounded-citations ledger, against fetch receipts in the "
            "session, its earlier compaction segments, and every subagent session their delegation ledgers name. "
            "Statuses: fetched, search_only, missing, "
            "child_unresolved, not_in_ledger. Exit 0 only when every cited source was fetched; 1 for any other status "
            "or a draft with no citations; 2 for a usage or read error. A receipt proves the URL was opened in this "
            "session tree, not that the page supports the claim."
        ),
    )
    verify.add_argument("--citations", required=True, help="grounded-citations ledger JSON ({\"sources\": [...]}).")
    verify.add_argument("--draft", required=True, help="Draft whose [n] citations are checked.")
    verify.add_argument("--session", default=None, help="Hermes session id (default: $HERMES_SESSION_ID).")
    verify.add_argument("--json", action="store_true", help="Print the citation_receipt_check/v1 payload.")
    verify.set_defaults(func=cmd_research_receipts_verify)
