from __future__ import annotations

import argparse

from ..installer import OmhError
from ..playbooks import inspect_playbook, list_playbooks, recommend_playbooks
from .common import _print_json


def cmd_playbook_list(args: argparse.Namespace) -> int:
    _print_json(list_playbooks())
    return 0


def cmd_playbook_inspect(args: argparse.Namespace) -> int:
    try:
        _print_json(inspect_playbook(args.id))
    except KeyError as exc:
        raise OmhError(f"unknown playbook: {args.id}") from exc
    return 0


def cmd_playbook_recommend(args: argparse.Namespace) -> int:
    query = " ".join(args.task).strip()
    try:
        _print_json(recommend_playbooks(query, limit=args.limit))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _add_playbook_commands(sub) -> None:
    playbook = sub.add_parser("playbook", help="Recommend or inspect complete Hermes workflow playbooks.")
    playbook_sub = playbook.add_subparsers(dest="playbook_command", required=True)

    playbook_list = playbook_sub.add_parser("list")
    playbook_list.set_defaults(func=cmd_playbook_list)

    playbook_inspect = playbook_sub.add_parser("inspect")
    playbook_inspect.add_argument("id")
    playbook_inspect.set_defaults(func=cmd_playbook_inspect)

    playbook_recommend = playbook_sub.add_parser("recommend")
    playbook_recommend.add_argument("task", nargs="+", help="Natural-language request to map to an OMH playbook.")
    playbook_recommend.add_argument("--limit", type=int, default=3, help="Maximum playbooks to return.")
    playbook_recommend.set_defaults(func=cmd_playbook_recommend)
