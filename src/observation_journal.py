from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

try:  # pragma: no cover - non-POSIX fallback is exercised only on platforms without fcntl.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from .local_store import ensure_dir, ensure_file, read_jsonl_objects, utc_now
from .paths import OmhPaths


OBSERVATION_EVENT_SCHEMA_VERSION = "omh_observation_event/v1"
LIFECYCLE_PROJECTION_SCHEMA_VERSION = "omh_lifecycle_projection/v1"
OBSERVATION_PRIVACY = "metadata_only"
OBSERVATION_STATUSES = ("observed", "blocked", "failed", "not_observed")
CANONICAL_OBSERVATION_EVENTS = (
    "prepared_handoff_created",
    "plan_artifact_created",
    "plan_accepted",
    "plan_revised",
    "plan_cancelled",
    "runtime_start_observed",
    "worktree_creation_observed",
    "executor_dispatch_observed",
    "executor_result_observed",
    "verification_result_observed",
    "review_result_observed",
    "ci_result_observed",
    "merge_gate_observed",
    "merge_observed",
    "blocked",
    "failed",
    "cancelled",
)
OBSERVATION_EVENT_ALIASES = {
    "coding_handoff_prepared": "prepared_handoff_created",
    "handoff_prepared": "prepared_handoff_created",
    "runtime_start": "runtime_start_observed",
    "worktree_creation": "worktree_creation_observed",
    "worker_dispatch": "executor_dispatch_observed",
    "executor_dispatch": "executor_dispatch_observed",
    "worker_result": "executor_result_observed",
    "executor_result": "executor_result_observed",
    "verification": "verification_result_observed",
    "review": "review_result_observed",
    "ci": "ci_result_observed",
    "merge_readiness": "merge_gate_observed",
    "merge_gate": "merge_gate_observed",
    "merge": "merge_observed",
}
PROJECTION_ORDER = (
    "prepared_not_observed",
    "runtime_start_observed",
    "worktree_creation_observed",
    "dispatch_observed",
    "execution_observed",
    "verification_observed",
    "review_observed",
    "ci_observed",
    "merge_gate_observed",
    "merge_observed",
)


def canonical_observation_event(event: str) -> str:
    value = str(event).strip()
    return OBSERVATION_EVENT_ALIASES.get(value, value)


def build_observation_event(event: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_observation_event(str(event.get("event", "")))
    observed_at = str(event.get("observed_at") or event.get("updated_at") or utc_now())
    evidence_refs = _evidence_refs(event)
    record: dict[str, Any] = {
        "schema_version": OBSERVATION_EVENT_SCHEMA_VERSION,
        "event_id": str(event.get("event_id") or _event_id(observed_at, event)),
        "target_type": str(event.get("target_type") or ("run" if event.get("run_id") else "runtime")),
        "target_id": str(event.get("target_id") or event.get("run_id") or event.get("session_id") or ""),
        "run_id": str(event.get("run_id") or ""),
        "workflow": str(event.get("workflow") or event.get("skill") or ""),
        "harness": str(event.get("harness") or ""),
        "phase": str(event.get("phase") or ""),
        "event": canonical,
        "status": str(event.get("status") or "observed"),
        "observed_at": observed_at,
        "source": str(event.get("source") or ""),
        "actor": str(event.get("actor") or ""),
        "runtime_profile": str(event.get("runtime_profile") or ""),
        "evidence_refs": evidence_refs,
        "summary": _bounded_summary(event.get("summary", "")),
        "privacy": OBSERVATION_PRIVACY,
    }
    for key in ("plan_artifact", "plan_status", "worktree_ref", "worker_ref"):
        if event.get(key):
            record[key] = str(event[key])
    errors = validate_observation_event(record)
    if errors:
        raise ValueError(errors[0])
    return record


def append_observation_event(paths: OmhPaths, event: dict[str, Any]) -> dict[str, Any]:
    record = build_observation_event(event)
    ensure_dir(paths.runtime_journal_dir, private=True)
    ensure_file(paths.runtime_journal_events_path, private=True)
    with paths.runtime_journal_events_path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return record


def read_observation_events_result(paths: OmhPaths) -> tuple[list[dict[str, Any]], list[str]]:
    return read_jsonl_objects(paths.runtime_journal_events_path)


def read_observation_events(
    paths: OmhPaths,
    *,
    run_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    events, _ = read_observation_events_result(paths)
    if run_id is not None:
        events = [event for event in events if str(event.get("run_id", "")) == run_id]
    if target_type is not None:
        events = [event for event in events if str(event.get("target_type", "")) == target_type]
    if target_id is not None:
        events = [event for event in events if str(event.get("target_id", "")) == target_id]
    return _apply_limit(events, limit)


def validate_observation_event(event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if event.get("schema_version") != OBSERVATION_EVENT_SCHEMA_VERSION:
        errors.append(f"observation_event schema_version must be {OBSERVATION_EVENT_SCHEMA_VERSION}")
    for key in ("event_id", "target_type", "target_id", "run_id", "event", "status", "observed_at", "privacy"):
        if not isinstance(event.get(key), str):
            errors.append(f"observation_event {key} must be a string")
    if event.get("event") not in CANONICAL_OBSERVATION_EVENTS:
        errors.append(f"observation_event event is unsupported: {event.get('event')!r}")
    if event.get("status") not in OBSERVATION_STATUSES:
        errors.append(f"observation_event status is unsupported: {event.get('status')!r}")
    if event.get("privacy") != OBSERVATION_PRIVACY:
        errors.append("observation_event privacy must be metadata_only")
    if not isinstance(event.get("evidence_refs"), list):
        errors.append("observation_event evidence_refs must be a list")
    else:
        for index, value in enumerate(event.get("evidence_refs", [])):
            if not isinstance(value, str):
                errors.append(f"observation_event evidence_refs[{index}] must be a string")
    if not isinstance(event.get("summary"), str):
        errors.append("observation_event summary must be a string")
    if event.get("target_type") == "run" and not event.get("run_id"):
        errors.append("observation_event target_type=run requires run_id")
    return errors


def validate_observation_journal(paths: OmhPaths, *, run_id: str | None = None) -> dict[str, Any]:
    events, errors = read_observation_events_result(paths)
    filtered: list[dict[str, Any]] = []
    for index, event in enumerate(events, start=1):
        if run_id and str(event.get("run_id", "")) != run_id:
            continue
        filtered.append(event)
        errors.extend(
            f"{paths.runtime_journal_events_path}:{index}: {error}"
            for error in validate_observation_event(event)
        )
    return {
        "schema_version": "omh_observation_journal_validation/v1",
        "path": str(paths.runtime_journal_events_path),
        "ok": not errors,
        "event_count": len(filtered),
        "errors": errors,
    }


def project_run_lifecycle(
    events: list[dict[str, Any]],
    *,
    run_id: str = "",
    workflow: str = "",
    harness: str = "",
    phase: str = "",
) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "schema_version": LIFECYCLE_PROJECTION_SCHEMA_VERSION,
        "run_id": run_id,
        "workflow": workflow,
        "harness": harness,
        "phase": phase,
        "prepared_handoff": False,
        "plan_artifact": "",
        "plan_status": "",
        "prompt_dispatched": False,
        "runtime_start_observed": False,
        "worktree_observed": False,
        "execution_observed": False,
        "verification_observed": False,
        "review_observed": False,
        "ci_observed": False,
        "merge_gate_observed": False,
        "merge_observed": False,
        "blocked": False,
        "failed": False,
        "cancelled": False,
        "observation_status": "unknown",
        "journal_event_count": 0,
        "latest_event_id": "",
        "latest_event": {},
    }
    for event in events:
        if not isinstance(event, dict):
            continue
        event_run_id = str(event.get("run_id", ""))
        if run_id and event_run_id and event_run_id != run_id:
            continue
        _fold_event(projection, event)
    if projection["journal_event_count"] == 0 and projection["prepared_handoff"]:
        projection["observation_status"] = "prepared_not_observed"
    return projection


def observation_status_from_projection(projection: dict[str, Any], fallback: str = "unknown") -> str:
    status = str(projection.get("observation_status") or "")
    return status if status and status != "unknown" else fallback


def merge_lifecycle_projection(legacy: dict[str, Any], journal: dict[str, Any]) -> dict[str, Any]:
    merged = {**legacy, **journal}
    for key in (
        "prepared_handoff",
        "prompt_dispatched",
        "runtime_start_observed",
        "worktree_observed",
        "execution_observed",
        "verification_observed",
        "review_observed",
        "ci_observed",
        "merge_gate_observed",
        "merge_observed",
        "blocked",
        "failed",
        "cancelled",
    ):
        merged[key] = bool(legacy.get(key)) or bool(journal.get(key))
    for key in ("run_id", "workflow", "harness", "phase", "plan_artifact", "plan_status"):
        merged[key] = journal.get(key) or legacy.get(key, "")
    merged["observation_status"] = _max_status(
        str(legacy.get("observation_status", "unknown")),
        str(journal.get("observation_status", "unknown")),
    )
    merged["journal_event_count"] = int(journal.get("journal_event_count", 0) or 0)
    merged["latest_event_id"] = str(journal.get("latest_event_id", ""))
    merged["latest_event"] = journal.get("latest_event", {})
    return merged


def _fold_event(projection: dict[str, Any], event: dict[str, Any]) -> None:
    status = str(event.get("status", "observed"))
    event_name = canonical_observation_event(str(event.get("event", "")))
    projection["journal_event_count"] = int(projection.get("journal_event_count", 0)) + 1
    projection["latest_event_id"] = str(event.get("event_id", ""))
    projection["latest_event"] = {
        "event": event_name,
        "status": status,
        "summary": str(event.get("summary", "")),
        "observed_at": str(event.get("observed_at", "")),
    }
    if event.get("workflow") and not projection.get("workflow"):
        projection["workflow"] = str(event.get("workflow", ""))
    if event.get("harness") and not projection.get("harness"):
        projection["harness"] = str(event.get("harness", ""))
    if event.get("phase"):
        projection["phase"] = str(event.get("phase", ""))
    if event.get("plan_artifact"):
        projection["plan_artifact"] = str(event.get("plan_artifact", ""))
    if event.get("plan_status"):
        projection["plan_status"] = str(event.get("plan_status", ""))
    if event_name == "plan_accepted":
        projection["plan_status"] = "accepted"
    elif event_name == "plan_revised":
        projection["plan_status"] = "revised"
    elif event_name == "plan_cancelled":
        projection["plan_status"] = "cancelled"
    if status == "blocked":
        projection["blocked"] = True
        projection["observation_status"] = "blocked"
    elif status == "failed":
        projection["failed"] = True
        projection["observation_status"] = "failed"
    if status != "observed":
        return
    if event_name == "prepared_handoff_created":
        projection["prepared_handoff"] = True
        _advance_status(projection, "prepared_not_observed")
    elif event_name == "runtime_start_observed":
        projection["runtime_start_observed"] = True
        _advance_status(projection, "runtime_start_observed")
    elif event_name == "worktree_creation_observed":
        projection["worktree_observed"] = True
        _advance_status(projection, "worktree_creation_observed")
    elif event_name == "executor_dispatch_observed":
        projection["prompt_dispatched"] = True
        _advance_status(projection, "dispatch_observed")
    elif event_name == "executor_result_observed":
        projection["execution_observed"] = True
        _advance_status(projection, "execution_observed")
    elif event_name == "verification_result_observed":
        projection["verification_observed"] = True
        _advance_status(projection, "verification_observed")
    elif event_name == "review_result_observed":
        projection["review_observed"] = True
        _advance_status(projection, "review_observed")
    elif event_name == "ci_result_observed":
        projection["ci_observed"] = True
        _advance_status(projection, "ci_observed")
    elif event_name == "merge_gate_observed":
        projection["merge_gate_observed"] = True
        _advance_status(projection, "merge_gate_observed")
    elif event_name == "merge_observed":
        projection["merge_observed"] = True
        _advance_status(projection, "merge_observed")
    elif event_name == "blocked":
        projection["blocked"] = True
        projection["observation_status"] = "blocked"
    elif event_name == "failed":
        projection["failed"] = True
        projection["observation_status"] = "failed"
    elif event_name == "cancelled":
        projection["cancelled"] = True
        projection["observation_status"] = "cancelled"


def _event_id(observed_at: str, event: dict[str, Any]) -> str:
    base = json.dumps(
        {
            "observed_at": observed_at,
            "run_id": event.get("run_id", ""),
            "target_id": event.get("target_id", ""),
            "event": event.get("event", ""),
            "summary": event.get("summary", ""),
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]
    return f"{observed_at.replace(':', '').replace('-', '').replace('.', '')}-{digest}-{secrets.token_hex(2)}"


def _evidence_refs(event: dict[str, Any]) -> list[str]:
    refs = event.get("evidence_refs", event.get("evidence_ref", []))
    if isinstance(refs, str):
        refs = [refs]
    if not isinstance(refs, list):
        return []
    return [str(ref) for ref in refs if str(ref)]


def _bounded_summary(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _apply_limit(events: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return events
    if limit < 1:
        return []
    return events[-limit:]


def _advance_status(projection: dict[str, Any], candidate: str) -> None:
    projection["observation_status"] = _max_status(str(projection.get("observation_status", "unknown")), candidate)


def _max_status(current: str, candidate: str) -> str:
    if candidate in {"blocked", "failed", "cancelled"}:
        return candidate
    if current in {"blocked", "failed", "cancelled"}:
        return current
    try:
        return candidate if PROJECTION_ORDER.index(candidate) >= PROJECTION_ORDER.index(current) else current
    except ValueError:
        return candidate if current == "unknown" else current
