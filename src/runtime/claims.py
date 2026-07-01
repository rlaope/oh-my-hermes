from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum, unique
from typing import Final, TypeAlias, TypedDict, assert_never


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@unique
class Claim(StrEnum):
    METADATA_AVAILABLE = "metadata_available"
    HANDOFF_PREPARED = "handoff_prepared"
    EXECUTOR_DISPATCHED = "executor_dispatched"
    EXECUTION_OBSERVED = "execution_observed"
    VERIFICATION_OBSERVED = "verification_observed"
    REVIEW_OBSERVED = "review_observed"
    CI_OBSERVED = "ci_observed"
    MERGE_READY = "merge_ready"
    MERGED = "merged"


class RuntimeBlockedClaim(TypedDict):
    claim: str
    reason: str


RUNTIME_CLAIM_LADDER: Final = (
    Claim.METADATA_AVAILABLE,
    Claim.HANDOFF_PREPARED,
    Claim.EXECUTOR_DISPATCHED,
    Claim.EXECUTION_OBSERVED,
    Claim.VERIFICATION_OBSERVED,
    Claim.REVIEW_OBSERVED,
    Claim.CI_OBSERVED,
    Claim.MERGE_READY,
    Claim.MERGED,
)

DEFAULT_RUNTIME_CLAIM_BOUNDARY: Final = (
    "Prepared metadata is not observed execution, verification, review, CI, merge-readiness, or merge evidence."
)

RUNTIME_CLAIM_LABELS: Final = {
    Claim.METADATA_AVAILABLE: "metadata available",
    Claim.HANDOFF_PREPARED: "handoff prepared",
    Claim.EXECUTOR_DISPATCHED: "executor dispatched",
    Claim.EXECUTION_OBSERVED: "execution observed",
    Claim.VERIFICATION_OBSERVED: "verification observed",
    Claim.REVIEW_OBSERVED: "review observed",
    Claim.CI_OBSERVED: "CI observed",
    Claim.MERGE_READY: "merge ready",
    Claim.MERGED: "merged",
}

RUNTIME_CLAIM_BLOCK_REASONS: Final = {
    Claim.HANDOFF_PREPARED: "prepared coding handoff metadata is not available",
    Claim.EXECUTOR_DISPATCHED: "wrapper dispatch evidence is not observed",
    Claim.EXECUTION_OBSERVED: "executor result evidence is not observed",
    Claim.VERIFICATION_OBSERVED: "verification evidence is not observed",
    Claim.REVIEW_OBSERVED: "review evidence is not observed",
    Claim.CI_OBSERVED: "CI evidence is not observed",
    Claim.MERGE_READY: "merge-readiness evidence is not observed",
    Claim.MERGED: "merge evidence is not observed",
}

RUNTIME_VALIDATION_BLOCK_REASON: Final = "runtime validation failed; fix violations before higher claims are safe"


def allowed_runtime_claims(status: Mapping[str, JsonValue], *, validation_failed: bool) -> list[Claim]:
    if validation_failed:
        return [Claim.METADATA_AVAILABLE]
    allowed = [Claim.METADATA_AVAILABLE]
    for claim in RUNTIME_CLAIM_LADDER[1:]:
        if _claim_allowed(claim, status):
            allowed.append(claim)
            continue
        break
    return allowed


def blocked_runtime_claims(
    allowed: Sequence[Claim],
    *,
    validation_failed: bool,
) -> list[RuntimeBlockedClaim]:
    blocked = RUNTIME_CLAIM_LADDER[len(allowed) :]
    return [
        {
            "claim": claim.value,
            "reason": RUNTIME_VALIDATION_BLOCK_REASON
            if validation_failed
            else RUNTIME_CLAIM_BLOCK_REASONS.get(claim, "required evidence is not observed"),
        }
        for claim in blocked
    ]


def _claim_allowed(claim: Claim, status: Mapping[str, JsonValue]) -> bool:
    match claim:
        case Claim.HANDOFF_PREPARED:
            return _bool_value(_mapping_value(status, "prepared"), "available")
        case Claim.EXECUTOR_DISPATCHED:
            return _bool_value(_mapping_value(status, "wrapper"), "prompt_dispatched")
        case Claim.EXECUTION_OBSERVED:
            return _bool_value(_mapping_value(status, "execution"), "observed")
        case Claim.VERIFICATION_OBSERVED:
            return _bool_value(_mapping_value(status, "verification"), "observed")
        case Claim.REVIEW_OBSERVED:
            review = _mapping_value(status, "review")
            return _bool_value(review, "observed") and _string_value(review, "status") == "passed"
        case Claim.CI_OBSERVED:
            ci = _mapping_value(status, "ci")
            return _bool_value(ci, "observed") and _string_value(ci, "status") == "passed"
        case Claim.MERGE_READY:
            readiness = _mapping_value(status, "merge_readiness")
            return _bool_value(readiness, "observed") and _string_value(readiness, "status") == "ready"
        case Claim.MERGED:
            merge = _mapping_value(status, "merge")
            return _bool_value(merge, "observed") and _string_value(merge, "status") == "merged"
        case Claim.METADATA_AVAILABLE:
            return True
        case _ as unreachable:
            assert_never(unreachable)


def _mapping_value(payload: Mapping[str, JsonValue], key: str) -> Mapping[str, JsonValue]:
    return _mapping(payload.get(key))


def _mapping(value: JsonValue | None) -> Mapping[str, JsonValue]:
    if isinstance(value, dict):
        return value
    return {}


def _bool_value(payload: Mapping[str, JsonValue], key: str) -> bool:
    return payload.get(key) is True


def _string_value(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    return ""
