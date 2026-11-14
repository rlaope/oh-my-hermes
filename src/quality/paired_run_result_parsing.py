"""Closed-schema parsing for paired-run result rows."""

from __future__ import annotations

import math
from typing import Final, TypeAlias

from .paired_run_model import (
    ArmRole,
    BehaviorVerdict,
    InfrastructureStatus,
    RecordedResult,
)
from .paired_run_validation_helpers import (
    closed_shape_error,
    safe_ref_error,
)
from .paired_run_values import is_receipt_provenance

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_RESULT_KEYS: Final = {
    "task_id",
    "arm",
    "infrastructure_status",
    "behavior_verdict",
    "receipt_ref",
    "receipt_run_id",
    "receipt_observed_at",
    "receipt_status",
}
_TIMED_RESULT_KEYS: Final = {*_RESULT_KEYS, "receipt_elapsed_seconds"}


def parse_result_records(
    value: JsonValue,
    errors: list[str],
    *,
    timed: bool = False,
) -> tuple[RecordedResult, ...]:
    """Parse result rows while collecting every boundary error.

    ``timed`` rows (``paired_run_decision/v2``) also carry the signed
    ``receipt_elapsed_seconds``; v1 rows have no such key and parse to None.
    """
    if not isinstance(value, list):
        errors.append("results must be a list")
        return ()
    results: list[RecordedResult] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"results[{index}] must be an object")
            continue
        if closure_error := closed_shape_error(
            item,
            _TIMED_RESULT_KEYS if timed else _RESULT_KEYS,
            f"results[{index}]",
        ):
            errors.append(closure_error)
        elapsed = item.get("receipt_elapsed_seconds")
        if elapsed is not None and (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            errors.append(
                f"results[{index}].receipt_elapsed_seconds must be non-negative seconds or null"
            )
            elapsed = None
        elif elapsed is not None and item.get("receipt_ref") is None:
            errors.append(
                f"results[{index}] receipt_elapsed_seconds requires receipt provenance"
            )
        try:
            role = ArmRole(item.get("arm"))
            status = InfrastructureStatus(item.get("infrastructure_status"))
            verdict = BehaviorVerdict(item.get("behavior_verdict"))
        except ValueError:
            errors.append(
                f"results[{index}] has an invalid closed-vocabulary value"
            )
            continue
        task_id = item.get("task_id")
        receipt_ref = item.get("receipt_ref")
        receipt_run_id = item.get("receipt_run_id")
        receipt_observed_at = item.get("receipt_observed_at")
        receipt_status = item.get("receipt_status")
        raw_receipt_values = (
            receipt_ref,
            receipt_run_id,
            receipt_observed_at,
            receipt_status,
        )
        normalized_receipt = tuple(
            value if isinstance(value, str) else None
            for value in raw_receipt_values
        )
        (
            normalized_ref,
            normalized_run_id,
            normalized_observed_at,
            normalized_status,
        ) = normalized_receipt
        observed = status is InfrastructureStatus.OBSERVED
        infrastructure_error = status is InfrastructureStatus.INFRA_ERROR
        safe_ref_error(task_id, f"results[{index}].task_id", errors)
        if observed != (verdict is not BehaviorVerdict.NOT_OBSERVED):
            errors.append(
                f"results[{index}] infrastructure and behavior are inconsistent"
            )
        complete_receipt = all(
            part is not None and part
            for part in normalized_receipt
        )
        if observed and (
            not complete_receipt or receipt_status != "completed"
        ):
            errors.append(
                f"results[{index}] observed behavior requires a completed receipt"
            )
        if infrastructure_error and (
            not complete_receipt
            or receipt_status not in {"failed", "timed_out", "cancelled"}
        ):
            errors.append(
                f"results[{index}] infra_error requires a terminal failure receipt"
            )
        if (
            not observed
            and not infrastructure_error
            and any(part is not None for part in raw_receipt_values)
        ):
            errors.append(
                f"results[{index}] not_observed forbids receipt provenance"
            )
        if (
            normalized_ref is not None
            and normalized_run_id is not None
            and normalized_observed_at is not None
            and normalized_status is not None
            and not is_receipt_provenance(
                normalized_ref,
                normalized_run_id,
                normalized_observed_at,
            )
        ):
            errors.append(
                f"results[{index}] receipt provenance is invalid"
            )
        if isinstance(task_id, str):
            results.append(
                RecordedResult(
                    task_id,
                    role,
                    status,
                    verdict,
                    normalized_ref,
                    normalized_run_id,
                    normalized_observed_at,
                    normalized_status,
                    float(elapsed) if elapsed is not None else None,
                )
            )
    return tuple(results)
