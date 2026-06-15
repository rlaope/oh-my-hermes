from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .catalogs.playbooks import recommend_playbooks
from .coding_delegation import build_coding_delegation_payload
from .ingress import CHAT_SOURCES
from .routing.chat import route_chat_message
from .wrapper.contract import build_chat_interaction_payload


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
        "ack",
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
        "ack",
        "triage_feedback",
        "clarify",
        False,
        expected_playbook="feedback-triage",
    ),
    GroundedScenario(
        "oss-issue-to-pr",
        "Open-source issue-to-PR preparation",
        "이 이슈 PR로 만들 수 있게 정리해줘",
        "ralplan",
        "plan",
        "present_plan",
        "delegate",
        True,
        expected_playbook="safe-feature-change",
    ),
    GroundedScenario(
        "ai-agent-product-qa",
        "AI agent product QA",
        "쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?",
        "ultraqa",
        "ack",
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
        "ack",
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
        "ack",
        "prepare_review_or_followup_handoff",
        "delegate",
        True,
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
        "ack",
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
        "ack",
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
        "ack",
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
        "ack",
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
        "ack",
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
        "ack",
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
        "ack",
        "prepare_deploy_monitor_plan",
        "clarify",
        False,
        expected_playbook="deploy-and-monitor",
    ),
    GroundedScenario(
        "direct-goal-loop",
        "Loopability-gated goal cycle",
        "./loop make this project a 10k star OSS",
        "loop",
        "loop",
        "reframe_north_star",
        "clarify",
        False,
        invocation_mode="direct_skill",
    ),
    GroundedScenario(
        "direct-ultraprocess-cycle",
        "Direct one-cycle ultraprocess",
        "$ultraprocess research the repo, plan, implement, code-review, sync docs, and prepare a PR",
        "ultraprocess",
        "process",
        "start_ultraprocess",
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


def _evaluate_grounded_scenario(scenario: GroundedScenario, *, source: str) -> dict[str, object]:
    route = route_chat_message(scenario.message, source=source)
    interaction = build_chat_interaction_payload(scenario.message, source=source)
    delegation = build_coding_delegation_payload(scenario.message, source=source, executor_target="codex")
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
