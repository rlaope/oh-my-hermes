from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence

from ..ingress import CHAT_SOURCES
from ..routing.action_copy import next_action_label
from ..wrapper.contract import build_chat_interaction_payload


COMMON_REQUEST_COVERAGE_SCHEMA_VERSION = "common_request_coverage/v1"
COMMON_REQUEST_TARGET_PERCENT = 95.0


@dataclass(frozen=True)
class CommonRequestCoverageCase:
    id: str
    family: str
    title: str
    message: str
    expected_route_action: str
    expected_workflow: str
    expected_kind: str
    expected_next_action: str


COMMON_REQUEST_COVERAGE_CASES: tuple[CommonRequestCoverageCase, ...] = (
    CommonRequestCoverageCase(
        "feedback-triage",
        "plan_and_clarify",
        "Product feedback triage",
        "결제 실패 이슈가 자주 나와",
        "dispatch",
        "feedback-triage",
        "feedback_triage",
        "triage_feedback",
    ),
    CommonRequestCoverageCase(
        "deep-interview-product",
        "plan_and_clarify",
        "Ambiguous product shaping",
        "I need to improve our onboarding but I do not know where to start",
        "dispatch",
        "deep-interview",
        "clarification",
        "answer_clarification",
    ),
    CommonRequestCoverageCase(
        "safe-feature-plan",
        "plan_and_clarify",
        "Safe feature planning",
        "how can I safely add a feature to this repo?",
        "dispatch",
        "ralplan",
        "plan",
        "present_plan",
    ),
    CommonRequestCoverageCase(
        "release-readiness-review",
        "coding_and_delivery",
        "Release readiness review",
        "릴리즈 전에 README claim이 실제 코드와 맞는가, doctor/harness가 통과하는가 봐줘",
        "dispatch",
        "code-review",
        "review_check",
        "prepare_review_or_followup_handoff",
    ),
    CommonRequestCoverageCase(
        "ai-coding-safety-review",
        "coding_and_delivery",
        "AI coding claim review",
        "AI가 했다고 했는데 실제로 뭐 했는지 모르겠다",
        "dispatch",
        "code-review",
        "review_check",
        "prepare_review_or_followup_handoff",
    ),
    CommonRequestCoverageCase(
        "github-issue-to-pr",
        "coding_and_delivery",
        "GitHub issue to PR ops",
        "Make this GitHub issue into a PR, run review, update docs, and tell me what changed",
        "dispatch",
        "github-event-ops",
        "github_event_ops",
        "prepare_github_event_ops_card",
    ),
    CommonRequestCoverageCase(
        "executor-runtime-choice",
        "coding_and_delivery",
        "Coding runtime choice",
        "Should I use Codex or Claude Code for this coding task?",
        "dispatch",
        "executor-runtime-readiness",
        "executor_runtime_readiness",
        "prepare_executor_runtime_readiness",
    ),
    CommonRequestCoverageCase(
        "coding-progress-status",
        "coding_and_delivery",
        "Coding-agent progress status",
        "Codex 작업이 진행중인지 확인하고 지금 어떤 상태인지 알려줘",
        "dispatch",
        "ultraprocess",
        "handoff",
        "show_coding_handoff_status",
    ),
    CommonRequestCoverageCase(
        "hermes-coding-team",
        "coding_and_delivery",
        "Hermes coding team setup",
        "Hermes 기반 coding team으로 builder reviewer verifier가 나눠서 구현하게 해줘",
        "dispatch",
        "team",
        "plan",
        "present_plan",
    ),
    CommonRequestCoverageCase(
        "web-research",
        "research_and_sources",
        "Source-backed web research",
        "web research with citations about current AI agent market trends",
        "dispatch",
        "web-research",
        "web_research",
        "run_hermes_research",
    ),
    CommonRequestCoverageCase(
        "source-finder",
        "research_and_sources",
        "Source acquisition",
        "find papers datasets github repos and public presentations about agent memory",
        "dispatch",
        "source-finder",
        "source_finder",
        "prepare_source_finder_plan",
    ),
    CommonRequestCoverageCase(
        "paper-learning",
        "research_and_sources",
        "Paper explanation",
        "논문 PDF를 쉬운 수준으로 섹션별로 해설해줘",
        "dispatch",
        "paper-learning",
        "paper_learning",
        "prepare_paper_learning",
    ),
    CommonRequestCoverageCase(
        "research-department",
        "research_and_sources",
        "Research department brief",
        "I need a weekly leadership brief from support tickets, competitor news, and release risks",
        "dispatch",
        "research-department",
        "research_department",
        "prepare_research_department_plan",
    ),
    CommonRequestCoverageCase(
        "strategy-brief",
        "research_and_sources",
        "Research to strategy",
        "조사해서 전략 보고서로 만들어줘",
        "dispatch",
        "strategy-brief",
        "strategy_brief",
        "prepare_strategy_brief",
    ),
    CommonRequestCoverageCase(
        "meeting-brief",
        "research_and_sources",
        "Meeting preparation",
        "prepare meeting agenda decision slots and follow-up template",
        "dispatch",
        "meeting-brief",
        "meeting_brief",
        "prepare_meeting_brief",
    ),
    CommonRequestCoverageCase(
        "report-package",
        "materials_and_frontend",
        "Leadership deck package",
        "create a PPT report package for a monthly leadership status deck",
        "dispatch",
        "report-package",
        "report_package",
        "prepare_report_package",
    ),
    CommonRequestCoverageCase(
        "materials-package",
        "materials_and_frontend",
        "Spreadsheet to PDF package",
        "엑셀 매출 리포트를 PDF로 만들고 렌더 QA까지 준비해줘",
        "dispatch",
        "materials-package",
        "materials_package",
        "prepare_material_package",
    ),
    CommonRequestCoverageCase(
        "deliverable-package",
        "materials_and_frontend",
        "Attachment-ready deliverable",
        "이 보고서를 파일로 만들어서 첨부할 수 있게 준비해줘",
        "dispatch",
        "deliverable-package",
        "deliverable_package",
        "prepare_deliverable_package",
    ),
    CommonRequestCoverageCase(
        "img-summary-poster",
        "materials_and_frontend",
        "Poster image prompt",
        "make a poster explaining cron automation",
        "dispatch",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
    ),
    CommonRequestCoverageCase(
        "design-quality-gate",
        "materials_and_frontend",
        "Design and layout quality gate",
        "웹페이지 디자인 레이아웃 QA 해줘",
        "dispatch",
        "design-quality-gate",
        "design_quality_gate",
        "prepare_design_quality_gate",
    ),
    CommonRequestCoverageCase(
        "frontend-handoff",
        "materials_and_frontend",
        "Frontend implementation handoff",
        "프론트엔드 구현 handoff 준비해줘",
        "dispatch",
        "frontend",
        "frontend_handoff",
        "prepare_frontend_handoff",
    ),
    CommonRequestCoverageCase(
        "visual-qa",
        "materials_and_frontend",
        "Rendered visual QA",
        "visual QA로 화면 깨지는지 봐줘",
        "dispatch",
        "visual-qa",
        "visual_qa",
        "prepare_visual_qa",
    ),
    CommonRequestCoverageCase(
        "accessibility-audit",
        "materials_and_frontend",
        "Accessibility audit",
        "접근성 WCAG 체크해줘",
        "dispatch",
        "accessibility-audit",
        "accessibility_audit",
        "prepare_accessibility_audit",
    ),
    CommonRequestCoverageCase(
        "content-operator",
        "materials_and_frontend",
        "Publish-ready copy",
        "release notes draft with source scope audience tone and review gates",
        "dispatch",
        "content-operator",
        "content_operator",
        "prepare_content_operator_card",
    ),
    CommonRequestCoverageCase(
        "automation-blueprint",
        "ops_and_quality",
        "Scheduled ops automation",
        "매일 아침 릴리즈 위험을 확인하고 변화가 있으면 슬랙에 알려줘",
        "dispatch",
        "automation-blueprint",
        "automation_blueprint",
        "prepare_scheduled_ops_blueprint",
    ),
    CommonRequestCoverageCase(
        "ops-observability",
        "ops_and_quality",
        "Run history observability",
        "show token cost latency run history for this automation loop",
        "dispatch",
        "ops-observability-card",
        "ops_observability",
        "prepare_ops_observability_card",
    ),
    CommonRequestCoverageCase(
        "external-metric-provider",
        "ops_and_quality",
        "External metric-provider board",
        "show metric provider cost latency run history",
        "dispatch",
        "ops-observability-card",
        "ops_observability",
        "prepare_ops_observability_card",
    ),
    CommonRequestCoverageCase(
        "reliability-review",
        "ops_and_quality",
        "Reliability incident review",
        "run an incident postmortem SLO error budget service reliability review",
        "dispatch",
        "reliability-review",
        "reliability_review",
        "prepare_reliability_review",
    ),
    CommonRequestCoverageCase(
        "deploy-and-monitor",
        "ops_and_quality",
        "Deploy and monitor",
        "deploy and monitor this release with rollback and health checks",
        "dispatch",
        "deploy-and-monitor",
        "deploy_monitor_plan",
        "prepare_deploy_monitor_plan",
    ),
    CommonRequestCoverageCase(
        "production-audit",
        "ops_and_quality",
        "Production readiness audit",
        "production readiness audit with rollback health checks",
        "dispatch",
        "production-audit",
        "production_audit",
        "prepare_production_audit",
    ),
    CommonRequestCoverageCase(
        "ops-review",
        "ops_and_quality",
        "Operating review",
        "prepare an ops review with blockers owners and customer signals",
        "dispatch",
        "ops-review",
        "ops_review",
        "prepare_ops_review",
    ),
    CommonRequestCoverageCase(
        "operating-rhythm",
        "ops_and_quality",
        "Operating rhythm",
        "회의록 히스토리 관리하고 스크럼 스프린트 회고 운영 리듬 정리해줘",
        "dispatch",
        "operating-rhythm",
        "operating_rhythm",
        "prepare_operating_record",
    ),
    CommonRequestCoverageCase(
        "performance-goal",
        "ops_and_quality",
        "Performance optimization",
        "performance optimization latency benchmark plan",
        "dispatch",
        "performance-goal",
        "plan",
        "forward_plan_to_selected_workflow",
    ),
    CommonRequestCoverageCase(
        "workspace-audit",
        "ops_and_quality",
        "Workspace surface audit",
        "audit this workspace prompts skills plugins and hooks for stale config",
        "dispatch",
        "workspace-audit",
        "workspace_audit",
        "prepare_workspace_audit",
    ),
    CommonRequestCoverageCase(
        "verification-gate",
        "ops_and_quality",
        "Verification gate",
        "검증 게이트 열고 테스트 CI 증거 확인해줘",
        "dispatch",
        "verification-gate",
        "verification_gate",
        "prepare_verification_gate",
    ),
    CommonRequestCoverageCase(
        "build-failure-triage",
        "ops_and_quality",
        "Build failure triage",
        "CI build failure logs triage root cause and minimal fix handoff",
        "dispatch",
        "build-failure-triage",
        "build_failure_triage",
        "prepare_build_failure_triage",
    ),
    CommonRequestCoverageCase(
        "agent-evaluation",
        "ops_and_quality",
        "Agent evaluation",
        "compare agent outputs with rubric and metrics",
        "dispatch",
        "agent-evaluation",
        "agent_evaluation",
        "prepare_agent_evaluation",
    ),
    CommonRequestCoverageCase(
        "rules-distill",
        "knowledge_and_learning",
        "Rule candidate distillation",
        "이 반복 실수를 AGENTS.md 규칙 후보로 정리해줘",
        "dispatch",
        "rules-distill",
        "rules_distill",
        "prepare_rules_distillation",
    ),
    CommonRequestCoverageCase(
        "codebase-onboarding",
        "knowledge_and_learning",
        "Codebase onboarding",
        "처음 보는 repo 온보딩 reading path 만들어줘",
        "dispatch",
        "codebase-onboarding",
        "codebase_onboarding",
        "prepare_codebase_onboarding",
    ),
    CommonRequestCoverageCase(
        "codegraph-refresh",
        "knowledge_and_learning",
        "Codegraph refresh",
        "codegraph refresh 상태 점검해줘",
        "dispatch",
        "codegraph-refresh",
        "codegraph_refresh",
        "prepare_codegraph_refresh",
    ),
    CommonRequestCoverageCase(
        "memory-curation",
        "knowledge_and_learning",
        "Memory curation review",
        "Hermes가 기억하고 있는 프로젝트 맥락이 오래된 것 같아 정리해줘",
        "dispatch",
        "memory-curation-review",
        "memory_curation",
        "prepare_memory_curation_review",
    ),
    CommonRequestCoverageCase(
        "workflow-learning",
        "knowledge_and_learning",
        "Workflow learning",
        "I want Hermes to learn from this workflow and improve the skill next time",
        "dispatch",
        "workflow-learning",
        "workflow_learning",
        "audit_learning_readiness",
    ),
    CommonRequestCoverageCase(
        "skill-scout",
        "knowledge_and_learning",
        "Skill candidate scout",
        "skill scout existing skill 후보를 찾아서 만들지 설치할지 비교해줘",
        "dispatch",
        "skill-scout",
        "skill_scout",
        "prepare_skill_scout",
    ),
    CommonRequestCoverageCase(
        "skill-health",
        "knowledge_and_learning",
        "Skill health dashboard",
        "skill health dashboard 보여줘",
        "dispatch",
        "skill-health",
        "skill_health",
        "prepare_skill_health",
    ),
    CommonRequestCoverageCase(
        "agent-debug",
        "knowledge_and_learning",
        "Stuck agent debug",
        "agent가 왜 멈췄는지 디버그해줘",
        "dispatch",
        "agent-debug",
        "agent_debug",
        "prepare_agent_debug",
    ),
    CommonRequestCoverageCase(
        "agent-board",
        "knowledge_and_learning",
        "Multi-agent board",
        "우리 팀 Hermes agent 여러 명이 같이 일할 때 역할과 보드를 잡아줘",
        "dispatch",
        "agent-board",
        "agent_board",
        "prepare_agent_board_card",
    ),
    CommonRequestCoverageCase(
        "context-budget",
        "knowledge_and_learning",
        "Context budget review",
        "context budget 압박이 있는지 검토해줘",
        "dispatch",
        "context-budget-review",
        "context_budget_review",
        "prepare_context_budget_review",
    ),
    CommonRequestCoverageCase(
        "security-safety",
        "knowledge_and_learning",
        "Security safety review",
        "security safety review prompt injection secrets destructive action check",
        "dispatch",
        "security-safety-review",
        "security_safety_review",
        "prepare_security_safety_review",
    ),
    CommonRequestCoverageCase(
        "harness-session-inventory",
        "knowledge_and_learning",
        "Harness session inventory",
        "harness session inventory and mcp drift check",
        "dispatch",
        "harness-session-inventory",
        "harness_session_inventory",
        "prepare_harness_session_inventory",
    ),
    CommonRequestCoverageCase(
        "instinct-ledger",
        "knowledge_and_learning",
        "Instinct ledger",
        "project instinct ledger 후보를 검토해줘",
        "dispatch",
        "instinct-ledger",
        "instinct_ledger",
        "prepare_instinct_ledger",
    ),
    CommonRequestCoverageCase(
        "gateway-intent",
        "runtime_tools",
        "Gateway intent card",
        "route Discord Slack Telegram threads with delivery policy",
        "dispatch",
        "gateway-intent-card",
        "gateway_intent",
        "prepare_gateway_intent_card",
    ),
    CommonRequestCoverageCase(
        "voice-operator",
        "runtime_tools",
        "Voice operator",
        "does OMH support voice commands?",
        "dispatch",
        "voice-operator",
        "voice_operator",
        "prepare_voice_operator_card",
    ),
    CommonRequestCoverageCase(
        "browser-operator",
        "runtime_tools",
        "Browser operator",
        "브라우저 열어서 사이트 상태 확인하는 작업 카드 만들어줘",
        "dispatch",
        "browser-operator",
        "browser_operator",
        "prepare_browser_operator_card",
    ),
    CommonRequestCoverageCase(
        "workspace-file-operator",
        "runtime_tools",
        "Workspace file operator",
        "파일 이동/삭제 작업 안전하게 준비해줘",
        "dispatch",
        "workspace-file-operator",
        "workspace_file_operator",
        "prepare_workspace_file_operator_card",
    ),
    CommonRequestCoverageCase(
        "command-operator",
        "runtime_tools",
        "Command operator",
        "터미널 명령 실행 전에 안전 게이트랑 증거 슬롯 만들어줘",
        "dispatch",
        "command-operator",
        "command_operator",
        "prepare_command_operator_card",
    ),
    CommonRequestCoverageCase(
        "connector-operator",
        "runtime_tools",
        "Connector operator",
        "send an email to the customer with confirmation gate before delivery",
        "dispatch",
        "connector-operator",
        "connector_operator",
        "prepare_connector_operator_card",
    ),
    CommonRequestCoverageCase(
        "live-info-operator",
        "runtime_tools",
        "Live information operator",
        "today's Seoul weather with freshness units and provider boundary",
        "dispatch",
        "live-info-operator",
        "live_info_operator",
        "prepare_live_info_operator_card",
    ),
    CommonRequestCoverageCase(
        "data-analysis",
        "runtime_tools",
        "Data analysis",
        "CSV 데이터 분석해서 차트와 결론 만들어줘",
        "dispatch",
        "data-analysis",
        "data_analysis",
        "prepare_data_analysis_card",
    ),
    CommonRequestCoverageCase(
        "toolbelt-readiness",
        "runtime_tools",
        "Toolbelt readiness",
        "can OMH help with MCP setup?",
        "dispatch",
        "toolbelt-readiness",
        "toolbelt_readiness",
        "prepare_toolbelt_readiness",
    ),
    CommonRequestCoverageCase(
        "direct-answer",
        "direct_and_catalog",
        "Plain concept answer",
        "what is Kubernetes?",
        "fallback",
        "oh-my-hermes",
        "clarification",
        "answer_directly",
    ),
    CommonRequestCoverageCase(
        "file-lookup",
        "direct_and_catalog",
        "File lookup stays direct",
        "README 내용 보여줘",
        "fallback",
        "oh-my-hermes",
        "clarification",
        "answer_file_lookup",
    ),
    CommonRequestCoverageCase(
        "catalog-picker",
        "direct_and_catalog",
        "Direct workflow picker",
        "./omh",
        "dispatch",
        "oh-my-hermes",
        "skill_picker",
        "choose_skill",
    ),
    CommonRequestCoverageCase(
        "agent-ops-status",
        "direct_and_catalog",
        "Agent operations status",
        "무슨일이노",
        "dispatch",
        "agent-ops-review",
        "agent_ops_review",
        "refresh_agent_ops_status",
    ),
    CommonRequestCoverageCase(
        "doctor-health",
        "direct_and_catalog",
        "Install/update health",
        "omh update 잘 된거야?",
        "dispatch",
        "doctor",
        "doctor_health",
        "run_local_operator_check",
    ),
)


def build_common_request_coverage_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    rows = [_evaluate_case(case, source=source) for case in COMMON_REQUEST_COVERAGE_CASES]
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    case_count = len(rows)
    coverage_percent = round((passing_count / max(1, case_count)) * 100, 1)
    family_rows = _family_summary(rows)
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
        },
        "check_basis": [
            "Representative ordinary Hermes-agent requests land on the expected OMH workflow or intentional direct fallback.",
            "The wrapper response exposes a next action, claim boundary, and renderable actions for every case.",
            "The target is at least 95% deterministic coverage over this curated local common-request corpus.",
            "Dedicated-card polish, live Hermes rendering, connector execution, and coding-agent work are verified by separate gates.",
        ],
        "families": family_rows,
        "cases": rows,
        "claim_boundary": (
            "Common request coverage proves deterministic local routing breadth over a curated OMH request corpus only. "
            "It is not external plugin telemetry, live Hermes chat rendering, connector execution, source retrieval, "
            "file generation, executor dispatch, implementation, verification, review, CI, merge, delivery, or market-share evidence."
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
            lines.append(f"- {row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'unknown issue'}")
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
