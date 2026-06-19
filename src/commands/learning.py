from __future__ import annotations

import argparse
import json

from ..ingress import CHAT_SOURCES
from ..installer import OmhError
from ..routing.chat import CONFIDENCE_LEVELS
from ..workflow_learning import (
    WorkflowLearningError,
    attach_learning_trace_ref_to_interaction,
    build_improvement_candidate,
    build_improvement_patch_proposal,
    build_workflow_learning_audit,
    build_learning_export_bundle,
    build_regression_case_from_trace,
    build_trace_from_chat_interaction,
    build_trace_from_runtime_run,
    build_workflow_eval_result,
    check_learning_index,
    learning_export_ref,
    learning_export_path,
    learning_trace_ref,
    list_learning_traces,
    rebuild_learning_index,
    replay_regression_cases,
    show_improvement_candidate,
    show_learning_trace,
    write_improvement_candidate,
    write_improvement_patch_proposal,
    write_learning_export,
    write_learning_trace,
    write_regression_case,
    write_workflow_eval,
)
from ..wrapper.contract import INTERACTION_MODES, build_chat_interaction_payload
from .common import _chat_input_and_metadata, _explicit_source_metadata, _paths, _print_json


def cmd_learning_record(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        if args.from_runtime_run:
            trace = build_trace_from_runtime_run(
                paths,
                args.from_runtime_run,
                outcome=args.outcome,
                feedback_summary=args.feedback_summary or "",
            )
            write_learning_trace(paths, trace)
            payload: dict[str, object] = {
                "schema_version": "learning_record_result/v1",
                "source_kind": "runtime_run",
                "learning_trace_ref": learning_trace_ref(str(trace["trace_id"])),
                "trace": trace,
                "claim_boundary": "The trace records existing runtime metadata only; it does not add execution evidence.",
            }
        else:
            event_or_message, source_metadata = _chat_input_and_metadata(args)
            interaction = build_chat_interaction_payload(
                event_or_message,
                source=args.source,
                mode=args.mode,
                limit=args.limit,
                min_confidence=args.min_confidence,
                include_message=False,
                source_metadata={**source_metadata, **_explicit_source_metadata(args)},
                executor_target=args.executor,
            )
            trace = build_trace_from_chat_interaction(
                interaction,
                source_ref=args.source_ref or args.source_event_id or "",
                outcome=args.outcome,
                feedback_summary=args.feedback_summary or "",
            )
            write_learning_trace(paths, trace)
            payload = {
                "schema_version": "learning_record_result/v1",
                "source_kind": "chat_interaction",
                "learning_trace_ref": learning_trace_ref(str(trace["trace_id"])),
                "trace": trace,
                "interaction": attach_learning_trace_ref_to_interaction(interaction, trace),
                "claim_boundary": "The learning ref is exposed only after the trace is written; it is not execution evidence.",
            }
    except (OSError, json.JSONDecodeError, ValueError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_learning_list(args: argparse.Namespace) -> int:
    try:
        traces = list_learning_traces(_paths(args), limit=args.limit)
    except (OSError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "learning_trace_list/v1",
            "traces": traces,
            "claim_boundary": "Trace lists summarize local learning records only; they do not prove workflow execution.",
        }
    )
    return 0


def cmd_learning_show(args: argparse.Namespace) -> int:
    try:
        trace = show_learning_trace(_paths(args), args.trace_id)
    except FileNotFoundError as exc:
        raise OmhError(f"learning trace not found: {args.trace_id}") from exc
    except (OSError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(trace)
    return 0


def cmd_learning_eval(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        trace = show_learning_trace(paths, args.trace_id)
        result = build_workflow_eval_result(trace, rubric_id=args.rubric)
        if not args.dry_run:
            write_workflow_eval(paths, result)
    except FileNotFoundError as exc:
        raise OmhError(f"learning trace not found: {args.trace_id}") from exc
    except (OSError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "learning_eval_result/v1",
            "recorded": not args.dry_run,
            "eval": result,
        }
    )
    return 0


def cmd_learning_candidate(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        trace = show_learning_trace(paths, args.trace_id)
        eval_result = build_workflow_eval_result(trace, rubric_id=args.rubric)
        candidate = build_improvement_candidate(trace, eval_result, target_type=args.target_type, title=args.title or "")
        if not args.dry_run:
            write_workflow_eval(paths, eval_result)
            write_improvement_candidate(paths, candidate)
    except FileNotFoundError as exc:
        raise OmhError(f"learning trace not found: {args.trace_id}") from exc
    except (OSError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "learning_candidate_result/v1",
            "recorded": not args.dry_run,
            "eval": eval_result,
            "candidate": candidate,
        }
    )
    return 0


def cmd_learning_proposal(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        candidate = show_improvement_candidate(paths, args.candidate_id)
        proposal = build_improvement_patch_proposal(paths, candidate)
        recorded = False
        if not args.dry_run:
            write_improvement_patch_proposal(paths, proposal)
            recorded = True
    except FileNotFoundError as exc:
        raise OmhError(f"improvement candidate not found: {args.candidate_id}") from exc
    except (OSError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "learning_patch_proposal_result/v1",
            "recorded": recorded,
            "dry_run": args.dry_run,
            "proposal": proposal,
            "claim_boundary": (
                "The patch proposal is handoff material only. OMH did not edit source files, "
                "run tests, pass review, or prove future behavior changed."
            ),
        }
    )
    return 0


def cmd_learning_regression_add(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        trace = show_learning_trace(paths, args.trace_id)
        case = build_regression_case_from_trace(
            trace,
            redacted_message=args.fixture_message or args.redacted_message or "",
            expected_workflow=args.expected_workflow or None,
            expected_harness=args.expected_harness or None,
            expected_next_action=args.expected_next_action or None,
        )
        write_regression_case(paths, case)
    except FileNotFoundError as exc:
        raise OmhError(f"learning trace not found: {args.trace_id}") from exc
    except (OSError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "learning_regression_case_result/v1",
            "regression_case": case,
            "claim_boundary": (
                "The case stores only operator-provided minimized fixture text when provided; "
                "OMH cannot prove redaction and does not treat the fixture as observed workflow execution."
            ),
        }
    )
    return 0


def cmd_learning_regression_replay(args: argparse.Namespace) -> int:
    try:
        payload = replay_regression_cases(_paths(args), limit=args.limit)
    except (OSError, WorkflowLearningError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_learning_index_check(args: argparse.Namespace) -> int:
    try:
        payload = check_learning_index(_paths(args))
    except (OSError, json.JSONDecodeError, ValueError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0 if payload.get("ok") else 1


def cmd_learning_index_rebuild(args: argparse.Namespace) -> int:
    try:
        payload = rebuild_learning_index(_paths(args), dry_run=args.dry_run)
    except (OSError, json.JSONDecodeError, ValueError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0 if payload.get("status") in {"rebuilt", "dry_run"} else 1


def cmd_learning_export(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        limit = None if args.all else args.limit
        bundle = build_learning_export_bundle(paths, trace_ids=args.trace_id or [], limit=limit)
        export_path = learning_export_path(paths, str(bundle["export_id"]))
        recorded = False
        if not args.dry_run and bundle.get("status") == "ready":
            write_learning_export(paths, bundle)
            recorded = True
    except (OSError, json.JSONDecodeError, ValueError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "schema_version": "learning_export_result/v1",
            "recorded": recorded,
            "dry_run": args.dry_run,
            "learning_export_ref": learning_export_ref(str(bundle["export_id"])),
            "export_path": str(export_path),
            "export": bundle,
            "claim_boundary": (
                "The export is a metadata-only review bundle. It is not model training, "
                "automatic skill improvement, workflow execution, or observed runtime evidence."
            ),
        }
    )
    return 0


def cmd_learning_audit(args: argparse.Namespace) -> int:
    try:
        payload = build_workflow_learning_audit(_paths(args), limit=None if args.all else args.limit)
    except (OSError, json.JSONDecodeError, ValueError, WorkflowLearningError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0 if payload.get("status") in {"ready", "no_records", "needs_attention"} else 1


def _add_learning_commands(sub) -> None:
    learning = sub.add_parser(
        "learning",
        help="Record workflow learning traces, evals, improvement candidates, and regression cases.",
    )
    learning_sub = learning.add_subparsers(dest="learning_command", required=True)

    record = learning_sub.add_parser("record", help="Persist a metadata-only learning trace from chat or runtime evidence.")
    record.add_argument("message", nargs="*", help="Chat message to route and record as a learning trace.")
    record.add_argument("--source", choices=CHAT_SOURCES, default="generic")
    record.add_argument("--mode", choices=INTERACTION_MODES, default="auto")
    record.add_argument("--limit", type=int, default=3)
    record.add_argument("--min-confidence", choices=CONFIDENCE_LEVELS, default="high")
    record.add_argument("--stdin", action="store_true")
    record.add_argument("--event-json", default=None)
    record.add_argument("--executor", default="choose")
    record.add_argument("--source-ref", default="")
    record.add_argument("--source-event-id", default="")
    record.add_argument("--channel-ref", default="")
    record.add_argument("--user-ref", default="")
    record.add_argument("--from-runtime-run", default="")
    record.add_argument("--outcome", choices=("unknown", "useful", "not_useful", "blocked", "failed"), default="unknown")
    record.add_argument("--feedback-summary", default="")
    record.set_defaults(func=cmd_learning_record)

    list_cmd = learning_sub.add_parser("list", help="List local workflow learning traces.")
    list_cmd.add_argument("--limit", type=int, default=None)
    list_cmd.set_defaults(func=cmd_learning_list)

    show_cmd = learning_sub.add_parser("show", help="Show one workflow learning trace.")
    show_cmd.add_argument("trace_id")
    show_cmd.set_defaults(func=cmd_learning_show)

    eval_cmd = learning_sub.add_parser("eval", help="Evaluate one learning trace against deterministic rubrics.")
    eval_cmd.add_argument("trace_id")
    eval_cmd.add_argument("--rubric", default="default")
    eval_cmd.add_argument("--dry-run", action="store_true")
    eval_cmd.set_defaults(func=cmd_learning_eval)

    candidate = learning_sub.add_parser("candidate", help="Create a review-only improvement candidate from a trace eval.")
    candidate.add_argument("trace_id")
    candidate.add_argument("--rubric", default="default")
    candidate.add_argument("--target-type", default="workflow_rubric")
    candidate.add_argument("--title", default="")
    candidate.add_argument("--dry-run", action="store_true")
    candidate.set_defaults(func=cmd_learning_candidate)

    proposal = learning_sub.add_parser(
        "proposal",
        help="Create a non-applying patch proposal from an approved improvement candidate.",
    )
    proposal.add_argument("candidate_id")
    proposal.add_argument("--dry-run", action="store_true")
    proposal.set_defaults(func=cmd_learning_proposal)

    export = learning_sub.add_parser("export", help="Create a redacted workflow learning review bundle.")
    export.add_argument("--trace-id", action="append", default=[], help="Trace id to include; may be repeated.")
    export.add_argument("--limit", type=int, default=20, help="Maximum recent traces to include when no trace id is provided.")
    export.add_argument("--all", action="store_true", help="Include all traces when no trace id is provided.")
    export.add_argument("--dry-run", action="store_true")
    export.set_defaults(func=cmd_learning_export)

    audit = learning_sub.add_parser("audit", help="Audit local workflow learning readiness without mutating records.")
    audit.add_argument("--limit", type=int, default=20, help="Maximum recent traces to summarize.")
    audit.add_argument("--all", action="store_true", help="Audit and summarize all traces.")
    audit.set_defaults(func=cmd_learning_audit)

    regression = learning_sub.add_parser("regression", help="Manage deterministic workflow regression cases.")
    regression_sub = regression.add_subparsers(dest="regression_command", required=True)

    regression_add = regression_sub.add_parser("add", help="Create a regression case from a learning trace.")
    regression_add.add_argument("trace_id")
    regression_add.add_argument("--fixture-message", default="", help="Operator-minimized replay fixture text.")
    regression_add.add_argument(
        "--redacted-message",
        default="",
        help="Deprecated alias for --fixture-message; caller is responsible for minimizing private content.",
    )
    regression_add.add_argument("--expected-workflow", default="")
    regression_add.add_argument("--expected-harness", default="")
    regression_add.add_argument("--expected-next-action", default="")
    regression_add.set_defaults(func=cmd_learning_regression_add)

    regression_replay = regression_sub.add_parser("replay", help="Replay local workflow regression cases.")
    regression_replay.add_argument("--limit", type=int, default=None)
    regression_replay.set_defaults(func=cmd_learning_regression_replay)

    index = learning_sub.add_parser("index", help="Check or rebuild the local workflow learning index.")
    index_sub = index.add_subparsers(dest="index_command", required=True)

    index_check = index_sub.add_parser("check", help="Validate learning_index.json against local learning records.")
    index_check.set_defaults(func=cmd_learning_index_check)

    index_rebuild = index_sub.add_parser("rebuild", help="Rebuild learning_index.json from local learning records.")
    index_rebuild.add_argument("--dry-run", action="store_true")
    index_rebuild.set_defaults(func=cmd_learning_index_rebuild)
