from __future__ import annotations

import argparse

from ..coding_delegation import CODING_EXECUTOR_TARGETS
from ..demo import DEFAULT_ORCHESTRATION_MESSAGE, build_orchestration_demo
from ..grounded_score import build_grounded_score_demo, format_grounded_score_summary
from ..quality.chat_card_coverage import build_chat_card_coverage_demo, format_chat_card_coverage_summary
from ..quality.context_brief_coverage import (
    build_context_brief_coverage_demo,
    format_context_brief_coverage_summary,
)
from ..quality.hermes_ux_quality import build_hermes_ux_quality_demo, format_hermes_ux_quality_summary
from ..quality.localized_chat_copy import (
    build_localized_chat_copy_demo,
    format_localized_chat_copy_summary,
)
from ..quality.route_hint_alignment import build_route_hint_alignment_demo, format_route_hint_alignment_summary
from ..quality.router_fast_path import build_router_fast_path_demo, format_router_fast_path_summary
from ..quality.routing_precision import build_routing_precision_demo, format_routing_precision_summary
from ..ingress import CHAT_SOURCES
from ..installer import OmhError
from .common import _print_json


DEMO_EPILOG = """Demo lanes:
  orchestration           Shows recommend -> chat -> plan -> handoff -> status for one request.
  grounded-score          Scores representative real-world prompts against dedicated OMH routes.
  chat-card-coverage      Verifies wrapper cards are specific, not generic acknowledgements.
  route-hint-alignment    Checks plugin/router route hints agree before Hermes speaks.
  context-brief-coverage  Checks compact OMH context briefs keep the right workflow visible.
  routing-precision       Guards against over-routing simple requests and missing OMH interventions.
  router-fast-path        Checks common chat turns stay on deterministic fast-path routes.
  localized-chat-copy     Verifies common non-English prompts keep local Hermes card framing.
  hermes-ux-quality       Runs the combined user-feel gate across routing, cards, hints, and context.

Recommended operator checks:
  omh demo hermes-ux-quality --summary
  omh demo localized-chat-copy --summary
  omh demo router-fast-path --summary
  omh demo routing-precision --summary
  omh demo orchestration "I want to safely add a feature to this repo"

Boundary:
  Demo commands are deterministic local contract artifacts. They do not call Hermes,
  dispatch a coding agent, deliver a chat message, or observe platform runtime evidence.
"""


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


def cmd_demo_route_hint_alignment(args: argparse.Namespace) -> int:
    try:
        payload = build_route_hint_alignment_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_route_hint_alignment_summary(payload))
    else:
        _print_json(payload)
    return 0


def cmd_demo_context_brief_coverage(args: argparse.Namespace) -> int:
    try:
        payload = build_context_brief_coverage_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_context_brief_coverage_summary(payload))
    else:
        _print_json(payload)
    return 0


def cmd_demo_routing_precision(args: argparse.Namespace) -> int:
    try:
        payload = build_routing_precision_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_routing_precision_summary(payload))
    else:
        _print_json(payload)
    return 0


def cmd_demo_localized_chat_copy(args: argparse.Namespace) -> int:
    try:
        payload = build_localized_chat_copy_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_localized_chat_copy_summary(payload))
    else:
        _print_json(payload)
    return 0


def cmd_demo_router_fast_path(args: argparse.Namespace) -> int:
    try:
        payload = build_router_fast_path_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_router_fast_path_summary(payload))
    else:
        _print_json(payload)
    return 0


def cmd_demo_hermes_ux_quality(args: argparse.Namespace) -> int:
    try:
        payload = build_hermes_ux_quality_demo(source=args.source)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if args.summary:
        print(format_hermes_ux_quality_summary(payload))
    else:
        _print_json(payload)
    return 0


def _add_demo_commands(sub) -> None:
    demo = sub.add_parser(
        "demo",
        help="Print deterministic demo artifacts for OMH orchestration examples.",
        description=(
            "Run local OMH demo artifacts that show how Hermes should route, explain, "
            "and status workflow requests before any live platform or executor evidence exists."
        ),
        epilog=DEMO_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    demo_sub = demo.add_subparsers(dest="demo_command", required=True, metavar="<demo>")

    orchestration = demo_sub.add_parser(
        "orchestration",
        help="Show the recommend -> chat -> plan -> handoff -> status flow for one request.",
        description="Build a fixture-backed end-to-end orchestration artifact for one natural-language request.",
    )
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

    grounded_score = demo_sub.add_parser(
        "grounded-score",
        help="Score representative prompts against dedicated OMH workflow routes.",
        description="Evaluate whether real-world operator prompts land on the intended OMH workflow instead of generic chat.",
    )
    grounded_score.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    output = grounded_score.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    output.add_argument("--summary", action="store_true", help="Print a compact human-readable score summary.")
    grounded_score.set_defaults(func=cmd_demo_grounded_score)

    card_coverage = demo_sub.add_parser(
        "chat-card-coverage",
        help="Verify routed prompts produce specific wrapper cards.",
        description="Check that wrapper-facing chat cards stay workflow-specific and avoid generic acknowledgement responses.",
    )
    card_coverage.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    card_output = card_coverage.add_mutually_exclusive_group()
    card_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    card_output.add_argument("--summary", action="store_true", help="Print a compact human-readable card coverage summary.")
    card_coverage.set_defaults(func=cmd_demo_chat_card_coverage)

    route_hint_alignment = demo_sub.add_parser(
        "route-hint-alignment",
        help="Check router and plugin awareness route hints agree.",
        description="Compare router decisions with plugin-awareness hints so Hermes receives the same workflow guidance.",
    )
    route_hint_alignment.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    alignment_output = route_hint_alignment.add_mutually_exclusive_group()
    alignment_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    alignment_output.add_argument("--summary", action="store_true", help="Print a compact human-readable alignment summary.")
    route_hint_alignment.set_defaults(func=cmd_demo_route_hint_alignment)

    context_brief_coverage = demo_sub.add_parser(
        "context-brief-coverage",
        help="Check compact OMH context briefs keep the right workflow visible.",
        description="Verify context briefs expose the workflow, next action, and boundary that wrappers or plugins should show.",
    )
    context_brief_coverage.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    context_output = context_brief_coverage.add_mutually_exclusive_group()
    context_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    context_output.add_argument("--summary", action="store_true", help="Print a compact human-readable context brief coverage summary.")
    context_brief_coverage.set_defaults(func=cmd_demo_context_brief_coverage)

    routing_precision = demo_sub.add_parser(
        "routing-precision",
        help="Guard against over-routing simple prompts and missing OMH interventions.",
        description="Evaluate negative controls and intervention prompts so OMH routes only when it adds workflow value.",
    )
    routing_precision.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    precision_output = routing_precision.add_mutually_exclusive_group()
    precision_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    precision_output.add_argument("--summary", action="store_true", help="Print a compact human-readable routing precision summary.")
    routing_precision.set_defaults(func=cmd_demo_routing_precision)

    localized_chat_copy = demo_sub.add_parser(
        "localized-chat-copy",
        help="Verify non-English prompts keep local Hermes card framing.",
        description=(
            "Check common non-English operator prompts for expected locale, workflow card kind, "
            "next action, and local framing without calling a translation API."
        ),
    )
    localized_chat_copy.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    localized_output = localized_chat_copy.add_mutually_exclusive_group()
    localized_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    localized_output.add_argument("--summary", action="store_true", help="Print a compact human-readable localized copy summary.")
    localized_chat_copy.set_defaults(func=cmd_demo_localized_chat_copy)

    router_fast_path = demo_sub.add_parser(
        "router-fast-path",
        help="Check common chat turns stay on fast-path routes.",
        description=(
            "Verify high-frequency picker, status, direct-answer, file lookup, setup health, "
            "and workflow requests keep explicit fast-path markers instead of drifting to full scoring."
        ),
    )
    router_fast_path.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    fast_path_output = router_fast_path.add_mutually_exclusive_group()
    fast_path_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    fast_path_output.add_argument("--summary", action="store_true", help="Print a compact human-readable fast-path summary.")
    router_fast_path.set_defaults(func=cmd_demo_router_fast_path)

    hermes_ux_quality = demo_sub.add_parser(
        "hermes-ux-quality",
        help="Run the combined user-feel quality gate.",
        description="Aggregate the major deterministic demos into one pass/fail Hermes UX quality report.",
    )
    hermes_ux_quality.add_argument("--source", choices=CHAT_SOURCES, default="discord")
    ux_output = hermes_ux_quality.add_mutually_exclusive_group()
    ux_output.add_argument("--json", action="store_true", help="Print the full machine-readable JSON payload. This is the default.")
    ux_output.add_argument("--summary", action="store_true", help="Print a compact human-readable Hermes UX quality summary.")
    hermes_ux_quality.set_defaults(func=cmd_demo_hermes_ux_quality)
