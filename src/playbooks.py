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
                "Create a metadata-safe handoff payload for a Codex-like executor after plan acceptance.",
                "coding_delegation/v1",
                ("send_to_codex", "show_status"),
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
                ("send_to_codex", "refresh_status"),
                ("runtime run id", "observed lifecycle records"),
                "A later green status cannot override missing upstream evidence.",
            ),
        ),
        acceptance_criteria=(
            "The pipeline identifies which layer owns each stage.",
            "Wrapper actions are platform-neutral ids, not transport SDK calls.",
            "Evidence stages are strict enough for repeated status reporting.",
        ),
        not_evidence_until_observed=_COMMON_NOT_EVIDENCE,
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
