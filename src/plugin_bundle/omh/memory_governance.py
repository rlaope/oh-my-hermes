"""Pure-stdlib memory governance and replay evaluation facade.

Public API for deterministic admission and replay decisions. Delegates to
internal modules for safety classification and evaluation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

__all__ = [
    "PROJECT_MEMORY_RECORD_SCHEMA_VERSION",
    "MEMORY_SCOPE_SCHEMA_VERSION",
    "MEMORY_BLOCK_SCHEMA_VERSION",
    "PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION",
    "MEMORY_GOVERNANCE_POLICY_VERSION",
    "MEMORY_CLASSIFIER_VERSION",
    "RETENTION_CLASSES",
    "ADMISSION_STATES",
    "RECORD_TYPES",
    "SOURCE_CLASSES",
    "SCOPE_KINDS",
    "canonical_memory_scope",
    "build_retention",
    "canonical_payload_digest",
    "classify_memory_admission",
    "resolve_record_expiry_deadline",
    "stable_artifact_identity",
    "evaluate_memory_replay",
    "external_context_label",
    "validate_replay_evaluation",
    "classify_record_expiry_v1_compat",
]


# Schema versions for v2 governance model
PROJECT_MEMORY_RECORD_SCHEMA_VERSION = "project_memory_record/v2"
MEMORY_SCOPE_SCHEMA_VERSION = "omh_memory_scope/v2"
MEMORY_BLOCK_SCHEMA_VERSION = "omh_memory_block/v2"
PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION = "project_memory_review_record/v2"

# Governance policy and classifier versions
MEMORY_GOVERNANCE_POLICY_VERSION = "governance/v2"
MEMORY_CLASSIFIER_VERSION = "classifier/v3"

# Retention classes
RETENTION_CLASSES = frozenset({"volatile", "standard", "durable"})

# Admission states
ADMISSION_STATES = frozenset({
    "pending_review",
    "approved_manual",
    "approved_auto_safe",
    "blocked",
    "rejected",
})

# Record types
RECORD_TYPES = frozenset({"fact", "decision", "lesson", "procedure", "episode"})

# Source classes
SOURCE_CLASSES = frozenset({
    "omh_local",
    "hermes_native",
    "provider",
    "external",
})

# Allowed scope kinds
SCOPE_KINDS = frozenset({"project", "target", "thread", "run"})

# Default TTL days for retention classes
DEFAULT_VOLATILE_TTL_DAYS = 7
DEFAULT_STANDARD_EPISODE_TTL_DAYS = 30
VOLATILE_MIN_TTL_DAYS = 1
VOLATILE_MAX_TTL_DAYS = 7


def canonical_memory_scope(scope: dict[str, object]) -> dict[str, object]:
    """Validate and return a canonical scope dict.
    
    Raises ValueError if scope is malformed or contains unexpected fields.
    Canonical scope is exactly: {"kind": str, "ref": str}
    """
    if not isinstance(scope, dict):
        raise ValueError("scope must be a dict")
    
    allowed_keys = {"kind", "ref"}
    actual_keys = set(scope.keys())
    
    if actual_keys != allowed_keys:
        unexpected = actual_keys - allowed_keys
        missing = allowed_keys - actual_keys
        if unexpected:
            raise ValueError(f"scope has unexpected fields: {unexpected}")
        if missing:
            raise ValueError(f"scope is missing required fields: {missing}")
    
    kind = scope.get("kind")
    ref = scope.get("ref")
    
    if not isinstance(kind, str) or kind not in SCOPE_KINDS:
        raise ValueError(f"scope.kind must be one of {SCOPE_KINDS}, got {kind!r}")
    
    if not isinstance(ref, str) or not ref:
        raise ValueError(f"scope.ref must be a non-empty string, got {ref!r}")
    
    return {"kind": kind, "ref": ref}


def build_retention(
    retention_class: str,
    *,
    record_type: str,
    admitted_at: datetime,
    ttl_days: int | None = None,
) -> dict[str, object]:
    """Build a retention policy dict for an artifact.
    
    B3 fix: Standard non-episode has no default TTL; only episode defaults 30d.
    - volatile: explicit class, 7-day default, allows 1-7 day custom TTL
    - standard: only episodes default 30d; other types need explicit TTL
    - durable: no default expiry, revalidation deadline optional
    
    Raises ValueError for invalid combinations.
    """
    if retention_class not in RETENTION_CLASSES:
        raise ValueError(f"retention_class must be one of {RETENTION_CLASSES}, got {retention_class!r}")
    
    if record_type not in RECORD_TYPES:
        raise ValueError(f"record_type must be one of {RECORD_TYPES}, got {record_type!r}")
    
    if not isinstance(admitted_at, datetime):
        raise ValueError(f"admitted_at must be a datetime, got {type(admitted_at)}")
    
    admitted_at_utc = admitted_at.astimezone(timezone.utc)
    admitted_iso = admitted_at_utc.isoformat().replace("+00:00", "Z")
    
    retention: dict[str, object] = {
        "class": retention_class,
        "admitted_at": admitted_iso,
    }
    
    if retention_class == "volatile":
        # Volatile: explicit, default 7 days, custom 1-7 allowed
        effective_ttl = ttl_days if ttl_days is not None else DEFAULT_VOLATILE_TTL_DAYS
        
        if (not isinstance(effective_ttl, int) or isinstance(effective_ttl, bool) or 
            effective_ttl < VOLATILE_MIN_TTL_DAYS or effective_ttl > VOLATILE_MAX_TTL_DAYS):
            raise ValueError(
                f"volatile TTL must be an int between {VOLATILE_MIN_TTL_DAYS} and {VOLATILE_MAX_TTL_DAYS}, "
                f"got {effective_ttl!r}"
            )
        
        retention["ttl_days"] = effective_ttl
        expires_at = admitted_at_utc + timedelta(days=effective_ttl)
        retention["expires_at"] = expires_at.isoformat().replace("+00:00", "Z")
    
    elif retention_class == "standard":
        # B3 fix: Only episodes default to 30 days; others need explicit TTL
        if record_type == "episode":
            effective_ttl = ttl_days if ttl_days is not None else DEFAULT_STANDARD_EPISODE_TTL_DAYS
            retention["ttl_days"] = effective_ttl
            expires_at = admitted_at_utc + timedelta(days=effective_ttl)
            retention["expires_at"] = expires_at.isoformat().replace("+00:00", "Z")
        else:
            # Non-episode standard records: only set TTL if explicit
            if ttl_days is not None:
                retention["ttl_days"] = ttl_days
                expires_at = admitted_at_utc + timedelta(days=ttl_days)
                retention["expires_at"] = expires_at.isoformat().replace("+00:00", "Z")
            # else: no expires_at, standard non-episode without explicit TTL
    
    elif retention_class == "durable":
        # Durable: no default expiry; revalidation deadline is optional (set separately)
        pass
    
    return retention


def canonical_payload_digest(artifact: dict[str, object]) -> str:
    """Compute canonical digest of artifact payload (excluding metadata).
    
    Digest includes: schema_version, id fields, revision, record_type, summary, scope, value, label
    Does NOT include: admission, retention, revalidation, timestamps, review data
    """
    payload = {}
    
    if "schema_version" in artifact:
        payload["schema_version"] = artifact["schema_version"]
    
    for id_key in ["record_id", "item_id", "block_id"]:
        if id_key in artifact:
            payload[id_key] = artifact[id_key]
    
    if "revision" in artifact:
        payload["revision"] = artifact["revision"]
    
    if "record_type" in artifact:
        payload["record_type"] = artifact["record_type"]
    
    if "summary" in artifact:
        payload["summary"] = artifact["summary"]
    
    if "scope" in artifact:
        payload["scope"] = artifact["scope"]
    
    if "value" in artifact:
        payload["value"] = artifact["value"]
    
    if "label" in artifact:
        payload["label"] = artifact["label"]
    
    canonical_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
    
    return digest


# Public re-exports from internal modules
from ._governance_safety import classify_memory_admission  # noqa: F401, E402
from ._governance_evaluation import (  # noqa: F401, E402
    stable_artifact_identity,
    evaluate_memory_replay,
)


def external_context_label(source_class: str) -> dict[str, object]:
    """Label for external (non-OMH-reviewed) context."""
    return {
        "source_class": source_class,
        "admission_status": "not_omh_reviewed",
        "reason_code": "external_not_omh_reviewed",
    }


def validate_replay_evaluation(result: dict[str, object]) -> list[str]:
    """Validate a replay evaluation result.
    
    Returns a list of error messages (empty if valid).
    Must not contain any content fields (summary, value, etc.).
    """
    errors = []
    
    required_keys = {"eligible", "reason_code", "evaluated_at"}
    actual_keys = set(result.keys())
    
    for key in required_keys:
        if key not in actual_keys:
            errors.append(f"missing required key: {key}")
    
    forbidden_keys = {"summary", "value", "label", "content", "text", "prompt", "body"}
    content_found = actual_keys & forbidden_keys
    if content_found:
        errors.append(f"result contains forbidden content keys: {content_found}")
    
    return errors


# The two spellings of one record's deadline. `ttl.expires_at` is the one recall,
# retirement, status, and the dreaming counts read; `retention.expires_at` is the
# one the lifecycle plans read. Both are written from a single value at approval
# and nothing enforced that they stay equal, so the two halves of the system
# could reach opposite verdicts about the same record in the same second:
# `memory retire` reported `expired: 1` for the record `memory prune` was
# rejecting as `prune_requires_expired_approved_volatile`.
#
# `ttl` wins wherever it speaks, and an empty `expires_at` is it speaking: it
# says this record never expires, which is not the same as saying nothing. So is
# an unreadable one, which says the deadline cannot be defended and must not be
# acted on. `retention.expires_at` is consulted only when the `ttl` mapping
# carries no `expires_at` key at all.
DEADLINE_ABSENT = "absent"
DEADLINE_UNREADABLE = "unreadable"
DEADLINE_RESOLVED = "resolved"


def _parse_deadline(raw: object) -> tuple[datetime | None, str]:
    text = str(raw or "").strip() if raw else ""
    if not text:
        return None, DEADLINE_ABSENT
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None, DEADLINE_UNREADABLE
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), DEADLINE_RESOLVED


def resolve_record_expiry_deadline(record: dict[str, object] | Mapping[str, object]) -> tuple[datetime | None, str]:
    """One record's deadline, so every caller reads the same date.

    Returns ``(deadline, state)`` where state is ``absent`` (this record does
    not expire), ``unreadable`` (a deadline is present but cannot be parsed and
    must not be acted on), or ``resolved``.

    ``ttl.expires_at`` is authoritative whenever the record states it, including
    when it states it as empty. ``retention.expires_at`` answers only for a
    record whose ``ttl`` mapping has no ``expires_at`` key at all -- a legacy
    shape, or one half of a hand edit. Preferring the earlier of the two instead
    was the first attempt and it is wrong: it lets a retention deadline overrule
    a record that has explicitly said it never expires, and it turns an
    unreadable TTL -- which retirement reports as `malformed_expires_at` and
    refuses to move -- into an expiry somebody acts on.

    Naive timestamps are UTC by definition; the local host's zone would move the
    verdict by up to 14 hours depending on where the machine happens to be.
    """
    ttl = record.get("ttl")
    if isinstance(ttl, Mapping) and "expires_at" in ttl:
        return _parse_deadline(ttl.get("expires_at"))
    retention = record.get("retention")
    if isinstance(retention, Mapping):
        return _parse_deadline(retention.get("expires_at"))
    return None, DEADLINE_ABSENT


def classify_record_expiry_v1_compat(
    record: dict[str, object],
    *,
    now: datetime,
    window_days: int = 7,
) -> str:
    """V1 compatibility function for record expiry classification.

    N5 integration: Moved from hermes_memory.py. Returns one of:
    - "fresh": not expired, not expiring soon
    - "expiring": approaching deadline within window_days
    - "expired": deadline passed
    - "no_ttl": no deadline set
    - "malformed": deadline present but unparseable

    The deadline comes from `resolve_record_expiry_deadline`, so this and the
    lifecycle plans read the same date rather than one field each.

    Naive timestamps (without tzinfo) are treated as UTC by definition.
    """
    expires_at, state = resolve_record_expiry_deadline(record)
    if state == DEADLINE_ABSENT:
        return "no_ttl"
    if expires_at is None:
        return "malformed"
    now_utc = now.astimezone(timezone.utc)
    if expires_at <= now_utc:
        return "expired"
    if expires_at <= now_utc + timedelta(days=max(window_days, 0)):
        return "expiring"
    return "fresh"
