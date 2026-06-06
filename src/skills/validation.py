from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..harness_quality import HARNESS_QUALITY_KEYS, HARNESS_QUALITY_SCHEMA_VERSION
from .catalog import (
    HarnessDefinition,
    SkillDefinition,
    builtin_definitions,
    builtin_harnesses,
    harness_quality_contract,
    primary_harness_for_skill,
)


CATALOG_VALIDATION_SCHEMA_VERSION = "catalog_validation/v1"


def validate_catalog_contract() -> dict[str, object]:
    definitions = builtin_definitions()
    harnesses = builtin_harnesses()
    errors: list[str] = []
    warnings: list[str] = []

    skill_names = [definition.name for definition in definitions]
    harness_names = [harness.name for harness in harnesses]
    _require_unique(skill_names, "skill", errors)
    _require_unique(harness_names, "harness", errors)
    harness_name_set = set(harness_names)

    for definition in definitions:
        errors.extend(_validate_skill_definition(definition, harness_name_set))
    for harness in harnesses:
        quality = harness_quality_contract(harness.name)
        errors.extend(_validate_harness_definition(harness))
        errors.extend(_validate_harness_quality_payload(quality, f"harness {harness.name} harness_quality"))
        errors.extend(_validate_harness_quality_matches_definition(quality, harness))
    errors.extend(_validate_named_harness_gates({harness.name: harness for harness in harnesses}))

    return {
        "schema_version": CATALOG_VALIDATION_SCHEMA_VERSION,
        "ok": not errors,
        "counts": {"skills": len(definitions), "harnesses": len(harnesses)},
        "errors": errors,
        "warnings": warnings,
    }


def harness_summary_payload() -> dict[str, object]:
    definitions = builtin_definitions()
    skills_by_harness = _skills_by_harness(definitions)
    return {
        "schema_version": "harness_list/v1",
        "validation": validate_catalog_contract(),
        "harnesses": [
            {
                "name": harness.name,
                "purpose": harness.purpose,
                "quality_tier": harness.quality_tier,
                "evidence_ladder": list(harness.evidence_ladder),
                "wrapper_actions": list(harness.wrapper_actions),
                "primary_skills": skills_by_harness.get(harness.name, []),
            }
            for harness in builtin_harnesses()
        ],
    }


def harness_inspection_payload(name: str) -> dict[str, object]:
    definitions = builtin_definitions()
    skills_by_harness = _skills_by_harness(definitions)
    for harness in builtin_harnesses():
        if harness.name != name:
            continue
        quality = harness_quality_contract(name)
        validation_errors = _validate_harness_definition(harness) + _validate_harness_quality_payload(
            quality,
            f"harness {name} harness_quality",
        )
        validation_errors.extend(_validate_harness_quality_matches_definition(quality, harness))
        return {
            "schema_version": "harness_inspect/v1",
            "harness": _dataclass_payload(harness),
            "harness_quality": quality,
            "primary_skills": skills_by_harness.get(name, []),
            "validation": {
                "ok": not validation_errors,
                "errors": validation_errors,
            },
        }
    raise KeyError(name)


def _validate_skill_definition(definition: SkillDefinition, harness_names: set[str]) -> list[str]:
    errors: list[str] = []
    label = f"skill {definition.name}"
    _require_text(definition.name, f"{label} name", errors)
    _require_text(definition.description, f"{label} description", errors)
    _require_text(definition.use_when, f"{label} use_when", errors)
    for field in ("triggers", "required_inputs", "expected_outputs", "artifact_expectations", "safety_rules", "quality_bar"):
        _require_text_sequence(getattr(definition, field), f"{label} {field}", errors)
    primary_harness = primary_harness_for_skill(definition.name)
    if primary_harness not in harness_names:
        errors.append(f"{label} primary_harness is unknown: {primary_harness}")
    return errors


def _validate_harness_definition(harness: HarnessDefinition) -> list[str]:
    errors: list[str] = []
    label = f"harness {harness.name}"
    for field in ("name", "purpose", "use_when", "fallback", "delegation_expectation", "privacy_default", "quality_tier"):
        _require_text(getattr(harness, field), f"{label} {field}", errors)
    for field in (
        "required_inputs",
        "expected_outputs",
        "stop_conditions",
        "verification",
        "artifact_events",
        "quality_bar",
        "evidence_ladder",
        "wrapper_actions",
        "overclaim_guards",
    ):
        _require_text_sequence(getattr(harness, field), f"{label} {field}", errors)
    if harness.privacy_default != "metadata_only":
        errors.append(f"{label} privacy_default must be metadata_only")
    if len(set(harness.evidence_ladder)) != len(harness.evidence_ladder):
        errors.append(f"{label} evidence_ladder must not contain duplicate steps")
    return errors


def _validate_harness_quality_payload(value: dict[str, object], label: str) -> list[str]:
    errors: list[str] = []
    extra = sorted(set(value) - set(HARNESS_QUALITY_KEYS))
    missing = [key for key in HARNESS_QUALITY_KEYS if key not in value]
    if extra:
        errors.append(f"{label} has unsupported keys: {extra}")
    if missing:
        errors.append(f"{label} is missing keys: {missing}")
    if value.get("schema_version") != HARNESS_QUALITY_SCHEMA_VERSION:
        errors.append(f"{label} schema_version must be {HARNESS_QUALITY_SCHEMA_VERSION}")
    for key in ("harness", "quality_tier"):
        _require_text(value.get(key), f"{label} {key}", errors)
    for key in ("quality_bar", "evidence_ladder", "wrapper_actions", "overclaim_guards"):
        _require_text_sequence(value.get(key), f"{label} {key}", errors)
    return errors


def _validate_harness_quality_matches_definition(value: dict[str, object], harness: HarnessDefinition) -> list[str]:
    errors: list[str] = []
    expected = {
        "harness": harness.name,
        "quality_tier": harness.quality_tier,
        "quality_bar": list(harness.quality_bar),
        "evidence_ladder": list(harness.evidence_ladder),
        "wrapper_actions": list(harness.wrapper_actions),
        "overclaim_guards": list(harness.overclaim_guards),
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"harness {harness.name} harness_quality {key} must match catalog definition")
    return errors


def _validate_named_harness_gates(harnesses: dict[str, HarnessDefinition]) -> list[str]:
    errors: list[str] = []
    required_steps = {
        "deep-interview": ("ambiguity_identified", "blocking_question_asked", "answer_recorded", "clarified_brief_ready"),
        "planning": (
            "request_clarified",
            "plan_drafted",
            "option_tradeoffs_recorded",
            "test_strategy_recorded",
            "acceptance_recorded",
            "handoff_ready",
        ),
        "research": (
            "research_question_scoped",
            "primary_sources_checked",
            "conflicts_checked",
            "evidence_synthesized",
            "uncertainty_recorded",
        ),
    }
    for harness_name, steps in required_steps.items():
        harness = harnesses.get(harness_name)
        if not harness:
            errors.append(f"harness {harness_name} is required for Hermes-native quality gates")
            continue
        missing = [step for step in steps if step not in harness.evidence_ladder]
        if missing:
            errors.append(f"harness {harness_name} evidence_ladder is missing gate steps: {missing}")
    return errors


def _skills_by_harness(definitions: list[SkillDefinition]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for definition in definitions:
        grouped.setdefault(primary_harness_for_skill(definition.name), []).append(definition.name)
    return {key: sorted(value) for key, value in grouped.items()}


def _dataclass_payload(value: SkillDefinition | HarnessDefinition) -> dict[str, object]:
    data = asdict(value)
    return {key: list(item) if isinstance(item, tuple) else item for key, item in data.items()}


def _require_unique(values: list[str], label: str, errors: list[str]) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            errors.append(f"duplicate {label} name: {value}")
        seen.add(value)


def _require_text(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty string")


def _require_text_sequence(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, (tuple, list)) or not value:
        errors.append(f"{label} must be a non-empty list")
        return
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{label}[{index}] must be a non-empty string")
