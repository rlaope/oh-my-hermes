from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

from ..ingress import CHAT_SOURCES
from ..routing.action_copy import next_action_label
from ..wrapper.contract import build_chat_interaction_payload
from .common_request_cases import COMMON_REQUEST_COVERAGE_CASES, CommonRequestCoverageCase
from .popular_plugin_coverage import build_popular_plugin_coverage_demo, popular_plugin_coverage_errors


COMMON_REQUEST_COVERAGE_SCHEMA_VERSION = "common_request_coverage/v1"
COMMON_REQUEST_TARGET_PERCENT = 95.0


def build_common_request_coverage_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    rows = [_evaluate_case(case, source=source) for case in COMMON_REQUEST_COVERAGE_CASES]
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    case_count = len(rows)
    coverage_percent = round((passing_count / max(1, case_count)) * 100, 1)
    family_rows = _family_summary(rows)
    popular_plugin_coverage = build_popular_plugin_coverage_demo(cases=rows)
    plugin_summary = _nested(popular_plugin_coverage, "summary")
    return {
        "schema_version": COMMON_REQUEST_COVERAGE_SCHEMA_VERSION,
        "source": source,
        "target_percent": COMMON_REQUEST_TARGET_PERCENT,
        "summary": {
            "case_count": case_count,
            "passing_count": passing_count,
            "failing_count": case_count - passing_count,
            "coverage_percent": coverage_percent,
            "target_met": coverage_percent >= COMMON_REQUEST_TARGET_PERCENT,
            "family_count": len(family_rows),
            "workflow_count": len({str(row["observed"]["workflow"]) for row in rows}),
            "dispatch_count": sum(1 for row in rows if row["observed"]["route_action"] == "dispatch"),
            "fallback_count": sum(1 for row in rows if row["observed"]["route_action"] == "fallback"),
            "generic_ack_count": sum(1 for row in rows if row["observed"]["kind"] == "ack"),
            "popular_plugin_family_count": plugin_summary.get("family_count", 0),
            "popular_plugin_covered_family_count": plugin_summary.get("covered_family_count", 0),
            "popular_plugin_weighted_coverage_percent": plugin_summary.get("weighted_coverage_percent", 0),
            "popular_plugin_target_percent": popular_plugin_coverage.get("target_percent", 0),
        },
        "check_basis": [
            (
                "Representative ordinary Hermes-agent requests land on the expected OMH workflow "
                "or intentional direct fallback."
            ),
            "The wrapper response exposes a next action, claim boundary, and renderable actions for every case.",
            "The target is at least 95% deterministic coverage over this curated local common-request corpus.",
            "Popular plugin-style request families are checked as a 100-point weighted local coverage heuristic.",
            (
                "Dedicated-card polish, live Hermes rendering, connector execution, and coding-agent work "
                "are verified by separate gates."
            ),
        ],
        "families": family_rows,
        "popular_plugin_coverage": popular_plugin_coverage,
        "cases": rows,
        "claim_boundary": (
            "Common request coverage proves deterministic local routing breadth over a curated OMH request "
            "corpus only. "
            "Its popular-plugin rollup is a local heuristic, not external plugin telemetry. It is not live Hermes chat "
            "rendering, connector execution, source retrieval, file generation, executor dispatch, implementation, "
            "verification, review, CI, merge, delivery, or market-share evidence."
        ),
    }


def format_common_request_coverage_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _mapping_rows(payload.get("cases"))
    passing = int(summary.get("passing_count", 0) or 0)
    total = int(summary.get("case_count", len(rows)) or 0)
    coverage = float(summary.get("coverage_percent", 0.0) or 0.0)
    target = float(payload.get("target_percent", COMMON_REQUEST_TARGET_PERCENT) or COMMON_REQUEST_TARGET_PERCENT)
    target_status = "met" if bool(summary.get("target_met")) else "missed"
    lines = [
        "OMH common request coverage",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {passing}/{total} cases passing ({coverage:.1f}%; target {target:.1f}% {target_status})",
        (
            f"Families: {summary.get('family_count', 0)}; workflows: {summary.get('workflow_count', 0)}; "
            f"dispatch {summary.get('dispatch_count', 0)}; fallback {summary.get('fallback_count', 0)}; "
            f"generic ack {summary.get('generic_ack_count', 0)}"
        ),
        (
            "Popular plugin families: "
            f"{summary.get('popular_plugin_covered_family_count', 0)}/"
            f"{summary.get('popular_plugin_family_count', 0)} "
            f"({summary.get('popular_plugin_weighted_coverage_percent', 0)}%; "
            f"target {summary.get('popular_plugin_target_percent', 0)}%)"
        ),
        "",
        "What this proves:",
    ]
    for basis in _string_items(payload.get("check_basis")):
        lines.append(f"- {basis}")
    lines.extend(["", "Family rollup:"])
    for family in _mapping_rows(payload.get("families")):
        family_status = "ok" if bool(family.get("target_met")) else "needs attention"
        lines.append(
            f"- {family.get('family', 'unknown')}: {family_status}; "
            f"{family.get('passing_count', 0)}/{family.get('case_count', 0)} "
            f"({float(family.get('coverage_percent', 0.0) or 0.0):.1f}%)"
        )
    failed = [row for row in rows if not row.get("passed")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(
                f"- {row.get('id', 'unknown')}: "
                f"{', '.join(_string_items(row.get('issues'))) or 'unknown issue'}"
            )
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def common_request_coverage_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != COMMON_REQUEST_COVERAGE_SCHEMA_VERSION:
        errors.append("unexpected_schema")
    summary = _nested(payload, "summary")
    if not bool(summary.get("target_met")):
        errors.append(
            f"coverage_below_target: {summary.get('coverage_percent', 0)} < "
            f"{payload.get('target_percent', COMMON_REQUEST_TARGET_PERCENT)}"
        )
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    plugin_coverage = payload.get("popular_plugin_coverage")
    if isinstance(plugin_coverage, Mapping):
        errors.extend(f"popular_plugin_coverage: {error}" for error in popular_plugin_coverage_errors(plugin_coverage))
    else:
        errors.append("popular_plugin_coverage_missing")
    for case in _mapping_rows(cases):
        if case.get("passed"):
            continue
        errors.append(f"{case.get('id', 'unknown')}: {', '.join(_string_items(case.get('issues'))) or 'failed'}")
    return errors


def _evaluate_case(case: CommonRequestCoverageCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(case.message, source=source)
    route = _nested(interaction, "route")
    response = _nested(interaction, "chat_response")
    actions = _mapping_rows(response.get("actions"))
    observed = {
        "route_action": str(route.get("action", "")),
        "workflow": str(route.get("selected_skill", "")),
        "kind": str(response.get("kind", "")),
        "next_action": str(interaction.get("next_action", "")),
        "confidence": str(route.get("confidence", "")),
        "claim_boundary": str(response.get("claim_boundary", "")),
        "action_count": len(actions),
        "primary_action_count": sum(1 for action in actions if action.get("style") == "primary"),
    }
    issues: list[str] = []
    if observed["route_action"] != case.expected_route_action:
        issues.append(f"expected route action {case.expected_route_action}, observed {observed['route_action']}")
    if observed["workflow"] != case.expected_workflow:
        issues.append(f"expected workflow {case.expected_workflow}, observed {observed['workflow']}")
    if observed["kind"] != case.expected_kind:
        issues.append(f"expected kind {case.expected_kind}, observed {observed['kind']}")
    if observed["next_action"] != case.expected_next_action:
        issues.append(f"expected next action {case.expected_next_action}, observed {observed['next_action']}")
    if not observed["claim_boundary"].strip():
        issues.append("missing claim boundary")
    if observed["action_count"] < 1:
        issues.append("missing renderable actions")
    if observed["primary_action_count"] < 1:
        issues.append("missing primary action")
    return {
        "id": case.id,
        "family": case.family,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "passed": not issues,
        "expected": {
            "route_action": case.expected_route_action,
            "workflow": case.expected_workflow,
            "kind": case.expected_kind,
            "next_action": case.expected_next_action,
        },
        "observed": observed,
        "next_action_label": next_action_label(case.expected_next_action),
        "issues": issues,
    }


def _family_summary(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    families = sorted({str(row.get("family", "")) for row in rows if str(row.get("family", ""))})
    summary: list[dict[str, object]] = []
    for family in families:
        family_rows = [row for row in rows if row.get("family") == family]
        passing_count = sum(1 for row in family_rows if bool(row.get("passed")))
        total = len(family_rows)
        coverage = round((passing_count / max(1, total)) * 100, 1)
        summary.append(
            {
                "family": family,
                "case_count": total,
                "passing_count": passing_count,
                "coverage_percent": coverage,
                "target_met": coverage >= COMMON_REQUEST_TARGET_PERCENT,
            }
        )
    return summary


def _nested(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]
