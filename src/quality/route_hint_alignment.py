from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

from ..ingress import CHAT_SOURCES
from ..plugin_bundle.omh.awareness import awareness_route_hint
from ..routing.action_copy import next_action_label
from ..wrapper.contract import build_chat_interaction_payload
from .chat_card_coverage import CHAT_CARD_COVERAGE_CASES
from .grounded_score import GROUNDED_SCENARIOS


ROUTE_HINT_ALIGNMENT_SCHEMA_VERSION = "route_hint_alignment/v1"


@dataclass(frozen=True)
class RouteHintAlignmentCase:
    corpus: str
    id: str
    title: str
    message: str
    expected_workflow: str
    expected_next_action: str


_OPERATOR_ROUTE_HINT_ALIGNMENT_CASES = (
    RouteHintAlignmentCase(
        "operator_regression",
        "claude-code-session-status",
        "Claude Code session status",
        "Claude Code session status 알려줘",
        "ultraprocess",
        "show_coding_handoff_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "setup-health-check",
        "Setup health check",
        "setup이 잘 됐는지 확인해줘",
        "doctor",
        "run_local_operator_check",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "dangerous-refactor-before-release",
        "Dangerous refactor before release",
        "dangerous refactor before release",
        "ralplan",
        "present_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "dataset-github-source-finder",
        "Dataset and GitHub source finding",
        "find datasets and github repos for agent memory",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "omh-update-health-korean",
        "Korean OMH update health question",
        "omh update 잘 된 거야?",
        "doctor",
        "run_local_operator_check",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "omh-visibility-health-korean",
        "Korean OMH visibility health question",
        "hermes에서 omh가 안 보여",
        "doctor",
        "run_local_operator_check",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "codex-session-running-korean",
        "Korean Codex session running status",
        "codex 세션 지금 실행 중이야?",
        "ultraprocess",
        "show_coding_handoff_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "codex-attach-status-korean",
        "Korean Codex attached-session status",
        "코덱스 세션 붙여서 상태 보여줘",
        "ultraprocess",
        "show_coding_handoff_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "coding-agent-dispatched-status",
        "Coding agent dispatched status follow-up",
        "the coding agent was dispatched, what happened next?",
        "ultraprocess",
        "show_coding_handoff_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "codex-issue-pr-tracking-korean",
        "Korean Codex issue-to-PR tracking handoff",
        "이 이슈를 Codex로 구현하게 맡기고 진행상태 추적해줘",
        "ultraprocess",
        "show_coding_handoff_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "codex-issue-pr-start-korean",
        "Korean Codex issue-to-PR start handoff",
        "코덱스로 이 이슈 PR 만들 수 있게 작업 시작해줘",
        "ultraprocess",
        "show_coding_handoff_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "codex-start-this-task-korean",
        "Korean Codex start current task",
        "코덱스로 이 작업 시작해줘",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "open-in-codex-button-korean",
        "Open in Codex button request",
        "Open in Codex 버튼 어디 있어?",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "attach-claude-session-korean",
        "Attach existing Claude Code session",
        "Attach existing Claude Code session 해줘",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "public-slide-github-source-finder",
        "Public slide deck and GitHub source finder",
        "public slide deck and github repo 찾아줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-source-dataset-github",
        "Korean source finder with dataset and GitHub",
        "자료 출처 찾아줘 데이터셋이랑 깃허브까지",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-arxiv-link-source-finder",
        "Korean arxiv link source finder",
        "arxiv 링크 찾아서 쉽게 설명해줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-paper-pdf-source-finder",
        "Korean paper PDF acquisition source finder",
        "논문 pdf 찾아서 쉽게 설명해줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-negated-paper-learning-source-finder",
        "Negated paper-learning mention stays source finder",
        "paper-learning 말고 논문 pdf 어디서 찾아?",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-negated-source-finder-paper-learning",
        "Negated source-finder mention stays paper learning",
        "source-finder 말고 이 논문 쉽게 설명해줘",
        "paper-learning",
        "prepare_paper_learning",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-attached-paper-beginner-learning",
        "Attached paper explanation stays paper learning",
        "첨부한 논문을 초보자 수준으로 풀어줘",
        "paper-learning",
        "prepare_paper_learning",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-paper-link-source-finder",
        "Korean paper link source finder",
        "초보자용으로 볼 수 있는 논문 링크를 찾아줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-dataset-report-source-finder",
        "Korean dataset acquisition source finder",
        "데이터셋 찾아서 요약 리포트로 정리해줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-github-oss-source-finder",
        "Korean GitHub OSS source finder",
        "깃허브 오픈소스 저장소 찾아서 구조 분석해줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-public-presentation-source-finder",
        "Korean public presentation acquisition source finder",
        "공개 발표자료 찾아서 요약해줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-public-slide-source-finder",
        "Korean public slide acquisition source finder",
        "공개 슬라이드 자료 찾아서 핵심 요약해줘",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-pr-image-tool-readiness",
        "Korean PR image request with missing generator readiness",
        "PR 요약 이미지 만들고 싶어 근데 GPT image 연결 안 됐어",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-fal-key-image-tool-readiness",
        "Korean image request with missing FAL key",
        "회의록 이미지 카드 만들고 싶은데 FAL_KEY가 없어",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-unattached-image-tool-readiness",
        "Korean image tool unattached readiness",
        "이미지 만들고 싶은데 도구가 안 붙어있어",
        "toolbelt-readiness",
        "prepare_toolbelt_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "research-department-daily-briefing-korean",
        "Korean daily market research department",
        "시장 뉴스 매일 브리핑하도록 리서치 부서 만들어줘",
        "research-department",
        "prepare_research_department_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "research-department-morning-market-research-korean",
        "Korean morning market research loop",
        "아침마다 시장 리서치 요약해줘",
        "research-department",
        "prepare_research_department_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-competitor-news-automation",
        "Korean competitor news automation blueprint",
        "오늘 아침 경쟁사 뉴스 요약 자동화해줘",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "research-department-knowledge-store-korean",
        "Korean research knowledge-store setup",
        "NotebookLM이랑 지식저장소 연결해서 리서치 요약하고 싶어",
        "research-department",
        "prepare_research_department_plan",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "memory-pile-cleanup-korean",
        "Korean accumulated memory cleanup",
        "메모리가 너무 쌓였는데 정리해줘",
        "memory-curation-review",
        "prepare_memory_curation_review",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "memory-stored-context-korean",
        "Korean stored memory inspection",
        "내 메모리 뭐가 저장되어있는지 점검해줘",
        "memory-curation-review",
        "prepare_memory_curation_review",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "missed-img-summary-route-korean",
        "Korean missed img-summary route feedback",
        "Hermes가 OMH img-summary를 안 썼는데 다음엔 쓰게 고쳐줘",
        "workflow-learning",
        "record_missed_route",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "missed-image-generation-route-feedback-korean",
        "Korean future missed image route feedback",
        "내가 방금 부탁한 이미지 생성에 OMH를 안 쓴 것 같은데 다음엔 쓰게 해줘",
        "workflow-learning",
        "record_missed_route",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "missed-paper-learning-route-feedback-korean",
        "Korean future missed paper-learning route feedback",
        "paper-learning 안 쓰고 그냥 답했어. 다음엔 논문 요약엔 OMH 쓰게 해줘",
        "workflow-learning",
        "record_missed_route",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "missed-coding-delegation-route-feedback-korean",
        "Korean future missed coding route feedback",
        "방금 코딩 위임에 OMH 안 쓴 것 같아. 다음엔 ultraprocess로 보내줘",
        "workflow-learning",
        "record_missed_route",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "workflow-trace-skill-improvement-korean",
        "Korean workflow trace skill improvement",
        "workflow trace 보고 다음에 스킬 고칠점 알려줘",
        "workflow-learning",
        "audit_learning_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "test-until-pass-coding-korean",
        "Korean test-as-stop-signal coding request",
        "테스트 통과할때까지 고쳐줘",
        "ultraprocess",
        "choose_executor",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "setup-output-improvement-korean",
        "Korean setup output improvement request",
        "setup 로그가 너무 어렵다 개선해줘",
        "ultraprocess",
        "answer_clarification",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "hud-menubar-restart-korean",
        "Korean HUD menu bar restart request",
        "상단바 hud 다시 켜고싶어",
        "agent-ops-review",
        "show_agent_ops_review",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "menubar-monitor-reopen-korean",
        "Korean menu bar monitor reopen request",
        "메뉴바 모니터링 다시 띄워줘",
        "agent-ops-review",
        "show_agent_ops_review",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-now-slang-korean",
        "Korean compact now-status slang",
        "지금 뭐함",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-doing-compact-korean",
        "Korean compact doing-status question",
        "뭐하고있어",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-current-work-korean",
        "Korean current-work status question",
        "현재 작업 뭐야",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-work-report-korean",
        "Korean work-status report question",
        "작업상황 보고해줘",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-doing-now-english",
        "English doing-now status question",
        "what are you doing now",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-going-on-rn-english",
        "English going-on status question",
        "what is going on rn",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-session-korean",
        "Korean session status question",
        "세션 상태 보여줘",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "status-question-work-history-korean",
        "Korean current-work history question",
        "내가 뭘 하고 있었는지 알려줘",
        "agent-ops-review",
        "refresh_agent_ops_status",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-meeting-vertical-image-card",
        "Korean meeting notes vertical image card",
        "이미지 생성해줘. 회의록을 세로 카드로 요약해줘",
        "img-summary",
        "prepare_visual_prompt_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-thumbnail-card",
        "Korean thumbnail card request",
        "썸네일 만들어줘",
        "img-summary",
        "prepare_visual_prompt_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-release-notes-thumbnail",
        "Korean release notes thumbnail request",
        "릴리즈 노트 썸네일로 만들어줘",
        "img-summary",
        "prepare_visual_prompt_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-photo-meeting-vertical-image-card",
        "Korean photo request for meeting notes vertical image card",
        "사진 생성해줘. 회의록을 보기 좋은 세로 이미지로 정리해줘",
        "img-summary",
        "prepare_visual_prompt_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-pretty-meeting-image-card",
        "Korean pretty meeting image request",
        "회의록을 예쁜 이미지로 만들어줘",
        "img-summary",
        "prepare_visual_prompt_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-github-pr-reviewer-image-card",
        "Korean GitHub PR reviewer image card",
        "이 GitHub PR을 리뷰어용 이미지 카드로 만들어줘",
        "img-summary",
        "prepare_visual_prompt_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-release-announcement-card",
        "Korean release announcement card",
        "릴리즈 노트를 announcement 카드로 만들어줘",
        "img-summary",
        "prepare_visual_prompt_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "korean-hermes-coding-team-only",
        "Korean Hermes-only coding team path",
        "Hermes만으로 코딩팀처럼 작업하고 싶어",
        "team",
        "show_runtime_handoff",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "claude-code-open-this-work-korean",
        "Korean Claude Code open current work",
        "Claude Code로 이거 열어서 작업하게 해줘",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "hermes-direct-coding-owner-korean",
        "Korean Hermes direct coding owner selection",
        "Hermes한테 직접 코딩시키고 싶어",
        "executor-runtime-readiness",
        "prepare_executor_runtime_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "execution-trace-skill-improvement-korean",
        "Korean execution trace skill improvement",
        "이번 실행 trace로 skill 개선 제안 만들어줘",
        "workflow-learning",
        "audit_learning_readiness",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "multi-hermes-agent-board-korean",
        "Korean multi-Hermes agent board",
        "여러 Hermes agent가 같이 일할 board 만들어줘",
        "agent-board",
        "prepare_agent_board_card",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "release-docs-claim-korean",
        "Korean release docs-claim review",
        "release 전에 docs claim이 맞는지 확인해줘",
        "code-review",
        "prepare_review_or_followup_handoff",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "loop-direct-task-korean",
        "Korean direct task loopability check",
        "웹사이트 버튼 색 바꾸는 것도 loop로 해야해?",
        "loop",
        "route_direct_task",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "loop-north-star-english",
        "English north-star loop reframe",
        "Make this a 100k-star OSS",
        "loop",
        "reframe_north_star",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "loop-first-run-project",
        "First-run loopable project",
        "run a loop to improve first-run experience",
        "loop",
        "choose_permission_profile",
    ),
    RouteHintAlignmentCase(
        "operator_regression",
        "loop-first-success-project-korean",
        "Korean first-success loopable project",
        "설치 후 첫 성공까지 막히는 부분을 계속 개선해줘",
        "loop",
        "choose_permission_profile",
    ),
)


def route_hint_alignment_cases() -> tuple[RouteHintAlignmentCase, ...]:
    return tuple(
        [
            RouteHintAlignmentCase(
                "grounded_score",
                scenario.id,
                scenario.title,
                scenario.message,
                scenario.expected_skill,
                scenario.expected_next_action,
            )
            for scenario in GROUNDED_SCENARIOS
        ]
        + [
            RouteHintAlignmentCase(
                "chat_card_coverage",
                case.id,
                case.title,
                case.message,
                case.expected_skill,
                case.expected_next_action,
            )
            for case in CHAT_CARD_COVERAGE_CASES
        ]
        + list(_OPERATOR_ROUTE_HINT_ALIGNMENT_CASES)
    )


def build_route_hint_alignment_demo(
    *,
    source: str = "discord",
    grounded_score: Mapping[str, object] | None = None,
    chat_card_coverage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    precomputed_routes = _precomputed_route_observations(
        grounded_score=grounded_score,
        chat_card_coverage=chat_card_coverage,
    )
    rows = [
        _evaluate_alignment_case(
            case,
            source=source,
            route_observation=precomputed_routes.get((case.corpus, case.id)),
        )
        for case in route_hint_alignment_cases()
    ]
    aligned_count = sum(1 for row in rows if bool(row["aligned"]))
    hinted_count = sum(1 for row in rows if _nested(row, "observed").get("hint_status") == "hinted")
    return {
        "schema_version": ROUTE_HINT_ALIGNMENT_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": len(rows),
            "hinted_count": hinted_count,
            "aligned_count": aligned_count,
            "missing_hint_count": len(rows) - hinted_count,
            "mismatch_count": len(rows) - aligned_count,
            "all_aligned": bool(rows) and aligned_count == len(rows),
        },
        "check_basis": [
            "The chat router selects the expected workflow for each representative operator message.",
            "The chat router and plugin awareness hint agree on the expected next user-facing action.",
            "The plugin awareness route hint returns a primary workflow instead of no_hint.",
            "The primary hint workflow matches the chat router and the expected public workflow.",
            "The hint carries a workflow context card and advisory-only claim boundary.",
            "This gate checks deterministic router/hint agreement only; it is not live Hermes rendering or execution evidence.",
        ],
        "cases": rows,
        "claim_boundary": (
            "Route hint alignment proves deterministic local agreement between chat routing and plugin awareness hints. "
            "It does not prove live Hermes chat rendering, platform delivery, executor execution, review, CI, merge, "
            "or plugin-load evidence."
        ),
    }


def format_route_hint_alignment_summary(payload: dict[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _dict_rows(payload.get("cases", []))
    total = int(summary.get("case_count", len(rows)) or 0)
    aligned = int(summary.get("aligned_count", 0) or 0)
    hinted = int(summary.get("hinted_count", 0) or 0)
    missing = int(summary.get("missing_hint_count", 0) or 0)
    mismatches = int(summary.get("mismatch_count", 0) or 0)
    all_aligned = bool(summary.get("all_aligned", False))
    lines = [
        "OMH route hint alignment",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {aligned}/{total} route hints aligned" + (" (all passing)" if all_aligned else ""),
        f"Hints present: {hinted}/{total}; missing hints: {missing}; mismatches: {mismatches}",
        "",
        "What this proves:",
    ]
    for basis in payload.get("check_basis", []):
        lines.append(f"- {basis}")
    lines.extend(["", "Alignment rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("aligned") else "needs attention"
        route_next_action = str(observed.get("route_next_action", "unknown"))
        hint_next_action = str(observed.get("hint_next_action", "unknown"))
        if route_next_action == hint_next_action:
            next_action_text = f"next={next_action_label(hint_next_action)}"
        else:
            next_action_text = (
                f"route_next={next_action_label(route_next_action)} "
                f"hint_next={next_action_label(hint_next_action)}"
            )
        lines.append(
            f"- {row.get('title', 'Untitled route')}: {status}; "
            f"route={observed.get('route_workflow', 'unknown')} "
            f"hint={observed.get('hint_workflow', 'unknown')} "
            f"{next_action_text}"
        )
    failed = [row for row in rows if not row.get("aligned")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('corpus', 'unknown')}:{row.get('id', 'unknown')}: {', '.join(row.get('issues', [])) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def _evaluate_alignment_case(
    case: RouteHintAlignmentCase,
    *,
    source: str,
    route_observation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if route_observation is None:
        interaction = build_chat_interaction_payload(case.message, source=source)
        route_observation = {
            "route_workflow": _nested(interaction, "route").get("selected_skill"),
            "route_action": _nested(interaction, "route").get("action"),
            "route_next_action": interaction.get("next_action"),
            "route_confidence": _nested(interaction, "route").get("confidence"),
        }
    hint = awareness_route_hint(case.message)
    hint_context_card = _nested(_first_dict(hint.get("hints")), "workflow_context_card")
    observed = {
        "route_workflow": route_observation.get("route_workflow"),
        "route_action": route_observation.get("route_action"),
        "route_next_action": route_observation.get("route_next_action"),
        "route_confidence": route_observation.get("route_confidence"),
        "hint_status": hint.get("status"),
        "hint_workflow": hint.get("primary_workflow"),
        "hint_next_action": hint.get("primary_next_action"),
        "hint_context_card": hint_context_card.get("id", ""),
        "hint_claim_boundary": hint.get("claim_boundary"),
    }
    issues: list[str] = []
    if observed["route_workflow"] != case.expected_workflow:
        issues.append(f"expected route workflow {case.expected_workflow}, observed {observed['route_workflow']}")
    if observed["route_next_action"] != case.expected_next_action:
        issues.append(f"expected route next action {case.expected_next_action}, observed {observed['route_next_action']}")
    if observed["hint_status"] != "hinted":
        issues.append("missing awareness route hint")
    if observed["hint_workflow"] != case.expected_workflow:
        issues.append(f"expected hint workflow {case.expected_workflow}, observed {observed['hint_workflow'] or 'none'}")
    if observed["hint_next_action"] != case.expected_next_action:
        issues.append(f"expected hint next action {case.expected_next_action}, observed {observed['hint_next_action'] or 'none'}")
    if observed["hint_workflow"] != observed["route_workflow"]:
        issues.append(f"route/hint mismatch: {observed['route_workflow']} != {observed['hint_workflow']}")
    if observed["hint_next_action"] != observed["route_next_action"]:
        issues.append(f"route/hint next-action mismatch: {observed['route_next_action']} != {observed['hint_next_action']}")
    if not observed["hint_context_card"]:
        issues.append("missing hint workflow context card")
    if "not workflow execution" not in str(observed["hint_claim_boundary"] or ""):
        issues.append("missing advisory-only hint boundary")
    return {
        "corpus": case.corpus,
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "aligned": not issues,
        "expected": {"workflow": case.expected_workflow, "next_action": case.expected_next_action},
        "observed": observed,
        "issues": issues,
    }


def _precomputed_route_observations(
    *,
    grounded_score: Mapping[str, object] | None,
    chat_card_coverage: Mapping[str, object] | None,
) -> dict[tuple[str, str], dict[str, object]]:
    observations: dict[tuple[str, str], dict[str, object]] = {}
    if grounded_score is not None:
        for row in _dict_rows(grounded_score.get("scenarios", [])):
            observed = _nested(row, "observed")
            route_workflow = observed.get("skill")
            if not route_workflow:
                continue
            observations[("grounded_score", str(row.get("id", "")))] = {
                "route_workflow": route_workflow,
                "route_action": observed.get("route_action"),
                "route_next_action": observed.get("next_action"),
                "route_confidence": observed.get("route_confidence") or "precomputed",
            }
    if chat_card_coverage is not None:
        for row in _dict_rows(chat_card_coverage.get("cases", [])):
            observed = _nested(row, "observed")
            route_workflow = observed.get("workflow")
            if not route_workflow:
                continue
            observations[("chat_card_coverage", str(row.get("id", "")))] = {
                "route_workflow": route_workflow,
                "route_action": observed.get("route_action"),
                "route_next_action": observed.get("next_action"),
                "route_confidence": observed.get("confidence") or "precomputed",
            }
    return observations


def _first_dict(value: object) -> dict[str, object]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _nested(payload: object, key: str) -> dict[str, object]:
    if isinstance(payload, dict):
        value = payload.get(key)
        return value if isinstance(value, dict) else {}
    return {}


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
