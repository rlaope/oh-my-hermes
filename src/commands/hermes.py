from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..hermes_planning import attach_plan_artifact_to_wrapper_contract, build_hermes_plan_payload, write_hermes_plan
from ..ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from ..installer import OmhError
from .common import _explicit_source_metadata, _paths, _print_json


def cmd_hermes_plan(args: argparse.Namespace) -> int:
    try:
        source_metadata: dict[str, str] = {}
        if args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            event = json.loads(raw)
            message = extract_message_text(event)
            source_metadata = extract_source_metadata(event)
        elif args.stdin:
            message = sys.stdin.read().strip()
        else:
            message = " ".join(args.message).strip()
        source_metadata.update(_explicit_source_metadata(args))
        payload = build_hermes_plan_payload(
            message,
            source=args.source,
            limit=args.limit,
            source_metadata=source_metadata,
        )
        if args.record:
            artifact = write_hermes_plan(_paths(args), payload)
            payload["artifact"] = artifact
            attach_plan_artifact_to_wrapper_contract(payload, artifact)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _add_hermes_commands(sub) -> None:
    hermes = sub.add_parser("hermes")
    hermes_sub = hermes.add_subparsers(dest="hermes_command", required=True)

    plan = hermes_sub.add_parser("plan")
    plan.add_argument("message", nargs="*", help="Task description to turn into a Hermes-facing planning scaffold.")
    plan.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the planning request.",
    )
    plan.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    plan.add_argument("--stdin", action="store_true", help="Read the raw planning task from stdin.")
    plan.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    plan.add_argument("--record", action="store_true", help="Write the plan under .hermes/plans.")
    plan.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    plan.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    plan.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    plan.set_defaults(func=cmd_hermes_plan)
