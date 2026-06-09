from __future__ import annotations

import argparse

from ..goal_loop import (
    LOOP_ACTIONS,
    PERMISSION_PROFILES,
    build_loop_status_card,
    create_loop_cycle,
    list_loop_cycles,
    read_loop_cycle,
    record_loop_feedback,
    tick_loop_runtime,
    update_loop_permission,
    validate_loop_cycle,
)
from ..installer import OmhError
from .common import _paths, _print_json


def cmd_loop_start(args: argparse.Namespace) -> int:
    try:
        cycle = create_loop_cycle(
            _paths(args),
            goal_summary=args.goal_summary,
            goal_reframe=args.goal_reframe,
            success_criteria=args.criterion or [],
            permission_profile=args.permission_profile,
            allowed_executors=args.allowed_executor or [],
            allow_actions=args.allow_action or [],
            forbid_actions=args.forbid_action or [],
            linked_goal_id=args.linked_goal or "",
            source=args.source,
            loop_id=args.loop_id or None,
        )
        _print_json({"loop": cycle, "status_card": build_loop_status_card(_paths(args), str(cycle["loop_id"]))})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_status(args: argparse.Namespace) -> int:
    try:
        if args.loop_id:
            _print_json(
                {
                    "loop": read_loop_cycle(_paths(args), args.loop_id),
                    "status_card": build_loop_status_card(_paths(args), args.loop_id),
                }
            )
            return 0
        loops = list_loop_cycles(_paths(args))
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    valid_loops = []
    invalid_loops = []
    for loop in loops:
        validation = validate_loop_cycle(loop)
        if not validation["ok"]:
            invalid_loops.append(
                {
                    "loop_id": str(loop.get("loop_id", "unknown")),
                    "errors": validation["errors"],
                }
            )
            continue
        valid_loops.append(
            {
                "loop_id": loop["loop_id"],
                "phase": loop["phase"],
                "wait_reason": loop["wait_reason"],
                "permission_profile": loop["authority_envelope"]["permission_profile"],
                "linked_goal_id": loop.get("linked_goal_id", ""),
                "next_action": loop["next_action"],
                "heartbeat_count": loop.get("runtime", {}).get("heartbeat_count", 0)
                if isinstance(loop.get("runtime"), dict)
                else 0,
                "last_planned_action": loop.get("runtime", {}).get("last_planned_action", "")
                if isinstance(loop.get("runtime"), dict)
                else "",
            }
        )
    _print_json({"loops": valid_loops, "invalid_loops": invalid_loops})
    return 0


def cmd_loop_feedback(args: argparse.Namespace) -> int:
    try:
        cycle = record_loop_feedback(
            _paths(args),
            args.loop_id,
            observed_artifacts=args.observed_artifact or [],
            internal_gap=args.internal_gap or "",
            external_wait=args.external_wait or "",
            context_exhausted=args.context_exhausted,
            budget_exhausted=args.budget_exhausted,
        )
        _print_json({"loop": cycle, "status_card": build_loop_status_card(_paths(args), args.loop_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_permit(args: argparse.Namespace) -> int:
    try:
        cycle = update_loop_permission(
            _paths(args),
            args.loop_id,
            allow_actions=args.allow_action or [],
            forbid_actions=args.forbid_action or [],
            allowed_executors=args.allowed_executor or [],
        )
        _print_json({"loop": cycle, "status_card": build_loop_status_card(_paths(args), args.loop_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_tick(args: argparse.Namespace) -> int:
    try:
        cycle = tick_loop_runtime(
            _paths(args),
            args.loop_id,
            trigger=args.trigger,
            cadence=args.cadence or "",
            worktree_base=args.worktree_base or "",
            worktree_branch=args.worktree_branch or "",
            subagent_role=args.subagent_role or "",
            connector=args.connector or "",
            connector_action=args.connector_action or "",
            note=args.note or "",
        )
        _print_json({"loop": cycle, "status_card": build_loop_status_card(_paths(args), args.loop_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _add_loop_commands(sub) -> None:
    loop = sub.add_parser("loop")
    loop_sub = loop.add_subparsers(dest="loop_command", required=True)

    start = loop_sub.add_parser("start")
    start.add_argument("--loop-id", default="")
    start.add_argument("--goal-summary", required=True)
    start.add_argument("--goal-reframe", required=True)
    start.add_argument("--criterion", action="append", required=True)
    start.add_argument("--permission-profile", choices=PERMISSION_PROFILES, default="handoff_only")
    start.add_argument("--allowed-executor", action="append")
    start.add_argument("--allow-action", choices=LOOP_ACTIONS, action="append")
    start.add_argument("--forbid-action", choices=LOOP_ACTIONS, action="append")
    start.add_argument("--linked-goal", default="")
    start.add_argument("--source", default="omh")
    start.set_defaults(func=cmd_loop_start)

    status = loop_sub.add_parser("status")
    status.add_argument("--loop", dest="loop_id", default="")
    status.set_defaults(func=cmd_loop_status)

    feedback = loop_sub.add_parser("feedback")
    feedback.add_argument("--loop", dest="loop_id", required=True)
    feedback.add_argument("--observed-artifact", action="append")
    feedback.add_argument("--internal-gap", default="")
    feedback.add_argument("--external-wait", default="")
    feedback.add_argument("--context-exhausted", action="store_true")
    feedback.add_argument("--budget-exhausted", action="store_true")
    feedback.set_defaults(func=cmd_loop_feedback)

    permit = loop_sub.add_parser("permit")
    permit.add_argument("--loop", dest="loop_id", required=True)
    permit.add_argument("--allow-action", choices=LOOP_ACTIONS, action="append")
    permit.add_argument("--forbid-action", choices=LOOP_ACTIONS, action="append")
    permit.add_argument("--allowed-executor", action="append")
    permit.set_defaults(func=cmd_loop_permit)

    tick = loop_sub.add_parser("tick")
    tick.add_argument("--loop", dest="loop_id", required=True)
    tick.add_argument("--trigger", choices=("manual", "scheduled", "wrapper", "automation"), default="manual")
    tick.add_argument("--cadence", default="")
    tick.add_argument("--worktree-base", default="")
    tick.add_argument("--worktree-branch", default="")
    tick.add_argument("--subagent-role", default="")
    tick.add_argument("--connector", default="")
    tick.add_argument("--connector-action", default="")
    tick.add_argument("--note", default="")
    tick.set_defaults(func=cmd_loop_tick)
