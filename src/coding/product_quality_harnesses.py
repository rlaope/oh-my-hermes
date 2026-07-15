from __future__ import annotations

from copy import deepcopy
from typing import Any

from .product_family_templates import PRODUCT_FAMILIES, product_family_template, validate_product_family_template


PRODUCT_QUALITY_HARNESS_SCHEMA_VERSION = "product_quality_harness/v1"

_STAGES: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "web": (
        ("reproduce", "Define the affected route, browser state, and deterministic reproduction path.", ("reproduction_steps",)),
        ("functional_accuracy", "Verify the requested behavior with targeted checks.", ("test_or_interaction_evidence",)),
        ("responsive_layout", "Review narrow, default, and wide layout states.", ("rendered_capture_or_layout_evidence",)),
        ("accessibility", "Review keyboard, focus, semantic, and contrast expectations.", ("accessibility_evidence",)),
        ("performance", "Measure the declared interaction or rendering budget when a runnable target exists.", ("performance_measurement",)),
        ("report", "Separate observed results, failures, and remaining evidence gaps.", ("result_summary",)),
    ),
    "mobile": (
        ("reproduce", "Define the affected device, OS, viewport, and reproduction path.", ("reproduction_steps",)),
        ("functional_accuracy", "Verify the requested behavior with targeted checks.", ("test_or_interaction_evidence",)),
        ("device_layout", "Review compact and large-device render states.", ("device_capture_or_layout_evidence",)),
        ("touch_accessibility", "Review touch targets, focus, assistive technology, and orientation expectations.", ("accessibility_evidence",)),
        ("performance", "Measure the declared startup, interaction, or rendering budget when a runnable target exists.", ("performance_measurement",)),
        ("report", "Separate observed results, failures, and remaining evidence gaps.", ("result_summary",)),
    ),
    "desktop": (
        ("reproduce", "Define the affected OS, window state, and deterministic reproduction path.", ("reproduction_steps",)),
        ("functional_accuracy", "Verify the requested behavior with targeted checks.", ("test_or_interaction_evidence",)),
        ("window_layout", "Review resize, scale, empty, error, and restored-window states.", ("rendered_capture_or_layout_evidence",)),
        ("keyboard_accessibility", "Review keyboard navigation, focus, shortcuts, and native accessibility expectations.", ("accessibility_evidence",)),
        ("performance", "Measure the declared startup, interaction, or rendering budget when a runnable target exists.", ("performance_measurement",)),
        ("report", "Separate observed results, failures, and remaining evidence gaps.", ("result_summary",)),
    ),
    "api": (
        ("reproduce", "Define the request shape, auth boundary, and deterministic reproduction path.", ("request_fixture_or_reproduction_steps",)),
        ("contract_accuracy", "Verify success, validation, and error-path response contracts.", ("contract_test_or_response_evidence",)),
        ("error_security", "Review authorization, input validation, redaction, and failure behavior.", ("security_or_error_path_evidence",)),
        ("performance", "Measure the declared latency, throughput, or resource budget when a runnable target exists.", ("performance_measurement",)),
        ("report", "Separate observed results, failures, and remaining evidence gaps.", ("result_summary",)),
    ),
}


def product_quality_harness(family: str) -> dict[str, object]:
    if family not in PRODUCT_FAMILIES:
        raise ValueError(f"unsupported product family: {family}")
    stages = [
        {
            "id": stage_id,
            "purpose": purpose,
            "required_observed_evidence": list(evidence),
            "state": "prepared",
        }
        for stage_id, purpose, evidence in _STAGES[family]
    ]
    return {
        "schema_version": PRODUCT_QUALITY_HARNESS_SCHEMA_VERSION,
        "family": family,
        "status": "prepared_not_observed",
        "product_family_template": product_family_template(family),
        "stages": stages,
        "stop_conditions": [
            "A required evidence source is unavailable or unsafe to collect.",
            "The requested behavior cannot be reproduced within the declared scope.",
            "A result would require claiming execution, review, or measurement that was not observed.",
        ],
        "claim_boundary": (
            "This prepared quality harness does not run tests, launch an app, capture a screen, inspect a device, "
            "measure performance, or prove layout, accessibility, correctness, review, CI, or merge status."
        ),
    }


def validate_product_quality_harness(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["product quality harness must be an object"]
    required = {
        "schema_version",
        "family",
        "status",
        "product_family_template",
        "stages",
        "stop_conditions",
        "claim_boundary",
    }
    errors: list[str] = []
    if set(value) != required:
        errors.append("product quality harness keys are invalid")
    family = value.get("family")
    if not isinstance(family, str) or family not in PRODUCT_FAMILIES:
        return [*errors, "product quality harness family is invalid"]
    expected = product_quality_harness(family)
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"product quality harness {key} is invalid")
    template = value.get("product_family_template")
    errors.extend(validate_product_family_template(template))
    return errors


def compact_product_quality_harness(value: Any) -> dict[str, object]:
    if not isinstance(value, dict) or validate_product_quality_harness(value):
        return {}
    return deepcopy(value)
