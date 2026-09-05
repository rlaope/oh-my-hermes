"""Fail-closed staged scope-memory batches."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..plugin_bundle.omh.memory_governance import MEMORY_GOVERNANCE_POLICY_VERSION, MEMORY_SCOPE_SCHEMA_VERSION, PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION, SOURCE_CLASSES, build_retention, canonical_memory_scope, canonical_payload_digest, classify_memory_admission, evaluate_renderable_strings, stable_artifact_identity
from ..system.local_store import atomic_write_json, ensure_dir, file_lock, read_json_object_result, utc_now
from ..system.paths import OmhPaths
from ._memory_store_validation import safe_token
from .memory_store import run_memory_operation

BATCH_CANDIDATE_SCHEMA_VERSION, BATCH_REVIEW_SCHEMA_VERSION, BATCH_RECEIPT_SCHEMA_VERSION = "memory_update_batch_candidate/v1", "memory_update_batch_review/v1", "memory_update_batch_receipt/v1"
_LEGACY_BATCH_SCHEMA_VERSION, _OPS, _DECISIONS = "memory_update_batch/v1", frozenset({"keep", "forget", "update", "change_scope", "dismiss_conflict"}), frozenset({"remember", "refuse", "defer"})
_RECEIPT_KEYS = frozenset({"schema_version", "operation_id", "operation_type", "state", "created_at", "completed_at", "step_count", "recovery_count", "outcome"})
_REVIEW_BOUND_ITEM_KEYS = (
    "review_id",
    "candidate_revision",
    "item_id",
    "op",
    "target_ref",
    "scope",
    "from_scope",
    "retention",
    "artifact_identity",
    "payload_digest",
)


def stage_memory_update_batch(paths: OmhPaths, batch: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
    _validate_batch(batch)
    current = _utc(now)
    batch_id = _opaque("batch")
    source_class = str(batch.get("source_class", "omh_local"))
    if source_class not in SOURCE_CLASSES:
        raise ValueError("unsupported batch source_class")
    items = [_proposal(paths, raw, batch, batch_id, current, source_class) for raw in batch["updates"]]
    _distinct_targets(items)
    candidate = {"schema_version": BATCH_CANDIDATE_SCHEMA_VERSION, "batch_id": batch_id, "candidate_revision": 1, "stage_operation_id": _opaque("op_stage"), "apply_operation_id": _opaque("op_apply"), "status": "pending_review", "source_class": source_class, "source_surface": _label(batch.get("source_surface", "api")), "created_at": _stamp(current), "admission": {"state": "pending_review", "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION}, "items": items}
    target = _candidate_relative(batch_id)

    def write_candidate(_: OmhPaths, step: dict[str, str]) -> None:
        if step["action"] != "write_batch_candidate" or step["target"] != target:
            raise ValueError("unexpected batch staging operation")
        present, error = read_json_object_result(paths.memory_dir / target)
        if error:
            raise ValueError("batch candidate is corrupt")
        if present is None:
            atomic_write_json(paths.memory_dir / target, candidate, private=True)
        elif present != candidate:
            raise ValueError("batch candidate identity collision")

    operation = run_memory_operation(paths, operation_id=candidate["stage_operation_id"], operation_type="stage_memory_batch", steps=[{"name": "stage_batch_candidate", "action": "write_batch_candidate", "target": target}], step_writer=write_candidate, now=current)
    if operation.get("state") != "completed":
        raise ValueError("batch staging did not complete")
    return _batch_view(candidate, status="pending_review")


def review_memory_update_batch(paths: OmhPaths, batch_id: str, decisions: Mapping[str, object] | list[Mapping[str, object]], *, reviewer_label: str = "operator", now: datetime | None = None) -> dict[str, object]:
    candidate = _candidate(paths, batch_id)
    decision_map = _decisions(candidate, decisions)
    label = _label(reviewer_label)
    reviewed_at = _stamp(_utc(now))
    reviews = [_review_record(candidate, item, decision_map[item["item_id"]], label, reviewed_at) for item in candidate["items"]]
    with file_lock(paths.memory_index_path, private=True):
        ensure_dir(_reviews_dir(paths), private=True)
        for review in reviews:
            path = _reviews_dir(paths) / f"{review['review_id']}.json"
            present, error = read_json_object_result(path)
            if error:
                raise ValueError("batch review is corrupt")
            if present is not None and not _same_review(present, review):
                raise ValueError("batch review is immutable")
            if present is None:
                atomic_write_json(path, review, private=True)
    return {"schema_version": BATCH_REVIEW_SCHEMA_VERSION, "status": "reviewed", "batch_id": candidate["batch_id"], "reviewer_label": label, "items": [{"item_id": item["item_id"], "review_id": item["review_id"], "decision": decision_map[item["item_id"]]} for item in candidate["items"]]}


def apply_approved_memory_update_batch(paths: OmhPaths, batch_id: str, *, now: datetime | None = None, write_hook: Callable[[str], None] | None = None) -> dict[str, object]:
    candidate = _candidate(paths, batch_id)
    try:
        reviews = _approved_reviews(paths, candidate)
    except ValueError:
        return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "review_required", "reason_code": "review_linkage_invalid", "applied": False, "batch_id": batch_id}
    if any(review["decision"] != "remember" for review in reviews.values()):
        return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "review_required", "reason_code": "review_required", "applied": False, "batch_id": batch_id}
    _revalidate(candidate, reviews)
    scopes = sorted({_relative_scope(scope) for item in candidate["items"] for scope in _item_scopes(item)})
    steps = [
        {"name": f"write_scope_{index}", "action": "write_batch_scope", "source": _candidate_relative(batch_id), "target": target}
        for index, target in enumerate(scopes, start=1)
    ]

    def write_scope(_: OmhPaths, step: dict[str, str]) -> None:
        if step["action"] != "write_batch_scope":
            raise ValueError("unexpected batch apply operation")
        if write_hook:
            write_hook(step["name"])
        _apply_scope(paths, candidate, reviews, step["target"])

    operation = run_memory_operation(paths, operation_id=str(candidate["apply_operation_id"]), operation_type="apply_memory_batch", steps=steps, step_writer=write_scope, now=now)
    receipt = {key: operation["receipt"][key] for key in _RECEIPT_KEYS if key in operation.get("receipt", {})}
    return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "applied" if operation.get("state") == "completed" else str(operation.get("state")), "applied": operation.get("state") == "completed", "batch_id": batch_id, "receipt": receipt}


def legacy_batch_review_required(paths: OmhPaths, batch: Mapping[str, object], *, dry_run: bool = False) -> dict[str, object]:
    _validate_batch(batch)
    return {"schema_version": _LEGACY_BATCH_SCHEMA_VERSION, "status": "review_required", "applied": False, "dry_run": bool(dry_run), "update_count": len(batch["updates"]), "claim_boundary": "Direct memory batches are review-required and do not write OMH memory."}


def _proposal(paths: OmhPaths, raw: object, batch: Mapping[str, object], batch_id: str, now: datetime, source_class: str) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("memory batch update must be an object")
    op, target_ref = str(raw.get("op", "")), str(raw.get("item_id", ""))
    if (
        op not in _OPS
        or not safe_token(target_ref)
        or classify_memory_admission(target_ref)["status"] != "safe"
    ):
        raise ValueError("invalid memory batch update")
    scope = _scope(raw.get("to_scope") if op == "change_scope" else raw.get("scope"))
    from_scope = _scope(raw.get("from_scope")) if op == "change_scope" else None
    if op == "change_scope" and from_scope == scope:
        raise ValueError("change_scope requires distinct scopes")
    existing = _existing(paths, from_scope or scope, target_ref)
    item_id = str(existing.get("item_id")) if existing and safe_token(existing.get("item_id")) else _opaque("item")
    revision = int(existing.get("revision", 0)) + 1 if existing and isinstance(existing.get("revision"), int) else 1
    key = _label(raw.get("key", existing.get("key", target_ref) if existing else target_ref))
    value = str(raw.get("value", existing.get("value", "") if existing else ""))[:500]
    summary = str(raw.get("summary", existing.get("summary", "") if existing else f"{key}: {value}"))[:500]
    if classify_memory_admission("\n".join((key, value, summary))).get("status") != "safe":
        raise ValueError("unsafe memory batch candidate")
    retention_class = str(raw.get("retention_class", batch.get("retention_class", "standard")))
    if classify_memory_admission(retention_class)["status"] != "safe":
        raise ValueError("unsafe memory batch retention class")
    ttl_days = raw.get("ttl_days", batch.get("ttl_days"))
    if ttl_days is not None and (isinstance(ttl_days, bool) or not isinstance(ttl_days, int)):
        raise ValueError("ttl_days must be an integer")
    retention = build_retention(retention_class, record_type="fact", admitted_at=now, ttl_days=ttl_days)
    artifact = {"schema_version": MEMORY_SCOPE_SCHEMA_VERSION, "item_id": item_id, "revision": revision, "key": key, "summary": summary, "value": value, "scope": scope, "source_class": source_class, "admission": {"state": "pending_review", "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION}, "retention": retention, "revalidation": {}}
    return {"item_id": item_id, "candidate_revision": 1, "review_id": _opaque("review"), "op": op, "target_ref": target_ref, "scope": scope, "from_scope": from_scope, "retention": retention, "artifact": artifact, "artifact_identity": stable_artifact_identity(artifact), "payload_digest": canonical_payload_digest(artifact), "batch_id": batch_id}


def _apply_scope(paths: OmhPaths, candidate: dict[str, Any], reviews: dict[str, dict[str, Any]], target: str) -> None:
    matching = [item for item in candidate["items"] if target in {_relative_scope(scope) for scope in _item_scopes(item)}]
    if not matching:
        return
    scope = next(scope for item in matching for scope in _item_scopes(item) if _relative_scope(scope) == target)
    path = paths.memory_dir / target
    current, error = read_json_object_result(path)
    if error:
        raise ValueError("scope file is corrupt")
    data: dict[str, Any] = current if isinstance(current, dict) else {"items": {}, "tombstones": {}}
    if not isinstance(data.get("items"), dict) or not isinstance(data.get("tombstones", {}), dict):
        raise ValueError("scope file is malformed")
    data["schema_version"] = MEMORY_SCOPE_SCHEMA_VERSION
    data["scope"] = scope
    data["items"] = dict(data["items"])
    data["tombstones"] = dict(data.get("tombstones", {}))
    for item in matching:
        op = item["op"]
        if op == "change_scope" and target == _relative_scope(item["from_scope"]):
            data["items"].pop(item["target_ref"], None)
        elif op == "forget":
            data["items"].pop(item["target_ref"], None)
            data["tombstones"][item["target_ref"]] = {"item_id": item["target_ref"], "operation_id": candidate["apply_operation_id"], "candidate_item_id": item["item_id"], "review_id": item["review_id"], "tombstoned_at": utc_now()}
        else:
            if data["items"].get(item["item_id"], {}).get("candidate_item_id") == item["item_id"]:
                continue
            data["items"].pop(item["target_ref"], None)
            data["items"][item["item_id"]] = _approved_item(candidate, item, reviews[item["item_id"]])
    data["updated_at"] = utc_now()
    atomic_write_json(path, data, private=True)


def _approved_item(candidate: Mapping[str, object], item: Mapping[str, object], review: Mapping[str, object]) -> dict[str, object]:
    artifact = dict(item["artifact"])
    admitted = _parse_time(str(review["reviewed_at"]))
    retention = build_retention(str(item["retention"]["class"]), record_type="fact", admitted_at=admitted, ttl_days=item["retention"].get("ttl_days"))
    days = item["artifact"].get("revalidation_days")
    revalidation = {"deadline": _stamp(admitted + timedelta(days=days))} if isinstance(days, int) and days > 0 else {}
    artifact.update({"admission": {"state": "approved_manual", "review_id": review["review_id"], "reviewer_label": review["reviewer_label"], "admitted_at": review["reviewed_at"], "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION}, "retention": retention, "revalidation": revalidation, "batch_id": candidate["batch_id"], "candidate_item_id": item["item_id"], "operation_id": candidate["apply_operation_id"]})
    artifact["admission"]["payload_digest"] = canonical_payload_digest(artifact)
    return artifact


def _approved_reviews(paths: OmhPaths, candidate: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for item in candidate["items"]:
        value, error = read_json_object_result(_reviews_dir(paths) / f"{item['review_id']}.json")
        if error or not isinstance(value, dict) or not _review_matches(value, candidate, item):
            raise ValueError("exact immutable batch review is required")
        reviews[item["item_id"]] = value
    return reviews


def _revalidate(candidate: Mapping[str, object], reviews: Mapping[str, Mapping[str, object]]) -> None:
    control_values = (
        candidate.get("batch_id", ""),
        candidate.get("stage_operation_id", ""),
        candidate.get("apply_operation_id", ""),
        candidate.get("source_surface", ""),
    )
    if (
        any(not safe_token(str(value)) for value in control_values[:3])
        or any(classify_memory_admission(str(value))["status"] != "safe" for value in control_values)
        or candidate.get("source_class") not in SOURCE_CLASSES
    ):
        raise ValueError("batch candidate control metadata is invalid")
    for item in candidate["items"]:
        artifact = item.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("batch candidate linkage or safety is invalid")
        identifiers = (item.get("item_id", ""), item.get("review_id", ""), item.get("target_ref", ""))
        if (
            any(not safe_token(str(value)) for value in identifiers)
            or any(classify_memory_admission(str(value))["status"] != "safe" for value in identifiers)
            or item.get("op") not in _OPS
            or item.get("batch_id") != candidate.get("batch_id")
            or evaluate_renderable_strings(artifact).get("status") != "safe"
            or stable_artifact_identity(artifact) != item["artifact_identity"]
            or canonical_payload_digest(artifact) != item["payload_digest"]
        ):
            raise ValueError("batch candidate linkage or safety is invalid")
        scope = _scope(item["scope"])
        if scope != artifact.get("scope"):
            raise ValueError("batch candidate scope linkage is invalid")
        if item.get("op") == "change_scope":
            _scope(item["from_scope"])
        build_retention(str(item["retention"]["class"]), record_type="fact", admitted_at=_utc(None), ttl_days=item["retention"].get("ttl_days"))
        review = reviews[item["item_id"]]
        if (
            review["decision"] != "remember"
            or classify_memory_admission(str(review.get("reviewer_label", "")))["status"] != "safe"
        ):
            raise ValueError("unapproved or unsafe batch review")


def _review_record(candidate: Mapping[str, object], item: Mapping[str, object], decision: str, label: str, reviewed_at: str) -> dict[str, object]:
    return {
        "schema_version": PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION,
        "batch_id": candidate["batch_id"],
        "candidate_digest": canonical_payload_digest(dict(candidate)),
        **{key: item.get(key) for key in _REVIEW_BOUND_ITEM_KEYS},
        "decision": decision,
        "reviewer_label": label,
        "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION,
        "reviewed_at": reviewed_at,
    }


def _review_matches(review: Mapping[str, object], candidate: Mapping[str, object], item: Mapping[str, object]) -> bool:
    return (
        review.get("schema_version") == PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION
        and all(review.get(key) == item.get(key) for key in _REVIEW_BOUND_ITEM_KEYS)
        and review.get("batch_id") == candidate.get("batch_id")
        and review.get("candidate_digest") == canonical_payload_digest(dict(candidate))
        and review.get("decision") in _DECISIONS
        and isinstance(review.get("reviewer_label"), str)
        and bool(review["reviewer_label"])
    )


def _same_review(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    keys = (*_REVIEW_BOUND_ITEM_KEYS, "batch_id", "candidate_digest", "decision", "reviewer_label")
    return all(left.get(key) == right.get(key) for key in keys)


def _decisions(candidate: Mapping[str, object], raw: Mapping[str, object] | list[Mapping[str, object]]) -> dict[str, str]:
    values = raw if isinstance(raw, Mapping) else {str(item.get("item_id", "")): item.get("decision") for item in raw if isinstance(item, Mapping)}
    expected = {item["item_id"] for item in candidate["items"]}
    if set(values) != expected:
        raise ValueError("review requires one exact decision per staged item")
    normalized = {str(item_id): str(value).lower() for item_id, value in values.items()}
    if not all(value in _DECISIONS for value in normalized.values()):
        raise ValueError("unsupported batch review decision")
    return normalized


def _candidate(paths: OmhPaths, batch_id: str) -> dict[str, Any]:
    if not safe_token(batch_id) or classify_memory_admission(batch_id)["status"] != "safe":
        raise ValueError("unsafe batch id")
    value, error = read_json_object_result(paths.memory_dir / _candidate_relative(batch_id))
    if error or not isinstance(value, dict) or value.get("schema_version") != BATCH_CANDIDATE_SCHEMA_VERSION or value.get("batch_id") != batch_id or not isinstance(value.get("items"), list) or not value["items"]:
        raise ValueError("unknown or malformed batch candidate")
    return value


def _validate_batch(batch: Mapping[str, object]) -> None:
    if not isinstance(batch, Mapping) or batch.get("schema_version") != _LEGACY_BATCH_SCHEMA_VERSION or not isinstance(batch.get("updates"), list) or not batch["updates"]:
        raise ValueError("memory update batch requires memory_update_batch/v1 updates")


def _scope(value: object) -> dict[str, object]:
    scope = canonical_memory_scope(dict(value) if isinstance(value, Mapping) else {})
    kind, ref = str(scope["kind"]), str(scope["ref"])
    if (
        not safe_token(kind)
        or not safe_token(ref)
        or classify_memory_admission("\n".join((kind, ref)))["status"] != "safe"
    ):
        raise ValueError("unsafe memory scope")
    return {"kind": kind, "ref": ref}


def _existing(paths: OmhPaths, scope: Mapping[str, object], target_ref: str) -> dict[str, Any] | None:
    value, error = read_json_object_result(paths.memory_dir / _relative_scope(scope))
    if error or not isinstance(value, dict):
        return None
    item = value.get("items", {}).get(target_ref) if isinstance(value.get("items"), dict) else None
    return item if isinstance(item, dict) else None


def _item_scopes(item: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return (item["from_scope"], item["scope"]) if item.get("op") == "change_scope" else (item["scope"],)


def _relative_scope(scope: Mapping[str, object]) -> str:
    return "scopes/project.json" if scope["kind"] == "project" else f"scopes/{scope['kind']}s/{scope['ref']}.json"


def _candidate_relative(batch_id: str) -> str:
    return f"candidates/{batch_id}.json"


def _reviews_dir(paths: OmhPaths) -> Path:
    return paths.memory_dir / "reviews"


def _distinct_targets(items: list[dict[str, object]]) -> None:
    targets = [(item["op"], item["target_ref"], _relative_scope(item["scope"])) for item in items]
    if len(targets) != len(set(targets)):
        raise ValueError("batch has ambiguous scope-item targets")


def _batch_view(candidate: Mapping[str, object], *, status: str) -> dict[str, object]:
    return {"schema_version": BATCH_CANDIDATE_SCHEMA_VERSION, "status": status, "batch_id": candidate["batch_id"], "operation_id": candidate["apply_operation_id"], "items": [{"item_id": item["item_id"], "candidate_revision": item["candidate_revision"], "op": item["op"], "scope": item["scope"], "retention_class": item["retention"]["class"], "source_class": item["artifact"]["source_class"], "admission_state": "pending_review"} for item in candidate["items"]], "claim_boundary": "Staged batch candidates are review-only and never prompt eligible."}


def _opaque(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _label(value: object) -> str:
    text = str(value or "operator").strip()
    if not text:
        raise ValueError("reviewer label is required")
    if classify_memory_admission(text)["status"] != "safe":
        raise ValueError("credential-like batch label is not allowed")
    return text[:120]


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
