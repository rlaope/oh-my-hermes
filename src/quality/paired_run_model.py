"""Typed values and JSON shapes for paired-run decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Final, NewType, NotRequired, TypedDict

from ..coding.hermes_child_receipts import VerifiedHermesChildReceipt, is_verified_receipt
from .paired_run_values import exposure_digest
from .reported_rate import ReportedRate

# v1 carries pass/fail only. v2 adds the signed per-cell elapsed seconds to
# every result row and the speed-at-equal-quality block to the aggregate.
# Both parse; only v2 is built.
DECISION_SCHEMA_V1: Final = "paired_run_decision/v1"
DECISION_SCHEMA_V2: Final = "paired_run_decision/v2"
DECISION_SCHEMA_VERSIONS: Final = (DECISION_SCHEMA_V1, DECISION_SCHEMA_V2)

DecisionId = NewType("DecisionId", str)
TaskId = NewType("TaskId", str)
Digest = NewType("Digest", str)


class ArmRole(StrEnum):
    BASELINE = "baseline"
    VARIANT = "variant"


class InfrastructureStatus(StrEnum):
    NOT_OBSERVED = "not_observed"
    INFRA_ERROR = "infra_error"
    OBSERVED = "observed"


class BehaviorVerdict(StrEnum):
    NOT_OBSERVED = "not_observed"
    PASS = "pass"
    FAIL = "fail"


class QualityGate(StrEnum):
    HELD = "held"
    REGRESSED = "regressed"
    UNMEASURED = "unmeasured"


class SpeedVerdict(StrEnum):
    VARIANT_FASTER = "variant_faster"
    VARIANT_SLOWER = "variant_slower"
    NO_DIFFERENCE = "no_difference"
    QUALITY_REGRESSED = "quality_regressed"
    UNMEASURED = "unmeasured"


# Every task the timing leaves out lands in exactly one of these classes, in
# this order of precedence for tasks that are not comparable.
SPEED_EXCLUSION_CLASSES: Final = (
    "one_arm_failed",
    "both_failed",
    "missing_elapsed",
    "infra_error",
    "not_observed",
)


class ParetoOutcome(StrEnum):
    VARIANT_DOMINATES = "variant_dominates"
    BASELINE_DOMINATES = "baseline_dominates"
    TRADEOFF = "tradeoff"
    NO_OBSERVED_DIFFERENCE = "no_observed_difference"
    INCONCLUSIVE = "inconclusive"


class PairedRunValidationError(Exception):
    __slots__ = ("errors",)

    def __init__(self, errors: tuple[str, ...]) -> None:
        super().__init__(*errors)
        self.errors = errors

    def __str__(self) -> str:
        return "; ".join(self.errors)


@dataclass(frozen=True, slots=True)
class ArmSpec:
    arm_id: str
    executor: str
    model: str
    exposed_skills: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    acceptance_criteria_ref: str
    input_digest: str


@dataclass(frozen=True, slots=True)
class RunResultInput:
    task_id: str
    arm: ArmRole
    infrastructure_status: InfrastructureStatus
    behavior_verdict: BehaviorVerdict
    receipt: VerifiedHermesChildReceipt | None

    def __post_init__(self) -> None:
        observed = self.infrastructure_status is InfrastructureStatus.OBSERVED
        infrastructure_error = self.infrastructure_status is InfrastructureStatus.INFRA_ERROR
        behavioral = self.behavior_verdict is not BehaviorVerdict.NOT_OBSERVED
        receipt = self.receipt
        sealed = isinstance(receipt, VerifiedHermesChildReceipt) and is_verified_receipt(receipt)
        receipt_status = receipt.status if sealed and receipt is not None else None
        completed = receipt_status == "completed"
        terminal_failure = receipt_status in {"failed", "timed_out", "cancelled"}
        valid = (
            (observed and behavioral and completed)
            or (infrastructure_error and not behavioral and terminal_failure)
            or (not observed and not infrastructure_error and not behavioral and self.receipt is None)
        )
        if not valid:
            raise PairedRunValidationError(("completed sealed receipts authorize pass/fail; terminal failures authorize infra_error",))


@dataclass(frozen=True, slots=True)
class RecordedResult:
    task_id: str
    arm: ArmRole
    infrastructure_status: InfrastructureStatus
    behavior_verdict: BehaviorVerdict
    receipt_ref: str | None
    receipt_run_id: str | None
    receipt_observed_at: str | None
    receipt_status: str | None
    receipt_elapsed_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class PairedRunRequest:
    decision_id: str
    supersedes_decision_ref: str | None
    baseline: ArmSpec
    variant: ArmSpec
    tasks: tuple[TaskSpec, ...]
    max_total_runs: int
    max_dispatch_seconds: int
    execution_revision: str
    recorded_at: str
    results: tuple[RunResultInput, ...]


@dataclass(frozen=True, slots=True)
class ArmAggregate:
    observed_pass: int
    observed_fail: int
    infra_error: int
    not_observed: int


@dataclass(frozen=True, slots=True)
class AggregationScope:
    task_set_digest: str = ""
    baseline_exposure_digest: str = ""
    variant_exposure_digest: str = ""


@dataclass(frozen=True, slots=True)
class SpeedAtEqualQuality:
    """Wall-clock comparison that counts only when quality held."""

    quality_gate: QualityGate
    regressed_task_count: int
    timed_task_count: int
    excluded: tuple[tuple[str, int], ...]
    baseline_total_seconds: float | None
    variant_total_seconds: float | None
    baseline_median_seconds: float | None
    variant_median_seconds: float | None
    variant_faster_rate: ReportedRate | None
    verdict: SpeedVerdict

    def to_record(self) -> dict[str, object]:
        return {
            "quality_gate": self.quality_gate.value,
            "regressed_task_count": self.regressed_task_count,
            "timed_task_count": self.timed_task_count,
            "excluded": dict(self.excluded),
            "baseline_total_seconds": self.baseline_total_seconds,
            "variant_total_seconds": self.variant_total_seconds,
            "baseline_median_seconds": self.baseline_median_seconds,
            "variant_median_seconds": self.variant_median_seconds,
            "variant_faster_rate": (
                None
                if self.variant_faster_rate is None
                else self.variant_faster_rate.to_payload()
            ),
            "verdict": self.verdict.value,
        }


@dataclass(frozen=True, slots=True)
class Aggregate:
    baseline: ArmAggregate
    variant: ArmAggregate
    comparable_task_count: int
    task_set_digest: str
    baseline_exposure_digest: str
    variant_exposure_digest: str
    outcome: str
    speed_at_equal_quality: SpeedAtEqualQuality


class ArmRecord(TypedDict):
    arm_id: str
    executor: str
    model: str
    exposed_skills: list[str]
    exposure_digest: str


class TaskRecord(TypedDict):
    task_id: str
    acceptance_criteria_ref: str
    input_digest: str


class ResultRecord(TypedDict):
    task_id: str
    arm: str
    infrastructure_status: str
    behavior_verdict: str
    receipt_ref: str | None
    receipt_run_id: str | None
    receipt_observed_at: str | None
    receipt_status: str | None
    receipt_elapsed_seconds: NotRequired[float | None]


class ArmAggregateRecord(TypedDict):
    observed_pass: int
    observed_fail: int
    infra_error: int
    not_observed: int


class AggregateRecord(TypedDict):
    baseline: ArmAggregateRecord
    variant: ArmAggregateRecord
    comparable_task_count: int
    task_set_digest: str
    baseline_exposure_digest: str
    variant_exposure_digest: str
    speed_at_equal_quality: NotRequired[dict[str, object]]


class DecisionRecord(TypedDict):
    schema_version: str
    decision_id: str
    supersedes_decision_ref: str | None
    baseline: ArmRecord
    variant: ArmRecord
    tasks: list[TaskRecord]
    task_set_digest: str
    max_total_runs: int
    max_dispatch_seconds: int
    execution_revision: str
    recorded_at: str
    results: list[ResultRecord]
    aggregate: AggregateRecord
    outcome: str
    claim_boundary: str


@dataclass(frozen=True, slots=True)
class PairedRunDecision:
    schema_version: str
    decision_id: str
    supersedes_decision_ref: str | None
    baseline: ArmSpec
    variant: ArmSpec
    tasks: tuple[TaskSpec, ...]
    task_set_digest: str
    max_total_runs: int
    max_dispatch_seconds: int
    execution_revision: str
    recorded_at: str
    results: tuple[RecordedResult, ...]
    aggregate: Aggregate
    claim_boundary: str

    @property
    def outcome(self) -> str:
        return self.aggregate.outcome

    def to_record(self) -> DecisionRecord:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "supersedes_decision_ref": self.supersedes_decision_ref,
            "baseline": _arm_record(self.baseline),
            "variant": _arm_record(self.variant),
            "tasks": [
                {
                    "task_id": item.task_id,
                    "acceptance_criteria_ref": item.acceptance_criteria_ref,
                    "input_digest": item.input_digest,
                }
                for item in self.tasks
            ],
            "task_set_digest": self.task_set_digest,
            "max_total_runs": self.max_total_runs,
            "max_dispatch_seconds": self.max_dispatch_seconds,
            "execution_revision": self.execution_revision,
            "recorded_at": self.recorded_at,
            "results": [
                _result_record(item, self.schema_version) for item in self.results
            ],
            "aggregate": aggregate_record(self.aggregate, self.schema_version),
            "outcome": self.outcome,
            "claim_boundary": self.claim_boundary,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_record(), sort_keys=True, separators=(",", ":"))


def _arm_record(arm: ArmSpec) -> ArmRecord:
    skills = tuple(sorted(arm.exposed_skills))
    return {
        "arm_id": arm.arm_id,
        "executor": arm.executor,
        "model": arm.model,
        "exposed_skills": list(skills),
        "exposure_digest": exposure_digest(skills),
    }


def aggregate_record(aggregate: Aggregate, schema_version: str) -> AggregateRecord:
    """Project an aggregate into the closed shape its schema version names."""
    record: AggregateRecord = {
        "baseline": {
            "observed_pass": aggregate.baseline.observed_pass,
            "observed_fail": aggregate.baseline.observed_fail,
            "infra_error": aggregate.baseline.infra_error,
            "not_observed": aggregate.baseline.not_observed,
        },
        "variant": {
            "observed_pass": aggregate.variant.observed_pass,
            "observed_fail": aggregate.variant.observed_fail,
            "infra_error": aggregate.variant.infra_error,
            "not_observed": aggregate.variant.not_observed,
        },
        "comparable_task_count": aggregate.comparable_task_count,
        "task_set_digest": aggregate.task_set_digest,
        "baseline_exposure_digest": aggregate.baseline_exposure_digest,
        "variant_exposure_digest": aggregate.variant_exposure_digest,
    }
    if schema_version != DECISION_SCHEMA_V1:
        record["speed_at_equal_quality"] = aggregate.speed_at_equal_quality.to_record()
    return record


def _result_record(result: RecordedResult, schema_version: str) -> ResultRecord:
    record: ResultRecord = {
        "task_id": result.task_id,
        "arm": result.arm.value,
        "infrastructure_status": result.infrastructure_status.value,
        "behavior_verdict": result.behavior_verdict.value,
        "receipt_ref": result.receipt_ref,
        "receipt_run_id": result.receipt_run_id,
        "receipt_observed_at": result.receipt_observed_at,
        "receipt_status": result.receipt_status,
    }
    if schema_version != DECISION_SCHEMA_V1:
        record["receipt_elapsed_seconds"] = result.receipt_elapsed_seconds
    return record
