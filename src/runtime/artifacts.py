from __future__ import annotations

import json
import re
import secrets
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..context_safety import build_coding_progress_reporting_policy
from ..harness_quality import build_harness_progress
from ..local_store import (
    atomic_write_json,
    ensure_dir,
    ensure_file,
    read_json_object,
    read_json_object_result,
    read_jsonl_objects,
    utc_now,
)
from ..observation_journal import (
    append_observation_event,
    merge_lifecycle_projection,
    project_run_lifecycle,
    read_observation_events_result,
    validate_observation_journal,
)
from ..paths import OmhPaths
from .records import (
    DELEGATION_RESULTS,
    EVENT_LEVELS,
    OBSERVED_RESULTS,
    OPTIONAL_RECORD_VALIDATORS,
    PRIVACY_MODES,
    RUNTIME_OBSERVATION_EVENTS,
    RUNTIME_OBSERVATION_SCHEMA_VERSION,
    RUNTIME_OBSERVATION_STATUSES,
    CI_STATUSES,
    MERGE_STATUSES,
    REVIEW_STATUSES,
    RUN_STATUSES,
    SCHEMA_VERSION,
    UNOBSERVED_RESULTS,
    WRAPPER_COMPLETION_STATUSES,
    build_delegation_record,
    build_coding_delegation_record,
    build_event_record,
    build_ci_record,
    build_routing_record,
    build_merge_record,
    build_review_record,
    build_run_record,
    build_runtime_observation_record,
    build_wrapper_record,
    validate_delegation_record,
    validate_coding_delegation_record,
    validate_ci_record,
    validate_delegation_result,
    validate_event_record,
    validate_merge_record,
    validate_review_record,
    validate_routing_record,
    validate_run_record,
    validate_runtime_observation_record,
    validate_wrapper_record,
    validate_wrapper_session_record,
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "run")[:48].strip("-") or "run"


def _stamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def new_run_id(now: datetime | str | None = None, slug: str = "run") -> str:
    return f"{_stamp(now)}-{_slugify(slug)}"


def _unique_run_id(paths: OmhPaths, slug: str) -> str:
    for _ in range(100):
        run_id = f"{new_run_id(slug=slug)}-{secrets.token_hex(3)}"
        if not (paths.runtime_runs_dir / run_id).exists():
            return run_id
    raise RuntimeError("could not allocate unique runtime run id")


def read_state(paths: OmhPaths) -> dict[str, Any] | None:
    return read_json_object(paths.runtime_state_path)


def read_state_result(paths: OmhPaths) -> tuple[dict[str, Any] | None, str | None]:
    return read_json_object_result(paths.runtime_state_path)


def read_state_error(paths: OmhPaths) -> str | None:
    return read_state_result(paths)[1]


def update_state(paths: OmhPaths, patch: dict[str, Any]) -> dict[str, Any]:
    current, state_error = read_state_result(paths)
    current = current or {"schema_version": SCHEMA_VERSION}
    merged = {**current, **patch, "schema_version": SCHEMA_VERSION, "updated_at": utc_now()}
    if state_error:
        merged["previous_state_error"] = state_error
    try:
        atomic_write_json(paths.runtime_state_path, merged, private=True)
    except OSError as exc:
        merged["state_write_error"] = str(exc)
    return merged


def create_run(paths: OmhPaths, metadata: dict[str, Any]) -> dict[str, Any]:
    skill = str(metadata.get("skill", "unknown"))
    harness = str(metadata.get("harness", "unknown"))
    run_id = str(metadata.get("run_id") or _unique_run_id(paths, f"{skill}-{harness}"))
    run = build_run_record(metadata, run_id)
    run_dir = paths.runtime_runs_dir / run_id
    evidence_dir = run_dir / "evidence"
    ensure_dir(evidence_dir, private=True)
    atomic_write_json(run_dir / "run.json", run, private=True)
    append_event(run_dir, {"event": "run_recorded", "level": "info", "message": f"{skill}/{harness} recorded as {run['status']}"})
    update_state(paths, {"last_run_id": run_id})
    return run


def create_prepared_coding_delegation_run(paths: OmhPaths, metadata: dict[str, Any]) -> dict[str, Any]:
    prepared_metadata = {
        **metadata,
        "status": "prepared",
        "artifact_kind": "prepared_coding_delegation",
        "phase": "prepared",
        "observation_status": "prepared_not_observed",
    }
    run = create_run(paths, prepared_metadata)
    append_observation_event(
        paths,
        {
            "target_type": "run",
            "target_id": run["run_id"],
            "run_id": run["run_id"],
            "workflow": run.get("skill", ""),
            "harness": run.get("harness", ""),
            "phase": "prepared",
            "event": "prepared_handoff_created",
            "status": "observed",
            "source": "omh-runtime",
            "summary": "Prepared coding handoff recorded; execution is not observed.",
        },
    )
    return run


def append_event(run_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    item = build_event_record(event)
    ensure_dir(run_dir, private=True)
    events_path = run_dir / "events.jsonl"
    ensure_file(events_path, private=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True) + "\n")
    return item


def write_delegation(run_dir: Path, delegation: dict[str, Any]) -> dict[str, Any]:
    record = build_delegation_record(delegation)
    atomic_write_json(run_dir / "delegation.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "delegation_recorded",
            "level": "info",
            "message": f"delegation {record['result']}",
            "data": {"requested": record["requested"], "observed": record["observed"]},
        },
    )
    return record


def write_wrapper_contract(run_dir: Path, wrapper: dict[str, Any]) -> dict[str, Any]:
    record = build_wrapper_record(wrapper)
    atomic_write_json(run_dir / "wrapper.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "wrapper_contract_recorded",
            "level": "info",
            "message": f"wrapper contract {record['completion_status']}",
            "data": {
                "prompt_dispatched": record["prompt_dispatched"],
                "hermes_response_observed": record["hermes_response_observed"],
                "verification_observed": record["verification_observed"],
            },
        },
    )
    return record


def write_routing_decision(run_dir: Path, routing: dict[str, Any]) -> dict[str, Any]:
    record = build_routing_record(routing)
    atomic_write_json(run_dir / "routing.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "routing_decision_recorded",
            "level": "info",
            "message": f"routing {record['action']} {record['selected_skill']}",
            "data": {
                "source": record["source"],
                "action": record["action"],
                "selected_skill": record["selected_skill"],
                "confidence": record["confidence"],
                "score": record["score"],
            },
        },
    )
    return record


def write_coding_delegation(run_dir: Path, delegation: dict[str, Any]) -> dict[str, Any]:
    record = build_coding_delegation_record(delegation)
    atomic_write_json(run_dir / "coding_delegation.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "coding_delegation_recorded",
            "level": "info",
            "message": f"coding delegation {record['action']} {record['recommended_workflow']}",
            "data": {
                "source": record["source"],
                "action": record["action"],
                "intent": record["intent"],
                "recommended_workflow": record["recommended_workflow"],
                "status": record["status"],
            },
        },
    )
    return record


def _run_id_for_dir(run_dir: Path) -> str:
    run = read_json_object(run_dir / "run.json") if (run_dir / "run.json").exists() else None
    return str(run.get("run_id", run_dir.name)) if isinstance(run, dict) else run_dir.name


def write_review_record(run_dir: Path, review: dict[str, Any]) -> dict[str, Any]:
    record = build_review_record({"run_id": _run_id_for_dir(run_dir), **review})
    atomic_write_json(run_dir / "review.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "review_recorded",
            "level": "info",
            "message": f"review {record['status']}",
            "data": {"status": record["status"], "observed": record["observed"], "required": record["required"]},
        },
    )
    return record


def write_ci_record(run_dir: Path, ci: dict[str, Any]) -> dict[str, Any]:
    record = build_ci_record({"run_id": _run_id_for_dir(run_dir), **ci})
    atomic_write_json(run_dir / "ci.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "ci_recorded",
            "level": "info",
            "message": f"ci {record['status']}",
            "data": {"status": record["status"], "observed": record["observed"], "required": record["required"]},
        },
    )
    return record


def write_merge_record(run_dir: Path, merge: dict[str, Any]) -> dict[str, Any]:
    record = build_merge_record({"run_id": _run_id_for_dir(run_dir), **merge})
    atomic_write_json(run_dir / "merge.json", record, private=True)
    append_event(
        run_dir,
        {
            "event": "merge_recorded",
            "level": "info",
            "message": f"merge {record['status']}",
            "data": {"status": record["status"], "observed": record["observed"], "ready": record["ready"], "merged": record["merged"]},
        },
    )
    return record


def write_runtime_observation(target_dir: Path, observation: dict[str, Any]) -> dict[str, Any]:
    record = build_runtime_observation_record(observation)
    ensure_dir(target_dir, private=True)
    path = target_dir / "runtime_observations.jsonl"
    ensure_file(path, private=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    append_event(
        target_dir,
        {
            "event": "runtime_observation_recorded",
            "level": "info" if record["status"] == "observed" else "warning",
            "message": f"runtime observation {record['event_type']} {record['status']}",
            "data": {
                "target_type": record["target_type"],
                "target_id": record["target_id"],
                "runtime_profile": record["runtime_profile"],
                "event_type": record["event_type"],
                "status": record["status"],
                "observed": record["observed"],
            },
        },
    )
    _append_runtime_observation_to_journal(target_dir, record)
    return record


def append_journal_observation(paths: OmhPaths, observation: dict[str, Any]) -> dict[str, Any]:
    return append_observation_event(paths, observation)


def _append_runtime_observation_to_journal(target_dir: Path, record: dict[str, Any]) -> None:
    try:
        runtime_dir = target_dir.parents[1]
        paths = OmhPaths(omh_home=runtime_dir.parent, hermes_home=Path("~/.hermes").expanduser())
        append_observation_event(
            paths,
            {
                "target_type": record.get("target_type", ""),
                "target_id": record.get("target_id", ""),
                "run_id": record.get("target_id", "") if record.get("target_type") == "run" else "",
                "event": record.get("event_type", ""),
                "status": record.get("status", "observed"),
                "observed_at": record.get("updated_at", ""),
                "runtime_profile": record.get("runtime_profile", ""),
                "evidence_refs": record.get("evidence_refs", []),
                "summary": record.get("summary", ""),
                "source": "runtime_observation",
                "worktree_ref": record.get("worktree_ref", ""),
                "worker_ref": record.get("worker_ref", ""),
            },
        )
    except (IndexError, OSError, ValueError):
        return


def _journal_events_for_run_result(paths: OmhPaths, run_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    events, errors = read_observation_events_result(paths)
    return [event for event in events if str(event.get("run_id", "")) == run_id], errors


def _lifecycle_projection_from_shown(shown: dict[str, Any]) -> dict[str, Any]:
    run = _object_or_empty(shown.get("run"))
    run_id = str(run.get("run_id", ""))
    legacy = _legacy_lifecycle_projection(shown)
    journal = project_run_lifecycle(
        _list_or_empty(shown.get("journal_events")),
        run_id=run_id,
        workflow=str(run.get("skill", "")),
        harness=str(run.get("harness", "")),
        phase=str(run.get("phase", "")),
    )
    return merge_lifecycle_projection(legacy, journal)


def _legacy_lifecycle_projection(shown: dict[str, Any]) -> dict[str, Any]:
    run = _object_or_empty(shown.get("run"))
    coding = _object_or_empty(shown.get("coding_delegation"))
    delegation = _object_or_empty(shown.get("delegation"))
    wrapper = _object_or_empty(shown.get("wrapper"))
    review = _object_or_empty(shown.get("review"))
    ci = _object_or_empty(shown.get("ci"))
    merge = _object_or_empty(shown.get("merge"))
    plan_artifact = _object_or_empty(coding.get("plan_artifact"))
    prepared = run.get("artifact_kind") == "prepared_coding_delegation" and bool(coding)
    observation_status = str(run.get("observation_status", "unknown"))
    if merge.get("observed"):
        observation_status = "merge_observed"
    elif ci.get("observed"):
        observation_status = "ci_observed"
    elif review.get("observed"):
        observation_status = "review_observed"
    elif wrapper.get("verification_observed"):
        observation_status = "verification_observed"
    elif delegation.get("observed"):
        observation_status = "execution_observed"
    elif wrapper.get("prompt_dispatched"):
        observation_status = "dispatch_observed"
    elif prepared:
        observation_status = "prepared_not_observed"
    return {
        "schema_version": "omh_lifecycle_projection/v1",
        "run_id": str(run.get("run_id", "")),
        "workflow": str(coding.get("recommended_workflow") or run.get("skill", "")),
        "harness": str(coding.get("recommended_harness") or run.get("harness", "")),
        "phase": str(run.get("phase", "")),
        "prepared_handoff": prepared,
        "plan_artifact": str(plan_artifact.get("path", "")),
        "plan_status": str(plan_artifact.get("status", "")),
        "prompt_dispatched": bool(wrapper.get("prompt_dispatched", False)),
        "runtime_start_observed": False,
        "worktree_observed": False,
        "execution_observed": bool(delegation.get("observed", False)),
        "verification_observed": bool(wrapper.get("verification_observed", False)),
        "review_observed": bool(review.get("observed", False)),
        "ci_observed": bool(ci.get("observed", False)),
        "merge_gate_observed": bool(merge.get("ready", False)),
        "merge_observed": bool(merge.get("merged", False)),
        "blocked": delegation.get("result") == "blocked" or wrapper.get("completion_status") == "blocked",
        "failed": delegation.get("result") == "failed" or wrapper.get("completion_status") == "failed",
        "cancelled": False,
        "observation_status": observation_status,
        "journal_event_count": 0,
        "latest_event_id": "",
        "latest_event": {},
    }


def _apply_limit(records: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return records
    if limit < 1:
        return []
    return records[-limit:]


def list_runs(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not paths.runtime_runs_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_json in sorted(paths.runtime_runs_dir.glob("*/run.json")):
        run = read_json_object(run_json)
        if run:
            runs.append(run)
    return _apply_limit(runs, limit)


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    return read_events_result(run_dir)[0]


def read_events_result(run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    path = run_dir / "events.jsonl"
    return read_jsonl_objects(path)


def read_runtime_observations(target_dir: Path) -> list[dict[str, Any]]:
    return read_runtime_observations_result(target_dir)[0]


def read_runtime_observations_result(target_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    return read_jsonl_objects(target_dir / "runtime_observations.jsonl")


def runtime_observations_for_target(records: list[dict[str, Any]], target_type: str, target_id: str) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("target_type") == target_type and str(record.get("target_id", "")) == target_id
    ]


def show_run(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    run_dir = paths.runtime_runs_dir / run_id
    run = read_json_object(run_dir / "run.json")
    if not run:
        raise FileNotFoundError(run_id)
    evidence_dir = run_dir / "evidence"
    events, event_errors = read_events_result(run_dir)
    observations, observation_errors = read_runtime_observations_result(run_dir)
    journal_events, journal_errors = _journal_events_for_run_result(paths, run_id)
    result = {
        "run": run,
        "events": events,
        "runtime_observations": observations,
        "journal_events": journal_events,
        "executor_progress": _show_executor_progress(run_dir),
        "routing": read_json_object(run_dir / "routing.json"),
        "coding_delegation": read_json_object(run_dir / "coding_delegation.json"),
        "delegation": read_json_object(run_dir / "delegation.json"),
        "wrapper": read_json_object(run_dir / "wrapper.json"),
        "review": read_json_object(run_dir / "review.json"),
        "ci": read_json_object(run_dir / "ci.json"),
        "merge": read_json_object(run_dir / "merge.json"),
        "evidence": sorted(path.name for path in evidence_dir.iterdir()) if evidence_dir.exists() else [],
    }
    if event_errors:
        result["event_errors"] = event_errors
    if observation_errors:
        result["runtime_observation_errors"] = observation_errors
    if journal_errors:
        result["journal_errors"] = journal_errors
    result["lifecycle"] = _lifecycle_projection_from_shown(result)
    return result


def list_wrapper_session_records(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for session_json in sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json")):
        session = read_json_object(session_json)
        if session:
            sessions.append(session)
    return _apply_limit(sessions, limit)


def show_wrapper_session_record(paths: OmhPaths, session_id: str) -> dict[str, Any]:
    session_dir = paths.runtime_wrapper_sessions_dir / session_id
    session = read_json_object(session_dir / "session.json")
    if not session:
        raise FileNotFoundError(session_id)
    events, event_errors = _read_jsonl_events_result(session_dir / "events.jsonl")
    observations, observation_errors = read_runtime_observations_result(session_dir)
    result = {
        "session": session,
        "events": events,
        "runtime_observations": observations,
        "executor_session": read_json_object(session_dir / "executor_session.json"),
        "executor_progress": _show_executor_progress(session_dir),
    }
    if event_errors:
        result["event_errors"] = event_errors
    if observation_errors:
        result["runtime_observation_errors"] = observation_errors
    return result


def _show_executor_progress(target_dir: Path) -> dict[str, Any]:
    progress_dir = target_dir / "executor_progress"
    binding = read_json_object(progress_dir / "binding.json") if (progress_dir / "binding.json").exists() else None
    events, event_errors = read_jsonl_objects(progress_dir / "events.jsonl")
    reports, report_errors = read_jsonl_objects(progress_dir / "reports.jsonl")
    binding_id = str(binding.get("binding_id", "")) if isinstance(binding, dict) else ""
    matching_events = [event for event in events if str(event.get("binding_id", "")) == binding_id]
    matching_reports = [report for report in reports if str(report.get("binding_id", "")) == binding_id]
    result = {
        "schema_version": "omh_executor_progress_show/v1",
        "diagnostic_only": True,
        "state": _executor_progress_show_state(target_dir, binding if isinstance(binding, dict) else {}),
        "binding": binding,
        "latest_event": matching_events[-1] if matching_events else {},
        "latest_report": matching_reports[-1] if matching_reports else {},
        "claim_boundary": (
            "Runtime show exposes diagnostic progress metadata. It is not result, verification, review, CI, "
            "merge-readiness, or merge evidence."
        ),
    }
    if event_errors:
        result["event_errors"] = event_errors
    if report_errors:
        result["report_errors"] = report_errors
    return result


def _executor_progress_show_state(target_dir: Path, binding: dict[str, Any]) -> str:
    delegation = read_json_object(target_dir / "delegation.json") or {}
    if bool(delegation.get("observed")) and str(delegation.get("result", "")) in {"completed", "blocked", "failed"}:
        return "closed"
    executor_session = read_json_object(target_dir / "executor_session.json") or {}
    if bool(executor_session.get("result_observed")) and str(executor_session.get("result", "")) in {"completed", "blocked", "failed"}:
        return "closed"
    return str(binding.get("state", ""))


def summarize_delegated_coding_status(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    shown = show_run(paths, run_id)
    run = _object_or_empty(shown.get("run"))
    coding = _object_or_empty(shown.get("coding_delegation"))
    delegation = _object_or_empty(shown.get("delegation"))
    wrapper = _object_or_empty(shown.get("wrapper"))
    review_record = _object_or_empty(shown.get("review"))
    ci_record = _object_or_empty(shown.get("ci"))
    merge_record = _object_or_empty(shown.get("merge"))
    runtime_observations = runtime_observations_for_target(_list_or_empty(shown.get("runtime_observations")), "run", run_id)
    lifecycle = _object_or_empty(shown.get("lifecycle"))
    legacy_runtime_observation = summarize_runtime_observation_status(runtime_observations)
    handoff = _object_or_empty(coding.get("executor_handoff"))
    review = _object_or_empty(handoff.get("review"))

    prepared = run.get("artifact_kind") == "prepared_coding_delegation" and bool(coding)
    action = str(coding.get("action", "unknown"))
    handoff_available = bool(handoff)
    executor_target = str(handoff.get("executor_target") or coding.get("executor_profile") or "generic")
    execution_observed = bool(delegation.get("observed", False)) or bool(lifecycle.get("execution_observed", False))
    execution_status = str(
        delegation.get("result")
        or ("completed" if lifecycle.get("execution_observed") else "not_observed" if prepared else "unknown")
    )
    prompt_dispatched = bool(wrapper.get("prompt_dispatched", False)) or bool(lifecycle.get("prompt_dispatched", False))
    response_observed = bool(wrapper.get("hermes_response_observed", False))
    verification_observed = bool(wrapper.get("verification_observed", False)) or bool(lifecycle.get("verification_observed", False))
    completion_status = str(wrapper.get("completion_status") or "unknown")
    verification_status = _verification_status_summary(
        observed=verification_observed,
        completion_status=completion_status,
        unobserved_gaps=wrapper.get("unobserved_gaps", []),
    )
    review_required = bool(review.get("required", coding.get("review_required", False)))
    review_workflow = review.get("workflow") if review else coding.get("review_workflow")
    review_status = _review_status_summary(review_required, review_workflow, review, review_record)
    review_status = _apply_lifecycle_review_status(review_status, lifecycle)
    ci_required = bool(ci_record) or review_status["status"] == "passed"
    ci_status = _ci_status_summary(ci_required, ci_record)
    ci_status = _apply_lifecycle_ci_status(ci_status, lifecycle, review_status)
    merge_required = bool(merge_record) or ci_status["status"] == "passed"
    merge_status = _merge_status_summary(merge_required, merge_record)
    merge_status = _apply_lifecycle_merge_status(merge_status, lifecycle)
    harness_quality = _object_or_empty(coding.get("harness_quality") or handoff.get("harness_quality"))
    harness_progress = _delegated_harness_progress(
        harness_quality,
        prepared=prepared,
        prompt_dispatched=prompt_dispatched,
        execution_observed=execution_observed,
        execution_status=execution_status,
        verification_observed=verification_observed,
        review_status=review_status,
        ci_status=ci_status,
        merge_status=merge_status,
    )

    next_action = _delegated_status_next_action(
        prepared=prepared,
        action=action,
        prompt_dispatched=prompt_dispatched,
        execution_observed=execution_observed,
        execution_status=execution_status,
        verification_observed=verification_observed,
        review_status=review_status,
        ci_status=ci_status,
        merge_status=merge_status,
    )
    runtime_observation_status = _delegated_runtime_observation_status(
        legacy_runtime_observation,
        lifecycle,
        next_action=next_action,
    )
    integrity_warnings = _delegated_status_integrity_warnings(
        run=run,
        coding=coding,
        delegation=delegation,
        wrapper=wrapper,
        handoff=handoff,
        prepared=prepared,
        action=action,
    )
    return {
        "schema_version": "delegated_coding_status/v1",
        "run_id": run_id,
        "source": coding.get("source", "generic"),
        "source_metadata": coding.get("source_metadata", {}),
        "prepared": {
            "available": prepared,
            "action": action,
            "status": coding.get("status", run.get("observation_status", "unknown")),
            "executor_target": executor_target,
            "workflow": coding.get("recommended_workflow", run.get("skill", "unknown")),
            "harness": coding.get("recommended_harness", run.get("harness", "unknown")),
            "handoff_available": handoff_available,
            "handoff_schema_version": handoff.get("schema_version"),
        },
        "handoff_contract": _handoff_contract_summary(handoff),
        "harness_quality": harness_quality,
        "harness_progress": harness_progress,
        "execution": {
            "observed": execution_observed,
            "status": execution_status,
            "participants": delegation.get("participants", []),
            "evidence_refs": delegation.get("evidence_refs", []),
        },
        "wrapper": {
            "prompt_dispatched": prompt_dispatched,
            "hermes_response_observed": response_observed,
            "completion_status": completion_status,
            "unobserved_gaps": wrapper.get("unobserved_gaps", []),
        },
        "verification": {
            **verification_status,
            "observed": verification_observed,
            "expected": coding.get("verification", []),
        },
        "review": {
            **review_status,
            "workflow": review_workflow,
            "evidence_required": review.get("evidence_required", "Record review evidence separately before claiming review observed."),
        },
        "ci": ci_status,
        "merge_readiness": {
            "required": merge_status["required"],
            "status": "ready" if merge_status["status"] in {"ready", "merged"} else merge_status["status"],
            "observed": merge_status["observed"],
            "target_branch": merge_status["target_branch"],
            "evidence_refs": merge_status["evidence_refs"],
            "summary": merge_status["summary"],
        },
        "merge": merge_status,
        "runtime_observation": runtime_observation_status,
        "lifecycle": lifecycle,
        "next_action": next_action,
        "progress_reporting_policy": build_coding_progress_reporting_policy(next_action=next_action),
        "safe_summary": _delegated_status_summary(
            prepared=prepared,
            action=action,
            executor_target=executor_target,
            prompt_dispatched=prompt_dispatched,
            execution_observed=execution_observed,
            execution_status=execution_status,
            verification_observed=verification_observed,
            review_status=review_status,
            ci_status=ci_status,
            merge_status=merge_status,
        ),
        "integrity": {
            "ok": not integrity_warnings,
            "warnings": integrity_warnings,
        },
        "overclaim_guard": [
            "Prepared coding delegation is not execution evidence.",
            "Hermes should not claim it implemented code from this record.",
            "Review, verification, CI, and merge status require separate observed evidence.",
        ],
    }


def summarize_runtime_observation_status(records: list[dict[str, Any]]) -> dict[str, Any]:
    latest_by_event: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        event_type = str(record.get("event_type", ""))
        current = latest_by_event.get(event_type)
        if event_type in RUNTIME_OBSERVATION_EVENTS and (
            current is None or _runtime_observation_sort_key(record) >= _runtime_observation_sort_key(current)
        ):
            latest_by_event[event_type] = record

    observed_events: list[str] = []
    blocked_events: list[str] = []
    failed_events: list[str] = []
    not_observed_events: list[str] = []
    for event_type in RUNTIME_OBSERVATION_EVENTS:
        record = latest_by_event.get(event_type)
        if not record:
            continue
        status = str(record.get("status", "not_observed"))
        if status == "observed":
            observed_events.append(event_type)
        elif status == "blocked":
            blocked_events.append(event_type)
        elif status == "failed":
            failed_events.append(event_type)
        elif status == "not_observed":
            not_observed_events.append(event_type)

    missing_events = [event_type for event_type in RUNTIME_OBSERVATION_EVENTS if event_type not in latest_by_event]
    unsatisfied_events = [*not_observed_events, *missing_events]
    if failed_events:
        next_action = f"surface_runtime_failure:{failed_events[-1]}"
    elif blocked_events:
        next_action = f"surface_runtime_blocker:{blocked_events[-1]}"
    elif unsatisfied_events:
        next_action = f"record_runtime_observation:{unsatisfied_events[0]}"
    else:
        next_action = "report_runtime_observed"

    return {
        "schema_version": "runtime_observation_status/v1",
        "record_schema": RUNTIME_OBSERVATION_SCHEMA_VERSION,
        "applicable": True,
        "observed_events": observed_events,
        "blocked_events": blocked_events,
        "failed_events": failed_events,
        "not_observed_events": not_observed_events,
        "missing_events": missing_events,
        "unsatisfied_events": unsatisfied_events,
        "latest": latest_by_event,
        "next_action": next_action,
        "claim_boundary": (
            "Runtime observation status is computed only from runtime_observation/v1 records. "
            "Missing ladder steps remain unobserved."
        ),
    }


def _runtime_observation_sort_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("updated_at", "")),
        str(record.get("target_type", "")),
        str(record.get("target_id", "")),
        str(record.get("event_type", "")),
    )


def runtime_observation_not_applicable(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "runtime_observation_status/v1",
        "record_schema": RUNTIME_OBSERVATION_SCHEMA_VERSION,
        "applicable": False,
        "observed_events": [],
        "blocked_events": [],
        "failed_events": [],
        "not_observed_events": [],
        "missing_events": [],
        "unsatisfied_events": [],
        "latest": {},
        "next_action": "not_applicable",
        "reason": reason,
        "claim_boundary": "Runtime observation status applies only to prepared runtime handoff sessions or explicit runtime records.",
    }


def validate_runtime_observations_for_wrapper_session(
    observations_path: Path,
    session: dict[str, Any],
    observations: list[dict[str, Any]],
) -> list[str]:
    expected_profile = _expected_runtime_profile_for_session(session)
    return _validate_runtime_observations_against_expected(
        observations_path,
        observations,
        expected_profile,
        expected_target_type="wrapper_session",
        expected_target_id=observations_path.parent.name,
        missing_message="runtime observations require a runtime_handoff_prepared wrapper session",
    )


def _validate_runtime_observations_for_run(
    observations_path: Path,
    run: dict[str, Any],
    coding: dict[str, Any] | None,
    observations: list[dict[str, Any]],
) -> list[str]:
    expected_profile = _expected_runtime_profile_for_run(run, coding)
    return _validate_runtime_observations_against_expected(
        observations_path,
        observations,
        expected_profile,
        expected_target_type="run",
        expected_target_id=observations_path.parent.name,
        missing_message="runtime observations are not valid for a non-runtime coding delegation run",
    )


def _validate_runtime_observations_against_expected(
    observations_path: Path,
    observations: list[dict[str, Any]],
    expected_profile: str | None,
    *,
    expected_target_type: str,
    expected_target_id: str,
    missing_message: str,
) -> list[str]:
    if not observations:
        return []
    errors: list[str] = []
    for index, observation in enumerate(observations, start=1):
        target_type = str(observation.get("target_type", ""))
        if target_type != expected_target_type:
            errors.append(
                f"{observations_path}:{index}: target_type must match containing target "
                f"{expected_target_type!r}, got {target_type!r}"
            )
        target_id = str(observation.get("target_id", ""))
        if target_id != expected_target_id:
            errors.append(
                f"{observations_path}:{index}: target_id must match containing target "
                f"{expected_target_id!r}, got {target_id!r}"
            )
    if expected_profile is None:
        return [*errors, f"{observations_path}: {missing_message}"]
    if not expected_profile:
        return [*errors, f"{observations_path}: {missing_message}"]
    for index, observation in enumerate(observations, start=1):
        runtime_profile = str(observation.get("runtime_profile", ""))
        if runtime_profile != expected_profile:
            errors.append(
                f"{observations_path}:{index}: runtime_profile must match prepared runtime handoff "
                f"{expected_profile!r}, got {runtime_profile!r}"
            )
    return errors


def _expected_runtime_profile_for_session(session: dict[str, Any]) -> str:
    if session.get("status") != "runtime_handoff_prepared" or session.get("work_owner_mode") != "runtime_handoff":
        return ""
    return _runtime_profile_from_handoff(session.get("runtime_handoff")) or str(session.get("selected_executor_profile") or "")


def _expected_runtime_profile_for_run(run: dict[str, Any], coding: dict[str, Any] | None) -> str | None:
    if not isinstance(coding, dict):
        return None
    if coding.get("work_owner_mode") == "runtime_handoff":
        return _runtime_profile_from_handoff(coding.get("runtime_handoff")) or str(coding.get("selected_executor_profile") or "")
    if run.get("artifact_kind") == "prepared_coding_delegation":
        return ""
    return None


def _runtime_profile_from_handoff(handoff: object) -> str:
    if not isinstance(handoff, dict):
        return ""
    selected = str(handoff.get("selected_executor_profile") or "")
    runtime_profile = handoff.get("runtime_profile")
    if isinstance(runtime_profile, dict):
        return str(runtime_profile.get("profile") or selected)
    return selected


def _delegated_harness_progress(
    harness_quality: dict[str, Any],
    *,
    prepared: bool,
    prompt_dispatched: bool,
    execution_observed: bool,
    execution_status: str,
    verification_observed: bool,
    review_status: dict[str, Any],
    ci_status: dict[str, Any],
    merge_status: dict[str, Any],
) -> dict[str, Any]:
    if not harness_quality:
        return {}
    step_states = {
        "coding_delegation_prepared": "complete" if prepared else "pending",
        "executor_dispatch_observed": "complete" if prompt_dispatched else "pending",
        "executor_result_observed": _executor_progress_state(execution_observed, execution_status),
        "verification_recorded": "complete" if verification_observed else "pending",
        "review_ci_merge_recorded_when_required": _downstream_gate_progress_state(review_status, ci_status, merge_status),
    }
    return build_harness_progress(harness_quality, step_states)


def _executor_progress_state(observed: bool, status: str) -> str:
    if not observed:
        return "pending"
    if status in {"blocked", "failed"}:
        return "blocked"
    return "complete"


def _downstream_gate_progress_state(
    review_status: dict[str, Any],
    ci_status: dict[str, Any],
    merge_status: dict[str, Any],
) -> str:
    for status in (review_status, ci_status, merge_status):
        if status.get("status") in {"blocked", "failed"}:
            return "blocked"
    downstream_required = bool(review_status.get("required")) or bool(ci_status.get("required")) or bool(merge_status.get("required"))
    if not downstream_required:
        return "not_required"
    if review_status.get("satisfied") and ci_status.get("satisfied") and merge_status.get("satisfied"):
        return "complete"
    return "pending"


def _verification_status_summary(*, observed: bool, completion_status: str, unobserved_gaps: Any) -> dict[str, Any]:
    gaps = _string_list(unobserved_gaps)
    if observed:
        status = "passed"
    elif completion_status == "failed":
        status = "failed"
    elif completion_status == "blocked" or gaps:
        status = "blocked"
    else:
        status = "not_observed"
    return {"status": status, "satisfied": observed}


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _handoff_contract_summary(handoff: dict[str, Any]) -> dict[str, Any]:
    if not handoff:
        return {}
    summary: dict[str, Any] = {
        "schema_version": handoff.get("schema_version", ""),
        "selected_executor_profile": handoff.get("selected_executor_profile", handoff.get("executor_target", "")),
        "execution_brief": _object_or_empty(handoff.get("execution_brief")),
        "runtime_brief": _object_or_empty(handoff.get("runtime_brief")),
        "isolation_plan": _isolation_plan_summary(_object_or_empty(handoff.get("isolation_plan"))),
        "report_contract": _object_or_empty(handoff.get("report_contract")),
        "evidence_contract": _object_or_empty(handoff.get("evidence_contract")),
        "acceptance_criteria": _string_list(handoff.get("acceptance_criteria")),
        "verification": _string_list(handoff.get("verification")),
    }
    context_pack = _object_or_empty(handoff.get("context_pack"))
    if context_pack:
        summary["context_pack"] = _context_pack_summary(context_pack)
    context_pack_blocked = _object_or_empty(handoff.get("context_pack_blocked"))
    if context_pack_blocked:
        summary["context_pack_blocked"] = _context_pack_blocked_summary(context_pack_blocked)
    return summary


def _context_pack_summary(context_pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": context_pack.get("schema_version", ""),
        "executor_target": context_pack.get("executor_target", ""),
        "session_id": context_pack.get("session_id", ""),
        "source_ref_count": len(_list_or_empty(context_pack.get("source_refs"))),
        "included_context_count": len(_list_or_empty(context_pack.get("included_context"))),
        "excluded_context_count": len(_list_or_empty(context_pack.get("excluded_context"))),
        "blocked_by_conflicts_count": len(_list_or_empty(context_pack.get("blocked_by_conflicts"))),
        "redaction_policy": context_pack.get("redaction_policy", ""),
        "claim_boundary": context_pack.get("claim_boundary", ""),
    }


def _isolation_plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    if not plan:
        return {}
    return {
        "schema_version": plan.get("schema_version", ""),
        "status": plan.get("status", ""),
        "strategy": plan.get("strategy", ""),
        "risk_level": plan.get("risk_level", ""),
        "workspace_policy": plan.get("workspace_policy", ""),
        "required_before": [str(item) for item in plan.get("required_before", []) if str(item)]
        if isinstance(plan.get("required_before"), list)
        else [],
        "wrapper_actions": [str(item) for item in plan.get("wrapper_actions", []) if str(item)]
        if isinstance(plan.get("wrapper_actions"), list)
        else [],
        "claim_boundary": plan.get("claim_boundary", ""),
    }


def _context_pack_blocked_summary(context_pack_blocked: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": context_pack_blocked.get("schema_version", ""),
        "blocked_by_conflicts_count": len(_list_or_empty(context_pack_blocked.get("blocked_by_conflicts"))),
        "claim_boundary": context_pack_blocked.get("claim_boundary", ""),
    }


def _list_or_empty(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _review_status_summary(
    required: bool,
    workflow: Any,
    handoff_review: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    if record:
        status = str(record.get("status", "not_observed"))
        observed = bool(record.get("observed", False))
        required = required or bool(record.get("required", required))
        return {
            "required": required,
            "observed": observed,
            "status": status,
            "satisfied": observed and (status == "passed" or (status == "not_required" and not required)),
            "reviewer": record.get("reviewer", ""),
            "evidence_refs": record.get("evidence_refs", []),
            "summary": record.get("summary", ""),
        }
    status = "not_observed" if required else "not_required"
    return {
        "required": required,
        "observed": not required,
        "status": status,
        "satisfied": not required,
        "reviewer": "",
        "evidence_refs": [],
        "summary": "",
    }


def _ci_status_summary(required: bool, record: dict[str, Any]) -> dict[str, Any]:
    if record:
        status = str(record.get("status", "not_observed"))
        observed = bool(record.get("observed", False))
        checks = record.get("checks", [])
        checks_passed = bool(checks) and all(isinstance(check, dict) and check.get("status") == "passed" for check in checks)
        checks_not_required = all(isinstance(check, dict) and check.get("status") == "not_required" for check in checks)
        required = required or bool(record.get("required", required))
        return {
            "required": required,
            "observed": observed,
            "status": status,
            "satisfied": observed and ((status == "not_required" and not required and checks_not_required) or (status == "passed" and checks_passed)),
            "provider": record.get("provider", ""),
            "checks": checks,
            "evidence_refs": record.get("evidence_refs", []),
            "summary": record.get("summary", ""),
        }
    status = "not_observed" if required else "not_required"
    return {
        "required": required,
        "observed": not required,
        "status": status,
        "satisfied": not required,
        "provider": "",
        "checks": [],
        "evidence_refs": [],
        "summary": "",
    }


def _merge_status_summary(required: bool, record: dict[str, Any]) -> dict[str, Any]:
    if record:
        status = str(record.get("status", "not_observed"))
        observed = bool(record.get("observed", False))
        ready = bool(record.get("ready", False))
        merged = bool(record.get("merged", False))
        merge_commit = str(record.get("merge_commit", ""))
        evidence_refs = record.get("evidence_refs", [])
        has_merge_evidence = bool(merge_commit) or bool(evidence_refs)
        return {
            "required": bool(record.get("required", required)),
            "observed": observed,
            "ready": ready,
            "merged": merged,
            "status": status,
            "satisfied": observed
            and (
                (status == "ready" and ready and not merged)
                or (status == "merged" and ready and merged and has_merge_evidence)
            ),
            "target_branch": record.get("target_branch", ""),
            "merge_commit": merge_commit,
            "evidence_refs": evidence_refs,
            "summary": record.get("summary", ""),
        }
    return {
        "required": required,
        "observed": not required,
        "ready": False,
        "merged": False,
        "status": "not_observed" if required else "not_required",
        "satisfied": not required,
        "target_branch": "",
        "merge_commit": "",
        "evidence_refs": [],
        "summary": "",
    }


def _apply_lifecycle_review_status(status: dict[str, Any], lifecycle: dict[str, Any]) -> dict[str, Any]:
    if not lifecycle.get("review_observed") or status.get("observed"):
        return status
    return {
        **status,
        "observed": True,
        "status": "passed",
        "satisfied": True,
        "summary": str(_object_or_empty(lifecycle.get("latest_event")).get("summary") or status.get("summary", "")),
    }


def _apply_lifecycle_ci_status(
    status: dict[str, Any],
    lifecycle: dict[str, Any],
    review_status: dict[str, Any],
) -> dict[str, Any]:
    if not lifecycle.get("ci_observed") or status.get("observed"):
        return status
    return {
        **status,
        "required": bool(status.get("required")) or review_status.get("status") == "passed",
        "observed": True,
        "status": "passed",
        "satisfied": True,
        "summary": str(_object_or_empty(lifecycle.get("latest_event")).get("summary") or status.get("summary", "")),
    }


def _apply_lifecycle_merge_status(status: dict[str, Any], lifecycle: dict[str, Any]) -> dict[str, Any]:
    if status.get("observed"):
        return status
    latest = _object_or_empty(lifecycle.get("latest_event"))
    if lifecycle.get("merge_observed"):
        return {
            **status,
            "required": True,
            "observed": True,
            "ready": True,
            "merged": True,
            "status": "merged",
            "satisfied": True,
            "summary": str(latest.get("summary") or status.get("summary", "")),
        }
    if lifecycle.get("merge_gate_observed"):
        return {
            **status,
            "required": True,
            "observed": True,
            "ready": True,
            "merged": False,
            "status": "ready",
            "satisfied": True,
            "summary": str(latest.get("summary") or status.get("summary", "")),
        }
    return status


def _delegated_runtime_observation_status(
    legacy_status: dict[str, Any],
    lifecycle: dict[str, Any],
    *,
    next_action: str,
) -> dict[str, Any]:
    if int(lifecycle.get("journal_event_count", 0) or 0) <= 0:
        return legacy_status
    observed_events = _runtime_events_from_lifecycle(lifecycle)
    latest = _object_or_empty(lifecycle.get("latest_event"))
    blocked_events = []
    failed_events = []
    latest_event = _runtime_event_from_journal_event(str(latest.get("event", "")))
    latest_status = str(latest.get("status", ""))
    if latest_event and latest_status == "blocked":
        blocked_events.append(latest_event)
    elif latest_event and latest_status == "failed":
        failed_events.append(latest_event)
    missing_events = _runtime_missing_events_for_next_action(next_action)
    return {
        "schema_version": "runtime_observation_status/v1",
        "record_schema": RUNTIME_OBSERVATION_SCHEMA_VERSION,
        "applicable": True,
        "source": "lifecycle_projection",
        "observed_events": observed_events,
        "blocked_events": blocked_events,
        "failed_events": failed_events,
        "not_observed_events": [],
        "missing_events": missing_events,
        "unsatisfied_events": missing_events,
        "latest": {"event": latest_event, **latest} if latest_event else latest,
        "next_action": next_action,
        "claim_boundary": (
            "Runtime observation status is projected from the merged lifecycle journal for prepared Codex runs. "
            "It remains metadata-only evidence."
        ),
    }


def _runtime_events_from_lifecycle(lifecycle: dict[str, Any]) -> list[str]:
    events: list[str] = []
    for lifecycle_key, event_type in (
        ("runtime_start_observed", "runtime_start"),
        ("worktree_observed", "worktree_creation"),
        ("prompt_dispatched", "worker_dispatch"),
        ("execution_observed", "worker_result"),
        ("verification_observed", "verification"),
        ("review_observed", "review"),
        ("ci_observed", "ci"),
        ("merge_gate_observed", "merge_readiness"),
        ("merge_observed", "merge"),
    ):
        if lifecycle.get(lifecycle_key):
            events.append(event_type)
    return events


def _runtime_missing_events_for_next_action(next_action: str) -> list[str]:
    return {
        "dispatch_to_executor": ["worker_dispatch"],
        "wait_for_executor_evidence": ["worker_result"],
        "record_verification_evidence": ["verification"],
        "record_review_evidence": ["review"],
        "record_ci_evidence": ["ci"],
        "record_merge_readiness": ["merge_readiness"],
    }.get(next_action, [])


def _runtime_event_from_journal_event(event_name: str) -> str:
    return {
        "runtime_start_observed": "runtime_start",
        "worktree_creation_observed": "worktree_creation",
        "executor_dispatch_observed": "worker_dispatch",
        "executor_result_observed": "worker_result",
        "verification_result_observed": "verification",
        "review_result_observed": "review",
        "ci_result_observed": "ci",
        "merge_gate_observed": "merge_readiness",
        "merge_observed": "merge",
    }.get(event_name, "")


def _delegated_status_next_action(
    *,
    prepared: bool,
    action: str,
    prompt_dispatched: bool,
    execution_observed: bool,
    execution_status: str,
    verification_observed: bool,
    review_status: dict[str, Any],
    ci_status: dict[str, Any],
    merge_status: dict[str, Any],
) -> str:
    if not prepared:
        return "prepare_coding_delegation"
    if action == "clarify":
        return "clarify_coding_request"
    if action == "fallback":
        return "route_coding_request"
    if action != "delegate":
        return "prepare_coding_delegation"
    if not prompt_dispatched:
        return "dispatch_to_executor"
    if not execution_observed:
        return "wait_for_executor_evidence"
    if execution_status in {"blocked", "failed"}:
        return "surface_executor_blocker"
    if not verification_observed:
        return "record_verification_evidence"
    if not review_status["satisfied"]:
        if review_status["status"] in {"failed", "blocked"}:
            return "surface_review_blocker"
        return "record_review_evidence"
    if not ci_status["satisfied"]:
        if ci_status["status"] in {"failed", "blocked"}:
            return "surface_ci_blocker"
        return "record_ci_evidence"
    if merge_status["status"] == "blocked":
        return "surface_merge_blocker"
    if merge_status["status"] == "merged" and merge_status["satisfied"]:
        return "report_merged"
    if merge_status["status"] == "ready" and merge_status["satisfied"]:
        return "report_merge_ready"
    if merge_status["required"]:
        return "record_merge_readiness"
    return "report_completion_with_evidence"


def _delegated_status_summary(
    *,
    prepared: bool,
    action: str,
    executor_target: str,
    prompt_dispatched: bool,
    execution_observed: bool,
    execution_status: str,
    verification_observed: bool,
    review_status: dict[str, Any],
    ci_status: dict[str, Any],
    merge_status: dict[str, Any],
) -> str:
    if not prepared:
        return "No prepared coding delegation was found for this run."
    if action == "clarify":
        return "The coding request needs clarification before executor/runtime dispatch."
    if action == "fallback":
        return "The coding request fell back to the router; do not dispatch it to an executor yet."
    if action != "delegate":
        return "The coding delegation is not dispatchable yet."
    if not prompt_dispatched:
        return f"A {executor_target} coding handoff is prepared, but wrapper dispatch is not observed yet."
    if not execution_observed:
        return f"A {executor_target} coding handoff was dispatched, but executor completion is not observed yet."
    if execution_status in {"blocked", "failed"}:
        return f"The {executor_target} executor reported {execution_status}; do not claim completion."
    if not verification_observed:
        return f"The {executor_target} executor is observed as {execution_status}, but verification evidence is not observed yet."
    if not review_status["satisfied"]:
        if review_status["status"] in {"failed", "blocked"}:
            return f"The {executor_target} executor is observed as {execution_status}, but review is {review_status['status']}."
        return f"The {executor_target} executor is observed as {execution_status}, but review evidence is still required."
    if not ci_status["satisfied"]:
        if ci_status["status"] in {"failed", "blocked"}:
            return f"The {executor_target} executor is reviewed, but CI is {ci_status['status']}."
        return f"The {executor_target} executor is reviewed, but CI evidence is still required."
    if merge_status["status"] == "blocked":
        return f"The {executor_target} executor is reviewed and CI passed, but merge is blocked."
    if merge_status["status"] == "merged" and merge_status["satisfied"]:
        return f"The {executor_target} executor is reviewed, CI passed, and merge evidence is observed."
    if merge_status["status"] == "ready" and merge_status["satisfied"]:
        return f"The {executor_target} executor is reviewed, CI passed, and the run is ready to merge."
    if merge_status["required"]:
        return f"The {executor_target} executor is reviewed and CI passed, but merge readiness is not observed yet."
    return f"The {executor_target} executor is observed as {execution_status} with wrapper verification evidence."


def _delegated_status_integrity_warnings(
    *,
    run: dict[str, Any],
    coding: dict[str, Any],
    delegation: dict[str, Any],
    wrapper: dict[str, Any],
    handoff: dict[str, Any],
    prepared: bool,
    action: str,
) -> list[str]:
    warnings: list[str] = []
    artifact_kind = run.get("artifact_kind")
    if artifact_kind == "prepared_coding_delegation" and not coding:
        warnings.append("prepared_coding_delegation run is missing coding_delegation.json")
    if coding and artifact_kind != "prepared_coding_delegation":
        warnings.append("coding_delegation.json exists but run artifact_kind is not prepared_coding_delegation")
    if prepared and run.get("observation_status") != "prepared_not_observed":
        warnings.append("prepared coding delegation run has unexpected observation_status")
    if action != "delegate" and handoff:
        warnings.append("non-delegate coding action must not include executor_handoff")
    if action == "delegate" and handoff and handoff.get("status") != "prepared_not_observed":
        warnings.append("executor_handoff has unexpected status")
    if wrapper and wrapper.get("completion_status") == "completed" and not wrapper.get("prompt_dispatched"):
        warnings.append("wrapper reports completed without prompt_dispatched")
    if delegation.get("observed") and not wrapper.get("prompt_dispatched", False):
        warnings.append("delegation is observed but wrapper dispatch is not observed")
    return warnings


def validate_run_dir(run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    coding_for_observation: dict[str, Any] | None = None
    run_path = run_dir / "run.json"
    try:
        run = read_json_object(run_path)
    except (OSError, JSONDecodeError, ValueError) as exc:
        run = None
        errors.append(f"{run_path}: {exc}")
    if not run:
        errors.append(f"{run_path}: missing run.json")
    else:
        errors.extend(f"{run_path}: {error}" for error in validate_run_record(run))
        coding_delegation_path = run_dir / "coding_delegation.json"
        if run.get("artifact_kind") == "prepared_coding_delegation" and not coding_delegation_path.exists():
            errors.append(f"{coding_delegation_path}: missing coding_delegation.json for prepared_coding_delegation run")
        if run.get("artifact_kind") == "prepared_coding_delegation" and coding_delegation_path.exists():
            try:
                coding = read_json_object(coding_delegation_path)
            except (OSError, JSONDecodeError, ValueError) as exc:
                coding = None
                errors.append(f"{coding_delegation_path}: {exc}")
            if isinstance(coding, dict):
                coding_for_observation = coding
                selection = coding.get("executor_selection")
                choice_required = isinstance(selection, dict) and selection.get("choice_required") is True
                if choice_required:
                    errors.append(f"{coding_delegation_path}: executor choice must not be stored as a prepared runtime run")
                if coding.get("work_owner_mode") == "prompt_only_handoff":
                    errors.append(f"{coding_delegation_path}: prompt-only handoff must not be stored as a prepared runtime run")
                if coding.get("work_owner_mode") == "runtime_handoff":
                    errors.append(f"{coding_delegation_path}: runtime handoff must not be stored as a prepared runtime run")
                if (
                    coding.get("work_owner_mode") != "external_executor"
                    or coding.get("selected_executor_profile") != "codex"
                    or not isinstance(coding.get("executor_handoff"), dict)
                ):
                    errors.append(f"{coding_delegation_path}: prepared runtime run requires a Codex executor_handoff")
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        events, event_errors = read_jsonl_objects(events_path)
        errors.extend(event_errors)
        for index, event in enumerate(events, start=1):
            errors.extend(f"{events_path}:{index}: {error}" for error in validate_event_record(event))
    else:
        errors.append(f"{events_path}: missing events.jsonl")
    observations_path = run_dir / "runtime_observations.jsonl"
    if observations_path.exists():
        observations, observation_errors = read_runtime_observations_result(run_dir)
        errors.extend(observation_errors)
        for index, observation in enumerate(observations, start=1):
            errors.extend(
                f"{observations_path}:{index}: {error}"
                for error in validate_runtime_observation_record(observation)
            )
        if isinstance(run, dict):
            if coding_for_observation is None and (run_dir / "coding_delegation.json").exists():
                try:
                    coding = read_json_object(run_dir / "coding_delegation.json")
                except (OSError, JSONDecodeError, ValueError):
                    coding = None
                if isinstance(coding, dict):
                    coding_for_observation = coding
            errors.extend(
                _validate_runtime_observations_for_run(
                    observations_path,
                    run,
                    coding_for_observation,
                    observations,
                )
            )
    for name, validator in OPTIONAL_RECORD_VALIDATORS:
        path = run_dir / name
        if not path.exists():
            continue
        try:
            record = read_json_object(path)
        except (OSError, JSONDecodeError, ValueError) as exc:
            record = None
            errors.append(f"{path}: {exc}")
        if record:
            errors.extend(f"{path}: {error}" for error in validator(record))
    errors.extend(_validate_run_status_gate_consistency(run_dir))
    return {"run_id": run_dir.name, "ok": not errors, "errors": errors}


def _validate_run_status_gate_consistency(run_dir: Path) -> list[str]:
    errors: list[str] = []
    run = _object_or_empty(read_json_object(run_dir / "run.json"))
    coding = _object_or_empty(read_json_object(run_dir / "coding_delegation.json"))
    delegation = _object_or_empty(read_json_object(run_dir / "delegation.json"))
    wrapper = _object_or_empty(read_json_object(run_dir / "wrapper.json"))
    review_record = _object_or_empty(read_json_object(run_dir / "review.json"))
    ci_record = _object_or_empty(read_json_object(run_dir / "ci.json"))
    merge_record = _object_or_empty(read_json_object(run_dir / "merge.json"))
    if not run:
        return errors

    handoff = _object_or_empty(coding.get("executor_handoff"))
    handoff_review = _object_or_empty(handoff.get("review"))
    review_required = bool(handoff_review.get("required", coding.get("review_required", False)))
    review_status = _review_status_summary(review_required, handoff_review.get("workflow"), handoff_review, review_record)
    ci_required_by_ladder = review_status["status"] == "passed"
    ci_required = bool(ci_record) or ci_required_by_ladder
    ci_status = _ci_status_summary(ci_required, ci_record)

    execution_satisfied = bool(delegation.get("observed", False)) and delegation.get("result") == "completed"
    verification_satisfied = bool(wrapper.get("verification_observed", False))
    review_path = run_dir / "review.json"
    ci_path = run_dir / "ci.json"
    merge_path = run_dir / "merge.json"

    if review_required and review_record.get("status") == "not_required":
        errors.append(f"{review_path}: review not_required cannot downgrade required review evidence")
    if ci_required_by_ladder and ci_record.get("status") == "not_required":
        errors.append(f"{ci_path}: ci not_required cannot downgrade required CI evidence")
    if review_record.get("status") == "passed" and not verification_satisfied:
        errors.append(f"{review_path}: review passed requires verification evidence")
    if ci_record.get("status") == "passed":
        if not verification_satisfied:
            errors.append(f"{ci_path}: ci passed requires verification evidence")
        if not review_status["satisfied"]:
            errors.append(f"{ci_path}: ci passed requires review passed or not_required")
    if merge_record.get("status") in {"ready", "merged"}:
        if not execution_satisfied:
            errors.append(f"{merge_path}: merge {merge_record.get('status')} requires completed executor evidence")
        if not verification_satisfied:
            errors.append(f"{merge_path}: merge {merge_record.get('status')} requires verification evidence")
        if not review_status["satisfied"]:
            errors.append(f"{merge_path}: merge {merge_record.get('status')} requires review passed or not_required")
        if not ci_status["satisfied"]:
            errors.append(f"{merge_path}: merge {merge_record.get('status')} requires CI passed or not_required")
    return errors


def validate_runtime(paths: OmhPaths, run_id: str | None = None) -> dict[str, Any]:
    if run_id:
        run_dirs = [paths.runtime_runs_dir / run_id]
        session_dirs = _wrapper_session_dirs_for_run(paths, run_id)
    else:
        run_dirs = sorted(path for path in paths.runtime_runs_dir.glob("*") if path.is_dir()) if paths.runtime_runs_dir.exists() else []
        session_dirs = (
            sorted(path for path in paths.runtime_wrapper_sessions_dir.glob("*") if path.is_dir())
            if paths.runtime_wrapper_sessions_dir.exists()
            else []
        )
    results = [validate_run_dir(run_dir) for run_dir in run_dirs]
    session_results = [validate_wrapper_session_dir(session_dir) for session_dir in session_dirs]
    journal_result = validate_observation_journal(paths, run_id=run_id)
    _add_duplicate_wrapper_run_link_errors(session_results, session_dirs)
    return {
        "ok": all(result["ok"] for result in results)
        and all(result["ok"] for result in session_results)
        and bool(journal_result["ok"]),
        "runs": results,
        "wrapper_sessions": session_results,
        "journal": journal_result,
    }


def _wrapper_session_dirs_for_run(paths: OmhPaths, run_id: str) -> list[Path]:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return []
    session_dirs: list[Path] = []
    for session_json in sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json")):
        session = read_json_object(session_json)
        if session and session.get("current_run_id") == run_id:
            session_dirs.append(session_json.parent)
    return session_dirs


def _add_duplicate_wrapper_run_link_errors(session_results: list[dict[str, Any]], session_dirs: list[Path]) -> None:
    owners_by_run_id: dict[str, list[str]] = {}
    for session_dir in session_dirs:
        session = read_json_object(session_dir / "session.json")
        if not session:
            continue
        run_id = str(session.get("current_run_id", ""))
        if run_id:
            owners_by_run_id.setdefault(run_id, []).append(session_dir.name)
    duplicate_errors = {
        run_id: f"current_run_id {run_id} is linked by multiple wrapper sessions: {', '.join(sorted(session_ids))}"
        for run_id, session_ids in owners_by_run_id.items()
        if len(session_ids) > 1
    }
    if not duplicate_errors:
        return
    results_by_session_id = {str(result.get("session_id")): result for result in session_results}
    for session_dir in session_dirs:
        session = read_json_object(session_dir / "session.json")
        if not session:
            continue
        run_id = str(session.get("current_run_id", ""))
        if run_id not in duplicate_errors:
            continue
        result = results_by_session_id.get(session_dir.name)
        if not result:
            continue
        result.setdefault("errors", []).append(f"{session_dir / 'session.json'}: {duplicate_errors[run_id]}")
        result["ok"] = False


SENSITIVE_KEY_PARTS = ("secret", "token", "api_key", "apikey", "password")
SENSITIVE_TEXT_KEY_PARTS = ("prompt", "response", "summary")
SENSITIVE_TEXT_KEYS = (
    "message",
    "raw_message",
    "task_statement",
    "external_session_ref",
    "summary",
    "correlation_root",
    "process",
    "delivery",
    "process_session_id",
    "pid",
    "worktree",
    "branch",
    "source",
    "channel_ref",
    "thread_ref",
    "delivery_target",
)
SENSITIVE_LIST_KEYS = ("evidence_refs", "observed_evidence_refs", "correlation_aliases")
EVIDENCE_KEYS_TO_PRESERVE = ("prompt_dispatched", "hermes_response_observed", "verification_observed")


def _should_redact_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in EVIDENCE_KEYS_TO_PRESERVE:
        return False
    if lowered in SENSITIVE_LIST_KEYS:
        return True
    if lowered in SENSITIVE_TEXT_KEYS:
        return True
    return any(part in lowered for part in SENSITIVE_KEY_PARTS + SENSITIVE_TEXT_KEY_PARTS)


def _redacted_value(key: str, value: Any) -> Any:
    if key.lower() in SENSITIVE_LIST_KEYS and isinstance(value, list):
        return ["[redacted]"] if value else []
    return "[redacted]"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _should_redact_key(str(key)):
                redacted[key] = _redacted_value(str(key), item)
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def export_runtime(
    paths: OmhPaths,
    redacted: bool = True,
    *,
    limit: int | None = None,
    full: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    runs = [read_json_object(paths.runtime_runs_dir / run_id / "run.json")] if run_id else list_runs(paths, limit=limit)
    runs = [run for run in runs if isinstance(run, dict)]
    if run_id:
        wrapper_sessions = _wrapper_session_records_for_run(paths, run_id, limit=limit)
    else:
        wrapper_sessions = list_wrapper_session_records(paths, limit=limit)
    journal_events, journal_errors = read_observation_events_result(paths)
    if run_id:
        journal_events = [event for event in journal_events if str(event.get("run_id", "")) == run_id]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "runtime_dir": str(paths.runtime_dir),
        "state": read_state(paths),
        "export": {
            "full": full,
            "limit": limit,
            "run_id": run_id or "",
            "run_count": len(runs),
            "wrapper_session_count": len(wrapper_sessions),
            "journal_event_count": len(journal_events),
        },
        "runs": [show_run(paths, run["run_id"]) for run in runs] if full else runs,
        "wrapper_sessions": (
            [show_wrapper_session_record(paths, session["session_id"]) for session in wrapper_sessions] if full else wrapper_sessions
        ),
        "journal": {
            "path": str(paths.runtime_journal_events_path),
            "events": journal_events if full else [],
            "errors": journal_errors,
        },
    }
    if redacted:
        payload = _redact(payload)
        payload["redacted"] = True
    else:
        payload["redacted"] = False
    return payload


def _wrapper_session_records_for_run(paths: OmhPaths, run_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for session_dir in _wrapper_session_dirs_for_run(paths, run_id):
        session = read_json_object(session_dir / "session.json")
        if isinstance(session, dict):
            sessions.append(session)
    return _apply_limit(sessions, limit)


def _read_jsonl_events(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl_events_result(path)[0]


def _read_jsonl_events_result(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    return read_jsonl_objects(path)


def validate_wrapper_session_dir(session_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    session_path = session_dir / "session.json"
    events: list[dict[str, Any]] = []
    try:
        session = read_json_object(session_path)
    except (OSError, JSONDecodeError, ValueError) as exc:
        session = None
        errors.append(f"{session_path}: {exc}")
    if not session:
        errors.append(f"{session_path}: missing session.json")
    else:
        errors.extend(f"{session_path}: {error}" for error in validate_wrapper_session_record(session))
        if session.get("session_id") != session_dir.name:
            errors.append(f"{session_path}: session_id must match directory name")
    events_path = session_dir / "events.jsonl"
    if events_path.exists():
        events, event_errors = read_jsonl_objects(events_path)
        errors.extend(event_errors)
        for index, event in enumerate(events, start=1):
            errors.extend(f"{events_path}:{index}: {error}" for error in validate_event_record(event))
    else:
        errors.append(f"{events_path}: missing events.jsonl")
    observations_path = session_dir / "runtime_observations.jsonl"
    if observations_path.exists():
        observations, observation_errors = read_runtime_observations_result(session_dir)
        errors.extend(observation_errors)
        for index, observation in enumerate(observations, start=1):
            errors.extend(
                f"{observations_path}:{index}: {error}"
                for error in validate_runtime_observation_record(observation)
            )
        if session:
            errors.extend(validate_runtime_observations_for_wrapper_session(observations_path, session, observations))
    if session:
        errors.extend(_validate_wrapper_session_run_link(session_dir, session, events))
    return {"session_id": session_dir.name, "ok": not errors, "errors": errors}


def _validate_wrapper_session_run_link(session_dir: Path, session: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    run_id = str(session.get("current_run_id", ""))
    if not run_id:
        return errors
    session_path = session_dir / "session.json"
    run_dir = session_dir.parents[1] / "runs" / run_id
    run_path = run_dir / "run.json"
    coding_path = run_dir / "coding_delegation.json"
    run = read_json_object(run_path)
    if not run:
        return [f"{session_path}: current_run_id does not point to an existing runtime run"]
    errors.extend(f"{run_path}: {error}" for error in validate_run_record(run))
    if run.get("artifact_kind") != "prepared_coding_delegation":
        errors.append(f"{session_path}: current_run_id must point to a prepared coding delegation run")
    if run.get("phase") != "prepared" or run.get("observation_status") != "prepared_not_observed":
        errors.append(f"{session_path}: linked run must preserve prepared_not_observed boundary")
    coding = read_json_object(coding_path)
    if not coding:
        errors.append(f"{session_path}: linked run is missing coding_delegation.json")
    else:
        errors.extend(f"{coding_path}: {error}" for error in validate_coding_delegation_record(coding))
        handoff = coding.get("executor_handoff") if isinstance(coding, dict) else None
        if not isinstance(handoff, dict) or handoff.get("executor_target") != "codex":
            errors.append(f"{session_path}: linked run must include a Codex executor handoff")
        if isinstance(coding, dict) and coding.get("status") != "prepared_not_observed":
            errors.append(f"{session_path}: linked coding delegation must be prepared_not_observed")
    has_link_event = any(
        event.get("event") == "handoff_prepared" and isinstance(event.get("data"), dict) and event["data"].get("run_id") == run_id
        for event in events
    )
    if not has_link_event:
        errors.append(f"{session_path}: current_run_id must be recorded by a handoff_prepared session event")
    return errors
