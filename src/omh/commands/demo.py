from __future__ import annotations

import argparse

from ..demo import DEFAULT_ORCHESTRATION_MESSAGE, build_orchestration_demo
from ..grounded_score import build_grounded_score_demo
from ..ingress import CHAT_SOURCES
from ..installer import OmhError
from .common import _print_json


def cmd_demo_orchestration(args: argparse.Namespace) -> int:
    message = " ".join(args.message).strip() or DEFAULT_ORCHESTRATION_MESSAGE
    try:
        _print_json(build_orchestration_demo(message, source=args.source, limit=args.limit))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_demo_grounded_score(args: argparse.Namespace) -> int:
    try:
        _print_json(build_grounded_score_demo(source=args.source))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _add_demo_commands(sub) -> None:
    demo = sub.add_parser("demo", help="Print deterministic demo artifacts for OMH orchestration examples.")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)

    orchestration = demo_sub.add_parser("orchestration")
    orchestration.add_argument(
        "message",
        nargs="*",
        help="Optional natural-language request for the deterministic orchestration demo.",
    )
    orchestration.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    orchestration.add_argument("--limit", type=int, default=3)
    orchestration.set_defaults(func=cmd_demo_orchestration)

    grounded_score = demo_sub.add_parser("grounded-score")
    grounded_score.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    grounded_score.set_defaults(func=cmd_demo_grounded_score)
