from __future__ import annotations

import argparse

from ..goal_loop import (
    LOOP_ACTIONS,
    LOOP_EXECUTOR_OPTION_IDS,
    LOOP_WORKFLOW_PATTERNS,
    PERMISSION_PROFILES,
    block_loop_queue_item,
    build_loop_queue_handoff,
    build_loop_start_card,
    build_loop_status_card,
    create_loop_cycle,
    inspect_loop_queue_item,
    list_loop_queue,
    list_loop_cycles,
    observe_loop_queue_item,
    read_loop_cycle,
    record_loop_feedback,
    tick_loop_runtime,
    update_loop_permission,
    validate_loop_cycle,
)
from ..installer import OmhError
from .common import _chat_message, _paths, _print_json


def cmd_loop_start_card(args: argparse.Namespace) -> int:
    try:
        _print_json(
            {
                "loop_start_card": build_loop_start_card(
                    _chat_message(args),
                    include_goal=args.include_goal,
                    source=args.source,
                    default_permission_profile=args.permission_profile,
                    default_executor=args.default_executor,
                )
            }
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


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
            workflow_pattern=args.workflow_pattern,
            note=args.note or "",
        )
        _print_json({"loop": cycle, "status_card": build_loop_status_card(_paths(args), args.loop_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_queue_list(args: argparse.Namespace) -> int:
    try:
        _print_json({"loop_queue": list_loop_queue(_paths(args), args.loop_id, include_observed=args.include_observed)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_queue_inspect(args: argparse.Namespace) -> int:
    try:
        _print_json(inspect_loop_queue_item(_paths(args), args.loop_id, args.queue_id))
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_queue_handoff(args: argparse.Namespace) -> int:
    try:
        _print_json({"queue_handoff": build_loop_queue_handoff(_paths(args), args.loop_id, args.queue_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_queue_observe(args: argparse.Namespace) -> int:
    try:
        cycle = observe_loop_queue_item(
            _paths(args),
            args.loop_id,
            args.queue_id,
            evidence_refs=args.evidence_ref or [],
            worktree_evidence_refs=args.worktree_evidence_ref or [],
            subagent_evidence_refs=args.subagent_evidence_ref or [],
            connector_evidence_refs=args.connector_evidence_ref or [],
            summary=args.summary or "",
        )
        _print_json({"loop": cycle, "status_card": build_loop_status_card(_paths(args), args.loop_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_loop_queue_block(args: argparse.Namespace) -> int:
    try:
        cycle = block_loop_queue_item(_paths(args), args.loop_id, args.queue_id, reason=args.reason)
        _print_json({"loop": cycle, "status_card": build_loop_status_card(_paths(args), args.loop_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _add_loop_commands(sub) -> None:
    loop = sub.add_parser("loop", help="Start, inspect, and advance ambitious goal loop control-plane records.")
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

    start_card = loop_sub.add_parser("start-card")
    start_card.add_argument("message", nargs="*", help="Ambitious goal text to shape into a loop start card.")
    start_card.add_argument("--stdin", action="store_true", help="Read the goal text from stdin.")
    start_card.add_argument(
        "--event-json",
        default=None,
        help="Read a Hermes-like JSON event from this path, or '-' for stdin.",
    )
    start_card.add_argument("--include-goal", action="store_true", help="Include the raw goal text in stdout.")
    start_card.add_argument("--source", default="omh")
    start_card.add_argument("--permission-profile", choices=PERMISSION_PROFILES, default="handoff_only")
    start_card.add_argument("--default-executor", choices=LOOP_EXECUTOR_OPTION_IDS, default="choose")
    start_card.set_defaults(func=cmd_loop_start_card)

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
    tick.add_argument("--workflow-pattern", choices=LOOP_WORKFLOW_PATTERNS, default="single_step")
    tick.add_argument("--note", default="")
    tick.set_defaults(func=cmd_loop_tick)

    queue = loop_sub.add_parser("queue")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)

    queue_list = queue_sub.add_parser("list")
    queue_list.add_argument("--loop", dest="loop_id", required=True)
    queue_list.add_argument("--include-observed", action="store_true")
    queue_list.set_defaults(func=cmd_loop_queue_list)

    queue_inspect = queue_sub.add_parser("inspect")
    queue_inspect.add_argument("--loop", dest="loop_id", required=True)
    queue_inspect.add_argument("--queue", dest="queue_id", required=True)
    queue_inspect.set_defaults(func=cmd_loop_queue_inspect)

    queue_handoff = queue_sub.add_parser("handoff")
    queue_handoff.add_argument("--loop", dest="loop_id", required=True)
    queue_handoff.add_argument("--queue", dest="queue_id", required=True)
    queue_handoff.set_defaults(func=cmd_loop_queue_handoff)

    queue_observe = queue_sub.add_parser("observe")
    queue_observe.add_argument("--loop", dest="loop_id", required=True)
    queue_observe.add_argument("--queue", dest="queue_id", required=True)
    queue_observe.add_argument("--evidence-ref", action="append", required=True)
    queue_observe.add_argument("--worktree-evidence-ref", action="append")
    queue_observe.add_argument("--subagent-evidence-ref", action="append")
    queue_observe.add_argument("--connector-evidence-ref", action="append")
    queue_observe.add_argument("--summary", default="")
    queue_observe.set_defaults(func=cmd_loop_queue_observe)

    queue_block = queue_sub.add_parser("block")
    queue_block.add_argument("--loop", dest="loop_id", required=True)
    queue_block.add_argument("--queue", dest="queue_id", required=True)
    queue_block.add_argument("--reason", required=True)
    queue_block.set_defaults(func=cmd_loop_queue_block)
