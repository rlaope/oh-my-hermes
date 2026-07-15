from __future__ import annotations

from ..quality.common_request_cases import COMMON_REQUEST_COVERAGE_CASES, CommonRequestCoverageCase


def natural_language_starters() -> list[dict[str, str]]:
    """Project one verified plain-language request from each covered family."""
    selected: dict[str, CommonRequestCoverageCase] = {}
    for case in COMMON_REQUEST_COVERAGE_CASES:
        selected.setdefault(case.family, case)
    return [_starter_payload(case) for case in selected.values()]


def _starter_payload(case: CommonRequestCoverageCase) -> dict[str, str]:
    return {
        "id": case.id,
        "family": case.family,
        "label": case.title,
        "prompt": case.message,
        "expected_route_action": case.expected_route_action,
        "expected_workflow": case.expected_workflow,
        "expected_kind": case.expected_kind,
        "next_action": case.expected_next_action,
        "selection_basis": "common_request_coverage",
        "claim_boundary": (
            "A starter is a local routing example, not evidence that Hermes, a connector, "
            "or a coding executor completed work."
        ),
    }
