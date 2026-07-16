from __future__ import annotations

from collections.abc import Mapping

from .specialist_work import PREPARED_NOT_OBSERVED, SPECIALIST_WORK_QUALITY_SCHEMA_VERSION


def validate_prepared_specialist_work_quality(contract: object) -> list[str]:
    """Validate the prepared-only subset that may cross a coding handoff boundary."""
    if not isinstance(contract, Mapping):
        return ["specialist_work_quality must be an object"]
    errors: list[str] = []
    if _string_at(contract, "schema_version") != SPECIALIST_WORK_QUALITY_SCHEMA_VERSION:
        errors.append("specialist_work_quality schema_version is invalid")
    if _string_at(contract, "status") != PREPARED_NOT_OBSERVED:
        errors.append("specialist_work_quality status must be prepared_not_observed")
    specialist = _mapping_at(contract, "specialist")
    application = _mapping_at(contract, "skill_application")
    goal = _mapping_at(contract, "goal")
    binding = _mapping_at(contract, "evidence_binding")
    progress = _mapping_at(contract, "progress")
    integrity = _mapping_at(contract, "claim_integrity")
    if not _string_at(specialist, "id"):
        errors.append("specialist_work_quality specialist.id is required")
    if _string_at(application, "status") != PREPARED_NOT_OBSERVED or not _string_at(application, "selected_skill"):
        errors.append("specialist_work_quality skill application must remain prepared and name a skill")
    if not _string_at(goal, "binding_digest") or not isinstance(goal.get("criteria"), list):
        errors.append("specialist_work_quality goal binding and criteria are required")
    if _string_at(binding, "selected_skill") != _string_at(application, "selected_skill"):
        errors.append("specialist_work_quality evidence binding must match selected skill")
    if _string_at(binding, "specialist_id") != _string_at(specialist, "id") or not _string_at(binding, "plan_digest"):
        errors.append("specialist_work_quality evidence binding must match specialist and plan")
    if _int_at(progress, "observed_goal_achievement_percent", -1) != 0:
        errors.append("prepared specialist_work_quality cannot report observed goal achievement")
    if _string_at(integrity, "state") != "unverified":
        errors.append("prepared specialist_work_quality claim integrity must remain unverified")
    if "not execution" not in _string_at(contract, "claim_boundary").lower():
        errors.append("specialist_work_quality claim boundary must reject execution claims")
    return errors


def _mapping_at(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    item = value.get(key)
    return item if isinstance(item, Mapping) else {}


def _string_at(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    return item if isinstance(item, str) else ""


def _int_at(value: Mapping[str, object], key: str, default: int) -> int:
    item = value.get(key)
    return item if isinstance(item, int) and not isinstance(item, bool) else default
