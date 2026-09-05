"""Report-first, transaction-owned Phase 3 memory lifecycle planning."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime

from ..plugin_bundle.omh.memory_governance import (
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    canonical_memory_scope,
    contains_credential_like_material,
    evaluate_renderable_strings,
)
from ..system.paths import OmhPaths
from ._memory_lifecycle_model import LifecycleMutation, LifecyclePlan, LifecycleTransactionExecutor, MAX_MANIFEST_TARGETS
from ._memory_lifecycle_plans import (
    _admission_state,
    _approved_record,
    _archived_record,
    _current_record,
    _execute_plan,
    _expiry_reason,
    _manifest,
    _pending_candidate,
    _plan,
    _prune_findings,
    _prune_mutations,
    _rejected,
    _require_guard,
    _retention_class,
    _review,
    _scope,
    _tombstone,
)
from ._memory_lifecycle_scan import parse_time, read_json, rejected_outcomes, safe_token, stamp

RECEIPT_SCHEMA_VERSION = "memory_lifecycle_receipt/v1"
_RECEIPT_FIELDS = frozenset({"schema_version", "operation_id", "operation_type", "record_id", "revision", "scope", "actor_class", "created_at", "completed_at", "state", "outcomes"})
_OUTCOME_FIELDS = frozenset({"target_id", "artifact_kind", "outcome", "reason_code"})
_ALLOWED_OUTCOMES = frozenset({"written", "moved", "rewritten", "removed", "already_absent", "rejected", "unlinked_preserved", "unsupported_or_corrupt", "external_excluded"})


def lifecycle_replay_status(record: Mapping[str, object], *, now: datetime) -> dict[str, object]:
    reason = _expiry_reason(record, now)
    state = _admission_state(record)
    scope_value = record.get("scope")
    try:
        scope = canonical_memory_scope(dict(scope_value) if isinstance(scope_value, Mapping) else {})
    except (TypeError, ValueError):
        scope = {"kind": "redacted", "ref": "redacted"}
    public_scope = {key: _public_label(scope.get(key, "")) for key in ("kind", "ref")}
    revision = record.get("revision")
    return {
        "record_id": _public_label(record.get("record_id", "")),
        "revision": revision if isinstance(revision, int) and not isinstance(revision, bool) else None,
        "scope": public_scope,
        "admission_state": _public_label(state),
        "retention_class": _public_label(_retention_class(record)),
        "replay_eligible": reason == "eligible" and state in {"approved_manual", "approved_auto_safe"},
        "reason_code": reason if reason != "eligible" else ("eligible" if state in {"approved_manual", "approved_auto_safe"} else "review_required"),
    }


def _public_label(value: object) -> str:
    text = str(value or "")
    return "redacted" if contains_credential_like_material(text) else text


def build_memory_retirement(paths: OmhPaths, record_id: str, revision: int, *, now: datetime) -> LifecyclePlan:
    record, error = _current_record(paths, record_id, revision)
    if error:
        return _rejected("retire", record_id, revision, now, error)
    if _retention_class(record) != "standard" or _expiry_reason(record, now) != "expired_standard":
        return _rejected("retire", record_id, revision, now, "retire_requires_expired_standard")
    archive = f"archive/{record_id}.r{revision}.json"
    if (paths.memory_dir / archive).exists():
        return _rejected("retire", record_id, revision, now, "archive_conflict")
    tombstone_id = f"retired-{record_id}-r{revision}"
    tombstone = _tombstone(tombstone_id, record_id, revision, _scope(record), "retired_archive", now)
    manifest = _manifest(((f"record:{record_id}:r{revision}", "record", f"records/{record_id}.json"), (f"tombstone:{tombstone_id}", "tombstone", f"tombstones/{tombstone_id}.json")))
    mutations = (LifecycleMutation("archive_current", "move", archive, f"record:{record_id}:r{revision}", "record", f"records/{record_id}.json"), LifecycleMutation("write_retired_tombstone", "write", f"tombstones/{tombstone_id}.json", f"tombstone:{tombstone_id}", "tombstone", payload=tombstone))
    return _plan("retire", record_id, revision, _scope(record), now, manifest, mutations)


def apply_memory_retirement(paths: OmhPaths, plan: LifecyclePlan, *, transaction_executor: LifecycleTransactionExecutor) -> dict[str, object]:
    _require_guard(paths, plan, "records")
    if (paths.memory_dir / plan.mutations[0].target).exists():
        raise ValueError("operation_guard_mismatch")
    return _execute(paths, plan, transaction_executor)


def build_memory_restore(paths: OmhPaths, record_id: str, revision: int, *, now: datetime, candidate_id: str | None = None) -> LifecyclePlan:
    archived, relative, error = _archived_record(paths, record_id, revision)
    if error:
        return _rejected("restore", record_id, revision, now, error)
    if (paths.memory_dir / f"tombstones/hard-deleted-{record_id}-r{revision}.json").exists():
        return _rejected("restore", record_id, revision, now, "tombstoned_identity")
    current, _ = read_json(paths.memory_dir, f"records/{record_id}.json")
    if current is not None and isinstance(current.get("revision"), int) and current["revision"] >= revision:
        return _rejected("restore", record_id, revision, now, "newer_live_revision_conflict")
    candidate_id = candidate_id or _lifecycle_candidate_id("restore", record_id, revision)
    if not safe_token(candidate_id):
        raise ValueError("unsafe_candidate_id")
    safety = evaluate_renderable_strings(dict(archived))
    if safety["status"] != "safe":
        return _rejected("restore", record_id, revision, now, str(safety["reason_code"]))
    candidate = _pending_candidate(archived, candidate_id, revision + 1, "restore")
    manifest = _manifest(((f"archive:{record_id}:r{revision}", "archive", relative), (f"candidate:{candidate_id}", "candidate", f"candidates/{candidate_id}.json")))
    mutation = LifecycleMutation("write_restore_candidate", "write", f"candidates/{candidate_id}.json", f"candidate:{candidate_id}", "candidate", payload=candidate)
    return _plan("restore", record_id, revision, _scope(archived), now, manifest, (mutation,))


def apply_memory_restore(paths: OmhPaths, plan: LifecyclePlan, *, transaction_executor: LifecycleTransactionExecutor) -> dict[str, object]:
    _require_guard(paths, plan, "archive")
    if (paths.memory_dir / f"tombstones/hard-deleted-{plan.record_id}-r{plan.revision}.json").exists():
        raise ValueError("operation_guard_mismatch")
    current, _ = read_json(paths.memory_dir, f"records/{plan.record_id}.json")
    if current is not None and isinstance(current.get("revision"), int) and current["revision"] >= plan.revision:
        raise ValueError("operation_guard_mismatch")
    return _execute(paths, plan, transaction_executor)


def build_memory_reapproval(paths: OmhPaths, candidate_id: str, *, reviewer_claim: str, now: datetime) -> LifecyclePlan:
    if not safe_token(candidate_id):
        raise ValueError("unsafe_candidate_id")
    candidate, error = read_json(paths.memory_dir, f"candidates/{candidate_id}.json")
    if error or candidate is None or candidate.get("schema_version") != "project_memory_candidate/v2" or _admission_state(candidate) != "pending_review":
        return _rejected("reapprove", candidate_id, 0, now, "restore_candidate_not_pending")
    record_id, revision = str(candidate.get("record_id", "")), candidate.get("candidate_revision")
    if not safe_token(record_id) or not isinstance(revision, int) or revision < 2:
        return _rejected("reapprove", candidate_id, 0, now, "restore_candidate_invalid")
    reviewer_safety = evaluate_renderable_strings({"label": str(reviewer_claim or "")})
    if reviewer_safety["status"] != "safe":
        return _rejected("reapprove", record_id, revision, now, "unsafe_reviewer_claim")
    if (paths.memory_dir / f"records/{record_id}.json").exists():
        return _rejected("reapprove", record_id, revision, now, "newer_live_revision_conflict")
    replacement = candidate.get("replacement")
    if not isinstance(replacement, Mapping):
        return _rejected("reapprove", record_id, revision, now, "restore_candidate_invalid")
    safety = evaluate_renderable_strings(dict(replacement))
    if safety["status"] != "safe":
        return _rejected("reapprove", record_id, revision, now, str(safety["reason_code"]))
    record = _approved_record(replacement, record_id, revision, reviewer_claim, now)
    review_id = str(record["admission"]["review_id"])
    review = _review(record, review_id, reviewer_claim)
    updated = {**candidate, "status": "approved", "reviewed_at": stamp(now), "admission": record["admission"]}
    manifest = _manifest(((f"candidate:{candidate_id}", "candidate", f"candidates/{candidate_id}.json"), (f"record:{record_id}:r{revision}", "record", f"records/{record_id}.json"), (f"review:{review_id}", "review", f"reviews/{review_id}.json")))
    mutations = (LifecycleMutation("write_reapproved_record", "write", f"records/{record_id}.json", f"record:{record_id}:r{revision}", "record", payload=record), LifecycleMutation("write_reapproval_review", "write", f"reviews/{review_id}.json", f"review:{review_id}", "review", payload=review), LifecycleMutation("mark_candidate_reapproved", "write", f"candidates/{candidate_id}.json", f"candidate:{candidate_id}", "candidate", payload=updated))
    return _plan("reapprove", record_id, revision, _scope(record), now, manifest, mutations)


def apply_memory_reapproval(paths: OmhPaths, plan: LifecyclePlan, *, transaction_executor: LifecycleTransactionExecutor) -> dict[str, object]:
    _require_guard(paths, plan, "candidates")
    if (paths.memory_dir / f"records/{plan.record_id}.json").exists():
        raise ValueError("operation_guard_mismatch")
    return _execute(paths, plan, transaction_executor)


def build_memory_correction(paths: OmhPaths, record_id: str, revision: int, summary: str, *, now: datetime, candidate_id: str | None = None) -> LifecyclePlan:
    record, error = _current_record(paths, record_id, revision)
    if error:
        return _rejected("correct", record_id, revision, now, error)
    candidate_id = candidate_id or _lifecycle_candidate_id("correct", record_id, revision)
    if not safe_token(candidate_id):
        raise ValueError("unsafe_candidate_id")
    replacement = {**record, "summary": str(summary)[:500]}
    safety = evaluate_renderable_strings(replacement)
    if safety["status"] != "safe":
        return _rejected("correct", record_id, revision, now, str(safety["reason_code"]))
    successor = {"schema_version": PROJECT_MEMORY_RECORD_SCHEMA_VERSION, "id": record_id, "id_key": "record_id", "revision": revision + 1, "scope": _scope(record)}
    history = {**record, "superseded_by": successor}
    candidate = _pending_candidate(replacement, candidate_id, revision + 1, "correction")
    manifest = _manifest(((f"record:{record_id}:r{revision}", "record", f"records/{record_id}.json"), (f"history:{record_id}:r{revision}", "history", f"history/{record_id}.r{revision}.json"), (f"candidate:{candidate_id}", "candidate", f"candidates/{candidate_id}.json")))
    mutations = (LifecycleMutation("write_superseded_history", "write", f"history/{record_id}.r{revision}.json", f"history:{record_id}:r{revision}", "history", payload=history), LifecycleMutation("remove_current_revision", "delete", f"records/{record_id}.json", f"record:{record_id}:r{revision}", "record"), LifecycleMutation("write_correction_candidate", "write", f"candidates/{candidate_id}.json", f"candidate:{candidate_id}", "candidate", payload=candidate))
    return _plan("correct", record_id, revision, _scope(record), now, manifest, mutations)


def apply_memory_correction(paths: OmhPaths, plan: LifecyclePlan, *, transaction_executor: LifecycleTransactionExecutor) -> dict[str, object]:
    _require_guard(paths, plan, "records")
    return _execute(paths, plan, transaction_executor)


def build_memory_prune(paths: OmhPaths, record_id: str, revision: int, *, now: datetime) -> LifecyclePlan:
    record, error = _current_record(paths, record_id, revision)
    if error:
        return _rejected("prune", record_id, revision, now, error)
    if _retention_class(record) != "volatile" or _expiry_reason(record, now) != "expired_volatile" or _admission_state(record) not in {"approved_manual", "approved_auto_safe"}:
        return _rejected("prune", record_id, revision, now, "prune_requires_expired_approved_volatile")
    findings, errors, preserved = _prune_findings(paths, record_id, revision)
    if errors or len(findings) + len(preserved) >= MAX_MANIFEST_TARGETS:
        return _rejected("prune", record_id, revision, now, errors[0] if errors else "manifest_target_limit", rejected_outcomes(errors))
    manifest = _manifest(tuple((item.target_id, item.artifact_kind, item.relative_path) for item in findings))
    mutations = _prune_mutations(paths.memory_dir, findings, record_id, revision, _scope(record), now)
    return _plan("prune", record_id, revision, _scope(record), now, manifest, mutations, preserved)


def apply_memory_prune(paths: OmhPaths, plan: LifecyclePlan, *, transaction_executor: LifecycleTransactionExecutor, confirm_hard_delete_local: bool, resume: bool = False) -> dict[str, object]:
    if not confirm_hard_delete_local:
        raise ValueError("hard_delete_confirmation_required")
    if not resume:
        rebuilt = build_memory_prune(paths, plan.record_id, plan.revision, now=plan.now)
        if rebuilt.report.get("manifest") != plan.report.get("manifest") or not rebuilt.report.get("eligible"):
            raise ValueError("manifest_mismatch")
    return _execute(paths, plan, transaction_executor)


def make_lifecycle_receipt(plan: LifecyclePlan, outcomes: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {"schema_version": RECEIPT_SCHEMA_VERSION, "operation_id": plan.operation_id, "operation_type": plan.operation_type, "record_id": plan.record_id, "revision": plan.revision, "scope": dict(plan.scope), "actor_class": "operator", "created_at": stamp(plan.now), "completed_at": stamp(plan.now), "state": "completed", "outcomes": [dict(item) for item in [*outcomes, *plan.preserved]][:MAX_MANIFEST_TARGETS]}


def validate_lifecycle_receipt(receipt: Mapping[str, object]) -> list[str]:
    errors = [f"unsupported:{key}" for key in sorted(set(receipt) - _RECEIPT_FIELDS)]
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION or receipt.get("state") != "completed":
        errors.append("invalid_receipt_state")
    if not all(safe_token(receipt.get(key)) for key in ("operation_id", "operation_type", "record_id", "actor_class")):
        errors.append("invalid_receipt_identifier")
    if not isinstance(receipt.get("revision"), int) or isinstance(receipt.get("revision"), bool) or receipt["revision"] < 1:
        errors.append("invalid_receipt_revision")
    try:
        canonical_memory_scope(dict(receipt.get("scope", {})))
    except (TypeError, ValueError):
        errors.append("invalid_receipt_scope")
    if any(parse_time(receipt.get(key)) is None for key in ("created_at", "completed_at")):
        errors.append("invalid_receipt_timestamp")
    outcomes = receipt.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) > MAX_MANIFEST_TARGETS:
        return [*errors, "invalid_receipt_outcomes"]
    for outcome in outcomes:
        if not isinstance(outcome, Mapping) or set(outcome) != _OUTCOME_FIELDS or not safe_token(outcome.get("target_id")) or not safe_token(outcome.get("artifact_kind")) or outcome.get("outcome") not in _ALLOWED_OUTCOMES or not safe_token(outcome.get("reason_code")):
            errors.append("invalid_receipt_outcome")
    return errors


def _lifecycle_candidate_id(operation: str, record_id: str, revision: int) -> str:
    digest = hashlib.sha256(f"{operation}:{record_id}:{revision}".encode("utf-8")).hexdigest()[:24]
    return f"cand-{operation}-{digest}"


def _execute(paths: OmhPaths, plan: LifecyclePlan, executor: LifecycleTransactionExecutor) -> dict[str, object]:
    return _execute_plan(paths, plan, executor, validate_lifecycle_receipt)
