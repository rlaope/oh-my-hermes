from __future__ import annotations

import json
import re
import secrets
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json, ensure_dir, ensure_file, read_json_object, read_json_object_result, utc_now
from ..paths import OmhPaths
from .records import (
    DELEGATION_RESULTS,
    EVENT_LEVELS,
    OBSERVED_RESULTS,
    OPTIONAL_RECORD_VALIDATORS,
    PRIVACY_MODES,
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
    return create_run(paths, prepared_metadata)


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


def list_runs(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.runtime_runs_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_json in sorted(paths.runtime_runs_dir.glob("*/run.json")):
        run = read_json_object(run_json)
        if run:
            runs.append(run)
    return runs


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def show_run(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    run_dir = paths.runtime_runs_dir / run_id
    run = read_json_object(run_dir / "run.json")
    if not run:
        raise FileNotFoundError(run_id)
    evidence_dir = run_dir / "evidence"
    return {
        "run": run,
        "events": read_events(run_dir),
        "routing": read_json_object(run_dir / "routing.json"),
        "coding_delegation": read_json_object(run_dir / "coding_delegation.json"),
        "delegation": read_json_object(run_dir / "delegation.json"),
        "wrapper": read_json_object(run_dir / "wrapper.json"),
        "review": read_json_object(run_dir / "review.json"),
        "ci": read_json_object(run_dir / "ci.json"),
        "merge": read_json_object(run_dir / "merge.json"),
        "evidence": sorted(path.name for path in evidence_dir.iterdir()) if evidence_dir.exists() else [],
    }


def list_wrapper_session_records(paths: OmhPaths) -> list[dict[str, Any]]:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for session_json in sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json")):
        session = read_json_object(session_json)
        if session:
            sessions.append(session)
    return sessions


def show_wrapper_session_record(paths: OmhPaths, session_id: str) -> dict[str, Any]:
    session_dir = paths.runtime_wrapper_sessions_dir / session_id
    session = read_json_object(session_dir / "session.json")
    if not session:
        raise FileNotFoundError(session_id)
    return {
        "session": session,
        "events": _read_jsonl_events(session_dir / "events.jsonl"),
    }


def summarize_delegated_coding_status(paths: OmhPaths, run_id: str) -> dict[str, Any]:
    shown = show_run(paths, run_id)
    run = _object_or_empty(shown.get("run"))
    coding = _object_or_empty(shown.get("coding_delegation"))
    delegation = _object_or_empty(shown.get("delegation"))
    wrapper = _object_or_empty(shown.get("wrapper"))
    review_record = _object_or_empty(shown.get("review"))
    ci_record = _object_or_empty(shown.get("ci"))
    merge_record = _object_or_empty(shown.get("merge"))
    handoff = _object_or_empty(coding.get("executor_handoff"))
    review = _object_or_empty(handoff.get("review"))

    prepared = run.get("artifact_kind") == "prepared_coding_delegation" and bool(coding)
    action = str(coding.get("action", "unknown"))
    handoff_available = bool(handoff)
    executor_target = str(handoff.get("executor_target") or coding.get("executor_profile") or "generic")
    execution_observed = bool(delegation.get("observed", False))
    execution_status = str(delegation.get("result") or ("not_observed" if prepared else "unknown"))
    prompt_dispatched = bool(wrapper.get("prompt_dispatched", False))
    response_observed = bool(wrapper.get("hermes_response_observed", False))
    verification_observed = bool(wrapper.get("verification_observed", False))
    completion_status = str(wrapper.get("completion_status") or "unknown")
    review_required = bool(review.get("required", coding.get("review_required", False)))
    review_workflow = review.get("workflow") if review else coding.get("review_workflow")
    review_status = _review_status_summary(review_required, review_workflow, review, review_record)
    ci_required = bool(ci_record) or review_status["status"] == "passed"
    ci_status = _ci_status_summary(ci_required, ci_record)
    merge_required = bool(merge_record) or ci_status["status"] == "passed"
    merge_status = _merge_status_summary(merge_required, merge_record)

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
        "next_action": next_action,
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


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
        return "The coding request needs clarification before executor dispatch."
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
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        try:
            for index, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict):
                    errors.append(f"{events_path}:{index}: event must be an object")
                    continue
                errors.extend(f"{events_path}:{index}: {error}" for error in validate_event_record(event))
        except (OSError, JSONDecodeError) as exc:
            errors.append(f"{events_path}: {exc}")
    else:
        errors.append(f"{events_path}: missing events.jsonl")
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
    _add_duplicate_wrapper_run_link_errors(session_results, session_dirs)
    return {
        "ok": all(result["ok"] for result in results) and all(result["ok"] for result in session_results),
        "runs": results,
        "wrapper_sessions": session_results,
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
SENSITIVE_TEXT_KEY_PARTS = ("prompt", "response")
SENSITIVE_TEXT_KEYS = ("message", "raw_message", "task_statement")
EVIDENCE_KEYS_TO_PRESERVE = ("prompt_dispatched", "hermes_response_observed", "verification_observed")


def _should_redact_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in EVIDENCE_KEYS_TO_PRESERVE:
        return False
    if lowered in SENSITIVE_TEXT_KEYS:
        return True
    return any(part in lowered for part in SENSITIVE_KEY_PARTS + SENSITIVE_TEXT_KEY_PARTS)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _should_redact_key(str(key)):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def export_runtime(paths: OmhPaths, redacted: bool = True) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "runtime_dir": str(paths.runtime_dir),
        "state": read_state(paths),
        "runs": [show_run(paths, run["run_id"]) for run in list_runs(paths)],
        "wrapper_sessions": [show_wrapper_session_record(paths, session["session_id"]) for session in list_wrapper_session_records(paths)],
    }
    if redacted:
        payload = _redact(payload)
        payload["redacted"] = True
    else:
        payload["redacted"] = False
    return payload


def _read_jsonl_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
        try:
            for index, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                event = json.loads(line)
                if not isinstance(event, dict):
                    errors.append(f"{events_path}:{index}: event must be an object")
                    continue
                events.append(event)
                errors.extend(f"{events_path}:{index}: {error}" for error in validate_event_record(event))
        except (OSError, JSONDecodeError) as exc:
            errors.append(f"{events_path}: {exc}")
    else:
        errors.append(f"{events_path}: missing events.jsonl")
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
