from __future__ import annotations

from dataclasses import dataclass
import re


PLAYBOOK_CATALOG_SCHEMA_VERSION = "playbook_catalog/v1"
PLAYBOOK_RECOMMENDATION_SCHEMA_VERSION = "playbook_recommendation/v1"
_TOKEN_RE = re.compile(r"[a-z0-9가-힣][a-z0-9가-힣-]*")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "when",
    "user",
    "agent",
    "hermes",
    "request",
    "workflow",
}


@dataclass(frozen=True)
class PlaybookStage:
    id: str
    title: str
    owner: str
    purpose: str
    contract: str
    wrapper_actions: tuple[str, ...]
    evidence_required: tuple[str, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "owner": self.owner,
            "purpose": self.purpose,
            "contract": self.contract,
            "wrapper_actions": list(self.wrapper_actions),
            "evidence_required": list(self.evidence_required),
            "evidence_boundary": self.evidence_boundary,
        }


@dataclass(frozen=True)
class Playbook:
    id: str
    title: str
    summary: str
    use_when: str
    keywords: tuple[str, ...]
    intent_tags: tuple[str, ...]
    pipeline: tuple[str, ...]
    retained_by_hermes: tuple[str, ...]
    delegated_to_executor: tuple[str, ...]
    stages: tuple[PlaybookStage, ...]
    acceptance_criteria: tuple[str, ...]
    not_evidence_until_observed: tuple[str, ...]

    def summary_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "use_when": self.use_when,
            "intent_tags": list(self.intent_tags),
            "pipeline": list(self.pipeline),
            "retained_by_hermes": list(self.retained_by_hermes),
            "delegated_to_executor": list(self.delegated_to_executor),
            "stage_count": len(self.stages),
            "not_evidence_until_observed": list(self.not_evidence_until_observed),
        }

    def to_dict(self) -> dict[str, object]:
        payload = self.summary_dict()
        payload.update(
            {
                "keywords": list(self.keywords),
                "stages": [stage.to_dict() for stage in self.stages],
                "acceptance_criteria": list(self.acceptance_criteria),
            }
        )
        return payload


_COMMON_NOT_EVIDENCE = (
    "executor_dispatch",
    "executor_result",
    "verification",
    "review",
    "ci",
    "merge_readiness",
    "merge",
)


_PLAYBOOKS = (
    Playbook(
        id="request-to-handoff",
        title="Request to handoff",
        summary="Flagship OMH path: turn a plain Hermes request into a role-owned next action with an explicit evidence boundary.",
        use_when="A user sends a natural request and needs Hermes to decide whether to clarify, research, plan, review, or prepare a coding handoff.",
        keywords=(
            "request-to-handoff",
            "request",
            "handoff",
            "next action",
            "plain request",
            "natural request",
            "i want to safely add a feature to this repo",
            "safe",
            "safely",
            "feature",
            "add",
            "change",
            "repo",
            "plan",
            "planning",
            "reviewable",
            "status",
            "evidence boundary",
            "executor",
            "coding handoff",
            "명령어",
            "자연어",
            "라우팅",
            "다음 행동",
            "계획",
            "핸드오프",
            "상태",
            "증거 경계",
        ),
        intent_tags=(
            "flagship workflow",
            "request to handoff",
            "chat first routing",
            "role owned next action",
            "prepared observed boundary",
        ),
        pipeline=("route_request", "select_role", "plan_or_prepare", "handoff_or_retain", "status_card"),
        retained_by_hermes=("chat intake", "clarification", "research/planning/review narration", "status explanation"),
        delegated_to_executor=("code changes only after plan acceptance and executor selection",),
        stages=(
            PlaybookStage(
                "route_request",
                "Route the plain request",
                "oh-my-hermes",
                "Classify the message into clarify, research, planning, review gate, retained response, or coding handoff.",
                "playbook_recommendation/v1",
                ("show_recommendation", "ask_followup"),
                ("task text hash", "selected route", "confidence"),
                "Routing is not plan acceptance, dispatch, or execution evidence.",
            ),
            PlaybookStage(
                "select_role",
                "Name the responsible role",
                "wrapper",
                "Expose the responsibility lane so the chat user knows who owns the next step.",
                "omh_role_surface/v1",
                ("show_status", "accept_plan", "revise_plan"),
                ("role id", "role evidence boundary"),
                "A role is a responsibility descriptor, not proof that a runtime agent ran.",
            ),
            PlaybookStage(
                "plan_or_prepare",
                "Plan before handoff",
                "planning-lead",
                "Clarify scope, non-goals, acceptance criteria, and verification before any coding handoff is prepared.",
                "hermes_plan/v1",
                ("accept_plan", "revise_plan", "prepare_handoff"),
                ("accepted plan or explicit retained-Hermes outcome",),
                "A draft plan is not accepted work or implementation evidence.",
            ),
            PlaybookStage(
                "handoff_or_retain",
                "Prepare handoff or retain in Hermes",
                "coding-handoff",
                "Prepare a selected executor handoff only when accepted work requires code; otherwise keep research, planning, review, or status in Hermes.",
                "coding_delegation/v1",
                ("choose_executor", "show_prompt_handoff", "send_to_executor", "show_status"),
                ("prepared handoff or retained-Hermes result",),
                "Prepared handoff is not executor dispatch, result, verification, review, CI, merge readiness, or merge evidence.",
            ),
            PlaybookStage(
                "status_card",
                "Render status card",
                "review-gate",
                "Report prepared, observed, missing, and blocked evidence separately.",
                "status_card/v1",
                ("refresh_status",),
                ("status card", "not-evidence list"),
                "Status only advances when the matching observation exists.",
            ),
        ),
        acceptance_criteria=(
            "The user sees why this workflow was chosen and what action is next.",
            "The response names the responsible role without claiming a hidden runtime agent ran.",
            "Coding is represented as prepared handoff until dispatch and execution are observed.",
        ),
        not_evidence_until_observed=_COMMON_NOT_EVIDENCE,
    ),
    Playbook(
        id="safe-feature-change",
        title="Safe feature change",
        summary="Turn a natural feature request into a plan-first coding handoff with status cards.",
        use_when="A user wants to add, change, or refactor code safely without learning command names.",
        keywords=(
            "safe",
            "safely",
            "feature",
            "add",
            "change",
            "repo",
            "implementation",
            "refactor",
            "review",
            "verify",
            "bug",
            "triage",
            "issue",
            "payment",
            "failure",
            "reproduce",
            "결제",
            "실패",
            "이슈",
            "버그",
            "재현",
            "기능",
            "리팩터링",
            "리팩터링하고",
            "리팩토링",
            "리팩토링하고",
            "위험",
            "위험 분석",
            "변경",
            "변경 범위",
            "변경 범위 제한",
            "테스트",
            "테스트 전략",
            "회귀",
            "회귀 테스트",
        ),
        intent_tags=(
            "safe feature change",
            "feature implementation",
            "repo change",
            "reviewed coding",
            "executor handoff",
        ),
        pipeline=("recommend", "chat_plan", "accept_plan", "prepare_handoff", "dispatch_executor", "status_card"),
        retained_by_hermes=("conversation", "clarification", "planning", "status narration"),
        delegated_to_executor=("implementation", "test execution", "review fix work"),
        stages=(
            PlaybookStage(
                "recommend",
                "Recommend a workflow lane",
                "omh",
                "Map the plain request to a planning-first route from local catalog metadata.",
                "playbook_recommendation/v1",
                ("show_recommendation",),
                ("task text hash", "selected playbook id", "confidence"),
                "Recommendation is not plan acceptance or execution evidence.",
            ),
            PlaybookStage(
                "plan",
                "Present a safe plan",
                "hermes",
                "Clarify scope, non-goals, acceptance criteria, and verification before coding starts.",
                "hermes_plan/v1",
                ("accept_plan", "revise_plan"),
                ("plan artifact or wrapper plan state",),
                "A draft plan is not implementation evidence.",
            ),
            PlaybookStage(
                "handoff",
                "Prepare coding handoff",
                "omh",
                "Create a metadata-safe handoff payload for the selected coding executor after plan acceptance.",
                "coding_delegation/v1",
                ("choose_executor", "show_prompt_handoff", "send_to_executor", "show_status"),
                ("prepared coding delegation record",),
                "Prepared handoff is not executor dispatch or result evidence.",
            ),
            PlaybookStage(
                "status",
                "Report observed progress",
                "wrapper",
                "Render handoff, execution, verification, review, CI, and merge readiness separately.",
                "status_card/v1",
                ("refresh_status",),
                ("runtime observation records",),
                "Status only advances when the matching runtime evidence exists.",
            ),
        ),
        acceptance_criteria=(
            "The user can stay in chat and choose plan actions without knowing shell commands.",
            "Coding work is represented as a prepared executor handoff until dispatch is observed.",
            "Completion claims require observed verification and review evidence when required.",
        ),
        not_evidence_until_observed=_COMMON_NOT_EVIDENCE,
    ),
    Playbook(
        id="source-backed-research",
        title="Source-backed research",
        summary="Keep current-information requests in Hermes as research before any later plan or handoff.",
        use_when="A user asks for latest, official, comparative, legal, financial, or source-backed information.",
        keywords=(
            "research",
            "latest",
            "current",
            "official",
            "source",
            "sources",
            "compare",
            "comparative",
            "evidence",
            "citation",
            "legal",
            "financial",
            "information",
            "investigate",
            "조사",
            "근거",
            "출처",
            "고객",
            "피드백",
        ),
        intent_tags=(
            "source backed research",
            "official sources",
            "current information",
            "legal research",
            "financial research",
            "evidence synthesis",
        ),
        pipeline=("clarify_scope", "gather_sources", "synthesize", "status_summary"),
        retained_by_hermes=("source selection", "evidence synthesis", "confidence and uncertainty narration"),
        delegated_to_executor=(),
        stages=(
            PlaybookStage(
                "scope",
                "Clarify source boundaries",
                "hermes",
                "Ask the smallest blocking question only when jurisdiction, recency, or source type changes the answer.",
                "chat_response/v1",
                ("answer_question", "revise_scope"),
                ("research question", "source boundary"),
                "Clarification is not research evidence.",
            ),
            PlaybookStage(
                "research",
                "Gather and compare sources",
                "hermes",
                "Prefer official or primary sources and separate direct evidence from inference.",
                "research_notes/v1",
                ("show_sources",),
                ("source refs", "retrieval dates", "quoted evidence summary"),
                "Research notes are not implementation or verification evidence.",
            ),
            PlaybookStage(
                "status",
                "Summarize confidence",
                "hermes",
                "Report conclusions, uncertainty, and what would change the answer.",
                "chat_response/v1",
                ("show_status",),
                ("confidence summary", "remaining uncertainty"),
                "A research conclusion is not a completed coding handoff.",
            ),
        ),
        acceptance_criteria=(
            "Official or primary sources are preferred when available.",
            "The answer separates evidence, inference, confidence, and residual uncertainty.",
            "No coding handoff is prepared unless the user asks for code changes after research.",
        ),
        not_evidence_until_observed=("implementation", "verification", "review", "ci", "merge"),
    ),
    Playbook(
        id="research-to-strategy-brief",
        title="Research to strategy brief",
        summary="Move from scoped business research into meeting topics, strategy options, and a decision-ready record.",
        use_when="A user wants customer, market, product, or source evidence turned into a strategy or meeting brief.",
        keywords=(
            "business research",
            "research brief",
            "customer feedback trends",
            "feedback trends",
            "meeting agenda",
            "meeting topics",
            "product strategy",
            "strategy memo",
            "strategy brief",
            "data search",
            "market evidence",
            "source scan",
            "자료 조사",
            "데이터 서치",
            "피드백 추세",
            "고객 피드백 추세",
            "회의 주제",
            "회의 아젠다",
            "다음 전략",
            "전략 정리",
        ),
        intent_tags=(
            "research brief",
            "business evidence",
            "meeting topics",
            "strategy options",
            "decision record",
        ),
        pipeline=("scope_research", "evidence_table", "meeting_topics", "strategy_options", "decision_record"),
        retained_by_hermes=("research scoping", "evidence synthesis", "strategy narration", "decision record prep"),
        delegated_to_executor=(),
        stages=(
            PlaybookStage(
                "scope",
                "Scope the business question",
                "hermes",
                "Name source boundaries, recency assumptions, and the decision the research should inform.",
                "research_brief/v1",
                ("ask_followup", "show_status"),
                ("research question", "source boundary", "decision context"),
                "A research scope is not observed source evidence.",
            ),
            PlaybookStage(
                "evidence",
                "Build evidence table",
                "hermes",
                "Separate observed evidence, inference, confidence, and missing-source gaps.",
                "research_brief/v1",
                ("show_sources", "show_status"),
                ("source evidence when observed", "inference summary", "uncertainty"),
                "A synthesized table is not implementation or verification evidence.",
            ),
            PlaybookStage(
                "strategy",
                "Prepare strategy brief",
                "hermes",
                "Turn evidence into meeting topics, options, tradeoffs, and a decision-ready note.",
                "strategy_brief/v1",
                ("show_brief", "revise_brief", "record_decision"),
                ("options", "tradeoffs", "recommended direction", "decision note"),
                "A strategy brief is not an accepted decision.",
            ),
        ),
        acceptance_criteria=(
            "Research boundaries and missing evidence are explicit.",
            "Strategy options distinguish observed evidence from inference.",
            "No coding handoff is prepared from the brief alone.",
        ),
        not_evidence_until_observed=("source_fetch", "decision_acceptance", "implementation", "verification", "review", "ci", "merge"),
    ),
    Playbook(
        id="meeting-prep-to-record",
        title="Meeting prep to record",
        summary="Prepare agenda, discussion prompts, decisions needed, and a record template.",
        use_when="A user wants Hermes to prepare for a meeting or turn context into meeting-ready structure.",
        keywords=(
            "meeting brief",
            "meeting prep",
            "meeting agenda",
            "agenda",
            "discussion prompts",
            "decisions needed",
            "record template",
            "action items",
            "leadership meeting",
            "회의 준비",
            "회의 주제",
            "회의 아젠다",
            "아젠다",
            "논의 질문",
            "결정할 것",
            "기록 템플릿",
            "액션 아이템",
        ),
        intent_tags=(
            "meeting prep",
            "agenda",
            "discussion guide",
            "decision prompts",
            "record template",
        ),
        pipeline=("gather_context", "agenda", "discussion_prompts", "decisions_needed", "record_template"),
        retained_by_hermes=("agenda shaping", "discussion prompt generation", "record template prep"),
        delegated_to_executor=(),
        stages=(
            PlaybookStage(
                "context",
                "Gather meeting context",
                "hermes",
                "Identify audience, objective, known facts, and missing context.",
                "meeting_brief/v1",
                ("ask_followup", "show_status"),
                ("meeting goal", "audience", "known context"),
                "Meeting context is not a meeting outcome.",
            ),
            PlaybookStage(
                "agenda",
                "Draft agenda and prompts",
                "hermes",
                "Prepare agenda topics, discussion prompts, and decisions needed.",
                "meeting_brief/v1",
                ("show_agenda", "revise_brief"),
                ("agenda", "prompts", "decisions needed"),
                "A prepared agenda is not evidence that discussion happened.",
            ),
            PlaybookStage(
                "record",
                "Prepare record template",
                "wrapper",
                "Expose a neutral record template for decisions, owners, due dates, and follow-ups.",
                "meeting_record_template/v1",
                ("record_decision", "show_status"),
                ("record template", "action-item fields"),
                "A template is not observed minutes or accepted action items.",
            ),
        ),
        acceptance_criteria=(
            "Agenda and prompts are tied to the meeting objective.",
            "Decisions needed are explicit.",
            "Prepared content remains separate from actual meeting outcomes.",
        ),
        not_evidence_until_observed=("meeting_held", "decision_acceptance", "action_item_acceptance", "implementation"),
    ),
    Playbook(
        id="feedback-triage",
        title="Feedback triage",
        summary="Cluster customer signals, rank severity or opportunity, and choose the next workflow without defaulting to coding.",
        use_when="A user brings customer feedback, bugs, or feature asks and wants the right next step before planning or implementation.",
        keywords=(
            "feedback triage",
            "customer feedback",
            "customer feedback trends",
            "feedback trends",
            "feedback cluster",
            "payment failure feedback",
            "payment failure",
            "bug or feature",
            "feature request",
            "severity",
            "opportunity",
            "next workflow",
            "고객 피드백",
            "피드백",
            "피드백을 모아서",
            "피드백 분류",
            "결제 실패 피드백",
            "결제 실패",
            "회의 주제",
            "다음 전략",
            "전략 정리",
            "버그",
            "기능 요청",
            "심각도",
            "기회",
        ),
        intent_tags=(
            "feedback triage",
            "customer insight",
            "bug signal",
            "feature ask",
            "next workflow recommendation",
        ),
        pipeline=("source_boundary", "cluster_feedback", "rank_signal", "recommend_next_workflow"),
        retained_by_hermes=("feedback classification", "severity/opportunity ranking", "next workflow guidance"),
        delegated_to_executor=(),
        stages=(
            PlaybookStage(
                "source",
                "Set source boundary",
                "hermes",
                "Name where the feedback came from and what is not yet observed.",
                "feedback_triage/v1",
                ("ask_followup", "show_status"),
                ("source boundary", "sample size or missing sample"),
                "A feedback summary is not proof that the full source was reviewed.",
            ),
            PlaybookStage(
                "cluster",
                "Cluster signals",
                "hermes",
                "Separate bug signals, feature asks, research questions, and strategy inputs.",
                "feedback_triage/v1",
                ("show_triage", "ask_followup"),
                ("clusters", "severity", "opportunity"),
                "A bug signal is not a reproduced bug or implemented fix.",
            ),
            PlaybookStage(
                "route",
                "Recommend next workflow",
                "wrapper",
                "Choose research, meeting, strategy, plan, or coding handoff only when intent is explicit.",
                "workflow_route/v1",
                ("prepare_plan", "show_status"),
                ("next workflow", "reason", "not-evidence list"),
                "Next workflow guidance is not execution evidence.",
            ),
        ),
        acceptance_criteria=(
            "Feedback source boundaries are explicit.",
            "Clusters distinguish bug, feature, research, and strategy signals.",
            "No coding handoff is prepared unless coding intent is explicit or a later plan is accepted.",
        ),
        not_evidence_until_observed=("source_review", "bug_reproduction", "roadmap_decision", "implementation", "verification", "review", "ci", "merge"),
    ),
    Playbook(
        id="weekly-ops-review",
        title="Weekly ops review",
        summary="Summarize status, risks, blockers, priorities, and follow-up actions from observed evidence.",
        use_when="A user wants a weekly, release, operating, or status review without overstating missing evidence.",
        keywords=(
            "weekly ops review",
            "ops review",
            "status review",
            "operating review",
            "weekly status",
            "release risks",
            "risks and blockers",
            "customer feedback and release risks",
            "priorities",
            "follow-up actions",
            "운영 리뷰",
            "주간 운영",
            "상태 리뷰",
            "릴리즈 리스크",
            "리스크",
            "블로커",
            "우선순위",
        ),
        intent_tags=(
            "ops review",
            "status evidence",
            "risks",
            "blockers",
            "priorities",
            "follow-up actions",
        ),
        pipeline=("scope_window", "status_evidence", "risks_blockers", "priorities", "followups"),
        retained_by_hermes=("status narration", "risk synthesis", "follow-up organization"),
        delegated_to_executor=(),
        stages=(
            PlaybookStage(
                "scope",
                "Scope review window",
                "hermes",
                "Name the time window, operating area, and evidence sources.",
                "ops_review/v1",
                ("ask_followup", "show_status"),
                ("scope", "time window", "evidence sources"),
                "A review scope is not status evidence.",
            ),
            PlaybookStage(
                "status",
                "Summarize observed status",
                "hermes",
                "Separate facts, missing evidence, risks, blockers, and priorities.",
                "ops_review/v1",
                ("show_status", "record_blocker"),
                ("status facts", "risks", "blockers", "unknowns"),
                "An ops summary is not review, CI, release, or merge evidence.",
            ),
            PlaybookStage(
                "followups",
                "Prepare follow-up actions",
                "wrapper",
                "Expose follow-up actions and route code fixes only as explicit later handoffs.",
                "ops_followups/v1",
                ("prepare_plan", "record_checkpoint"),
                ("follow-ups", "owners when known", "next workflow"),
                "Follow-up suggestions are not completed work.",
            ),
        ),
        acceptance_criteria=(
            "Every status claim is observed or marked unknown.",
            "Risks, blockers, priorities, and follow-ups are separated.",
            "Code fixes become explicit follow-up handoffs only when accepted.",
        ),
        not_evidence_until_observed=("status_source_review", "followup_acceptance", "implementation", "review", "ci", "release", "merge"),
    ),
    Playbook(
        id="market-scan-to-strategy",
        title="Market scan to strategy",
        summary="Turn competitor or market scan inputs into an implication matrix and strategy brief.",
        use_when="A user wants competitor, market, or leadership-meeting evidence shaped into strategy.",
        keywords=(
            "competitor market scan",
            "market scan",
            "competitor scan",
            "competitive scan",
            "competitor",
            "market",
            "strategy memo",
            "leadership meeting",
            "implication matrix",
            "product strategy",
            "경쟁사",
            "시장 조사",
            "시장 스캔",
            "전략 메모",
            "리더십 회의",
        ),
        intent_tags=(
            "market scan",
            "competitor evidence",
            "implication matrix",
            "strategy brief",
            "leadership meeting",
        ),
        pipeline=("scope_scan", "evidence_matrix", "implications", "strategy_brief"),
        retained_by_hermes=("scan scoping", "evidence synthesis", "strategy implications"),
        delegated_to_executor=(),
        stages=(
            PlaybookStage(
                "scope",
                "Scope market scan",
                "hermes",
                "Name competitors, market boundaries, source needs, and recency constraints.",
                "market_scan/v1",
                ("ask_followup", "show_status"),
                ("market boundary", "source boundary", "recency"),
                "A scan scope is not observed market evidence.",
            ),
            PlaybookStage(
                "matrix",
                "Build implication matrix",
                "hermes",
                "Separate competitor evidence, product implications, and uncertainty.",
                "market_scan/v1",
                ("show_sources", "show_brief"),
                ("evidence matrix", "implications", "uncertainty"),
                "An implication matrix is not a decision or implementation.",
            ),
            PlaybookStage(
                "brief",
                "Prepare strategy brief",
                "hermes",
                "Turn implications into options and a leadership-ready strategy memo.",
                "strategy_brief/v1",
                ("show_brief", "record_decision"),
                ("options", "tradeoffs", "recommendation"),
                "A strategy memo is not an accepted decision.",
            ),
        ),
        acceptance_criteria=(
            "Market and source boundaries are explicit.",
            "Evidence, implications, and uncertainty are separated.",
            "Strategy output stays decision-ready but not decision-accepted.",
        ),
        not_evidence_until_observed=("source_fetch", "decision_acceptance", "implementation", "verification", "review", "ci", "merge"),
    ),
    Playbook(
        id="deep-interview-to-plan",
        title="Deep interview to plan",
        summary="Reduce ambiguous goals into a clarified brief, then a plan, before any handoff.",
        use_when="A broad goal has missing scope, non-goals, decision authority, or acceptance criteria.",
        keywords=(
            "ambiguous",
            "unclear",
            "interview",
            "clarify",
            "plan",
            "strategy",
            "goal",
            "non-goal",
            "onboarding",
            "product",
            "shaping",
            "온보딩",
            "부드럽게",
            "모호",
            "기획",
        ),
        intent_tags=(
            "deep interview",
            "clarified brief",
            "ambiguous goal",
            "planning before handoff",
            "acceptance criteria",
        ),
        pipeline=("ask_one_question", "clarified_brief", "draft_plan", "decision_gate"),
        retained_by_hermes=("one-question interview", "brief synthesis", "plan narration"),
        delegated_to_executor=("implementation only after plan acceptance",),
        stages=(
            PlaybookStage(
                "interview",
                "Ask one blocking question",
                "hermes",
                "Resolve the decision that most changes the plan shape or stop condition.",
                "chat_response/v1",
                ("answer_question",),
                ("blocking ambiguity", "user answer"),
                "An unanswered question is not a plan.",
            ),
            PlaybookStage(
                "brief",
                "Synthesize clarified brief",
                "hermes",
                "Name goals, non-goals, constraints, and acceptance criteria.",
                "clarified_brief/v1",
                ("accept_brief", "revise_brief"),
                ("clarified brief",),
                "A clarified brief is not execution evidence.",
            ),
            PlaybookStage(
                "plan",
                "Draft execution plan",
                "hermes",
                "Produce a reviewable plan and only expose handoff actions after acceptance.",
                "hermes_plan/v1",
                ("accept_plan", "revise_plan"),
                ("plan artifact",),
                "A draft plan is not accepted work.",
            ),
        ),
        acceptance_criteria=(
            "Only one blocking question is asked at a time.",
            "The plan contains goals, non-goals, risks, verification, and handoff guidance.",
            "Coding delegation remains disabled until the user or wrapper accepts the plan.",
        ),
        not_evidence_until_observed=_COMMON_NOT_EVIDENCE,
    ),
    Playbook(
        id="local-pipeline-buildout",
        title="Local pipeline buildout",
        summary="Design a repeatable local workflow from chat intake through plan, handoff, status, and review evidence.",
        use_when="A maintainer wants to build or document a deterministic pipeline for a recurring work pattern.",
        keywords=(
            "pipeline",
            "buildout",
            "recurring",
            "workflow",
            "process",
            "status",
            "review",
            "automation",
            "hub",
            "handoff",
            "coding handoff",
            "review gate",
            "답할",
            "차례인지",
            "준비할",
            "agency",
            "template",
            "requirements",
            "작업",
            "허브",
            "여러",
            "도구",
            "프로젝트별",
            "고객사",
            "요구사항",
            "운영",
            "템플릿",
        ),
        intent_tags=(
            "local pipeline",
            "wrapper orchestration",
            "recurring workflow",
            "status lifecycle",
            "contract buildout",
        ),
        pipeline=("catalog_route", "wrapper_contract", "plan_gate", "executor_lifecycle", "review_ci_merge_status"),
        retained_by_hermes=("process explanation", "planning", "status narration"),
        delegated_to_executor=("pipeline code changes", "test implementation"),
        stages=(
            PlaybookStage(
                "catalog",
                "Select catalog route",
                "omh",
                "Use local skill and harness metadata to pick the workflow lane.",
                "workflow_catalog/v1",
                ("show_route",),
                ("catalog match", "confidence"),
                "Catalog selection is not runtime execution.",
            ),
            PlaybookStage(
                "contract",
                "Render wrapper contract",
                "wrapper",
                "Map route state to buttons, thread updates, and status cards.",
                "chat_interaction/v1",
                ("render_buttons", "show_status"),
                ("wrapper action ids", "thread key"),
                "Rendered UI is not executor evidence.",
            ),
            PlaybookStage(
                "lifecycle",
                "Track executor lifecycle",
                "omh",
                "Record dispatch, result, verification, review, CI, and merge readiness as separate observations.",
                "delegated_coding_status/v1",
                ("send_to_executor", "refresh_status"),
                ("runtime run id", "observed lifecycle records"),
                "A later green status cannot override missing upstream evidence.",
            ),
        ),
        acceptance_criteria=(
            "The pipeline identifies which layer owns each stage.",
            "Wrapper actions are stable Hermes-facing ids.",
            "Evidence stages are strict enough for repeated status reporting.",
        ),
        not_evidence_until_observed=_COMMON_NOT_EVIDENCE,
    ),
    Playbook(
        id="idea-to-deploy",
        title="Idea to deploy",
        summary="Carry an app idea through shaping, decision, delivery handoff, verification, release, deploy, and monitoring status.",
        use_when="A user wants a product or app idea to feel like an end-to-end delivery loop, not just a plan or coding prompt.",
        keywords=(
            "idea-to-deploy",
            "idea to deploy",
            "from idea to deploy",
            "plan to deploy",
            "idea to launch",
            "ship this idea",
            "ship this feature",
            "launch this feature",
            "product delivery loop",
            "app delivery loop",
            "complete product loop",
            "end-to-end app operation",
            "완제품 루프",
            "아이디어부터 배포",
            "기획부터 배포",
            "출시까지",
            "앱 운영 루프",
        ),
        intent_tags=(
            "idea to deploy",
            "app delivery loop",
            "product shaping",
            "executor handoff",
            "release monitor",
        ),
        pipeline=(
            "shape_idea",
            "decision_gate",
            "delivery_plan",
            "executor_handoff",
            "verification_release_gate",
            "deploy_monitor_status",
        ),
        retained_by_hermes=(
            "idea shaping",
            "decision framing",
            "delivery plan narration",
            "release and status explanation",
        ),
        delegated_to_executor=("accepted implementation work after plan approval",),
        stages=(
            PlaybookStage(
                "shape_idea",
                "Shape idea and success metric",
                "hermes",
                "Turn the idea into user value, non-goals, constraints, and a success metric.",
                "app_delivery_loop/v1",
                ("ask_followup", "show_delivery_loop"),
                ("idea", "user/customer value", "success metric", "non-goals"),
                "Idea shaping is not an accepted plan, implementation, deploy, or monitoring evidence.",
            ),
            PlaybookStage(
                "decision_gate",
                "Record decision gate",
                "wrapper",
                "Ask the user or owner to accept, revise, or block the delivery direction.",
                "decision_gate/v1",
                ("accept_plan", "revise_plan", "show_status"),
                ("decision owner", "accepted direction or blocker"),
                "A recommendation is not an accepted decision until decision evidence is recorded.",
            ),
            PlaybookStage(
                "delivery_plan",
                "Draft delivery plan",
                "hermes",
                "Prepare scope, risks, acceptance criteria, verification, release notes, and handoff criteria.",
                "hermes_plan/v1",
                ("accept_plan", "prepare_handoff", "show_status"),
                ("delivery plan", "acceptance criteria", "verification plan"),
                "A draft delivery plan is not implementation or release evidence.",
            ),
            PlaybookStage(
                "executor_handoff",
                "Prepare executor handoff if code is needed",
                "coding-handoff",
                "Use the selected executor profile for accepted code work; otherwise keep the loop in Hermes.",
                "coding_delegation/v1",
                ("choose_executor", "show_prompt_handoff", "send_to_executor"),
                ("selected executor", "prepared handoff"),
                "Prepared handoff is not executor dispatch, result, verification, review, CI, or merge evidence.",
            ),
            PlaybookStage(
                "verification_release_gate",
                "Check verification and release gate",
                "review-gate",
                "Separate observed verification, review, CI, and release-readiness facts from missing evidence.",
                "harness_quality/v1",
                ("record_checkpoint", "show_status"),
                ("verification evidence or explicit gap", "release gate status"),
                "Release-ready is not deployed, monitored, or merged.",
            ),
            PlaybookStage(
                "deploy_monitor_status",
                "Record deploy and monitor status",
                "wrapper",
                "Record deploy, health signal, rollback, or incident observations only when supplied by the operator or wrapper.",
                "status_card/v1",
                ("record_deploy", "record_monitor_signal", "show_status"),
                ("deploy observation or not_observed", "monitor signal or not_observed"),
                "A deployment plan or health watchlist is not observed deploy or monitoring evidence.",
            ),
        ),
        acceptance_criteria=(
            "The wrapper can show a single end-to-end stage rail from idea to monitoring.",
            "Coding work becomes a selected executor handoff only after plan acceptance.",
            "Deploy, health, rollback, and monitoring states remain unobserved until evidence is recorded.",
        ),
        not_evidence_until_observed=(
            "decision_acceptance",
            "executor_dispatch",
            "executor_result",
            "verification",
            "review",
            "ci",
            "release_readiness",
            "deploy",
            "monitoring",
            "rollback",
            "incident_response",
            "merge",
        ),
    ),
    Playbook(
        id="cto-loop",
        title="CTO loop",
        summary="Run a leadership operating loop across roadmap, PM framing, architecture tradeoffs, delivery risk, release readiness, and follow-ups.",
        use_when="A user wants CTO/PM-style operating cadence and decision quality without forcing a default team profile or hidden runtime roles.",
        keywords=(
            "cto-loop",
            "cto loop",
            "cto",
            "cto pm",
            "pm dev qa security ops",
            "roadmap architecture",
            "architecture tradeoff",
            "delivery risk",
            "release readiness",
            "technical leadership loop",
            "leadership operating loop",
            "engineering leadership",
            "CTO 구조",
            "PM 구조",
            "로드맵",
            "아키텍처 트레이드오프",
            "기술 리더십",
            "출시 준비",
        ),
        intent_tags=(
            "cto loop",
            "roadmap decision",
            "architecture tradeoff",
            "delivery risk",
            "release readiness",
        ),
        pipeline=(
            "intake_signals",
            "prioritize_risks",
            "architecture_tradeoffs",
            "delivery_decision",
            "followup_handoffs",
            "status_review",
        ),
        retained_by_hermes=(
            "roadmap and PM synthesis",
            "architecture tradeoff narration",
            "risk prioritization",
            "decision and status explanation",
        ),
        delegated_to_executor=("accepted implementation follow-ups only",),
        stages=(
            PlaybookStage(
                "intake_signals",
                "Intake operating signals",
                "hermes",
                "Collect customer, product, engineering, release, and risk signals into one operating frame.",
                "leadership_loop/v1",
                ("show_status", "ask_followup"),
                ("signals", "source boundary", "decision owner"),
                "Signal intake is not a roadmap decision or execution evidence.",
            ),
            PlaybookStage(
                "prioritize_risks",
                "Prioritize risks and opportunities",
                "hermes",
                "Rank PM value, engineering risk, QA uncertainty, security concern, and ops readiness.",
                "leadership_loop/v1",
                ("show_brief", "record_blocker"),
                ("ranked risks", "opportunities", "assumptions"),
                "Risk ranking is not evidence that any owner accepted or resolved a risk.",
            ),
            PlaybookStage(
                "architecture_tradeoffs",
                "Frame architecture tradeoffs",
                "planning-lead",
                "Make architecture options, rejected alternatives, and delivery consequences explicit.",
                "strategy_brief/v1",
                ("show_brief", "revise_plan"),
                ("options", "tradeoffs", "rejected alternatives"),
                "Tradeoff framing is not implementation evidence.",
            ),
            PlaybookStage(
                "delivery_decision",
                "Record delivery decision",
                "wrapper",
                "Ask the decision owner to accept, revise, defer, or block the recommended direction.",
                "decision_gate/v1",
                ("record_decision", "accept_plan", "show_status"),
                ("decision status", "owner", "follow-up lane"),
                "A CTO loop recommendation is not accepted until decision evidence is recorded.",
            ),
            PlaybookStage(
                "followup_handoffs",
                "Prepare follow-up handoffs",
                "coding-handoff",
                "Convert accepted implementation follow-ups into executor-neutral handoffs; keep non-code follow-ups in Hermes.",
                "coding_delegation/v1",
                ("choose_executor", "prepare_handoff", "show_status"),
                ("accepted follow-up", "selected executor if code is needed"),
                "Prepared follow-up handoffs are not dispatch, result, verification, review, CI, or merge evidence.",
            ),
            PlaybookStage(
                "status_review",
                "Report operating status",
                "wrapper",
                "Show decisions, blockers, accepted follow-ups, unobserved work, and next review cadence.",
                "status_card/v1",
                ("show_status", "record_checkpoint"),
                ("status card", "not-evidence list"),
                "A status report cannot upgrade missing downstream evidence.",
            ),
        ),
        acceptance_criteria=(
            "The loop is understandable as CTO/PM-style operations without claiming hidden role agents ran.",
            "Draft recommendations, accepted decisions, and implementation follow-ups remain separate.",
            "Code work leaves Hermes only as accepted executor-neutral handoffs.",
        ),
        not_evidence_until_observed=(
            "decision_acceptance",
            "owner_acknowledgement",
            "executor_dispatch",
            "executor_result",
            "verification",
            "review",
            "ci",
            "release_readiness",
            "deploy",
            "monitoring",
            "merge",
        ),
    ),
    Playbook(
        id="deploy-and-monitor",
        title="Deploy and monitor",
        summary="Prepare a release operation with deploy checklist, health signals, rollback gate, incident watch, and post-deploy status.",
        use_when="A user wants Hermes to guide release operations and monitoring status without OMH becoming an infrastructure executor.",
        keywords=(
            "deploy-and-monitor",
            "deploy and monitor",
            "deploy monitor",
            "deployment monitoring",
            "release monitor",
            "post deploy",
            "post-deploy",
            "rollback",
            "rollback gate",
            "health check",
            "incident watch",
            "release health",
            "배포 모니터링",
            "배포 감시",
            "롤백",
            "헬스 체크",
            "장애 감시",
            "릴리즈 모니터링",
        ),
        intent_tags=(
            "deploy and monitor",
            "release operation",
            "health check",
            "rollback gate",
            "incident watch",
        ),
        pipeline=("release_scope", "predeploy_checks", "deploy_decision", "monitor_signals", "rollback_gate", "postdeploy_record"),
        retained_by_hermes=("release checklist narration", "health signal framing", "rollback criteria", "status explanation"),
        delegated_to_executor=("fix follow-ups after observed deploy or monitor failure",),
        stages=(
            PlaybookStage(
                "release_scope",
                "Scope release",
                "hermes",
                "Name release target, environment, owner, expected impact, and known risk.",
                "release_operation/v1",
                ("ask_followup", "show_status"),
                ("release scope", "environment", "owner", "risk"),
                "Release scope is not deploy or release-readiness evidence.",
            ),
            PlaybookStage(
                "predeploy_checks",
                "Prepare pre-deploy checks",
                "review-gate",
                "List checks, required evidence, missing blockers, and rollback prerequisites.",
                "harness_quality/v1",
                ("record_checkpoint", "show_status"),
                ("checklist", "required evidence", "known blockers"),
                "A checklist is not a passed check.",
            ),
            PlaybookStage(
                "deploy_decision",
                "Record deploy decision",
                "wrapper",
                "Require an explicit go, no-go, defer, or blocked decision before deploy status can advance.",
                "decision_gate/v1",
                ("record_decision", "show_status"),
                ("deploy decision", "owner", "timestamp when available"),
                "Deploy decision evidence is not deploy execution evidence.",
            ),
            PlaybookStage(
                "monitor_signals",
                "Watch monitor signals",
                "wrapper",
                "Record health signals, alerts, error budget, customer reports, or missing observations.",
                "status_card/v1",
                ("record_monitor_signal", "show_status"),
                ("health signal or not_observed", "alert/customer signal when available"),
                "A monitor watchlist is not observed health evidence.",
            ),
            PlaybookStage(
                "rollback_gate",
                "Evaluate rollback gate",
                "hermes",
                "Narrate rollback criteria and recommend follow-up based on observed monitor evidence.",
                "release_operation/v1",
                ("record_blocker", "prepare_plan", "show_status"),
                ("rollback criteria", "observed trigger or explicit not_observed"),
                "Rollback criteria are not rollback execution evidence.",
            ),
            PlaybookStage(
                "postdeploy_record",
                "Record post-deploy status",
                "wrapper",
                "Summarize observed deploy, monitor, incident, rollback, and follow-up evidence.",
                "status_card/v1",
                ("show_status", "prepare_handoff"),
                ("post-deploy status", "not-evidence list", "follow-up handoff when needed"),
                "Post-deploy status cannot claim fixes, review, CI, or merge without separate observations.",
            ),
        ),
        acceptance_criteria=(
            "The deploy loop names release scope, owner, environment, health signals, and rollback criteria.",
            "Prepared checks, go/no-go decision, deploy execution, monitoring, and rollback stay separate.",
            "Fixes discovered during monitoring become later accepted plans or executor handoffs.",
        ),
        not_evidence_until_observed=(
            "predeploy_check_pass",
            "deploy_decision",
            "deploy",
            "health_check",
            "monitoring",
            "rollback",
            "incident_response",
            "fix_result",
            "verification",
            "review",
            "ci",
            "merge",
        ),
    ),
    Playbook(
        id="release-readiness-review",
        title="Release readiness review",
        summary="Frame docs, QA, review, CI, and merge-readiness checks without treating them as code fixes.",
        use_when="A change is public-facing, release-shaped, or needs confidence before merge.",
        keywords=(
            "release",
            "readiness",
            "review",
            "qa",
            "ci",
            "merge",
            "public",
            "docs",
            "quality",
            "kubernetes",
            "incident",
            "scenario",
            "checklist",
            "cloudy",
            "evidence",
            "claim",
            "audit",
            "릴리즈",
            "검증",
            "체크리스트",
            "쿠버네티스",
            "장애",
            "시나리오",
            "실제로",
            "뭐",
            "했는지",
            "ai가",
        ),
        intent_tags=(
            "release readiness",
            "qa review",
            "ci status",
            "merge readiness",
            "public docs quality",
        ),
        pipeline=("review_scope", "qa_checks", "ci_status", "merge_readiness", "report"),
        retained_by_hermes=("review framing", "status narration", "risk synthesis"),
        delegated_to_executor=("fix implementation", "test repair", "docs edits when accepted"),
        stages=(
            PlaybookStage(
                "review",
                "Run review gate",
                "hermes",
                "Separate review findings from any follow-up code changes.",
                "review_gate/v1",
                ("show_findings", "prepare_fix_handoff"),
                ("review summary", "risk list"),
                "Review findings are not fix evidence.",
            ),
            PlaybookStage(
                "qa",
                "Check adversarial scenarios",
                "hermes",
                "Name scenario coverage and record pass, fail, or not observed.",
                "harness_quality/v1",
                ("show_status",),
                ("scenario list", "observed result"),
                "A QA plan is not a passed test.",
            ),
            PlaybookStage(
                "merge",
                "Report merge readiness",
                "omh",
                "Combine review, verification, CI, and merge readiness without skipping missing gates.",
                "status_card/v1",
                ("refresh_status",),
                ("review record", "ci record", "merge readiness record"),
                "Merge-ready is not merged.",
            ),
        ),
        acceptance_criteria=(
            "Findings, fixes, verification, CI, and merge readiness remain separate.",
            "Fix work becomes an executor handoff when code changes are required.",
            "Merge status is never inferred from review or CI alone.",
        ),
        not_evidence_until_observed=("fix_result", "verification", "ci", "merge_readiness", "merge"),
    ),
)


def list_playbooks() -> dict[str, object]:
    return {
        "schema_version": PLAYBOOK_CATALOG_SCHEMA_VERSION,
        "playbooks": [playbook.summary_dict() for playbook in _PLAYBOOKS],
    }


def inspect_playbook(playbook_id: str) -> dict[str, object]:
    playbook = _playbook_by_id(playbook_id)
    return {
        "schema_version": PLAYBOOK_CATALOG_SCHEMA_VERSION,
        "playbook": playbook.to_dict(),
    }


def recommend_playbooks(query: str, *, limit: int = 3) -> dict[str, object]:
    if limit < 1:
        raise ValueError("playbook recommend --limit must be at least 1")
    task = query.strip()
    if not task:
        raise ValueError("playbook recommend requires a task description")
    scored = [_score_playbook(playbook, task) for playbook in _PLAYBOOKS]
    scored.sort(key=lambda item: (-int(item["score"]), str(item["id"])))
    matches = [item for item in scored if int(item["score"]) > 0] or [_fallback_playbook(task)]
    return {
        "schema_version": PLAYBOOK_RECOMMENDATION_SCHEMA_VERSION,
        "query": task,
        "recommendations": matches[:limit],
    }


def _playbook_by_id(playbook_id: str) -> Playbook:
    for playbook in _PLAYBOOKS:
        if playbook.id == playbook_id:
            return playbook
    raise KeyError(playbook_id)


def _score_playbook(playbook: Playbook, query: str) -> dict[str, object]:
    query_tokens = _tokens(query)
    query_terms = _terms(query)
    score = 0
    matched: set[str] = set()

    for keyword in playbook.keywords:
        normalized_keyword = keyword.lower()
        if _matches_term(normalized_keyword, query_terms):
            score += 5
            matched.add(f"keyword:{normalized_keyword}")

    intent_tokens = _tokens(" ".join((playbook.id, *playbook.intent_tags)))
    for token in sorted(query_tokens & intent_tokens):
        score += 2
        matched.add(f"intent:{token}")

    for intent_tag in playbook.intent_tags:
        normalized_intent = intent_tag.lower()
        if _matches_term(normalized_intent, query_terms):
            score += 3
            matched.add(f"intent-tag:{normalized_intent}")

    if "coding" in query_tokens or "code" in query_tokens or "implement" in query_tokens:
        if playbook.delegated_to_executor:
            score += 2
            matched.add("boundary:executor")
    if "research" in query_tokens or "source" in query_tokens:
        if not playbook.delegated_to_executor:
            score += 2
            matched.add("boundary:hermes")

    return _recommendation_payload(playbook, score=score, matched=tuple(sorted(matched)))


def _fallback_playbook(query: str) -> dict[str, object]:
    playbook = _playbook_by_id("deep-interview-to-plan")
    payload = _recommendation_payload(playbook, score=0, matched=())
    payload["why"] = "No strong playbook match; start by clarifying the request before planning or handoff."
    payload["suggested_prompt"] = f"Clarify and plan this request before delegation: {query}"
    return payload


def _recommendation_payload(playbook: Playbook, *, score: int, matched: tuple[str, ...]) -> dict[str, object]:
    first_stage = playbook.stages[0]
    return {
        "id": playbook.id,
        "title": playbook.title,
        "summary": playbook.summary,
        "score": score,
        "confidence": _confidence(score),
        "matched": list(matched),
        "why": _why(matched),
        "pipeline": list(playbook.pipeline),
        "next_action": first_stage.id,
        "wrapper_actions": list(first_stage.wrapper_actions),
        "evidence_boundary": first_stage.evidence_boundary,
        "retained_by_hermes": list(playbook.retained_by_hermes),
        "delegated_to_executor": list(playbook.delegated_to_executor),
        "not_evidence_until_observed": list(playbook.not_evidence_until_observed),
        "suggested_prompt": f"Use the {playbook.id} playbook for this request.",
    }


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in _terms(value):
        for token in (raw_token, *raw_token.split("-")):
            if len(token) >= 3 and token not in _STOPWORDS:
                tokens.add(token)
    return tokens


def _terms(value: str) -> set[str]:
    terms: set[str] = set()
    for raw_token in _TOKEN_RE.findall(value.lower()):
        terms.add(raw_token)
        terms.update(raw_token.split("-"))
    return terms


def _matches_term(term: str, query_terms: set[str]) -> bool:
    term_tokens = tuple(_terms(term))
    if not term_tokens:
        return False
    return all(token in query_terms for token in term_tokens)


def _confidence(score: int) -> str:
    if score >= 10:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _why(matched: tuple[str, ...]) -> str:
    if not matched:
        return "No strong playbook match."
    sources = sorted({item.split(":", 1)[0] for item in matched})
    return f"Matched {'/'.join(sources)} playbook signals for this task."
