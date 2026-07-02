from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..hermes_planning import (
    attach_plan_artifact_to_wrapper_contract,
    build_hermes_plan_payload,
    read_hermes_plan_artifact,
    update_hermes_plan_status,
    write_hermes_plan,
    write_plan_handoff_context_pack,
)
from ..hermes_readiness import build_hermes_agent_readiness
from ..ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from ..installer import OmhError
from .common import _explicit_source_metadata, _paths, _print_json


def cmd_hermes_plan(args: argparse.Namespace) -> int:
    try:
        lifecycle_result = _maybe_handle_plan_lifecycle_alias(args)
        if lifecycle_result is not None:
            _print_json(lifecycle_result)
            return 0
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


def _maybe_handle_plan_lifecycle_alias(args: argparse.Namespace) -> dict[str, object] | None:
    words = list(getattr(args, "message", []) or [])
    if len(words) != 2 or words[0] not in {"accept", "revise", "cancel"}:
        return None
    path = Path(words[1]).expanduser()
    looks_like_path = path.exists() or words[1].endswith(".md") or "/" in words[1]
    if not looks_like_path:
        return None
    if args.stdin or args.event_json or args.record:
        raise ValueError("omh hermes plan accept/revise/cancel cannot be combined with --stdin, --event-json, or --record")
    status_by_action = {"accept": "accepted", "revise": "revised", "cancel": "cancelled"}
    return update_hermes_plan_status(_paths(args), path, status=status_by_action[words[0]])


def cmd_hermes_plan_accept(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        result = update_hermes_plan_status(paths, args.path, status="accepted", summary=args.summary or "")
        if args.write_context_pack:
            artifact = read_hermes_plan_artifact(args.path)
            result["context_pack"] = write_plan_handoff_context_pack(
                paths,
                artifact,
                executor_target=args.executor,
            )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(result)
    return 0


def cmd_hermes_plan_revise(args: argparse.Namespace) -> int:
    try:
        result = update_hermes_plan_status(_paths(args), args.path, status="revised", summary=args.note or "")
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(result)
    return 0


def cmd_hermes_plan_cancel(args: argparse.Namespace) -> int:
    try:
        result = update_hermes_plan_status(_paths(args), args.path, status="cancelled", summary=args.reason or "")
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(result)
    return 0


def cmd_hermes_readiness(args: argparse.Namespace) -> int:
    try:
        payload = build_hermes_agent_readiness(_paths(args))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _add_hermes_commands(sub) -> None:
    hermes = sub.add_parser("hermes", help="Build Hermes-facing plan and readiness scaffolds for natural-language work.")
    hermes_sub = hermes.add_subparsers(dest="hermes_command", required=True)

    readiness = hermes_sub.add_parser(
        "readiness",
        help="Inspect Hermes Agent runtime surfaces and OMH reinforcement coverage.",
    )
    readiness.set_defaults(func=cmd_hermes_readiness)

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

    plan_accept = hermes_sub.add_parser("plan-accept", help="Mark a file-backed Hermes plan as accepted.")
    plan_accept.add_argument("path", help="Path to a hermes_plan/v1 Markdown artifact.")
    plan_accept.add_argument("--summary", default="", help="Optional metadata-only acceptance summary.")
    plan_accept.add_argument("--write-context-pack", action="store_true", help="Write a handoff_context_pack/v1 pointer for the accepted plan.")
    plan_accept.add_argument("--executor", default="codex", choices=("codex", "generic", "claude-code", "hermes", "omx-runtime", "omo-runtime", "omc-runtime"))
    plan_accept.set_defaults(func=cmd_hermes_plan_accept)

    plan_revise = hermes_sub.add_parser("plan-revise", help="Mark a file-backed Hermes plan as revised.")
    plan_revise.add_argument("path", help="Path to a hermes_plan/v1 Markdown artifact.")
    plan_revise.add_argument("--note", default="", help="Optional metadata-only revision note.")
    plan_revise.set_defaults(func=cmd_hermes_plan_revise)

    plan_cancel = hermes_sub.add_parser("plan-cancel", help="Mark a file-backed Hermes plan as cancelled.")
    plan_cancel.add_argument("path", help="Path to a hermes_plan/v1 Markdown artifact.")
    plan_cancel.add_argument("--reason", default="", help="Optional metadata-only cancellation reason.")
    plan_cancel.set_defaults(func=cmd_hermes_plan_cancel)
