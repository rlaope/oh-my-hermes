from __future__ import annotations

import argparse

from ..executors import CODING_EXECUTOR_TARGETS
from ..installer import OmhError
from ..worktree_creator import list_worktree_records
from ..wrapper.worktree_binding import build_worktree_executor_binding
from .common import _paths, _print_json


def cmd_worktree_list(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise OmhError("--limit must be at least 1")
    records, errors = list_worktree_records(_paths(args), limit=args.limit)
    _print_json(
        {
            "schema_version": "omh_worktree_observations/v1",
            "records": records,
            "errors": errors,
            "claim_boundary": (
                "OMH worktree records are workspace-isolation evidence only. They do not prove executor "
                "dispatch, implementation, verification, review, CI, merge-readiness, or merge."
            ),
        }
    )
    return 0


def cmd_worktree_bind(args: argparse.Namespace) -> int:
    try:
        payload = build_worktree_executor_binding(
            _paths(args),
            worktree_path=args.path,
            executor=args.executor,
            session_id=args.session_id or "",
            run_id=args.run_id or "",
            runtime_profile=args.runtime_profile or "",
            prompt_ref=args.prompt_ref or "",
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"binding": payload})
    return 1 if payload["status"] == "blocked_missing_worktree" else 0


def _add_worktree_commands(sub) -> None:
    worktree = sub.add_parser(
        "worktree",
        help="Observe worktree isolation evidence and bind coding handoffs (creation is deferred to native Hermes/Git tooling).",
    )
    worktree_sub = worktree.add_subparsers(dest="worktree_command", required=True)

    listing = worktree_sub.add_parser("list", help="List recent observed OMH worktree records.")
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(func=cmd_worktree_list)

    bind = worktree_sub.add_parser(
        "bind",
        help="Build wrapper launch and observation recipes for an isolated coding-agent worktree.",
    )
    bind.add_argument("--path", required=True, help="Existing or intended Git worktree path.")
    bind.add_argument(
        "--executor",
        choices=tuple(target for target in CODING_EXECUTOR_TARGETS if target != "choose"),
        required=True,
        help="Coding agent or runtime profile that should open in this worktree.",
    )
    bind_target = bind.add_mutually_exclusive_group()
    bind_target.add_argument("--session", dest="session_id", default="", help="Wrapper executor-session id to bind.")
    bind_target.add_argument("--run", dest="run_id", default="", help="Runtime run id to bind.")
    bind.add_argument("--runtime-profile", default="", help="Override the runtime profile for runtime observation recipes.")
    bind.add_argument("--prompt-ref", default="", help="Opaque prompt/handoff reference held by the wrapper.")
    bind.set_defaults(func=cmd_worktree_bind)
