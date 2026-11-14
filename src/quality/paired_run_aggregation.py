"""Per-arm aggregation and Pareto comparison for paired-run decisions."""

from __future__ import annotations

import math
from statistics import median
from typing import Sequence, TypeVar

from .paired_run_model import (
    Aggregate,
    AggregationScope,
    ArmAggregate,
    ArmRole,
    BehaviorVerdict,
    InfrastructureStatus,
    ParetoOutcome,
    QualityGate,
    RecordedResult,
    RunResultInput,
    SPEED_EXCLUSION_CLASSES,
    SpeedAtEqualQuality,
    SpeedVerdict,
)
from .paired_run_values import is_digest
from .reported_rate import reported_rate, reported_rate_shape_errors

_AggregateValue = TypeVar("_AggregateValue")


def aggregate_results(
    results: Sequence[RunResultInput | RecordedResult],
    scope: AggregationScope = AggregationScope(),
) -> Aggregate:
    by_task: dict[str, dict[ArmRole, BehaviorVerdict]] = {}
    for item in results:
        if item.infrastructure_status is InfrastructureStatus.OBSERVED:
            by_task.setdefault(item.task_id, {})[item.arm] = item.behavior_verdict
    variant_wins = False
    baseline_wins = False
    comparable_count = 0
    for arms in by_task.values():
        if set(arms) != {ArmRole.BASELINE, ArmRole.VARIANT}:
            continue
        comparable_count += 1
        baseline = arms[ArmRole.BASELINE]
        variant = arms[ArmRole.VARIANT]
        variant_wins = variant_wins or (
            variant is BehaviorVerdict.PASS and baseline is BehaviorVerdict.FAIL
        )
        baseline_wins = baseline_wins or (
            baseline is BehaviorVerdict.PASS and variant is BehaviorVerdict.FAIL
        )
    if comparable_count == 0:
        outcome = ParetoOutcome.INCONCLUSIVE
    elif variant_wins and baseline_wins:
        outcome = ParetoOutcome.TRADEOFF
    elif variant_wins:
        outcome = ParetoOutcome.VARIANT_DOMINATES
    elif baseline_wins:
        outcome = ParetoOutcome.BASELINE_DOMINATES
    else:
        outcome = ParetoOutcome.NO_OBSERVED_DIFFERENCE
    return Aggregate(
        _arm_aggregate(results, ArmRole.BASELINE),
        _arm_aggregate(results, ArmRole.VARIANT),
        comparable_count,
        scope.task_set_digest,
        scope.baseline_exposure_digest,
        scope.variant_exposure_digest,
        outcome.value,
        speed_at_equal_quality(results),
    )


def _row_elapsed(item: RunResultInput | RecordedResult) -> float | None:
    if isinstance(item, RecordedResult):
        return item.receipt_elapsed_seconds
    return item.receipt.elapsed_seconds if item.receipt is not None else None


def speed_at_equal_quality(
    results: Sequence[RunResultInput | RecordedResult],
) -> SpeedAtEqualQuality:
    """Compare wall-clock time only over tasks where quality did not move.

    Everything here is recomputed from result rows, whose elapsed seconds come
    from signed receipts. The quality gate looks at every task both arms
    observed: a single baseline PASS that the variant turned into a FAIL
    regresses it, and a regressed gate makes no speed claim at all. Timing is
    taken only over tasks both arms passed with elapsed time on both sides;
    every other task is counted under one named exclusion class. A missing
    figure stays None and is never read as zero seconds.
    """
    by_task: dict[str, dict[ArmRole, RunResultInput | RecordedResult]] = {}
    for item in results:
        by_task.setdefault(item.task_id, {})[item.arm] = item
    excluded = {name: 0 for name in SPEED_EXCLUSION_CLASSES}
    comparable = 0
    regressed = 0
    variant_faster = 0
    pairs: list[tuple[float, float]] = []
    for arms in by_task.values():
        rows = tuple(arms.get(role) for role in (ArmRole.BASELINE, ArmRole.VARIANT))
        if not all(
            row is not None and row.infrastructure_status is InfrastructureStatus.OBSERVED
            for row in rows
        ):
            infra = any(
                row is not None
                and row.infrastructure_status is InfrastructureStatus.INFRA_ERROR
                for row in rows
            )
            excluded["infra_error" if infra else "not_observed"] += 1
            continue
        baseline, variant = arms[ArmRole.BASELINE], arms[ArmRole.VARIANT]
        comparable += 1
        passed = (
            baseline.behavior_verdict is BehaviorVerdict.PASS,
            variant.behavior_verdict is BehaviorVerdict.PASS,
        )
        if passed == (True, False):
            regressed += 1
        if passed == (False, False):
            excluded["both_failed"] += 1
            continue
        if passed != (True, True):
            excluded["one_arm_failed"] += 1
            continue
        baseline_seconds, variant_seconds = _row_elapsed(baseline), _row_elapsed(variant)
        if baseline_seconds is None or variant_seconds is None:
            excluded["missing_elapsed"] += 1
            continue
        pairs.append((baseline_seconds, variant_seconds))
        variant_faster += variant_seconds < baseline_seconds
    gate = (
        QualityGate.UNMEASURED
        if comparable == 0
        else QualityGate.REGRESSED if regressed else QualityGate.HELD
    )
    counts = tuple(excluded.items())
    if gate is QualityGate.REGRESSED or gate is QualityGate.UNMEASURED or not pairs:
        verdict = (
            SpeedVerdict.QUALITY_REGRESSED
            if gate is QualityGate.REGRESSED
            else SpeedVerdict.UNMEASURED
        )
        return SpeedAtEqualQuality(
            gate, regressed, len(pairs), counts, None, None, None, None, None, verdict,
        )
    baseline_total = round(sum(item[0] for item in pairs), 3)
    variant_total = round(sum(item[1] for item in pairs), 3)
    if variant_total < baseline_total:
        verdict = SpeedVerdict.VARIANT_FASTER
    elif variant_total > baseline_total:
        verdict = SpeedVerdict.VARIANT_SLOWER
    else:
        verdict = SpeedVerdict.NO_DIFFERENCE
    return SpeedAtEqualQuality(
        gate,
        regressed,
        len(pairs),
        counts,
        baseline_total,
        variant_total,
        round(median(item[0] for item in pairs), 3),
        round(median(item[1] for item in pairs), 3),
        reported_rate(
            numerator=variant_faster,
            denominator=len(pairs),
            numerator_of=("variant_faster_task",),
            denominator_of="timed_task",
            excluded=SPEED_EXCLUSION_CLASSES,
        ),
        verdict,
    )


def _arm_aggregate(
    results: Sequence[RunResultInput | RecordedResult],
    role: ArmRole,
) -> ArmAggregate:
    rows = tuple(item for item in results if item.arm is role)
    return ArmAggregate(
        sum(item.behavior_verdict is BehaviorVerdict.PASS for item in rows),
        sum(item.behavior_verdict is BehaviorVerdict.FAIL for item in rows),
        sum(item.infrastructure_status is InfrastructureStatus.INFRA_ERROR for item in rows),
        sum(item.infrastructure_status is InfrastructureStatus.NOT_OBSERVED for item in rows),
    )


def aggregate_shape_errors(
    value: _AggregateValue,
    *,
    with_speed: bool = False,
) -> tuple[str, ...]:
    expected = {
        "baseline", "variant", "comparable_task_count", "task_set_digest",
        "baseline_exposure_digest", "variant_exposure_digest",
    }
    if with_speed:
        expected.add("speed_at_equal_quality")
    arm_expected = {"observed_pass", "observed_fail", "infra_error", "not_observed"}
    if not isinstance(value, dict) or set(value) != expected:
        return ("aggregate keys are not closed",)
    errors: list[str] = []
    for label in ("baseline", "variant"):
        arm = value.get(label)
        if not isinstance(arm, dict) or set(arm) != arm_expected:
            errors.append(f"aggregate.{label} keys are not closed")
            continue
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in arm.values()
        ):
            errors.append(f"aggregate.{label} counts must be non-negative integers")
    comparable = value.get("comparable_task_count")
    if isinstance(comparable, bool) or not isinstance(comparable, int) or comparable < 0:
        errors.append("aggregate.comparable_task_count must be a non-negative integer")
    for field in ("task_set_digest", "baseline_exposure_digest", "variant_exposure_digest"):
        digest = value.get(field)
        if not isinstance(digest, str) or not is_digest(digest):
            errors.append(f"aggregate.{field} must be a lowercase sha256 digest")
    if with_speed:
        errors.extend(_speed_shape_errors(value.get("speed_at_equal_quality")))
    return tuple(errors)


_SPEED_KEYS = {
    "quality_gate", "regressed_task_count", "timed_task_count", "excluded",
    "baseline_total_seconds", "variant_total_seconds",
    "baseline_median_seconds", "variant_median_seconds",
    "variant_faster_rate", "verdict",
}


def _speed_shape_errors(value: _AggregateValue) -> tuple[str, ...]:
    label = "aggregate.speed_at_equal_quality"
    if not isinstance(value, dict) or set(value) != _SPEED_KEYS:
        return (f"{label} keys are not closed",)
    errors: list[str] = []
    if value.get("quality_gate") not in {item.value for item in QualityGate}:
        errors.append(f"{label}.quality_gate is invalid")
    if value.get("verdict") not in {item.value for item in SpeedVerdict}:
        errors.append(f"{label}.verdict is invalid")
    excluded = value.get("excluded")
    counts = [value.get("regressed_task_count"), value.get("timed_task_count")]
    if not isinstance(excluded, dict) or set(excluded) != set(SPEED_EXCLUSION_CLASSES):
        errors.append(f"{label}.excluded keys are not closed")
    else:
        counts.extend(excluded.values())
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 0
        for count in counts
    ):
        errors.append(f"{label} counts must be non-negative integers")
    for field in (
        "baseline_total_seconds", "variant_total_seconds",
        "baseline_median_seconds", "variant_median_seconds",
    ):
        seconds = value.get(field)
        if seconds is not None and (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds < 0
        ):
            errors.append(f"{label}.{field} must be non-negative seconds or null")
    rate = value.get("variant_faster_rate")
    if rate is not None:
        errors.extend(f"{label}.variant_faster_rate: {item}" for item in reported_rate_shape_errors(rate))
    return tuple(errors)
