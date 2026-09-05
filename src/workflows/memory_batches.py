"""Fail-closed staged scope-memory batches."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..plugin_bundle.omh.memory_governance import MEMORY_GOVERNANCE_POLICY_VERSION, MEMORY_SCOPE_SCHEMA_VERSION, PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION, SOURCE_CLASSES, build_retention, canonical_memory_scope, canonical_payload_digest, classify_memory_admission, evaluate_renderable_strings, stable_artifact_identity
from ..system.local_store import atomic_write_json, file_lock, read_json_object_result
from ..system.paths import OmhPaths
from ._memory_store_validation import safe_token
from .memory_store import (
    MemoryOperationIdentityError,
    checked_memory_directory,
    checked_memory_json_path,
    ensure_memory_directory,
    run_memory_operation,
)

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
_REVIEW_KEYS = frozenset(
    {
        "schema_version",
        "batch_id",
        "candidate_digest",
        *_REVIEW_BOUND_ITEM_KEYS,
        "decision",
        "reviewer_label",
        "policy_version",
        "reviewed_at",
    }
)
_REVIEW_REQUEST_SCHEMA_VERSION = "memory_update_batch_review_request/v1"
_REVIEW_REQUEST_KEYS = frozenset(
    {"schema_version", "candidate_digest", "decisions", "reviewer_label", "policy_version", "reviewed_at"}
)


class _ScopePreconditionChanged(RuntimeError):
    pass


def stage_memory_update_batch(paths: OmhPaths, batch: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
    _validate_batch(batch)
    current = _utc(now)
    batch_id = _opaque("batch")
    source_class = str(batch.get("source_class", "omh_local"))
    if source_class not in SOURCE_CLASSES:
        raise ValueError("unsupported batch source_class")
    scope_cache: dict[str, dict[str, Any] | None] = {}
    items = [_proposal(paths, raw, batch, batch_id, current, source_class, scope_cache) for raw in batch["updates"]]
    _distinct_targets(items)
    for item in items:
        for scope in _item_scopes(item):
            _scope_snapshot(paths, scope, scope_cache)
    _reject_live_logical_target_collisions(items, scope_cache)
    scope_preconditions = {
        target: _scope_precondition_digest(value, items, target)
        for target, value in sorted(scope_cache.items())
    }
    candidate = {"schema_version": BATCH_CANDIDATE_SCHEMA_VERSION, "batch_id": batch_id, "candidate_revision": 1, "stage_operation_id": _opaque("op_stage"), "apply_operation_id": _opaque("op_apply"), "status": "pending_review", "source_class": source_class, "source_surface": _label(batch.get("source_surface", "api")), "created_at": _stamp(current), "admission": {"state": "pending_review", "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION}, "scope_preconditions": scope_preconditions, "items": items}
    target = _candidate_relative(batch_id)
    ensure_memory_directory(paths, "candidates")
    checked_memory_json_path(paths, target)

    def write_candidate(check_paths: OmhPaths, step: dict[str, str]) -> None:
        if step["action"] != "write_batch_candidate" or step["target"] != target:
            raise ValueError("unexpected batch staging operation")
        path = checked_memory_json_path(check_paths, target)
        present, error = read_json_object_result(path)
        if error:
            raise ValueError("batch candidate is corrupt")
        if present is None:
            atomic_write_json(path, candidate, private=True)
        elif present != candidate:
            raise ValueError("batch candidate identity collision")

    operation = run_memory_operation(paths, operation_id=candidate["stage_operation_id"], operation_type="stage_memory_batch", steps=[{"name": "stage_batch_candidate", "action": "write_batch_candidate", "target": target}], step_writer=write_candidate, now=current)
    if operation.get("state") != "completed":
        raise ValueError("batch staging did not complete")
    return _batch_view(candidate, status="pending_review")


def review_memory_update_batch(paths: OmhPaths, batch_id: str, decisions: Mapping[str, object] | list[Mapping[str, object]], *, reviewer_label: str = "operator", now: datetime | None = None) -> dict[str, object]:
    label = _label(reviewer_label)
    reviewed_at = _stamp(_utc(now))
    with file_lock(paths.memory_index_path, private=True):
        candidate = _candidate(paths, batch_id)
        _validate_review_membership(candidate)
        decision_map = _decisions(candidate, decisions)
        ensure_memory_directory(paths, "reviews")
        request = candidate.get("review_request")
        if request is None:
            if candidate.get("review_seals") or any(
                _review_path(paths, str(item["review_id"])).exists() for item in candidate["items"]
            ):
                raise ValueError("batch review is immutable")
            request = _review_request(candidate, decision_map, label, reviewed_at)
            candidate = {**candidate, "review_request": request}
            atomic_write_json(_candidate_path(paths, batch_id), candidate, private=True)
        elif not _review_request_matches(request, candidate, decision_map, label):
            raise ValueError("batch review is immutable")
        reviewed_at = str(request["reviewed_at"])
        reviews = [_review_record(candidate, item, decision_map[item["item_id"]], label, reviewed_at) for item in candidate["items"]]
        existing_seals = candidate.get("review_seals", {})
        if not isinstance(existing_seals, dict):
            raise ValueError("batch review linkage is corrupt")
        seals: dict[str, str] = {}
        items_by_review = {str(item["review_id"]): item for item in candidate["items"]}
        expected_review_ids = set(items_by_review)
        expected_item_ids = {str(item["item_id"]) for item in candidate["items"]}
        if _existing_batch_review_ids(paths, batch_id) - expected_review_ids:
            raise ValueError("batch review is immutable")
        if existing_seals and set(existing_seals) != expected_item_ids:
            raise ValueError("batch review is immutable")
        for review in reviews:
            path = _review_path(paths, str(review["review_id"]))
            item = items_by_review[str(review["review_id"])]
            if existing_seals:
                present, error = read_json_object_result(path)
                if (
                    error
                    or present is None
                    or not _review_base_matches(present, candidate, item)
                    or present.get("decision") != review.get("decision")
                    or present.get("reviewer_label") != review.get("reviewer_label")
                    or existing_seals.get(str(item["item_id"])) != _review_digest(present)
                ):
                    raise ValueError("batch review is immutable")
                sealed = dict(present)
            else:
                # Unsealed reviews are interrupted-write debris, not
                # executable authorization. Replace them before committing
                # the complete seal set on the candidate. A digest mismatch,
                # however, proves the candidate itself moved since the review
                # file was written and must fail closed.
                present, error = read_json_object_result(path)
                if (
                    not error
                    and isinstance(present, Mapping)
                    and present.get("candidate_digest") != _candidate_digest(candidate)
                ):
                    raise ValueError("batch review is immutable")
                atomic_write_json(path, review, private=True)
                sealed = review
            seals[str(item["item_id"])] = _review_digest(sealed)

        if existing_seals and existing_seals != seals:
            raise ValueError("batch review is immutable")
        sealed_candidate = {**candidate, "review_seals": seals}
        if sealed_candidate != candidate:
            atomic_write_json(_candidate_path(paths, batch_id), sealed_candidate, private=True)
    return {"schema_version": BATCH_REVIEW_SCHEMA_VERSION, "status": "reviewed", "batch_id": candidate["batch_id"], "reviewer_label": label, "items": [{"item_id": item["item_id"], "review_id": item["review_id"], "decision": decision_map[item["item_id"]]} for item in candidate["items"]]}


def apply_approved_memory_update_batch(paths: OmhPaths, batch_id: str, *, now: datetime | None = None, write_hook: Callable[[str], None] | None = None) -> dict[str, object]:
    candidate = _candidate(paths, batch_id)
    try:
        reviews = _approved_reviews(paths, candidate)
        _revalidate(candidate, reviews)
        preconditions = _scope_preconditions(candidate)
    except ValueError:
        return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "review_required", "reason_code": "review_linkage_invalid", "applied": False, "batch_id": batch_id}
    if any(review["decision"] != "remember" for review in reviews.values()):
        return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "review_required", "reason_code": "review_required", "applied": False, "batch_id": batch_id}
    scopes = sorted({_relative_scope(scope) for item in candidate["items"] for scope in _item_scopes(item)})
    scope_steps = [
        {"name": f"write_scope_{index}", "action": "write_batch_scope", "target": target, "revision": preconditions[target]}
        for index, target in enumerate(scopes, start=1)
    ]

    def assert_precondition(check_paths: OmhPaths, step: dict[str, str]) -> None:
        try:
            snapshot = _scope_snapshot_by_target(check_paths, step["target"])
        except ValueError as exc:
            raise _ScopePreconditionChanged("reviewed scope is unreadable before apply") from exc
        if snapshot is not None and (
            not isinstance(snapshot.get("items"), Mapping)
            or not isinstance(snapshot.get("tombstones", {}), Mapping)
        ):
            raise _ScopePreconditionChanged("reviewed scope is malformed before apply")
        if (
            _scope_precondition_digest(snapshot, candidate["items"], step["target"])
            != step["revision"]
            and not _scope_matches_candidate_apply(
                snapshot,
                candidate,
                reviews,
                step["target"],
            )
        ):
            raise _ScopePreconditionChanged("reviewed scope changed before apply")

    def preflight(check_paths: OmhPaths) -> None:
        for scope_step in scope_steps:
            assert_precondition(check_paths, scope_step)

    def write_scopes(check_paths: OmhPaths, step: dict[str, str]) -> str:
        if step["action"] != "write_batch_scopes":
            raise ValueError("unexpected batch apply operation")
        # Run every interruption/drift hook before rechecking any target so a
        # later target cannot fail after an earlier scope has been mutated.
        if write_hook:
            for scope_step in scope_steps:
                write_hook(scope_step["name"])
        for scope_step in scope_steps:
            assert_precondition(check_paths, scope_step)
        for scope_step in scope_steps:
            _apply_scope(
                check_paths,
                candidate,
                reviews,
                scope_step["target"],
                updated_at=step["revision"],
            )
        return "written"

    apply_revision = min(str(review["reviewed_at"]) for review in reviews.values())
    steps = [
        {
            "name": "write_reviewed_scopes",
            "action": "write_batch_scopes",
            "target": _candidate_relative(batch_id),
            "revision": apply_revision,
        }
    ]

    try:
        operation = run_memory_operation(
            paths,
            operation_id=str(candidate["apply_operation_id"]),
            operation_type="apply_memory_batch",
            steps=steps,
            step_writer=write_scopes,
            preflight=preflight,
            now=now,
        )
    except _ScopePreconditionChanged:
        return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "review_required", "reason_code": "scope_precondition_changed", "applied": False, "batch_id": batch_id}
    except MemoryOperationIdentityError:
        return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "review_required", "reason_code": "operation_identity_conflict", "applied": False, "batch_id": batch_id}
    receipt = {key: operation["receipt"][key] for key in _RECEIPT_KEYS if key in operation.get("receipt", {})}
    return {"schema_version": BATCH_RECEIPT_SCHEMA_VERSION, "status": "applied" if operation.get("state") == "completed" else str(operation.get("state")), "applied": operation.get("state") == "completed", "batch_id": batch_id, "receipt": receipt}


def legacy_batch_review_required(paths: OmhPaths, batch: Mapping[str, object], *, dry_run: bool = False) -> dict[str, object]:
    _validate_batch(batch)
    return {"schema_version": _LEGACY_BATCH_SCHEMA_VERSION, "status": "review_required", "applied": False, "dry_run": bool(dry_run), "update_count": len(batch["updates"]), "claim_boundary": "Direct memory batches are review-required and do not write OMH memory."}


def _proposal(
    paths: OmhPaths,
    raw: object,
    batch: Mapping[str, object],
    batch_id: str,
    now: datetime,
    source_class: str,
    scope_cache: dict[str, dict[str, Any] | None],
) -> dict[str, object]:
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
    existing = _existing(paths, from_scope or scope, target_ref, scope_cache)
    existing_id = str(existing.get("item_id", "")) if existing else ""
    if existing and (
        not safe_token(existing_id)
        or classify_memory_admission(existing_id)["status"] != "safe"
    ):
        raise ValueError("unsafe legacy memory batch item")
    item_id = existing_id if existing else _opaque("item")
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


def _apply_scope(
    paths: OmhPaths,
    candidate: dict[str, Any],
    reviews: dict[str, dict[str, Any]],
    target: str,
    *,
    updated_at: str,
) -> None:
    matching = [item for item in candidate["items"] if target in {_relative_scope(scope) for scope in _item_scopes(item)}]
    if not matching:
        return
    scope = next(scope for item in matching for scope in _item_scopes(item) if _relative_scope(scope) == target)
    path = _checked_scope_path(paths, target)
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
            data["tombstones"][item["target_ref"]] = {
                "item_id": item["target_ref"],
                "operation_id": candidate["apply_operation_id"],
                "candidate_item_id": item["item_id"],
                "review_id": item["review_id"],
                "reason_code": "scope_changed",
                "tombstoned_at": updated_at,
            }
        elif op == "forget":
            data["items"].pop(item["target_ref"], None)
            data["tombstones"][item["target_ref"]] = {"item_id": item["target_ref"], "operation_id": candidate["apply_operation_id"], "candidate_item_id": item["item_id"], "review_id": item["review_id"], "tombstoned_at": updated_at}
        else:
            approved = _approved_item(candidate, item, reviews[item["item_id"]])
            if data["items"].get(item["item_id"]) == approved:
                continue
            data["items"].pop(item["target_ref"], None)
            data["items"][item["item_id"]] = approved
    data["updated_at"] = updated_at
    _checked_scope_path(paths, target)
    atomic_write_json(path, data, private=True)


def _scope_matches_candidate_apply(
    value: Mapping[str, object] | None,
    candidate: Mapping[str, object],
    reviews: Mapping[str, Mapping[str, object]],
    target: str,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    items = value.get("items")
    tombstones = value.get("tombstones", {})
    if not isinstance(items, Mapping) or not isinstance(tombstones, Mapping):
        return False
    candidate_items = candidate.get("items")
    if not isinstance(candidate_items, list):
        return False
    matching = [
        item
        for item in candidate_items
        if isinstance(item, Mapping)
        and target in {_relative_scope(scope) for scope in _item_scopes(item)}
    ]
    if not matching:
        return False
    expected_scope = next(
        scope
        for item in matching
        for scope in _item_scopes(item)
        if _relative_scope(scope) == target
    )
    if (
        value.get("schema_version") != MEMORY_SCOPE_SCHEMA_VERSION
        or value.get("scope") != dict(expected_scope)
    ):
        return False
    for item in matching:
        op = item.get("op")
        target_ref = str(item.get("target_ref", ""))
        item_id = str(item.get("item_id", ""))
        review_id = str(item.get("review_id", ""))
        if op == "change_scope" and target == _relative_scope(item["from_scope"]):
            marker = tombstones.get(target_ref)
            if target_ref in items or not isinstance(marker, Mapping):
                return False
            if any(
                marker.get(key) != expected
                for key, expected in {
                    "operation_id": candidate.get("apply_operation_id"),
                    "candidate_item_id": item_id,
                    "review_id": review_id,
                    "reason_code": "scope_changed",
                }.items()
            ):
                return False
        elif op == "forget":
            marker = tombstones.get(target_ref)
            if target_ref in items or not isinstance(marker, Mapping):
                return False
            if any(
                marker.get(key) != expected
                for key, expected in {
                    "operation_id": candidate.get("apply_operation_id"),
                    "candidate_item_id": item_id,
                    "review_id": review_id,
                }.items()
            ):
                return False
        else:
            review = reviews.get(item_id)
            if not isinstance(review, Mapping):
                return False
            expected_item = _approved_item(candidate, item, review)
            if items.get(item_id) != expected_item:
                return False
            if target_ref != item_id and target_ref in items:
                return False
    return True


def _approved_item(candidate: Mapping[str, object], item: Mapping[str, object], review: Mapping[str, object]) -> dict[str, object]:
    artifact = dict(item["artifact"])
    admitted = _parse_time(str(review["reviewed_at"]))
    retention = build_retention(str(item["retention"]["class"]), record_type="fact", admitted_at=admitted, ttl_days=item["retention"].get("ttl_days"))
    days = item["artifact"].get("revalidation_days")
    revalidation = {"deadline": _stamp(admitted + timedelta(days=days))} if isinstance(days, int) and days > 0 else {}
    artifact.update({"admission": {"state": "approved_manual", "review_id": review["review_id"], "reviewer_label": review["reviewer_label"], "admitted_at": review["reviewed_at"], "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION}, "retention": retention, "revalidation": revalidation, "batch_id": candidate["batch_id"], "candidate_item_id": item["item_id"], "operation_id": candidate["apply_operation_id"], "operation": item["op"]})
    if item["op"] == "dismiss_conflict":
        artifact["dismissed_at"] = review["reviewed_at"]
    artifact["admission"]["payload_digest"] = canonical_payload_digest(artifact)
    return artifact


def _approved_reviews(paths: OmhPaths, candidate: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    seals = candidate.get("review_seals")
    items = candidate.get("items")
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        raise ValueError("batch candidate items are malformed")
    expected_item_ids = {str(item.get("item_id", "")) for item in items}
    if not isinstance(seals, Mapping) or set(seals) != expected_item_ids:
        raise ValueError("exact immutable batch review seals are required")
    reviews: dict[str, dict[str, Any]] = {}
    for item in items:
        value, error = read_json_object_result(_review_path(paths, str(item["review_id"])))
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
        "candidate_digest": _candidate_digest(candidate),
        **{key: item.get(key) for key in _REVIEW_BOUND_ITEM_KEYS},
        "decision": decision,
        "reviewer_label": label,
        "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION,
        "reviewed_at": reviewed_at,
    }


def _review_request(
    candidate: Mapping[str, object],
    decisions: Mapping[str, str],
    label: str,
    reviewed_at: str,
) -> dict[str, object]:
    return {
        "schema_version": _REVIEW_REQUEST_SCHEMA_VERSION,
        "candidate_digest": _candidate_subject_digest(candidate),
        "decisions": {key: decisions[key] for key in sorted(decisions)},
        "reviewer_label": label,
        "policy_version": MEMORY_GOVERNANCE_POLICY_VERSION,
        "reviewed_at": reviewed_at,
    }


def _review_request_matches(
    request: object,
    candidate: Mapping[str, object],
    decisions: Mapping[str, str],
    label: str,
) -> bool:
    if not isinstance(request, Mapping) or set(request) != _REVIEW_REQUEST_KEYS:
        return False
    items = candidate.get("items")
    if not isinstance(items, list):
        return False
    expected_ids = {str(item.get("item_id", "")) for item in items if isinstance(item, Mapping)}
    return (
        request.get("schema_version") == _REVIEW_REQUEST_SCHEMA_VERSION
        and request.get("candidate_digest") == _candidate_subject_digest(candidate)
        and request.get("decisions") == {key: decisions[key] for key in sorted(decisions)}
        and set(decisions) == expected_ids
        and request.get("reviewer_label") == label
        and request.get("policy_version") == MEMORY_GOVERNANCE_POLICY_VERSION
        and _canonical_review_time(request.get("reviewed_at"))
    )


def _review_matches(review: Mapping[str, object], candidate: Mapping[str, object], item: Mapping[str, object]) -> bool:
    seals = candidate.get("review_seals")
    return (
        _review_base_matches(review, candidate, item)
        and isinstance(seals, Mapping)
        and seals.get(str(item.get("item_id", ""))) == _review_digest(review)
    )


def _review_base_matches(review: Mapping[str, object], candidate: Mapping[str, object], item: Mapping[str, object]) -> bool:
    return (
        set(review) == _REVIEW_KEYS
        and review.get("schema_version") == PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION
        and all(review.get(key) == item.get(key) for key in _REVIEW_BOUND_ITEM_KEYS)
        and review.get("batch_id") == candidate.get("batch_id")
        and review.get("candidate_digest") == _candidate_digest(candidate)
        and review.get("decision") in _DECISIONS
        and isinstance(review.get("reviewer_label"), str)
        and bool(review["reviewer_label"])
        and classify_memory_admission(str(review["reviewer_label"]))["status"] == "safe"
        and review.get("policy_version") == MEMORY_GOVERNANCE_POLICY_VERSION
        and _canonical_review_time(review.get("reviewed_at"))
    )


def _candidate_subject_digest(candidate: Mapping[str, object]) -> str:
    payload = {
        str(key): value
        for key, value in candidate.items()
        if key not in {"review_request", "review_seals"}
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_digest(candidate: Mapping[str, object]) -> str:
    payload = {str(key): value for key, value in candidate.items() if key != "review_seals"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _review_digest(review: Mapping[str, object]) -> str:
    canonical = json.dumps(dict(review), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_review_time(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return _stamp(_parse_time(value)) == value
    except (TypeError, ValueError):
        return False


def _validate_review_membership(candidate: Mapping[str, object]) -> None:
    items = candidate.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("batch review membership is malformed")
    for item in items:
        identifiers = (
            item.get("item_id", ""),
            item.get("review_id", ""),
            item.get("target_ref", ""),
        )
        artifact = item.get("artifact")
        if (
            any(not safe_token(str(value)) for value in identifiers)
            or any(classify_memory_admission(str(value))["status"] != "safe" for value in identifiers)
            or item.get("op") not in _OPS
            or item.get("batch_id") != candidate.get("batch_id")
            or not isinstance(artifact, dict)
            or evaluate_renderable_strings(artifact).get("status") != "safe"
            or stable_artifact_identity(artifact) != item.get("artifact_identity")
            or canonical_payload_digest(artifact) != item.get("payload_digest")
        ):
            raise ValueError("batch review membership is malformed")
        scope = _scope(item.get("scope"))
        if artifact.get("scope") != scope or artifact.get("retention") != item.get("retention"):
            raise ValueError("batch review membership is malformed")
        if item.get("op") == "change_scope":
            _scope(item.get("from_scope"))
    try:
        _distinct_targets(items)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("batch review membership is ambiguous") from exc
    review_ids = [str(item.get("review_id", "")) for item in items]
    if not all(review_ids) or len(review_ids) != len(set(review_ids)):
        raise ValueError("batch review membership is ambiguous")


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
    value, error = read_json_object_result(_candidate_path(paths, batch_id))
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


def _existing(
    paths: OmhPaths,
    scope: Mapping[str, object],
    target_ref: str,
    scope_cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    value = _scope_snapshot(paths, scope, scope_cache)
    if not isinstance(value, dict):
        return None
    item = value.get("items", {}).get(target_ref) if isinstance(value.get("items"), dict) else None
    return item if isinstance(item, dict) else None


def _scope_snapshot(
    paths: OmhPaths,
    scope: Mapping[str, object],
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    target = _relative_scope(scope)
    if target not in cache:
        cache[target] = _scope_snapshot_by_target(paths, target)
    return cache[target]


def _scope_snapshot_by_target(paths: OmhPaths, target: str) -> dict[str, Any] | None:
    path = _checked_scope_path(paths, target)
    value, error = read_json_object_result(path)
    if error or (value is not None and not isinstance(value, dict)):
        raise ValueError("scope file is corrupt")
    return value


def _checked_scope_path(paths: OmhPaths, target: str) -> Path:
    root = paths.memory_dir
    relative = Path(target)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("scope path is unsafe")
    path = root / relative
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("scope path is unsafe")
    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
        raise ValueError("scope path is unsafe")
    return path


def _scope_precondition_digest(
    value: Mapping[str, object] | None,
    items: list[dict[str, object]] | list[object],
    target: str,
) -> str:
    matching = [
        item
        for item in items
        if isinstance(item, Mapping) and target in {_relative_scope(scope) for scope in _item_scopes(item)}
    ]
    item_keys: set[str] = set()
    logical_keys: set[str] = set()
    tombstone_keys: set[str] = set()
    for item in matching:
        target_ref = str(item.get("target_ref", ""))
        item_id = str(item.get("item_id", ""))
        artifact = item.get("artifact")
        if isinstance(artifact, Mapping):
            logical_keys.add(str(artifact.get("key", "")))
        item_keys.add(target_ref)
        if not (
            item.get("op") == "forget"
            or (item.get("op") == "change_scope" and target == _relative_scope(item["from_scope"]))
        ):
            item_keys.add(item_id)
        if item.get("op") == "forget" or (
            item.get("op") == "change_scope"
            and target == _relative_scope(_item_scopes(item)[0])
        ):
            tombstone_keys.add(target_ref)
    data = dict(value) if isinstance(value, Mapping) else None
    current_items = data.get("items", {}) if data is not None else {}
    current_tombstones = data.get("tombstones", {}) if data is not None else {}
    expected_scope = next(
        scope
        for item in matching
        for scope in _item_scopes(item)
        if _relative_scope(scope) == target
    )
    projection = {
        "schema_version": (
            data.get("schema_version") if data is not None else MEMORY_SCOPE_SCHEMA_VERSION
        ),
        "scope": data.get("scope") if data is not None else dict(expected_scope),
        "items": (
            {key: current_items.get(key) for key in sorted(item_keys)}
            if isinstance(current_items, Mapping)
            else current_items
        ),
        "tombstones": (
            {key: current_tombstones.get(key) for key in sorted(tombstone_keys)}
            if isinstance(current_tombstones, Mapping)
            else current_tombstones
        ),
        "logical_items": (
            {
                str(item_id): item
                for item_id, item in sorted(current_items.items(), key=lambda pair: str(pair[0]))
                if isinstance(item, Mapping) and str(item.get("key", "")) in logical_keys
            }
            if isinstance(current_items, Mapping)
            else current_items
        ),
    }
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scope_preconditions(candidate: Mapping[str, object]) -> dict[str, str]:
    raw = candidate.get("scope_preconditions")
    items = candidate.get("items")
    if not isinstance(items, list):
        raise ValueError("batch scope preconditions are invalid")
    expected = {
        _relative_scope(scope)
        for item in items
        if isinstance(item, Mapping)
        for scope in _item_scopes(item)
    }
    if (
        not isinstance(raw, Mapping)
        or set(raw) != expected
        or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in raw.values())
    ):
        raise ValueError("batch scope preconditions are invalid")
    return {str(key): str(value) for key, value in raw.items()}


def _item_scopes(item: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return (item["from_scope"], item["scope"]) if item.get("op") == "change_scope" else (item["scope"],)


def _relative_scope(scope: Mapping[str, object]) -> str:
    return "scopes/project.json" if scope["kind"] == "project" else f"scopes/{scope['kind']}s/{scope['ref']}.json"


def _candidate_relative(batch_id: str) -> str:
    return f"candidates/{batch_id}.json"


def _candidate_path(paths: OmhPaths, batch_id: str) -> Path:
    return checked_memory_json_path(paths, _candidate_relative(batch_id))


def _review_path(paths: OmhPaths, review_id: str) -> Path:
    return checked_memory_json_path(paths, f"reviews/{review_id}.json")


def _reviews_dir(paths: OmhPaths) -> Path:
    return checked_memory_directory(paths, "reviews")


def _existing_batch_review_ids(paths: OmhPaths, batch_id: str) -> set[str]:
    review_ids: set[str] = set()
    directory = _reviews_dir(paths)
    if not directory.exists():
        return review_ids
    for path in directory.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        value, error = read_json_object_result(path)
        if not error and isinstance(value, Mapping) and value.get("batch_id") == batch_id:
            review_ids.add(str(value.get("review_id", "")))
    return review_ids


def _distinct_targets(items: list[dict[str, object]]) -> None:
    scope_item_targets: set[tuple[str, str]] = set()
    logical_targets: set[tuple[str, str]] = set()
    candidate_item_ids: set[str] = set()
    for item in items:
        op = str(item["op"])
        target_ref = str(item["target_ref"])
        item_id = str(item["item_id"])
        if item_id in candidate_item_ids:
            raise ValueError("batch has ambiguous candidate item ids")
        candidate_item_ids.add(item_id)
        destination_scope = item.get("scope")
        if not isinstance(destination_scope, Mapping):
            raise ValueError("batch has malformed logical target")
        destination_target = _relative_scope(destination_scope)
        item_targets: set[tuple[str, str]] = set()
        for scope in _item_scopes(item):
            scope_target = _relative_scope(scope)
            item_targets.add((scope_target, target_ref))
            if op != "forget" and scope_target == destination_target:
                item_targets.add((scope_target, item_id))
        if scope_item_targets & item_targets:
            raise ValueError("batch has ambiguous scope-item targets")
        scope_item_targets.update(item_targets)

        artifact = item.get("artifact")
        if not isinstance(artifact, Mapping):
            raise ValueError("batch has malformed logical target")
        logical_key = str(artifact.get("key", ""))
        item_logical_targets = {
            (_relative_scope(scope), logical_key)
            for scope in _item_scopes(item)
        }
        if logical_targets & item_logical_targets:
            raise ValueError("batch has ambiguous logical targets")
        logical_targets.update(item_logical_targets)


def _reject_live_logical_target_collisions(
    items: list[dict[str, object]],
    scope_cache: Mapping[str, dict[str, Any] | None],
) -> None:
    for item in items:
        if item.get("op") == "forget":
            continue
        scope = item.get("scope")
        artifact = item.get("artifact")
        if not isinstance(scope, Mapping) or not isinstance(artifact, Mapping):
            raise ValueError("batch has malformed logical target")
        current = scope_cache.get(_relative_scope(scope))
        current_items = current.get("items", {}) if isinstance(current, Mapping) else {}
        if not isinstance(current_items, Mapping):
            continue
        logical_key = str(artifact.get("key", ""))
        allowed_refs = {str(item.get("target_ref", "")), str(item.get("item_id", ""))}
        if any(
            str(ref) not in allowed_refs
            and isinstance(value, Mapping)
            and str(value.get("key", "")) == logical_key
            for ref, value in current_items.items()
        ):
            raise ValueError("batch has ambiguous live logical target")


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
