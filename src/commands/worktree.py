from __future__ import annotations

import argparse

from ..installer import OmhError
from ..worktree_creator import list_worktree_records, prepare_git_worktree
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
