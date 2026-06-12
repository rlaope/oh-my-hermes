from __future__ import annotations

from pathlib import Path
from typing import Any

from ..coding_delegation import build_coding_delegation_payload, coding_delegation_record_payload
from ..paths import OmhPaths
from ..runtime.artifacts import (
    create_prepared_coding_delegation_run,
    summarize_delegated_coding_status,
    validate_runtime,
    write_coding_delegation,
    write_delegation,
    write_wrapper_contract,
)
from ..runtime.records import OBSERVED_RESULTS


LIFECYCLE_SCHEMA_VERSION = "coding_lifecycle/v1"


class CodingLifecycleError(ValueError):
    pass


def start_codex_delegation_lifecycle(
    paths: OmhPaths,
    message: str,
    *,
    source: str = "generic",
    source_metadata: dict[str, str] | None = None,
    limit: int = 3,
    include_message: bool = False,
    context_pack: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = build_coding_delegation_payload(
        message,
        source=source,
        limit=limit,
        include_message=include_message,
        source_metadata=source_metadata,
        executor_target="codex",
        context_pack=context_pack,
    )
    delegation = payload.get("delegation")
    if not isinstance(delegation, dict):
        raise CodingLifecycleError("coding lifecycle payload is missing delegation")
    run = create_prepared_coding_delegation_run(
        paths,
        {
            "skill": str(delegation["recommended_workflow"]),
            "harness": str(delegation["recommended_harness"]),
            "trigger": f"coding-lifecycle:{source}:{delegation['action']}",
            "privacy": "metadata_only",
            "inputs_summary": f"{source} Codex lifecycle request; message_length={len(message)}",
            "outputs_summary": f"prepared {delegation['action']} for {delegation['recommended_workflow']}",
            "verification_summary": "prepared_not_observed; Codex work is not observed by omh",
        },
    )
    run_dir = paths.runtime_runs_dir / str(run["run_id"])
    record = write_coding_delegation(
        run_dir,
        coding_delegation_record_payload(payload, message, source_metadata=source_metadata),
    )
    status = report_codex_delegation_lifecycle(paths, str(run["run_id"]))
    result: dict[str, object] = {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "run": run,
        "coding_delegation": record,
        "status": status,
    }
    if include_message:
        result["message"] = message
        if "executor_handoff_prompt" in payload:
            result["executor_handoff_prompt"] = payload["executor_handoff_prompt"]
    return result


def record_codex_dispatch(paths: OmhPaths, run_id: str) -> dict[str, object]:
    run_dir = _existing_run_dir(paths, run_id)
    status = summarize_delegated_coding_status(paths, run_id)
    next_action = str(status.get("next_action", ""))
    if next_action not in {"dispatch_to_executor", "wait_for_executor_evidence"}:
        raise CodingLifecycleError(f"cannot dispatch Codex handoff while next_action is {next_action}")
    wrapper = write_wrapper_contract(
        run_dir,
        {
            "prompt_dispatched": True,
            "hermes_response_observed": True,
            "verification_observed": False,
            "completion_status": "started",
        },
    )
    return {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "wrapper": wrapper,
        "status": report_codex_delegation_lifecycle(paths, run_id),
    }


def record_codex_result(
    paths: OmhPaths,
    run_id: str,
    *,
    result: str,
    participants: list[str] | tuple[str, ...] | None = None,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    run_dir = _existing_run_dir(paths, run_id)
    status = summarize_delegated_coding_status(paths, run_id)
    if str(status.get("next_action")) != "wait_for_executor_evidence":
        raise CodingLifecycleError(f"cannot record Codex result while next_action is {status.get('next_action')}")
    if result not in OBSERVED_RESULTS:
        raise CodingLifecycleError("Codex result must be completed, blocked, or failed")
    delegation = write_delegation(
        run_dir,
        {
            "requested": True,
            "observed": True,
            "participants": list(participants or ["codex"]),
            "result": result,
            "evidence_refs": list(evidence_refs or []),
        },
    )
    return {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "delegation": delegation,
        "status": report_codex_delegation_lifecycle(paths, run_id),
    }


def record_codex_verification(
    paths: OmhPaths,
    run_id: str,
    *,
    completion_status: str = "completed",
    gaps: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    run_dir = _existing_run_dir(paths, run_id)
    status = summarize_delegated_coding_status(paths, run_id)
    execution = status.get("execution", {})
    if not isinstance(execution, dict) or not execution.get("observed"):
        raise CodingLifecycleError("cannot record verification before executor evidence is observed")
    if execution.get("status") in {"blocked", "failed"}:
        raise CodingLifecycleError("cannot record successful verification for blocked or failed executor result")
    unobserved_gaps = list(gaps or [])
    verification_observed = completion_status == "completed" and not unobserved_gaps
    wrapper = write_wrapper_contract(
        run_dir,
        {
            "prompt_dispatched": True,
            "hermes_response_observed": True,
            "verification_observed": verification_observed,
            "completion_status": completion_status,
            "unobserved_gaps": unobserved_gaps,
        },
    )
    return {
        "schema_version": LIFECYCLE_SCHEMA_VERSION,
        "wrapper": wrapper,
        "status": report_codex_delegation_lifecycle(paths, run_id),
    }


def report_codex_delegation_lifecycle(paths: OmhPaths, run_id: str) -> dict[str, object]:
    status = summarize_delegated_coding_status(paths, run_id)
    next_action = str(status.get("next_action", "unknown"))
    completion_report_actions = {"report_completion_with_evidence"}
    terminal_report_actions = {"report_completion_with_evidence", "report_merge_ready", "report_merged"}
    report = dict(status)
    report.update(
        {
            "lifecycle_schema_version": LIFECYCLE_SCHEMA_VERSION,
            "lifecycle_status": _lifecycle_status(next_action),
            "can_report_completion": next_action in completion_report_actions,
            "can_report_terminal_status": next_action in terminal_report_actions,
            "blocking_reason": "" if next_action in terminal_report_actions else _blocking_reason(next_action),
            "artifact_paths": _artifact_paths(paths, run_id),
            "runtime_validation": validate_runtime(paths, run_id),
        }
    )
    return report


def _existing_run_dir(paths: OmhPaths, run_id: str) -> Path:
    run_dir = paths.runtime_runs_dir / run_id
    if not (run_dir / "run.json").exists():
        raise FileNotFoundError(run_id)
    return run_dir


def _lifecycle_status(next_action: str) -> str:
    return {
        "prepare_coding_delegation": "not_prepared",
        "route_coding_request": "needs_routing",
        "clarify_coding_request": "needs_clarification",
        "dispatch_to_executor": "prepared",
        "wait_for_executor_evidence": "dispatched",
        "surface_executor_blocker": "blocked",
        "surface_review_blocker": "blocked",
        "surface_ci_blocker": "blocked",
        "surface_merge_blocker": "blocked",
        "record_review_evidence": "awaiting_review",
        "record_ci_evidence": "awaiting_ci",
        "record_merge_readiness": "awaiting_merge_readiness",
        "record_verification_evidence": "awaiting_verification",
        "report_completion_with_evidence": "reportable",
        "report_merge_ready": "merge_ready",
        "report_merged": "merged",
    }.get(next_action, "unknown")


def _blocking_reason(next_action: str) -> str:
    return {
        "prepare_coding_delegation": "coding delegation is not prepared",
        "route_coding_request": "request must be routed before coding delegation",
        "clarify_coding_request": "request needs clarification before executor/runtime dispatch",
        "dispatch_to_executor": "executor/runtime dispatch is not observed",
        "wait_for_executor_evidence": "executor evidence is not observed",
        "surface_executor_blocker": "executor reported blocked or failed",
        "surface_review_blocker": "review failed or blocked completion",
        "surface_ci_blocker": "CI failed or blocked completion",
        "surface_merge_blocker": "merge is blocked",
        "record_review_evidence": "review evidence is required before completion can be reported",
        "record_ci_evidence": "CI evidence is required before merge readiness can be reported",
        "record_merge_readiness": "merge readiness evidence is required before merge-ready status can be reported",
        "record_verification_evidence": "verification evidence is required before completion can be reported",
    }.get(next_action, "lifecycle status is not reportable")


def _artifact_paths(paths: OmhPaths, run_id: str) -> dict[str, str]:
    run_dir = paths.runtime_runs_dir / run_id
    return {
        "run": str(run_dir / "run.json"),
        "events": str(run_dir / "events.jsonl"),
        "coding_delegation": str(run_dir / "coding_delegation.json"),
        "delegation": str(run_dir / "delegation.json"),
        "wrapper": str(run_dir / "wrapper.json"),
        "review": str(run_dir / "review.json"),
        "ci": str(run_dir / "ci.json"),
        "merge": str(run_dir / "merge.json"),
    }
