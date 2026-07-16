"""Deterministic, fail-closed governance for OMH and native Hermes skills."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Final, TypeAlias

from .evidence_records import resolve_omh_record_ref


SCHEMA_VERSION: Final = "skill_governance_policy/v1"
_FIELDS: Final = frozenset({"skills", "priority", "runtime_priority", "omh_observed_record"})
_POLICY_TOP_FIELDS: Final = frozenset({"schema_version", "project", "user", "builtin_omh", "native_hermes", "source"})
_SOURCE_FIELDS: Final = frozenset({"repository_id", "commit_sha", "tree_sha"})
_OBSERVED_RECORD_FIELDS: Final = frozenset({"provenance", "ref", "record_type", "policy_digest", "executor", "runtime_priority", "source", "policy_identity", "observed"})
_PolicyInput: TypeAlias = Mapping[str, object] | Sequence[Mapping[str, object]] | None


def _as_levels(value: _PolicyInput) -> tuple[Mapping[str, object], ...] | None:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if all(isinstance(item, Mapping) for item in value):
            return tuple(value)
    return None


def _merge_level(value: _PolicyInput) -> tuple[dict[str, object] | None, list[str]]:
    levels = _as_levels(value)
    if levels is None:
        return None, ["malformed_policy"]
    merged: dict[str, object] = {}
    errors: list[str] = []
    for level in levels:
        unknown = set(level) - _FIELDS
        if unknown:
            errors.append("unknown_fields")
        for key, candidate in level.items():
            if key not in _FIELDS:
                continue
            if key in merged and merged[key] != candidate:
                errors.append("conflicting_values")
            if key == "skills" and (
                not isinstance(candidate, Sequence)
                or isinstance(candidate, (str, bytes, bytearray))
                or not candidate
                or not all(isinstance(skill, str) and skill.strip() for skill in candidate)
                or len(set(candidate)) != len(candidate)
            ):
                errors.append("malformed_policy")
            if key in {"priority", "runtime_priority"} and (
                not isinstance(candidate, str) or not candidate.strip()
            ):
                errors.append("malformed_policy")
            if key == "omh_observed_record" and (
                not isinstance(candidate, Mapping) or not isinstance(candidate.get("ref"), str)
                or not candidate.get("ref")
                or set(candidate) - _OBSERVED_RECORD_FIELDS
                or candidate.get("provenance") != "omh_observed_record"
                or candidate.get("record_type") != "policy_applied"
                or not _is_sha256(candidate.get("policy_digest"))
                or not isinstance(candidate.get("executor"), str)
                or not candidate.get("executor", "").strip()
                or candidate.get("runtime_priority") != candidate.get("executor")
                or not _valid_source(candidate.get("source"))
                or ("observed" in candidate and candidate.get("observed") is not True)
                or ("policy_identity" in candidate and not isinstance(candidate.get("policy_identity"), Mapping))
            ):
                errors.append("malformed_policy")
            merged[key] = candidate
    return merged, errors


def validate_skill_governance_policy(policy: object) -> dict[str, object]:
    """Validate a v1 policy without selecting or executing any skill."""
    if not isinstance(policy, Mapping):
        return {"valid": False, "errors": ["malformed_policy"]}
    errors: list[str] = []
    if policy.get("schema_version") != SCHEMA_VERSION:
        errors.append("unknown_policy_version")
    unknown = set(policy) - _POLICY_TOP_FIELDS
    if unknown:
        errors.append("unknown_fields")
    for name in ("project", "user", "builtin_omh", "native_hermes"):
        if name in policy and policy[name] is None:
            errors.append("malformed_policy")
            continue
        merged, level_errors = _merge_level(policy.get(name))
        if name == "native_hermes" and merged is not None:
            if set(merged) - {"skills"}:
                level_errors.append("native_recommendation_fields")
        errors.extend(level_errors)
    if "source" in policy and not _valid_source(policy.get("source")):
        errors.append("invalid_source_identity")
    return {"valid": not errors, "errors": sorted(set(errors))}


def build_skill_governance_policy(
    project: _PolicyInput = None,
    user: _PolicyInput = None,
    builtin_omh: _PolicyInput = None,
    native_hermes: _PolicyInput = None,
    *,
    native_hermes_recommendation: _PolicyInput = None,
    source: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a schema-versioned policy artifact from four governance levels."""
    native = native_hermes if native_hermes_recommendation is None else native_hermes_recommendation
    return {
        "schema_version": SCHEMA_VERSION,
        "project": project if project is not None else {},
        "user": user if user is not None else {},
        "builtin_omh": builtin_omh if builtin_omh is not None else {},
        "native_hermes": native if native is not None else {},
        **({"source": dict(source)} if source is not None else {}),
    }


def resolve_skill_governance(
    policy: object, *, omh_home: str | None = None
) -> dict[str, object]:
    """Resolve OMH policy precedence; native Hermes values remain recommendations."""
    validation = validate_skill_governance_policy(policy)
    if not validation["valid"] or not isinstance(policy, Mapping):
        return {
            "status": "fail_closed",
            "selected_skills": [],
            "selected_native_skills": [],
            "native_recommendations": [],
            "runtime_priority_observed": False,
            "policy_prepared": False,
            "prepared_status": "fail_closed",
            "evidence_boundary": "fail_closed",
            "errors": validation["errors"],
        }
    selected: dict[str, object] = {}
    for name in ("builtin_omh", "user", "project"):
        merged, _ = _merge_level(policy.get(name))
        if merged:
            selected.update(merged)
    native, _ = _merge_level(policy.get("native_hermes"))
    recommendations = [] if native is None else native.get("skills", [])
    observed = selected.get("omh_observed_record")
    runtime_priority = selected.get("runtime_priority")
    source = policy.get("source")
    decision_identity = policy_decision_identity(selected, executor=runtime_priority, source=source)
    decision_digest = policy_decision_digest(selected, executor=runtime_priority, source=source)
    resolved_observation = None
    if isinstance(observed, Mapping):
        ref = observed.get("ref")
        if isinstance(ref, str) and ref.strip() and omh_home is not None:
            resolved_observation = resolve_omh_record_ref(omh_home, ref)
    runtime_observed = _matching_observation(resolved_observation, selected, runtime_priority, source, decision_digest)
    if observed is not None and not runtime_observed:
        return {
            "status": "fail_closed",
            "selected_skills": [],
            "selected_native_skills": [],
            "native_recommendations": [],
            "runtime_priority_observed": False,
            "policy_prepared": False,
            "prepared_status": "fail_closed",
            "evidence_boundary": "fail_closed",
            "errors": ["unmatched_policy_applied_record"],
        }
    return {
        "status": "resolved",
        "selected_skills": selected.get("skills", []),
        "selected_policy": selected,
        "selected_native_skills": [],
        "native_recommendations": recommendations,
        "runtime_priority_observed": runtime_observed,
        "policy_prepared": True,
        "prepared_status": "policy_prepared",
        "evidence_boundary": "runtime_priority_observed" if runtime_observed else "prepared_not_observed",
        "errors": [],
        "policy_decision_identity": decision_identity,
        "policy_decision_digest": decision_digest,
    }


def policy_decision_identity(
    selected_policy: Mapping[str, object], *, executor: object = None, source: object = None
) -> dict[str, object]:
    """Return the canonical, metadata-only identity for a selected policy."""
    normalized = {key: value for key, value in selected_policy.items() if key != "omh_observed_record"}
    return {
        "policy": normalized,
        "executor": executor if isinstance(executor, str) else "",
        "source": dict(source) if isinstance(source, Mapping) else {},
    }


def policy_decision_digest(
    selected_policy: Mapping[str, object], *, executor: object = None, source: object = None
) -> str:
    payload = json.dumps(
        policy_decision_identity(selected_policy, executor=executor, source=source),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _valid_source(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == _SOURCE_FIELDS
        and all(isinstance(item, str) and item.strip() for item in value.values())
    )


def _matching_observation(observed: object, selected_policy: Mapping[str, object], executor: object, source: object, digest: str) -> bool:
    return (
        isinstance(executor, str)
        and bool(executor.strip())
        and _valid_source(source)
        and isinstance(observed, Mapping)
        and observed.get("provenance") == "omh_observed_record"
        and bool(observed.get("ref"))
        and observed.get("record_type") == "policy_applied"
        and observed.get("policy_digest") == digest
        and observed.get("executor") == executor
        and observed.get("runtime_priority") == executor
        and observed.get("observed") is True
        and dict(observed.get("source", {})) == dict(source)
        and observed.get("policy_identity") == policy_decision_identity(selected_policy, executor=executor, source=source)
    )
