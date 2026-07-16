from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Mapping

from ..catalogs.specialists import SpecialistDefinition, recommend_specialist, specialist_for_skill


SPECIALIST_WORK_QUALITY_SCHEMA_VERSION = "specialist_work_quality/v1"
PREPARED_NOT_OBSERVED = "prepared_not_observed"
_FRESHNESS_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_OBSERVED_SOURCE_KINDS = frozenset({"runtime_observation", "command", "artifact", "review", "ci"})
_STAGE_IDS = ("clarify", "plan", "critique", "execute", "verify", "completion-audit")


def build_specialist_work_quality_contract(
    selected_skill: str,
    *,
    phase: str,
    acceptance_criteria: tuple[str, ...] = (),
    route_plan: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a prepared work contract whose completion claims require observed evidence."""
    specialist = specialist_for_skill(selected_skill, phase=phase)
    criteria = acceptance_criteria or ("Observed outcome matches the selected workflow's acceptance boundary.",)
    route_digest = _digest(_canonical_route_plan(route_plan))
    specialist_id = specialist.id if specialist else "unclassified"
    plan_digest = _digest("|".join((selected_skill, phase, specialist_id, *criteria, route_digest)))
    binding_digest = _digest(f"{selected_skill}|{phase}|{plan_digest}")
    profile = _specialist_payload(specialist, selected_skill)
    recommendation = recommend_specialist(selected_skill, task_phase=phase)
    criterion_items = [{"id": f"AC{index:03d}", "summary": criterion} for index, criterion in enumerate(criteria, start=1)]
    return {
        "schema_version": SPECIALIST_WORK_QUALITY_SCHEMA_VERSION,
        "status": PREPARED_NOT_OBSERVED,
        "specialist": profile,
        "specialist_recommendation": recommendation,
        "skill_application": {
            "selected_skill": selected_skill,
            "task_phase": phase,
            "route_plan_digest": route_digest,
            "status": PREPARED_NOT_OBSERVED,
        },
        "goal": {
            "binding_digest": binding_digest,
            "criteria": criterion_items,
        },
        "stages": _prepared_stages(specialist),
        "critique_protocol": _critique_protocol(specialist),
        "repeat_validation": {
            "retry_when": ["a required check fails", "required evidence is missing", "evidence binding is rejected"],
            "retry_boundary": "Record the failed or missing observation and the next check; do not silently retry or upgrade status.",
            "status": PREPARED_NOT_OBSERVED,
        },
        "progress": {
            "prepared_coverage_completed": len(_STAGE_IDS),
            "prepared_coverage_total": len(_STAGE_IDS),
            "prepared_coverage_percent": 100,
            "observed_goal_achievement_completed": 0,
            "observed_goal_achievement_total": len(criterion_items),
            "observed_goal_achievement_percent": 0,
        },
        "evidence_binding": {
            "selected_skill": selected_skill,
            "specialist_id": specialist_id,
            "plan_digest": plan_digest,
            "freshness_max_age_seconds": _FRESHNESS_MAX_AGE_SECONDS,
            "accepted_source_kinds": sorted(_OBSERVED_SOURCE_KINDS),
        },
        "claim_integrity": _claim_integrity("unverified", ["missing_observed_evidence"]),
        "claim_boundary": (
            "This is a prepared specialist work contract, not execution, critique completion, validation, review, CI, "
            "merge-readiness, merge, or goal-completion evidence."
        ),
    }


def evaluate_observed_goal_achievement(
    contract: Mapping[str, object],
    evidence_records: list[Mapping[str, object]],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Accept only fresh, source-bound observed evidence for goal achievement."""
    criteria = _criterion_ids(contract)
    binding = _mapping_at(contract, "evidence_binding")
    goal = _mapping_at(contract, "goal")
    expected_skill = _string_at(binding, "selected_skill")
    expected_specialist_id = _string_at(binding, "specialist_id")
    expected_plan_digest = _string_at(binding, "plan_digest")
    expected_goal_digest = _string_at(goal, "binding_digest")
    max_age = _int_at(binding, "freshness_max_age_seconds", _FRESHNESS_MAX_AGE_SECONDS)
    current_time = _utc_datetime(now) if now is not None else datetime.now(timezone.utc)
    satisfied: set[str] = set()
    violations: list[str] = []
    for record in evidence_records:
        violation = _record_violation(
            record,
            expected_skill,
            expected_specialist_id,
            expected_plan_digest,
            expected_goal_digest,
            max_age,
            current_time,
        )
        if violation:
            violations.append(violation)
            continue
        criterion_id = _string_at(record, "criterion_id")
        if criterion_id not in criteria:
            violations.append("unknown_criterion")
            continue
        satisfied.add(criterion_id)
    if len(satisfied) != len(criteria):
        violations.append("missing_observed_evidence")
    unique_violations = list(dict.fromkeys(violations))
    total = len(criteria)
    completed = len(satisfied)
    percent = (completed * 100 // total) if total else 0
    integrity_failures = [violation for violation in unique_violations if violation != "missing_observed_evidence"]
    state = "verified" if completed == total and not unique_violations else "failed" if integrity_failures else "unverified"
    return {
        "observed_goal_achievement_completed": completed,
        "observed_goal_achievement_total": total,
        "observed_goal_achievement_percent": percent,
        "satisfied_criteria": sorted(satisfied),
        "claim_integrity": _claim_integrity(state, unique_violations),
    }


def _specialist_payload(specialist: SpecialistDefinition | None, selected_skill: str) -> dict[str, object]:
    if specialist is None:
        return {
            "id": "unclassified",
            "title": "Unclassified Specialist",
            "selected_skill_eligible": False,
            "runtime_claim": "prepared_profile_not_runtime_agent",
            "evidence_boundary": "No specialist profile is available; keep the workflow prepared and require explicit review before completion claims.",
        }
    payload = specialist.to_dict()
    payload["selected_skill_eligible"] = selected_skill in specialist.eligible_skill_ids
    return payload


def _prepared_stages(specialist: SpecialistDefinition | None) -> list[dict[str, object]]:
    checkpoints = specialist.critique_checkpoints if specialist else ()
    return [
        {
            "id": stage_id,
            "status": PREPARED_NOT_OBSERVED,
            "required": True,
            "critique_checkpoint": checkpoints[0] if stage_id == "critique" and checkpoints else "",
            "claim_boundary": "Prepared stage is not observed completion.",
        }
        for stage_id in _STAGE_IDS
    ]


def _critique_protocol(specialist: SpecialistDefinition | None) -> dict[str, object]:
    checks = list(specialist.critique_checkpoints) if specialist else ["explicit-review-required"]
    return {
        "checkpoints": checks,
        "required_before_completion": True,
        "status": PREPARED_NOT_OBSERVED,
        "claim_boundary": "A prepared critique checkpoint is not proof that a critic or reviewer ran.",
    }


def _record_violation(
    record: Mapping[str, object],
    expected_skill: str,
    expected_specialist_id: str,
    expected_plan_digest: str,
    expected_goal_digest: str,
    max_age: int,
    current_time: datetime,
) -> str:
    if _string_at(record, "source_kind") == "self_report":
        return "self_attested_evidence"
    if _string_at(record, "status") != "observed":
        return "evidence_not_observed"
    if _string_at(record, "goal_binding_digest") != expected_goal_digest:
        return "foreign_goal_binding"
    if _string_at(record, "selected_skill") != expected_skill:
        return "foreign_selected_skill"
    if _string_at(record, "specialist_id") != expected_specialist_id:
        return "foreign_specialist_profile"
    if _string_at(record, "plan_digest") != expected_plan_digest:
        return "stale_or_foreign_plan"
    if _string_at(record, "source_kind") not in _OBSERVED_SOURCE_KINDS:
        return "unsupported_evidence_source"
    observed_at = _parse_timestamp(_string_at(record, "observed_at"))
    if observed_at is None:
        return "missing_observed_timestamp"
    if observed_at > current_time:
        return "future_evidence"
    if (current_time - observed_at).total_seconds() > max_age:
        return "stale_evidence"
    return ""


def _criterion_ids(contract: Mapping[str, object]) -> set[str]:
    goal = _mapping_at(contract, "goal")
    raw_criteria = goal.get("criteria")
    if not isinstance(raw_criteria, list):
        return set()
    return {_string_at(item, "id") for item in raw_criteria if isinstance(item, Mapping) and _string_at(item, "id")}


def _claim_integrity(state: str, violations: list[str]) -> dict[str, object]:
    return {
        "state": state,
        "violations": violations,
        "anti_cheating_rules": [
            "prepared_state_is_not_observed_completion",
            "self_attestation_is_not_evidence",
            "evidence_must_bind_goal_skill_specialist_and_plan",
            "stale_or_foreign_evidence_is_rejected",
        ],
    }


def _canonical_route_plan(route_plan: Mapping[str, object] | None) -> str:
    if route_plan is None:
        return ""
    steps = route_plan.get("steps", [])
    if not isinstance(steps, list):
        return ""
    return "|".join(
        f"{_string_at(step, 'stage')}:{_string_at(step, 'skill')}"
        for step in steps
        if isinstance(step, Mapping)
    )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _mapping_at(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    item = value.get(key)
    return item if isinstance(item, Mapping) else {}


def _string_at(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    return str(item) if isinstance(item, str) else ""


def _int_at(value: Mapping[str, object], key: str, default: int) -> int:
    item = value.get(key)
    return item if isinstance(item, int) and not isinstance(item, bool) else default


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
