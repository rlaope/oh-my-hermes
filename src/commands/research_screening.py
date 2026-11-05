"""`omh research screening freeze|prepare|merge`: two-reviewer title/abstract screening.

Agent-facing backend for the systematic-review skill. Hermes freezes the
person's criteria, prepares blind task files for two subagent reviewers, and
merges their answer lines deterministically. Normal users ask Hermes for a
systematic review; they never need these commands. Nothing here makes a
network or model call.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..installer import OmhError
from ..quality.reported_rate import format_reported_rate, reported_rate
from ..workflows.systematic_review import (
    BATCH_SIZE_DEFAULT,
    MERGE_SCHEMA_VERSION,
    ScreeningInputError,
    freeze_protocol,
    merge_answers,
    parse_reviewer_models,
    prepare_tasks,
)
from .common import _print_json, _wants_json


def _screening_merge_exit_code(payload: Any) -> int:
    """0 only when every record is decided: no conflict and no pending record remain.

    1 when any conflict or pending record remains after adjudication, so a
    skill reading only the status cannot report an unfinished screen as done.
    2 is what `main` returns for an OmhError (unreadable or malformed input,
    an adjudication line for a record that is not a conflict), so a caller can
    tell "the merge could not run" from "the merge ran and work remains".

    Generic failure signals -- a refused or interrupted run, or a unit
    carrying a failure kind -- are never success either.
    """
    summary = payload if isinstance(payload, dict) else {}
    if summary.get("refused") or summary.get("interrupted"):
        return 1
    units = summary.get("units")
    if isinstance(units, list) and any(isinstance(unit, dict) and unit.get("failure_kind") for unit in units):
        return 1
    if summary.get("schema_version") == MERGE_SCHEMA_VERSION or "counts" in summary:
        counts = summary.get("counts")
        if not isinstance(counts, dict):
            return 1
        if counts.get("conflicts") != 0 or counts.get("pending") != 0:
            return 1
    return 0


def _path(value: str) -> Path:
    return Path(value).expanduser()


def cmd_research_screening_freeze(args: argparse.Namespace) -> int:
    try:
        protocol = freeze_protocol(criteria_path=_path(args.criteria), codes_path=_path(args.codes), out_dir=_path(args.out))
    except ScreeningInputError as exc:
        raise OmhError(str(exc)) from exc
    summary = {
        "schema_version": protocol["schema_version"],
        "protocol": str(_path(args.out) / "protocol.json"),
        "protocol_sha256": protocol["protocol_sha256"],
        "criteria_sha256": protocol["criteria_sha256"],
        "codes": [code["code"] for code in protocol["codes"]],
        "frozen_at": protocol["frozen_at"],
    }
    if _wants_json(args):
        _print_json(summary)
    else:
        print(f"protocol frozen: {summary['protocol']}")
        print(f"protocol_sha256: {summary['protocol_sha256']}")
        print("codes: " + ", ".join(summary["codes"]))
    return 0


def cmd_research_screening_prepare(args: argparse.Namespace) -> int:
    try:
        manifest = prepare_tasks(
            screening_dir=_path(args.dir), records_path=_path(args.records), seed=args.seed, batch_size=args.batch_size
        )
    except ScreeningInputError as exc:
        raise OmhError(str(exc)) from exc
    summary = {
        "schema_version": manifest["schema_version"],
        "manifest": str(_path(args.dir) / "manifest.json"),
        "protocol_sha256": manifest["protocol_sha256"],
        "records_sha256": manifest["records_sha256"],
        "seed": manifest["seed"],
        "record_count": manifest["record_count"],
        "task_files": [batch["path"] for batch in manifest["batches"]],
    }
    if _wants_json(args):
        _print_json(summary)
    else:
        print(f"prepared {summary['record_count']} records for reviewers A and B: {summary['manifest']}")
        for path in summary["task_files"]:
            print(f"  {path}")
    return 0


def cmd_research_screening_merge(args: argparse.Namespace) -> int:
    try:
        models = parse_reviewer_models(args.reviewer_models) if args.reviewer_models is not None else None
        payload = merge_answers(
            screening_dir=_path(args.dir),
            answers_a=_path(args.answers_a),
            answers_b=_path(args.answers_b),
            adjudication=_path(args.adjudication) if args.adjudication else None,
            reviewer_models=models,
        )
    except ScreeningInputError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        print(_render_merge_text(payload))
    return _screening_merge_exit_code(payload)


def _render_merge_text(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    agreement = payload["agreement"]
    observed = agreement["observed_agreement"]
    rate = reported_rate(
        numerator=observed["numerator"],
        denominator=observed["denominator"],
        numerator_of=observed["numerator_of"],
        denominator_of=observed["denominator_of"],
        excluded=observed["excluded"],
    )
    by_code = ", ".join(f"{code} {n}" for code, n in counts["excluded_by_code"].items())
    kappa = agreement["cohen_kappa"]
    pabak = agreement["pabak"]
    lines = [
        f"records {counts['records']}: included {counts['included']}, excluded {counts['excluded']} ({by_code}), "
        f"conflicts {counts['conflicts']}, adjudicated {counts['adjudicated']}, pending {counts['pending']}",
        f"observed agreement: {format_reported_rate(rate)}",
        f"cohen_kappa: {'undefined (' + agreement['kappa_undefined_reason'] + ')' if kappa is None else kappa}; "
        f"pabak: {'undefined' if pabak is None else pabak}",
        f"reviewer independence: {payload['reviewer_independence']}",
    ]
    if payload["conflict_ids"]:
        lines.append("conflicts: " + ", ".join(payload["conflict_ids"]))
    for row in payload["pending"]:
        shown = ", ".join(f"{reviewer} {reason}" for reviewer, reason in sorted(row["reviewers"].items()))
        lines.append(f"pending {row['id']}: {shown}")
    if payload["code_disagreements"]:
        lines.append("exclusion code disagreements: " + ", ".join(payload["code_disagreements"]))
    for warning in payload["warnings"]:
        lines.append(f"warning: {warning}")
    lines.append("screening complete" if counts["conflicts"] == 0 and counts["pending"] == 0 else "screening incomplete")
    lines.append(payload["claim_boundary"])
    return "\n".join(lines)


def add_screening_commands(research_sub) -> None:
    screening = research_sub.add_parser(
        "screening",
        help="Two-reviewer title/abstract screening for the systematic-review skill (freeze, prepare, merge).",
        description=(
            "Agent-facing backend for the systematic-review skill. freeze writes the criteria once, prepare writes "
            "blind task files for reviewers A and B, merge decides each record from both reviewers' answer lines. "
            "No network or model call."
        ),
    )
    screening_sub = screening.add_subparsers(dest="screening_command", required=True)

    freeze = screening_sub.add_parser(
        "freeze",
        help="Write DIR/protocol.json (screening_protocol/v1) once from the criteria text and exclusion codes.",
        description="Write-once: exit 2 when DIR/protocol.json already exists or an input is malformed.",
    )
    freeze.add_argument("--criteria", required=True, help="UTF-8 protocol text, at most 20000 characters.")
    freeze.add_argument("--codes", required=True, help='JSON list of {"code": "E1", "label": "..."} in application order.')
    freeze.add_argument("--out", required=True, help="Screening directory to create protocol.json in.")
    freeze.add_argument("--json", action="store_true", help="Print a JSON summary.")
    freeze.set_defaults(func=cmd_research_screening_freeze)

    prepare = screening_sub.add_parser(
        "prepare",
        help="Write DIR/tasks/A|B/batch-NNN.md and DIR/manifest.json (screening_manifest/v1).",
        description="Exit 2 when DIR/tasks already exists, the protocol was edited, or a record is malformed.",
    )
    prepare.add_argument("--dir", required=True, help="Screening directory holding protocol.json.")
    prepare.add_argument("--records", required=True, help="JSONL rows {id, title, abstract}; id unique and non-empty.")
    prepare.add_argument("--seed", required=True, type=int, help="Seed for each reviewer's record order.")
    prepare.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT, help="Records per task file (default 25).")
    prepare.add_argument("--json", action="store_true", help="Print a JSON summary.")
    prepare.set_defaults(func=cmd_research_screening_prepare)

    merge = screening_sub.add_parser(
        "merge",
        help="Merge both reviewers' answers into screening_merge/v1; exit 0 only when every record is decided.",
        description=(
            "Exit 0 when no conflict and no pending record remains after adjudication; 1 when any remain; "
            "2 for an input error. Agreement is between two reviewers, not accuracy."
        ),
    )
    merge.add_argument("--dir", required=True, help="Screening directory holding protocol.json and manifest.json.")
    merge.add_argument("--answers-a", required=True, help="Reviewer A's answer file, or a directory of *.md files.")
    merge.add_argument("--answers-b", required=True, help="Reviewer B's answer file, or a directory of *.md files.")
    merge.add_argument("--adjudication", default=None, help="Adjudication lines (no UNSURE) for conflict records only.")
    merge.add_argument("--reviewer-models", default=None, help="A=<model>,B=<model>; equal models are not independent.")
    merge.add_argument("--json", action="store_true", help="Print the screening_merge/v1 payload.")
    merge.set_defaults(func=cmd_research_screening_merge)
