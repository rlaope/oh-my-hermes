from __future__ import annotations

import argparse

from ..installer import OmhError
from ..playbooks import inspect_playbook, list_playbooks, recommend_playbooks
from .common import _print_json, _wants_json


def cmd_playbook_list(args: argparse.Namespace) -> int:
    payload = list_playbooks()
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_playbook_list_summary(payload)
    return 0


def cmd_playbook_inspect(args: argparse.Namespace) -> int:
    try:
        payload = inspect_playbook(args.id)
    except KeyError as exc:
        raise OmhError(f"unknown playbook: {args.id}") from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_playbook_inspect_summary(payload)
    return 0


def cmd_playbook_recommend(args: argparse.Namespace) -> int:
    query = " ".join(args.task).strip()
    try:
        payload = recommend_playbooks(query, limit=args.limit)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_playbook_recommend_summary(payload)
    return 0


def _print_playbook_list_summary(payload: dict[str, object]) -> None:
    playbooks = payload.get("playbooks", [])
    if not isinstance(playbooks, list):
        playbooks = []
    print("OMH playbooks")
    print("Summary")
    print(f"  Available playbooks: {len(playbooks)}")
    for playbook in playbooks:
        if not isinstance(playbook, dict):
            continue
        playbook_id = str(playbook.get("id", "unknown"))
        title = str(playbook.get("title", playbook_id))
        summary = _short_summary(str(playbook.get("summary", "")), limit=110)
        print(f"  - {playbook_id}: {title}")
        if summary:
            print(f"    {summary}")
    print("Next")
    print("  Inspect a playbook with `omh playbook inspect <id>`.")
    print("  Recommend one with `omh playbook recommend <task>`.")
    print("  For machine-readable output, rerun with `--json`.")


def _print_playbook_inspect_summary(payload: dict[str, object]) -> None:
    playbook = payload.get("playbook", {})
    if not isinstance(playbook, dict):
        playbook = {}
    stages = playbook.get("stages", [])
    if not isinstance(stages, list):
        stages = []
    playbook_id = str(playbook.get("id", "unknown"))
    print(f"OMH playbook: {playbook.get('title', playbook_id)}")
    print("Summary")
    print(f"  ID: {playbook_id}")
    summary = str(playbook.get("summary", "")).strip()
    use_when = str(playbook.get("use_when", "")).strip()
    if summary:
        print(f"  Summary: {summary}")
    if use_when:
        print(f"  Use when: {use_when}")
    pipeline = playbook.get("pipeline", [])
    if isinstance(pipeline, list) and pipeline:
        print("  Pipeline: " + " -> ".join(str(step) for step in pipeline))
    print(f"  Stages: {len(stages)}")
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("id", "unknown"))
        owner = str(stage.get("owner", "unknown"))
        boundary = _short_summary(str(stage.get("evidence_boundary", "")), limit=110)
        print(f"  - {stage_id}: owner={owner}")
        if boundary:
            print(f"    Boundary: {boundary}")
    print("Boundary")
    print("  A playbook is routing and status guidance, not executor result evidence.")
    print("  For machine-readable output, rerun with `--json`.")


def _print_playbook_recommend_summary(payload: dict[str, object]) -> None:
    recommendations = payload.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    print("OMH playbook recommendation")
    query = str(payload.get("query", "")).strip()
    if query:
        print(f"Query: {query}")
    if not recommendations:
        print("No playbook recommendations.")
        print("  For machine-readable output, rerun with `--json`.")
        return
    for index, recommendation in enumerate(recommendations, start=1):
        if not isinstance(recommendation, dict):
            continue
        playbook_id = str(recommendation.get("id", "unknown"))
        confidence = str(recommendation.get("confidence", "unknown"))
        title = str(recommendation.get("title", playbook_id))
        print(f"{index}. {playbook_id} [{confidence}]")
        print(f"   {title}")
        next_action = str(recommendation.get("next_action", "")).strip()
        if next_action:
            print(f"   Next action: {next_action}")
        boundary = _short_summary(str(recommendation.get("evidence_boundary", "")), limit=120)
        if boundary:
            print(f"   Boundary: {boundary}")
    print("Boundary")
    print("  A recommendation is routing guidance, not accepted plan or execution evidence.")
    print("  For machine-readable output, rerun with `--json`.")


def _short_summary(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _add_playbook_commands(sub) -> None:
    playbook = sub.add_parser("playbook", help="Recommend or inspect complete Hermes workflow playbooks.")
    playbook_sub = playbook.add_subparsers(dest="playbook_command", required=True)

    playbook_list = playbook_sub.add_parser("list")
    playbook_list.add_argument("--json", action="store_true", help="Print the full machine-readable playbook catalog.")
    playbook_list.set_defaults(func=cmd_playbook_list)

    playbook_inspect = playbook_sub.add_parser("inspect")
    playbook_inspect.add_argument("id")
    playbook_inspect.add_argument("--json", action="store_true", help="Print the full machine-readable playbook payload.")
    playbook_inspect.set_defaults(func=cmd_playbook_inspect)

    playbook_recommend = playbook_sub.add_parser("recommend")
    playbook_recommend.add_argument("task", nargs="+", help="Natural-language request to map to an OMH playbook.")
    playbook_recommend.add_argument("--limit", type=int, default=3, help="Maximum playbooks to return.")
    playbook_recommend.add_argument("--json", action="store_true", help="Print the full machine-readable recommendation payload.")
    playbook_recommend.set_defaults(func=cmd_playbook_recommend)
