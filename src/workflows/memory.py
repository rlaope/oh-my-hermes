from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..local_store import atomic_write_json, ensure_dir, read_json_object, read_json_object_result, utc_now
from ..paths import OmhPaths
from ..profiles.setup import read_setup_profile
from ..targets import summarize_target_registry


MEMORY_SNAPSHOT_SCHEMA_VERSION = "memory_snapshot/v1"
MEMORY_INSPECTION_SCHEMA_VERSION = "memory_inspection/v1"
MEMORY_REVIEW_CARD_SCHEMA_VERSION = "memory_review_card/v1"
HANDOFF_CONTEXT_PACK_SCHEMA_VERSION = "handoff_context_pack/v1"
MEMORY_UPDATE_BATCH_SCHEMA_VERSION = "memory_update_batch/v1"
MEMORY_SCOPE_SCHEMA_VERSION = "omh_memory_scope/v1"
MEMORY_INDEX_SCHEMA_VERSION = "omh_memory_index/v1"
PROJECT_MEMORY_POLICY_SCHEMA_VERSION = "project_memory_policy/v1"
PROJECT_MEMORY_STATUS_SCHEMA_VERSION = "project_memory_status/v1"
PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION = "project_memory_capture/v1"
PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION = "project_memory_candidate/v1"
PROJECT_MEMORY_RECORD_SCHEMA_VERSION = "project_memory_record/v1"
PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION = "project_memory_review_card/v1"
PROJECT_MEMORY_REVIEW_QUEUE_SCHEMA_VERSION = "project_memory_review_queue/v1"
PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION = "project_memory_review_record/v1"
PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION = "project_memory_recall_pack/v1"

SOURCE_TRUTH_LEVELS = {
    "runtime_evidence": "observed_evidence",
    "runtime_state": "runtime_index_state",
    "wrapper_session": "chat_decision_state",
    "target_topology": "setup_evidence",
    "setup_profile": "preference_default",
    "omh_memory": "approved_context",
    "wiki_notes": "durable_knowledge",
    "catalog_hint": "capability_hint",
    "wrapper_snapshot": "supplied_hint",
}
SOURCE_PRECEDENCE = {
    "runtime_evidence": 100,
    "wrapper_session": 90,
    "runtime_state": 85,
    "target_topology": 80,
    "setup_profile": 70,
    "omh_memory": 60,
    "wiki_notes": 50,
    "catalog_hint": 40,
    "wrapper_snapshot": 30,
}
ALLOWED_UPDATE_OPS = {"keep", "forget", "update", "change_scope", "dismiss_conflict"}
ALLOWED_SCOPE_KINDS = {"project", "target", "thread", "run"}
PROJECT_MEMORY_MODES = ("off", "review-first", "auto-safe")
PROJECT_MEMORY_RECORD_TYPES = ("fact", "decision", "lesson", "procedure", "episode")
MEMORY_ACTION_IDS = (
    "keep_memory",
    "forget_memory",
    "update_memory",
    "change_memory_scope",
    "apply_memory_updates",
    "show_memory_status",
    "cancel",
)
_SAFE_REF = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
_PROMPTISH_KEYS = {"message", "prompt", "raw", "text", "body", "content", "prompt_template"}
_PROJECT_MEMORY_RECORD_KEYS = {
    "schema_version",
    "record_id",
    "candidate_id",
    "review_status",
    "record_type",
    "summary",
    "scope",
    "tags",
    "source",
    "source_ref",
    "approved_by",
    "approved_at",
    "created_at",
    "updated_at",
    "ttl",
    "staleness",
    "safety",
    "redaction_policy",
    "claim_boundary",
}
_PROJECT_MEMORY_RECALL_PACK_KEYS = {
    "schema_version",
    "enabled",
    "executor_target",
    "session_id",
    "task_ref",
    "policy",
    "scope",
    "included_records",
    "excluded_records",
    "record_count",
    "redaction_policy",
    "claim_boundary",
}
_PROJECT_MEMORY_RECALL_ITEM_KEYS = {
    "record_id",
    "record_type",
    "summary",
    "scope",
    "tags",
    "source",
    "approved_at",
    "staleness",
    "score",
}
_PROJECT_MEMORY_EXCLUDED_KEYS = {"record_id", "reason", "staleness"}
_PROJECT_MEMORY_TASK_REF_KEYS = {"sha256", "length", "query_supplied"}
_HANDOFF_CONTEXT_PACK_KEYS = {
    "schema_version",
    "executor_target",
    "session_id",
    "scope",
    "source_refs",
    "included_context",
    "excluded_context",
    "blocked_by_conflicts",
    "metadata",
    "redaction_policy",
    "claim_boundary",
}
_HANDOFF_CONTEXT_SCOPE_KEYS = {"kind", "ref"}
_HANDOFF_CONTEXT_SOURCE_REF_KEYS = {"source", "truth_level", "precedence", "item_count"}
_HANDOFF_CONTEXT_INCLUDED_KEYS = {"item_id", "key", "summary", "source", "truth_level", "scope", "artifact_ref"}
_HANDOFF_CONTEXT_EXCLUDED_KEYS = {"item_id", "source", "reason"}
_HANDOFF_CONTEXT_CONFLICT_KEYS = {
    "item_id",
    "key",
    "severity",
    "current_value",
    "preferred_value",
    "current_source",
    "preferred_source",
    "reason",
    "claim_boundary",
}
_HANDOFF_CONTEXT_BLOCKED_KEYS = {"schema_version", "blocked_by_conflicts", "claim_boundary"}


def build_project_memory_policy(paths: OmhPaths, *, mode: str | None = None) -> dict[str, object]:
    normalized = _normalize_memory_mode(mode)
    return {
        "schema_version": PROJECT_MEMORY_POLICY_SCHEMA_VERSION,
        "mode": normalized,
        "capture_enabled": normalized != "off",
        "recall_enabled": normalized != "off",
        "review_required": normalized == "review-first",
        "auto_approve_safe": normalized == "auto-safe",
        "store_scope": "project_local",
        "store_dir": str(paths.memory_dir),
        "redaction_policy": "metadata_only",
        "backend": "local_json",
        "optional_backend_extension": True,
        "claim_boundary": "Project memory configures OMH-local prepared context only; it does not mutate Hermes global or internal memory.",
    }


def read_project_memory_policy(paths: OmhPaths) -> dict[str, object]:
    setup = read_setup_profile(paths)
    if isinstance(setup, dict):
        policy = setup.get("memory_policy")
        if isinstance(policy, dict):
            return build_project_memory_policy(paths, mode=str(policy.get("mode", "") or "review-first"))
        return build_project_memory_policy(paths, mode=str(setup.get("memory_mode", "") or "review-first"))
    return build_project_memory_policy(paths)


def build_project_memory_status(paths: OmhPaths) -> dict[str, object]:
    candidates = _read_project_memory_candidates(paths)
    records = _read_project_memory_records(paths)
    reviews = _read_project_memory_reviews(paths)
    candidate_status_counts: dict[str, int] = {}
    for candidate in candidates:
        status = str(candidate.get("status", "unknown"))
        candidate_status_counts[status] = candidate_status_counts.get(status, 0) + 1
    return {
        "schema_version": PROJECT_MEMORY_STATUS_SCHEMA_VERSION,
        "policy": read_project_memory_policy(paths),
        "store": {
            "schema_version": MEMORY_INDEX_SCHEMA_VERSION,
            "memory_dir": str(paths.memory_dir),
            "candidate_dir": str(_memory_candidates_dir(paths)),
            "record_dir": str(_memory_records_dir(paths)),
            "review_dir": str(_memory_reviews_dir(paths)),
            "index_path": str(paths.memory_index_path),
            "local_only": True,
        },
        "counts": {
            "candidates": len(candidates),
            "pending_review": sum(1 for candidate in candidates if str(candidate.get("status", "")) in {"pending_review", "blocked_review_required"}),
            "approved_records": len(records),
            "review_records": len(reviews),
            "candidate_statuses": candidate_status_counts,
        },
        "redaction_policy": "metadata_only",
        "claim_boundary": "Project memory status is prepared local context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def capture_project_memory_candidate(
    paths: OmhPaths,
    summary: str,
    *,
    content: str = "",
    record_type: str = "fact",
    scope_kind: str = "project",
    scope_ref: str = "default",
    source: str = "cli",
    source_ref: str = "",
    tags: list[str] | tuple[str, ...] | None = None,
    ttl_days: int | None = None,
    stale_after_days: int | None = None,
) -> dict[str, object]:
    policy = read_project_memory_policy(paths)
    if not bool(policy.get("capture_enabled", True)):
        return {
            "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
            "captured": False,
            "auto_approved": False,
            "policy": policy,
            "reason": "project_memory_disabled",
            "claim_boundary": "Memory capture is disabled by OMH project policy; Hermes global or internal memory is not mutated.",
        }
    candidate = _build_project_memory_candidate(
        summary,
        content=content,
        record_type=record_type,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        source=source,
        source_ref=source_ref,
        tags=tags or [],
        ttl_days=ttl_days,
        stale_after_days=stale_after_days,
    )
    _write_project_memory_candidate(paths, candidate)
    auto_approved = False
    record: dict[str, object] = {}
    if bool(policy.get("auto_approve_safe")) and candidate.get("safety", {}).get("status") == "safe":
        approved = approve_project_memory_candidate(paths, str(candidate["candidate_id"]), approved_by="auto-safe")
        record = approved.get("record", {}) if isinstance(approved.get("record"), dict) else {}
        candidate = approved.get("candidate", candidate) if isinstance(approved.get("candidate"), dict) else candidate
        auto_approved = True
    return {
        "schema_version": PROJECT_MEMORY_CAPTURE_SCHEMA_VERSION,
        "captured": True,
        "auto_approved": auto_approved,
        "candidate": candidate,
        "record": record,
        "policy": policy,
        "claim_boundary": (
            "Captured project memory is an OMH-local candidate or reviewed record only; "
            "it is not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def build_project_memory_review(
    paths: OmhPaths,
    *,
    candidate_id: str | None = None,
    limit: int = 20,
) -> dict[str, object]:
    candidates = _read_project_memory_candidates(paths)
    if candidate_id:
        candidates = [candidate for candidate in candidates if candidate.get("candidate_id") == candidate_id]
    else:
        candidates = [candidate for candidate in candidates if str(candidate.get("status", "")) in {"pending_review", "blocked_review_required"}]
    cards = [build_project_memory_review_card(candidate) for candidate in candidates[: max(limit, 0)]]
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_QUEUE_SCHEMA_VERSION,
        "policy": read_project_memory_policy(paths),
        "cards": cards,
        "card_count": len(cards),
        "pending_count": len(candidates),
        "redaction_policy": "metadata_only",
        "claim_boundary": "Project memory review is prepared context review only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def build_project_memory_review_card(candidate: dict[str, Any]) -> dict[str, object]:
    safety = candidate.get("safety", {}) if isinstance(candidate.get("safety"), dict) else {}
    safety_status = str(safety.get("status", "needs_review"))
    recommended_action = "reject" if safety_status == "blocked" else "approve_or_reject"
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_CARD_SCHEMA_VERSION,
        "candidate_id": str(candidate.get("candidate_id", "")),
        "record_type": str(candidate.get("record_type", "")),
        "summary": str(candidate.get("summary", "")),
        "scope": _normalize_scope(candidate.get("scope", _scope("project", "default"))),
        "tags": _string_list(candidate.get("tags", [])),
        "safety": safety,
        "recommended_action": recommended_action,
        "actions": [
            {"id": "approve_memory", "enabled": safety_status != "blocked"},
            {"id": "reject_memory", "enabled": True},
            {"id": "show_memory_status", "enabled": True},
        ],
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "Memory review cards are prepared project context only; "
            "they are not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def approve_project_memory_candidate(paths: OmhPaths, candidate_id: str, *, approved_by: str = "operator") -> dict[str, object]:
    candidate = _read_project_memory_candidate(paths, candidate_id)
    if not candidate:
        raise FileNotFoundError(candidate_id)
    safety = candidate.get("safety", {}) if isinstance(candidate.get("safety"), dict) else {}
    if safety.get("status") == "blocked":
        raise ValueError("blocked memory candidates must be rejected or recaptured without protected raw content")
    now = utc_now()
    record = _record_from_candidate(candidate, approved_by=approved_by, approved_at=now)
    _write_project_memory_record(paths, record)
    candidate = {**candidate, "status": "approved", "reviewed_at": now, "reviewed_by": approved_by, "record_id": record["record_id"]}
    _write_project_memory_candidate(paths, candidate)
    review = _write_project_memory_review_decision(paths, candidate, decision="approved", reviewer=approved_by, reason="")
    _write_memory_index(paths)
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "decision": "approved",
        "candidate": candidate,
        "record": record,
        "review": review,
        "claim_boundary": "Approved project memory is prepared context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def reject_project_memory_candidate(
    paths: OmhPaths,
    candidate_id: str,
    *,
    rejected_by: str = "operator",
    reason: str = "",
) -> dict[str, object]:
    candidate = _read_project_memory_candidate(paths, candidate_id)
    if not candidate:
        raise FileNotFoundError(candidate_id)
    now = utc_now()
    candidate = {**candidate, "status": "rejected", "reviewed_at": now, "reviewed_by": rejected_by, "rejection_reason": _redact(str(reason or ""))[:300]}
    _write_project_memory_candidate(paths, candidate)
    review = _write_project_memory_review_decision(paths, candidate, decision="rejected", reviewer=rejected_by, reason=reason)
    _write_memory_index(paths)
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "decision": "rejected",
        "candidate": candidate,
        "review": review,
        "claim_boundary": (
            "Rejected project memory is an OMH-local review decision only; "
            "it is not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def build_project_memory_recall_pack(
    paths: OmhPaths,
    query: str = "",
    *,
    executor_target: str = "generic",
    session_id: str = "",
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    limit: int = 6,
    include_stale: bool = False,
) -> dict[str, object]:
    policy = read_project_memory_policy(paths)
    task_ref = {
        "sha256": hashlib.sha256(query.encode("utf-8")).hexdigest() if query else "",
        "length": len(query),
        "query_supplied": bool(query),
    }
    if not bool(policy.get("recall_enabled", True)):
        return _empty_recall_pack(
            policy,
            executor_target=executor_target,
            session_id=session_id,
            task_ref=task_ref,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            reason="project_memory_disabled",
        )
    records = _read_project_memory_records(paths)
    included: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for record in records:
        if not _record_scope_matches(record, scope_kind=scope_kind, scope_ref=scope_ref):
            continue
        staleness = _record_staleness(record)
        if staleness["state"] == "expired":
            excluded.append({"record_id": str(record.get("record_id", "")), "reason": "expired", "staleness": staleness})
            continue
        if staleness["state"] == "stale" and not include_stale:
            excluded.append({"record_id": str(record.get("record_id", "")), "reason": "stale", "staleness": staleness})
            continue
        score = _memory_recall_score(record, query)
        if query and score <= 0:
            excluded.append({"record_id": str(record.get("record_id", "")), "reason": "no_query_overlap", "staleness": staleness})
            continue
        included.append(_recall_item(record, score=score, staleness=staleness))
    included.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("record_id", ""))))
    included = included[: max(limit, 0)]
    return {
        "schema_version": PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
        "enabled": True,
        "executor_target": executor_target,
        "session_id": session_id,
        "task_ref": task_ref,
        "policy": policy,
        "scope": _scope(scope_kind or "project", scope_ref or "default"),
        "included_records": included,
        "excluded_records": excluded,
        "record_count": len(included),
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "Memory recall packs contain reviewed OMH project summaries only; "
            "they are prepared context, not execution, review, CI, merge, or Hermes internal-memory evidence."
        ),
    }


def memory_recall_pack_for_handoff(
    paths: OmhPaths,
    query: str,
    *,
    executor_target: str = "generic",
    session_id: str = "",
    limit: int = 5,
) -> dict[str, object] | None:
    pack = build_project_memory_recall_pack(paths, query, executor_target=executor_target, session_id=session_id, limit=limit)
    if not pack.get("enabled") or not pack.get("included_records"):
        return None
    return pack


def build_memory_inspection(
    paths: OmhPaths,
    *,
    wrapper_snapshot: dict[str, Any] | None = None,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    session_limit: int | None = None,
    summary: bool = False,
    review_item_limit: int | None = None,
) -> dict[str, object]:
    snapshots = _local_snapshots(paths, scope_kind=scope_kind, scope_ref=scope_ref, session_limit=session_limit)
    if wrapper_snapshot:
        snapshots.append(_normalize_wrapper_snapshot(wrapper_snapshot))
    conflicts = _detect_conflicts(snapshots)
    stale_candidates = [conflict for conflict in conflicts if conflict["severity"] in {"warning", "blocker"}]
    all_review_items = _review_items(snapshots, conflicts)
    review_items = _limited_items(all_review_items, review_item_limit)
    payload: dict[str, object] = {
        "schema_version": MEMORY_INSPECTION_SCHEMA_VERSION,
        "created_at": utc_now(),
        "snapshots": [] if summary else snapshots,
        "snapshot_summary": _snapshot_summary(snapshots) if summary else [],
        "snapshot_count": len(snapshots),
        "review_items": review_items,
        "review_item_count": len(all_review_items),
        "conflicts": conflicts,
        "stale_candidates": stale_candidates,
        "recommended_actions": _recommended_actions(conflicts),
        "handoff_context_preview": _handoff_preview(snapshots, conflicts),
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "Memory inspection reviews OMH-local or wrapper-supplied context only; it is not proof that Hermes internal memory was read or changed."
        ),
    }
    payload["review_card"] = build_memory_review_card(payload)
    return payload


def build_memory_review_card(inspection: dict[str, Any]) -> dict[str, object]:
    review_items = list(inspection.get("review_items", []) if isinstance(inspection.get("review_items"), list) else [])
    conflicts = list(inspection.get("conflicts", []) if isinstance(inspection.get("conflicts"), list) else [])
    blocker_count = sum(1 for conflict in conflicts if isinstance(conflict, dict) and conflict.get("severity") == "blocker")
    headline = "Review Hermes memory assumptions."
    if blocker_count:
        headline = f"Review {blocker_count} stale or conflicting memory assumption(s)."
    return {
        "schema_version": MEMORY_REVIEW_CARD_SCHEMA_VERSION,
        "headline": headline,
        "summary": f"{len(review_items)} memory/context item(s) are available for review; {len(conflicts)} conflict(s) are flagged.",
        "primary_action": "apply_memory_updates" if review_items else "show_memory_status",
        "actions": [_memory_action(action_id) for action_id in MEMORY_ACTION_IDS],
        "review_items": review_items,
        "conflicts": conflicts,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Memory review is not runtime execution evidence and does not mutate opaque Hermes memory.",
    }


def build_handoff_context_pack(
    paths: OmhPaths,
    *,
    inspection: dict[str, Any] | None = None,
    executor_target: str = "generic",
    session_id: str = "",
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    session_limit: int | None = None,
    context_limit: int = 12,
) -> dict[str, object]:
    if inspection is None:
        snapshots = _local_snapshots(paths, scope_kind=scope_kind, scope_ref=scope_ref, session_limit=session_limit)
        conflicts = _detect_conflicts(snapshots)
        inspection = {"snapshots": snapshots, "conflicts": conflicts}
    conflicts = [conflict for conflict in inspection.get("conflicts", []) if isinstance(conflict, dict)]
    blocking_conflicts = [conflict for conflict in conflicts if conflict.get("severity") == "blocker"]
    included: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for snapshot in inspection.get("snapshots", []):
        if not isinstance(snapshot, dict):
            continue
        for item in snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            if _item_conflicts(item, blocking_conflicts):
                excluded.append(
                    {
                        "item_id": str(item.get("item_id", "")),
                        "source": str(snapshot.get("source", "")),
                        "reason": "blocked_by_unresolved_conflict",
                    }
                )
                continue
            if _is_packable(item, snapshot):
                included.append(
                    {
                        "item_id": str(item.get("item_id", "")),
                        "key": str(item.get("key", "")),
                        "summary": str(item.get("summary", "")),
                        "source": str(snapshot.get("source", "")),
                        "truth_level": str(snapshot.get("truth_level", "")),
                        "scope": item.get("scope", snapshot.get("scope", _scope("project", "default"))),
                    }
                )
    return {
        "schema_version": HANDOFF_CONTEXT_PACK_SCHEMA_VERSION,
        "executor_target": executor_target,
        "session_id": session_id,
        "scope": _scope("project", "default"),
        "source_refs": _source_refs(inspection),
        "included_context": included[:context_limit],
        "excluded_context": excluded,
        "blocked_by_conflicts": blocking_conflicts,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Context packs contain approved summaries only; they are not raw memory dumps or execution evidence.",
    }


def apply_memory_update_batch(paths: OmhPaths, batch: dict[str, Any], *, dry_run: bool = False) -> dict[str, object]:
    if batch.get("schema_version") != MEMORY_UPDATE_BATCH_SCHEMA_VERSION:
        raise ValueError("unsupported memory update batch schema")
    updates = batch.get("updates")
    if not isinstance(updates, list):
        raise ValueError("memory update batch requires updates list")
    result_updates: list[dict[str, object]] = []
    written_paths: list[str] = []
    not_applied: list[dict[str, object]] = []
    touched: dict[Path, dict[str, Any]] = {}
    base = _memory_root(paths)
    for update in updates:
        try:
            result = _prepare_update(paths, update, touched)
            result_updates.append(result)
        except OSError as exc:
            item_id = str(update.get("item_id", "")) if isinstance(update, dict) else ""
            not_applied.append({"item_id": item_id, "reason": str(exc)})
    if not dry_run and not not_applied:
        ensure_dir(base, private=True)
        for path, data in touched.items():
            _assert_under_memory_root(paths, path)
            atomic_write_json(path, data, private=True)
            written_paths.append(str(path))
        _write_memory_index(paths)
    return {
        "schema_version": MEMORY_UPDATE_BATCH_SCHEMA_VERSION,
        "approved_by": str(batch.get("approved_by", "")),
        "source_surface": str(batch.get("source_surface", "")),
        "dry_run": dry_run,
        "applied": bool(updates) and not dry_run and not not_applied,
        "updates": result_updates,
        "written_paths": written_paths,
        "not_applied": not_applied,
        "claim_boundary": "Approved updates write OMH-local memory only; Hermes internal memory is not mutated.",
    }


def read_memory_snapshot_file(path: str | Path) -> dict[str, Any]:
    data = read_json_object(Path(path).expanduser().resolve())
    if not isinstance(data, dict):
        raise ValueError("memory snapshot fixture must be a JSON object")
    return data


def read_handoff_context_pack_file(path: str | Path) -> dict[str, Any]:
    data = read_json_object(Path(path).expanduser().resolve())
    if not isinstance(data, dict):
        raise ValueError("context pack must be a JSON object")
    errors = validate_handoff_context_pack(data, require_conflict_free=False, label="context pack")
    if errors:
        raise ValueError("; ".join(errors))
    return data


def validate_handoff_context_pack(value: Any, *, require_conflict_free: bool, label: str = "context_pack") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _HANDOFF_CONTEXT_PACK_KEYS, errors, label)
    if value.get("schema_version") != HANDOFF_CONTEXT_PACK_SCHEMA_VERSION:
        errors.append(f"{label} schema_version must be {HANDOFF_CONTEXT_PACK_SCHEMA_VERSION}")
    if value.get("redaction_policy") != "metadata_only":
        errors.append(f"{label} redaction_policy must be metadata_only")
    if not isinstance(value.get("claim_boundary"), str):
        errors.append(f"{label} claim_boundary must be a string")
    if not isinstance(value.get("executor_target"), str):
        errors.append(f"{label} executor_target must be a string")
    if not isinstance(value.get("session_id"), str):
        errors.append(f"{label} session_id must be a string")
    _validate_context_scope(value.get("scope"), errors, f"{label}.scope")
    _validate_context_list(value.get("source_refs"), _HANDOFF_CONTEXT_SOURCE_REF_KEYS, errors, f"{label}.source_refs")
    _validate_context_list(value.get("included_context"), _HANDOFF_CONTEXT_INCLUDED_KEYS, errors, f"{label}.included_context", scope_key="scope")
    _validate_context_list(value.get("excluded_context"), _HANDOFF_CONTEXT_EXCLUDED_KEYS, errors, f"{label}.excluded_context")
    _validate_context_list(value.get("blocked_by_conflicts"), _HANDOFF_CONTEXT_CONFLICT_KEYS, errors, f"{label}.blocked_by_conflicts")
    if require_conflict_free and value.get("blocked_by_conflicts") != []:
        errors.append(f"{label} must be conflict-free when attached")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text and cannot be attached")
    return errors


def validate_handoff_context_blocked(value: Any, *, label: str = "context_pack_blocked") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _HANDOFF_CONTEXT_BLOCKED_KEYS, errors, label)
    if value.get("schema_version") != "handoff_context_blocked/v1":
        errors.append(f"{label} schema_version must be handoff_context_blocked/v1")
    _validate_context_list(value.get("blocked_by_conflicts"), _HANDOFF_CONTEXT_CONFLICT_KEYS, errors, f"{label}.blocked_by_conflicts")
    if not value.get("blocked_by_conflicts"):
        errors.append(f"{label} requires at least one conflict")
    if not isinstance(value.get("claim_boundary"), str):
        errors.append(f"{label} claim_boundary must be a string")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text and cannot be attached")
    return errors


def validate_project_memory_recall_pack(value: Any, *, label: str = "memory_recall_pack") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _PROJECT_MEMORY_RECALL_PACK_KEYS, errors, label)
    if value.get("schema_version") != PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION:
        errors.append(f"{label} schema_version must be {PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION}")
    if not isinstance(value.get("enabled"), bool):
        errors.append(f"{label}.enabled must be a boolean")
    if not isinstance(value.get("executor_target"), str):
        errors.append(f"{label}.executor_target must be a string")
    if not isinstance(value.get("session_id"), str):
        errors.append(f"{label}.session_id must be a string")
    _validate_context_scope(value.get("scope"), errors, f"{label}.scope")
    _validate_context_list(value.get("included_records"), _PROJECT_MEMORY_RECALL_ITEM_KEYS, errors, f"{label}.included_records", scope_key="scope")
    _validate_context_list(value.get("excluded_records"), _PROJECT_MEMORY_EXCLUDED_KEYS, errors, f"{label}.excluded_records")
    _validate_context_map(value.get("task_ref"), _PROJECT_MEMORY_TASK_REF_KEYS, errors, f"{label}.task_ref")
    if not isinstance(value.get("policy"), dict):
        errors.append(f"{label}.policy must be an object")
    if value.get("redaction_policy") != "metadata_only":
        errors.append(f"{label}.redaction_policy must be metadata_only")
    if not isinstance(value.get("claim_boundary"), str):
        errors.append(f"{label}.claim_boundary must be a string")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text and cannot be attached")
    return errors


def _build_project_memory_candidate(
    summary: str,
    *,
    content: str,
    record_type: str,
    scope_kind: str,
    scope_ref: str,
    source: str,
    source_ref: str,
    tags: list[str] | tuple[str, ...],
    ttl_days: int | None,
    stale_after_days: int | None,
) -> dict[str, object]:
    normalized_type = _normalize_record_type(record_type)
    scope = _scope_for_project_memory(scope_kind, scope_ref)
    normalized_tags = _normalize_tags(tags)
    content_text = str(content or "")
    safety = _project_memory_safety(summary, content_text, tags=normalized_tags)
    now = utc_now()
    ttl = _ttl_metadata(ttl_days, record_type=normalized_type, created_at=now)
    staleness = _staleness_metadata(stale_after_days, record_type=normalized_type, created_at=now)
    candidate_basis = {
        "record_type": normalized_type,
        "summary": summary.strip(),
        "scope": scope,
        "source": source,
        "source_ref": source_ref,
        "tags": normalized_tags,
    }
    candidate_id = "cand_" + hashlib.sha256(_jsonish(candidate_basis).encode("utf-8")).hexdigest()[:16]
    status = "blocked_review_required" if safety["status"] == "blocked" else "pending_review"
    return {
        "schema_version": PROJECT_MEMORY_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "status": status,
        "record_type": normalized_type,
        "summary": _redact(summary.strip())[:500],
        "scope": scope,
        "tags": normalized_tags,
        "source": str(source or "cli"),
        "source_ref": _redact(str(source_ref or ""))[:160],
        "created_at": now,
        "ttl": ttl,
        "staleness": staleness,
        "content_ref": {
            "sha256": hashlib.sha256(content_text.encode("utf-8")).hexdigest() if content_text else "",
            "length": len(content_text),
            "raw_persisted": False,
        },
        "safety": safety,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Memory candidates are OMH-local prepared context only; they are not approved memory or execution/review/CI/merge evidence.",
    }


def _record_from_candidate(candidate: dict[str, Any], *, approved_by: str, approved_at: str) -> dict[str, object]:
    record_id = "mem_" + hashlib.sha256(str(candidate.get("candidate_id", "")).encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "candidate_id": str(candidate.get("candidate_id", "")),
        "review_status": "approved",
        "record_type": _normalize_record_type(str(candidate.get("record_type", "fact"))),
        "summary": _redact(str(candidate.get("summary", "")))[:500],
        "scope": _normalize_scope(candidate.get("scope", _scope("project", "default"))),
        "tags": _normalize_tags(candidate.get("tags", [])),
        "source": str(candidate.get("source", "cli")),
        "source_ref": _redact(str(candidate.get("source_ref", "")))[:160],
        "approved_by": str(approved_by or "operator"),
        "approved_at": approved_at,
        "created_at": str(candidate.get("created_at", approved_at)),
        "updated_at": approved_at,
        "ttl": candidate.get("ttl", {}),
        "staleness": candidate.get("staleness", {}),
        "safety": candidate.get("safety", {}),
        "redaction_policy": "metadata_only",
        "claim_boundary": "Reviewed OMH project memory is prepared context only; it is not execution, review, CI, merge, or Hermes internal-memory evidence.",
    }


def _write_project_memory_review_decision(
    paths: OmhPaths,
    candidate: dict[str, Any],
    *,
    decision: str,
    reviewer: str,
    reason: str,
) -> dict[str, object]:
    reviewed_at = str(candidate.get("reviewed_at") or utc_now())
    review = {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "candidate_id": str(candidate.get("candidate_id", "")),
        "record_id": str(candidate.get("record_id", "")),
        "decision": decision,
        "reviewer": str(reviewer or "operator"),
        "reason": _redact(str(reason or ""))[:300],
        "reviewed_at": reviewed_at,
        "claim_boundary": "Project memory review decisions are local prepared-context governance only; they are not execution/review/CI/merge evidence.",
    }
    path = _memory_review_path(paths, str(candidate.get("candidate_id", "")))
    atomic_write_json(path, review, private=True)
    return review


def _empty_recall_pack(
    policy: dict[str, object],
    *,
    executor_target: str,
    session_id: str,
    task_ref: dict[str, object],
    scope_kind: str | None,
    scope_ref: str | None,
    reason: str,
) -> dict[str, object]:
    return {
        "schema_version": PROJECT_MEMORY_RECALL_PACK_SCHEMA_VERSION,
        "enabled": False,
        "executor_target": executor_target,
        "session_id": session_id,
        "task_ref": task_ref,
        "policy": policy,
        "scope": _scope(scope_kind or "project", scope_ref or "default"),
        "included_records": [],
        "excluded_records": [{"record_id": "", "reason": reason, "staleness": {"state": "not_checked"}}],
        "record_count": 0,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Memory recall is disabled or empty; no execution, review, CI, merge, or Hermes internal-memory evidence is produced.",
    }


def _recall_item(record: dict[str, Any], *, score: int, staleness: dict[str, object]) -> dict[str, object]:
    return {
        "record_id": str(record.get("record_id", "")),
        "record_type": str(record.get("record_type", "")),
        "summary": _redact(str(record.get("summary", "")))[:500],
        "scope": _normalize_scope(record.get("scope", _scope("project", "default"))),
        "tags": _normalize_tags(record.get("tags", [])),
        "source": str(record.get("source", "")),
        "approved_at": str(record.get("approved_at", "")),
        "staleness": staleness,
        "score": int(score),
    }


def _memory_recall_score(record: dict[str, Any], query: str) -> int:
    if not query.strip():
        return 1
    query_tokens = _memory_tokens(query)
    record_tokens = _memory_tokens(
        " ".join(
            [
                str(record.get("summary", "")),
                str(record.get("record_type", "")),
                " ".join(_normalize_tags(record.get("tags", []))),
            ]
        )
    )
    overlap = query_tokens & record_tokens
    tag_overlap = query_tokens & set(_normalize_tags(record.get("tags", [])))
    return len(overlap) * 10 + len(tag_overlap) * 5


def _memory_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9_/-]+", value.lower()) if len(token) >= 3}


def _record_scope_matches(record: dict[str, Any], *, scope_kind: str | None, scope_ref: str | None) -> bool:
    scope = _normalize_scope(record.get("scope", _scope("project", "default")))
    return (not scope_kind or scope["kind"] == scope_kind) and (not scope_ref or scope["ref"] == scope_ref)


def _record_staleness(record: dict[str, Any]) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    ttl = record.get("ttl", {}) if isinstance(record.get("ttl"), dict) else {}
    expires_at = _parse_utc(str(ttl.get("expires_at", "") or ""))
    if expires_at and expires_at <= now:
        return {"state": "expired", "expires_at": str(ttl.get("expires_at", ""))}
    staleness = record.get("staleness", {}) if isinstance(record.get("staleness"), dict) else {}
    stale_after = _parse_utc(str(staleness.get("stale_after", "") or ""))
    if stale_after and stale_after <= now:
        return {"state": "stale", "stale_after": str(staleness.get("stale_after", ""))}
    return {"state": "fresh", "stale_after": str(staleness.get("stale_after", "")), "expires_at": str(ttl.get("expires_at", ""))}


def _project_memory_safety(summary: str, content: str, *, tags: list[str]) -> dict[str, object]:
    text = "\n".join([summary, content, " ".join(tags)])
    reasons: list[str] = []
    blocked = False
    if _looks_sensitive(text):
        blocked = True
        reasons.append("sensitive_credential_like_text")
    if _looks_like_raw_log(text):
        blocked = True
        reasons.append("raw_log_or_traceback")
    if _looks_like_full_transcript(text):
        blocked = True
        reasons.append("full_transcript_like_text")
    if re.search(r"\b(?:PR|pull request)\s*#?\d+\b", text, flags=re.IGNORECASE):
        reasons.append("short_lived_pr_reference")
    if re.search(r"\b[0-9a-f]{7,40}\b", text, flags=re.IGNORECASE):
        reasons.append("short_lived_commit_reference")
    if re.search(r"\b(?:temporary|for this session|wip|in progress|pending ci|currently running|today|tomorrow|yesterday)\b", text, flags=re.IGNORECASE):
        reasons.append("temporary_task_progress")
    if len(content) > 2400:
        reasons.append("long_content_requires_review")
    status = "blocked" if blocked else "needs_review" if reasons else "safe"
    return {
        "schema_version": "project_memory_safety/v1",
        "status": status,
        "safe_to_auto_approve": status == "safe",
        "review_reasons": reasons,
        "protected_inputs": [
            "credentials",
            "raw_logs",
            "full_transcripts",
            "short_lived_pr_or_commit_ids",
            "temporary_task_progress",
        ],
    }


def _looks_like_raw_log(value: str) -> bool:
    lowered = value.lower()
    markers = ("traceback (most recent call last)", "\nstderr", "\nstdout", "[error]", "exception:", "raw log", "full log")
    timestamp_lines = len(re.findall(r"^\d{4}-\d{2}-\d{2}[ t]\d{2}:\d{2}:\d{2}", value, flags=re.MULTILINE))
    return any(marker in lowered for marker in markers) or timestamp_lines >= 3


def _looks_like_full_transcript(value: str) -> bool:
    lowered = value.lower()
    speaker_lines = len(re.findall(r"^(user|assistant|system|developer|human|agent):", value, flags=re.IGNORECASE | re.MULTILINE))
    return "full transcript" in lowered or "chat transcript" in lowered or speaker_lines >= 4


def _ttl_metadata(ttl_days: int | None, *, record_type: str, created_at: str) -> dict[str, object]:
    default_days = 30 if record_type == "episode" and ttl_days is None else ttl_days
    return {
        "ttl_days": default_days,
        "expires_at": _days_after(created_at, default_days) if default_days else "",
    }


def _staleness_metadata(stale_after_days: int | None, *, record_type: str, created_at: str) -> dict[str, object]:
    default_days = 90 if record_type in {"fact", "decision", "lesson", "procedure"} and stale_after_days is None else stale_after_days
    return {
        "stale_after_days": default_days,
        "stale_after": _days_after(created_at, default_days) if default_days else "",
    }


def _days_after(created_at: str, days: int | None) -> str:
    if not days:
        return ""
    base = _parse_utc(created_at) or datetime.now(timezone.utc)
    return (base + timedelta(days=int(days))).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _normalize_memory_mode(value: str | None) -> str:
    mode = str(value or "review-first").strip()
    if mode not in PROJECT_MEMORY_MODES:
        raise ValueError(f"unsupported memory mode: {mode}; expected one of {', '.join(PROJECT_MEMORY_MODES)}")
    return mode


def _normalize_record_type(value: str) -> str:
    record_type = str(value or "fact").strip()
    if record_type not in PROJECT_MEMORY_RECORD_TYPES:
        raise ValueError(f"unsupported memory record type: {record_type}; expected one of {', '.join(PROJECT_MEMORY_RECORD_TYPES)}")
    return record_type


def _scope_for_project_memory(kind: str, ref: str) -> dict[str, str]:
    scope = _scope(str(kind or "project"), str(ref or "default"))
    if scope["kind"] not in ALLOWED_SCOPE_KINDS:
        raise ValueError(f"unsupported memory scope kind: {scope['kind']}")
    if not _SAFE_REF.match(scope["ref"]):
        raise ValueError(f"unsafe memory scope ref: {scope['ref']!r}")
    return scope


def _normalize_tags(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = str(value).strip().lower()
        if not tag or not _SAFE_REF.match(tag):
            continue
        if tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags[:12]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _read_project_memory_candidate(paths: OmhPaths, candidate_id: str) -> dict[str, Any] | None:
    if not _SAFE_REF.match(candidate_id):
        raise ValueError(f"unsafe memory candidate id: {candidate_id!r}")
    return read_json_object(_memory_candidate_path(paths, candidate_id))


def _read_project_memory_candidates(paths: OmhPaths) -> list[dict[str, Any]]:
    return _read_memory_json_files(paths, _memory_candidates_dir(paths))


def _read_project_memory_records(paths: OmhPaths) -> list[dict[str, Any]]:
    records = []
    for record in _read_memory_json_files(paths, _memory_records_dir(paths)):
        if record.get("schema_version") == PROJECT_MEMORY_RECORD_SCHEMA_VERSION and record.get("review_status") == "approved":
            records.append(record)
    return records


def _read_project_memory_reviews(paths: OmhPaths) -> list[dict[str, Any]]:
    return _read_memory_json_files(paths, _memory_reviews_dir(paths))


def _read_memory_json_files(paths: OmhPaths, directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        _assert_under_memory_root(paths, path)
        data = read_json_object(path)
        if isinstance(data, dict):
            items.append(data)
    return items


def _write_project_memory_candidate(paths: OmhPaths, candidate: dict[str, object]) -> None:
    path = _memory_candidate_path(paths, str(candidate.get("candidate_id", "")))
    atomic_write_json(path, candidate, private=True)
    _write_memory_index(paths)


def _write_project_memory_record(paths: OmhPaths, record: dict[str, object]) -> None:
    errors = validate_project_memory_record(record)
    if errors:
        raise ValueError("; ".join(errors))
    atomic_write_json(_memory_record_path(paths, str(record.get("record_id", ""))), record, private=True)


def validate_project_memory_record(value: Any, *, label: str = "project_memory_record") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    _validate_allowed_keys(value, _PROJECT_MEMORY_RECORD_KEYS, errors, label)
    if value.get("schema_version") != PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
        errors.append(f"{label}.schema_version must be {PROJECT_MEMORY_RECORD_SCHEMA_VERSION}")
    if value.get("review_status") != "approved":
        errors.append(f"{label}.review_status must be approved")
    _validate_context_scope(value.get("scope"), errors, f"{label}.scope")
    if value.get("redaction_policy") != "metadata_only":
        errors.append(f"{label}.redaction_policy must be metadata_only")
    if _contains_sensitive_text(value):
        errors.append(f"{label} contains sensitive-looking text")
    return errors


def _memory_candidates_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "candidates"


def _memory_records_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "records"


def _memory_reviews_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "reviews"


def _memory_candidate_path(paths: OmhPaths, candidate_id: str) -> Path:
    if not _SAFE_REF.match(candidate_id):
        raise ValueError(f"unsafe memory candidate id: {candidate_id!r}")
    path = _memory_candidates_dir(paths) / f"{candidate_id}.json"
    _assert_under_memory_root(paths, path)
    return path


def _memory_record_path(paths: OmhPaths, record_id: str) -> Path:
    if not _SAFE_REF.match(record_id):
        raise ValueError(f"unsafe memory record id: {record_id!r}")
    path = _memory_records_dir(paths) / f"{record_id}.json"
    _assert_under_memory_root(paths, path)
    return path


def _memory_review_path(paths: OmhPaths, candidate_id: str) -> Path:
    if not _SAFE_REF.match(candidate_id):
        raise ValueError(f"unsafe memory candidate id: {candidate_id!r}")
    path = _memory_reviews_dir(paths) / f"{candidate_id}.json"
    _assert_under_memory_root(paths, path)
    return path


def _validate_context_map(value: Any, allowed: set[str], errors: list[str], label: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_allowed_keys(value, allowed, errors, label)
    for key, nested in value.items():
        if isinstance(nested, (str, int, bool)) or nested is None:
            continue
        errors.append(f"{label}.{key} must be scalar metadata")


def _jsonish(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _local_snapshots(
    paths: OmhPaths,
    *,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    session_limit: int | None = None,
) -> list[dict[str, object]]:
    snapshots: list[dict[str, object]] = []
    setup = read_setup_profile(paths)
    if setup:
        snapshots.append(_setup_snapshot(setup))
    topology = summarize_target_registry(paths)
    if topology.get("status") == "available":
        snapshots.append(_target_snapshot(topology))
    runtime_state, runtime_error = read_json_object_result(paths.runtime_state_path)
    if runtime_state:
        snapshots.append(_runtime_state_snapshot(runtime_state))
    elif runtime_error:
        snapshots.append(_snapshot("runtime_state", _scope("project", "default"), [{"item_id": "runtime-state-error", "key": "runtime_state", "summary": runtime_error}]))
    memory_snapshots = _memory_snapshots(paths)
    snapshots.extend(memory_snapshots)
    snapshots.extend(_wrapper_session_snapshots(paths, limit=session_limit))
    snapshots.append(_catalog_hint_snapshot())
    return _filter_snapshots_by_scope(snapshots, scope_kind=scope_kind, scope_ref=scope_ref)


def _setup_snapshot(setup: dict[str, Any]) -> dict[str, object]:
    return _snapshot(
        "setup_profile",
        _scope("project", "default"),
        [
            {
                "item_id": "setup-default-executor",
                "key": "default_executor",
                "value": str(setup.get("default_executor", "")),
                "summary": f"default executor: {setup.get('default_executor', '')}",
            },
            {
                "item_id": "setup-dispatch-policy",
                "key": "dispatch_policy",
                "value": str(setup.get("dispatch_policy", "")),
                "summary": f"dispatch policy: {setup.get('dispatch_policy', '')}",
            },
            {
                "item_id": "setup-operating-model",
                "key": "operating_model_id",
                "value": str(setup.get("operating_model_id", "")),
                "summary": f"operating model: {setup.get('operating_model_id', '')}",
            },
        ],
    )


def _target_snapshot(topology: dict[str, Any]) -> dict[str, object]:
    return _snapshot(
        "target_topology",
        _scope("target", str(topology.get("current_target_id") or "default")),
        [
            {
                "item_id": "target-mode",
                "key": "target_mode",
                "value": str(topology.get("mode", "")),
                "summary": f"target mode: {topology.get('mode', '')}; active agents: {topology.get('active_agent_count', 0)}",
            },
            {
                "item_id": "target-active-agent-count",
                "key": "active_agent_count",
                "value": str(topology.get("active_agent_count", 0)),
                "summary": f"active Hermes agents: {topology.get('active_agent_count', 0)}",
            },
        ],
    )


def _runtime_state_snapshot(state: dict[str, Any]) -> dict[str, object]:
    items: list[dict[str, object]] = []
    last_run = str(state.get("last_run_id", ""))
    if last_run:
        items.append({"item_id": "runtime-last-run", "key": "last_run_id", "value": last_run, "summary": f"last runtime run: {last_run}"})
    last_setup = state.get("last_setup")
    if isinstance(last_setup, dict):
        items.append({"item_id": "runtime-last-setup", "key": "last_setup", "summary": f"last setup ok: {bool(last_setup.get('ok', False))}"})
    return _snapshot("runtime_state", _scope("project", "default"), items)


def _memory_snapshots(paths: OmhPaths) -> list[dict[str, object]]:
    snapshots: list[dict[str, object]] = []
    reviewed_items: list[dict[str, object]] = []
    for record in _read_project_memory_records(paths):
        reviewed_items.append(
            {
                "item_id": str(record.get("record_id", "")),
                "key": str(record.get("record_type", "memory")),
                "summary": _safe_summary(record),
                "scope": record.get("scope", _scope("project", "default")),
            }
        )
    if reviewed_items:
        snapshots.append(_snapshot("omh_memory", _scope("project", "default"), reviewed_items))
    for path in _memory_scope_paths(paths):
        data = read_json_object(path)
        if not isinstance(data, dict):
            continue
        items = []
        for item_id, item in (data.get("items", {}) if isinstance(data.get("items"), dict) else {}).items():
            if isinstance(item, dict):
                items.append(
                    {
                        "item_id": str(item_id),
                        "key": str(item.get("key", item_id)),
                        "value": str(item.get("value", "")),
                        "summary": _safe_summary(item),
                        "scope": data.get("scope", _scope("project", "default")),
                    }
                )
        snapshots.append(_snapshot("omh_memory", data.get("scope", _scope("project", "default")), items))
    return snapshots


def _wrapper_session_snapshots(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, object]]:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return []
    snapshots: list[dict[str, object]] = []
    session_paths = sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json"))
    if limit is not None and limit > 0:
        session_paths = session_paths[-limit:]
    for session_json in session_paths:
        session = read_json_object(session_json)
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("session_id", session_json.parent.name))
        items = [
            {
                "item_id": f"wrapper-session-{session_id}",
                "key": "wrapper_session_status",
                "value": str(session.get("status", "")),
                "summary": f"wrapper session {session_id}: {session.get('status', '')}",
            }
        ]
        selected_executor = str(session.get("selected_executor_profile") or "")
        if selected_executor:
            items.append(
                {
                    "item_id": f"wrapper-session-{session_id}-executor",
                    "key": "default_executor",
                    "value": selected_executor,
                    "summary": f"session executor: {selected_executor}",
                }
            )
        snapshots.append(_snapshot("wrapper_session", _scope("thread", _stable_ref(session.get("thread_key", session_id))), items))
    return snapshots


def _filter_snapshots_by_scope(
    snapshots: list[dict[str, object]],
    *,
    scope_kind: str | None,
    scope_ref: str | None,
) -> list[dict[str, object]]:
    if not scope_kind and not scope_ref:
        return snapshots
    filtered: list[dict[str, object]] = []
    for snapshot in snapshots:
        scope = _normalize_scope(snapshot.get("scope", _scope("project", "default")))
        kind_matches = not scope_kind or scope["kind"] == scope_kind
        ref_matches = not scope_ref or scope["ref"] == scope_ref
        if kind_matches and ref_matches:
            filtered.append(snapshot)
    return filtered


def _limited_items(items: list[dict[str, object]], limit: int | None) -> list[dict[str, object]]:
    if limit is None:
        return items
    if limit < 1:
        return []
    return items[:limit]


def _snapshot_summary(snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "source": str(snapshot.get("source", "")),
            "truth_level": str(snapshot.get("truth_level", "")),
            "precedence": int(snapshot.get("precedence", 0) or 0),
            "scope": snapshot.get("scope", _scope("project", "default")),
            "item_count": len(snapshot.get("items", [])) if isinstance(snapshot.get("items"), list) else 0,
        }
        for snapshot in snapshots
    ]


def _catalog_hint_snapshot() -> dict[str, object]:
    return _snapshot(
        "catalog_hint",
        _scope("project", "default"),
        [
            {
                "item_id": "catalog-memory-boundary",
                "key": "memory_boundary",
                "summary": "OMH can inspect local state and wrapper snapshots; opaque Hermes memory requires explicit source evidence.",
            }
        ],
    )


def _normalize_wrapper_snapshot(snapshot: dict[str, Any]) -> dict[str, object]:
    if snapshot.get("schema_version") != MEMORY_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("wrapper memory snapshot schema_version must be memory_snapshot/v1")
    source = "wrapper_snapshot"
    scope = _normalize_scope(snapshot.get("scope", _scope("project", "default")))
    items = [_sanitize_item(item, default_scope=scope) for item in snapshot.get("items", []) if isinstance(item, dict)]
    return _snapshot(source, scope, items, claim_boundary=str(snapshot.get("claim_boundary", "Wrapper supplied memory candidates are not trusted until reviewed.")))


def _snapshot(source: str, scope: Any, items: list[dict[str, object]], *, claim_boundary: str = "") -> dict[str, object]:
    normalized_scope = _normalize_scope(scope)
    return {
        "schema_version": MEMORY_SNAPSHOT_SCHEMA_VERSION,
        "source": source,
        "truth_level": SOURCE_TRUTH_LEVELS[source],
        "precedence": SOURCE_PRECEDENCE[source],
        "scope": normalized_scope,
        "items": [_sanitize_item(item, default_scope=normalized_scope) for item in items],
        "observed_at": utc_now(),
        "redaction_policy": "metadata_only",
        "claim_boundary": claim_boundary or _claim_boundary_for_source(source),
    }


def _sanitize_item(item: dict[str, Any], *, default_scope: dict[str, str]) -> dict[str, object]:
    item_id = str(item.get("item_id") or _stable_ref(item.get("key", "item")))
    key = str(item.get("key", item_id))
    summary = _safe_summary(item)
    sanitized: dict[str, object] = {
        "item_id": item_id,
        "key": key,
        "summary": summary,
        "scope": _normalize_scope(item.get("scope", default_scope)),
        "sensitive": bool(item.get("sensitive", False)),
    }
    value = item.get("value")
    if _safe_to_expose_value(key, value, item):
        sanitized["value"] = str(value)
    return sanitized


def _safe_summary(item: dict[str, Any]) -> str:
    summary = str(item.get("summary", ""))
    if summary:
        return _redact(summary)
    key = str(item.get("key", item.get("item_id", "item")))
    value = str(item.get("value", ""))
    if key in _PROMPTISH_KEYS or item.get("sensitive"):
        return f"{key}: redacted"
    return _redact(f"{key}: {value}")[:240]


def _safe_to_expose_value(key: str, value: Any, item: dict[str, Any]) -> bool:
    if value is None or item.get("sensitive"):
        return False
    text = str(value)
    if key in _PROMPTISH_KEYS:
        return False
    if _looks_sensitive(text):
        return False
    return len(text) <= 240


def _redact(value: str) -> str:
    if _looks_sensitive(value):
        return "[redacted]"
    return value[:240]


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in ("secret", "token", "password", "private-key", "api_key", "apikey"))


def _validate_allowed_keys(value: dict[str, Any], allowed: set[str], errors: list[str], label: str) -> None:
    extra_keys = sorted(set(value) - allowed)
    if extra_keys:
        errors.append(f"{label} has unsupported keys: {extra_keys}")


def _validate_context_scope(value: Any, errors: list[str], label: str) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return
    _validate_allowed_keys(value, _HANDOFF_CONTEXT_SCOPE_KEYS, errors, label)
    kind = value.get("kind")
    ref = value.get("ref")
    if not isinstance(kind, str) or not kind:
        errors.append(f"{label}.kind must be a non-empty string")
    if not isinstance(ref, str) or not ref:
        errors.append(f"{label}.ref must be a non-empty string")


def _validate_context_list(
    value: Any,
    allowed: set[str],
    errors: list[str],
    label: str,
    *,
    scope_key: str | None = None,
) -> None:
    if not isinstance(value, list):
        errors.append(f"{label} must be a list")
        return
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label} must be an object")
            continue
        _validate_allowed_keys(item, allowed, errors, item_label)
        for key, nested in item.items():
            nested_label = f"{item_label}.{key}"
            if scope_key and key == scope_key:
                _validate_context_scope(nested, errors, nested_label)
            elif key == "tags" and isinstance(nested, list):
                if any(not isinstance(tag, str) for tag in nested):
                    errors.append(f"{nested_label} must contain string tags")
            elif key == "staleness" and isinstance(nested, dict):
                _validate_context_map(nested, set(nested), errors, nested_label)
            elif isinstance(nested, (str, int, bool)) or nested is None:
                continue
            else:
                errors.append(f"{nested_label} must be scalar metadata")


def _contains_sensitive_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_sensitive_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_sensitive_text(item) for item in value)
    if isinstance(value, str):
        return _looks_sensitive(value)
    return False


def _detect_conflicts(snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    values = _values_by_key(snapshots)
    conflicts.extend(_pairwise_conflict(values, "default_executor", preferred_source="setup_profile"))
    conflicts.extend(_pairwise_conflict(values, "target_mode", preferred_source="target_topology"))
    if any(value["key"] == "verification_status" and str(value.get("value", "")).lower() in {"verified", "passed"} for value in values):
        has_runtime_verification = any(value["source"] == "runtime_evidence" and value["key"] in {"verification_status", "verification_observed"} for value in values)
        if not has_runtime_verification:
            conflicts.append(
                {
                    "item_id": "verification-status-conflict",
                    "key": "verification_status",
                    "severity": "blocker",
                    "preferred_source": "runtime_evidence",
                    "reason": "Remembered verification cannot be used as runtime evidence without a run-ledger verification record.",
                    "claim_boundary": "Remembered verification is not observed verification evidence.",
                }
            )
    return conflicts


def _pairwise_conflict(values: list[dict[str, Any]], key: str, *, preferred_source: str) -> list[dict[str, object]]:
    keyed = [value for value in values if value["key"] == key and value.get("value") not in {None, ""}]
    preferred = [value for value in keyed if value["source"] == preferred_source]
    if not preferred:
        return []
    preferred_value = str(preferred[0].get("value", ""))
    conflicts = []
    for value in keyed:
        if value["source"] == preferred_source:
            continue
        if str(value.get("value", "")) and str(value.get("value", "")) != preferred_value:
            conflicts.append(
                {
                    "item_id": str(value.get("item_id", "")),
                    "key": key,
                    "severity": "blocker",
                    "current_value": str(value.get("value", "")),
                    "preferred_value": preferred_value,
                    "current_source": value["source"],
                    "preferred_source": preferred_source,
                    "reason": f"{key} from {value['source']} conflicts with {preferred_source}.",
                    "claim_boundary": "Conflicting memory-like context must be reviewed before it is reused in a handoff.",
                }
            )
    return conflicts


def _values_by_key(snapshots: list[dict[str, object]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for snapshot in snapshots:
        source = str(snapshot.get("source", ""))
        for item in snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            values.append({**item, "source": source, "precedence": snapshot.get("precedence", 0)})
    return values


def _review_items(snapshots: list[dict[str, object]], conflicts: list[dict[str, object]]) -> list[dict[str, object]]:
    conflict_ids = {str(conflict.get("item_id", "")) for conflict in conflicts}
    synthetic_conflict_keys = {
        str(conflict.get("key", ""))
        for conflict in conflicts
        if str(conflict.get("item_id", "")).endswith("-conflict") and str(conflict.get("key", ""))
    }
    items: list[dict[str, object]] = []
    for snapshot in snapshots:
        for item in snapshot.get("items", []) if isinstance(snapshot.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id", ""))
            blocked = item_id in conflict_ids or str(item.get("key", "")) in synthetic_conflict_keys
            items.append(
                {
                    "item_id": item_id,
                    "source": snapshot.get("source", ""),
                    "truth_level": snapshot.get("truth_level", ""),
                    "key": item.get("key", ""),
                    "summary": item.get("summary", ""),
                    "scope": item.get("scope", snapshot.get("scope", _scope("project", "default"))),
                    "suggested_action": "update_memory" if blocked else "keep_memory",
                    "blocked": blocked,
                }
            )
    return items


def _recommended_actions(conflicts: list[dict[str, object]]) -> list[str]:
    if conflicts:
        return ["update_memory", "change_memory_scope", "dismiss_conflict", "apply_memory_updates"]
    return ["keep_memory", "show_memory_status"]


def _handoff_preview(snapshots: list[dict[str, object]], conflicts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": HANDOFF_CONTEXT_PACK_SCHEMA_VERSION,
        "included_candidate_count": sum(len(snapshot.get("items", [])) for snapshot in snapshots if isinstance(snapshot.get("items"), list)),
        "blocked_by_conflict_count": len(conflicts),
        "claim_boundary": "Preview only; use handoff_context_pack/v1 before embedding context in a handoff.",
    }


def _prepare_update(paths: OmhPaths, update: Any, touched: dict[Path, dict[str, Any]]) -> dict[str, object]:
    if not isinstance(update, dict):
        raise ValueError("memory update must be an object")
    op = str(update.get("op", ""))
    if op not in ALLOWED_UPDATE_OPS:
        raise ValueError(f"unsupported memory update op: {op}")
    item_id = str(update.get("item_id", ""))
    if not _SAFE_REF.match(item_id):
        raise ValueError(f"unsafe memory item id: {item_id!r}")
    scope = _scope_for_update(update, "scope")
    path = _scope_path(paths, scope)
    data = touched.setdefault(path, _read_scope_file(path, scope))
    status = "prepared"
    if op in {"keep", "update", "dismiss_conflict"}:
        status = _upsert_item(data, item_id, update, op=op)
    elif op == "forget":
        status = _forget_item(data, item_id, update)
    elif op == "change_scope":
        from_scope = _scope_for_update(update, "from_scope")
        to_scope = _scope_for_update(update, "to_scope")
        from_path = _scope_path(paths, from_scope)
        to_path = _scope_path(paths, to_scope)
        from_data = touched.setdefault(from_path, _read_scope_file(from_path, from_scope))
        to_data = touched.setdefault(to_path, _read_scope_file(to_path, to_scope))
        status = _move_item(from_data, to_data, item_id, update)
        path = to_path
    return {"item_id": item_id, "op": op, "scope": scope, "status": status, "path": str(path)}


def _upsert_item(data: dict[str, Any], item_id: str, update: dict[str, Any], *, op: str) -> str:
    items = data.setdefault("items", {})
    existing = items.get(item_id)
    value = str(update.get("value", existing.get("value", "") if isinstance(existing, dict) else ""))
    key = str(update.get("key", item_id))
    item = {
        "item_id": item_id,
        "key": key,
        "summary": _safe_summary(update),
        "reason": str(update.get("reason", "")),
        "operation": op,
        "updated_at": utc_now(),
    }
    if _safe_to_expose_value(key, value, update):
        item["value"] = value
    if op == "keep":
        item["confirmed_at"] = item["updated_at"]
    if op == "dismiss_conflict":
        item["dismissed_at"] = item["updated_at"]
    if isinstance(existing, dict) and existing.get("value", "") == item.get("value", "") and existing.get("summary") == item["summary"]:
        items[item_id] = {**existing, **item}
        return "noop"
    items[item_id] = item
    return "prepared"


def _forget_item(data: dict[str, Any], item_id: str, update: dict[str, Any]) -> str:
    items = data.setdefault("items", {})
    tombstones = data.setdefault("tombstones", {})
    existed = item_id in items
    if existed:
        items.pop(item_id)
    tombstones[item_id] = {
        "item_id": item_id,
        "reason": str(update.get("reason", "")),
        "tombstoned_at": utc_now(),
    }
    return "prepared" if existed else "noop"


def _move_item(from_data: dict[str, Any], to_data: dict[str, Any], item_id: str, update: dict[str, Any]) -> str:
    from_items = from_data.setdefault("items", {})
    to_items = to_data.setdefault("items", {})
    item = from_items.pop(item_id, None)
    if not isinstance(item, dict):
        value = str(update.get("value", ""))
        key = str(update.get("key", item_id))
        item = {
            "item_id": item_id,
            "key": key,
            "summary": _safe_summary(update),
        }
        if _safe_to_expose_value(key, value, update):
            item["value"] = value
    if to_items.get(item_id) == item:
        return "noop"
    to_items[item_id] = {**item, "moved_at": utc_now(), "reason": str(update.get("reason", ""))}
    return "prepared"


def _scope_for_update(update: dict[str, Any], key: str) -> dict[str, str]:
    scope = _normalize_scope(update.get(key, update.get("scope", _scope("project", "default"))))
    if scope["kind"] not in ALLOWED_SCOPE_KINDS:
        raise ValueError(f"unsupported memory scope kind: {scope['kind']}")
    if not _SAFE_REF.match(scope["ref"]):
        raise ValueError(f"unsafe memory scope ref: {scope['ref']!r}")
    return scope


def _read_scope_file(path: Path, scope: dict[str, str]) -> dict[str, Any]:
    data = read_json_object(path)
    if isinstance(data, dict):
        return data
    return {
        "schema_version": MEMORY_SCOPE_SCHEMA_VERSION,
        "scope": scope,
        "items": {},
        "tombstones": {},
        "updated_at": utc_now(),
    }


def _write_memory_index(paths: OmhPaths) -> None:
    ensure_dir(paths.memory_dir, private=True)
    scopes = [str(path.relative_to(paths.memory_dir)) for path in _memory_scope_paths(paths)]
    candidates = [str(path.relative_to(paths.memory_dir)) for path in _safe_memory_files(paths, _memory_candidates_dir(paths))]
    records = [str(path.relative_to(paths.memory_dir)) for path in _safe_memory_files(paths, _memory_records_dir(paths))]
    reviews = [str(path.relative_to(paths.memory_dir)) for path in _safe_memory_files(paths, _memory_reviews_dir(paths))]
    atomic_write_json(
        paths.memory_index_path,
        {
            "schema_version": MEMORY_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "scope_files": sorted(scopes),
            "candidate_files": sorted(candidates),
            "record_files": sorted(records),
            "review_files": sorted(reviews),
            "claim_boundary": "OMH local memory only; this index is not Hermes internal memory.",
        },
        private=True,
    )


def _safe_memory_files(paths: OmhPaths, directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    safe_paths: list[Path] = []
    for path in directory.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        _assert_under_memory_root(paths, path)
        safe_paths.append(path)
    return sorted(safe_paths)


def _memory_scope_paths(paths: OmhPaths) -> list[Path]:
    scopes_dir = paths.memory_dir / "scopes"
    if not scopes_dir.exists():
        return []
    safe_paths: list[Path] = []
    for path in scopes_dir.rglob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        _assert_under_memory_root(paths, path)
        safe_paths.append(path)
    return sorted(safe_paths)


def _scope_path(paths: OmhPaths, scope: dict[str, str]) -> Path:
    kind = scope["kind"]
    ref = scope["ref"]
    if kind == "project":
        relative = Path("scopes/project.json")
    else:
        relative = Path("scopes") / f"{kind}s" / f"{ref}.json"
    path = paths.memory_dir / relative
    _assert_under_memory_root(paths, path)
    return path


def _assert_under_memory_root(paths: OmhPaths, path: Path) -> None:
    root = _memory_root(paths)
    candidate = path.resolve(strict=False)
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"memory write path escapes .omh/memory: {path}")


def _memory_root(paths: OmhPaths) -> Path:
    return paths.memory_dir.resolve(strict=False)


def _normalize_scope(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        kind = str(value.get("kind", "project") or "project")
        ref = str(value.get("ref", "default") or "default")
        return _scope(kind, ref)
    if isinstance(value, str) and value:
        return _scope("project", value)
    return _scope("project", "default")


def _scope(kind: str, ref: str) -> dict[str, str]:
    return {"kind": kind, "ref": ref}


def _source_refs(inspection: dict[str, Any]) -> list[dict[str, object]]:
    refs = []
    for snapshot in inspection.get("snapshots", []) if isinstance(inspection.get("snapshots"), list) else []:
        if isinstance(snapshot, dict):
            refs.append(
                {
                    "source": str(snapshot.get("source", "")),
                    "truth_level": str(snapshot.get("truth_level", "")),
                    "precedence": int(snapshot.get("precedence", 0) or 0),
                    "item_count": len(snapshot.get("items", [])) if isinstance(snapshot.get("items"), list) else 0,
                }
            )
    return refs


def _item_conflicts(item: dict[str, Any], conflicts: list[dict[str, object]]) -> bool:
    item_id = str(item.get("item_id", ""))
    key = str(item.get("key", ""))
    return any(conflict.get("item_id") == item_id or conflict.get("key") == key for conflict in conflicts)


def _is_packable(item: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    source = str(snapshot.get("source", ""))
    if source == "wrapper_snapshot":
        return False
    key = str(item.get("key", ""))
    return key not in {"verification_status"} and bool(item.get("summary"))


def _memory_action(action_id: str) -> dict[str, object]:
    labels = {
        "keep_memory": "Keep",
        "forget_memory": "Forget",
        "update_memory": "Update",
        "change_memory_scope": "Change scope",
        "apply_memory_updates": "Apply updates",
        "show_memory_status": "Show memory status",
        "cancel": "Cancel",
    }
    return {"id": action_id, "label": labels[action_id], "enabled": True}


def _claim_boundary_for_source(source: str) -> str:
    return {
        "runtime_evidence": "Runtime ledger evidence is the source of execution/review/CI/merge claims.",
        "runtime_state": "Runtime state is an index of local OMH activity, not execution/review/CI/merge evidence.",
        "wrapper_session": "Wrapper sessions own chat continuity and plan decisions only.",
        "target_topology": "Target topology is setup evidence only.",
        "setup_profile": "Setup profile records defaults and preferences only.",
        "omh_memory": "OMH memory is user-approved local context only.",
        "wiki_notes": "Wiki/notes are durable knowledge and can become stale.",
        "catalog_hint": "Catalog hints describe capabilities, not observed runtime behavior.",
        "wrapper_snapshot": "Wrapper snapshots are supplied hints until reviewed.",
    }[source]


def _stable_ref(value: Any) -> str:
    text = str(value or "default")
    if _SAFE_REF.match(text):
        return text
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
