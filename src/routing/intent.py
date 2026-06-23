from __future__ import annotations

from dataclasses import asdict, dataclass

from .localization import normalized_phrase, routing_tokens


WORKFLOW_VOCABULARY = (
    "deep-interview",
    "ralplan",
    "ultragoal",
    "loop",
    "ultraprocess",
    "workflow-learning",
    "code-review",
    "team",
    "ultrawork",
    "ultraqa",
)
RUNTIME_VOCABULARY = {
    "codex": "Codex",
    "coding handoff": "coding handoff",
    "coding delegate": "coding delegate",
    "one-cycle delivery": "one-cycle delivery",
    "one cycle delivery": "one-cycle delivery",
    "coding-agent": "coding-agent",
}
META_OR_FEEDBACK_INTENTS = frozenset({"meta_discussion", "feedback_signal"})

_META_CUES = (
    "test",
    "testing",
    "fixture",
    "smoke test",
    "developer",
    "operator",
    "meta",
    "vocabulary",
    "terminology",
    "term",
    "route hint",
    "hud",
    "log",
    "trigger",
    "not asking to implement",
    "not asking for implementation",
    "테스트",
    "픽스처",
    "개발자",
    "운영자",
    "용어",
    "라우팅",
    "라우터",
    "로그",
    "트리거",
    "오해",
    "설명",
)
_FEEDBACK_CUES = (
    "why did",
    "why is",
    "why does",
    "confusing",
    "confused",
    "wrong route",
    "wrong workflow",
    "misroute",
    "misrouted",
    "missed route",
    "skipped omh",
    "route this wrong",
    "routing is wrong",
    "왜",
    "왜 뜨",
    "잘못",
    "오해",
    "안 썼",
    "누락",
)
_PLANNING_CUES = (
    "plan",
    "proposal",
    "improvement",
    "prepare a plan",
    "planning",
    "계획",
    "개선안",
    "제안",
)
_EXECUTION_CUES = (
    "implement",
    "implementation",
    "make a pr",
    "open a pr",
    "prepare a pr",
    "pr-ready",
    "dispatch",
    "delegate",
    "send to codex",
    "run ultraprocess",
    "run $ultraprocess",
    "execute",
    "merge",
    "구현",
    "구현해",
    "구현해줘",
    "pr 만들어",
    "pr까지",
    "codex로",
    "맡겨",
    "보내",
    "실행",
)
_NEGATED_EXECUTION_CUES = (
    "not asking to implement",
    "not asking for implementation",
    "not implement",
    "do not implement",
    "don't implement",
    "without implementation",
    "no implementation",
    "구현 요청 아님",
    "구현하라는 뜻 아님",
    "구현하지 말고",
)
_MISSING_REQUIREMENTS_CUES = (
    "no requirements",
    "without requirements",
    "requirements are missing",
    "missing requirements",
    "no real requirements",
    "요구사항은 없어",
    "요구사항 없어",
    "요구사항 없음",
    "아직 요구사항",
)


@dataclass(frozen=True)
class WorkflowIntent:
    intent_class: str
    explicit_execution: bool
    mentioned_workflows: tuple[str, ...]
    mentioned_runtime_terms: tuple[str, ...]
    meta_cues: tuple[str, ...]
    feedback_cues: tuple[str, ...]
    planning_cues: tuple[str, ...]
    execution_cues: tuple[str, ...]
    missing_requirements_cues: tuple[str, ...]
    routing_context: bool

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        data["not_executed"] = list(self.not_executed)
        return data

    @property
    def not_executed(self) -> tuple[str, ...]:
        if self.intent_class == "delivery_intent":
            return ()
        return (*self.mentioned_workflows, *self.mentioned_runtime_terms)


def classify_workflow_intent(message: str) -> WorkflowIntent:
    """Classify whether workflow vocabulary is a reference or execution intent."""
    normalized = normalized_phrase(message)
    tokens = set(routing_tokens(message, stopwords=set()))
    tokens.update(normalized.split())
    compact = normalized.replace(" ", "")

    mentioned_workflows = _mentioned_workflows(normalized, tokens)
    mentioned_runtime_terms = _mentioned_runtime_terms(normalized)
    meta_cues = _matched_cues(_META_CUES, normalized, compact)
    feedback_cues = _matched_cues(_FEEDBACK_CUES, normalized, compact)
    planning_cues = _matched_cues(_PLANNING_CUES, normalized, compact)
    negated_execution_cues = _matched_cues(_NEGATED_EXECUTION_CUES, normalized, compact)
    execution_cues = _suppress_negated_execution_cues(
        _matched_cues(_EXECUTION_CUES, normalized, compact),
        negated_execution_cues,
    )
    missing_requirements_cues = _matched_cues(_MISSING_REQUIREMENTS_CUES, normalized, compact)
    explicit_execution = bool(execution_cues or (_explicit_workflow_invocation(normalized, tokens) and not negated_execution_cues))
    routing_context = _routing_context(normalized, tokens)

    specific_runtime_reference = any(term != "Codex" for term in mentioned_runtime_terms)
    workflow_or_specific_runtime = bool(mentioned_workflows or specific_runtime_reference)

    if explicit_execution:
        intent_class = "delivery_intent"
    elif missing_requirements_cues or (feedback_cues and (routing_context or workflow_or_specific_runtime)):
        intent_class = "feedback_signal"
    elif meta_cues and (routing_context or workflow_or_specific_runtime):
        intent_class = "meta_discussion"
    elif planning_cues:
        intent_class = "planning_request"
    else:
        intent_class = "unknown"
    return WorkflowIntent(
        intent_class=intent_class,
        explicit_execution=explicit_execution,
        mentioned_workflows=mentioned_workflows,
        mentioned_runtime_terms=mentioned_runtime_terms,
        meta_cues=meta_cues,
        feedback_cues=feedback_cues,
        planning_cues=planning_cues,
        execution_cues=execution_cues,
        missing_requirements_cues=missing_requirements_cues,
        routing_context=routing_context,
    )


def is_workflow_meta_or_feedback(message: str) -> bool:
    intent = classify_workflow_intent(message)
    return intent.intent_class in META_OR_FEEDBACK_INTENTS and not intent.explicit_execution


def has_missing_requirements_signal(message: str) -> bool:
    return bool(classify_workflow_intent(message).missing_requirements_cues)


def _mentioned_workflows(normalized: str, tokens: set[str]) -> tuple[str, ...]:
    mentioned: list[str] = []
    for workflow in WORKFLOW_VOCABULARY:
        normalized_workflow = normalized_phrase(workflow)
        if normalized_workflow in tokens or normalized_workflow in normalized:
            mentioned.append(workflow)
    return tuple(mentioned)


def _mentioned_runtime_terms(normalized: str) -> tuple[str, ...]:
    mentioned: list[str] = []
    for term, label in RUNTIME_VOCABULARY.items():
        normalized_term = normalized_phrase(term)
        if normalized_term and normalized_term in normalized and label not in mentioned:
            mentioned.append(label)
    return tuple(mentioned)


def _matched_cues(cues: tuple[str, ...], normalized: str, compact: str) -> tuple[str, ...]:
    matches: list[str] = []
    for cue in cues:
        normalized_cue = normalized_phrase(cue)
        if not normalized_cue:
            continue
        if normalized_cue in normalized or normalized_cue.replace(" ", "") in compact:
            matches.append(cue)
    return tuple(matches)


def _suppress_negated_execution_cues(
    execution_cues: tuple[str, ...],
    negated_execution_cues: tuple[str, ...],
) -> tuple[str, ...]:
    if not negated_execution_cues:
        return execution_cues
    return tuple(cue for cue in execution_cues if cue not in {"implement", "implementation", "구현", "구현해", "구현해줘"})


def _explicit_workflow_invocation(normalized: str, tokens: set[str]) -> bool:
    for workflow in WORKFLOW_VOCABULARY:
        if f"${workflow}" in normalized or f"/{workflow}" in normalized or f"./{workflow}" in normalized:
            return True
    return "dispatch" in tokens or "execute" in tokens


def _routing_context(normalized: str, tokens: set[str]) -> bool:
    context_tokens = {
        "omh",
        "oh-my-hermes",
        "route",
        "routing",
        "router",
        "workflow",
        "workflows",
        "handoff",
        "coding",
        "라우팅",
        "라우터",
        "워크플로",
        "워크플로우",
        "코딩",
    }
    context_phrases = {
        "oh-my-hermes",
        "route hint",
        "handoff",
        "coding handoff",
        "coding delegate",
        "one-cycle delivery",
        "one cycle delivery",
        "라우팅",
        "라우터",
        "워크플로",
        "워크플로우",
        "코딩",
    }
    return bool(tokens & context_tokens) or any(term in normalized for term in context_phrases)
