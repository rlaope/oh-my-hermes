from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..coding.cross_phase_audit import run_cross_phase_audit
from ..installer import OmhError
from .common import _print_json


def _read_json(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OmhError(f"could not read JSON evidence: {exc}") from exc


def cmd_audit_cross_phase(args: argparse.Namespace) -> int:
    checkpoint = _read_json(args.checkpoint) if args.checkpoint else None
    memory_pack = _read_json(args.memory_pack) if args.memory_pack else None
    payload = run_cross_phase_audit(
        args.repo,
        seed_id=args.seed,
        checkpoint=checkpoint if isinstance(checkpoint, dict) else None,
        memory_pack=memory_pack,
        token_budget=args.token_budget,
    )
    _print_json(payload)
    return 0 if payload["ok"] else 1


def _add_audit_commands(sub) -> None:
    audit = sub.add_parser(
        "audit", help="Run read-only cross-phase continuity and evidence audits."
    )
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    cross_phase = audit_sub.add_parser(
        "cross-phase",
        help="Audit memory telemetry, feature branch, and Git checkpoint continuity.",
    )
    cross_phase.add_argument("--repo", default=".")
    cross_phase.add_argument("--seed", default="")
    cross_phase.add_argument(
        "--checkpoint", help="JSON checkpoint captured by `omh git checkpoint`."
    )
    cross_phase.add_argument("--memory-pack", help="JSON handoff memory recall pack.")
    cross_phase.add_argument("--token-budget", type=int, default=8192)
    cross_phase.set_defaults(func=cmd_audit_cross_phase)
