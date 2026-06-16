from __future__ import annotations

import argparse

from ..installer import OmhError
from ..use_cases import inspect_use_case, list_use_cases, recommend_use_cases, validate_use_cases
from .common import _print_json, _wants_json


def cmd_cases_list(args: argparse.Namespace) -> int:
    payload = list_use_cases()
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_cases_list_summary(payload)
    return 0


def cmd_cases_inspect(args: argparse.Namespace) -> int:
    try:
        payload = inspect_use_case(args.id)
    except KeyError as exc:
        raise OmhError(f"unknown use case: {args.id}") from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_case_summary(payload["use_case"])
    return 0


def cmd_cases_recommend(args: argparse.Namespace) -> int:
    query = " ".join(args.task).strip()
    try:
        payload = recommend_use_cases(query, limit=args.limit)
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_cases_recommend_summary(payload)
    return 0


def cmd_cases_validate(args: argparse.Namespace) -> int:
    payload = validate_use_cases()
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_cases_validate_summary(payload)
    return 0 if payload["ok"] else 1


def _print_cases_list_summary(payload: dict[str, object]) -> None:
    cases = payload.get("use_cases", [])
    if not isinstance(cases, list):
        cases = []
    print("OMH Hermes use cases")
    print("Summary")
    print(f"  Mapped use cases: {len(cases)}")
    for case in cases:
        if not isinstance(case, dict):
            continue
        print(f"  - {case.get('goal')}: {case.get('title')} ({case.get('primary_skill')})")
    print("Boundary")
    print("  These are implemented OMH feature surfaces, not runtime execution evidence.")
    print("Next")
    print("  Inspect one with `omh cases inspect G10`.")
    print("  Recommend one with `omh cases recommend <task>`.")
    print("  For machine-readable output, rerun with `--json`.")


def _print_case_summary(case: dict[str, object]) -> None:
    print(f"OMH use case: {case.get('goal')} - {case.get('title')}")
    print("Situation")
    print(f"  {case.get('hermes_use_case')}")
    print("Current gap")
    print(f"  {case.get('current_gap')}")
    print("Route")
    print(f"  Skill: {case.get('primary_skill')}")
    print(f"  Playbook: {case.get('playbook')}")
    print(f"  Harness: {case.get('harness')}")
    print(f"  Next action: {case.get('next_action')}")
    print("Use it")
    print(f"  Direct skill: {case.get('direct_skill_invocation')}")
    print(f"  Hermes chat: {case.get('hermes_chat_prompt')}")
    print("Feature surface")
    print(f"  {case.get('feature_surface')}")
    print("User value")
    print(f"  {case.get('user_value')}")
    print("Boundary")
    print(f"  {case.get('evidence_boundary')}")
    print("  For machine-readable output, rerun with `--json`.")


def _print_cases_recommend_summary(payload: dict[str, object]) -> None:
    recommendations = payload.get("recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    print("OMH use-case recommendation")
    query = str(payload.get("query", "")).strip()
    if query:
        print(f"Query: {query}")
    for index, case in enumerate(recommendations, start=1):
        if not isinstance(case, dict):
            continue
        print(f"{index}. {case.get('goal')} {case.get('id')} [{case.get('confidence')}]")
        print(f"   Skill: {case.get('primary_skill')} | playbook: {case.get('playbook')}")
        print(f"   Next action: {case.get('next_action')}")
        print(f"   Boundary: {case.get('evidence_boundary')}")
    print("Boundary")
    print("  A use-case recommendation is routing guidance, not accepted work or observed evidence.")
    print("  For machine-readable output, rerun with `--json`.")


def _print_cases_validate_summary(payload: dict[str, object]) -> None:
    validated = payload.get("validated", [])
    if not isinstance(validated, list):
        validated = []
    print("OMH G1-G10 feature surface validation")
    print("Summary")
    print(f"  OK: {payload.get('ok')}")
    print(f"  Validated feature surfaces: {len(validated)}")
    for item in validated:
        if not isinstance(item, dict):
            continue
        marker = "ok" if item.get("ok") else "missing"
        print(
            f"  - {item.get('goal')}: {item.get('primary_skill')} "
            f"/ {item.get('playbook')} / {item.get('harness')} [{marker}]"
        )
    print("Boundary")
    print("  Validation proves catalog registration only, not external runtime execution.")
    print("  For machine-readable output, rerun with `--json`.")


def _add_cases_commands(sub) -> None:
    cases = sub.add_parser("cases", help="List, inspect, or recommend the G1-G10 Hermes use-case catalog.")
    cases_sub = cases.add_subparsers(dest="cases_command", required=True)

    list_cmd = cases_sub.add_parser("list")
    list_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable use-case catalog.")
    list_cmd.set_defaults(func=cmd_cases_list)

    inspect_cmd = cases_sub.add_parser("inspect")
    inspect_cmd.add_argument("id", help="Use-case id such as G10, ops-observability-card, or natural-automation-blueprint.")
    inspect_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable use-case payload.")
    inspect_cmd.set_defaults(func=cmd_cases_inspect)

    recommend_cmd = cases_sub.add_parser("recommend")
    recommend_cmd.add_argument("task", nargs="+", help="Natural-language request to map to a representative OMH use case.")
    recommend_cmd.add_argument("--limit", type=int, default=3, help="Maximum use cases to return.")
    recommend_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable recommendation payload.")
    recommend_cmd.set_defaults(func=cmd_cases_recommend)

    validate_cmd = cases_sub.add_parser("validate")
    validate_cmd.add_argument("--json", action="store_true", help="Print machine-readable validation for all G1-G10 feature surfaces.")
    validate_cmd.set_defaults(func=cmd_cases_validate)
