from __future__ import annotations

import argparse

from ..executors import CODING_EXECUTOR_TARGETS
from ..installer import OmhError
from ..worktree_creator import list_worktree_records, prepare_git_worktree
from ..wrapper.worktree_binding import build_worktree_executor_binding
from .common import _paths, _print_json


def cmd_worktree_prepare(args: argparse.Namespace) -> int:
    try:
        payload = prepare_git_worktree(
            _paths(args),
            repo=args.repo,
            task=args.task or "",
            branch=args.branch or "",
            worktree_path=args.path,
            base_dir=args.base_dir,
            from_ref=args.from_ref,
            dry_run=args.dry_run,
            allow_dirty_source=args.allow_dirty_source,
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"worktree": payload})
    return 1 if payload["status"] == "blocked" else 0


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
    worktree = sub.add_parser("worktree", help="Prepare opt-in Git worktrees for isolated coding handoffs.")
    worktree_sub = worktree.add_subparsers(dest="worktree_command", required=True)

    prepare = worktree_sub.add_parser(
        "prepare",
        help="Create an explicit Git worktree and record local workspace-isolation evidence.",
    )
    prepare.add_argument("--repo", required=True, help="Existing Git repository/worktree to isolate from.")
    prepare.add_argument("--task", default="", help="Short task label used for the default branch name.")
    prepare.add_argument("--branch", default="", help="Branch name for the new worktree. Defaults to omh/<task>-<timestamp>.")
    prepare.add_argument("--path", default=None, help="Absolute or relative destination path for the new worktree.")
    prepare.add_argument("--base-dir", default=".worktrees", help="Default worktree parent when --path is omitted.")
    prepare.add_argument("--from-ref", default="HEAD", help="Starting ref for git worktree add.")
    prepare.add_argument("--dry-run", action="store_true", help="Show the git worktree command without writing files.")
    prepare.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="Allow creating from a source worktree with uncommitted changes; dirty changes are not copied.",
    )
    prepare.set_defaults(func=cmd_worktree_prepare)

    listing = worktree_sub.add_parser("list", help="List recent OMH worktree preparation records.")
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
