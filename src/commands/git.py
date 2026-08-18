from __future__ import annotations

import argparse

from ..coding.git_checkpoint import (
    GitCheckpointError,
    build_git_checkpoint,
    collect_git_maintenance_evidence,
    collect_range_diff_evidence,
    verify_git_checkpoint,
)
from ..installer import OmhError
from .common import _print_json


def _read_checkpoint(path: str) -> dict[str, object]:
    import json
    from pathlib import Path

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("checkpoint JSON must be an object")
    return value


def cmd_git_checkpoint(args: argparse.Namespace) -> int:
    try:
        payload = build_git_checkpoint(args.repo, seed=args.seed, base_sha=args.base_sha, validation=args.validation)
    except (GitCheckpointError, OSError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_git_verify_checkpoint(args: argparse.Namespace) -> int:
    try:
        payload = verify_git_checkpoint(_read_checkpoint(args.file), args.repo)
    except (ValueError, OSError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0 if payload["ok"] else 1


def cmd_git_maintenance(args: argparse.Namespace) -> int:
    _print_json(collect_git_maintenance_evidence(args.repo))
    return 0


def cmd_git_range_diff(args: argparse.Namespace) -> int:
    _print_json(collect_range_diff_evidence(args.repo, args.old_range, args.new_range))
    return 0


def _add_git_commands(sub) -> None:
    git = sub.add_parser("git", help="Capture Git checkpoint, maintenance, and rebase evidence.")
    git_sub = git.add_subparsers(dest="git_command", required=True)

    checkpoint = git_sub.add_parser("checkpoint", help="Capture repository, branch, SHA, worktree, and dirty-state evidence.")
    checkpoint.add_argument("--repo", default=".")
    checkpoint.add_argument("--seed", default="")
    checkpoint.add_argument("--base-sha", default="")
    checkpoint.add_argument("--validation", action="append", default=[])
    checkpoint.set_defaults(func=cmd_git_checkpoint)

    verify = git_sub.add_parser("verify-checkpoint", help="Refuse continuity when recorded Git state has drifted.")
    verify.add_argument("--file", required=True)
    verify.add_argument("--repo", default=".")
    verify.set_defaults(func=cmd_git_verify_checkpoint)

    maintenance = git_sub.add_parser("maintenance", help="Report maintenance configuration and prune candidates.")
    maintenance.add_argument("--repo", default=".")
    maintenance.set_defaults(func=cmd_git_maintenance)

    range_diff = git_sub.add_parser("range-diff", help="Capture rebase patch-preservation evidence.")
    range_diff.add_argument("--repo", default=".")
    range_diff.add_argument("old_range")
    range_diff.add_argument("new_range")
    range_diff.set_defaults(func=cmd_git_range_diff)
