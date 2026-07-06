from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ..catalogs.playbooks import recommend_playbooks
from ..coding_delegation import build_coding_delegation_payload
from ..ingress import CHAT_SOURCES
from ..routing.action_copy import next_action_label
from ..wrapper.contract import build_chat_interaction_payload


GROUNDED_SCORE_SCHEMA_VERSION = "grounded_score_evaluation/v1"


@dataclass(frozen=True)
class GroundedScenario:
    id: str
    title: str
    message: str
    expected_skill: str
    expected_kind: str
    expected_next_action: str
    expected_delegation_action: str
    expect_executor_handoff: bool
    invocation_mode: str = "playbook"
    expected_playbook: str | None = None


# Frozen contract-compliance corpus. These cases are not production routing
# metadata; they are the public examples OMH must continue to satisfy.
GROUNDED_SCENARIOS: tuple[GroundedScenario, ...] = (
    GroundedScenario(
        "startup-product-triage",
        "Startup SaaS product triage",
        "결제 실패 이슈가 자주 나와",
        "feedback-triage",
        "feedback_triage",
        "triage_feedback",
        "clarify",
        False,
        expected_playbook="feedback-triage",
    ),
    GroundedScenario(
        "startup-product-triage-expanded",
        "Startup SaaS product triage with strategy follow-up",
        "결제 실패 피드백을 모아서 회의 주제와 다음 전략을 정리해줘",
        "feedback-triage",
        "feedback_triage",
        "triage_feedback",
        "clarify",
        False,
        expected_playbook="feedback-triage",
    ),
    GroundedScenario(
        "oss-issue-to-pr",
        "Open-source issue-to-PR preparation",
        "이 이슈 PR로 만들 수 있게 정리해줘",
        "github-event-ops",
        "github_event_ops",
        "prepare_github_event_ops_card",
        "delegate",
        True,
        expected_playbook="github-event-ops",
    ),
    GroundedScenario(
        "ai-agent-product-qa",
        "AI agent product QA",
        "쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?",
        "ultraqa",
        "qa_review",
        "dispatch_to_workflow",
        "clarify",
        False,
        expected_playbook="release-readiness-review",
    ),
    GroundedScenario(
        "dangerous-refactor",
        "Dangerous refactor plan-first routing",
        "이거 위험한 리팩터링 같아",
        "ralplan",
        "plan",
        "present_plan",
        "delegate",
        True,
        expected_playbook="safe-feature-change",
    ),
    GroundedScenario(
        "ai-coding-safety-audit",
        "AI coding safety audit",
        "AI가 했다고 했는데 실제로 뭐 했는지 모르겠다",
        "code-review",
        "review_check",
        "prepare_review_or_followup_handoff",
        "delegate",
        True,
        expected_playbook="release-readiness-review",
    ),
    GroundedScenario(
        "product-feature-shaping",
        "Product feature shaping",
        "온보딩을 더 부드럽게 만들고 싶어",
        "deep-interview",
        "clarification",
        "answer_clarification",
        "clarify",
        False,
        expected_playbook="deep-interview-to-plan",
    ),
    GroundedScenario(
        "release-gate-review",
        "Release gate review",
        "릴리즈 전에 README claim이 실제 코드와 맞는가, doctor/harness가 통과하는가 봐줘",
        "code-review",
        "review_check",
        "prepare_review_or_followup_handoff",
        "delegate",
        True,
        expected_playbook="release-readiness-review",
    ),
    GroundedScenario(
        "korean-release-readiness-status",
        "Korean release readiness status",
        "릴리즈 준비 상태 점검해줘",
        "code-review",
        "review_check",
        "prepare_review_or_followup_handoff",
        "clarify",
        False,
        expected_playbook="release-readiness-review",
    ),
    GroundedScenario(
        "repeated-refactor-workflow",
        "Repeated refactor workflow",
        "레거시 서비스를 위험 분석, 변경 범위 제한, 테스트 전략, Codex 구현, 리뷰, 회귀 테스트 순서로 리팩터링하고 싶어",
        "ai-slop-cleaner",
        "plan",
        "present_plan",
        "delegate",
        True,
        expected_playbook="safe-feature-change",
    ),
    GroundedScenario(
        "personal-multi-agent-hub",
        "Personal multi-agent work hub",
        "지금은 Hermes가 답할 차례인지, coding handoff를 준비할 차례인지, review gate를 열 차례인지 정리해줘",
        "plan",
        "plan",
        "present_plan",
        "delegate",
        True,
        expected_playbook="local-pipeline-buildout",
    ),
    GroundedScenario(
        "agency-template",
        "Consulting or agency operating template",
        "고객사 프로젝트별 요구사항 정리, 조사, 구현 handoff, QA, 리뷰, 릴리즈 보고 운영 템플릿이 필요해",
        "plan",
        "plan",
        "present_plan",
        "delegate",
        True,
        expected_playbook="local-pipeline-buildout",
    ),
    GroundedScenario(
        "operating-rhythm-history",
        "Operating rhythm history",
        "회의록 히스토리 관리하고 스크럼 스프린트 회고 운영 리듬 정리해줘",
        "operating-rhythm",
        "operating_rhythm",
        "prepare_operating_record",
        "clarify",
        False,
        expected_playbook="operating-rhythm-history",
    ),
    GroundedScenario(
        "leadership-report-package",
        "Leadership report package",
        "create a PPT report package for a monthly leadership status deck",
        "report-package",
        "report_package",
        "prepare_report_package",
        "clarify",
        False,
        expected_playbook="report-package",
    ),
    GroundedScenario(
        "materials-processing-package",
        "Materials processing package",
        "엑셀 매출 리포트를 PDF로 만들고 렌더 QA까지 준비해줘",
        "materials-package",
        "materials_package",
        "prepare_material_package",
        "clarify",
        False,
        expected_playbook="materials-processing",
    ),
    GroundedScenario(
        "korean-meeting-to-slides",
        "Korean meeting notes to presentation material",
        "이 회의록을 발표자료로 만들어줘",
        "materials-package",
        "materials_package",
        "prepare_material_package",
        "clarify",
        False,
        expected_playbook="materials-processing",
    ),
    GroundedScenario(
        "reliability-incident-review",
        "Reliability incident review",
        "run an incident postmortem SLO error budget service reliability review",
        "reliability-review",
        "reliability_review",
        "prepare_reliability_review",
        "clarify",
        False,
        expected_playbook="reliability-incident-review",
    ),
    GroundedScenario(
        "idea-to-deploy-loop",
        "Idea-to-deploy product loop",
        "take this product idea from plan to deploy and monitor safely",
        "idea-to-deploy",
        "app_delivery_loop",
        "present_app_delivery_loop",
        "clarify",
        False,
        expected_playbook="idea-to-deploy",
    ),
    GroundedScenario(
        "cto-loop",
        "CTO loop",
        "run a CTO loop for roadmap architecture tradeoffs delivery risk and release readiness",
        "cto-loop",
        "cto_loop",
        "run_cto_loop",
        "clarify",
        False,
        expected_playbook="cto-loop",
    ),
    GroundedScenario(
        "deploy-and-monitor",
        "Deploy and monitor",
        "deploy and monitor this release with rollback and health checks",
        "deploy-and-monitor",
        "deploy_monitor_plan",
        "prepare_deploy_monitor_plan",
        "clarify",
        False,
        expected_playbook="deploy-and-monitor",
    ),
    GroundedScenario(
        "english-product-shaping",
        "English product shaping",
        "I need to improve our onboarding but I don't know where to start",
        "deep-interview",
        "clarification",
        "answer_clarification",
        "clarify",
        False,
        expected_playbook="deep-interview-to-plan",
    ),
    GroundedScenario(
        "workflow-learning-improvement",
        "Workflow learning improvement",
        "I want Hermes to learn from this workflow and improve the skill next time",
        "workflow-learning",
        "workflow_learning",
        "audit_learning_readiness",
        "clarify",
        False,
        expected_playbook="workflow-learning",
    ),
    GroundedScenario(
        "korean-workflow-learning-improvement",
        "Korean workflow learning improvement",
        "이 워크플로우 다음엔 더 잘하게 개선해줘",
        "workflow-learning",
        "workflow_learning",
        "audit_learning_readiness",
        "clarify",
        False,
        expected_playbook="workflow-learning",
    ),
    GroundedScenario(
        "korean-task-learning-memory",
        "Korean task improvement memory",
        "다음부터 이 작업 더 잘하게 기억해줘",
        "workflow-learning",
        "workflow_learning",
        "audit_learning_readiness",
        "clarify",
        False,
        expected_playbook="workflow-learning",
    ),
    GroundedScenario(
        "korean-answer-skill-improve",
        "Korean answer-to-skill improvement",
        "이 답변 다음엔 더 잘하게 스킬 고쳐줘",
        "workflow-learning",
        "workflow_learning",
        "audit_learning_readiness",
        "clarify",
        False,
        expected_playbook="workflow-learning",
    ),
    GroundedScenario(
        "visual-summary-poster",
        "Visual summary poster",
        "make a poster explaining cron automation",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
        "clarify",
        False,
        expected_playbook="img-summary",
    ),
    GroundedScenario(
        "korean-meeting-image-summary",
        "Korean meeting image summary",
        "회의록을 보기 좋은 세로 이미지로 요약해줘",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
        "clarify",
        False,
        expected_playbook="img-summary",
    ),
    GroundedScenario(
        "korean-release-note-image-summary",
        "Korean release-note image summary",
        "릴리즈 노트 이미지로 만들어줘",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
        "clarify",
        False,
        expected_playbook="img-summary",
    ),
    GroundedScenario(
        "korean-omh-loop-feature-image-summary",
        "Korean OMH loop feature image summary",
        "OMH 루프 기능 소개 이미지 만들어줘",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
        "clarify",
        False,
        expected_playbook="img-summary",
    ),
    GroundedScenario(
        "korean-image-generator-connector-readiness",
        "Korean image-generator connector readiness",
        "이미지 생성 연결체가 없으면 어떤걸로 연결할지 물어봐줘",
        "toolbelt-readiness",
        "toolbelt_readiness",
        "prepare_toolbelt_readiness",
        "clarify",
        False,
        expected_playbook="toolbelt-readiness",
    ),
    GroundedScenario(
        "korean-release-update-announcement-card",
        "Korean release update announcement card",
        "릴리즈 업데이트를 발표 카드로 만들어줘",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
        "clarify",
        False,
        expected_playbook="img-summary",
    ),
    GroundedScenario(
        "korean-instagram-card-news-summary",
        "Korean Instagram card-news summary",
        "요약을 인스타 카드뉴스처럼 만들어줘",
        "img-summary",
        "img_summary",
        "prepare_visual_prompt_card",
        "clarify",
        False,
        expected_playbook="img-summary",
    ),
    GroundedScenario(
        "research-department-ops",
        "Research department ops",
        "I need a weekly leadership brief from support tickets, competitor news, and release risks",
        "research-department",
        "research_department",
        "prepare_research_department_plan",
        "clarify",
        False,
        expected_playbook="weekly-ops-review",
    ),
    GroundedScenario(
        "korean-research-to-strategy-report",
        "Korean research to strategy report",
        "조사해서 전략 보고서로 만들어줘",
        "strategy-brief",
        "strategy_brief",
        "prepare_strategy_brief",
        "clarify",
        False,
        expected_playbook="research-to-strategy-brief",
    ),
    GroundedScenario(
        "github-event-ops-delivery",
        "GitHub event ops delivery",
        "Make this GitHub issue into a PR, run review, update docs, and tell me what changed",
        "github-event-ops",
        "github_event_ops",
        "prepare_github_event_ops_card",
        "clarify",
        False,
        expected_playbook="github-event-ops",
    ),
    GroundedScenario(
        "korean-github-issue-label-pr",
        "Korean GitHub issue labeling and PR prep",
        "새 이슈 들어오면 라벨링하고 PR 준비해줘",
        "github-event-ops",
        "github_event_ops",
        "prepare_github_event_ops_card",
        "clarify",
        False,
        expected_playbook="github-event-ops",
    ),
    GroundedScenario(
        "executor-runtime-selection",
        "Executor runtime selection",
        "Should I use Codex or Claude Code for this coding task?",
        "executor-runtime-readiness",
        "executor_runtime_readiness",
        "prepare_executor_runtime_readiness",
        "clarify",
        False,
        expected_playbook="executor-runtime-readiness",
    ),
    GroundedScenario(
        "korean-codex-open-session",
        "Korean Codex open session",
        "codex 세션 켜서 작업 시작하게 해줘",
        "executor-runtime-readiness",
        "executor_runtime_readiness",
        "prepare_executor_runtime_readiness",
        "clarify",
        False,
        expected_playbook="executor-runtime-readiness",
    ),
    GroundedScenario(
        "korean-claude-open-direct",
        "Korean Claude Code open direct",
        "Claude Code로 바로 열어줘",
        "executor-runtime-readiness",
        "executor_runtime_readiness",
        "prepare_executor_runtime_readiness",
        "delegate",
        True,
        expected_playbook="executor-runtime-readiness",
    ),
    GroundedScenario(
        "korean-hermes-coding-owner",
        "Korean Hermes coding owner",
        "Hermes가 직접 코딩하게 해줘",
        "executor-runtime-readiness",
        "executor_runtime_readiness",
        "prepare_executor_runtime_readiness",
        "clarify",
        False,
        expected_playbook="executor-runtime-readiness",
    ),
    GroundedScenario(
        "coding-agent-progress-status",
        "Coding-agent progress status",
        "Codex 작업이 진행중인지 확인하고 지금 어떤 상태인지 알려줘",
        "ultraprocess",
        "handoff",
        "show_coding_handoff_status",
        "clarify",
        False,
        expected_playbook="ultraprocess",
    ),
    GroundedScenario(
        "korean-pr-merge-readiness-status",
        "Korean PR merge readiness status",
        "지금 PR 머지 준비 됐는지 알려줘",
        "ultraprocess",
        "handoff",
        "show_coding_handoff_status",
        "clarify",
        False,
        expected_playbook="ultraprocess",
    ),
    GroundedScenario(
        "korean-codex-progress-status",
        "Korean Codex progress status",
        "코덱스가 지금 어디까지 했는지 알려줘",
        "ultraprocess",
        "handoff",
        "show_coding_handoff_status",
        "clarify",
        False,
        expected_playbook="ultraprocess",
    ),
    GroundedScenario(
        "korean-codex-current-activity-status",
        "Korean Codex current-activity status",
        "코덱스가 지금 뭐하고있는지 알려줘",
        "ultraprocess",
        "handoff",
        "show_coding_handoff_status",
        "clarify",
        False,
        expected_playbook="ultraprocess",
    ),
    GroundedScenario(
        "korean-claude-code-open-session",
        "Korean Claude Code open session",
        "claude code 작업 세션 열어줘",
        "executor-runtime-readiness",
        "executor_runtime_readiness",
        "prepare_executor_runtime_readiness",
        "delegate",
        True,
        expected_playbook="executor-runtime-readiness",
    ),
    GroundedScenario(
        "korean-hermes-memory-review",
        "Korean Hermes memory review",
        "Hermes가 기억하는 내용 한번 점검하자",
        "memory-curation-review",
        "memory_curation",
        "prepare_memory_curation_review",
        "clarify",
        False,
        expected_playbook="memory-curation-review",
    ),
    GroundedScenario(
        "korean-user-qa-scenario",
        "Korean user-like QA scenario",
        "실제 사용자처럼 QA 시나리오 돌려줘",
        "ultraqa",
        "qa_review",
        "dispatch_to_workflow",
        "clarify",
        False,
        expected_playbook="release-readiness-review",
    ),
    GroundedScenario(
        "korean-loop-cost-latency",
        "Korean loop cost and latency status",
        "루프 비용이랑 지연시간 상태 보여줘",
        "ops-observability-card",
        "ops_observability",
        "prepare_ops_observability_card",
        "clarify",
        False,
        expected_playbook="ops-observability-card",
    ),
    GroundedScenario(
        "direct-goal-loop",
        "Loopability-gated goal cycle",
        "./loop make this project a 10k star OSS",
        "loop",
        "loop",
        "start_loop_cycle",
        "clarify",
        False,
        invocation_mode="direct_skill",
    ),
    GroundedScenario(
        "direct-ultraprocess-cycle",
        "Direct one-cycle ultraprocess",
        "$ultraprocess research the repo, plan, implement, code-review, sync docs, and prepare a PR",
        "ultraprocess",
        "handoff",
        "choose_executor",
        "clarify",
        False,
        invocation_mode="direct_skill",
    ),
)


def build_grounded_score_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    results = [_evaluate_grounded_scenario(scenario, source=source) for scenario in GROUNDED_SCENARIOS]
    scores = [int(result["score"]) for result in results]
    return {
        "schema_version": GROUNDED_SCORE_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "scenario_count": len(results),
            "score_scale": "0_to_10",
            "minimum_score": min(scores) if scores else 0,
            "maximum_score": max(scores) if scores else 0,
            "average_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "all_10": bool(scores) and all(score == 10 for score in scores),
        },
        "score_basis": [
            "Chat route selected the expected skill, response kind, and next action.",
            "Playbook recommendation is checked only for scenarios with a situation-level playbook.",
            "Direct skill invocations are checked as explicit skill routes without forcing a playbook.",
            "Coding delegation boundary keeps retained Hermes work handoff-free and code-shaped work prepared_not_observed.",
            "No scenario score treats dispatch, execution, verification, review, CI, or merge as observed.",
        ],
        "scenarios": results,
        "claim_boundary": (
            "This is deterministic local contract-compliance evaluation, not live Hermes chat, "
            "executor execution, review, CI, or merge evidence."
        ),
    }


def format_grounded_score_summary(payload: dict[str, object]) -> str:
    summary = _nested(payload, "summary")
    scenario_rows = _dict_rows(payload.get("scenarios", []))
    total = int(summary.get("scenario_count", len(scenario_rows)) or 0)
    perfect = sum(1 for scenario in scenario_rows if int(_value(scenario, "score", 0)) == 10)
    average = summary.get("average_score", 0)
    minimum = summary.get("minimum_score", 0)
    maximum = summary.get("maximum_score", 0)
    all_10 = bool(summary.get("all_10", False))
    lines = [
        "OMH grounded score",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {perfect}/{total} scenarios at 10/10" + (" (all passing)" if all_10 else ""),
        f"Score range: min {minimum}, avg {average}, max {maximum}",
        "",
        "What this proves:",
    ]
    for basis in payload.get("score_basis", []):
        lines.append(f"- {basis}")
    lines.extend(["", "Scenario rollup:"])
    for scenario in scenario_rows:
        observed = _nested(scenario, "observed")
        skill = observed.get("skill", "unknown")
        next_action = next_action_label(str(observed.get("next_action", "unknown")))
        handoff = observed.get("handoff_status", "unknown")
        score = scenario.get("score", 0)
        status = "ok" if int(score) == 10 else "needs attention"
        lines.append(f"- {scenario.get('title', 'Untitled scenario')}: {score}/10 {status}; {skill} -> {next_action}; {handoff}")
    failed = [scenario for scenario in scenario_rows if int(_value(scenario, "score", 0)) != 10]
    if failed:
        lines.extend(["", "Failures:"])
        for scenario in failed:
            failed_checks = [
                str(check.get("name", "unknown"))
                for check in scenario.get("checks", [])
                if isinstance(check, dict) and not check.get("passed", False)
            ]
            lines.append(f"- {scenario.get('id', 'unknown')}: {', '.join(failed_checks) or 'unknown check failure'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def _evaluate_grounded_scenario(scenario: GroundedScenario, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(scenario.message, source=source)
    route = _nested(interaction, "route")
    delegation = build_coding_delegation_payload(
        scenario.message,
        source=source,
        executor_target="codex",
        prefer_direct_coding_handoff=False,
    )
    response = _nested(interaction, "chat_response")
    delegation_body = _nested(delegation, "delegation")
    checks = [
        _check(
            "chat_skill",
            route.get("selected_skill") == scenario.expected_skill,
            2,
            route.get("selected_skill"),
        ),
        _check(
            "chat_response_kind",
            response.get("kind") == scenario.expected_kind,
            1,
            response.get("kind"),
        ),
        _check(
            "chat_next_action",
            interaction.get("next_action") == scenario.expected_next_action,
            1,
            interaction.get("next_action"),
        ),
        _check(
            "delegation_action",
            delegation_body.get("action") == scenario.expected_delegation_action,
            1,
            delegation_body.get("action"),
        ),
        _check(
            "executor_handoff_boundary",
            ("executor_handoff" in delegation) is scenario.expect_executor_handoff,
            2,
            "present" if "executor_handoff" in delegation else "absent",
        ),
        _check(
            "prepared_not_observed_boundary",
            _prepared_boundary_ok(delegation, expect_executor_handoff=scenario.expect_executor_handoff),
            1,
            _boundary_observation(delegation),
        ),
    ]
    observed_playbook = None
    if scenario.invocation_mode == "playbook":
        playbook = recommend_playbooks(scenario.message, limit=1)["recommendations"][0]
        checks.extend(
            [
                _check("playbook", playbook.get("id") == scenario.expected_playbook, 1, playbook.get("id")),
                _check("playbook_confidence", playbook.get("confidence") == "high", 1, playbook.get("confidence")),
            ]
        )
        observed_playbook = {
            "id": playbook.get("id"),
            "confidence": playbook.get("confidence"),
            "score": playbook.get("score"),
            "next_action": playbook.get("next_action"),
        }
    else:
        checks.append(_check("direct_skill_invocation", bool(route.get("explicit")), 2, route.get("explicit")))
    score = sum(int(check["weight"]) for check in checks if check["passed"])
    return {
        "id": scenario.id,
        "title": scenario.title,
        "message_sha256": hashlib.sha256(scenario.message.encode("utf-8")).hexdigest(),
        "score": score,
        "passed": score == 10,
        "expected": {
            "skill": scenario.expected_skill,
            "kind": scenario.expected_kind,
            "next_action": scenario.expected_next_action,
            "playbook": scenario.expected_playbook,
            "delegation_action": scenario.expected_delegation_action,
            "executor_handoff": scenario.expect_executor_handoff,
            "invocation_mode": scenario.invocation_mode,
        },
        "observed": {
            "skill": route.get("selected_skill"),
            "route_action": route.get("action"),
            "route_score": route.get("score"),
            "kind": response.get("kind"),
            "next_action": interaction.get("next_action"),
            "claim_boundary": response.get("claim_boundary"),
            "playbook": observed_playbook,
            "delegation_action": delegation_body.get("action"),
            "delegation_workflow": delegation_body.get("recommended_workflow"),
            "executor_handoff": "present" if "executor_handoff" in delegation else "absent",
            "handoff_status": _boundary_observation(delegation),
        },
        "checks": checks,
    }


def _check(name: str, passed: bool, weight: int, observed: object) -> dict[str, object]:
    return {
        "name": name,
        "passed": bool(passed),
        "weight": weight,
        "observed": observed,
    }


def _prepared_boundary_ok(delegation: dict[str, object], *, expect_executor_handoff: bool) -> bool:
    if not expect_executor_handoff:
        return "executor_handoff" not in delegation
    handoff = delegation.get("executor_handoff")
    return isinstance(handoff, dict) and handoff.get("status") == "prepared_not_observed"


def _boundary_observation(delegation: dict[str, object]) -> str:
    handoff = delegation.get("executor_handoff")
    if isinstance(handoff, dict):
        return str(handoff.get("status", "unknown"))
    return "handoff_absent"


def _nested(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _value(payload: object, key: str, default: object = "") -> object:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return default
