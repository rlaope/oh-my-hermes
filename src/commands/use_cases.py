from __future__ import annotations

import argparse

from ..installer import OmhError
from ..use_cases import (
    build_all_use_case_artifacts,
    build_use_case_artifact,
    demo_all_use_cases,
    demo_use_case,
    inspect_use_case,
    list_use_cases,
    recommend_use_cases,
    validate_use_case_artifact_store,
    validate_use_cases,
    write_all_use_case_artifacts,
    write_use_case_artifact,
)
from .common import _paths, _print_json, _wants_json


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


def cmd_cases_demo(args: argparse.Namespace) -> int:
    try:
        if args.all:
            if args.id:
                raise OmhError("use either `omh cases demo <id>` or `omh cases demo --all`, not both")
            payload = demo_all_use_cases()
        else:
            if not args.id:
                raise OmhError("use-case id required unless --all is passed")
            payload = demo_use_case(args.id)
    except KeyError as exc:
        raise OmhError(f"unknown use case: {args.id}") from exc
    if _wants_json(args):
        _print_json(payload)
    elif args.all:
        _print_cases_demo_collection_summary(payload)
    else:
        _print_case_demo_summary(payload)
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


def cmd_cases_artifact(args: argparse.Namespace) -> int:
    try:
        if args.all:
            if args.id:
                raise OmhError("use either `omh cases artifact <id>` or `omh cases artifact --all`, not both")
            payload = (
                write_all_use_case_artifacts(_paths(args), force=args.force)
                if args.write
                else build_all_use_case_artifacts()
            )
        else:
            if not args.id:
                raise OmhError("use-case id required unless --all is passed")
            artifact = build_use_case_artifact(args.id)
            payload = write_use_case_artifact(_paths(args), artifact, force=args.force) if args.write else artifact
    except KeyError as exc:
        raise OmhError(f"unknown use case: {args.id}") from exc
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_cases_artifact_summary(payload)
    return 0


def cmd_cases_artifact_validate(args: argparse.Namespace) -> int:
    payload = validate_use_case_artifact_store(_paths(args))
    if _wants_json(args):
        _print_json(payload)
    else:
        _print_cases_artifact_validate_summary(payload)
    return 0 if payload["ok"] else 1


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
        print(
            f"  - {case.get('goal')}: {case.get('title')} "
            f"({case.get('primary_skill')} | {case.get('exposure')})"
        )
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
    print(f"  Surface: {case.get('primary_skill')}")
    print(f"  Exposure: {case.get('exposure')}")
    print(f"  Install visibility: {case.get('install_visibility')}")
    print(f"  Preferred usage: {case.get('preferred_usage')}")
    print(f"  Compatibility alias: {case.get('compatibility_alias')}")
    print(f"  Playbook: {case.get('playbook')}")
    print(f"  Harness: {case.get('harness')}")
    print(f"  Next action: {case.get('next_action')}")
    print("Use it")
    print(f"  Hermes chat: {case.get('hermes_chat_prompt')}")
    print(f"  Compatibility alias: {case.get('direct_skill_invocation')}")
    print("Feature surface")
    print(f"  {case.get('feature_surface')}")
    print("User value")
    print(f"  {case.get('user_value')}")
    print("Boundary")
    print(f"  {case.get('evidence_boundary')}")
    print("  For machine-readable output, rerun with `--json`.")


def _print_case_demo_summary(card: dict[str, object]) -> None:
    route = card.get("route", {})
    chat_surface = card.get("chat_surface", {})
    evidence = card.get("evidence", {})
    actions = card.get("actions", [])
    if not isinstance(route, dict):
        route = {}
    if not isinstance(chat_surface, dict):
        chat_surface = {}
    if not isinstance(evidence, dict):
        evidence = {}
    if not isinstance(actions, list):
        actions = []
    print(f"OMH use-case demo card: {card.get('goal')} - {card.get('title')}")
    print("Route")
    print(
        f"  {route.get('primary_skill')} -> {route.get('next_action')} "
        f"({route.get('exposure')}; playbook {route.get('playbook')}; harness {route.get('harness')})"
    )
    print("Hermes card")
    print(f"  {chat_surface.get('headline')}")
    for line in chat_surface.get("body_lines", []):
        print(f"  - {line}")
    print(f"  Status: {chat_surface.get('status_line')}")
    print("Actions")
    for action in actions[:4]:
        if not isinstance(action, dict):
            continue
        print(f"  - {action.get('label')}: {action.get('value')}")
    print("Boundary")
    print(f"  {evidence.get('claim_boundary')}")
    print("  For machine-readable output, rerun with `--json`.")


def _print_cases_demo_collection_summary(payload: dict[str, object]) -> None:
    cards = payload.get("cards", [])
    if not isinstance(cards, list):
        cards = []
    print("OMH G1-G10 use-case demo cards")
    print("Summary")
    print(f"  Demo cards: {len(cards)}")
    for card in cards:
        if not isinstance(card, dict):
            continue
        route = card.get("route", {})
        if not isinstance(route, dict):
            route = {}
        print(f"  - {card.get('goal')}: {card.get('title')} ({route.get('primary_skill')} -> {route.get('next_action')})")
    print("Boundary")
    print(f"  {payload.get('boundary')}")
    print("Next")
    print("  Inspect one with `omh cases demo G10`.")
    print("  Export all cards with `omh cases demo --all --json`.")
    print("  For machine-readable output, rerun with `--json`.")


def _print_cases_artifact_summary(payload: dict[str, object]) -> None:
    schema = payload.get("schema_version")
    if schema == "omh_use_case_artifact_write/v1":
        mode = str(payload.get("mode", ""))
        print("OMH use-case artifact write")
        print("Summary")
        if mode == "write_all":
            artifacts = payload.get("artifacts", [])
            if not isinstance(artifacts, list):
                artifacts = []
            print(f"  Written artifacts: {len(artifacts)}")
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                marker = "replaced" if artifact.get("replaced") else "written"
                print(f"  - {artifact.get('goal')}: {artifact.get('title')} [{marker}]")
            print(f"  Index: {payload.get('index_path')}")
        else:
            artifact = payload.get("artifact", {})
            if not isinstance(artifact, dict):
                artifact = {}
            marker = "replaced" if payload.get("replaced") else "written"
            print(f"  Artifact: {artifact.get('goal')} - {artifact.get('title')} [{marker}]")
            print(f"  Path: {payload.get('artifact_path')}")
            print(f"  Index: {payload.get('index_path')}")
        print("Boundary")
        print(f"  {payload.get('boundary')}")
        print("  For machine-readable output, rerun with `--json`.")
        return
    if schema == "omh_use_case_artifact_collection/v1":
        artifacts = payload.get("artifacts", [])
        if not isinstance(artifacts, list):
            artifacts = []
        print("OMH G1-G10 use-case artifacts")
        print("Summary")
        print(f"  Prepared artifacts: {len(artifacts)}")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            route = artifact.get("route", {})
            if not isinstance(route, dict):
                route = {}
            print(f"  - {artifact.get('goal')}: {artifact.get('title')} ({route.get('primary_skill')} -> {route.get('next_action')})")
        print("Boundary")
        print(f"  {payload.get('boundary')}")
        print("Next")
        print("  Write them with `omh cases artifact --all --write`.")
        print("  For machine-readable output, rerun with `--json`.")
        return
    route = payload.get("route", {})
    evidence = payload.get("evidence", {})
    if not isinstance(route, dict):
        route = {}
    if not isinstance(evidence, dict):
        evidence = {}
    print(f"OMH use-case artifact: {payload.get('goal')} - {payload.get('title')}")
    print("Route")
    print(f"  {route.get('primary_skill')} -> {route.get('next_action')}")
    print("Artifact")
    print(f"  ID: {payload.get('artifact_id')}")
    print(f"  Status: {payload.get('observation_status')}")
    print("Boundary")
    print(f"  {evidence.get('claim_boundary')}")
    print("Next")
    print(f"  Write it with `omh cases artifact {payload.get('goal')} --write`.")
    print("  For machine-readable output, rerun with `--json`.")


def _print_cases_artifact_validate_summary(payload: dict[str, object]) -> None:
    print("OMH use-case artifact validation")
    print("Summary")
    print(f"  OK: {payload.get('ok')}")
    print(f"  Artifacts: {payload.get('artifact_count')}/{payload.get('expected_count')}")
    missing = payload.get("missing_goals", [])
    errors = payload.get("errors", [])
    if missing:
        print("  Missing goals: " + ", ".join(str(item) for item in missing))
    if errors:
        print("Errors")
        for error in (errors[:12] if isinstance(errors, list) else []):
            print(f"  - {error}")
        if isinstance(errors, list) and len(errors) > 12:
            print(f"  ... {len(errors) - 12} more")
    print("Boundary")
    print(f"  {payload.get('boundary')}")
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
        print(
            f"   Surface: {case.get('primary_skill')} | exposure: {case.get('exposure')} "
            f"| playbook: {case.get('playbook')}"
        )
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
            f"({item.get('exposure')}) / {item.get('playbook')} / {item.get('harness')} [{marker}]"
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

    demo_cmd = cases_sub.add_parser("demo")
    demo_cmd.add_argument("id", nargs="?", default="", help="Use-case id such as G10 or ops-observability-card.")
    demo_cmd.add_argument("--all", action="store_true", help="Print demo cards for all G1-G10 use cases.")
    demo_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable demo card payload.")
    demo_cmd.set_defaults(func=cmd_cases_demo)

    recommend_cmd = cases_sub.add_parser("recommend")
    recommend_cmd.add_argument("task", nargs="+", help="Natural-language request to map to a representative OMH use case.")
    recommend_cmd.add_argument("--limit", type=int, default=3, help="Maximum use cases to return.")
    recommend_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable recommendation payload.")
    recommend_cmd.set_defaults(func=cmd_cases_recommend)

    artifact_cmd = cases_sub.add_parser("artifact")
    artifact_cmd.add_argument("id", nargs="?", default="", help="Use-case id such as G10 or ops-observability-card.")
    artifact_cmd.add_argument("--all", action="store_true", help="Build artifacts for all G1-G10 use cases.")
    artifact_cmd.add_argument("--write", action="store_true", help="Write prepared use-case artifacts under the OMH home.")
    artifact_cmd.add_argument("--force", action="store_true", help="Replace an existing managed use-case artifact.")
    artifact_cmd.add_argument("--json", action="store_true", help="Print the full machine-readable artifact payload.")
    artifact_cmd.set_defaults(func=cmd_cases_artifact)

    artifact_validate_cmd = cases_sub.add_parser("artifact-validate")
    artifact_validate_cmd.add_argument("--json", action="store_true", help="Print machine-readable validation for local use-case artifacts.")
    artifact_validate_cmd.set_defaults(func=cmd_cases_artifact_validate)

    validate_cmd = cases_sub.add_parser("validate")
    validate_cmd.add_argument("--json", action="store_true", help="Print machine-readable validation for all G1-G10 feature surfaces.")
    validate_cmd.set_defaults(func=cmd_cases_validate)
