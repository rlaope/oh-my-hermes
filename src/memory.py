from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .local_store import atomic_write_json, ensure_dir, read_json_object, read_json_object_result, utc_now
from .paths import OmhPaths
from .profiles.setup import read_setup_profile
from .targets import summarize_target_registry


MEMORY_SNAPSHOT_SCHEMA_VERSION = "memory_snapshot/v1"
MEMORY_INSPECTION_SCHEMA_VERSION = "memory_inspection/v1"
MEMORY_REVIEW_CARD_SCHEMA_VERSION = "memory_review_card/v1"
HANDOFF_CONTEXT_PACK_SCHEMA_VERSION = "handoff_context_pack/v1"
MEMORY_UPDATE_BATCH_SCHEMA_VERSION = "memory_update_batch/v1"
MEMORY_SCOPE_SCHEMA_VERSION = "omh_memory_scope/v1"
MEMORY_INDEX_SCHEMA_VERSION = "omh_memory_index/v1"

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
_HANDOFF_CONTEXT_PACK_KEYS = {
    "schema_version",
    "executor_target",
    "session_id",
    "scope",
    "source_refs",
    "included_context",
    "excluded_context",
    "blocked_by_conflicts",
    "redaction_policy",
    "claim_boundary",
}
_HANDOFF_CONTEXT_SCOPE_KEYS = {"kind", "ref"}
_HANDOFF_CONTEXT_SOURCE_REF_KEYS = {"source", "truth_level", "precedence", "item_count"}
_HANDOFF_CONTEXT_INCLUDED_KEYS = {"item_id", "key", "summary", "source", "truth_level", "scope"}
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


def build_memory_inspection(
    paths: OmhPaths,
    *,
    wrapper_snapshot: dict[str, Any] | None = None,
) -> dict[str, object]:
    snapshots = _local_snapshots(paths)
    if wrapper_snapshot:
        snapshots.append(_normalize_wrapper_snapshot(wrapper_snapshot))
    conflicts = _detect_conflicts(snapshots)
    stale_candidates = [conflict for conflict in conflicts if conflict["severity"] in {"warning", "blocker"}]
    review_items = _review_items(snapshots, conflicts)
    payload: dict[str, object] = {
        "schema_version": MEMORY_INSPECTION_SCHEMA_VERSION,
        "created_at": utc_now(),
        "snapshots": snapshots,
        "review_items": review_items,
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
) -> dict[str, object]:
    inspection = inspection or build_memory_inspection(paths)
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
        "included_context": included[:12],
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


def _local_snapshots(paths: OmhPaths) -> list[dict[str, object]]:
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
    snapshots.extend(_wrapper_session_snapshots(paths))
    snapshots.append(_catalog_hint_snapshot())
    return snapshots


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


def _wrapper_session_snapshots(paths: OmhPaths) -> list[dict[str, object]]:
    if not paths.runtime_wrapper_sessions_dir.exists():
        return []
    snapshots: list[dict[str, object]] = []
    for session_json in sorted(paths.runtime_wrapper_sessions_dir.glob("*/session.json")):
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
    atomic_write_json(
        paths.memory_index_path,
        {
            "schema_version": MEMORY_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "scope_files": sorted(scopes),
            "claim_boundary": "OMH local memory only; this index is not Hermes internal memory.",
        },
        private=True,
    )


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
