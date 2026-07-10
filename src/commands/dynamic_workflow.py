from __future__ import annotations

import argparse
import json

from ..dynamic_workflow import (
    build_dynamic_coding_workflow,
    render_dynamic_workflow_svg,
    write_dynamic_coding_workflow,
)
from ..ingress import CHAT_SOURCES, extract_message_text
from ..installer import OmhError
from .common import _chat_input_and_metadata, _paths, _print_json


def cmd_coding_dynamic_workflow(args: argparse.Namespace) -> int:
    try:
        event_or_message, source_metadata = _chat_input_and_metadata(args)
        message = extract_message_text(event_or_message)
        payload = build_dynamic_coding_workflow(
            message,
            source=args.source,
            planners=args.planner,
            critics=args.critic,
            implementers=args.implementer,
            reviewers=args.reviewer,
            reporter=args.reporter,
            source_metadata=source_metadata,
        )
        if args.write:
            payload = write_dynamic_coding_workflow(_paths(args), payload)
        if args.include_svg:
            payload["chart_svg"] = render_dynamic_workflow_svg(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _add_dynamic_workflow_command(coding_sub) -> None:
    dynamic = coding_sub.add_parser(
        "dynamic-workflow",
        help="Prepare a typed target workflow JSON contract and SVG chart.",
    )
    dynamic.add_argument("message", nargs="*", help="Coding goal to convert into a dynamic workflow plan.")
    dynamic.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the coding request.",
    )
    dynamic.add_argument("--stdin", action="store_true", help="Read the raw coding goal from stdin.")
    dynamic.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    dynamic.add_argument(
        "--planner",
        action="append",
        help=(
            "Planner spec as target[:model[:label[:cost_tier[:target_type]]]]. "
            "Defaults to the dynamic planning model pool."
        ),
    )
    dynamic.add_argument(
        "--critic",
        action="append",
        help=(
            "Critic spec as target[:model[:label[:cost_tier[:target_type]]]]. "
            "Defaults to the dynamic critique model pool."
        ),
    )
    dynamic.add_argument(
        "--implementer",
        action="append",
        help=(
            "Implementation target spec as target[:model[:label[:cost_tier[:target_type]]]]. "
            "Repeat for fan-out lanes."
        ),
    )
    dynamic.add_argument(
        "--reviewer",
        action="append",
        help=(
            "Review target spec as target[:model[:label[:cost_tier[:target_type]]]]. "
            "Repeat for independent reviewers."
        ),
    )
    dynamic.add_argument(
        "--reporter",
        default=None,
        help="Final report owner spec as target[:model[:label[:cost_tier[:target_type]]]].",
    )
    dynamic.add_argument("--write", action="store_true", help="Write workflow.json and workflow-chart.svg under .omh.")
    dynamic.add_argument(
        "--include-svg",
        action="store_true",
        help="Include SVG text in stdout in addition to artifact paths.",
    )
    dynamic.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    dynamic.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    dynamic.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    dynamic.set_defaults(func=cmd_coding_dynamic_workflow)
