from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeGuard

from ..capabilities.hooks import hook_manifest
from ..capabilities.skills import skill_capabilities
from ..routing.chat import route_chat_message
from .common_request_coverage import build_common_request_coverage_demo
from .routing_precision import build_routing_precision_demo


CAPABILITY_IMPACT_SCHEMA_VERSION = "omh_capability_impact_report/v1"


@dataclass(frozen=True, slots=True)
class ImpactRouteCase:
    id: str
    message: str
    expected_skill: str


REPRESENTATIVE_ROUTE_CASES = (
    ImpactRouteCase("tdd-en", "Please write tests first and implement this with TDD", "ultraprocess"),
    ImpactRouteCase("tdd-ko", "이 기능 테스트부터 작성하고 TDD로 구현해줘", "ultraprocess"),
    ImpactRouteCase("literature-en", "Do a literature review of recent agent memory papers", "web-research"),
    ImpactRouteCase("literature-ko", "이 논문들 문헌 검토하고 근거를 정리해줘", "web-research"),
    ImpactRouteCase("visual-qa-en", "Analyze this screenshot for UI layout problems", "visual-qa"),
    ImpactRouteCase("visual-qa-ko", "이 스크린샷 UI 레이아웃 문제를 분석해줘", "visual-qa"),
    ImpactRouteCase("durable-goal-ko", "이 목표를 오래 실행하면서 완료조건까지 계속 진행해줘", "ultragoal"),
    ImpactRouteCase("deploy-en", "Deploy this service to production infrastructure", "deploy-and-monitor"),
    ImpactRouteCase("deploy-ko", "이 서비스를 프로덕션 인프라에 배포해줘", "deploy-and-monitor"),
    ImpactRouteCase("session-en", "Find and recover my previous Codex coding session", "harness-session-inventory"),
    ImpactRouteCase("session-ko", "지난 코딩 세션을 찾아서 기억을 복구해줘", "harness-session-inventory"),
    ImpactRouteCase("image-edit", "Edit this image to remove the background", "img-summary"),
    ImpactRouteCase("video-generate", "Generate a short product demo video", "external-connector-readiness"),
    ImpactRouteCase("home-assistant", "Check whether Home Assistant can control this device", "external-connector-readiness"),
    ImpactRouteCase("testing-article", "Write an article about testing best practices", "best-practice-research"),
    ImpactRouteCase("pull-request-review", "Review this pull request code", "ultraprocess"),
    ImpactRouteCase("csv-analysis", "Analyze this CSV dataset", "data-analysis"),
    ImpactRouteCase("quick-plan", "Make a quick implementation plan", "plan"),
    ImpactRouteCase("video-summary", "Summarize this product demo video with timestamps", "media-input-operator"),
    ImpactRouteCase("screenshot-ocr", "Extract text from this screenshot with OCR", "media-input-operator"),
    ImpactRouteCase("image-card", "Generate an image card for these release notes", "img-summary"),
    ImpactRouteCase("slack-route", "Route this Slack thread silently unless action is needed", "gateway-intent-card"),
)


def build_capability_impact_report(
    *,
    source: str = "installed_package",
    route_source: str = "discord",
) -> dict[str, object]:
    precision = build_routing_precision_demo(source=route_source)
    coverage = build_common_request_coverage_demo(source=route_source)
    representative = _representative_route_result(source=route_source)
    precision_summary = _mapping(precision.get("summary"))
    coverage_summary = _mapping(coverage.get("summary"))
    representative_total = _int_value(representative.get("total"))
    representative_passing = representative_total > 0 and (
        _int_value(representative.get("passed")) == representative_total
    )
    route_contract_passing = bool(precision_summary.get("all_passing")) and bool(
        coverage_summary.get("target_met")
    ) and representative_passing

    skills = skill_capabilities()
    hooks = hook_manifest()
    plugin_tools = _mapping_rows(hooks.get("plugin_tools"))
    plugin_hooks = _mapping_rows(hooks.get("plugin_hooks"))
    quality_bars = sum(1 for skill in skills if _string_items(skill.get("quality_bar")))
    pre_verify_registered = any(hook.get("name") == "pre_verify" for hook in plugin_hooks)

    route_selection = {
        "fixed_precision": {
            "passed": _int_value(precision_summary.get("total_passing_count")),
            "total": _int_value(precision_summary.get("total_case_count")),
            "overroutes": _int_value(precision_summary.get("overroute_count")),
            "missed_interventions": _int_value(precision_summary.get("missed_intervention_count")),
        },
        "common_requests": {
            "passed": _int_value(coverage_summary.get("passing_count")),
            "total": _int_value(coverage_summary.get("case_count")),
            "coverage_percent": _float_value(coverage_summary.get("coverage_percent")),
            "target_met": bool(coverage_summary.get("target_met")),
            "popular_plugin_families": {
                "covered": _int_value(coverage_summary.get("popular_plugin_covered_family_count")),
                "total": _int_value(coverage_summary.get("popular_plugin_family_count")),
                "weighted_coverage_percent": _float_value(
                    coverage_summary.get("popular_plugin_weighted_coverage_percent")
                ),
            },
        },
        "representative": representative,
    }
    dimensions = [
        _dimension(
            "route_selection",
            "passing_local_contract" if route_contract_passing else "failing_local_contract",
            route_selection,
            "Deterministic in-repo corpora check expected route choices; they do not prove live task outcomes.",
        ),
        _dimension(
            "guidance_depth",
            "partially_proven",
            {"skills": len(skills), "skills_with_quality_bars": quality_bars},
            "Catalog guidance is inspectable, but outcome improvement needs paired task evaluation.",
        ),
        _dimension(
            "native_execution_availability",
            "requires_host_observation",
            {"plugin_tools_registered": len(plugin_tools), "plugin_hooks_registered": len(plugin_hooks)},
            "Registration metadata does not prove that a Hermes host loaded or invoked a surface.",
        ),
        _dimension(
            "provider_execution_availability",
            "requires_provider_observation",
            {"provider_classes": ["browser", "connector", "image", "video"]},
            "External providers vary by installation and require observed provider evidence.",
        ),
        _dimension(
            "artifact_verification",
            "partially_proven",
            {"pre_verify_registered": pre_verify_registered, "runtime_invocation_observed": False},
            "The hook requests served-surface checks; it does not turn guidance into verification evidence.",
        ),
        _dimension(
            "comparative_outcome_quality",
            "requires_external_evaluator",
            {"paired_tasks_observed": 0, "evaluator": "not_run"},
            "Claims that OMH beats another setup require blinded paired tasks and an external evaluator.",
        ),
    ]
    return {
        "schema_version": CAPABILITY_IMPACT_SCHEMA_VERSION,
        "source": source,
        "degraded": False,
        "determinism": "local_contract_evaluation_no_network_or_model_calls",
        "verdict": "partially_proven" if route_contract_passing else "needs_attention",
        "score_policy": (
            "No aggregate score: route accuracy, guidance, host availability, provider availability, "
            "artifact verification, and comparative quality are separate claims."
        ),
        "dimensions": dimensions,
        "route_selection": route_selection,
        "claim_boundaries": [
            "Prepared or registered capability is not observed execution.",
            "A routed skill is not proof that its runtime, provider, or artifact succeeded.",
            "Comparative quality remains unproven until an external paired evaluator is run.",
        ],
    }


def format_capability_impact_summary(payload: Mapping[str, object]) -> str:
    route_selection = _mapping(payload.get("route_selection"))
    precision = _mapping(route_selection.get("fixed_precision"))
    coverage = _mapping(route_selection.get("common_requests"))
    representative = _mapping(route_selection.get("representative"))
    lines = [
        "OMH capability impact",
        f"Verdict: {payload.get('verdict', 'unknown')}",
        f"Fixed routing precision: {precision.get('passed', 0)}/{precision.get('total', 0)}",
        f"Common requests: {coverage.get('passed', 0)}/{coverage.get('total', 0)}",
        f"Representative requests: {representative.get('passed', 0)}/{representative.get('total', 0)}",
        "",
        "Evidence dimensions:",
    ]
    for dimension in _mapping_rows(payload.get("dimensions")):
        lines.append(f"- {dimension.get('id', 'unknown')}: {dimension.get('status', 'unknown')}")
        lines.append(f"  Boundary: {dimension.get('boundary', '')}")
    lines.extend(
        [
            "",
            (
                "Observation note: Host and provider execution remain unproven until observed; "
                "artifact verification needs a recorded result, and comparative outcomes require external evaluation."
            ),
            str(payload.get("score_policy", "")),
            "Use --json for the full report.",
        ]
    )
    return "\n".join(lines)


def _representative_route_result(*, source: str) -> dict[str, object]:
    failed: list[dict[str, str]] = []
    for case in REPRESENTATIVE_ROUTE_CASES:
        route = route_chat_message(case.message, source=source)
        observed = str(route.get("selected_skill", ""))
        if route.get("action") != "dispatch" or observed != case.expected_skill:
            failed.append({"id": case.id, "expected": case.expected_skill, "observed": observed})
    return {
        "passed": len(REPRESENTATIVE_ROUTE_CASES) - len(failed),
        "total": len(REPRESENTATIVE_ROUTE_CASES),
        "failed": failed,
        "evidence_class": "implementation_smoke",
    }


def _dimension(id_: str, status: str, evidence: object, boundary: str) -> dict[str, object]:
    return {"id": id_, "status": status, "evidence": evidence, "boundary": boundary}


def _mapping(value: object) -> dict[str, object]:
    if not _is_object_mapping(value):
        return {}
    return _string_keyed_mapping(value)


def _is_object_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _string_keyed_mapping(value: Mapping[object, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if not _is_object_sequence(value):
        return []
    return _mapping_sequence_rows(value)


def _is_object_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _mapping_sequence_rows(value: Sequence[object]) -> list[dict[str, object]]:
    return [_string_keyed_mapping(item) for item in value if _is_object_mapping(item)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]


def _int_value(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _float_value(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0
