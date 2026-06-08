from __future__ import annotations

import argparse

from ..installer import OmhError
from ..runtime.artifacts import (
    CI_STATUSES,
    DELEGATION_RESULTS,
    MERGE_STATUSES,
    PRIVACY_MODES,
    REVIEW_STATUSES,
    RUN_STATUSES,
    create_run,
    export_runtime,
    list_runs,
    read_state_result,
    show_run,
    summarize_delegated_coding_status,
    validate_runtime,
    write_ci_record,
    write_delegation,
    write_merge_record,
    write_review_record,
    write_wrapper_contract,
)
from ..skill_pack import builtin_definitions, builtin_harnesses
from .common import _paths, _print_json


def _valid_skill_names() -> set[str]:
    return {definition.name for definition in builtin_definitions()}


def _valid_harness_names() -> set[str]:
    return {harness.name for harness in builtin_harnesses()}


def _validate_runtime_names(skill: str, harness: str) -> None:
    if skill not in _valid_skill_names():
        raise OmhError(f"unknown skill for runtime record: {skill}")
    if harness not in _valid_harness_names():
        raise OmhError(f"unknown harness for runtime record: {harness}")


def cmd_runtime_status(args: argparse.Namespace) -> int:
    paths = _paths(args)
    state, state_error = read_state_result(paths)
    _print_json(
        {
            "schema_version": 1,
            "runtime_dir": str(paths.runtime_dir),
            "state_path": str(paths.runtime_state_path),
            "runs_dir": str(paths.runtime_runs_dir),
            "wrapper_sessions_dir": str(paths.runtime_wrapper_sessions_dir),
            "state": state,
            "state_error": state_error,
        }
    )
    return 0


def cmd_runtime_runs(args: argparse.Namespace) -> int:
    _print_json({"runs": list_runs(_paths(args))})
    return 0


def cmd_runtime_show(args: argparse.Namespace) -> int:
    try:
        _print_json(show_run(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    return 0


def cmd_runtime_delegation_status(args: argparse.Namespace) -> int:
    try:
        _print_json(summarize_delegated_coding_status(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    return 0


def cmd_runtime_record(args: argparse.Namespace) -> int:
    _validate_runtime_names(args.skill, args.harness)
    run = create_run(
        _paths(args),
        {
            "skill": args.skill,
            "harness": args.harness,
            "status": args.status,
            "trigger": args.trigger or "",
            "privacy": args.privacy,
            "inputs_summary": args.inputs_summary or "",
            "outputs_summary": args.outputs_summary or "",
            "verification_summary": args.verification_summary or "",
        },
    )
    _print_json({"run": run})
    return 0


def cmd_runtime_delegate(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    observed = args.observed
    result = args.result
    if args.not_observed:
        observed = False
        result = result or "not_observed"
    elif observed:
        result = result or "completed"
    else:
        result = result or "not_available"
    participants = [item.strip() for item in (args.participants or "").split(",") if item.strip()]
    try:
        delegation = write_delegation(
            run_dir,
            {
                "requested": args.requested,
                "observed": observed,
                "participants": participants,
                "result": result,
                "evidence_refs": args.evidence_ref or [],
                "message": args.message or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"delegation": delegation})
    return 0


def cmd_runtime_wrapper(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    try:
        wrapper = write_wrapper_contract(
            run_dir,
            {
                "prompt_dispatched": args.prompt_dispatched,
                "hermes_response_observed": args.response_observed,
                "verification_observed": args.verification_observed,
                "completion_status": args.completion_status,
                "unobserved_gaps": args.gap or [],
                "message": args.message or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"wrapper": wrapper})
    return 0


def cmd_runtime_review(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    preflight = summarize_delegated_coding_status(paths, args.run_id)
    if args.status in {"passed", "not_required"} and preflight.get("next_action") != "record_review_evidence":
        raise OmhError(f"cannot record review {args.status} while next_action is {preflight.get('next_action')}")
    review_status = preflight.get("review", {})
    if args.status == "not_required" and isinstance(review_status, dict) and review_status.get("required"):
        raise OmhError("cannot mark required review as not_required")
    try:
        review = write_review_record(
            run_dir,
            {
                "status": args.status,
                "required": args.status != "not_required",
                "reviewer": args.reviewer or "",
                "evidence_refs": args.evidence_ref or [],
                "summary": args.summary or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"review": review, "status": summarize_delegated_coding_status(paths, args.run_id)})
    return 0


def cmd_runtime_ci(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    preflight = summarize_delegated_coding_status(paths, args.run_id)
    if args.status == "passed" and preflight.get("next_action") != "record_ci_evidence":
        raise OmhError(f"cannot record passed CI while next_action is {preflight.get('next_action')}")
    ci_status = preflight.get("ci", {})
    if args.status == "not_required" and isinstance(ci_status, dict) and ci_status.get("required"):
        raise OmhError("cannot mark required CI as not_required")
    try:
        ci = write_ci_record(
            run_dir,
            {
                "status": args.status,
                "required": args.status != "not_required",
                "provider": args.provider or "",
                "checks": args.check or [],
                "evidence_refs": args.evidence_ref or [],
                "summary": args.summary or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"ci": ci, "status": summarize_delegated_coding_status(paths, args.run_id)})
    return 0


def cmd_runtime_merge(args: argparse.Namespace) -> int:
    paths = _paths(args)
    run_dir = paths.runtime_runs_dir / args.run_id
    if not (run_dir / "run.json").exists():
        raise OmhError(f"runtime run not found: {args.run_id}")
    selected_statuses = [
        status
        for status, selected in (
            ("ready", args.ready),
            ("merged", args.merged),
            ("blocked", args.blocked),
            (args.status, bool(args.status)),
        )
        if selected
    ]
    if len(selected_statuses) > 1:
        raise OmhError("runtime merge accepts only one of --ready, --merged, --blocked, or --status")
    status = selected_statuses[0] if selected_statuses else None
    if not status:
        raise OmhError("runtime merge requires --ready, --merged, --blocked, or --status")
    preflight = summarize_delegated_coding_status(paths, args.run_id)
    allowed_preflight = {
        "ready": {"record_merge_readiness", "report_merge_ready"},
        "merged": {"report_merge_ready"},
        "blocked": {"record_merge_readiness", "report_merge_ready"},
        "not_ready": {"record_merge_readiness", "report_merge_ready", "report_completion_with_evidence"},
        "not_observed": {"record_merge_readiness", "report_merge_ready", "report_completion_with_evidence"},
    }
    if status in allowed_preflight and preflight.get("next_action") not in allowed_preflight[status]:
        raise OmhError(f"cannot record merge {status} while next_action is {preflight.get('next_action')}")
    try:
        merge = write_merge_record(
            run_dir,
            {
                "status": status,
                "target_branch": args.target_branch or "",
                "merge_commit": args.merge_commit or "",
                "evidence_refs": args.evidence_ref or [],
                "summary": args.summary or "",
            },
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"merge": merge, "status": summarize_delegated_coding_status(paths, args.run_id)})
    return 0


def cmd_runtime_validate(args: argparse.Namespace) -> int:
    result = validate_runtime(_paths(args), args.run_id)
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_runtime_export(args: argparse.Namespace) -> int:
    _print_json(export_runtime(_paths(args), redacted=args.redacted))
    return 0


def _add_runtime_commands(sub) -> None:
    runtime = sub.add_parser("runtime")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)

    runtime_status = runtime_sub.add_parser("status")
    runtime_status.set_defaults(func=cmd_runtime_status)

    runtime_runs = runtime_sub.add_parser("runs")
    runtime_runs.set_defaults(func=cmd_runtime_runs)

    runtime_show = runtime_sub.add_parser("show")
    runtime_show.add_argument("run_id")
    runtime_show.set_defaults(func=cmd_runtime_show)

    runtime_delegation_status = runtime_sub.add_parser("delegation-status")
    runtime_delegation_status.add_argument("--run", dest="run_id", required=True)
    runtime_delegation_status.set_defaults(func=cmd_runtime_delegation_status)

    runtime_record = runtime_sub.add_parser("record")
    runtime_record.add_argument("--skill", required=True)
    runtime_record.add_argument("--harness", required=True)
    runtime_record.add_argument("--status", choices=RUN_STATUSES, default="unknown")
    runtime_record.add_argument("--trigger", default="")
    runtime_record.add_argument("--privacy", choices=PRIVACY_MODES, default="metadata_only")
    runtime_record.add_argument("--inputs-summary", default="")
    runtime_record.add_argument("--outputs-summary", default="")
    runtime_record.add_argument("--verification-summary", default="")
    runtime_record.set_defaults(func=cmd_runtime_record)

    runtime_delegate = runtime_sub.add_parser("delegate")
    runtime_delegate.add_argument("--run", dest="run_id", required=True)
    runtime_delegate.add_argument("--requested", action="store_true")
    observation = runtime_delegate.add_mutually_exclusive_group()
    observation.add_argument("--observed", action="store_true")
    observation.add_argument("--not-observed", action="store_true")
    runtime_delegate.add_argument("--result", choices=DELEGATION_RESULTS, default=None)
    runtime_delegate.add_argument("--participants", default="")
    runtime_delegate.add_argument("--evidence-ref", action="append")
    runtime_delegate.add_argument("--message", default="")
    runtime_delegate.set_defaults(func=cmd_runtime_delegate)

    runtime_wrapper = runtime_sub.add_parser("wrapper")
    runtime_wrapper.add_argument("--run", dest="run_id", required=True)
    runtime_wrapper.add_argument("--prompt-dispatched", action="store_true")
    runtime_wrapper.add_argument("--response-observed", action="store_true")
    runtime_wrapper.add_argument("--verification-observed", action="store_true")
    runtime_wrapper.add_argument("--completion-status", choices=("started", "completed", "blocked", "failed", "unknown"), default="unknown")
    runtime_wrapper.add_argument("--gap", action="append")
    runtime_wrapper.add_argument("--message", default="")
    runtime_wrapper.set_defaults(func=cmd_runtime_wrapper)

    runtime_review = runtime_sub.add_parser("review")
    runtime_review.add_argument("--run", dest="run_id", required=True)
    runtime_review.add_argument("--status", choices=REVIEW_STATUSES, required=True)
    runtime_review.add_argument("--reviewer", default="")
    runtime_review.add_argument("--evidence-ref", action="append")
    runtime_review.add_argument("--summary", default="")
    runtime_review.set_defaults(func=cmd_runtime_review)

    runtime_ci = runtime_sub.add_parser("ci")
    runtime_ci.add_argument("--run", dest="run_id", required=True)
    runtime_ci.add_argument("--status", choices=CI_STATUSES, required=True)
    runtime_ci.add_argument("--provider", default="")
    runtime_ci.add_argument("--check", action="append")
    runtime_ci.add_argument("--evidence-ref", action="append")
    runtime_ci.add_argument("--summary", default="")
    runtime_ci.set_defaults(func=cmd_runtime_ci)

    runtime_merge = runtime_sub.add_parser("merge")
    runtime_merge.add_argument("--run", dest="run_id", required=True)
    merge_status = runtime_merge.add_mutually_exclusive_group()
    merge_status.add_argument("--ready", action="store_true")
    merge_status.add_argument("--merged", action="store_true")
    merge_status.add_argument("--blocked", action="store_true")
    merge_status.add_argument("--status", choices=MERGE_STATUSES, default=None)
    runtime_merge.add_argument("--target-branch", default="")
    runtime_merge.add_argument("--merge-commit", default="")
    runtime_merge.add_argument("--evidence-ref", action="append")
    runtime_merge.add_argument("--summary", default="")
    runtime_merge.set_defaults(func=cmd_runtime_merge)

    runtime_validate = runtime_sub.add_parser("validate")
    runtime_validate.add_argument("--run", dest="run_id", default=None)
    runtime_validate.set_defaults(func=cmd_runtime_validate)

    runtime_export = runtime_sub.add_parser("export")
    runtime_export.add_argument("--redacted", action="store_true", default=True)
    runtime_export.add_argument("--no-redact", dest="redacted", action="store_false")
    runtime_export.set_defaults(func=cmd_runtime_export)
