"""Deterministic offline grader and `omh_reported_rate/v1` verdict engine for skill-lift v1."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from omh.quality.reported_rate import reported_rate

SKILL_LIFT_REPORT_SCHEMA_VERSION = "omh_skill_lift_report/v1"
MIN_PASS_RATE_DELTA_PP = 15.0
MIN_FAILURE_REDUCTION_PERCENT = 50.0
MAX_TOKEN_OVERHEAD_RATIO = 1.5


@dataclass(frozen=True)
class TaskGrade:
    task_id: str
    skill: str
    kind: str
    passed: bool
    missing_required: tuple[str, ...]
    hit_forbidden: tuple[str, ...]
    tokens: int

    def to_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "skill": self.skill,
            "kind": self.kind,
            "passed": self.passed,
            "missing_required": list(self.missing_required),
            "hit_forbidden": list(self.hit_forbidden),
            "tokens": self.tokens,
        }


def grade_response(task: Mapping[str, Any], response_text: str, *, tokens: int = 0) -> TaskGrade:
    """Grade one response deterministically against required and forbidden clauses."""
    lowered = response_text.lower()
    missing = tuple(
        clause for clause in task.get("required_substrings", ()) if str(clause).lower() not in lowered
    )
    forbidden = tuple(
        clause for clause in task.get("forbidden_substrings", ()) if str(clause).lower() in lowered
    )
    return TaskGrade(
        task_id=str(task["id"]),
        skill=str(task["skill"]),
        kind=str(task["kind"]),
        passed=not missing and not forbidden,
        missing_required=missing,
        hit_forbidden=forbidden,
        tokens=max(0, int(tokens)),
    )


def evaluate_model_arm_pair(
    *,
    model: str,
    without_grades: Sequence[TaskGrade],
    with_grades: Sequence[TaskGrade],
) -> dict[str, object]:
    """Compute `omh_reported_rate/v1` lift metrics and pass/fail verdict for one model."""
    pos_without = [g for g in without_grades if g.kind == "positive"]
    pos_with = [g for g in with_grades if g.kind == "positive"]
    neg_without = [g for g in without_grades if g.kind == "negative_control"]
    neg_with = [g for g in with_grades if g.kind == "negative_control"]

    without_rate = reported_rate(
        numerator=sum(1 for g in pos_without if g.passed),
        denominator=len(pos_without),
        numerator_of=("passed_positive_tasks_without_skill",),
        denominator_of="positive_skill_lift_tasks",
        excluded=("negative_control_tasks",),
    ).to_payload()
    with_rate = reported_rate(
        numerator=sum(1 for g in pos_with if g.passed),
        denominator=len(pos_with),
        numerator_of=("passed_positive_tasks_with_skill",),
        denominator_of="positive_skill_lift_tasks",
        excluded=("negative_control_tasks",),
    ).to_payload()

    without_failures = sum(1 for g in pos_without if not g.passed)
    with_failures = sum(1 for g in pos_with if not g.passed)
    eliminated_failures = max(0, without_failures - with_failures)
    failure_reduction = reported_rate(
        numerator=eliminated_failures,
        denominator=without_failures,
        numerator_of=("eliminated_baseline_failures",),
        denominator_of="baseline_failed_positive_tasks",
        excluded=("baseline_passing_tasks", "negative_control_tasks"),
    ).to_payload()

    neg_without_by_id = {g.task_id: g.passed for g in neg_without}
    neg_regressions = sum(
        1 for g in neg_with if neg_without_by_id.get(g.task_id, True) and not g.passed
    )
    neg_regression_rate = reported_rate(
        numerator=neg_regressions,
        denominator=len(neg_with),
        numerator_of=("negative_control_regressions",),
        denominator_of="negative_control_tasks",
        excluded=("positive_skill_lift_tasks",),
    ).to_payload()

    without_tokens = sum(g.tokens for g in without_grades)
    with_tokens = sum(g.tokens for g in with_grades)
    token_overhead_ratio = round(with_tokens / without_tokens, 3) if without_tokens > 0 else None

    without_pct = without_rate["percent"]
    with_pct = with_rate["percent"]
    delta_pp = round(with_pct - without_pct, 2) if (without_pct is not None and with_pct is not None) else None
    fail_red_pct = failure_reduction["percent"]

    lift_met = bool(
        (delta_pp is not None and delta_pp >= MIN_PASS_RATE_DELTA_PP)
        or (fail_red_pct is not None and fail_red_pct >= MIN_FAILURE_REDUCTION_PERCENT)
    )
    neg_ok = neg_regressions == 0 and len(neg_with) > 0
    tokens_ok = token_overhead_ratio is None or token_overhead_ratio <= MAX_TOKEN_OVERHEAD_RATIO
    has_observations = len(pos_without) > 0 and len(pos_with) > 0
    passed = has_observations and lift_met and neg_ok and tokens_ok

    reasons: list[str] = []
    if not has_observations:
        reasons.append("no_positive_observations")
    if not lift_met:
        reasons.append("lift_below_threshold")
    if not neg_ok:
        reasons.append("negative_control_regression_or_missing")
    if not tokens_ok:
        reasons.append("token_overhead_exceeds_limit")

    return {
        "model": model,
        "verdict": "pass" if passed else "retire_or_rework",
        "passed": passed,
        "reasons": reasons,
        "without_skill_pass_rate": without_rate,
        "with_skill_pass_rate": with_rate,
        "pass_rate_delta_pp": delta_pp,
        "failure_reduction_rate": failure_reduction,
        "negative_control_regression_rate": neg_regression_rate,
        "token_overhead_ratio": token_overhead_ratio,
        "thresholds": {
            "min_pass_rate_delta_pp": MIN_PASS_RATE_DELTA_PP,
            "min_failure_reduction_percent": MIN_FAILURE_REDUCTION_PERCENT,
            "max_token_overhead_ratio": MAX_TOKEN_OVERHEAD_RATIO,
        },
    }
