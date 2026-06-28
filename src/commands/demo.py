from __future__ import annotations

import argparse

from ..coding_delegation import CODING_EXECUTOR_TARGETS
from ..demo import DEFAULT_ORCHESTRATION_MESSAGE, build_orchestration_demo
from ..grounded_score import build_grounded_score_demo, format_grounded_score_summary
from ..quality.chat_card_coverage import build_chat_card_coverage_demo, format_chat_card_coverage_summary
from ..ingress import CHAT_SOURCES
from ..installer import OmhError
from .common import _print_json


def cmd_demo_orchestration(args: argparse.Namespace) -> int:
    message = " ".join(args.message).strip() or DEFAULT_ORCHESTRATION_MESSAGE
    try:
        _print_json(
            build_orchestration_demo(
                message,
                source=args.source,
                limit=args.limit,
                executor_target=args.executor,
            )
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_demo_grounded_score(args: argparse.Namespace) -> int:
    try:
        payload = build_grounded_score_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_grounded_score_summary(payload))
    else:
        _print_json(payload)
    return 0


def cmd_demo_chat_card_coverage(args: argparse.Namespace) -> int:
    try:
        payload = build_chat_card_coverage_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_chat_card_coverage_summary(payload))
    else:
        _print_json(payload)
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
    orchestration.add_argument(
        "--executor",
        choices=CODING_EXECUTOR_TARGETS,
        default="choose",
        help="Executor/runtime profile to demonstrate. Defaults to an explicit choice-required handoff.",
    )
    orchestration.set_defaults(func=cmd_demo_orchestration)

    grounded_score = demo_sub.add_parser("grounded-score")
    grounded_score.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    output = grounded_score.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    output.add_argument("--summary", action="store_true", help="Print a compact human-readable score summary.")
    grounded_score.set_defaults(func=cmd_demo_grounded_score)

    card_coverage = demo_sub.add_parser("chat-card-coverage")
    card_coverage.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    card_output = card_coverage.add_mutually_exclusive_group()
    card_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    card_output.add_argument("--summary", action="store_true", help="Print a compact human-readable card coverage summary.")
    card_coverage.set_defaults(func=cmd_demo_chat_card_coverage)
