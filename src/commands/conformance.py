from __future__ import annotations

import argparse

from ..conformance.checker import check_runtime_run
from ..conformance.contract import CLAIM_LABELS, Claim, ConformanceReport
from ..installer import OmhError
from .common import _paths, _print_json, _wants_json


def cmd_conformance_check(args: argparse.Namespace) -> int:
    try:
        report = check_runtime_run(_paths(args), str(args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    if _wants_json(args):
        _print_json(report)
    else:
        _print_human_report(report)
    return 0 if report["ok"] else 1


def _print_human_report(report: ConformanceReport) -> None:
    subject = report["subject"]
    print(f"Conformance: runtime run {subject['id']}")
    print(f"Status: {report['claim_state'].replace('_', ' ')}")
    if not report["ok"]:
        print("Conformance result: invalid")
        for violation in report["violations"]:
            print(f"Violation: {violation}")
    print(f"Allowed claim: {_claim_label(report['claim_state'])}")
    blocked = _primary_blocked_claim(report)
    if blocked:
        print(f"Blocked claim: {_claim_label(blocked['claim'])}")
        print(f"Reason: {blocked['reason']}.")
    if report.get("next_action"):
        print(f"Next action: {report['next_action']}")
    if report.get("safe_summary"):
        print(f"Summary: {report['safe_summary']}")
    print(f"Boundary: {report['claim_boundary']}")


def _primary_blocked_claim(report: ConformanceReport) -> dict[str, str] | None:
    blocked = report["blocked_claims"]
    if not blocked:
        return None
    if report["claim_state"] == Claim.HANDOFF_PREPARED.value:
        for claim in blocked:
            if claim["claim"] == Claim.EXECUTION_OBSERVED.value:
                return claim
    return blocked[0]


def _claim_label(claim: str) -> str:
    return CLAIM_LABELS.get(Claim(claim), claim.replace("_", " "))


def _add_conformance_commands(sub) -> None:
    conformance = sub.add_parser("conformance", help="Check which OMH evidence claims are currently safe to make.")
    conformance_sub = conformance.add_subparsers(dest="conformance_command", required=True)

    check = conformance_sub.add_parser("check", help="Check runtime-run claim conformance.")
    check.add_argument("--run", dest="run_id", required=True, help="Runtime run id to check.")
    check.add_argument("--json", action="store_true", help="Print machine-readable conformance report JSON.")
    check.set_defaults(func=cmd_conformance_check)
