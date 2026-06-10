from __future__ import annotations

import argparse

from ..goal_ledger import (
    CHECKPOINT_STATUSES,
    build_goal_completion_gate,
    build_goal_continuation,
    build_goal_status_card,
    complete_goal_ledger,
    create_goal_ledger,
    list_goal_ledgers,
    read_goal_ledger,
    record_goal_blocker,
    record_goal_checkpoint,
)
from ..installer import OmhError
from .common import _paths, _print_json


def cmd_goal_create(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        goal = create_goal_ledger(
            paths,
            args.objective,
            args.criterion or [],
            source=args.source,
            goal_id=args.goal_id or None,
            objective_summary=args.summary or None,
            linked_runtime_runs=args.linked_runtime_run or [],
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"goal": goal, "completion_gate": build_goal_completion_gate(paths, goal["goal_id"])})
    return 0


def cmd_goal_checkpoint(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        goal = record_goal_checkpoint(
            paths,
            args.goal_id,
            args.summary,
            criteria_refs=args.criterion or [],
            status=args.status,
            evidence_refs=args.evidence_ref or [],
            notes_summary=args.notes_summary or "",
            linked_runtime_run_id=args.linked_runtime_run or "",
        )
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"goal": goal, "completion_gate": build_goal_completion_gate(paths, args.goal_id)})
    return 0


def cmd_goal_blocker(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        goal = record_goal_blocker(
            paths,
            args.goal_id,
            args.summary,
            attempted_recovery=args.attempted_recovery or "",
            missing_authority=args.missing_authority or "",
            evidence_refs=args.evidence_ref or [],
            mark_goal_blocked=args.mark_goal_blocked,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"goal": goal, "completion_gate": build_goal_completion_gate(paths, args.goal_id)})
    return 0


def cmd_goal_complete(args: argparse.Namespace) -> int:
    try:
        result = complete_goal_ledger(_paths(args), args.goal_id, evidence_refs=args.evidence_ref or [])
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(result)
    return 0 if result["completed"] else 1


def cmd_goal_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    try:
        if args.goal_id:
            _print_json(
                {
                    "goal": read_goal_ledger(paths, args.goal_id),
                    "completion_gate": build_goal_completion_gate(paths, args.goal_id),
                    "status_card": build_goal_status_card(paths, args.goal_id),
                }
            )
            return 0
        goals = list_goal_ledgers(paths)
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "goals": [
                {
                    "goal_id": goal["goal_id"],
                    "status": goal["status"],
                    "objective_summary": goal["objective_summary"],
                    "criteria_total": len(goal["acceptance_criteria"]),
                    "criteria_satisfied": len([item for item in goal["acceptance_criteria"] if item["status"] == "satisfied"]),
                }
                for goal in goals
            ]
        }
    )
    return 0


def cmd_goal_continue(args: argparse.Namespace) -> int:
    try:
        _print_json({"continuation": build_goal_continuation(_paths(args), args.goal_id)})
    except (FileNotFoundError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _add_goal_commands(sub) -> None:
    goal = sub.add_parser("goal", help="Manage durable local goal ledgers and completion gates.")
    goal_sub = goal.add_subparsers(dest="goal_command", required=True)

    goal_create = goal_sub.add_parser("create")
    goal_create.add_argument("--goal-id", default="")
    goal_create.add_argument("--objective", required=True)
    goal_create.add_argument("--summary", default="")
    goal_create.add_argument("--criterion", action="append", required=True)
    goal_create.add_argument("--source", default="omh")
    goal_create.add_argument("--linked-runtime-run", action="append")
    goal_create.set_defaults(func=cmd_goal_create)

    goal_checkpoint = goal_sub.add_parser("checkpoint")
    goal_checkpoint.add_argument("--goal", dest="goal_id", required=True)
    goal_checkpoint.add_argument("--summary", required=True)
    goal_checkpoint.add_argument("--criterion", action="append")
    goal_checkpoint.add_argument("--status", choices=sorted(CHECKPOINT_STATUSES), default="done")
    goal_checkpoint.add_argument("--evidence-ref", action="append")
    goal_checkpoint.add_argument("--notes-summary", default="")
    goal_checkpoint.add_argument("--linked-runtime-run", default="")
    goal_checkpoint.set_defaults(func=cmd_goal_checkpoint)

    goal_blocker = goal_sub.add_parser("blocker")
    goal_blocker.add_argument("--goal", dest="goal_id", required=True)
    goal_blocker.add_argument("--summary", required=True)
    goal_blocker.add_argument("--attempted-recovery", default="")
    goal_blocker.add_argument("--missing-authority", default="")
    goal_blocker.add_argument("--evidence-ref", action="append")
    goal_blocker.add_argument("--mark-goal-blocked", action="store_true")
    goal_blocker.set_defaults(func=cmd_goal_blocker)

    goal_complete = goal_sub.add_parser("complete")
    goal_complete.add_argument("--goal", dest="goal_id", required=True)
    goal_complete.add_argument("--evidence-ref", action="append")
    goal_complete.set_defaults(func=cmd_goal_complete)

    goal_status = goal_sub.add_parser("status")
    goal_status.add_argument("--goal", dest="goal_id", default="")
    goal_status.set_defaults(func=cmd_goal_status)

    goal_continue = goal_sub.add_parser("continue")
    goal_continue.add_argument("--goal", dest="goal_id", required=True)
    goal_continue.set_defaults(func=cmd_goal_continue)
