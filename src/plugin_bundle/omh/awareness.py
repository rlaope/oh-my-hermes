from __future__ import annotations

from functools import lru_cache
import hashlib
import re
import unicodedata

_DIAGNOSTIC_STATUS_MARKERS = (
    "[omh awareness]",
    "[omh route hint]",
    "[omh]",
    "evidence boundary",
    "not_executed=",
    "latest_runtime_run",
    "latest runtime run",
    "execution_observed",
    "review_observed",
    "ci_observed",
    "merge_observed",
    "prepared_not_observed",
)
_DIAGNOSTIC_STATUS_LINE_MARKERS = (
    *_DIAGNOSTIC_STATUS_MARKERS,
    "selected_workflow=",
    "mentioned_workflows=",
    "mentioned_runtime_terms=",
    "not_executed=",
    "intent_class=",
    "status=",
    "workflow=",
    "hints=",
)
_OMH_DIAGNOSTIC_EVALUATION_CUES = (
    "usage evaluation",
    "usability evaluation",
    "usage analysis",
    "analyze the run",
    "analyze this run",
    "router improvement",
    "router hardening",
    "route improvement",
    "evaluate omh",
    "why omh",
    "사용성 평가",
    "사용성평가",
    "omh 관여",
    "omh관여",
    "omh 관여도",
    "omh관여도",
    "안쓴이유",
    "안 쓴 이유",
    "덜 쓴 이유",
    "덜쓴 이유",
    "덜 썼",
    "덜썼",
    "부족했던 점",
    "부족한 점",
    "라우터 강화",
    "라우터강화",
    "라우터 개선",
    "플랜으로 잡",
    "반복해서 강화",
)

try:  # Keep installed plugin bundles usable even when the full package is absent.
    from ...routing.intent import META_OR_FEEDBACK_INTENTS, classify_omh_quality_intent, classify_workflow_intent
except ImportError:  # pragma: no cover - exercised by standalone plugin hosts.
    from dataclasses import dataclass

    META_OR_FEEDBACK_INTENTS = frozenset({"meta_discussion", "feedback_signal"})

    @dataclass(frozen=True)
    class _FallbackWorkflowIntent:
        intent_class: str
        explicit_execution: bool
        mentioned_workflows: tuple[str, ...]
        mentioned_runtime_terms: tuple[str, ...]
        meta_cues: tuple[str, ...]
        feedback_cues: tuple[str, ...]
        missing_requirements_cues: tuple[str, ...]
        routing_context: bool

        @property
        def not_executed(self) -> tuple[str, ...]:
            if self.intent_class == "delivery_intent":
                return ()
            return (*self.mentioned_workflows, *self.mentioned_runtime_terms)

    @dataclass(frozen=True)
    class _FallbackOmhQualityIntent:
        applies: bool
        target_cues: tuple[str, ...]
        improvement_cues: tuple[str, ...]
        quality_cues: tuple[str, ...]
        loop_cues: tuple[str, ...]
        handoff_cues: tuple[str, ...]
        customer_feedback_cues: tuple[str, ...]
        matched_label: str = "semantic:omh_quality_improvement_loop"
        primary_workflow: str = "ultraprocess"

        @property
        def matched_cues(self) -> tuple[str, ...]:
            return (
                *(f"target:{cue}" for cue in self.target_cues),
                *(f"improve:{cue}" for cue in self.improvement_cues),
                *(f"quality:{cue}" for cue in self.quality_cues),
                *(f"loop:{cue}" for cue in self.loop_cues),
                *(f"handoff:{cue}" for cue in self.handoff_cues),
            )

    def _fallback_contains_non_ascii(value: str) -> bool:
        return any(ord(char) > 127 for char in value)

    def _fallback_contains_bounded_english_cue(text: str, cue: str) -> bool:
        parts = re.findall(r"[a-z0-9]+", cue)
        if not parts:
            return False
        separator = r"[\s_-]+"
        pattern = r"(?<![a-z0-9])" + separator.join(re.escape(part) for part in parts) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None

    def _fallback_matched_omh_quality_cues(cues: tuple[str, ...], text: str, compact: str) -> tuple[str, ...]:
        matches = []
        for cue in cues:
            normalized_cue = unicodedata.normalize("NFKC", cue).casefold()
            if not normalized_cue:
                continue
            if _fallback_contains_non_ascii(normalized_cue):
                if normalized_cue in text or normalized_cue.replace(" ", "") in compact:
                    matches.append(cue)
                continue
            if _fallback_contains_bounded_english_cue(text, normalized_cue):
                matches.append(cue)
        return tuple(matches)

    def _fallback_diagnostic_status_context(text: str) -> bool:
        return any(marker in text for marker in _DIAGNOSTIC_STATUS_MARKERS)

    def _fallback_diagnostic_omh_evaluation_context(text: str, compact: str) -> bool:
        if not _fallback_diagnostic_status_context(text):
            return False
        user_region = _without_diagnostic_status_lines(text)
        user_compact = user_region.replace(" ", "")
        has_user_omh_subject = bool(re.search(r"(?<![a-z0-9])omh(?![a-z0-9])", user_region))
        has_user_router_subject = bool(_matched_text_cues(("router", "routing", "route hint", "라우터", "라우팅"), user_region, user_compact))
        if not (has_user_omh_subject or has_user_router_subject):
            return False
        return bool(
            _fallback_matched_omh_quality_cues(
                _OMH_DIAGNOSTIC_EVALUATION_CUES,
                user_region,
                user_compact,
            )
        )

    def classify_omh_quality_intent(message: str) -> _FallbackOmhQualityIntent:
        text = unicodedata.normalize("NFKC", message).casefold()
        compact = text.replace(" ", "")
        system_target_cues = []
        if re.search(r"(?<![a-z0-9])omh(?![a-z0-9])", text):
            system_target_cues.append("omh")
        system_target_cues.extend(cue for cue in ("oh-my-hermes", "oh my hermes") if cue in text and cue not in system_target_cues)
        quality_domain_cues = _fallback_matched_omh_quality_cues(
            (
                "route quality",
                "router",
                "routing",
                "route hint",
                "context loss",
                "context-loss",
                "context safety",
                "progress reporting",
                "progress evidence",
                "coding handoff",
                "handoff reliability",
                "라우터",
                "라우팅",
                "맥락",
                "컨텍스트",
                "컨텍스트 손실",
                "진행상태",
                "진행 상태",
                "코딩 handoff",
            ),
            text,
            compact,
        )
        improvement_cues = _fallback_matched_omh_quality_cues(
            (
                "improve",
                "improvement",
                "fix",
                "fixed",
                "fixes",
                "fixing",
                "harden",
                "strengthen",
                "audit",
                "find and fix",
                "개선",
                "개선해",
                "고쳐",
                "찾아",
                "점검",
                "강화",
            ),
            text,
            compact,
        )
        quality_cues = _fallback_matched_omh_quality_cues(
            (
                "bug",
                "bugs",
                "failure",
                "loss",
                "missing",
                "regression",
                "reliability",
                "quality",
                "버그",
                "유사버그",
                "실패",
                "손실",
                "누락",
                "신뢰성",
                "품질",
            ),
            text,
            compact,
        )
        loop_cues = _fallback_matched_omh_quality_cues(
            ("loop", "continuous", "keep", "keeps", "keeping", "루프", "계속", "반복"),
            text,
            compact,
        )
        handoff_cues = _fallback_matched_omh_quality_cues(("coding handoff", "handoff", "코딩"), text, compact)
        customer_feedback_cues = _fallback_matched_omh_quality_cues(
            ("customer", "payment", "고객", "결제", "피드백", "제보"),
            text,
            compact,
        )
        applies = bool(system_target_cues and (quality_domain_cues or handoff_cues) and (improvement_cues or loop_cues or quality_cues))
        if customer_feedback_cues and not system_target_cues:
            applies = False
        return _FallbackOmhQualityIntent(
            applies=applies,
            target_cues=(*tuple(system_target_cues), *quality_domain_cues),
            improvement_cues=improvement_cues,
            quality_cues=quality_cues,
            loop_cues=loop_cues,
            handoff_cues=handoff_cues,
            customer_feedback_cues=customer_feedback_cues,
        )

    def classify_workflow_intent(message: str) -> _FallbackWorkflowIntent:
        text = unicodedata.normalize("NFKC", message).casefold()
        compact = text.replace(" ", "")
        diagnostic_evaluation = _fallback_diagnostic_omh_evaluation_context(text, compact)
        analysis_text = text if diagnostic_evaluation or not _diagnostic_status_context(text) else _without_diagnostic_status_lines(text)
        delivery_workflows = {
            "ultraprocess",
            "ralplan",
            "ultragoal",
            "loop",
            "workflow-learning",
            "code-review",
            "team",
            "ultrawork",
            "ultraqa",
        }
        mentioned_workflows = tuple(workflow for workflow in delivery_workflows if workflow in analysis_text)
        runtime_terms = []
        for term, label in (
            ("codex", "Codex"),
            ("coding handoff", "coding handoff"),
            ("coding delegate", "coding delegate"),
            ("one-cycle delivery", "one-cycle delivery"),
            ("one cycle delivery", "one-cycle delivery"),
        ):
            if term in analysis_text and label not in runtime_terms:
                runtime_terms.append(label)
        meta_cues = tuple(
            cue
            for cue in (
                "test",
                "developer",
                "operator",
                "vocabulary",
                "route hint",
                "hud",
                "log",
                "trigger",
                "테스트",
                "개발자",
                "용어",
                "로그",
                "트리거",
                "오해",
                "라우터",
            )
            if cue in analysis_text
        )
        feedback_cues = tuple(
            cue
            for cue in (
                "why",
                "wrong route",
                "missed route",
                "왜",
                "잘못",
                "오해",
                "누락",
                "사용성 평가",
                "안쓴이유",
                "안 쓴 이유",
            )
            if cue in analysis_text
        )
        missing = tuple(cue for cue in ("no requirements", "missing requirements", "요구사항은 없어", "요구사항 없음") if cue in analysis_text)
        negated_execution = tuple(
            cue
            for cue in ("not asking to implement", "not asking for implementation", "not implement", "do not implement", "don't implement", "without implementation", "no implementation")
            if cue in analysis_text
        )
        execution = tuple(
            cue
            for cue in ("implement", "make a pr", "open a pr", "dispatch", "delegate", "send to codex", "run ultraprocess", "구현", "pr 만들어", "codex로", "맡겨", "실행")
            if cue in analysis_text and not (negated_execution and cue in {"implement", "구현"})
        )
        routing_context = any(
            cue in analysis_text.split() or cue in analysis_text
            for cue in ("routing", "route", "workflow", "handoff", "coding", "route hint", "coding handoff", "coding delegate", "라우팅", "워크플로", "코딩")
        ) or " omh " in f" {analysis_text} "
        specific_runtime_reference = any(term != "Codex" for term in runtime_terms)
        workflow_or_specific_runtime = bool(mentioned_workflows or specific_runtime_reference)
        if execution:
            intent_class = "delivery_intent"
        elif diagnostic_evaluation or missing or (feedback_cues and (routing_context or workflow_or_specific_runtime)):
            intent_class = "feedback_signal"
        elif meta_cues and (routing_context or workflow_or_specific_runtime):
            intent_class = "meta_discussion"
        else:
            intent_class = "unknown"
        return _FallbackWorkflowIntent(
            intent_class=intent_class,
            explicit_execution=bool(execution),
            mentioned_workflows=mentioned_workflows,
            mentioned_runtime_terms=tuple(runtime_terms),
            meta_cues=meta_cues,
            feedback_cues=feedback_cues,
            missing_requirements_cues=missing,
            routing_context=routing_context,
        )

try:  # File-loaded plugin bundles should still use package classifiers when OMH is installed.
    from omh.routing.intent import META_OR_FEEDBACK_INTENTS, classify_omh_quality_intent, classify_workflow_intent
except ImportError:  # pragma: no cover - standalone plugin hosts keep the fallback above.
    pass

try:  # Keep route hints aligned with router locale phrase packs when available.
    from ...routing.localization import prepare_routing_text as _prepare_routing_text
except ImportError:  # pragma: no cover - exercised by standalone plugin hosts.
    _prepare_routing_text = None

try:  # File-loaded plugin bundles can still reuse OMH locale phrase packs.
    from omh.routing.localization import prepare_routing_text as _prepare_routing_text
except ImportError:  # pragma: no cover - standalone plugin hosts keep the fallback above.
    pass

try:  # Prefer the package copy table, but keep copied plugin bundles standalone.
    from ...routing.action_copy import next_action_label as _next_action_label
except ImportError:  # pragma: no cover - exercised by standalone plugin hosts.

    def _next_action_label(action: str) -> str:
        return action.strip().replace("_", " ")

try:  # File-loaded plugin bundles should keep the nicer action copy when OMH is installed.
    from omh.routing.action_copy import next_action_label as _next_action_label
except ImportError:  # pragma: no cover - standalone plugin hosts keep the fallback above.
    pass

try:  # Keep loop route hints aligned with the deterministic loopability assessor.
    from omh.loopability import assess_loopability as _assess_loopability
except ImportError:  # pragma: no cover - exercised by standalone plugin hosts.
    try:
        from ...loopability import assess_loopability as _assess_loopability
    except ImportError:
        _assess_loopability = None

OMH_AWARENESS_SCHEMA_VERSION = "omh_awareness/v1"
OMH_ROUTE_HINT_SCHEMA_VERSION = "omh_route_hint/v1"
OMH_GENERIC_TOOL_CHECKPOINT_SCHEMA_VERSION = "omh_generic_tool_checkpoint/v1"
GENERIC_TOOL_CHECKPOINT_TEXT = "Before generic tools, check OMH prep/status/learning; if relevant, name the workflow first."
GENERIC_TOOL_CHECKPOINT_APPLIES_BEFORE = ("image tools", "file tools", "search tools", "coding tools")
GENERIC_TOOL_CHECKPOINT_ROUTES = (
    {
        "tool_family": "image_tools",
        "applies_before": ("image generation", "local rendering", "visual design tools"),
        "primary_workflow": "img-summary",
        "preferred_workflows": ("img-summary", "design-quality-gate", "materials-package", "report-package"),
        "primary_next_action": "prepare_visual_prompt_card",
        "fallback_action": "choose_image_generator_or_setup",
        "not_evidence_yet": ("image generation", "visual QA", "attachment", "delivery"),
    },
    {
        "tool_family": "file_tools",
        "applies_before": ("PPT/PDF/XLSX/DOC/HWP generation", "file conversion", "attachment packaging"),
        "primary_workflow": "materials-package",
        "preferred_workflows": ("materials-package", "design-quality-gate", "paper-learning", "deliverable-package", "report-package"),
        "primary_next_action": "prepare_material_package",
        "fallback_action": "confirm_target_format_and_generator",
        "not_evidence_yet": ("file export", "render QA", "attachment", "delivery"),
    },
    {
        "tool_family": "search_tools",
        "applies_before": ("web search", "source lookup", "market/news/paper research"),
        "primary_workflow": "web-research",
        "preferred_workflows": ("source-finder", "web-research", "paper-learning", "research-department", "research-brief"),
        "primary_next_action": "gather_source_backed_evidence",
        "fallback_action": "ask_for_scope_or_source_constraints",
        "not_evidence_yet": ("source retrieval", "source verification", "synthesis approval", "delivery"),
    },
    {
        "tool_family": "coding_tools",
        "applies_before": ("Codex", "Claude Code", "Hermes coding", "oh-my runtime handoff"),
        "primary_workflow": "ultraprocess",
        "preferred_workflows": ("ultraprocess", "ralplan", "code-review", "agent-ops-review"),
        "primary_next_action": "prepare_one_cycle_delivery",
        "fallback_action": "choose_coding_agent_or_runtime",
        "not_evidence_yet": ("executor dispatch", "implementation", "review", "CI", "merge"),
    },
)
ROUTER_KEYWORD_SKILLS = (
    "deep-interview",
    "ralplan",
    "ultragoal",
    "loop",
    "ultraprocess",
    "web-research",
    "research-department",
    "source-finder",
    "paper-learning",
    "feedback-triage",
    "materials-package",
    "img-summary",
    "design-quality-gate",
    "automation-blueprint",
    "workflow-learning",
    "code-review",
    "team",
    "ultrawork",
    "ultraqa",
    "doctor",
)

LANE_CROSS_LANE_EXAMPLES = {
    "intent_to_plan": [
        "ambitious goal -> loopability check -> loop or ultraprocess -> verification status",
        "fuzzy feature request -> deep-interview -> ralplan -> accepted plan",
    ],
    "research_and_ops": [
        "customer signal -> feedback-triage -> investigation plan -> coding handoff -> status",
        "source discovery -> source-finder -> candidate set -> downstream workflow",
        "supplied paper -> paper-learning -> level choice -> coverage ledger -> section walkthrough",
        "market topic -> web-research -> research-brief -> strategy-brief -> operating-rhythm",
    ],
    "retained_knowledge": [
        "decision -> wiki -> write boundary",
        "external store -> wiki -> retrieval hints",
    ],
    "materials_and_visuals": [
        "meeting notes -> meeting-brief -> report-package -> img-summary -> delivery evidence",
        "source spreadsheet -> materials-package -> report-package -> observed export evidence",
    ],
    "automation_and_status": [
        "daily digest request -> automation-blueprint -> confirmation card -> observed schedule evidence",
        "workflow attempt -> workflow-learning -> eval -> improvement candidate or regression case",
        "runtime confusion -> doctor or agent-ops-review -> status card -> next repair action",
    ],
    "coding_handoff": [
        "accepted plan -> ultraprocess -> coding handoff -> review and CI evidence",
        "risky change -> ralplan -> executor selection -> observed coding-agent status",
    ],
}
WORKFLOW_CONTEXT_CARDS = (
    {
        "id": "intent_to_plan",
        "label": "Intent to plan",
        "user_signal": "fuzzy goal, ambitious target, safe feature, or one-cycle delivery request",
        "omh_pattern": "clarify or plan first, then move to ultragoal, ultraprocess, loop, or handoff only when concrete",
        "representative_workflows": ("deep-interview", "ralplan", "ultragoal", "loop", "ultraprocess"),
        "user_examples": ("Make onboarding feel smoother", "Make this repo star-worthy"),
        "first_response_shape": "Name the ambiguity, choose clarify/plan/loop/process, then state the next concrete action and what is not evidence yet.",
        "not_evidence_until_observed": ("plan acceptance", "executor dispatch", "verification"),
    },
    {
        "id": "research_and_ops",
        "label": "Research and ops",
        "user_signal": "customer signal, meeting notes, source candidates, market question, strategy request, or operating record",
        "omh_pattern": "classify source acquisition when needed, collect evidence, separate source notes from synthesis, then create a brief, decision, or status artifact",
        "representative_workflows": ("source-finder", "web-research", "paper-learning", "research-department", "feedback-triage", "meeting-brief", "strategy-brief"),
        "user_examples": (
            "Find papers and datasets for this topic",
            "Payment failures keep coming up",
            "Track competitor news every morning",
        ),
        "first_response_shape": "Name the source/synthesis split, including source acquisition when relevant, pick the research or ops workflow, then ask for missing source evidence or cadence only when needed.",
        "not_evidence_until_observed": ("source retrieval", "decision approval", "delivery"),
    },
    {
        "id": "retained_knowledge",
        "label": "Retained knowledge",
        "user_signal": "wiki, durable notes, Obsidian, Notion, Drive, or external store",
        "omh_pattern": "prepare source-backed notes and destination hints; writes need evidence",
        "representative_workflows": ("wiki",),
        "user_examples": ("Wiki",),
        "first_response_shape": "Name target, source evidence, retrieval hints, missing write/query proof.",
        "not_evidence_until_observed": ("external write", "connector I/O", "memory mutation", "source verification"),
    },
    {
        "id": "materials_and_visuals",
        "label": "Materials and visuals",
        "user_signal": "deck, PDF, spreadsheet, document, HWP, report, website, poster, image card, or shareable summary",
        "omh_pattern": "shape the deliverable contract, prepare prompts/package/design-quality metadata, then record generation and QA only when observed",
        "representative_workflows": ("design-quality-gate", "materials-package", "report-package", "deliverable-package", "img-summary"),
        "user_examples": ("Turn this PR into a reviewer image card", "Make this spreadsheet a PDF report package"),
        "first_response_shape": "Separate copy/layout/package prep from generated file or image evidence, then offer revise/copy/generate/record actions.",
        "not_evidence_until_observed": ("file export", "image generation", "visual QA", "attachment"),
    },
    {
        "id": "automation_and_status",
        "label": "Automation and status",
        "user_signal": "recurring digest, cron-like request, gateway command, health check, status confusion, workflow learning, or runtime question",
        "omh_pattern": "prepare a schedule/status/repair/learning card, name required tools or evidence, then keep observed runtime state separate",
        "representative_workflows": (
            "automation-blueprint",
            "agent-ops-review",
            "workflow-learning",
            "toolbelt-readiness",
            "doctor",
        ),
        "user_examples": (
            "Every morning send a digest if something changed",
            "Why did this route to plan? Make it a regression.",
        ),
        "first_response_shape": "Show the prepared status, schedule, or learning shape, name the missing evidence, and expose refresh, repair, or review actions.",
        "not_evidence_until_observed": ("schedule creation", "connector I/O", "runtime load", "skill patch approval"),
    },
    {
        "id": "coding_handoff",
        "label": "Coding handoff",
        "user_signal": "risky code change, issue-to-PR, review, CI, merge, coding-agent progress, or Hermes coding request",
        "omh_pattern": "choose the coding owner, prepare executor-neutral handoff or Hermes coding team path, then track dispatch and result evidence",
        "representative_workflows": ("ultraprocess", "code-review", "team", "ultrawork", "ultraqa"),
        "user_examples": ("Turn this issue into a PR-ready plan", "Is the Codex run done yet?"),
        "first_response_shape": "State the selected coding owner or choice point, prepare the handoff/status, and keep dispatch, result, review, CI, and merge evidence separate.",
        "not_evidence_until_observed": ("dispatch", "implementation", "review", "CI", "merge"),
    },
)
_WORKFLOW_CONTEXT_CARD_BY_WORKFLOW = {
    "deep-interview": "intent_to_plan",
    "plan": "intent_to_plan",
    "ralplan": "intent_to_plan",
    "ralph": "intent_to_plan",
    "ultragoal": "intent_to_plan",
    "loop": "intent_to_plan",
    "ultraprocess": "intent_to_plan",
    "performance-goal": "intent_to_plan",
    "web-research": "research_and_ops",
    "research-department": "research_and_ops",
    "source-finder": "research_and_ops",
    "paper-learning": "research_and_ops",
    "research-brief": "research_and_ops",
    "best-practice-research": "research_and_ops",
    "autoresearch-goal": "research_and_ops",
    "feedback-triage": "research_and_ops",
    "meeting-brief": "research_and_ops",
    "strategy-brief": "research_and_ops",
    "operating-rhythm": "research_and_ops",
    "wiki": "retained_knowledge",
    "materials-package": "materials_and_visuals",
    "report-package": "materials_and_visuals",
    "deliverable-package": "materials_and_visuals",
    "img-summary": "materials_and_visuals",
    "design-quality-gate": "materials_and_visuals",
    "achievements": "automation_and_status",
    "automation-blueprint": "automation_and_status",
    "agent-board": "automation_and_status",
    "agent-ops-review": "automation_and_status",
    "doctor": "automation_and_status",
    "gateway-intent-card": "automation_and_status",
    "memory-curation-review": "automation_and_status",
    "ops-observability-card": "automation_and_status",
    "ops-review": "automation_and_status",
    "reliability-review": "automation_and_status",
    "skill": "automation_and_status",
    "toolbelt-readiness": "automation_and_status",
    "voice-operator": "automation_and_status",
    "workflow-learning": "automation_and_status",
    "ai-slop-cleaner": "coding_handoff",
    "ask": "coding_handoff",
    "code-review": "coding_handoff",
    "cto-loop": "coding_handoff",
    "deploy-and-monitor": "coding_handoff",
    "executor-runtime-readiness": "coding_handoff",
    "github-event-ops": "coding_handoff",
    "idea-to-deploy": "coding_handoff",
    "team": "coding_handoff",
    "ultraqa": "coding_handoff",
    "ultrawork": "coding_handoff",
}
_AWARENESS_MESSAGE_MARKERS = (
    "oh-my-hermes",
    "pull request",
    "100k-star",
    "star oss",
    "delivery policy",
    "dangerous refactor",
    "image card",
    "improve our onboarding",
    "summary card",
    "thumbnail",
    "infographic",
    "poster",
    "route discord",
    "shareable card",
    "visual one-pager",
    "what happened next",
    "where to start",
    "what are you doing",
    "what are you doing now",
    "what is going on",
    "what is going on rn",
    "what was i working on",
    "show session status",
    "계획",
    "리서치",
    "회의",
    "회의록",
    "피드백",
    "이슈",
    "버그",
    "상태",
    "세션 상태",
    "썸네일",
    "릴리즈 노트 썸네일",
    "arxiv",
    "arxiv 링크",
    "source-finder",
    "paper-learning",
    "자동화",
    "루프",
    "부드럽게",
    "실제 사용자처럼",
    "어디까지",
    "내가 뭘 하고 있었는지",
    "워크플로우 다음",
    "메모리",
    "기억",
    "맥락",
    "코딩",
    "코덱스",
    "클로드",
    "리뷰",
    "릴리즈",
    "보고서",
    "자료",
    "setup log",
    "setup logs",
    "setup output",
    "setup ux",
    "setup 로그",
    "setup 출력",
    "셋업 로그",
    "셋업 출력",
    "로그가 너무 어렵",
    "출력이 너무 어렵",
    "설치 후",
    "첫 성공",
    "첫 성공까지",
    "테스트 통과",
    "통과할때까지",
    "통과할 때까지",
    "계속 개선",
    "계속해서 개선",
    "막히는 부분을 계속 개선",
    "상단바 hud",
    "메뉴바 모니터링",
    "메뉴바 다시",
    "메뉴바다시",
    "이미지",
    "사진",
    "진단",
    "실제로 뭐 했는지",
    "ai가 했다고",
    "사진처럼",
    "설명 사진",
    "요약 사진",
    "첨부한 논문",
    "논문 링크",
    "데이터셋 찾아",
    "깃허브 오픈소스",
    "오픈소스 저장소",
    "공개 슬라이드",
    "포스터",
    "공유용 카드",
    "요약 카드",
    "카드뉴스",
    "위험한 리팩터링",
    "더 잘하게",
    "스킬 고쳐",
    "hermes agent",
    "agent 여러",
    "보드",
    "잘 됐는지",
    "잘됐는지",
    "지금 뭐함",
    "뭐하고있어",
    "뭐 하는중이야",
    "진행중인거 뭐야",
    "현재 작업 뭐야",
    "작업상황 보고",
    "현재 상태 브리핑",
    "어디까지 했노",
    "어디까지 됐노",
    "画像",
    "海报",
    "海報",
)
_AWARENESS_TOKEN_MARKERS = frozenset(
    {
        "omh",
        "workflow",
        "workflows",
        "100k-star",
        "skill",
        "skills",
        "plan",
        "planning",
        "research",
        "brief",
        "meeting",
        "feedback",
        "issue",
        "bug",
        "pr",
        "status",
        "hud",
        "automation",
        "cron",
        "schedule",
        "loop",
        "handoff",
        "coding",
        "codex",
        "claude",
        "review",
        "release",
        "deck",
        "ppt",
        "pdf",
        "spreadsheet",
        "image",
        "thumbnail",
        "infographic",
        "poster",
        "one-pager",
        "visual",
        "deliverable",
        "material",
        "memory",
        "memories",
        "context",
        "contexts",
    }
)
_ROUTE_HINT_RULES = (
    {
        "id": "missed_workflow",
        "workflow": "workflow-learning",
        "lane": "automation_and_status",
        "next_action": "record_missed_route",
        "reason": "The user is reporting that OMH or the expected workflow was not used.",
        "fallback_action": "record_learning_trace_or_show_route_review",
        "phrases": (
            "missed route",
            "missed workflow",
            "did not use omh",
            "omh was not used",
            "omx was not used",
            "not use omh",
            "omh 안 썼어",
            "omh 안 썼",
            "안 썼는데 다음엔",
            "안 썼는데 다음에는",
            "안 쓴 것 같은데 다음엔",
            "안 쓴 것 같은데 다음에는",
            "안 쓴 것 같아",
            "안 쓴 것 같아 다음엔",
            "안 쓴 것 같아 다음에는",
            "안 쓰고 그냥 답했어",
            "안썼는데 다음엔",
            "안썼는데 다음에는",
            "안쓴것같은데다음엔",
            "안쓴것같은데다음에는",
            "안쓴것같아",
            "안쓴것같아다음엔",
            "안쓴것같아다음에는",
            "안쓰고그냥답했어",
            "다음엔 쓰게 해줘",
            "다음에는 쓰게 해줘",
            "다음엔 쓰게 고쳐",
            "다음에는 쓰게 고쳐",
            "다음엔 쓰게 개선",
            "다음에는 쓰게 개선",
            "다음엔 보내줘",
            "다음에는 보내줘",
            "워크플로 누락",
            "라우팅 누락",
            "일반 답변으로 빠져",
            "일반 답변으로 빠짐",
            "omh가 자꾸 일반 답변",
            "omh 기능을 모르는",
            "omh 기능 모르",
            "omh context를 못 보는",
            "omh context 못 보는",
            "omh 컨텍스트를 못 보는",
            "omh 컨텍스트 못 보는",
            "라우터가 잘못 고른",
            "라우터가 잘못 골",
            "지금 omh가 안 쓰여",
            "omh가 안 쓰여",
        ),
        "tokens": ("missed",),
        "adjacent_workflows": ("doctor", "agent-ops-review"),
    },
    {
        "id": "source_finder_candidates",
        "workflow": "source-finder",
        "lane": "research_and_ops",
        "next_action": "prepare_source_finder_plan",
        "reason": "The user is asking for candidate papers, datasets, public repos, presentations, or source links before downstream work.",
        "fallback_action": "ask_for_source_kind_scope_or_downstream_intent",
        "phrases": (
            "find papers datasets github repos and public presentations",
            "find datasets and github repos",
            "datasets and github repos",
            "papers datasets github repos",
            "public presentations about",
            "source candidates",
            "source links",
            "find sources",
            "find paper link",
            "find arxiv link",
            "paper link",
            "arxiv link",
            "dataset search",
            "find datasets",
            "public slide deck",
            "public slides",
            "public slide deck and github repo",
            "public slide deck and github repos",
            "slide deck and github repo",
            "public presentation materials",
            "자료 출처 찾아",
            "자료 출처 찾아줘",
            "자료 출처 찾아서",
            "자료 출처 찾아줘 데이터셋",
            "자료 출처 찾아줘 데이터셋이랑 깃허브",
            "데이터셋이랑 깃허브",
            "데이터셋과 깃허브",
            "논문 링크를 찾아",
            "논문 링크부터 찾아",
            "논문 링크",
            "데이터셋 찾아",
            "데이터셋 찾아서",
            "공개 슬라이드 자료 찾아",
            "공개 슬라이드 자료 찾아서",
            "슬라이드 자료 찾아",
            "슬라이드 자료 찾아서",
            "자료 후보",
            "출처 후보",
            "소스 후보",
        ),
        "tokens": (),
        "adjacent_workflows": ("web-research", "paper-learning", "research-department", "materials-package"),
    },
    {
        "id": "research_to_strategy_brief",
        "workflow": "strategy-brief",
        "lane": "research_and_ops",
        "next_action": "prepare_strategy_brief",
        "reason": "The user wants research or source material turned into a strategy report, memo, or decision brief.",
        "fallback_action": "ask_for_audience_decision_context_or_evidence_scope",
        "phrases": (
            "strategy report",
            "strategy brief",
            "strategy memo",
            "research into a strategy report",
            "turn this research into a strategy report",
            "조사해서 전략 보고서",
            "전략 보고서",
            "전략 리포트",
            "전략 브리프",
            "전략 메모",
        ),
        "tokens": (),
        "adjacent_workflows": ("web-research", "research-brief", "meeting-brief", "report-package"),
    },
    {
        "id": "workflow_improvement_learning",
        "workflow": "workflow-learning",
        "lane": "automation_and_status",
        "next_action": "audit_learning_readiness",
        "reason": "The user wants Hermes or OMH to learn from a workflow attempt before proposing reviewed improvements.",
        "fallback_action": "record_trace_and_prepare_human_review_queue",
        "phrases": (
            "learn from this workflow",
            "improve the skill next time",
            "improve this workflow next time",
            "make this workflow better next time",
            "remember this for next time",
            "remember to do this better next time",
            "make this task better next time",
            "answer better next time",
            "improve this answer next time",
            "fix the skill next time",
            "execution trace skill improvement",
            "execution trace improvement proposal",
            "workflow trace skill improvement",
            "workflow trace 보고",
            "workflow trace 보고 다음에",
            "workflow trace 보고 다음에 스킬",
            "workflow trace 보고 다음에 스킬 고칠",
            "skill improvement proposal",
            "trace 보고 다음에 스킬",
            "trace 보고 스킬 개선",
            "next time do this task better",
            "workflow and improve the skill",
            "workflow learning",
            "same mistake next time",
            "워크플로우 개선",
            "워크플로우를 개선",
            "워크플로우 다음엔 더 잘",
            "워크플로우 다음엔 더 잘하게",
            "워크플로우 다음엔 더 잘하게 개선",
            "다음 실행에서 더 잘",
            "다음 워크플로우에 반영",
            "다음부터 이 작업 더 잘하게",
            "다음부터 이 작업 더 잘하게 기억",
            "다음부터 더 잘하게 기억",
            "다음부터 이런 작업 더 잘하게",
            "이번 실행 trace",
            "이번 실행 trace로 skill 개선",
            "이번 실행 trace로 skill 개선 제안",
            "이번 실행 트레이스",
            "이번 실행 트레이스로 스킬 개선",
            "트레이스 보고 다음에 스킬",
            "트레이스 보고 스킬 개선",
            "실행 기록 보고 다음에 스킬",
            "이 작업 더 잘하게 기억",
            "답변 다음엔 더 잘하게",
            "답변 다음에는 더 잘하게",
            "다음엔 더 잘하게 스킬",
            "스킬 고쳐줘",
            "스킬 개선 제안",
            "skill 개선 제안",
        ),
        "tokens": (),
        "adjacent_workflows": ("agent-ops-review", "doctor"),
    },
    {
        "id": "release_gate_review",
        "workflow": "code-review",
        "lane": "coding_handoff",
        "next_action": "prepare_review_or_followup_handoff",
        "reason": "The user is asking for release-gate or claim-vs-code review before shipping.",
        "fallback_action": "prepare_review_scope_and_verification_commands",
        "phrases": (
            "release gate",
            "before release",
            "readme claim",
            "docs claim",
            "docs claim matches",
            "release docs claim",
            "doctor/harness",
            "claim이 실제 코드",
            "release 전에 docs claim",
            "릴리즈 전에 docs claim",
            "docs claim이 맞는지",
            "docs claim 맞는지",
            "릴리즈 전에",
            "릴리즈 준비 상태",
            "릴리즈 준비 상태 점검",
            "통과하는가 봐줘",
        ),
        "tokens": (),
        "adjacent_workflows": ("reliability-review", "ultraprocess", "workflow-learning"),
    },
    {
        "id": "ai_coding_safety_review",
        "workflow": "code-review",
        "lane": "coding_handoff",
        "next_action": "prepare_review_or_followup_handoff",
        "reason": "The user is asking what an AI coding agent actually did and whether the result is reviewable.",
        "fallback_action": "ask_for_runtime_trace_or_prepare_review_checklist",
        "phrases": (
            "what the ai actually did",
            "what did the ai actually do",
            "ai가 했다고 했는데",
            "실제로 뭐 했는지",
            "실제로 무엇을 했는지",
        ),
        "tokens": (),
        "adjacent_workflows": ("agent-ops-review", "ultraprocess", "workflow-learning"),
    },
    {
        "id": "agent_product_qa",
        "workflow": "ultraqa",
        "lane": "coding_handoff",
        "next_action": "dispatch_to_workflow",
        "reason": "The user is asking for adversarial QA or diagnostic adequacy against a product scenario.",
        "fallback_action": "prepare_qa_scenario_expected_response_and_verification",
        "phrases": (
            "ai agent product qa",
            "kubernetes outage",
            "appropriately diagnose",
            "쿠버네티스 장애",
            "적절히 진단",
            "실제 사용자처럼 qa",
            "qa 시나리오",
        ),
        "tokens": (),
        "adjacent_workflows": ("reliability-review", "code-review", "agent-ops-review"),
    },
    {
        "id": "product_feature_clarification",
        "workflow": "deep-interview",
        "lane": "intent_to_plan",
        "next_action": "answer_clarification",
        "reason": "The user has a fuzzy product improvement goal that needs clarification before planning or coding.",
        "fallback_action": "ask_the_smallest_useful_product_question",
        "phrases": (
            "make onboarding feel smoother",
            "improve our onboarding",
            "don't know where to start",
            "온보딩을 더 부드럽게",
            "부드럽게 만들고 싶어",
        ),
        "tokens": (),
        "adjacent_workflows": ("ralplan", "ultraprocess", "loop"),
    },
    {
        "id": "repeated_refactor_workflow",
        "workflow": "ai-slop-cleaner",
        "lane": "coding_handoff",
        "next_action": "present_plan",
        "reason": "The user is asking to standardize a risky repeated refactor workflow before implementation.",
        "fallback_action": "prepare_behavior_lock_and_refactor_scope",
        "phrases": (
            "repeated refactor workflow",
            "risk analysis, change scope, test strategy",
            "위험 분석, 변경 범위 제한, 테스트 전략",
            "회귀 테스트 순서로 리팩터링",
            "레거시 서비스를",
        ),
        "tokens": (),
        "adjacent_workflows": ("ralplan", "code-review", "ultraprocess"),
    },
    {
        "id": "multi_agent_hub_plan",
        "workflow": "plan",
        "lane": "intent_to_plan",
        "next_action": "present_plan",
        "reason": "The user wants Hermes to decide which work lane should own the next step across multiple agents or gates.",
        "fallback_action": "map_owner_next_action_and_status_boundary",
        "phrases": (
            "multi-agent work hub",
            "Hermes가 답할 차례인지",
            "coding handoff를 준비할 차례인지",
            "review gate를 열 차례인지",
            "답할 차례인지",
        ),
        "tokens": (),
        "adjacent_workflows": ("agent-board", "ultraprocess", "workflow-learning"),
    },
    {
        "id": "agency_operating_template",
        "workflow": "plan",
        "lane": "intent_to_plan",
        "next_action": "present_plan",
        "reason": "The user wants a reusable operating template that spans requirements, research, implementation handoff, QA, review, and release reporting.",
        "fallback_action": "shape_template_lanes_roles_and_artifacts",
        "phrases": (
            "agency operating template",
            "고객사 프로젝트별",
            "운영 템플릿",
            "요구사항 정리, 조사, 구현 handoff",
        ),
        "tokens": (),
        "adjacent_workflows": ("operating-rhythm", "report-package", "ultraprocess"),
    },
    {
        "id": "operating_rhythm_history",
        "workflow": "operating-rhythm",
        "lane": "research_and_ops",
        "next_action": "prepare_operating_record",
        "reason": "The user is asking to turn meetings, scrum, retros, and operating cadence into durable records.",
        "fallback_action": "ask_for_time_window_owners_and_record_destination",
        "phrases": (
            "operating rhythm",
            "scrum sprint retro",
            "회의록 히스토리",
            "스크럼 스프린트 회고",
            "운영 리듬",
        ),
        "tokens": (),
        "adjacent_workflows": ("meeting-brief", "report-package", "strategy-brief"),
    },
    {
        "id": "leadership_report_package",
        "workflow": "report-package",
        "lane": "materials_and_visuals",
        "next_action": "prepare_report_package",
        "reason": "The user is asking for a leadership report or status deck package, not just raw file conversion.",
        "fallback_action": "confirm_audience_sections_and_export_targets",
        "phrases": (
            "ppt report package",
            "monthly leadership status deck",
            "leadership status deck",
            "status deck",
        ),
        "tokens": (),
        "adjacent_workflows": ("materials-package", "img-summary", "operating-rhythm"),
    },
    {
        "id": "materials_revenue_report",
        "workflow": "materials-package",
        "lane": "materials_and_visuals",
        "next_action": "prepare_material_package",
        "reason": "The user is asking to turn a spreadsheet/report source into a PDF or rendered material package.",
        "fallback_action": "confirm_source_file_target_format_and_render_qa",
        "phrases": (
            "revenue spreadsheet into an excel and pdf package",
            "엑셀 매출 리포트를 pdf",
            "매출 리포트를 pdf",
            "렌더 qa",
        ),
        "tokens": (),
        "adjacent_workflows": ("report-package", "deliverable-package", "img-summary"),
    },
    {
        "id": "reliability_incident_review",
        "workflow": "reliability-review",
        "lane": "automation_and_status",
        "next_action": "prepare_reliability_review",
        "reason": "The user is asking for an incident, SLO, error-budget, or reliability review workflow.",
        "fallback_action": "ask_for_incident_window_service_and_health_signals",
        "phrases": (
            "incident postmortem",
            "slo error budget",
            "service reliability review",
            "장애 회고",
        ),
        "tokens": (),
        "adjacent_workflows": ("code-review", "deploy-and-monitor", "ops-observability-card"),
    },
    {
        "id": "idea_to_deploy_loop",
        "workflow": "idea-to-deploy",
        "lane": "coding_handoff",
        "next_action": "present_app_delivery_loop",
        "reason": "The user is asking for an end-to-end product idea delivery loop with safe deployment posture.",
        "fallback_action": "shape_plan_build_deploy_monitor_boundaries",
        "phrases": (
            "idea from plan to deploy",
            "plan to deploy and monitor safely",
            "idea-to-deploy",
        ),
        "tokens": (),
        "adjacent_workflows": ("cto-loop", "deploy-and-monitor", "ultraprocess"),
    },
    {
        "id": "deploy_and_monitor_specific",
        "workflow": "deploy-and-monitor",
        "lane": "coding_handoff",
        "next_action": "prepare_deploy_monitor_plan",
        "reason": "The user is asking for release deployment, rollback, and health monitoring preparation.",
        "fallback_action": "confirm_environment_rollback_and_observed_health_signals",
        "phrases": (
            "deploy and monitor",
            "monitor this release",
        ),
        "tokens": (),
        "adjacent_workflows": ("reliability-review", "ops-observability-card", "code-review"),
    },
    {
        "id": "cto_loop",
        "workflow": "cto-loop",
        "lane": "coding_handoff",
        "next_action": "run_cto_loop",
        "reason": "The user is asking for CTO-style roadmap, architecture, delivery-risk, and release-readiness coordination.",
        "fallback_action": "prepare_cto_pm_dev_qa_security_ops_lanes",
        "phrases": (
            "cto loop",
            "roadmap architecture tradeoffs",
            "delivery risk and release readiness",
        ),
        "tokens": (),
        "adjacent_workflows": ("idea-to-deploy", "deploy-and-monitor", "agent-board"),
    },
    {
        "id": "deploy_and_monitor",
        "workflow": "deploy-and-monitor",
        "lane": "coding_handoff",
        "next_action": "prepare_deploy_monitor_plan",
        "reason": "The user is asking for release deployment, rollback, and health monitoring preparation.",
        "fallback_action": "confirm_environment_rollback_and_observed_health_signals",
        "phrases": (
            "deploy and monitor",
            "monitor this release",
            "rollback and health checks",
        ),
        "tokens": (),
        "adjacent_workflows": ("reliability-review", "ops-observability-card", "code-review"),
    },
    {
        "id": "research_department_ops",
        "workflow": "research-department",
        "lane": "research_and_ops",
        "next_action": "prepare_research_department_plan",
        "reason": "The user is asking for recurring research intake, synthesis, and briefing lanes rather than one-off search.",
        "fallback_action": "ask_for_topics_sources_cadence_and_knowledge_store",
        "phrases": (
            "weekly leadership brief",
            "support tickets, competitor news, and release risks",
            "support tickets competitor news release risks",
            "research department",
            "research department workflow",
            "knowledge store research summary",
            "knowledge storage research summary",
            "notebooklm knowledge store",
            "notebooklm knowledge storage",
            "market news daily briefing",
            "daily market news briefing",
            "리서치 부서",
            "리서치 부서 만들어",
            "시장 뉴스 매일 브리핑",
            "매일 브리핑하도록 리서치",
            "아침마다 시장 리서치",
            "아침마다 리서치 요약",
            "지식저장소 리서치 요약",
            "지식 저장소 리서치 요약",
            "notebooklm이랑 지식저장소",
        ),
        "tokens": (),
        "adjacent_workflows": ("web-research", "report-package", "operating-rhythm"),
    },
    {
        "id": "github_event_ops_delivery",
        "workflow": "github-event-ops",
        "lane": "coding_handoff",
        "next_action": "prepare_github_event_ops_card",
        "reason": "The user is asking to turn GitHub issue/PR events into review, docs, and implementation workflow operations.",
        "fallback_action": "ask_for_event_payload_issue_link_or_observed_thread",
        "phrases": (
            "github issue into a pr",
            "make this github issue into a pr",
            "run review, update docs",
            "github pr",
            "github issue",
            "issue labeling",
            "label issue and prepare pr",
            "이슈 들어오면",
            "새 이슈 들어오면",
            "이슈 라벨링",
            "라벨링하고 PR 준비",
            "PR 준비",
        ),
        "tokens": (),
        "adjacent_workflows": ("ralplan", "ultraprocess", "code-review"),
    },
    {
        "id": "executor_named_coding_delivery",
        "workflow": "ultraprocess",
        "lane": "coding_handoff",
        "next_action": "show_coding_handoff_status",
        "reason": "The user named a coding agent and asked to start or track issue-to-PR implementation work.",
        "fallback_action": "show_prepared_vs_observed_status_or_ask_executor_choice",
        "phrases": (
            "use codex to implement",
            "send to codex",
            "codex로 이 기능 구현",
            "codex로 구현 맡겨",
            "codex로 맡겨",
            "코덱스로 구현",
            "코덱스에게 맡기",
            "코덱스로 맡기",
            "이 이슈를 codex로 구현하게",
            "이 이슈를 codex로 구현하게 맡기고",
            "코덱스로 이 이슈 pr 만들 수 있게 작업 시작",
            "codex로 이 이슈 pr 만들 수 있게 작업 시작",
        ),
        "tokens": (),
        "adjacent_workflows": ("executor-runtime-readiness", "agent-ops-review", "code-review"),
    },
    {
        "id": "executor_runtime_choice",
        "workflow": "executor-runtime-readiness",
        "lane": "coding_handoff",
        "next_action": "prepare_executor_runtime_readiness",
        "reason": "The user is asking which coding agent or runtime path should own the task.",
        "fallback_action": "show_available_executor_capabilities_and_missing_setup",
        "phrases": (
            "should i use codex or claude code",
            "codex or claude code",
            "which coding agent",
            "어떤 코딩 에이전트",
            "codex claude code",
            "open in codex",
            "open in codex button",
            "open in claude code",
            "attach existing codex session",
            "attach existing claude code session",
            "open a codex work session",
            "open a claude code work session",
            "codex 버튼",
            "codex 버튼 어디",
            "codex로 여는 버튼",
            "코덱스 버튼",
            "코덱스 버튼 어디",
            "codex 작업 세션 열어",
            "코덱스 작업 세션 열어",
            "codex로 이 작업 시작",
            "코덱스로 이 작업 시작",
            "codex로 작업 시작",
            "코덱스로 작업 시작",
            "claude code로 이거 열",
            "claude code로 이거 열어서",
            "클로드 코드로 이거 열",
            "클로드 코드로 이거 열어서",
            "claude code로 이 작업 시작",
            "클로드 코드로 이 작업 시작",
            "claude code 작업 세션 열어",
            "클로드 코드 작업 세션 열어",
            "codex 세션 켜",
            "codex 세션 켜서",
            "코덱스 세션 붙여",
            "claude code 세션 붙여",
            "클로드 코드 세션 붙여",
            "코덱스 세션 켜",
            "claude code로 바로 열어",
            "클로드 코드로 바로 열어",
            "hermes가 직접 코딩",
            "hermes한테 직접 코딩",
            "hermes에게 직접 코딩",
            "hermes한테 코딩",
            "hermes에게 코딩",
            "헤르메스가 직접 코딩",
            "헤르메스한테 직접 코딩",
            "헤르메스에게 직접 코딩",
            "헤르메스한테 코딩",
            "헤르메스에게 코딩",
        ),
        "tokens": (),
        "adjacent_workflows": ("ultraprocess", "toolbelt-readiness", "agent-ops-review"),
    },
    {
        "id": "agent_board_collaboration",
        "workflow": "agent-board",
        "lane": "automation_and_status",
        "next_action": "prepare_agent_board_card",
        "reason": "The user is asking for multiple Hermes agents to coordinate through roles, boards, or status lanes.",
        "fallback_action": "prepare_board_states_roles_and_target_topology",
        "phrases": (
            "multi-agent board",
            "Hermes agent 여러 명",
            "여러 Hermes agent",
            "여러 Hermes agent가 같이",
            "같이 일할 board",
            "역할과 보드",
            "여러 명이 같이 일할 때",
        ),
        "tokens": (),
        "adjacent_workflows": ("agent-ops-review", "gateway-intent-card", "operating-rhythm"),
    },
    {
        "id": "gateway_intent_delivery",
        "workflow": "gateway-intent-card",
        "lane": "automation_and_status",
        "next_action": "prepare_gateway_intent_card",
        "reason": "The user is asking for gateway thread, source, delivery, or platform intent policy.",
        "fallback_action": "ask_for_origin_thread_delivery_and_silence_policy",
        "phrases": (
            "route discord slack telegram",
            "discord slack telegram threads",
            "delivery policy",
            "gateway intent",
        ),
        "tokens": (),
        "adjacent_workflows": ("automation-blueprint", "agent-board", "voice-operator"),
    },
    {
        "id": "deliverable_attachment_package",
        "workflow": "deliverable-package",
        "lane": "materials_and_visuals",
        "next_action": "prepare_deliverable_package",
        "reason": "The user is asking to prepare a result as an attachable deliverable package.",
        "fallback_action": "confirm_file_format_channel_and_observed_attachment_step",
        "phrases": (
            "attachable deliverable",
            "file attachment",
            "파일로 만들어서 첨부",
            "첨부할 수 있게",
        ),
        "tokens": (),
        "adjacent_workflows": ("materials-package", "report-package", "img-summary"),
    },
    {
        "id": "voice_operator",
        "workflow": "voice-operator",
        "lane": "automation_and_status",
        "next_action": "prepare_voice_operator_card",
        "reason": "The user is asking how OMH should handle voice-first or short spoken commands.",
        "fallback_action": "prepare_voice_clarify_plan_status_rules",
        "phrases": (
            "voice commands",
            "voice-first",
            "voice operator",
            "음성 명령",
        ),
        "tokens": (),
        "adjacent_workflows": ("gateway-intent-card", "deep-interview", "toolbelt-readiness"),
    },
    {
        "id": "toolbelt_readiness",
        "workflow": "toolbelt-readiness",
        "lane": "automation_and_status",
        "next_action": "prepare_toolbelt_readiness",
        "reason": "The user is asking what MCP, CLI, API, or credentials are needed for a workflow.",
        "fallback_action": "show_required_tools_missing_tools_and_setup_choices",
        "phrases": (
            "mcp setup",
            "help with mcp",
            "toolbelt readiness",
            "external tools",
            "image generator connector",
            "which image generator",
            "image generation tool is missing",
            "image generation failed",
            "fal_key",
            "fal key",
            "tool not attached",
            "image tool not attached",
            "mcp 설정",
            "이미지 생성 연결체",
            "이미지 생성 커넥터",
            "이미지 생성 도구",
            "도구가 안 붙",
            "도구 안 붙",
            "이미지 도구가 안 붙",
            "이미지 도구 연결",
            "이미지 도구 연결 안",
            "이미지 도구 연결 안돼",
            "이미지 도구 연결 안 됐",
            "gpt image 연결",
            "gpt image 연결 안",
            "gpt 이미지 연결",
            "gpt 이미지 연결 안",
            "어떤걸로 연결",
            "어떤 걸로 연결",
            "이미지 생성이 막",
        ),
        "tokens": (),
        "adjacent_workflows": ("executor-runtime-readiness", "automation-blueprint", "doctor"),
    },
    {
        "id": "ops_observability",
        "workflow": "ops-observability-card",
        "lane": "automation_and_status",
        "next_action": "prepare_ops_observability_card",
        "reason": "The user is asking for cost, token, latency, run-history, or runtime observability status.",
        "fallback_action": "prepare_observability_card_with_observed_only_metrics",
        "phrases": (
            "token cost latency run history",
            "cost latency run history",
            "runtime observability",
            "ops observability",
            "loop cost",
            "latency status",
            "루프 비용",
            "지연시간 상태",
            "비용이랑 지연시간",
            "omh가 너무 느려",
            "omh 너무 느려",
            "omh가 느려",
            "omh 느려",
            "omh routing is slow",
            "slow omh routing",
            "hermes omh response takes too long",
            "hermes에서 omh 답변이 오래",
            "omh 답변이 오래",
            "omh 라우팅이 느려",
            "라우팅이 느려",
            "라우터가 느려",
            "응답 지연시간",
            "토큰을 너무 많이",
            "토큰 너무 많이",
            "비용이 많이",
            "비용 많이",
            "비용 확인",
        ),
        "tokens": (),
        "adjacent_workflows": ("automation-blueprint", "loop", "agent-ops-review"),
    },
    {
        "id": "achievements_badges",
        "workflow": "achievements",
        "lane": "automation_and_status",
        "next_action": "show_achievements_summary",
        "reason": "The user is asking about unlocked achievements, badges, tiers, or badge progress.",
        "fallback_action": "show_achievements_summary_from_observed_artifacts_only",
        "phrases": (
            "my achievements",
            "show achievements",
            "achievement summary",
            "unlocked badges",
            "my badges",
            "badge progress",
            "achievement tier",
            "recent unlocks",
            "내 업적",
            "업적 보여",
            "업적 요약",
            "배지 보여",
            "내 배지",
            "배지 진행",
            "뱃지 보여",
            "도전과제 보여",
            "実績を見せて",
            "バッジを見せて",
            "我的成就",
            "我的徽章",
        ),
        "tokens": (),
        "adjacent_workflows": ("ops-observability-card", "agent-ops-review", "report-package"),
    },
    {
        "id": "agent_ops_quality_review",
        "workflow": "agent-ops-review",
        "lane": "automation_and_status",
        "next_action": "show_agent_ops_review",
        "reason": "The user is asking to inspect AI-agent search, coding, quality, or productivity from an operations manager perspective.",
        "fallback_action": "prepare_quality_performance_and_usability_review",
        "phrases": (
            "agent ops review",
            "third-party manager",
            "제3자 관리자",
            "AI agent 서치및 코딩 품질",
            "품질을 제3자",
        ),
        "tokens": (),
        "adjacent_workflows": ("workflow-learning", "ultraprocess", "ops-observability-card"),
    },
    {
        "id": "agent_ops_status_surface",
        "workflow": "agent-ops-review",
        "lane": "automation_and_status",
        "next_action": "show_agent_ops_review",
        "reason": "The user is asking to reopen or inspect the OMH HUD/menu bar/status surface.",
        "fallback_action": "show_status_surface_or_next_repair_action",
        "phrases": (
            "start the omh menubar",
            "restart the omh menubar",
            "start the omh menu bar",
            "restart the omh menu bar",
            "start omh hud",
            "restart omh hud",
            "show the omh menu bar",
            "show the omh menubar",
            "omh menu bar icon is missing",
            "omh menubar icon is missing",
            "상단바 hud 다시 켜",
            "상단바 hud 다시 키",
            "상단바 omh 아이콘 안 보여",
            "상단바 아이콘 안 보여",
            "메뉴바 모니터 다시 켜",
            "메뉴바 모니터 다시 키",
            "메뉴바 모니터링 다시 띄",
            "메뉴바 다시 켜",
            "메뉴바 다시 키",
        ),
        "tokens": (),
        "adjacent_workflows": ("doctor", "ops-observability-card", "toolbelt-readiness"),
    },
    {
        "id": "agent_ops_status_question",
        "workflow": "agent-ops-review",
        "lane": "automation_and_status",
        "next_action": "refresh_agent_ops_status",
        "reason": "The user is asking a short status/progress question, so Hermes should show the agent-ops status instead of asking for workflow clarification.",
        "fallback_action": "show_status_surface_or_next_repair_action",
        "phrases": (
            "what are you doing",
            "what are you doing now",
            "what is going on",
            "what is going on rn",
            "status update please",
            "did ci pass",
            "ci passed",
            "ci status",
            "did the pr merge",
            "is the pr merged",
            "is this ready to ship",
            "is this ready to release",
            "current pr review status",
            "did the current pr review pass",
            "지금 뭐함",
            "뭐하고있어",
            "뭐 하는중이야",
            "작업상황 보고",
            "진행중인거 뭐야",
            "현재 작업 뭐야",
            "세션 상태",
            "세션 상태 보여줘",
            "내가 뭘 하고 있었는지",
            "내가 뭘 하고 있었는지 알려줘",
            "현재 상태 브리핑",
            "현재 PR 리뷰 상태",
            "현재 PR 리뷰 통과",
            "PR 머지됐는지",
            "CI 통과했어",
            "CI 상태",
            "기능 배포 준비됐어",
            "이 기능 배포 준비됐어",
            "배포 준비됐어",
            "릴리즈 준비됐어",
            "어디까지 했노",
            "어디까지 됐노",
        ),
        "tokens": (),
        "adjacent_workflows": ("doctor", "ops-observability-card", "workflow-learning"),
    },
    {
        "id": "memory_curation",
        "workflow": "memory-curation-review",
        "lane": "automation_and_status",
        "next_action": "prepare_memory_curation_review",
        "reason": "The user is asking to inspect, update, or clean Hermes memory or accumulated context.",
        "fallback_action": "show_memory_review_before_writing",
        "phrases": (
            "memory review",
            "memory inspect",
            "memory check",
            "memory update",
            "context review",
            "context cleanup",
            "hermes remembers",
            "hermes가 기억하는 내용",
            "헤르메스가 기억하는 내용",
            "기억하는 내용 점검",
            "메모리 업데이트",
            "메모리 검사",
            "메모리 점검",
            "메모리가 쌓",
            "메모리가 너무 쌓",
            "메모리 너무 쌓",
            "메모리가 쌓였",
            "메모리 뭐가 저장",
            "메모리 뭐 저장",
            "내 메모리 뭐가 저장",
            "내 기억 뭐가 저장",
            "내 기억에 뭐 저장",
            "내 기억에 뭐가 저장",
            "메모리에 뭐가 저장",
            "기억에 뭐가 저장",
            "저장되어있는지 점검",
            "저장되어 있는지 점검",
            "저장돼있는지 점검",
            "저장돼 있는지 점검",
            "저장되어있는지 검토",
            "저장되어 있는지 검토",
            "저장돼있는지 검토",
            "저장돼 있는지 검토",
            "기억하는 맥락",
            "기억하고 있는",
            "헤르메스가 기억하는 맥락",
            "맥락 점검",
            "맥락 피드백",
        ),
        "tokens": ("memory", "memories", "context"),
        "adjacent_workflows": ("workflow-learning", "doctor"),
    },
    {
        "id": "doctor_health",
        "workflow": "doctor",
        "lane": "automation_and_status",
        "next_action": "run_local_operator_check",
        "reason": "The user is asking whether OMH install, setup, update, or skill registration health looks correct.",
        "fallback_action": "run_doctor_or_show_next_repair_step",
        "phrases": (
            "after omh update",
            "omh update says setup",
            "setup is next",
            "skills still look stale",
            "skills look stale",
            "update version unchanged",
            "version unchanged after update",
            "did update work",
            "update ok",
            "update worked",
            "update 잘 됐",
            "update 잘됐",
            "update 했는데 잘",
            "update 했는데 제대로",
            "update 했는데 버전이 그대로",
            "update 제대로 반영",
            "update 잘 된 거야",
            "update 잘된 거야",
            "update 잘 된거야",
            "update 잘된거야",
            "업데이트 잘 됐",
            "업데이트 잘됐",
            "업데이트 했는데 잘",
            "업데이트 했는데 버전이 그대로",
            "업데이트했는데 버전이 그대로",
            "업데이트 제대로",
            "업데이트가 제대로",
            "제대로 반영",
            "hermes에서 omh가 안 보여",
            "hermes에서 omh 안 보여",
            "hermes에서 omh가 안보여",
            "hermes에서 omh 안보여",
            "omh가 안 보여",
            "omh 안 보여",
            "omh가 안보여",
            "omh 안보여",
            "setup slow",
            "setup feels slow",
            "setup arrow key",
            "setup에서 화살표",
            "셋업에서 화살표",
            "화살표 누르면 느려",
            "setup에서 위아래키",
            "위아래키 누르면 느려",
            "설치 잘 됐",
            "설치가 제대로 됐",
            "설치가 제대로 되었",
            "설치 제대로 됐",
            "설치 제대로 되었",
            "설치가 제대로 반영",
            "설정 잘 됐",
            "설정 잘됐",
            "세팅 잘 됐",
            "세팅 잘됐",
            "setup 다시 해야",
            "셋업 다시 해야",
            "설정 다시 해야",
            "setup 잘 됐",
            "setup 잘됐",
            "setup이 잘 됐",
            "setup이 잘됐",
            "setup 됐는지",
            "setup 확인",
            "잘 된 거야",
            "잘된 거야",
            "잘 된거야",
            "잘된거야",
            "버전이 그대로야",
            "버전 그대로야",
        ),
        "tokens": ("doctor",),
        "adjacent_workflows": ("agent-ops-review", "toolbelt-readiness"),
    },
    {
        "id": "omh_workflow_picker",
        "workflow": "oh-my-hermes",
        "lane": "intent_to_plan",
        "next_action": "choose_skill",
        "reason": "The user is asking to open the OMH workflow picker or menu instead of selecting a specific workflow yet.",
        "fallback_action": "show_workflow_picker_or_open_command_preview",
        "phrases": (
            "open the omh picker",
            "open omh picker",
            "open the omh workflow picker",
            "open omh workflow picker",
            "show the omh menu",
            "show omh menu",
            "open the oh-my-hermes picker",
            "open oh-my-hermes picker",
            "show the oh-my-hermes menu",
            "show oh-my-hermes menu",
        ),
        "tokens": (),
        "adjacent_workflows": ("deep-interview", "ralplan", "loop", "ultraprocess"),
    },
    {
        "id": "hermes_coding_team_path",
        "workflow": "team",
        "lane": "coding_handoff",
        "next_action": "show_runtime_handoff",
        "reason": "The user wants Hermes itself to own a coding team, worker, or worktree-shaped runtime path.",
        "fallback_action": "prepare_runtime_handoff_or_ask_coding_owner",
        "phrases": (
            "hermes coding team",
            "hermes itself code with workers",
            "let hermes itself code",
            "hermes workers and worktrees",
            "hermes만으로 코딩팀",
            "hermes만으로 코딩 팀",
            "hermes 만으로 코딩팀",
            "hermes 만으로 코딩 팀",
            "헤르메스만으로 코딩팀",
            "헤르메스만으로 코딩 팀",
            "헤르메스 만으로 코딩팀",
            "헤르메스 만으로 코딩 팀",
            "헤르메스가 직접 코딩팀",
            "헤르메스가 직접 코딩 팀",
        ),
        "tokens": (),
        "adjacent_workflows": ("ultraprocess", "executor-runtime-readiness", "agent-ops-review"),
    },
    {
        "id": "coding_progress_status",
        "workflow": "ultraprocess",
        "lane": "coding_handoff",
        "next_action": "show_coding_handoff_status",
        "reason": "The user is asking where a coding handoff, coding agent, or implementation session currently stands.",
        "fallback_action": "show_prepared_vs_observed_status_or_ask_executor_choice",
        "phrases": (
            "coding handoff status",
            "coding handoff progress",
            "coding work status",
            "coding work progress",
            "what is the coding handoff status",
            "codex progress",
            "codex status",
            "codex session running",
            "is codex session running",
            "codex session is running",
            "is codex session alive",
            "check codex session liveness",
            "claude code status",
            "claude code session status",
            "claude session status",
            "is codex done",
            "claude code work done",
            "claude code task done",
            "claude code completed",
            "did the coding agent finish",
            "the coding agent was dispatched",
            "coding agent was dispatched",
            "what happened next",
            "what is codex doing",
            "what is codex doing now",
            "what is claude code doing",
            "what is claude code doing now",
            "코딩 작업 어디까지",
            "코딩 작업 지금 어디까지",
            "코딩 작업 진행상황",
            "코딩 작업 상태",
            "codex 작업 어디까지",
            "codex 작업이 어디까지",
            "codex가 지금 뭐",
            "codex 지금 뭐",
            "codex가 뭐하고",
            "codex 뭐하고",
            "codex 세션 실행 중",
            "codex 세션 지금 실행 중",
            "codex 세션 살아있는지",
            "codex 세션이 살아있는지",
            "codex 세션 붙여서 상태",
            "코덱스 작업 어디까지",
            "코덱스 작업이 어디까지",
            "코덱스가 지금 어디까지",
            "코덱스 지금 어디까지",
            "코덱스가 지금 뭐",
            "코덱스 지금 뭐",
            "코덱스가 뭐하고",
            "코덱스가 뭐 하고",
            "코덱스 뭐하고",
            "코덱스 뭐 하고",
            "코덱스 세션 실행 중",
            "코덱스 세션 지금 실행 중",
            "코덱스 세션 살아있는지",
            "코덱스 세션이 살아있는지",
            "코덱스 세션 붙여서 상태",
            "코덱스 진행상황",
            "코덱스 상태",
            "claude code가 지금 어디까지",
            "claude code가 지금 뭐",
            "claude code 지금 뭐",
            "claude code가 뭐하고",
            "claude code 작업 어디까지",
            "claude code 작업이 어디까지",
            "claude code 작업 완료",
            "claude code 완료",
            "claude code 진행상황",
            "claude code 상태",
            "클로드 코드가 지금 어디까지",
            "클로드 코드가 지금 뭐",
            "클로드 코드 지금 뭐",
            "클로드 코드가 뭐하고",
            "클로드 코드가 뭐 하고",
            "클로드 코드 뭐하고",
            "클로드 코드 뭐 하고",
            "클로드 코드 작업 어디까지",
            "클로드 코드 작업이 어디까지",
            "클로드 코드 작업 완료",
            "클로드 코드 완료",
            "클로드 코드 진행상황",
            "클로드 코드 세션 상태",
            "codex 작업이 진행중인지",
            "코덱스 작업이 진행중인지",
            "PR 머지 준비",
            "머지 준비 됐는지",
            "머지 준비 상태",
            "PR 머지됐는지",
            "CI 통과했어",
            "CI 통과했는지",
            "CI 상태",
        ),
        "tokens": (),
        "adjacent_workflows": ("agent-ops-review", "executor-runtime-readiness", "workflow-learning"),
    },
    {
        "id": "safe_feature_plan",
        "workflow": "ralplan",
        "lane": "intent_to_plan",
        "next_action": "present_plan",
        "reason": "The user is asking to safely add or change a feature, so Hermes should plan before implementation handoff.",
        "fallback_action": "ask_scope_acceptance_criteria_or_risk_boundary",
        "phrases": (
            "safely add a feature",
            "add a feature safely",
            "safe feature",
            "safe feature change",
            "안전하게 기능",
            "안전한 기능",
            "기능 안전하게",
        ),
        "tokens": (),
        "adjacent_workflows": ("deep-interview", "ultraprocess", "code-review"),
    },
    {
        "id": "risky_refactor_plan",
        "workflow": "ralplan",
        "lane": "intent_to_plan",
        "next_action": "present_plan",
        "reason": "The user is describing a risky refactor, so Hermes should plan and bound verification before cleanup or coding.",
        "fallback_action": "ask_for_refactor_scope_and_regression_signal",
        "phrases": (
            "risky refactor",
            "risky refactoring",
            "dangerous refactor",
            "dangerous refactoring",
            "위험한 리팩터링",
            "위험한 refactor",
            "위험한 리팩토링",
        ),
        "tokens": (),
        "adjacent_workflows": ("code-review", "ai-slop-cleaner", "ultraprocess"),
    },
    {
        "id": "issue_to_pr_plan",
        "workflow": "github-event-ops",
        "lane": "coding_handoff",
        "next_action": "prepare_github_event_ops_card",
        "reason": "The user wants an issue shaped into PR-ready scope, acceptance criteria, and verification before implementation.",
        "fallback_action": "ask_for_issue_link_or_observed_issue_text",
        "phrases": (
            "issue to pr",
            "issue into a pr",
            "turn this issue into a pr",
            "make this issue into a pr",
            "prepare this issue for pr",
            "이슈 pr",
            "이슈를 pr",
            "이슈 pr로",
            "pr로 만들",
            "pr로 만들 수",
            "pr로 만들 수 있게",
        ),
        "tokens": (),
        "adjacent_workflows": ("ralplan", "ultraprocess", "code-review"),
    },
    {
        "id": "loopability_goal",
        "workflow": "loop",
        "lane": "intent_to_plan",
        "next_action": "assess_loopability",
        "reason": "The user is invoking or describing a loopable goal that should be classified before repeated cycles start.",
        "fallback_action": "ask_for_north_star_arena_problem_and_stop_signal",
        "phrases": (
            "./loop",
            "/loop",
            "run a loop",
            "run loop",
            "start a loop",
            "start loop",
            "goal loop",
            "loop to improve",
            "keep looping",
            "loop engineering",
            "loopable",
            "loopability",
            "loop로 돌릴만",
            "loop로 해야",
            "loop로 해야해",
            "loop로 해야 해",
            "first run",
            "first run을 계속 개선",
            "설치 후 첫 성공",
            "첫 성공까지",
            "막히는 부분을 계속 개선",
            "계속 개선",
            "계속해서 개선",
            "star-worthy",
            "star worthy",
            "100k star",
            "10k star",
            "star oss",
            "star급",
            "스타급",
            "스타 oss",
            "north star",
            "루프",
            "루프로 돌릴만",
            "루프로 해야",
        ),
        "tokens": (),
        "adjacent_workflows": ("ultragoal", "ultraprocess", "workflow-learning"),
    },
    {
        "id": "visual_summary",
        "workflow": "img-summary",
        "lane": "materials_and_visuals",
        "next_action": "prepare_visual_prompt_card",
        "reason": "The user is asking for an image card, infographic, poster, or shareable visual summary.",
        "fallback_action": "choose_image_generator_or_prompt_only_when_missing",
        "phrases": (
            "image card",
            "summary card",
            "thumbnail",
            "release thumbnail",
            "infographic",
            "poster",
            "visual one-pager",
            "shareable visual",
            "generate image",
            "image summary",
            "pretty image",
            "haz una imagen",
            "hacer una imagen",
            "crea una imagen",
            "imagen que explique",
            "imagen explicando",
            "infografía",
            "infografia",
            "erstelle ein bild",
            "mach ein bild",
            "bild das",
            "bild, das",
            "infografik",
            "이미지",
            "사진",
            "예쁜 이미지",
            "예쁜 이미지로",
            "회의록 예쁜 이미지",
            "회의록을 예쁜 이미지",
            "사진처럼",
            "설명 사진",
            "요약 사진",
            "썸네일",
            "릴리즈 노트 썸네일",
            "크론 기능 설명 사진",
            "기능 소개 이미지",
            "기능 설명 이미지",
            "OMH 루프 기능 소개 이미지",
            "omh 루프 기능 소개 이미지",
            "루프 기능 소개 이미지",
            "pr 요약 사진",
            "pr 리뷰어용 이미지 카드",
            "github pr 리뷰어용 이미지 카드",
            "깃허브 pr 리뷰어용 이미지 카드",
            "릴리즈 노트 이미지",
            "릴리즈 노트 이미지로",
            "릴리즈 노트 카드",
            "릴리즈 노트 발표 카드",
            "릴리즈 노트를 announcement 카드",
            "릴리즈 노트 announcement 카드",
            "릴리즈 업데이트 announcement 카드",
            "릴리즈 업데이트 발표 카드",
            "릴리즈 업데이트를 발표 카드",
            "릴리즈 업데이트를 발표 카드로",
            "업데이트 요약 이미지",
            "업데이트 요약 카드",
            "발표 카드",
            "카드뉴스",
            "카드 뉴스",
            "인스타 카드뉴스",
            "인스타 카드뉴스처럼",
            "포스터",
            "요약 카드",
            "공유용 카드",
            "画像",
            "画像を作って",
            "画像で説明",
            "説明する画像",
            "要約画像",
            "图片",
            "圖像",
            "图像",
            "説明圖片",
            "说明图片",
            "摘要图片",
            "摘要圖片",
            "信息图",
            "資訊圖",
            "海报",
            "海報",
        ),
        "tokens": ("image", "infographic", "poster", "visual", "imagen", "bild", "infografik"),
        "adjacent_workflows": ("materials-package", "report-package"),
    },
    {
        "id": "customer_signal",
        "workflow": "feedback-triage",
        "lane": "research_and_ops",
        "next_action": "triage_feedback",
        "reason": "The user is describing customer feedback, bugs, issues, or product signals that need triage before implementation.",
        "fallback_action": "ask_for_examples_or_prepare_repro_plan",
        "phrases": (
            "customer feedback",
            "payment failure",
            "payment failures",
            "bug report",
            "issue triage",
            "user feedback",
            "결제 실패",
            "고객 피드백",
            "버그",
            "이슈",
            "피드백",
        ),
        "tokens": ("feedback", "bug", "issue", "triage"),
        "adjacent_workflows": ("web-research", "github-event-ops", "coding handoff"),
    },
    {
        "id": "scheduled_ops",
        "workflow": "automation-blueprint",
        "lane": "automation_and_status",
        "next_action": "prepare_scheduled_ops_blueprint",
        "reason": "The user is asking for recurring, scheduled, cron-like, or digest-style work.",
        "fallback_action": "confirm_schedule_delivery_and_tools",
        "phrases": (
            "every morning",
            "every day",
            "daily digest",
            "weekly digest",
            "automate this",
            "automate workflow",
            "cron",
            "scheduled",
            "recurring",
            "매일",
            "아침마다",
            "매주",
            "자동화",
            "자동화해줘",
            "자동화하는 흐름",
            "스케줄",
        ),
        "tokens": ("cron", "schedule", "scheduled", "recurring", "digest"),
        "adjacent_workflows": ("research-department", "ops-observability-card"),
    },
    {
        "id": "source_finder",
        "workflow": "source-finder",
        "lane": "research_and_ops",
        "next_action": "prepare_source_finder_plan",
        "reason": "The user is asking Hermes to find, classify, or intake source candidates before downstream learning, research, materials, or coding work.",
        "fallback_action": "ask_for_source_kind_scope_or_downstream_intent",
        "phrases": (
            "source finder",
            "source candidates",
            "source candidate",
            "source links",
            "source material",
            "find sources",
            "find source candidates",
            "find paper pdf",
            "find arxiv link",
            "find arxiv paper link",
            "find paper link",
            "paper pdf link",
            "paper link",
            "arxiv link",
            "pdf link",
            "dataset link",
            "dataset links",
            "dataset search",
            "public dataset",
            "public datasets",
            "public presentation",
            "public presentations",
            "public slide deck",
            "public slides",
            "public slide deck and github repo",
            "slide deck and github repo",
            "presentation materials",
            "public presentation materials",
            "github repo 찾아",
            "github repo 찾아줘",
            "arxiv 링크",
            "arxiv 링크 찾아",
            "arxiv 논문 링크",
            "arxiv 논문 링크 찾아",
            "논문 링크를 찾아",
            "논문 링크부터 찾아",
            "github oss",
            "github oss repo",
            "github oss repos",
            "open source repo",
            "open source repos",
            "자료 후보",
            "출처 후보",
            "소스 후보",
            "논문 pdf 찾아",
            "논문 pdf 찾아서",
            "논문 pdf 어디서 찾아",
            "논문 링크 찾아",
            "논문 링크 찾아서",
            "논문 링크",
            "논문 pdf 링크",
            "논문 pdf 링크 찾아",
            "pdf 링크",
            "pdf 찾아",
            "pdf 찾아서",
            "데이터셋 링크",
            "데이터셋 찾아",
            "데이터셋 찾아서",
            "공개 데이터셋",
            "공개된 프레젠테이션 자료",
            "공개 슬라이드 자료 찾아",
            "공개 슬라이드 자료 찾아서",
            "공개 프레젠테이션 자료",
            "공개 발표자료 찾아",
            "공개 발표자료 찾아서",
            "슬라이드 자료 찾아",
            "슬라이드 자료 찾아서",
            "프레젠테이션 자료",
            "발표자료 찾아",
            "발표자료 찾아서",
            "깃허브 oss",
            "오픈소스 저장소",
            "레포 찾아",
            "저장소 찾아",
        ),
        "tokens": ("dataset", "datasets"),
        "adjacent_workflows": ("web-research", "paper-learning", "research-department", "materials-package"),
    },
    {
        "id": "materials_package",
        "workflow": "materials-package",
        "lane": "materials_and_visuals",
        "next_action": "prepare_material_package",
        "reason": "The user is asking Hermes to prepare, convert, package, or QA files such as PDFs, decks, spreadsheets, docs, or upload-ready materials.",
        "fallback_action": "confirm_target_format_and_generator",
        "phrases": (
            "materials package",
            "material package",
            "file package",
            "pdf to ppt",
            "pdf into ppt",
            "pdf to presentation",
            "pdf into presentation",
            "convert pdf to presentation",
            "turn pdf into presentation",
            "convert pdf to deck",
            "pdf and excel file",
            "convierte este pdf",
            "pdf en una presentación",
            "pdf en una presentacion",
            "transforme ce pdf",
            "pdf en présentation",
            "pdf en presentation",
            "pdf und excel datei",
            "pdf를 ppt",
            "pdf를 ppt로",
            "ppt 만들어",
            "meeting notes to slides",
            "발표자료",
            "발표 자료",
            "회의록을 발표자료",
            "회의록을 발표 자료",
            "발표자료로 만들어",
            "엑셀 파일",
            "자료 패키지",
        ),
        "tokens": ("ppt", "pptx", "spreadsheet", "excel", "xlsx", "deck", "slides", "presentacion", "datei"),
        "adjacent_workflows": ("report-package", "deliverable-package", "paper-learning", "img-summary"),
    },
    {
        "id": "paper_learning",
        "workflow": "paper-learning",
        "lane": "research_and_ops",
        "next_action": "prepare_paper_learning",
        "reason": "The user is asking Hermes to explain a supplied paper or paper PDF at a chosen difficulty without dropping coverage.",
        "fallback_action": "choose_level_or_request_observed_paper_text",
        "phrases": (
            "paper learning",
            "paper explanation",
            "explain this paper",
            "explain this arxiv paper",
            "paper walkthrough",
            "pdf paper explain",
            "without dropping details",
            "attached paper",
            "attached paper at beginner level",
            "attached paper easy",
            "논문 설명",
            "논문 해설",
            "논문 쉽게 설명",
            "논문 전문가급",
            "첨부한 논문",
            "첨부한 논문을",
            "논문을 초보자",
            "논문을 초보자 수준",
            "논문을 초보자 수준으로",
            "논문을 풀어",
        ),
        "tokens": ("paper", "arxiv", "pdf", "explain", "expert", "논문", "설명", "해설"),
        "adjacent_workflows": ("web-research", "research-department", "materials-package"),
    },
    {
        "id": "source_research",
        "workflow": "web-research",
        "lane": "research_and_ops",
        "next_action": "run_hermes_research",
        "reason": "The user is asking for current, source-backed, market, competitor, paper, or news research.",
        "fallback_action": "ask_for_scope_or_source_constraints",
        "phrases": (
            "web search",
            "web research",
            "best practice",
            "competitor",
            "market research",
            "latest news",
            "source-backed",
            "latest materials",
            "latest sources",
            "paper",
            "논문",
            "리서치",
            "웹서치",
            "웹 검색",
            "최신 자료",
            "최신 자료 정리",
            "검색",
            "시장 조사",
            "경쟁사",
        ),
        "tokens": ("research", "sources", "competitor", "market", "paper", "news"),
        "adjacent_workflows": ("research-brief", "research-department", "strategy-brief"),
    },
    {
        "id": "test_until_pass_delivery",
        "workflow": "ultraprocess",
        "lane": "coding_handoff",
        "next_action": "choose_executor",
        "reason": "The user gave a coding task with tests as the stop signal, so Hermes should choose the coding owner for one bounded delivery cycle.",
        "fallback_action": "choose_coding_agent_or_runtime",
        "phrases": (
            "fix until tests pass",
            "keep fixing until tests pass",
            "test passes",
            "tests pass",
            "until tests pass",
            "테스트 통과할때까지 고쳐",
            "테스트 통과할 때까지 고쳐",
            "통과할때까지 고쳐",
            "통과할 때까지 고쳐",
        ),
        "tokens": (),
        "adjacent_workflows": ("code-review", "executor-runtime-readiness", "agent-ops-review"),
    },
    {
        "id": "setup_output_improvement",
        "workflow": "ultraprocess",
        "lane": "coding_handoff",
        "next_action": "answer_clarification",
        "reason": "The user is asking to improve OMH setup logs or terminal output, which needs a scoped one-cycle implementation path after clarification.",
        "fallback_action": "ask_which_setup_surface_or_log_output_to_improve",
        "phrases": (
            "setup log",
            "setup logs",
            "setup output",
            "setup ux",
            "setup 로그",
            "setup 출력",
            "셋업 로그",
            "셋업 출력",
            "로그가 너무 어렵",
            "출력이 너무 어렵",
        ),
        "tokens": (),
        "adjacent_workflows": ("doctor", "toolbelt-readiness", "agent-ops-review"),
    },
    {
        "id": "coding_delivery",
        "workflow": "ultraprocess",
        "lane": "coding_handoff",
        "next_action": "prepare_one_cycle_delivery",
        "reason": "The user is asking for coding delivery, PR preparation, implementation, review, CI, or merge-oriented work.",
        "fallback_action": "choose_coding_agent_or_runtime",
        "phrases": (
            "pull request",
            "code review",
            "ci failed",
            "merge this",
            "implement",
            "coding agent",
            "codex",
            "claude code",
            "fix until tests pass",
            "keep fixing until tests pass",
            "pr 올려",
            "머지",
            "코딩",
            "구현",
            "리뷰",
            "테스트 통과할때까지 고쳐",
            "테스트 통과할 때까지 고쳐",
            "통과할때까지 고쳐",
            "통과할 때까지 고쳐",
        ),
        "tokens": ("pr", "implementation", "implement", "review", "ci", "merge", "codex", "claude"),
        "adjacent_workflows": ("ralplan", "code-review", "agent-ops-review"),
    },
)


def router_keyword_summary() -> str:
    """Return representative workflow keywords for router/snippet guidance."""
    return ", ".join(f"`{skill}`" for skill in ROUTER_KEYWORD_SKILLS)


def awareness_lane_examples(lane_id: str) -> list[str]:
    """Return compact examples relevant to one OMH awareness lane."""
    return list(LANE_CROSS_LANE_EXAMPLES.get(lane_id, []))


def workflow_context_cards() -> list[dict[str, object]]:
    """Return compact workflow cards that teach Hermes when OMH should help."""
    return [
        {
            "id": card["id"],
            "label": card["label"],
            "user_signal": card["user_signal"],
            "omh_pattern": card["omh_pattern"],
            "representative_workflows": list(card["representative_workflows"]),
            "user_examples": list(card["user_examples"]),
            "first_response_shape": card["first_response_shape"],
            "not_evidence_until_observed": list(card["not_evidence_until_observed"]),
        }
        for card in WORKFLOW_CONTEXT_CARDS
    ]


def workflow_context_card_for_workflow(workflow: str) -> dict[str, object]:
    """Return the OMH pattern card that should frame one selected workflow."""
    workflow_key = workflow.strip().casefold()
    card_id = _WORKFLOW_CONTEXT_CARD_BY_WORKFLOW.get(workflow_key, "")
    if not card_id:
        for card in WORKFLOW_CONTEXT_CARDS:
            representative_workflows = {str(item).casefold() for item in card["representative_workflows"]}
            if workflow_key in representative_workflows:
                card_id = str(card["id"])
                break
    if not card_id:
        return {}
    for card in workflow_context_cards():
        if card["id"] == card_id:
            return card
    return {}


def awareness_context_matches_message(message: str) -> bool:
    """Return true when a non-first-turn message should refresh OMH context."""
    return _awareness_context_matches_message_cached(message)


@lru_cache(maxsize=512)
def _awareness_context_matches_message_cached(message: str) -> bool:
    raw_text = unicodedata.normalize("NFKC", message).casefold()
    if not raw_text.strip():
        return False
    localized_text = unicodedata.normalize("NFKC", _localized_routing_text(message)).casefold()
    text = f"{raw_text} {localized_text}"
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]*", text))
    return bool(tokens & _AWARENESS_TOKEN_MARKERS) or any(
        marker in text for marker in _AWARENESS_MESSAGE_MARKERS
    )


def awareness_route_hint(message: str, *, max_hints: int = 2) -> dict[str, object]:
    """Return bounded message-specific workflow hints without exposing raw text."""
    return _copy_awareness_route_hint_payload(_awareness_route_hint_cached(message, max(max_hints, 0)))


def _copy_awareness_route_hint_payload(payload: dict[str, object]) -> dict[str, object]:
    """Copy the bounded route-hint shape without paying for generic deepcopy."""
    copied = dict(payload)
    for key in ("mentioned_workflows", "mentioned_runtime_terms", "adjacent_workflows", "not_executed"):
        values = payload.get(key, [])
        copied[key] = list(values) if isinstance(values, list | tuple) else []

    hints = payload.get("hints", [])
    copied["hints"] = [
        _copy_route_hint_item(hint) if isinstance(hint, dict) else hint
        for hint in (hints if isinstance(hints, list) else [])
    ]

    privacy = payload.get("privacy")
    if isinstance(privacy, dict):
        copied_privacy = dict(privacy)
        stored_fields = privacy.get("stored_fields", [])
        copied_privacy["stored_fields"] = (
            list(stored_fields) if isinstance(stored_fields, list | tuple) else []
        )
        copied["privacy"] = copied_privacy
    return copied


def _copy_route_hint_item(hint: dict[str, object]) -> dict[str, object]:
    copied = dict(hint)
    for key in ("matched_cues", "adjacent_workflows", "not_evidence_yet"):
        values = hint.get(key, [])
        copied[key] = list(values) if isinstance(values, list | tuple) else []
    context_card = hint.get("workflow_context_card")
    copied["workflow_context_card"] = (
        _copy_workflow_context_card(context_card) if isinstance(context_card, dict) else context_card
    )
    return copied


def _copy_workflow_context_card(card: dict[str, object]) -> dict[str, object]:
    copied = dict(card)
    for key in ("representative_workflows", "user_examples", "not_evidence_until_observed"):
        values = card.get(key, [])
        copied[key] = list(values) if isinstance(values, list | tuple) else []
    return copied


def _route_hint_with_action_labels(hint: dict[str, object]) -> dict[str, object]:
    copied = dict(hint)
    next_action = str(copied.get("next_action") or copied.get("primary_next_action") or "").strip()
    if next_action:
        copied.setdefault("next_action_label", _next_action_label(next_action))
    fallback_action = str(copied.get("fallback_action") or "").strip()
    if fallback_action:
        copied.setdefault("fallback_action_label", _next_action_label(fallback_action))
    return copied


@lru_cache(maxsize=512)
def _awareness_route_hint_cached(message: str, max_hints: int) -> dict[str, object]:
    normalized = unicodedata.normalize("NFKC", message).casefold()
    routing_text = _localized_routing_text(message)
    localized_normalized = unicodedata.normalize("NFKC", routing_text).casefold()
    diagnostic_status = _diagnostic_status_context(normalized)
    diagnostic_eval = _prefers_diagnostic_workflow_learning_hint(message, classify_workflow_intent(message))
    routing_normalized = (
        localized_normalized
        if diagnostic_eval or not diagnostic_status
        else _without_diagnostic_status_lines(localized_normalized)
    )
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]*", routing_normalized))
    hint_limit = max_hints
    intent = classify_workflow_intent(message)
    omh_quality_intent = classify_omh_quality_intent(message)
    diagnostic_learning_first = diagnostic_eval
    hints: list[dict[str, object]] = []
    if normalized.strip() and hint_limit:
        if omh_quality_intent.applies and not diagnostic_learning_first:
            hints.append(_omh_quality_improvement_hint(omh_quality_intent))
        if len(hints) < hint_limit and (
            diagnostic_learning_first
            or (_prefers_workflow_learning_hint(intent) and not omh_quality_intent.applies)
        ):
            hints.append(_workflow_vocabulary_reference_hint(intent))
        direct_hint = _direct_workflow_invocation_hint(intent, routing_normalized, message)
        if len(hints) < hint_limit and direct_hint and not any(
            isinstance(hint, dict) and hint.get("workflow") == direct_hint.get("workflow") for hint in hints
        ):
            hints.append(direct_hint)
        for rule in _ROUTE_HINT_RULES:
            if len(hints) >= hint_limit:
                break
            if _rule_suppressed_by_omh_quality_intent(rule, omh_quality_intent):
                continue
            if _rule_suppressed_by_reference_intent(rule, intent):
                continue
            if _rule_suppressed_by_context(rule, routing_normalized):
                continue
            phrase_matches = [phrase for phrase in rule["phrases"] if phrase in routing_normalized]
            token_matches = [token for token in rule["tokens"] if token in tokens]
            if not phrase_matches and not token_matches:
                continue
            workflow = str(rule["workflow"])
            if any(isinstance(hint, dict) and hint.get("workflow") == workflow for hint in hints):
                continue
            if workflow == "workflow-learning" and any(hint.get("workflow") == workflow for hint in hints):
                continue
            context_card = workflow_context_card_for_workflow(workflow)
            next_action = str(rule["next_action"])
            if workflow == "loop":
                next_action = _loop_route_hint_next_action(message, next_action)
            if rule["id"] == "coding_delivery":
                next_action = _coding_delivery_route_hint_next_action(message, next_action)
            hints.append(
                {
                    "id": str(rule["id"]),
                    "workflow": workflow,
                    "lane": str(rule["lane"]),
                    "next_action": next_action,
                    "reason": str(rule["reason"]),
                    "fallback_action": str(rule["fallback_action"]),
                    "matched_cues": _bounded_matches(phrase_matches + token_matches),
                    "adjacent_workflows": list(rule["adjacent_workflows"]),
                    "workflow_context_card": context_card,
                    "not_evidence_yet": list(context_card.get("not_evidence_until_observed", []))
                    if isinstance(context_card, dict)
                    else [],
                }
            )
            if len(hints) >= hint_limit:
                break
    hints = [_route_hint_with_action_labels(hint) for hint in hints]
    primary_workflow = str(hints[0]["workflow"]) if hints else ""
    primary_next_action = str(hints[0]["next_action"]) if hints else ""
    adjacent_workflows = _unique_strings(
        str(item)
        for hint in hints
        if isinstance(hint, dict)
        for item in hint.get("adjacent_workflows", [])
    )
    return {
        "schema_version": OMH_ROUTE_HINT_SCHEMA_VERSION,
        "status": "hinted" if hints else "no_hint",
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest() if message else "",
        "message_length": len(message),
        "intent_class": intent.intent_class,
        "selected_workflow": primary_workflow,
        "mentioned_workflows": list(intent.mentioned_workflows),
        "mentioned_runtime_terms": list(intent.mentioned_runtime_terms),
        "adjacent_workflows": adjacent_workflows,
        "not_executed": list(intent.not_executed),
        "primary_workflow": primary_workflow,
        "primary_next_action": primary_next_action,
        "primary_next_action_label": _next_action_label(primary_next_action) if primary_next_action else "",
        "hints": hints,
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "stored_fields": ["message hash", "message length", "matched cue labels", "workflow hint"],
        },
        "claim_boundary": (
            "OMH route hints are local deterministic prompt context only. They are not workflow execution, "
            "tool invocation, generated output, verification, review, CI, merge, or proof that routing was correct."
        ),
    }


def _localized_routing_text(message: str) -> str:
    if _prepare_routing_text is None:
        return message
    try:
        return str(_prepare_routing_text(message).scoring_text or message)
    except Exception:  # pragma: no cover - defensive for standalone plugin hosts.
        return message


def awareness_route_hint_context(message: str, *, max_hints: int = 2) -> str:
    """Return compact hook text for message-specific workflow hints."""
    payload = awareness_route_hint(message, max_hints=max_hints)
    return awareness_route_hint_context_from_payload(payload)


def awareness_route_hint_context_from_payload(payload: dict[str, object]) -> str:
    """Return compact hook text from an already-built route hint payload."""
    if payload.get("status") != "hinted":
        return ""
    adjacent_summary = ", ".join(str(item) for item in payload.get("adjacent_workflows", []))
    mentioned_summary = ", ".join(str(item) for item in payload.get("mentioned_workflows", []))
    not_executed_summary = ", ".join(str(item) for item in payload.get("not_executed", []))
    lines = [
        "[OMH Route Hint]",
        "Use this message-specific OMH hint before generic chat/tools when it fits the user intent.",
        (
            f"intent={payload.get('intent_class')}; selected={payload.get('selected_workflow')}; "
            f"confidence=medium"
        ),
    ]
    if mentioned_summary:
        lines.append(f"mentioned_workflows={mentioned_summary}.")
    if adjacent_summary:
        lines.append(f"adjacent_workflows={adjacent_summary}.")
    if not_executed_summary:
        lines.append(f"not_executed={not_executed_summary}.")
    for hint in payload.get("hints", []):
        if not isinstance(hint, dict):
            continue
        adjacent = ", ".join(str(item) for item in hint.get("adjacent_workflows", []))
        next_action = str(hint.get("next_action") or "").strip()
        next_action_label = str(hint.get("next_action_label") or _next_action_label(next_action)).strip()
        lines.append(
            f"- selected={hint.get('workflow')}; lane={hint.get('lane')}; "
            f"next_action_label={next_action_label}; next_action={next_action}; reason={hint.get('reason')}"
        )
        context_card = hint.get("workflow_context_card")
        if isinstance(context_card, dict):
            first_response_shape = str(context_card.get("first_response_shape") or "").strip()
            if first_response_shape:
                lines.append(f"  first_response_shape={first_response_shape}")
        fallback_action = str(hint.get("fallback_action") or "").strip()
        if fallback_action:
            fallback_action_label = str(hint.get("fallback_action_label") or _next_action_label(fallback_action)).strip()
            lines.append(f"  fallback_action_label={fallback_action_label}; fallback_action={fallback_action}.")
        if adjacent:
            lines.append(f"  adjacent_workflows={adjacent}.")
        not_evidence = ", ".join(str(item) for item in hint.get("not_evidence_yet", [])[:4])
        if not_evidence:
            lines.append(f"  not_evidence_yet={not_evidence}.")
    lines.append("Boundary: " + str(payload.get("claim_boundary", "")))
    return "\n".join(lines)


def awareness_primer_payload() -> dict[str, object]:
    """Return the compact OMH mental model shared by hooks, tools, and skills."""
    lanes = [
        {
            "id": "intent_to_plan",
            "label": "Intent -> plan",
            "skills": [
                "oh-my-hermes",
                "deep-interview",
                "plan",
                "ralplan",
                "ultragoal",
                "ultraprocess",
                "loop",
                "ralph",
                "performance-goal",
            ],
            "use_for": "ambiguous goals, plans, one-cycle delivery, durable goals, and loopable projects",
        },
        {
            "id": "research_and_ops",
            "label": "Research and company ops",
            "skills": [
                "source-finder",
                "web-research",
                "best-practice-research",
                "autoresearch-goal",
                "research-brief",
                "strategy-brief",
                "feedback-triage",
                "research-department",
                "paper-learning",
                "meeting-brief",
                "operating-rhythm",
                "ops-review",
                "reliability-review",
            ],
            "use_for": "source-backed research, customer signals, product operations, and briefing workflows",
        },
        {
            "id": "retained_knowledge",
            "label": "Retained knowledge",
            "skills": ["wiki"],
            "use_for": "project wiki notes, external connections, retrieval hints, and staleness warnings",
        },
        {
            "id": "materials_and_visuals",
            "label": "Materials and visual summaries",
            "skills": ["design-quality-gate", "materials-package", "img-summary", "report-package", "deliverable-package"],
            "use_for": "premium websites, decks, PDFs, spreadsheets, documents, posters, image summary cards, and shareable packages",
        },
        {
            "id": "automation_and_status",
            "label": "Automation and status",
            "skills": [
                "achievements",
                "automation-blueprint",
                "github-event-ops",
                "agent-board",
                "gateway-intent-card",
                "voice-operator",
                "toolbelt-readiness",
                "ops-observability-card",
                "agent-ops-review",
                "memory-curation-review",
                "workflow-learning",
                "doctor",
                "skill",
                "ask",
                "cancel",
            ],
            "use_for": "scheduled ops, gateway cards, boards, tool readiness, status, health, and release/ops review",
        },
        {
            "id": "coding_handoff",
            "label": "Coding handoff",
            "skills": [
                "idea-to-deploy",
                "cto-loop",
                "deploy-and-monitor",
                "code-review",
                "ultrawork",
                "team",
                "ultraqa",
                "ai-slop-cleaner",
                "executor-runtime-readiness",
                "request-to-handoff",
                "executor selection",
                "coding runtime handoff",
            ],
            "use_for": "Codex, Claude Code, Hermes coding, or oh-my runtime paths with observed evidence tracking",
        },
    ]
    return {
        "schema_version": OMH_AWARENESS_SCHEMA_VERSION,
        "id": "omh_awareness",
        "purpose": "Give Hermes a compact first-turn mental model for using OMH across all workflow-shaped requests.",
        "product_context": (
            "OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, "
            "show status, and hand off with observed evidence boundaries."
        ),
        "first_turn_rule": (
            "For planning, research, retained knowledge, ops records, materials, visual summaries, automation, "
            "coding delegation, review, status, or long loops, consider OMH before generic chat or generic tools."
        ),
        "all_skill_context_rule": (
            "For every OMH skill: match intent to a lane; name adjacent workflows; "
            "generic tool can render or execute is not a dismissal."
        ),
        "generic_tool_checkpoint": GENERIC_TOOL_CHECKPOINT_TEXT,
        "skill_coverage": "Every generated workflow skill carries this rail.",
        "chat_rule": "Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.",
        "lanes": lanes,
        "workflow_context_cards": workflow_context_cards(),
        "generic_tool_checkpoint_routes": generic_tool_checkpoint_routes(),
        "cross_lane_examples": [
            example
            for lane_examples in LANE_CROSS_LANE_EXAMPLES.values()
            for example in lane_examples[:1]
        ],
        "workflow_cues": [
            {
                "cue": "meeting notes, retros, decisions, or follow-ups",
                "route": "operating-rhythm or meeting-brief before generic summarization",
            },
            {
                "cue": "PR, issue, bug, customer feedback, or release summaries",
                "route": "github-event-ops, feedback-triage, report-package, or img-summary by output shape",
            },
            {
                "cue": "current sources, market/news research, or evidence-backed answers",
                "route": "web-research, research-brief, or research-department before unsupported recall",
            },
            {
                "cue": "decks, PDFs, spreadsheets, docs, HWP, or upload-ready files",
                "route": "materials-package or report-package before ad hoc file narration",
            },
            {
                "cue": "image cards, infographics, briefing posters, or shareable visuals",
                "route": "img-summary before generic image generation or local rendering",
            },
            {
                "cue": "coding, risky changes, executor status, review, CI, or merge state",
                "route": "ultraprocess, coding handoff, code-review, or agent-ops-review with observed evidence boundaries",
            },
            {
                "cue": "workflow trace, skill improvement, regression corpus, or why-routing questions",
                "route": "workflow-learning before ad hoc self-critique or automatic skill patching",
            },
        ],
        "context_surfaces": [
            "installed skills and workflow picker",
            "capability manifest",
            "runtime status and HUD",
            "roles and operating model",
            "wrapper cards and actions",
            "local artifacts and evidence records",
        ],
        "tool_hints": [
            "Use omh_context when Hermes needs the compact OMH mental model, generic-tool checkpoint, and message-specific route hint in one payload.",
            "Use omh_capabilities action=summary when the user asks what OMH can do or which workflows are available.",
            "Use omh_recommend when the user gives a natural-language request and Hermes needs the nearest OMH workflow without shell approval.",
            "Use omh_capabilities for detailed workflow catalog and capability manifest lookup.",
            "Use omh_probe when the user asks whether OMH is installed, what is missing, or what the next setup/runtime evidence step should be.",
            "Use omh_status or omh_hud for metadata-only runtime state.",
            "Use omh_role for responsibility context when a role marker is present.",
            "Use wrapper cards/actions for user-facing choices instead of asking users to approve shell catalog commands.",
        ],
        "evidence_boundary": (
            "Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, "
            "delivery, review, CI, merge-readiness, or merge evidence."
        ),
        "fallback_rule": (
            "If an external image tool, coding agent, connector, credential, or runtime is missing, offer setup/selection fallback."
        ),
        "non_goals": [
            "no hidden executor dispatch",
            "no hidden image generation",
            "no hidden platform transport",
            "no Hermes core patching",
        ],
        "source_refs": [
            "src/plugin_bundle/omh/awareness.py",
            "src/skills/render.py",
            "src/capabilities/registry.py",
        ],
    }


def awareness_generic_tool_checkpoint_payload() -> dict[str, object]:
    return {
        "schema_version": OMH_GENERIC_TOOL_CHECKPOINT_SCHEMA_VERSION,
        "label": "OMH-first checkpoint",
        "body": GENERIC_TOOL_CHECKPOINT_TEXT,
        "applies_before": list(GENERIC_TOOL_CHECKPOINT_APPLIES_BEFORE),
        "routes": generic_tool_checkpoint_routes(),
        "operating_rule": (
            "If a route matches, show the preferred OMH workflow/action first. "
            "Use the generic tool only after the user accepts the route or when the route does not fit."
        ),
        "claim_boundary": "Advisory routing context only; not workflow execution or generic tool invocation evidence.",
    }


def generic_tool_checkpoint_routes() -> list[dict[str, object]]:
    """Return compact OMH-first route hints for common generic tool families."""
    return [
        {
            "tool_family": str(route["tool_family"]),
            "applies_before": list(route["applies_before"]),
            "primary_workflow": str(route["primary_workflow"]),
            "preferred_workflows": list(route["preferred_workflows"]),
            "primary_next_action": str(route["primary_next_action"]),
            "primary_next_action_label": _next_action_label(str(route["primary_next_action"])),
            "fallback_action": str(route["fallback_action"]),
            "fallback_action_label": _next_action_label(str(route["fallback_action"])),
            "not_evidence_yet": list(route["not_evidence_yet"]),
        }
        for route in GENERIC_TOOL_CHECKPOINT_ROUTES
    ]


def awareness_primer_context() -> str:
    payload = awareness_primer_payload()
    return "\n".join(
        [
            "[OMH Awareness]",
            "OMH is Hermes-native workflow guidance, not hidden execution or a transport/runtime patch.",
            (
                "For planning, research, files, visuals, automation, coding, review, status, or loops, "
                "consider OMH before generic tools."
            ),
            "Use message-specific route hints when present; they should outrank this always-on rail.",
            "Boundary: " + str(payload["evidence_boundary"]),
            "Expand only when needed with omh_context, omh_capabilities, and omh_status/omh_hud.",
        ]
    )


def awareness_primer_markdown() -> str:
    payload = awareness_primer_payload()
    lane_lines = []
    for lane in payload["lanes"]:
        if not isinstance(lane, dict):
            continue
        skills = [str(skill) for skill in lane["skills"][:4]]
        lane_lines.append(
            f"- **{lane['label']}**: {lane['use_for']}. Key: `{'`, `'.join(skills)}`."
        )
    return "\n".join(
        [
            "## OMH Awareness Primer",
            "",
            str(payload["product_context"]),
            "",
            str(payload["first_turn_rule"]),
            "",
            str(payload["all_skill_context_rule"]),
            "",
            str(payload["generic_tool_checkpoint"]),
            "",
            str(payload["skill_coverage"]),
            "",
            str(payload["chat_rule"]),
            *lane_lines,
            "",
            "Workflow context cards:",
            _compact_workflow_context_cards_line() + ".",
            "",
            "Common cues before generic tools:",
            _compact_workflow_cue_line() + ".",
            "",
            "Generic tool map:",
            _compact_generic_tool_checkpoint_line() + ".",
            "",
            f"Boundary: {payload['evidence_boundary']}",
        ]
    )


def awareness_workflow_context_markdown(skill_name: str) -> str:
    payload = awareness_primer_payload()
    lane = _lane_for_skill(skill_name, payload["lanes"])
    lane_line = "Use `omh_recommend` or the `oh-my-hermes` router for workflow choice, and `omh_capabilities` for manifest detail."
    if lane:
        skills = "`, `".join(str(skill) for skill in lane["skills"])
        lane_line = f"Current lane: **{lane['label']}** (`{skills}`) - {lane['use_for']}."
    return "\n".join(
        [
            "## OMH Context Rail",
            "",
            f"- This skill is part of OMH's Hermes workflow layer, not a standalone executor.",
            f"- Product context: {payload['product_context']}",
            f"- {lane_line}",
            "- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.",
            f"- Cross-skill context: {payload['all_skill_context_rule']}",
            f"- Generic-tool checkpoint: {_compact_generic_tool_checkpoint_line()}.",
            f"- Coverage: {payload['skill_coverage']}",
            f"- {payload['chat_rule']}",
            f"- Boundary: {payload['evidence_boundary']}",
        ]
    )


def _compact_workflow_cue_line() -> str:
    return (
        "notes/retros -> operating-rhythm/meeting-brief; PR/issue/bug/feedback/release -> github-event-ops, "
        "feedback-triage, report-package, or img-summary; supplied papers -> paper-learning; sources/news -> web-research or research-department; "
        "premium design/web/poster/PPT/PDF quality -> design-quality-gate; decks/PDF/sheets/docs/HWP -> materials-package or report-package; image cards/infographics -> img-summary; "
        "coding/status/review/CI/merge -> ultraprocess, code-review, or agent-ops-review; "
        "trace/improve/regression -> workflow-learning"
    )


def _compact_workflow_context_cards_line() -> str:
    return (
        "intent -> deep-interview/ralplan/loop/ultraprocess; "
        "signals -> web-research/research-department/feedback-triage/meeting-brief; "
        "materials -> design-quality-gate/materials-package/report-package/img-summary; "
        "automation/status/learning -> automation-blueprint/agent-ops-review/workflow-learning/doctor; "
        "code -> ultraprocess/code-review/team/ultrawork/ultraqa"
    )


def _compact_generic_tool_checkpoint_line() -> str:
    return (
        "image->img-summary; supplied paper->paper-learning; file->materials-package; "
        "search->web-research; code->ultraprocess/ralplan/review"
    )


_DIRECT_WORKFLOW_NEXT_ACTIONS = {
    "deep-interview": "answer_clarification",
    "plan": "present_plan",
    "ralplan": "present_plan",
    "ultragoal": "start_goal",
    "loop": "start_loop_cycle",
    "ultraprocess": "choose_executor",
    "workflow-learning": "audit_learning_readiness",
    "code-review": "prepare_review_or_followup_handoff",
    "team": "show_runtime_handoff",
    "ultrawork": "prepare_parallel_delivery",
    "ultraqa": "dispatch_to_workflow",
}


def _loop_route_hint_next_action(message: str, default_action: str) -> str:
    if _assess_loopability is None:
        return default_action
    try:
        assessment = _assess_loopability(message or "loop", expose_goal=False)
    except Exception:  # pragma: no cover - route hints should not break standalone hosts.
        return default_action
    next_action = str(assessment.get("recommended_next_action") or "").strip()
    normalized = unicodedata.normalize("NFKC", message).casefold().strip()
    explicit_loop = bool(re.match(r"^(?:\./loop|/loop)(?:\b|$)", normalized))
    loopability = str(assessment.get("loopability") or "").strip()
    if explicit_loop:
        if loopability == "needs_clarification":
            return next_action or "ask_goal_boundary"
        if loopability == "direct_task":
            return "route_direct_task"
        if loopability == "external_wait_only":
            return "record_external_wait"
        return "start_loop_cycle"
    return next_action or default_action


def _coding_delivery_route_hint_next_action(message: str, default_action: str) -> str:
    normalized = unicodedata.normalize("NFKC", message).casefold().strip()
    compact = re.sub(r"[\s\?\!\.,;:~…？]+", "", normalized)
    has_friren = "friren" in normalized or "프리렌" in normalized
    has_authority_or_merge_context = any(
        marker in normalized or marker in compact
        for marker in ("author", "merge", "commit", "머지", "커밋")
    )
    if has_friren and has_authority_or_merge_context:
        return "show_coding_handoff_status"
    return default_action


def _direct_workflow_invocation_hint(intent: object, routing_normalized: str, message: str) -> dict[str, object]:
    mentioned = [str(item) for item in getattr(intent, "mentioned_workflows", ()) if str(item)]
    if not mentioned:
        return {}
    structural = {str(item) for item in getattr(intent, "structural_cues", ())}
    direct_omh_form = routing_normalized.strip().startswith(("use omh ", "use oh-my-hermes ", "use oh-my-hermes-agent "))
    if "workflow_marker" not in structural and not direct_omh_form:
        return {}
    workflow = mentioned[0]
    context_card = workflow_context_card_for_workflow(workflow)
    lane = str(context_card.get("id") or _WORKFLOW_CONTEXT_CARD_BY_WORKFLOW.get(workflow.casefold(), "intent_to_plan"))
    next_action = _DIRECT_WORKFLOW_NEXT_ACTIONS.get(workflow, "route_to_downstream_workflow")
    if workflow == "loop":
        next_action = _loop_route_hint_next_action(message, next_action)
    return {
        "id": "direct_workflow_invocation",
        "workflow": workflow,
        "lane": lane,
        "next_action": next_action,
        "reason": "The user explicitly invoked an OMH workflow, so the hint should not be overridden by broad content keywords.",
        "fallback_action": "run_the_named_workflow_or_show_picker_if_unavailable",
        "matched_cues": ["direct workflow invocation"],
        "adjacent_workflows": [],
        "workflow_context_card": context_card,
        "not_evidence_yet": list(context_card.get("not_evidence_until_observed", []))
        if isinstance(context_card, dict)
        else [],
    }


def _bounded_matches(matches: list[str]) -> list[str]:
    seen: list[str] = []
    for item in matches:
        value = item.strip()
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= 4:
            break
    return seen


def _prefers_workflow_learning_hint(intent: object) -> bool:
    has_review_cues = bool(
        getattr(intent, "meta_cues", ())
        or getattr(intent, "feedback_cues", ())
        or getattr(intent, "missing_requirements_cues", ())
        or getattr(intent, "mentioned_workflows", ())
    )
    if bool(getattr(intent, "mentioned_runtime_terms", ())) and not has_review_cues:
        return False
    return (
        getattr(intent, "intent_class", "") in META_OR_FEEDBACK_INTENTS
        and not bool(getattr(intent, "explicit_execution", False))
        and (
            bool(getattr(intent, "mentioned_workflows", ()))
            or bool(getattr(intent, "mentioned_runtime_terms", ()))
            or bool(getattr(intent, "routing_context", False))
        )
    )


def _prefers_diagnostic_workflow_learning_hint(message: str, intent: object) -> bool:
    if bool(getattr(intent, "explicit_execution", False)):
        return False
    text = unicodedata.normalize("NFKC", message).casefold()
    if not _diagnostic_status_context(text):
        return False
    user_region = _without_diagnostic_status_lines(text)
    compact = user_region.replace(" ", "")
    has_user_omh_subject = re.search(r"(?<![a-z0-9])omh(?![a-z0-9])", user_region) is not None
    has_user_router_subject = bool(_matched_text_cues(("router", "routing", "route hint", "라우터", "라우팅"), user_region, compact))
    if not (has_user_omh_subject or has_user_router_subject):
        return False
    return bool(_matched_text_cues(_OMH_DIAGNOSTIC_EVALUATION_CUES, user_region, compact))


def _diagnostic_status_context(text: str) -> bool:
    return any(marker in text for marker in _DIAGNOSTIC_STATUS_MARKERS)


def _without_diagnostic_status_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines() or [text]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[omh"):
            stripped = re.sub(r"^\[omh(?:\s+awareness|\s+route\s+hint)?\]\s*", "", stripped).strip()
            if not stripped:
                continue
        if stripped.startswith(("native bridge status context", "evidence boundary", "latest runtime run")):
            continue
        if any(unicodedata.normalize("NFKC", marker).casefold() in stripped for marker in _DIAGNOSTIC_STATUS_LINE_MARKERS):
            fragments = [fragment.strip() for fragment in re.split(r"[;|]", stripped)]
            user_fragments = [
                fragment
                for fragment in fragments
                if fragment
                and not any(unicodedata.normalize("NFKC", marker).casefold() in fragment for marker in _DIAGNOSTIC_STATUS_LINE_MARKERS)
            ]
            if user_fragments:
                kept.append(" ".join(user_fragments))
            continue
        kept.append(stripped)
    return "\n".join(kept)


def _matched_text_cues(cues: tuple[str, ...], text: str, compact: str) -> tuple[str, ...]:
    matches: list[str] = []
    for cue in cues:
        normalized_cue = unicodedata.normalize("NFKC", cue).casefold()
        if not normalized_cue:
            continue
        if any(ord(char) > 127 for char in normalized_cue):
            if normalized_cue in text or normalized_cue.replace(" ", "") in compact:
                matches.append(cue)
            continue
        parts = re.findall(r"[a-z0-9]+", normalized_cue)
        if not parts:
            continue
        pattern = r"(?<![a-z0-9])" + r"[\s_-]+".join(re.escape(part) for part in parts) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            matches.append(cue)
    return tuple(matches)


def _omh_quality_improvement_hint(intent: object) -> dict[str, object]:
    workflow = "ultraprocess"
    context_card = workflow_context_card_for_workflow(workflow)
    return {
        "id": "omh_quality_improvement_loop",
        "workflow": workflow,
        "lane": "coding_handoff",
        "next_action": "prepare_one_cycle_delivery",
        "reason": (
            "The whole request is about improving OMH routing, context, progress, or coding-handoff quality; "
            "bug or failure words are evidence for a coding/process lane, not customer feedback triage."
        ),
        "fallback_action": "prepare_loop_or_coding_handoff_quality_regression",
        "matched_cues": _bounded_matches([str(item) for item in getattr(intent, "matched_cues", ())]),
        "adjacent_workflows": ["loop", "workflow-learning", "code-review", "agent-ops-review"],
        "workflow_context_card": context_card,
        "not_evidence_yet": list(context_card.get("not_evidence_until_observed", []))
        if isinstance(context_card, dict)
        else [],
    }


def _workflow_vocabulary_reference_hint(intent: object) -> dict[str, object]:
    workflow = "workflow-learning"
    context_card = workflow_context_card_for_workflow(workflow)
    next_action = "record_missed_route" if getattr(intent, "intent_class", "") == "feedback_signal" else "audit_learning_readiness"
    matched_cues = list(getattr(intent, "feedback_cues", ())) + list(getattr(intent, "meta_cues", ()))
    matched_cues.extend(getattr(intent, "mentioned_workflows", ()))
    matched_cues.extend(getattr(intent, "mentioned_runtime_terms", ()))
    return {
        "id": "workflow_vocabulary_reference",
        "workflow": workflow,
        "lane": "automation_and_status",
        "next_action": next_action,
        "reason": "The message discusses OMH workflow or coding-handoff vocabulary rather than asking to execute it.",
        "fallback_action": "record_learning_trace_or_prepare_route_review",
        "matched_cues": _bounded_matches([str(item) for item in matched_cues]),
        "adjacent_workflows": ["doctor", "agent-ops-review"],
        "mentioned_workflows": list(getattr(intent, "mentioned_workflows", ())),
        "mentioned_runtime_terms": list(getattr(intent, "mentioned_runtime_terms", ())),
        "not_executed": list(getattr(intent, "not_executed", ())),
        "workflow_context_card": context_card,
        "not_evidence_yet": list(context_card.get("not_evidence_until_observed", []))
        if isinstance(context_card, dict)
        else [],
    }


def _rule_suppressed_by_reference_intent(rule: dict[str, object], intent: object) -> bool:
    if not _prefers_workflow_learning_hint(intent):
        return False
    return str(rule.get("id", "")) == "coding_delivery"


def _rule_suppressed_by_omh_quality_intent(rule: dict[str, object], intent: object) -> bool:
    return bool(getattr(intent, "applies", False)) and str(rule.get("id", "")) == "customer_signal"


def _rule_suppressed_by_context(rule: dict[str, object], text: str) -> bool:
    rule_id = str(rule.get("id", ""))
    visual_markers = (
        "image card",
        "summary card",
        "announcement card",
        "poster",
        "visual",
        "이미지",
        "사진",
        "카드",
        "포스터",
    )
    if rule_id == "loopability_goal" and any(phrase in text for phrase in visual_markers):
        return True
    if rule_id == "github_event_ops_delivery" and any(
        phrase in text for phrase in visual_markers
    ):
        return True
    if rule_id == "executor_runtime_choice" and any(
        phrase in text
        for phrase in (
            "status",
            "progress",
            "where is",
            "어디까지",
            "진행상황",
            "진행 상황",
            "상태",
            "상태 보여",
            "완료됐",
            "완료됐어",
        )
    ):
        return True
    if rule_id == "release_gate_review" and any(
        phrase in text
        for phrase in (
            "risky refactor",
            "risky refactoring",
            "dangerous refactor",
            "dangerous refactoring",
            "위험한 리팩터링",
            "위험한 리팩토링",
        )
    ):
        return True
    if rule_id == "paper_learning" and any(
        phrase in text
        for phrase in (
            "find paper",
            "find arxiv",
            "paper link",
            "arxiv link",
            "논문 pdf 찾아",
            "논문 링크 찾아",
            "논문 pdf 링크",
            "arxiv 논문 링크",
            "arxiv 링크 찾아",
            "어디서 찾아",
        )
    ):
        return True
    if rule_id == "source_research" and any(
        phrase in text
        for phrase in (
            "attached paper",
            "attached paper at beginner level",
            "explain this paper",
            "paper-learning",
            "첨부한 논문",
            "논문을 초보자",
            "논문을 초보자 수준",
            "논문 설명",
            "논문 해설",
        )
    ):
        return True
    if rule_id == "source_research" and any(
        phrase in text
        for phrase in (
            "paper link",
            "arxiv link",
            "dataset search",
            "find datasets",
            "public slides",
            "public presentation materials",
            "논문 링크",
            "데이터셋 찾아",
            "공개 슬라이드 자료 찾아",
            "슬라이드 자료 찾아",
            "공개 발표자료 찾아",
        )
    ):
        return True
    if rule_id == "materials_package" and any(
        phrase in text
        for phrase in (
            "find public presentation",
            "public presentation",
            "public presentations",
            "공개 발표자료 찾아",
            "공개 발표자료 찾아서",
            "발표자료 찾아",
            "발표자료 찾아서",
        )
    ):
        return True
    if rule_id == "visual_summary" and any(
        phrase in text
        for phrase in (
            "image tool not connected",
            "image generation tool is missing",
            "image generation failed",
            "image generator connector",
            "which image generator",
            "fal_key",
            "fal key",
            "tool not attached",
            "image tool not attached",
            "this photo",
            "explain this photo",
            "describe this photo",
            "이 사진 설명",
            "사진 설명해",
            "그냥 이 사진 설명",
            "image라는 단어",
            "image 라는 단어",
            "이미지라는 단어",
            "이미지 라는 단어",
            "이미지 도구 연결",
            "이미지 도구 연결 안",
            "이미지 생성 도구",
            "도구가 안 붙",
            "도구 안 붙",
            "이미지 도구가 안 붙",
            "이미지 생성 연결",
            "이미지 생성 커넥터",
            "gpt image 연결",
            "gpt image 연결 안",
            "gpt 이미지 연결",
            "gpt 이미지 연결 안",
            "어떤걸로 연결",
            "어떤 걸로 연결",
        )
    ):
        return True
    return False


def _unique_strings(values: object) -> list[str]:
    seen: list[str] = []
    for item in values:
        value = str(item).strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _lane_for_skill(skill_name: str, lanes: object) -> dict[str, object] | None:
    if not isinstance(lanes, list):
        return None
    normalized = skill_name.strip()
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        skills = lane.get("skills", [])
        if isinstance(skills, list) and normalized in {str(skill) for skill in skills}:
            return lane
    return None
