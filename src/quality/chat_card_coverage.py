from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ..ingress import CHAT_SOURCES
from ..wrapper.contract import build_chat_interaction_payload


CHAT_CARD_COVERAGE_SCHEMA_VERSION = "chat_card_coverage/v1"


@dataclass(frozen=True)
class ChatCardCoverageCase:
    id: str
    title: str
    message: str
    expected_skill: str
    expected_kind: str
    expected_next_action: str


# Frozen wrapper-card corpus. These are user-facing routes where a generic
# acknowledgement would make Hermes feel less capable and less explainable.
CHAT_CARD_COVERAGE_CASES: tuple[ChatCardCoverageCase, ...] = (
    ChatCardCoverageCase(
        "automation-blueprint",
        "Scheduled ops blueprint",
        "매일 아침 릴리즈 위험을 확인하고 변화가 있으면 슬랙에 알려줘",
        "automation-blueprint",
        "automation_blueprint",
        "prepare_scheduled_ops_blueprint",
    ),
    ChatCardCoverageCase(
        "agent-board",
        "Multi-agent board",
        "우리 팀 Hermes agent 여러 명이 같이 일할 때 역할과 보드를 잡아줘",
        "agent-board",
        "agent_board",
        "prepare_agent_board_card",
    ),
    ChatCardCoverageCase(
        "memory-curation-review",
        "Memory curation review",
        "Hermes가 기억하고 있는 프로젝트 맥락이 오래된 것 같아 정리해줘",
        "memory-curation-review",
        "memory_curation",
        "prepare_memory_curation_review",
    ),
    ChatCardCoverageCase(
        "gateway-intent-card",
        "Gateway intent card",
        "route Discord Slack Telegram threads with delivery policy",
        "gateway-intent-card",
        "gateway_intent",
        "prepare_gateway_intent_card",
    ),
    ChatCardCoverageCase(
        "deliverable-package",
        "Deliverable package",
        "이 보고서를 파일로 만들어서 첨부할 수 있게 준비해줘",
        "deliverable-package",
        "deliverable_package",
        "prepare_deliverable_package",
    ),
    ChatCardCoverageCase(
        "voice-operator",
        "Voice operator guidance",
        "does OMH support voice commands?",
        "voice-operator",
        "voice_operator",
        "prepare_voice_operator_card",
    ),
    ChatCardCoverageCase(
        "toolbelt-readiness",
        "Toolbelt readiness",
        "can OMH help with MCP setup?",
        "toolbelt-readiness",
        "toolbelt_readiness",
        "prepare_toolbelt_readiness",
    ),
    ChatCardCoverageCase(
        "ops-observability-card",
        "Ops observability card",
        "show token cost latency run history for this automation loop",
        "ops-observability-card",
        "ops_observability",
        "prepare_ops_observability_card",
    ),
    ChatCardCoverageCase(
        "operating-rhythm",
        "Operating rhythm",
        "회의록 히스토리 관리하고 스크럼 스프린트 회고 운영 리듬 정리해줘",
        "operating-rhythm",
        "operating_rhythm",
        "prepare_operating_record",
    ),
    ChatCardCoverageCase(
        "report-package",
        "Report package",
        "create a PPT report package for a monthly leadership status deck",
        "report-package",
        "report_package",
        "prepare_report_package",
    ),
    ChatCardCoverageCase(
        "materials-package",
        "Materials package",
        "엑셀 매출 리포트를 PDF로 만들고 렌더 QA까지 준비해줘",
        "materials-package",
        "materials_package",
        "prepare_material_package",
    ),
    ChatCardCoverageCase(
        "reliability-review",
        "Reliability review",
        "run an incident postmortem SLO error budget service reliability review",
        "reliability-review",
        "reliability_review",
        "prepare_reliability_review",
    ),
    ChatCardCoverageCase(
        "idea-to-deploy",
        "Idea to deploy",
        "take this product idea from plan to deploy and monitor safely",
        "idea-to-deploy",
        "app_delivery_loop",
        "present_app_delivery_loop",
    ),
    ChatCardCoverageCase(
        "cto-loop",
        "CTO loop",
        "run a CTO loop for roadmap architecture tradeoffs delivery risk and release readiness",
        "cto-loop",
        "cto_loop",
        "run_cto_loop",
    ),
    ChatCardCoverageCase(
        "deploy-and-monitor",
        "Deploy and monitor",
        "deploy and monitor this release with rollback and health checks",
        "deploy-and-monitor",
        "deploy_monitor_plan",
        "prepare_deploy_monitor_plan",
    ),
    ChatCardCoverageCase(
        "research-department",
        "Research department",
        "I need a weekly leadership brief from support tickets, competitor news, and release risks",
        "research-department",
        "research_department",
        "prepare_research_department_plan",
    ),
    ChatCardCoverageCase(
        "github-event-ops",
        "GitHub event ops",
        "Make this GitHub issue into a PR, run review, update docs, and tell me what changed",
        "github-event-ops",
        "github_event_ops",
        "prepare_github_event_ops_card",
    ),
    ChatCardCoverageCase(
        "executor-runtime-readiness",
        "Executor runtime readiness",
        "Should I use Codex or Claude Code for this coding task?",
        "executor-runtime-readiness",
        "executor_runtime_readiness",
        "prepare_executor_runtime_readiness",
    ),
    ChatCardCoverageCase(
        "feedback-triage",
        "Feedback triage",
        "결제 실패 이슈가 자주 나와",
        "feedback-triage",
        "feedback_triage",
        "triage_feedback",
    ),
    ChatCardCoverageCase(
        "img-summary",
        "Image summary",
        "make a poster explaining cron automation",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
    ),
    ChatCardCoverageCase(
        "paper-learning",
        "Paper learning",
        "논문 PDF를 쉬운 수준으로 섹션별로 해설해줘",
        "paper-learning",
        "paper_learning",
        "prepare_paper_learning",
    ),
    ChatCardCoverageCase(
        "source-finder",
        "Source finder",
        "find papers datasets github repos and public presentations about agent memory",
        "source-finder",
        "source_finder",
        "prepare_source_finder_plan",
    ),
    ChatCardCoverageCase(
        "web-research",
        "Web research",
        "web research with citations about current AI agent market trends",
        "web-research",
        "web_research",
        "run_hermes_research",
    ),
    ChatCardCoverageCase(
        "workflow-learning",
        "Workflow learning",
        "I want Hermes to learn from this workflow and improve the skill next time",
        "workflow-learning",
        "workflow_learning",
        "audit_learning_readiness",
    ),
    ChatCardCoverageCase(
        "agent-ops-review",
        "Agent ops review",
        "AI agent 서치및 코딩 품질을 제3자 관리자 입장에서 점검해줘",
        "agent-ops-review",
        "agent_ops_review",
        "show_agent_ops_review",
    ),
)


def build_chat_card_coverage_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    rows = [_evaluate_chat_card_case(case, source=source) for case in CHAT_CARD_COVERAGE_CASES]
    dedicated_count = sum(1 for row in rows if bool(row["dedicated_card"]))
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    generic_ack_count = sum(1 for row in rows if row["observed"]["kind"] == "ack")
    return {
        "schema_version": CHAT_CARD_COVERAGE_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": len(rows),
            "passing_count": passing_count,
            "dedicated_card_count": dedicated_count,
            "generic_ack_count": generic_ack_count,
            "all_passing": bool(rows) and passing_count == len(rows),
        },
        "check_basis": [
            "The selected workflow matches the expected user-facing route.",
            "The chat response uses a dedicated card kind instead of generic ack.",
            "The wrapper next action matches the expected workflow action.",
            "The response includes renderable actions, claim boundary copy, and not-observed evidence.",
            "This gate checks wrapper-card coverage only; it does not prove live Hermes rendering or execution.",
        ],
        "cases": rows,
        "claim_boundary": (
            "This is deterministic local wrapper-card coverage, not live Hermes chat, "
            "executor execution, review, CI, merge, platform delivery, or plugin-load evidence."
        ),
    }


def format_chat_card_coverage_summary(payload: dict[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _dict_rows(payload.get("cases", []))
    total = int(summary.get("case_count", len(rows)) or 0)
    passing = int(summary.get("passing_count", 0) or 0)
    generic_ack_count = int(summary.get("generic_ack_count", 0) or 0)
    all_passing = bool(summary.get("all_passing", False))
    lines = [
        "OMH chat card coverage",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {passing}/{total} workflow cards dedicated" + (" (all passing)" if all_passing else ""),
        f"Generic ack responses: {generic_ack_count}",
        "",
        "What this proves:",
    ]
    for basis in payload.get("check_basis", []):
        lines.append(f"- {basis}")
    lines.extend(["", "Card rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("passed") else "needs attention"
        lines.append(
            f"- {row.get('title', 'Untitled card')}: {status}; "
            f"{observed.get('workflow', 'unknown')} -> {observed.get('kind', 'unknown')} -> {observed.get('next_action', 'unknown')}"
        )
    failed = [row for row in rows if not row.get("passed")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('id', 'unknown')}: {', '.join(row.get('issues', [])) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def _evaluate_chat_card_case(case: ChatCardCoverageCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(case.message, source=source)
    route = _nested(interaction, "route")
    response = _nested(interaction, "chat_response")
    state = _nested(response, "state")
    actions = _dict_rows(response.get("actions", []))
    observed = {
        "workflow": route.get("selected_skill"),
        "kind": response.get("kind"),
        "next_action": interaction.get("next_action"),
        "route_action": route.get("action"),
        "confidence": route.get("confidence"),
        "claim_boundary": response.get("claim_boundary"),
        "action_count": len(actions),
        "primary_action_count": sum(1 for action in actions if action.get("style") == "primary"),
        "evidence_not_observed_count": len(_list_rows(state.get("evidence_not_observed", []))),
    }
    issues: list[str] = []
    if observed["workflow"] != case.expected_skill:
        issues.append(f"expected workflow {case.expected_skill}, observed {observed['workflow']}")
    if observed["kind"] != case.expected_kind:
        issues.append(f"expected kind {case.expected_kind}, observed {observed['kind']}")
    if observed["kind"] == "ack":
        issues.append("generic ack response")
    if observed["next_action"] != case.expected_next_action:
        issues.append(f"expected next action {case.expected_next_action}, observed {observed['next_action']}")
    if not str(observed["claim_boundary"] or "").strip():
        issues.append("missing claim boundary")
    if not actions:
        issues.append("missing renderable actions")
    if not any(action.get("style") == "primary" for action in actions):
        issues.append("missing primary action")
    if observed["evidence_not_observed_count"] < 1:
        issues.append("missing not-observed evidence")
    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "dedicated_card": observed["kind"] != "ack",
        "passed": not issues,
        "expected": {
            "workflow": case.expected_skill,
            "kind": case.expected_kind,
            "next_action": case.expected_next_action,
        },
        "observed": observed,
        "issues": issues,
    }


def _nested(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_rows(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return value
