from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import re

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

# These aliases preserve known English/Korean wrapper behavior. They are not a
# multilingual understanding strategy, and new languages should not be added here
# as an ever-growing keyword table. Prefer the structural cues below; broader
# multilingual interpretation belongs in Hermes/LLM clarification or wrapper UX.
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
_REFERENCE_CONTEXT_TOKENS = frozenset(
    {
        "context",
        "hint",
        "literal",
        "log",
        "ref",
        "reference",
        "route",
        "routing",
        "status",
        "term",
        "terminology",
        "token",
        "vocabulary",
    }
)
_NEGATABLE_EXECUTION_CUES = frozenset(_EXECUTION_CUES)
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


@dataclass(frozen=True)
class WorkflowIntent:
    intent_class: str
    explicit_execution: bool
    mentioned_workflows: tuple[str, ...]
    mentioned_runtime_terms: tuple[str, ...]
    structural_cues: tuple[str, ...]
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


@dataclass(frozen=True)
class OmhQualityIntent:
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
        return _compact_tuple(
            (
                *(f"target:{cue}" for cue in self.target_cues),
                *(f"improve:{cue}" for cue in self.improvement_cues),
                *(f"quality:{cue}" for cue in self.quality_cues),
                *(f"loop:{cue}" for cue in self.loop_cues),
                *(f"handoff:{cue}" for cue in self.handoff_cues),
            )
        )


def classify_workflow_intent(message: str) -> WorkflowIntent:
    """Classify whether workflow vocabulary is a reference or execution intent."""
    normalized = normalized_phrase(message)
    tokens = set(routing_tokens(message, stopwords=set()))
    tokens.update(normalized.split())
    compact = normalized.replace(" ", "")

    diagnostic_status_context = _diagnostic_status_context(normalized, compact)
    diagnostic_evaluation_context = _diagnostic_omh_evaluation_context(normalized, compact)
    matching_normalized = (
        normalized
        if not diagnostic_status_context or diagnostic_evaluation_context
        else _without_diagnostic_status_lines(normalized)
    )
    matching_compact = matching_normalized.replace(" ", "")
    matching_tokens = set(routing_tokens(matching_normalized, stopwords=set()))
    matching_tokens.update(matching_normalized.split())

    mentioned_workflows = _mentioned_workflows(matching_normalized, matching_tokens)
    mentioned_runtime_terms = _mentioned_runtime_terms(matching_normalized)
    structural_cues = _structural_cues(
        message,
        matching_normalized,
        matching_tokens,
        diagnostic_status_context=diagnostic_status_context,
    )
    meta_cues = _matched_cues(_META_CUES, matching_normalized, matching_compact)
    feedback_cues = _matched_cues(_FEEDBACK_CUES, matching_normalized, matching_compact)
    planning_cues = _matched_cues(_PLANNING_CUES, matching_normalized, matching_compact)
    negated_execution_cues = _compact_tuple(
        (*_matched_cues(_NEGATED_EXECUTION_CUES, matching_normalized, matching_compact), *_structural_negated_execution_cues(matching_normalized))
    )
    execution_cues = _suppress_negated_execution_cues(
        _matched_cues(_EXECUTION_CUES, matching_normalized, matching_compact),
        negated_execution_cues,
    )
    if diagnostic_evaluation_context:
        execution_cues = _suppress_diagnostic_status_execution_cues(execution_cues, normalized)
    missing_requirements_cues = _matched_cues(_MISSING_REQUIREMENTS_CUES, matching_normalized, matching_compact)
    routing_context = _routing_context(matching_normalized, matching_tokens)

    specific_runtime_reference = any(term != "Codex" for term in mentioned_runtime_terms)
    workflow_or_specific_runtime = bool(mentioned_workflows or specific_runtime_reference)
    structural_reference = _structural_reference_context(
        structural_cues,
        workflow_or_specific_runtime=workflow_or_specific_runtime,
        routing_context=routing_context,
    )
    explicit_workflow_marker = _explicit_workflow_invocation(normalized, tokens)
    explicit_execution = bool(
        execution_cues
        or (
            explicit_workflow_marker
            and not negated_execution_cues
            and not structural_reference
        )
    )

    if explicit_execution:
        intent_class = "delivery_intent"
    elif (
        missing_requirements_cues
        or diagnostic_evaluation_context
        or (feedback_cues and (routing_context or workflow_or_specific_runtime))
    ):
        intent_class = "feedback_signal"
    elif (meta_cues or structural_reference) and (routing_context or workflow_or_specific_runtime):
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
        structural_cues=structural_cues,
        meta_cues=meta_cues,
        feedback_cues=feedback_cues,
        planning_cues=planning_cues,
        execution_cues=execution_cues,
        missing_requirements_cues=missing_requirements_cues,
        routing_context=routing_context,
    )


_OMH_SYSTEM_TARGET_CUES = (
    "omh",
    "oh-my-hermes",
    "oh my hermes",
)
_OMH_QUALITY_DOMAIN_CUES = (
    "route quality",
    "router quality",
    "router",
    "routing",
    "route hint",
    "context loss",
    "context-loss",
    "context safety",
    "context-safety",
    "progress reporting",
    "progress evidence",
    "event progress",
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
)
_OMH_IMPROVEMENT_CUES = (
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
    "keep finding",
    "개선",
    "개선해",
    "고쳐",
    "찾아",
    "점검",
    "강화",
)
_OMH_QUALITY_PROBLEM_CUES = (
    "bug",
    "bugs",
    "failure",
    "failures",
    "loss",
    "missing",
    "regression",
    "reliability",
    "quality",
    "performance balance",
    "버그",
    "유사버그",
    "실패",
    "손실",
    "누락",
    "회귀",
    "신뢰성",
    "품질",
    "성능균형",
)
_OMH_LOOP_CUES = (
    "loop",
    "continuous",
    "continue",
    "keep",
    "keeps",
    "keeping",
    "recurring",
    "루프",
    "계속",
    "반복",
)
_OMH_HANDOFF_CUES = (
    "coding handoff",
    "handoff",
    "코딩",
    "위임",
)
_CUSTOMER_FEEDBACK_CUES = (
    "customer",
    "customers",
    "user feedback",
    "payment failure",
    "payment failures",
    "payment",
    "billing",
    "checkout",
    "product feedback",
    "feature request",
    "고객",
    "사용자",
    "결제",
    "피드백",
    "제보",
)


def classify_omh_quality_intent(message: str) -> OmhQualityIntent:
    """Classify deterministic OMH self-improvement loop intent.

    This is a semantic feature layer over local cues: product/customer bug words
    are only decisive when the request subject is customer feedback; OMH bug
    words become evidence for improving routing, context, progress, or handoff
    quality when the request is about OMH itself.
    """
    normalized = normalized_phrase(message)
    compact = normalized.replace(" ", "")

    system_target_cues = _matched_omh_system_target_cues(normalized)
    quality_domain_cues = _matched_omh_quality_cues(_OMH_QUALITY_DOMAIN_CUES, normalized, compact)
    improvement_cues = _matched_omh_quality_cues(_OMH_IMPROVEMENT_CUES, normalized, compact)
    quality_cues = _matched_omh_quality_cues(_OMH_QUALITY_PROBLEM_CUES, normalized, compact)
    loop_cues = _matched_omh_quality_cues(_OMH_LOOP_CUES, normalized, compact)
    handoff_cues = _matched_omh_quality_cues(_OMH_HANDOFF_CUES, normalized, compact)
    customer_feedback_cues = _matched_omh_quality_cues(_CUSTOMER_FEEDBACK_CUES, normalized, compact)

    target_cues = _compact_tuple((*system_target_cues, *quality_domain_cues))
    has_omh_subject = bool(system_target_cues)
    has_quality_domain = bool(quality_domain_cues or handoff_cues)
    has_improvement_motion = bool(improvement_cues or loop_cues)
    has_quality_evidence = bool(quality_cues)
    customer_feedback_subject = bool(customer_feedback_cues) and not has_omh_subject
    applies = (
        has_omh_subject
        and has_quality_domain
        and (has_improvement_motion or has_quality_evidence)
        and not customer_feedback_subject
    )

    return OmhQualityIntent(
        applies=applies,
        target_cues=target_cues,
        improvement_cues=improvement_cues,
        quality_cues=quality_cues,
        loop_cues=loop_cues,
        handoff_cues=handoff_cues,
        customer_feedback_cues=customer_feedback_cues,
    )


def _matched_omh_system_target_cues(normalized: str) -> tuple[str, ...]:
    cues: list[str] = []
    if re.search(r"(?<![a-z0-9])omh(?![a-z0-9])", normalized):
        cues.append("omh")
    for cue in ("oh-my-hermes", "oh my hermes"):
        if cue in normalized and cue not in cues:
            cues.append(cue)
    return tuple(cues)


def _matched_omh_quality_cues(cues: tuple[str, ...], normalized: str, compact: str) -> tuple[str, ...]:
    matches: list[str] = []
    for cue, normalized_cue, contains_non_ascii in _normalized_quality_cues(cues):
        if contains_non_ascii:
            if normalized_cue in normalized or normalized_cue.replace(" ", "") in compact:
                matches.append(cue)
            continue
        if _contains_bounded_english_cue(normalized, normalized_cue):
            matches.append(cue)
    return tuple(matches)


def _contains_non_ascii(value: str) -> bool:
    return any(ord(char) > 127 for char in value)


def _contains_bounded_english_cue(normalized: str, normalized_cue: str) -> bool:
    pattern = _bounded_english_cue_pattern(normalized_cue)
    return pattern is not None and pattern.search(normalized) is not None


@lru_cache(maxsize=512)
def _bounded_english_cue_pattern(normalized_cue: str) -> re.Pattern[str] | None:
    parts = re.findall(r"[a-z0-9]+", normalized_cue)
    if not parts:
        return None
    separator = r"[\s_-]+"
    pattern = r"(?<![a-z0-9])" + separator.join(re.escape(part) for part in parts) + r"(?![a-z0-9])"
    return re.compile(pattern)


def is_workflow_meta_or_feedback(message: str) -> bool:
    intent = classify_workflow_intent(message)
    return intent.intent_class in META_OR_FEEDBACK_INTENTS and not intent.explicit_execution


def has_missing_requirements_signal(message: str) -> bool:
    return bool(classify_workflow_intent(message).missing_requirements_cues)


def _mentioned_workflows(normalized: str, tokens: set[str]) -> tuple[str, ...]:
    mentioned: list[str] = []
    for workflow, normalized_workflow in _normalized_workflow_vocabulary():
        if normalized_workflow in tokens or normalized_workflow in normalized:
            mentioned.append(workflow)
    return tuple(mentioned)


def _mentioned_runtime_terms(normalized: str) -> tuple[str, ...]:
    mentioned: list[str] = []
    for _term, label, normalized_term in _normalized_runtime_vocabulary():
        if normalized_term and normalized_term in normalized and label not in mentioned:
            mentioned.append(label)
    return tuple(mentioned)


def _structural_cues(
    message: str,
    normalized: str,
    tokens: set[str],
    *,
    diagnostic_status_context: bool = False,
) -> tuple[str, ...]:
    cues: list[str] = []
    if _explicit_workflow_invocation(normalized, tokens):
        cues.append("workflow_marker")
    if _quoted_known_term_reference(message):
        cues.append("quoted_known_term")
    if tokens & _REFERENCE_CONTEXT_TOKENS:
        cues.append("reference_context_token")
    if _symbolic_negated_execution(normalized):
        cues.append("symbolic_negated_execution")
    if _routing_context(normalized, tokens):
        cues.append("routing_context")
    if diagnostic_status_context:
        cues.append("diagnostic_status_context")
    return tuple(cues)


def _quoted_known_term_reference(message: str) -> bool:
    normalized = normalized_phrase(message)
    quoted_chunks = re.findall(r"[`\"']([^`\"']+)[`\"']", normalized)
    if not quoted_chunks:
        return False
    return any(any(term in chunk for term in _normalized_known_terms()) for chunk in quoted_chunks)


def _structural_reference_context(
    structural_cues: tuple[str, ...],
    *,
    workflow_or_specific_runtime: bool,
    routing_context: bool,
) -> bool:
    cues = set(structural_cues)
    if {"quoted_known_term", "symbolic_negated_execution"} & cues:
        return True
    return bool(
        "reference_context_token" in cues
        and workflow_or_specific_runtime
        and (routing_context or "workflow_marker" in cues)
    )


def _structural_negated_execution_cues(normalized: str) -> tuple[str, ...]:
    return ("symbolic_negated_execution",) if _symbolic_negated_execution(normalized) else ()


def _symbolic_negated_execution(normalized: str) -> bool:
    if "!=" not in normalized and "≠" not in normalized:
        return False
    return any(normalized_cue in normalized for _cue, normalized_cue in _normalized_cues(_EXECUTION_CUES))


def _matched_cues(cues: tuple[str, ...], normalized: str, compact: str) -> tuple[str, ...]:
    matches: list[str] = []
    for cue, normalized_cue in _normalized_cues(cues):
        if normalized_cue in normalized or normalized_cue.replace(" ", "") in compact:
            matches.append(cue)
    return tuple(matches)


def _diagnostic_status_context(normalized: str, compact: str) -> bool:
    for _marker, normalized_marker in _normalized_cues(_DIAGNOSTIC_STATUS_MARKERS):
        if normalized_marker in normalized or normalized_marker.replace(" ", "") in compact:
            return True
    return False


def _diagnostic_omh_evaluation_context(normalized: str, compact: str) -> bool:
    if not _diagnostic_status_context(normalized, compact):
        return False
    user_region = _without_diagnostic_status_lines(normalized)
    user_compact = user_region.replace(" ", "")
    has_user_omh_subject = bool(_matched_omh_system_target_cues(user_region))
    has_user_router_subject = _routing_context(user_region, set(user_region.split()))
    if not (has_user_omh_subject or has_user_router_subject):
        return False
    return bool(_matched_cues(_OMH_DIAGNOSTIC_EVALUATION_CUES, user_region, user_compact))


def _without_diagnostic_status_lines(normalized: str) -> str:
    kept: list[str] = []
    diagnostic_line_markers = _normalized_cues(_DIAGNOSTIC_STATUS_LINE_MARKERS)
    for line in normalized.splitlines() or [normalized]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[omh"):
            stripped = re.sub(r"^\[omh(?:\s+awareness|\s+route\s+hint)?\]\s*", "", stripped).strip()
            if not stripped:
                continue
        if stripped.startswith(("native bridge status context", "evidence boundary", "latest runtime run")):
            continue
        if any(normalized_marker in stripped for _marker, normalized_marker in diagnostic_line_markers):
            fragments = [fragment.strip() for fragment in re.split(r"[;|]", stripped)]
            user_fragments = [
                fragment
                for fragment in fragments
                if fragment and not any(normalized_marker in fragment for _marker, normalized_marker in diagnostic_line_markers)
            ]
            if user_fragments:
                kept.append(" ".join(user_fragments))
            continue
        kept.append(stripped)
    return "\n".join(kept)


def scrub_diagnostic_status_text(message: str) -> str:
    """Remove pasted/generated OMH status fragments while preserving user text."""
    normalized = normalized_phrase(message)
    compact = normalized.replace(" ", "")
    if not _diagnostic_status_context(normalized, compact):
        return message
    scrubbed = _without_diagnostic_status_lines(normalized)
    return scrubbed or normalized


def _compact_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return tuple(seen)


@lru_cache(maxsize=128)
def _normalized_cues(cues: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((cue, normalized) for cue in cues if (normalized := normalized_phrase(cue)))


@lru_cache(maxsize=128)
def _normalized_quality_cues(cues: tuple[str, ...]) -> tuple[tuple[str, str, bool], ...]:
    return tuple(
        (cue, normalized, _contains_non_ascii(normalized))
        for cue in cues
        if (normalized := normalized_phrase(cue))
    )


@lru_cache(maxsize=1)
def _normalized_workflow_vocabulary() -> tuple[tuple[str, str], ...]:
    return tuple(
        (workflow, normalized)
        for workflow in WORKFLOW_VOCABULARY
        if (normalized := normalized_phrase(workflow))
    )


@lru_cache(maxsize=1)
def _normalized_runtime_vocabulary() -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (term, label, normalized)
        for term, label in RUNTIME_VOCABULARY.items()
        if (normalized := normalized_phrase(term))
    )


@lru_cache(maxsize=1)
def _normalized_known_terms() -> tuple[str, ...]:
    workflow_terms = tuple(normalized for _workflow, normalized in _normalized_workflow_vocabulary())
    runtime_terms = tuple(normalized for _term, _label, normalized in _normalized_runtime_vocabulary())
    return workflow_terms + runtime_terms


def _suppress_negated_execution_cues(
    execution_cues: tuple[str, ...],
    negated_execution_cues: tuple[str, ...],
) -> tuple[str, ...]:
    if not negated_execution_cues:
        return execution_cues
    return tuple(cue for cue in execution_cues if cue not in _NEGATABLE_EXECUTION_CUES)


def _suppress_diagnostic_status_execution_cues(execution_cues: tuple[str, ...], normalized: str) -> tuple[str, ...]:
    return tuple(cue for cue in execution_cues if not _diagnostic_status_only_execution_cue(cue, normalized))


def _diagnostic_status_only_execution_cue(cue: str, normalized: str) -> bool:
    if cue == "execute":
        scrubbed = re.sub(r"\bnot_executed\b", " ", normalized)
        return not _contains_bounded_english_cue(scrubbed, "execute")
    if cue == "merge":
        scrubbed = re.sub(r"\bmerge_observed\b", " ", normalized)
        return not _contains_bounded_english_cue(scrubbed, "merge")
    return False


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
