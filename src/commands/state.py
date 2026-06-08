from __future__ import annotations

import argparse

from ..installer import OmhError
from ..workflow_state import LIFECYCLE_OUTCOMES, WorkflowStateError, clear_workflow_state, finish_workflow_state, list_workflow_states, start_workflow_state
from .common import _paths, _print_json


def cmd_state_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    states, errors = list_workflow_states(paths)
    if args.workflow:
        states = [state for state in states if state.get("workflow") == args.workflow]
        errors = [error for error in errors if f"{args.workflow}-state.json" in error["path"]]
    active = [state for state in states if state.get("active")]
    _print_json(
        {
            "schema_version": 1,
            "state_dir": str(paths.workflow_state_dir),
            "states": states,
            "active": active,
            "errors": errors,
            "ok": not errors,
        }
    )
    return 0 if not errors else 1


def cmd_state_start(args: argparse.Namespace) -> int:
    try:
        state = start_workflow_state(_paths(args), args.workflow, args.note or "")
    except WorkflowStateError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"state": state})
    return 0


def cmd_state_finish(args: argparse.Namespace) -> int:
    try:
        state = finish_workflow_state(_paths(args), args.workflow, args.outcome, args.note or "")
    except WorkflowStateError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"state": state})
    return 0


def cmd_state_clear(args: argparse.Namespace) -> int:
    try:
        removed = clear_workflow_state(_paths(args), args.workflow)
    except WorkflowStateError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"removed": removed, "workflow": args.workflow})
    return 0


def _add_state_commands(sub) -> None:
    state = sub.add_parser("state")
    state_sub = state.add_subparsers(dest="state_command", required=True)

    state_status = state_sub.add_parser("status")
    state_status.add_argument("--workflow", default=None)
    state_status.set_defaults(func=cmd_state_status)

    state_start = state_sub.add_parser("start")
    state_start.add_argument("--workflow", required=True)
    state_start.add_argument("--note", default="")
    state_start.set_defaults(func=cmd_state_start)

    state_finish = state_sub.add_parser("finish")
    state_finish.add_argument("--workflow", required=True)
    state_finish.add_argument("--outcome", choices=LIFECYCLE_OUTCOMES, default="finished")
    state_finish.add_argument("--note", default="")
    state_finish.set_defaults(func=cmd_state_finish)

    state_clear = state_sub.add_parser("clear")
    state_clear.add_argument("--workflow", required=True)
    state_clear.set_defaults(func=cmd_state_clear)
