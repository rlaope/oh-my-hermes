"""`omh research receipts verify` and `omh research eval litqa2 prepare|grade`.

Agent-facing infrastructure for the research skills: after grounded-citations'
`sources.py verify`, a skill runs `receipts verify` to report how many cited
sources a web tool actually fetched. `eval litqa2` freezes a LitQA2 sample into
task files and grades the two arms' answers against its key. Normal users ask
Hermes for research; they never need these commands.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from ..installer import OmhError
from ..quality.reported_rate import format_reported_rate, reported_rate
from ..workflows.research_eval_litqa2 import (
    GRADE_SCHEMA_VERSION,
    OUTCOMES,
    LitQA2DigestError,
    LitQA2InputError,
    grade_litqa2,
    parse_receipt_check_args,
    prepare_litqa2,
)
from ..workflows.research_receipt_check import (
    CITATION_RECEIPT_CHECK_SCHEMA_VERSION,
    CITATION_STATUSES,
    STATUS_FETCHED,
    ReceiptCheckInputError,
    check_draft_receipts,
)
from .common import _command_hermes_session_id, _paths, _print_json, _wants_json
from .research_screening import add_screening_commands


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


def _litqa2_grade_exit_code(payload: Any) -> int:
    """0 only when every key task has an answer file for every arm; 1 when any is missing.

    2 is what `main` returns for an OmhError (an unreadable or invalid key,
    answer file or receipt check). A wrong or unsure answer is a graded
    outcome, not a failed grade, so it does not move the code. Generic
    failure signals -- a refused or interrupted run, or a unit carrying a
    failure kind -- are never success either.
    """
    summary = payload if isinstance(payload, dict) else {}
    if summary.get("refused") or summary.get("interrupted"):
        return 1
    units = summary.get("units")
    if isinstance(units, list) and any(isinstance(unit, dict) and unit.get("failure_kind") for unit in units):
        return 1
    if summary.get("schema_version") == GRADE_SCHEMA_VERSION and summary.get("complete") is not True:
        return 1
    return 0


def cmd_research_eval_litqa2_prepare(args: argparse.Namespace) -> int:
    try:
        payload = prepare_litqa2(
            data_path=Path(args.data).expanduser(),
            sha256=args.sha256,
            sample=args.sample,
            seed=args.seed,
            out_dir=Path(args.out).expanduser(),
        )
    except LitQA2DigestError as exc:
        # The data is not the pinned export: a refused run, distinct from a usage error.
        print(f"omh: {exc}", file=sys.stderr)
        return 1
    except LitQA2InputError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        print(f"prepared {payload['task_count']} task(s) in {payload['out_dir']}")
        print(f"data sha256: {payload['data_sha256']} (seed {payload['seed']})")
    return 0


def cmd_research_eval_litqa2_grade(args: argparse.Namespace) -> int:
    try:
        payload = grade_litqa2(
            key_path=Path(args.key).expanduser(),
            answers_dir=Path(args.answers).expanduser(),
            receipt_checks=parse_receipt_check_args(args.receipt_checks),
        )
    except LitQA2InputError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_render_litqa2_grade(payload))
    return _litqa2_grade_exit_code(payload)


def _payload_rate_line(rate: dict[str, Any]) -> str:
    return format_reported_rate(reported_rate(
        numerator=rate["numerator"],
        denominator=rate["denominator"],
        numerator_of=rate["numerator_of"],
        denominator_of=rate["denominator_of"],
        excluded=rate["excluded"],
    ))


def _render_litqa2_grade(payload: dict[str, Any]) -> str:
    key = payload["key"]
    lines = [f"LitQA2 grade: {key['task_count']} task(s), data sha256 {key['data_sha256']}, seed {key['seed']}"]
    for arm, metrics in payload["arms"].items():
        lines.append(f"{arm}:")
        for name in ("accuracy", "precision", "unsure_rate", "unanswered_rate"):
            lines.append(f"  {name}: {_payload_rate_line(metrics[name])}")
        receipts = metrics["receipt_coverage"]
        if receipts["status"] == "observed":
            lines.append(f"  receipt_coverage: {_payload_rate_line(receipts['rate'])} "
                         f"(no_receipt_check {receipts['no_receipt_check']})")
        else:
            lines.append("  receipt_coverage: not_observed")
        lines.append("  counts: " + ", ".join(f"{name} {metrics['counts'][name]}" for name in OUTCOMES))
    paired = payload["paired"]
    lines.append("paired: " + ", ".join(f"{name} {paired[name]}" for name in paired))
    if not payload["complete"]:
        lines.append(f"answer files missing: {payload['missing_answers']}")
    lines.append(payload["claim_boundary"])
    return "\n".join(lines)


def _add_research_commands(sub) -> None:
    research = sub.add_parser(
        "research",
        help="Agent infrastructure: check research drafts against fetch receipts; score research on LitQA2.",
        description=(
            "Agent-facing backend for the research skills. Normal use is asking Hermes for research; "
            "these commands verify what a session's web tools really opened and grade benchmark answers."
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

    evaluation = research_sub.add_parser(
        "eval",
        help="Score the research workflow on a pinned benchmark sample.",
    )
    eval_sub = evaluation.add_subparsers(dest="eval_command", required=True)
    litqa2 = eval_sub.add_parser(
        "litqa2",
        help="LitQA2: freeze a seeded sample into task files, then grade both arms' answers.",
    )
    litqa2_sub = litqa2.add_subparsers(dest="litqa2_command", required=True)
    prepare = litqa2_sub.add_parser(
        "prepare",
        help="Write task files, an answer key and a manifest for a seeded LitQA2 sample into an empty DIR.",
        description=(
            "Check the LitQA2 JSONL export against --sha256, sample --sample rows with --seed, and write "
            "DIR/tasks/<task_id>.md (question, lettered options, the ANSWER-line instruction; never the answer), "
            "DIR/answer_key.json and DIR/manifest.json. Exit 0 when written; 1 when the digest does not match "
            "(nothing written); 2 for a usage error, a malformed row, or a non-empty DIR."
        ),
    )
    prepare.add_argument("--data", required=True, help="LitQA2 JSONL export (read only, never copied).")
    prepare.add_argument("--sha256", required=True, help="Pinned sha256 of the exact --data bytes.")
    prepare.add_argument("--sample", required=True, type=int, help="Number of questions to sample.")
    prepare.add_argument("--seed", required=True, type=int, help="Seed for the sample and the option order.")
    prepare.add_argument("--out", required=True, help="Empty output directory.")
    prepare.add_argument("--json", action="store_true", help="Print the research_eval_litqa2_prepare/v1 payload.")
    prepare.set_defaults(func=cmd_research_eval_litqa2_prepare)
    grade = litqa2_sub.add_parser(
        "grade",
        help="Grade DIR/<arm>/<task_id>.md answers against an answer key; exit 0 only when no answer is missing.",
        description=(
            "Extract the last `ANSWER: <letter>` line of each answer file and report accuracy, precision, unsure "
            "and unanswered rates per arm (omh_reported_rate/v1), paired counts, and receipt coverage from "
            "citation_receipt_check/v1 payloads. The payload carries outcomes and letters, never answer text. "
            "Exit 0 when every task has an answer file for every arm; 1 when any is missing; 2 for an "
            "unreadable or invalid input."
        ),
    )
    grade.add_argument("--key", required=True, help="research_eval_litqa2_key/v1 answer_key.json.")
    grade.add_argument("--answers", required=True, help="Directory holding <arm>/<task_id>.md answer files.")
    grade.add_argument(
        "--receipt-checks", action="append", default=None, metavar="ARM=DIR",
        help="Directory of <task_id>.json citation_receipt_check/v1 payloads for one arm (repeatable).",
    )
    grade.add_argument("--json", action="store_true", help="Print the research_eval_litqa2_grade/v1 payload.")
    grade.set_defaults(func=cmd_research_eval_litqa2_grade)
    add_screening_commands(research_sub)
