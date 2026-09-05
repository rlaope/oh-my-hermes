"""Replay evaluation for memory governance (internal module).

Deterministic 10-step evaluation with fail-closed reason codes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ._governance_safety import evaluate_renderable_strings
from ._governance_overrides import validate_stale_override


def stable_artifact_identity(artifact: dict[str, object]) -> dict[str, object]:
    """Compute stable identity: schema_version + id + revision + scope."""
    from .memory_governance import canonical_memory_scope, PROJECT_MEMORY_RECORD_SCHEMA_VERSION, MEMORY_SCOPE_SCHEMA_VERSION, MEMORY_BLOCK_SCHEMA_VERSION
    
    schema_version = artifact.get("schema_version")
    
    if schema_version == PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
        id_key = "record_id"
    elif schema_version == MEMORY_SCOPE_SCHEMA_VERSION:
        id_key = "item_id"
    elif schema_version == MEMORY_BLOCK_SCHEMA_VERSION:
        id_key = "block_id"
    else:
        id_key = "record_id"
    
    id_value = artifact.get(id_key)
    revision = artifact.get("revision", 1)
    
    scope = artifact.get("scope")
    if scope:
        scope = canonical_memory_scope(scope)
    else:
        scope = None
    
    return {
        "schema_version": schema_version,
        "id": id_value,
        "id_key": id_key,
        "revision": revision,
        "scope": scope,
    }





def evaluate_memory_replay(
    artifact: dict[str, object],
    *,
    now: datetime | None = None,
    requested_scope: dict[str, object] | None = None,
    review_resolver: dict[str, dict[str, object]] | None = None,
    conflict_ids: set[str] | None = None,
    run_id: str | None = None,
    stale_override: dict[str, object] | None = None,
    tombstoned: bool = False,
) -> dict[str, object]:
    """Evaluate whether an artifact can replay (is eligible).
    
    B1 fix: Evaluates all renderable string fields (summary, value, label)
    and fails closed on worst result.
    
    Returns metadata-only dict with eligible/reason_code.
    """
    from .memory_governance import (
        PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
        MEMORY_SCOPE_SCHEMA_VERSION,
        MEMORY_BLOCK_SCHEMA_VERSION,
        canonical_memory_scope,
        canonical_payload_digest,
        contains_credential_like_material,
    )
    
    if now is None:
        now = datetime.now(timezone.utc)
    
    now_utc = now.astimezone(timezone.utc)
    now_iso = now_utc.isoformat().replace("+00:00", "Z")
    
    result: dict[str, object] = {
        "evaluated_at": now_iso,
        "eligible": False,
        "reason_code": "unknown",
        "admission_state": None,
        "admission_mode": None,
        "payload_digest": None,
        "source_class": (
            "redacted"
            if contains_credential_like_material(str(artifact.get("source_class", "")))
            else artifact.get("source_class")
        ),
        "retention_class": None,
    }
    
    # 1. Check schema version
    schema_version = artifact.get("schema_version")
    
    if schema_version == PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
        pass
    elif schema_version == MEMORY_SCOPE_SCHEMA_VERSION:
        pass
    elif schema_version == MEMORY_BLOCK_SCHEMA_VERSION:
        pass
    elif schema_version is None or isinstance(schema_version, str):
        if schema_version and "project_memory_record/v1" in str(schema_version):
            result["reason_code"] = "review_required_legacy"
            return result
        result["reason_code"] = "unsupported_schema"
        return result
    else:
        result["reason_code"] = "unsupported_schema"
        return result
    
    revision = artifact.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
        result["reason_code"] = "invalid_revision"
        return result
    
    # 2. Check scope match
    artifact_scope = artifact.get("scope")
    if artifact_scope:
        try:
            artifact_scope = canonical_memory_scope(artifact_scope)
        except ValueError:
            result["reason_code"] = "scope_invalid"
            return result
    
    if requested_scope is not None:
        try:
            requested_scope = canonical_memory_scope(requested_scope)
        except ValueError:
            result["reason_code"] = "scope_invalid"
            return result
        
        if artifact_scope != requested_scope:
            result["reason_code"] = "scope_mismatch"
            return result
    
    # 3. Check admission state and review linkage
    admission = artifact.get("admission", {})
    if not isinstance(admission, dict):
        result["reason_code"] = "admission_invalid"
        return result
    
    admission_state = admission.get("state")
    result["admission_state"] = admission_state
    
    from .memory_governance import ADMISSION_STATES
    if admission_state not in ADMISSION_STATES:
        result["reason_code"] = "admission_state_invalid"
        return result
    
    if admission_state in ("blocked", "rejected", "pending_review"):
        result["reason_code"] = {
            "blocked": "admission_blocked",
            "rejected": "admission_rejected",
            "pending_review": "review_required",
        }.get(admission_state, "admission_invalid")
        return result
    
    # For approved states, verify review linkage
    if admission_state in ("approved_manual", "approved_auto_safe"):
        result["admission_mode"] = admission_state
        
        expected_digest = admission.get("payload_digest")
        review_id = admission.get("review_id")
        
        actual_digest = canonical_payload_digest(artifact)
        result["payload_digest"] = actual_digest
        
        if expected_digest != actual_digest:
            result["reason_code"] = "payload_digest_mismatch"
            return result
        
        if review_id:
            if not review_resolver:
                # An approved artifact asserting review linkage fails closed
                # when no resolver can verify the immutable review record.
                result["reason_code"] = "review_not_found"
                return result
            review = review_resolver.get(review_id)
            if not review:
                result["reason_code"] = "review_not_found"
                return result
            
            review_identity = review.get("artifact_identity")
            actual_identity = stable_artifact_identity(artifact)
            
            if review_identity != actual_identity:
                result["reason_code"] = "review_identity_mismatch"
                return result
            
            review_digest = review.get("payload_digest")
            if review_digest != actual_digest:
                result["reason_code"] = "review_payload_mismatch"
                return result
    
    # 4. B1: Safety re-classification on all renderable strings
    safety_eval = evaluate_renderable_strings(artifact)
    if safety_eval.get("status") == "blocked":
        result["reason_code"] = safety_eval.get("reason_code", "safety_blocked")
        return result
    elif safety_eval.get("status") == "needs_review":
        result["reason_code"] = safety_eval.get("reason_code", "safety_needs_review")
        return result
    
    # 5. Check expiry
    retention = artifact.get("retention", {})
    if isinstance(retention, dict):
        result["retention_class"] = retention.get("class")
        expires_at_str = retention.get("expires_at")
        
        if expires_at_str:
            try:
                expires_str = str(expires_at_str).replace("Z", "+00:00")
                expires_at = datetime.fromisoformat(expires_str)
                
                if now_utc >= expires_at:
                    retention_class = retention.get("class", "standard")
                    result["reason_code"] = f"expired_{retention_class}"
                    return result
            except (ValueError, TypeError):
                result["reason_code"] = "retention_parse_error"
                return result
    
    # 6. Check stale/revalidation deadline
    revalidation = artifact.get("revalidation")
    if isinstance(revalidation, dict):
        reval_deadline_str = revalidation.get("deadline")
        if reval_deadline_str:
            try:
                reval_str = str(reval_deadline_str).replace("Z", "+00:00")
                reval_deadline = datetime.fromisoformat(reval_str)
                
                if now_utc >= reval_deadline:
                    if stale_override:
                        override_valid = validate_stale_override(
                            stale_override,
                            artifact,
                            reval_deadline,
                            now_utc,
                            run_id,
                        )
                        if not override_valid["valid"]:
                            result["reason_code"] = override_valid["reason"]
                            return result
                    else:
                        result["reason_code"] = "stale_review_required"
                        return result
            except (ValueError, TypeError):
                result["reason_code"] = "revalidation_parse_error"
                return result
    
    # 7. Check supersession, correction, tombstone
    if tombstoned:
        result["reason_code"] = "tombstoned"
        return result
    
    if artifact.get("superseded_by"):
        result["reason_code"] = "superseded"
        return result
    
    # 8. Check unresolved conflicts
    if conflict_ids:
        artifact_conflicts = artifact.get("conflict_ids", [])
        if isinstance(artifact_conflicts, list):
            for conflict_id in artifact_conflicts:
                if conflict_id in conflict_ids:
                    result["reason_code"] = "unresolved_conflict"
                    return result
    
    # All checks passed
    result["eligible"] = True
    result["reason_code"] = "eligible"
    
    return result
