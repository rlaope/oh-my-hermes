from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


POPULAR_PLUGIN_COVERAGE_SCHEMA_VERSION = "popular_plugin_coverage/v1"
POPULAR_PLUGIN_TARGET_PERCENT = 95.0


@dataclass(frozen=True)
class PopularPluginFamily:
    family_id: str
    title: str
    weight: int
    typical_plugins: tuple[str, ...]
    case_ids: tuple[str, ...]
    coverage_contract: str


POPULAR_PLUGIN_FAMILIES: tuple[PopularPluginFamily, ...] = (
    PopularPluginFamily(
        "web_search_and_sources",
        "Web search, citations, papers, and source discovery",
        10,
        ("web-search", "scholar", "github-search", "dataset-search"),
        ("web-research", "source-finder", "paper-learning", "research-department"),
        "Routes source-heavy asks to research/source cards with citation and freshness boundaries.",
    ),
    PopularPluginFamily(
        "browser_and_live_info",
        "Browser checks and live/local information lookups",
        8,
        (
            "browser",
            "weather",
            "news",
            "finance",
            "sports",
            "maps",
            "timezone",
            "webpage-check",
        ),
        (
            "browser-operator",
            "live-info-operator",
            "time-zone-lookup",
            "exchange-rate-lookup",
            "crypto-price-lookup",
            "sports-score-lookup",
            "nearby-place-lookup",
            "visual-qa",
        ),
        "Prepares browser/live-info cards without claiming the live provider was called.",
    ),
    PopularPluginFamily(
        "files_shell_and_workspace",
        "Files, shell commands, and workspace audits",
        10,
        ("filesystem", "terminal", "workspace", "codegraph"),
        ("workspace-file-operator", "command-operator", "file-lookup", "workspace-audit", "codegraph-refresh"),
        "Separates direct file lookup from risky file, shell, workspace, and index operations.",
    ),
    PopularPluginFamily(
        "github_and_coding_delivery",
        "GitHub, code review, PR, and coding handoff work",
        13,
        ("github", "pull-request", "codex", "claude-code", "ci"),
        (
            "github-issue-to-pr",
            "release-readiness-review",
            "ai-coding-safety-review",
            "executor-runtime-choice",
            "coding-progress-status",
            "hermes-coding-team",
            "verification-gate",
            "build-failure-triage",
        ),
        "Turns coding delivery into explicit handoff, review, status, CI, and evidence gates.",
    ),
    PopularPluginFamily(
        "docs_slides_pdf_and_visuals",
        "Documents, slides, PDFs, media, posters, and frontend/design QA",
        10,
        ("docs", "sheets", "slides", "pdf", "image", "frontend", "accessibility", "transcription", "youtube"),
        (
            "report-package",
            "materials-package",
            "deliverable-package",
            "img-summary-poster",
            "design-quality-gate",
            "frontend-handoff",
            "accessibility-audit",
            "content-operator",
            "audio-transcription-summary",
            "youtube-video-summary",
        ),
        "Prepares publishable material, frontend, media-input, and visual QA flows with render/evidence boundaries.",
    ),
    PopularPluginFamily(
        "communications_and_connectors",
        "Email, chat, meeting, gateway, and scheduled connector work",
        9,
        ("email", "slack", "discord", "telegram", "calendar", "scheduler"),
        ("connector-operator", "gateway-intent", "automation-blueprint", "meeting-brief", "operating-rhythm"),
        "Models outbound connector work behind confirmation gates and delivery-policy cards.",
    ),
    PopularPluginFamily(
        "ops_metrics_and_reliability",
        "Metrics, observability, deploy, incident, and reliability work",
        12,
        ("prometheus", "grafana", "sentry", "datadog", "pagerduty"),
        (
            "ops-observability",
            "external-metric-provider",
            "reliability-review",
            "deploy-and-monitor",
            "production-audit",
            "ops-review",
            "performance-goal",
        ),
        "Keeps metric-provider analysis, SLOs, incident review, rollout, and rollback work evidence-bound.",
    ),
    PopularPluginFamily(
        "data_analysis_and_reporting",
        "CSV, tables, charts, and analysis reporting",
        6,
        ("csv", "spreadsheet", "charting", "analytics"),
        ("data-analysis", "materials-package", "report-package"),
        "Routes data work to analysis/material cards instead of treating files as generic attachments.",
    ),
    PopularPluginFamily(
        "knowledge_memory_and_learning",
        "Memory, wiki, rules, skill health, and learning loops",
        10,
        ("memory", "wiki", "rules", "skills", "learning"),
        (
            "memory-curation",
            "workflow-learning",
            "rules-distill",
            "skill-scout",
            "skill-health",
            "agent-debug",
            "context-budget",
            "harness-session-inventory",
            "instinct-ledger",
        ),
        "Keeps durable knowledge and learning work reviewed, bounded, and distinct from execution evidence.",
    ),
    PopularPluginFamily(
        "agent_orchestration_and_safety",
        "Subagents, evaluation, safety, and operator control",
        12,
        ("subagents", "evaluation", "security-review", "toolbelt", "manager-dashboard"),
        ("agent-board", "agent-evaluation", "agent-ops-status", "security-safety", "toolbelt-readiness"),
        "Gives multi-agent operation explicit boards, evaluation rubrics, and safety boundaries.",
    ),
)


def build_popular_plugin_coverage_demo(*, cases: Sequence[Mapping[str, object]]) -> dict[str, object]:
    case_rows = _mapping_rows(cases)
    indexed = {str(row.get("id", "")): row for row in case_rows if str(row.get("id", ""))}
    families = [_evaluate_family(family, cases=indexed) for family in POPULAR_PLUGIN_FAMILIES]
    unique_case_ids = sorted({case_id for family in POPULAR_PLUGIN_FAMILIES for case_id in family.case_ids})
    passing_unique_case_count = sum(1 for case_id in unique_case_ids if bool(indexed.get(case_id, {}).get("passed")))
    total_weight = sum(int(row["weight"]) for row in families)
    covered_weight = sum(int(row["weight"]) for row in families if bool(row["covered"]))
    weighted_coverage = round((covered_weight / max(1, total_weight)) * 100, 1)
    return {
        "schema_version": POPULAR_PLUGIN_COVERAGE_SCHEMA_VERSION,
        "target_percent": POPULAR_PLUGIN_TARGET_PERCENT,
        "summary": {
            "family_count": len(families),
            "covered_family_count": sum(1 for row in families if bool(row["covered"])),
            "case_reference_count": sum(int(row["case_count"]) for row in families),
            "covered_case_reference_count": sum(int(row["passing_case_count"]) for row in families),
            "unique_case_count": len(unique_case_ids),
            "covered_unique_case_count": passing_unique_case_count,
            "total_weight": total_weight,
            "covered_weight": covered_weight,
            "weighted_coverage_percent": weighted_coverage,
            "target_met": weighted_coverage >= POPULAR_PLUGIN_TARGET_PERCENT,
            "generic_ack_count": sum(int(row["generic_ack_count"]) for row in families),
        },
        "families": families,
        "check_basis": [
            "High-frequency plugin-style request families map to already verified common-request cases.",
            "Each family must have at least one dispatch route so it is not covered only by a direct fallback.",
            "Dispatch rows must avoid generic acknowledgements and retain claim-boundary copy.",
            "Weights are a local product heuristic for coverage breadth, not external plugin telemetry.",
        ],
        "claim_boundary": (
            "Popular plugin coverage is a deterministic local family-weighted heuristic over OMH common-request "
            "cases. It is not Hermes plugin telemetry, connector execution, live provider access, platform delivery, "
            "coding-agent execution, review, CI, merge, or market-share evidence."
        ),
    }


def popular_plugin_coverage_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != POPULAR_PLUGIN_COVERAGE_SCHEMA_VERSION:
        errors.append("unexpected_schema")
    summary = _nested(payload, "summary")
    if not bool(summary.get("target_met")):
        errors.append(
            f"popular_plugin_coverage_below_target: {summary.get('weighted_coverage_percent', 0)} < "
            f"{payload.get('target_percent', POPULAR_PLUGIN_TARGET_PERCENT)}"
        )
    for family in _mapping_rows(payload.get("families")):
        if family.get("covered"):
            continue
        errors.append(
            f"{family.get('family_id', 'unknown')}: "
            f"{', '.join(_string_items(family.get('issues'))) or 'failed'}"
        )
    return errors


def _evaluate_family(
    family: PopularPluginFamily,
    *,
    cases: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    rows = [cases[case_id] for case_id in family.case_ids if case_id in cases]
    missing = [case_id for case_id in family.case_ids if case_id not in cases]
    failed = [str(row.get("id", "unknown")) for row in rows if not row.get("passed")]
    dispatch_rows = [row for row in rows if _nested(row, "observed").get("route_action") == "dispatch"]
    generic_ack = [
        str(row.get("id", "unknown"))
        for row in dispatch_rows
        if _nested(row, "observed").get("kind") == "ack"
    ]
    missing_boundary = [
        str(row.get("id", "unknown"))
        for row in rows
        if not str(_nested(row, "observed").get("claim_boundary", "")).strip()
    ]
    issues: list[str] = []
    if missing:
        issues.append(f"missing cases {', '.join(missing)}")
    if failed:
        issues.append(f"failing cases {', '.join(failed)}")
    if not dispatch_rows:
        issues.append("no dispatch-backed case")
    if generic_ack:
        issues.append(f"generic ack dispatch cases {', '.join(generic_ack)}")
    if missing_boundary:
        issues.append(f"missing boundary cases {', '.join(missing_boundary)}")
    return {
        "family_id": family.family_id,
        "title": family.title,
        "weight": family.weight,
        "typical_plugins": list(family.typical_plugins),
        "coverage_contract": family.coverage_contract,
        "case_ids": list(family.case_ids),
        "case_count": len(family.case_ids),
        "observed_case_count": len(rows),
        "passing_case_count": sum(1 for row in rows if bool(row.get("passed"))),
        "dispatch_case_count": len(dispatch_rows),
        "generic_ack_count": len(generic_ack),
        "observed_workflows": sorted({str(_nested(row, "observed").get("workflow", "")) for row in rows if row}),
        "observed_kinds": sorted({str(_nested(row, "observed").get("kind", "")) for row in rows if row}),
        "covered": not issues,
        "issues": issues,
    }


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
