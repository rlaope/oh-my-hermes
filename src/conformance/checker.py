from __future__ import annotations

from collections.abc import Mapping

from ..paths import OmhPaths
from ..runtime.artifacts import show_run, summarize_delegated_coding_status, validate_runtime
from ..runtime.claims import allowed_runtime_claims, blocked_runtime_claims
from .contract import (
    DEFAULT_CLAIM_BOUNDARY,
    RUNTIME_SUBJECT_TYPE,
    SCHEMA_VERSION,
    Claim,
    ConformanceReport,
    EvidenceItem,
    JsonValue,
)


VALIDATION_FAILURE_NEXT_ACTION = "fix_validation_violations"
VALIDATION_FAILURE_SUMMARY = "Runtime validation failed; fix the listed violations before making higher evidence claims."


def check_runtime_run(paths: OmhPaths, run_id: str) -> ConformanceReport:
    if not (paths.runtime_runs_dir / run_id / "run.json").exists():
        raise FileNotFoundError(run_id)
    validation = validate_runtime(paths, run_id)
    violations = _validation_violations(validation)
    conformance_ok = _bool_value(validation, "ok") and not violations
    shown = show_run(paths, run_id) if conformance_ok else {}
    status = summarize_delegated_coding_status(paths, run_id) if conformance_ok else {}
    allowed = allowed_runtime_claims(status, validation_failed=not conformance_ok)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": conformance_ok,
        "subject": {"type": RUNTIME_SUBJECT_TYPE, "id": run_id},
        "claim_state": allowed[-1].value,
        "allowed_claims": [claim.value for claim in allowed],
        "blocked_claims": blocked_runtime_claims(allowed, validation_failed=not conformance_ok),
        "evidence": _evidence(validation, shown, status),
        "violations": violations,
        "claim_boundary": _claim_boundary(status),
        "next_action": _next_action(status, conformance_ok=conformance_ok),
        "safe_summary": _safe_summary(status, conformance_ok=conformance_ok),
    }


def _validation_violations(validation: Mapping[str, JsonValue]) -> list[str]:
    if _bool_value(validation, "ok"):
        return []
    violations: list[str] = []
    for run in _list_value(validation, "runs"):
        errors = _list_value(_mapping(run), "errors")
        violations.extend(str(error) for error in errors)
    for session in _list_value(validation, "wrapper_sessions"):
        errors = _list_value(_mapping(session), "errors")
        violations.extend(str(error) for error in errors)
    journal = _mapping_value(validation, "journal")
    violations.extend(str(error) for error in _list_value(journal, "errors"))
    return violations


def _evidence(
    validation: Mapping[str, JsonValue],
    shown: Mapping[str, JsonValue],
    status: Mapping[str, JsonValue],
) -> list[EvidenceItem]:
    validation_status = "passed" if _bool_value(validation, "ok") else "failed"
    lifecycle = _mapping_value(shown, "lifecycle")
    return [
        {"kind": "runtime_validation", "status": validation_status, "source": "validate_runtime"},
        {"kind": "runtime_projection", "status": _string_value(lifecycle, "observation_status"), "source": "show_run"},
        {
            "kind": "delegated_coding_status",
            "status": _string_value(status, "next_action"),
            "source": "summarize_delegated_coding_status",
        },
    ]


def _claim_boundary(status: Mapping[str, JsonValue]) -> str:
    guard = [str(item) for item in _list_value(status, "overclaim_guard")]
    if guard:
        return " ".join(guard)
    return DEFAULT_CLAIM_BOUNDARY


def _next_action(status: Mapping[str, JsonValue], *, conformance_ok: bool) -> str:
    if not conformance_ok:
        return VALIDATION_FAILURE_NEXT_ACTION
    return _string_value(status, "next_action")


def _safe_summary(status: Mapping[str, JsonValue], *, conformance_ok: bool) -> str:
    if not conformance_ok:
        return VALIDATION_FAILURE_SUMMARY
    return _string_value(status, "safe_summary")


def _mapping_value(payload: Mapping[str, JsonValue], key: str) -> Mapping[str, JsonValue]:
    return _mapping(payload.get(key))


def _mapping(value: JsonValue | None) -> Mapping[str, JsonValue]:
    if isinstance(value, dict):
        return value
    return {}


def _list_value(payload: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    value = payload.get(key)
    if isinstance(value, list):
        return value
    return []


def _bool_value(payload: Mapping[str, JsonValue], key: str) -> bool:
    return payload.get(key) is True


def _string_value(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    return ""
