from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ..plugin_bundle.omh.context_budget_plan_capacity import parse_must_keep, parse_route_capacity_input
from ..runtime.context_budget_plan import (
    build_route_identity, context_budget_plan_status, prepare_context_budget_plan, rebind_context_budget_plan,
)

from ..context import build_context_brief
from ..workflows.hermes_achievements import observe_achievements
from .common import _action_label, _paths, _print_json, _wants_json


def cmd_context_brief(args: argparse.Namespace) -> int:
    message = " ".join(args.message).strip()
    payload = build_context_brief(
        message,
        source=args.source,
        max_hints=args.limit,
        include_prompt_context=args.prompt_context,
        achievements_profile=_achievements_profile(args),
    )
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_context_brief_summary(payload)
    return 0


def _achievements_profile(args: argparse.Namespace) -> dict[str, object] | None:
    try:
        observation = observe_achievements(_paths(args))
    except OSError:
        return None
    profile = observation.get("agent_profile")
    if isinstance(profile, dict) and profile.get("observed"):
        return profile
    return None


def _print_context_brief_summary(payload: dict[str, object]) -> None:
    print("OMH context brief")
    print("Summary")
    print(f"  Purpose: {payload['purpose']}")
    print(f"  Chat rule: {payload['chat_rule']}")
    route_hint = payload.get("route_hint")
    if isinstance(route_hint, dict):
        primary = str(route_hint.get("primary_workflow") or "")
        action = str(route_hint.get("primary_next_action") or "")
        action_label = str(route_hint.get("primary_next_action_label") or "")
        if primary:
            print(f"  Route hint: {primary} -> {_action_label(action, action_label)}")
        else:
            print("  Route hint: no strong message-specific hint")
    catalog_question = payload.get("catalog_question")
    if isinstance(catalog_question, dict) and catalog_question.get("status") == "matched":
        print(
            "  Catalog question: "
            f"{_action_label(str(catalog_question.get('next_action', '')))} "
            f"via {catalog_question.get('recommended_tool')}"
        )
    profile = payload.get("achievements_profile")
    if isinstance(profile, dict):
        strengths = ", ".join(str(item) for item in list(profile.get("strengths", []))[:3]) or "none observed"
        gaps = ", ".join(str(item) for item in list(profile.get("gaps", []))[:3]) or "none observed"
        print(f"  Achievements profile: strengths {strengths}; gaps {gaps} (advisory only)")
    print("Workflow lanes")
    lanes = payload.get("lanes", [])
    if isinstance(lanes, list):
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            skills = [str(skill) for skill in lane.get("skills", [])[:5]]
            print(f"  - {lane.get('label')}")
            print(f"    Use for: {lane.get('use_for')}")
            print(f"    Key workflows: {', '.join(skills)}")
    checkpoint = payload.get("generic_tool_checkpoint")
    if isinstance(checkpoint, dict):
        print("Generic tool checkpoint")
        print(f"  {checkpoint.get('body')}")
    print("Response contract")
    contract = payload.get("normal_response_contract")
    if isinstance(contract, dict):
        print(f"  - {contract.get('when_user_asks_capabilities')}")
        print(f"  - {contract.get('when_request_matches_lane')}")
        print(f"  - {contract.get('when_generic_tool_is_available')}")
    print("Boundary")
    print(f"  {payload['claim_boundary']}")
    print("For machine-readable output, rerun with `--json`.")


def cmd_context_budget_plan(args: argparse.Namespace) -> int:
    """Agent-facing publication; never fetch limits or perform compaction."""
    try:
        paths = _paths(args)
        if args.budget_operation == "status":
            payload = context_budget_plan_status(paths, session_ref=args.session_ref)
        else:
            identity = build_route_identity(args.executor_profile, args.provider, args.model)
            raw = Path(args.capacity).read_text(encoding="utf-8") if args.capacity else json.dumps({"schema_version": "route_capacity_input/v1"})
            capacity = parse_route_capacity_input(raw)
            if args.budget_operation == "prepare":
                pack = parse_must_keep(Path(args.must_keep).read_text(encoding="utf-8"))
                payload = prepare_context_budget_plan(paths, session_ref=args.session_ref, identity=identity, capacity=capacity, must_keep=pack)
            else:
                payload = rebind_context_budget_plan(paths, session_ref=args.session_ref, identity=identity, capacity=capacity)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        print(f"Context budget plan unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2
    if _wants_json(args):
        _print_json(payload)
    else:
        record = payload["route_capacity"]
        route = record["route_identity"]
        print(f"Context budget: {route['executor_profile']} / {route['provider'] or 'unknown'} / {route['wire_model']}")
        print(f"Usable tokens: {record['usable_budget_tokens']['value']} ({record['usable_budget_tokens']['class']})")
        for name, evidence in record["capacity"].items():
            print(f"  {name}: {evidence['value']} ({evidence['class']}; {evidence['source']}; clock={evidence['observed_at'] or 'unknown'})")
        print(f"Continuation: {payload['invalidation']['action']} ({payload['invalidation']['reason']})")
        _print_must_keep_delta(payload.get("must_keep_delta"))
        print("Prepared obligation only. Provider usage, compaction and billing: not observed.")
    return 0


def _print_must_keep_delta(delta: object) -> None:
    """Name the class that lost an item; never print a bare digest verdict."""
    if not isinstance(delta, dict):
        return
    if delta["comparison"] != "compared":
        print(f"Must-keep item classes: unavailable ({delta['unavailable_reason']})")
        return
    missing, reduced = delta["missing_classes"], delta["reduced_classes"]
    if not missing and not reduced:
        print("Must-keep item classes: every recorded class still present")
        return
    for name in missing:
        print(f"  MISSING class {name}: recorded before, absent now")
    for row in reduced:
        dropped = ", ".join(row["dropped_refs"]) or "no refs recorded"
        print(f"  REDUCED class {row['item_class']}: {row['previous_count']} -> {row['current_count']} (dropped: {dropped})")


def _add_context_commands(sub) -> None:
    context = sub.add_parser("context", help="Build compact Hermes-facing OMH context for wrappers or plugin hosts.")
    context_sub = context.add_subparsers(dest="context_command", required=True)

    brief = context_sub.add_parser("brief", help="Show the OMH mental model and optional message route hint.")
    brief.add_argument("message", nargs="*", help="Optional current user request to route without echoing raw prompt text.")
    brief.add_argument("--source", default="generic", help="Host or wrapper source label.")
    brief.add_argument("--limit", type=int, default=2, help="Maximum message-specific route hints.")
    brief.add_argument(
        "--prompt-context",
        action="store_true",
        help="Include compact prompt-context text for a Hermes hook or wrapper injection.",
    )
    brief.add_argument("--json", action="store_true", help="Print machine-readable context payload.")
    brief.set_defaults(func=cmd_context_brief)

    budget = context_sub.add_parser("budget-plan", help="Agent/operator route-bound context plan publication and status.")
    operations = budget.add_subparsers(dest="budget_operation", required=True)
    for operation in ("prepare", "rebind", "status"):
        parser = operations.add_parser(operation)
        parser.add_argument("--session-ref", required=True)
        parser.add_argument("--json", action="store_true")
        if operation != "status":
            parser.add_argument("--executor-profile", required=True)
            parser.add_argument("--provider", default="", help="Explicit provider identity; absent stays unknown.")
            parser.add_argument("--model", required=True, help="Exact host wire-model spelling, not a family alias.")
            parser.add_argument("--capacity", help="Local route_capacity_input/v1 JSON; absent limits stay unknown.")
        if operation == "prepare":
            parser.add_argument(
                "--must-keep",
                required=True,
                help=(
                    "JSON digest, estimated_tokens_total, and optional item_classes counts/refs; never pack content. "
                    "Omitting item_classes reports a later comparison as unavailable, not as zero items."
                ),
            )
        parser.set_defaults(func=cmd_context_budget_plan)
