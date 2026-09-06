from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum, unique
from typing import Final, TypeAlias, TypedDict, assert_never

from ..workflows.external_effect_receipts import receipt_satisfies_success_claim


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
    Claim.EXECUTION_OBSERVED: "executor result evidence is not observed, or the run was cancelled before it reached one",
    Claim.VERIFICATION_OBSERVED: "verification evidence is not observed",
    Claim.REVIEW_OBSERVED: (
        "review evidence is not observed, or no external effect receipt from runtime_review_record "
        "records this run's review as succeeded; a run recorded before external effect receipts "
        "existed has none and cannot make this claim"
    ),
    Claim.CI_OBSERVED: (
        "CI evidence is not observed, or no external effect receipt from runtime_ci_record "
        "records this run's CI as succeeded; a run recorded before external effect receipts "
        "existed has none and cannot make this claim"
    ),
    Claim.MERGE_READY: "merge-readiness evidence is not observed",
    Claim.MERGED: (
        "merge evidence is not observed, or no external effect receipt from runtime_merge_record "
        "records this run's merge as succeeded; a run recorded before external effect receipts "
        "existed has none and cannot make this claim"
    ),
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
            execution = _mapping_value(status, "execution")
            # This rung's own block reason names what it stands for: "executor
            # result evidence is observed". A cancelled run has none -- it was
            # stopped before it reached one -- so it stops here, and every rung
            # above it (verification, review, CI, merge-readiness, merge) is
            # blocked by the ladder's break rather than by a separate check.
            # Blocked and failed results are NOT excluded: each of those IS the
            # executor's answer about the work, however unwelcome.
            if _string_value(execution, "status") == "cancelled":
                return False
            return _bool_value(execution, "observed")
        case Claim.VERIFICATION_OBSERVED:
            return _bool_value(_mapping_value(status, "verification"), "observed")
        case Claim.REVIEW_OBSERVED:
            review = _mapping_value(status, "review")
            return (
                _bool_value(review, "observed")
                and _string_value(review, "status") == "passed"
                and _receipt_cited(status, review, kind="review")
            )
        case Claim.CI_OBSERVED:
            ci = _mapping_value(status, "ci")
            return (
                _bool_value(ci, "observed")
                and _string_value(ci, "status") == "passed"
                and _receipt_cited(status, ci, kind="ci")
            )
        case Claim.MERGE_READY:
            readiness = _mapping_value(status, "merge_readiness")
            return _bool_value(readiness, "observed") and _string_value(readiness, "status") == "ready"
        case Claim.MERGED:
            merge = _mapping_value(status, "merge")
            return (
                _bool_value(merge, "observed")
                and _string_value(merge, "status") == "merged"
                and _receipt_cited(status, merge, kind="merge")
            )
        case Claim.METADATA_AVAILABLE:
            return True
        case _ as unreachable:
            assert_never(unreachable)


def _receipt_cited(status: Mapping[str, JsonValue], section: Mapping[str, JsonValue], *, kind: str) -> bool:
    """Whether a gate's success is backed by a receipt that names who acted.

    Review, CI, and merge are the three rungs that assert something happened
    outside this machine. A local record saying "passed" or "merged" is the
    claim, not the evidence for it, so each rung additionally requires a receipt
    that observed *that* effect *succeed* from the surface that gate is observed
    by. A `failed`, `attempted`, or unrelated receipt refuses the claim.

    Review was the last rung to skip this check (#844). It was the one place
    OMH would report "review passed" with nothing naming the surface that
    reviewed, which made the evidence ladder inconsistent with itself.

    This is the same `receipt_satisfies_success_claim` that runtime validation
    uses, called on the same receipt, so the ladder and the validator can never
    disagree about what a receipt proves. A run with no receipt at all -- an
    older store, or a store that could not be written -- simply does not reach
    these rungs; that is a refused claim, not invalid data.
    """
    run_id = _string_value(_mapping_value(status, "external_effects"), "run_id")
    return receipt_satisfies_success_claim(_mapping(section.get("receipt")), kind=kind, run_id=run_id)


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
