from __future__ import annotations

import argparse

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
