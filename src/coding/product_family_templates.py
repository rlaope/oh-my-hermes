from __future__ import annotations

from copy import deepcopy
from typing import Any


PRODUCT_FAMILY_TEMPLATE_SCHEMA_VERSION = "product_family_template/v1"
PRODUCT_FAMILIES = ("web", "mobile", "desktop", "api")

_TEMPLATES: dict[str, dict[str, object]] = {
    "web": {
        "template_id": "web-quality/v1",
        "quality_expectations": ["accessibility_review", "fresh_rendered_qa", "layout_consistency", "responsive_states"],
        "verification_expectations": ["rendered_evidence_when_available", "targeted_tests"],
        "recommended_skills": ["accessibility-audit", "frontend", "visual-qa"],
        "recommended_harnesses": ["accessibility-audit", "frontend", "visual-qa"],
    },
    "mobile": {
        "template_id": "mobile-quality/v1",
        "quality_expectations": ["accessibility_review", "device_render_qa", "small_viewport_states", "touch_state_review"],
        "verification_expectations": ["device_or_rendered_evidence_when_available", "targeted_tests"],
        "recommended_skills": ["accessibility-audit", "frontend", "visual-qa"],
        "recommended_harnesses": ["accessibility-audit", "frontend", "visual-qa"],
    },
    "desktop": {
        "template_id": "desktop-quality/v1",
        "quality_expectations": ["fresh_rendered_qa", "keyboard_accessibility", "native_surface_layout", "window_state_review"],
        "verification_expectations": ["rendered_evidence_when_available", "targeted_tests"],
        "recommended_skills": ["accessibility-audit", "visual-qa"],
        "recommended_harnesses": ["accessibility-audit", "visual-qa"],
    },
    "api": {
        "template_id": "api-quality/v1",
        "quality_expectations": ["authentication_boundary", "contract_error_paths", "response_consistency"],
        "verification_expectations": ["integration_evidence_when_available", "targeted_tests"],
        "recommended_skills": ["security-safety-review", "verification-gate"],
        "recommended_harnesses": ["security-safety-review", "verification-gate"],
    },
}


def product_family_template(family: str) -> dict[str, object]:
    if family not in _TEMPLATES:
        raise ValueError(f"unsupported product family: {family}")
    template = deepcopy(_TEMPLATES[family])
    template.update(
        {
            "schema_version": PRODUCT_FAMILY_TEMPLATE_SCHEMA_VERSION,
            "family": family,
            "status": "prepared_not_observed",
            "claim_boundary": "References are prepared guidance, not proof of installation, use, execution, or observation.",
        }
    )
    return template


def validate_product_family_template(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["product family template must be an object"]
    required = {
        "schema_version", "template_id", "family", "status", "quality_expectations", "verification_expectations",
        "recommended_skills", "recommended_harnesses", "claim_boundary",
    }
    errors: list[str] = []
    if set(value) != required:
        errors.append("product family template keys are invalid")
    family = value.get("family")
    if not isinstance(family, str) or family not in PRODUCT_FAMILIES:
        errors.append("product family template family is invalid")
        return errors
    expected = product_family_template(family)
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"product family template {key} is invalid")
    from ..skills.catalog import builtin_harnesses, installable_skill_names

    skills = set(installable_skill_names())
    harnesses = {harness.name for harness in builtin_harnesses()}
    if any(item not in skills for item in value.get("recommended_skills", [])):
        errors.append("product family template references an unknown skill")
    if any(item not in harnesses for item in value.get("recommended_harnesses", [])):
        errors.append("product family template references an unknown harness")
    return errors
