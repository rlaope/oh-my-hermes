from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from typing import Any

from ..goal_loop import explicit_loop_invocation_signal
from ..ingress import CHAT_SOURCES, extract_message_text
from .catalog_questions import is_file_or_text_lookup_question, is_skill_catalog_question
from .intent import scrub_diagnostic_status_text
from .policy import (
    CONFIDENCE_LEVELS,
    ROUTE_ACTIONS,
    explicit_skill_invocation as explicit_skill_name,
    is_ambiguous_scores,
    meets_confidence_threshold,
)
from .recommend import recommend_skills
from .route_plan import build_workflow_route_plan, compact_workflow_route_plan
from .task_cards import classify_task, task_card_recommendation
from ..learning_candidate import build_learning_candidate_card
from ..skills.catalog import SkillDefinition, primary_harness_for_skill, routable_definitions


FILE_LOOKUP_REASON = (
    "File or text lookup request; answer directly or ask for the target file instead of dispatching to a workflow keyword."
)
DIRECT_ANSWER_REASON = (
    "Plain user question; answer directly in chat instead of opening an OMH workflow or picker."
)
ROUTE_EXPLANATION_SCHEMA_VERSION = "route_explanation/v1"
_ROUTER_SKILL = "oh-my-hermes"
_SPECIFIC_CAPABILITY_CATALOG_MIN_SCORE = 6
_SPECIFIC_CAPABILITY_CATALOG_SKILLS = frozenset(
    {
        "agent-board",
        "agent-ops-review",
        "automation-blueprint",
        "deliverable-package",
        "code-review",
        "deep-interview",
        "executor-runtime-readiness",
        "feedback-triage",
        "github-event-ops",
        "img-summary",
        "idea-to-deploy",
        "loop",
        "materials-package",
        "memory-curation-review",
        "operating-rhythm",
        "ops-observability-card",
        "paper-learning",
        "ralplan",
        "report-package",
        "research-department",
        "source-finder",
        "strategy-brief",
        "toolbelt-readiness",
        "ultragoal",
        "ultraprocess",
        "voice-operator",
        "web-research",
        "workflow-learning",
    }
)
_BROAD_CAPABILITY_CATALOG_PHRASES = (
    "planning, research, and coding",
    "planning/research/coding",
    "planning, research, coding",
    "deep-interview/ralplan/loop",
    "계획/리서치/코딩",
    "플랜/리서치/코딩",
)
_BROAD_CAPABILITY_TOPIC_TOKENS = frozenset(
    {
        "planning",
        "plan",
        "research",
        "coding",
        "interview",
        "workflow",
        "workflows",
        "skill",
        "skills",
        "계획",
        "플랜",
        "리서치",
        "코딩",
        "워크플로",
        "워크플로우",
        "스킬",
    }
)
_DIRECT_PICKER_ALIASES = frozenset(("./omh", "/omh", "./skills", "/skills"))
_GENERIC_CATALOG_COLLECTION_MARKERS = (
    "workflow",
    "workflows",
    "skill",
    "skills",
    "command",
    "commands",
    "기능",
    "명령",
    "스킬",
    "워크플로",
    "워크플로우",
)
_GENERIC_CATALOG_LISTING_MARKERS = (
    "available",
    "installed",
    "do you have",
    "list",
    "show",
    "menu",
    "picker",
    "뭐 있어",
    "무엇이 있어",
    "목록",
    "리스트",
    "할 수 있는",
)
_DIRECT_ANSWER_STARTERS = (
    "what ",
    "what's ",
    "whats ",
    "how ",
    "how do ",
    "how can ",
    "why ",
    "please explain",
    "explain ",
    "describe ",
    "tell me ",
)
_DIRECT_ANSWER_KEYWORDS = (
    "python",
    "list comprehension",
    "path",
    "zsh",
    "bash",
    "shell",
    "stack trace",
    "error",
    "means",
    "mean",
    "concept",
)
_DIRECT_ANSWER_BLOCKERS = (
    "omh",
    "oh-my-hermes",
    "oh my hermes",
    "hermes",
    "workflow",
    "workflows",
    "skill",
    "skills",
    "codex",
    "claude",
    "pr",
    "issue",
    "repo",
    "repository",
    "codebase",
    "implement",
    "fix",
    "build",
    "create",
    "generate",
    "research",
    "paper",
    "pdf",
    "image",
    "poster",
    "summary card",
    "회의",
    "요약",
    "논문",
    "이미지",
    "기능",
    "스킬",
    "워크플로",
    "헤르메스",
)


@dataclass(frozen=True)
class ChatRouteDecision:
    schema_version: int
    source: str
    action: str
    selected_skill: str
    selected_harness: str
    candidate_skill: str
    candidate_harness: str
    confidence: str
    score: int
    threshold: str
    explicit: bool
    ambiguous: bool
    reason: str
    clarification: str
    routing_prompt: str
    task_card: dict[str, object] | None
    workflow_route_plan: dict[str, object] | None
    learning_candidate_card: dict[str, object] | None
    recommendations: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "action": self.action,
            "selected_skill": self.selected_skill,
            "selected_harness": self.selected_harness,
            "candidate_skill": self.candidate_skill,
            "candidate_harness": self.candidate_harness,
            "confidence": self.confidence,
            "score": self.score,
            "threshold": self.threshold,
            "explicit": self.explicit,
            "ambiguous": self.ambiguous,
            "reason": self.reason,
            "clarification": self.clarification,
            "routing_prompt": self.routing_prompt,
            "task_card": dict(self.task_card) if self.task_card else None,
            "workflow_route_plan": self.workflow_route_plan,
            "learning_candidate_card": (
                dict(self.learning_candidate_card) if self.learning_candidate_card else None
            ),
            "recommendations": [dict(recommendation) for recommendation in self.recommendations],
        }


@dataclass(frozen=True)
class _CatalogFastPathResult:
    decision: ChatRouteDecision | None
    catalog_question: bool


def route_chat_message(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    min_confidence: str = "high",
) -> dict[str, object]:
    message = message.strip()
    if not message:
        raise ValueError("chat route requires a message")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported chat source: {source}")
    if limit < 1:
        raise ValueError("chat route --limit must be at least 1")
    if min_confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"unsupported chat route confidence threshold: {min_confidence}")

    return _clone_jsonish(_route_chat_message_cached(message, source, limit, min_confidence))


def public_chat_route_payload(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    min_confidence: str = "high",
    include_message: bool = False,
) -> dict[str, object]:
    message = message.strip()
    if not message:
        raise ValueError("chat route requires a message")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported chat source: {source}")
    if limit < 1:
        raise ValueError("chat route --limit must be at least 1")
    if min_confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"unsupported chat route confidence threshold: {min_confidence}")
    return _clone_jsonish(
        _public_chat_route_payload_cached(
            message,
            source,
            limit,
            min_confidence,
            include_message,
        )
    )


@lru_cache(maxsize=2048)
def _route_chat_message_cached(
    message: str,
    source: str,
    limit: int,
    min_confidence: str,
) -> dict[str, object]:
    routing_message = scrub_diagnostic_status_text(message)
    fast_catalog_decision = _catalog_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_catalog_decision.decision is not None:
        return fast_catalog_decision.decision.to_dict()

    definitions = routable_definitions()
    full_recommendations = recommend_skills(routing_message, limit=len(definitions))
    explicit_skill = explicit_skill_invocation(routing_message, definitions)
    task_card = classify_task(message)
    explicit_prefix = _has_explicit_invocation_prefix(routing_message)
    task_card_overrides_explicit = _task_card_overrides_explicit_invocation(
        task_card,
        explicit_prefix=explicit_prefix,
    )
    if task_card and (not explicit_skill or task_card_overrides_explicit):
        full_recommendations = _prioritize_recommendation(full_recommendations, task_card_recommendation(task_card))
    catalog_question = fast_catalog_decision.catalog_question
    specific_catalog_match = (
        _specific_capability_catalog_match(full_recommendations)
        if catalog_question and not _is_broad_capability_catalog_question(routing_message)
        else None
    )
    if specific_catalog_match is not None:
        full_recommendations = _prioritize_recommendation(full_recommendations, specific_catalog_match)
    recommendations = tuple(full_recommendations[:limit])
    top = full_recommendations[0]
    candidate_skill = str(top["skill"])
    candidate_harness = primary_harness_for_skill(candidate_skill)
    candidate_score = _int_value(top["score"])
    candidate_confidence = str(top["confidence"])
    ambiguous = _is_ambiguous(full_recommendations)
    explicit_loop_signal = _explicit_loop_signal(routing_message, full_recommendations)
    file_or_text_lookup = is_file_or_text_lookup_question(routing_message)
    direct_answer = _is_plain_direct_answer_question(
        routing_message,
        candidate_score=candidate_score,
    )

    if explicit_skill and not task_card_overrides_explicit:
        selected_skill = explicit_skill
        action = "dispatch"
        reason = "Explicit workflow invocation wins over heuristic routing."
        ambiguous = False
        task_card = None
    elif task_card:
        selected_skill = str(task_card.get("selected_workflow_rail", candidate_skill))
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = max(candidate_score, _int_value(task_card.get("score", 0)))
        candidate_confidence = str(task_card.get("confidence", "high"))
        action = "dispatch"
        reason = str(task_card.get("routing_reason", "Matched high-level task abstraction before workflow routing."))
        ambiguous = False
    elif catalog_question and specific_catalog_match is not None:
        selected_skill = candidate_skill
        action = "dispatch"
        reason = (
            f"Specific OMH capability question matched `{candidate_skill}`; "
            "show that workflow card instead of the generic workflow picker."
        )
        ambiguous = False
    elif catalog_question:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = max(candidate_score, 11)
        candidate_confidence = "high"
        action = "dispatch"
        reason = "Catalog question; show the OMH workflow picker instead of asking for shell command approval."
        ambiguous = False
    elif file_or_text_lookup:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = 0
        candidate_confidence = "low"
        action = "fallback"
        reason = FILE_LOOKUP_REASON
        ambiguous = False
    elif direct_answer:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = 0
        candidate_confidence = "low"
        action = "fallback"
        reason = DIRECT_ANSWER_REASON
        ambiguous = False
    elif explicit_loop_signal:
        selected_skill = "loop"
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = max(candidate_score, 10)
        candidate_confidence = "high"
        action = "dispatch"
        reason = "Explicit loop invocation; start or continue the goal loop instead of opening a picker."
        ambiguous = False
    elif candidate_score == 0:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        action = "fallback"
        reason = "No strong catalog metadata match; use the router to clarify the workflow."
    elif ambiguous:
        selected_skill = _ROUTER_SKILL
        action = "clarify"
        reason = "Top catalog matches are tied; ask one concise clarification before dispatch."
    elif _meets_threshold(candidate_confidence, min_confidence):
        selected_skill = candidate_skill
        action = "dispatch"
        reason = str(top["why"])
    else:
        selected_skill = _ROUTER_SKILL
        action = "clarify"
        reason = f"Best match confidence {candidate_confidence} is below {min_confidence}; clarify before dispatch."

    selected_harness = primary_harness_for_skill(selected_skill)
    learning_candidate_card = build_learning_candidate_card(
        message,
        source=source,
        selected_workflow=selected_skill,
        selected_harness=selected_harness,
    )
    if learning_candidate_card:
        selected_skill = str(learning_candidate_card.get("recommended_workflow", selected_skill))
        selected_harness = primary_harness_for_skill(selected_skill)
        candidate_skill = selected_skill
        candidate_harness = selected_harness
        candidate_score = max(candidate_score, 12)
        candidate_confidence = "high"
        action = "dispatch"
        ambiguous = False
        reason = "Explicit learning signal; prepare a reviewable learning candidate card without running Hermes /learn."
        learning_candidate_card = build_learning_candidate_card(
            message,
            source=source,
            selected_workflow=selected_skill,
            selected_harness=selected_harness,
        )
    workflow_route_plan = build_workflow_route_plan(
        message,
        full_recommendations,
        selected_skill=selected_skill,
        action=action,
    )
    clarification = _clarification(action, candidate_skill, candidate_confidence, min_confidence, reason)
    decision = ChatRouteDecision(
        schema_version=1,
        source=source,
        action=action,
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=candidate_skill,
        candidate_harness=candidate_harness,
        confidence="high" if (explicit_skill and not task_card_overrides_explicit) or explicit_loop_signal else candidate_confidence,
        score=max(candidate_score, 1) if (explicit_skill and not task_card_overrides_explicit) or explicit_loop_signal else candidate_score,
        threshold=min_confidence,
        explicit=bool((explicit_skill and not task_card_overrides_explicit) or explicit_loop_signal),
        ambiguous=ambiguous,
        reason=reason,
        clarification=clarification,
        routing_prompt=_routing_prompt(action, selected_skill, candidate_skill, reason, message),
        task_card=task_card,
        workflow_route_plan=workflow_route_plan,
        learning_candidate_card=learning_candidate_card,
        recommendations=recommendations,
    )
    return decision.to_dict()


@lru_cache(maxsize=2048)
def _public_chat_route_payload_cached(
    message: str,
    source: str,
    limit: int,
    min_confidence: str,
    include_message: bool,
) -> dict[str, object]:
    return public_route_payload(
        _route_chat_message_cached(message, source, limit, min_confidence),
        include_message=include_message,
    )


def _clone_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clone_jsonish(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_jsonish(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clone_jsonish(item) for item in value)
    return value


def _has_explicit_invocation_prefix(message: str) -> bool:
    first = message.strip().split(maxsplit=1)[0].strip(":,").lower()
    return first.startswith(("$", "/", "./", "@"))


def _catalog_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> _CatalogFastPathResult:
    direct_picker = _direct_picker_alias(routing_message)
    catalog_question = False if direct_picker else is_skill_catalog_question(routing_message)
    catalog_picker = (
        not direct_picker
        and catalog_question
        and _generic_omh_catalog_question(routing_message)
    )
    if not direct_picker and not catalog_picker:
        return _CatalogFastPathResult(decision=None, catalog_question=catalog_question)

    matched = ("direct_picker_alias",) if direct_picker else ("catalog_question",)
    score = 12 if direct_picker else 11
    reason = (
        "Direct OMH picker alias; show the workflow picker without scoring every workflow."
        if direct_picker
        else "Catalog question; show the OMH workflow picker instead of asking for shell command approval."
    )
    selected_harness = primary_harness_for_skill(_ROUTER_SKILL)
    recommendation = _router_picker_recommendation(message, matched=matched, score=score)
    return _CatalogFastPathResult(
        decision=ChatRouteDecision(
            schema_version=1,
            source=source,
            action="dispatch",
            selected_skill=_ROUTER_SKILL,
            selected_harness=selected_harness,
            candidate_skill=_ROUTER_SKILL,
            candidate_harness=selected_harness,
            confidence="high",
            score=score,
            threshold=min_confidence,
            explicit=direct_picker,
            ambiguous=False,
            reason=reason,
            clarification="",
            routing_prompt=_routing_prompt("dispatch", _ROUTER_SKILL, _ROUTER_SKILL, reason, message),
            task_card=None,
            workflow_route_plan=None,
            learning_candidate_card=None,
            recommendations=(recommendation,),
        ),
        catalog_question=catalog_question,
    )


def _direct_picker_alias(message: str) -> bool:
    compact = message.strip().lower().strip(" \t\r\n.!?,;:")
    return compact in _DIRECT_PICKER_ALIASES


def _generic_omh_catalog_question(message: str) -> bool:
    text = message.strip().lower()
    if _is_broad_capability_catalog_question(text):
        return True
    if not any(marker in text for marker in ("omh", "oh-my-hermes", "oh my hermes")):
        return False
    named_hits = sum(1 for skill in _SPECIFIC_CAPABILITY_CATALOG_SKILLS if skill in text)
    if named_hits:
        return False
    has_collection = any(marker in text for marker in _GENERIC_CATALOG_COLLECTION_MARKERS)
    has_listing_intent = any(marker in text for marker in _GENERIC_CATALOG_LISTING_MARKERS)
    return has_collection and has_listing_intent


def _router_picker_recommendation(query: str, *, matched: tuple[str, ...], score: int) -> dict[str, object]:
    definition = _router_skill_definition()
    return {
        "skill": definition.name,
        "description": definition.description,
        "category": definition.category,
        "phase": definition.phase,
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        "score": score,
        "confidence": "high",
        "matched": list(matched),
        "why": "Matched the OMH workflow picker entry point.",
        "next_action": "choose_skill",
        "evidence_boundary": (
            "Skill picker routing is not plan acceptance, dispatch, execution, review, CI, or verification evidence."
        ),
        "wrapper_guidance": (
            "Render the OMH workflow picker in chat; do not ask the user to approve `omh list` for catalog discovery."
        ),
        "suggested_prompt": f"Use oh-my-hermes for: {query}",
    }


@lru_cache(maxsize=1)
def _router_skill_definition() -> SkillDefinition:
    for definition in routable_definitions():
        if definition.name == _ROUTER_SKILL:
            return definition
    raise RuntimeError("oh-my-hermes router skill definition is missing")


def _task_card_overrides_explicit_invocation(
    task_card: dict[str, object] | None,
    *,
    explicit_prefix: bool,
) -> bool:
    if not isinstance(task_card, dict):
        return False
    task_type = task_card.get("task_type")
    if task_type == "omh_cli_maintenance":
        return True
    if task_type == "router_design_feedback":
        return not explicit_prefix
    return False


def route_chat_event(
    event: dict[str, Any] | str,
    *,
    source: str = "generic",
    limit: int = 3,
    min_confidence: str = "high",
) -> dict[str, object]:
    return route_chat_message(extract_message_text(event), source=source, limit=limit, min_confidence=min_confidence)


def public_route_payload(decision: dict[str, object], *, include_message: bool = False) -> dict[str, object]:
    route = dict(decision)
    route["recommendations"] = _compact_recommendations(route.get("recommendations", []))
    route["routing_instruction"] = _routing_instruction(
        str(route["action"]),
        str(route["selected_skill"]),
        str(route["candidate_skill"]),
        str(route["reason"]),
    )
    route["routing_prompt_template"] = _routing_prompt_template(
        str(route["action"]),
        str(route["selected_skill"]),
        str(route["candidate_skill"]),
        str(route["reason"]),
    )
    if not include_message:
        route.pop("routing_prompt", None)
    if not route.get("task_card"):
        route.pop("task_card", None)
    if not route.get("learning_candidate_card"):
        route.pop("learning_candidate_card", None)
    workflow_route_plan = compact_workflow_route_plan(route.get("workflow_route_plan"))
    if workflow_route_plan:
        route["workflow_route_plan"] = workflow_route_plan
    else:
        route.pop("workflow_route_plan", None)
    route["route_explanation"] = route_explanation_payload(route)
    return route


def route_explanation_payload(route: dict[str, object]) -> dict[str, object]:
    """Build a compact human-facing explanation without storing the raw message."""
    action = str(route.get("action", "fallback"))
    selected = str(route.get("selected_skill", ""))
    harness = str(route.get("selected_harness", "")) or primary_harness_for_skill(selected)
    recommendation = _selected_recommendation(route)
    next_action = _route_next_action(route, recommendation)
    claim_boundary = _route_claim_boundary(route, recommendation)
    why = _route_explanation_reason(route)
    not_evidence_yet = _not_evidence_from_boundary(claim_boundary)
    headline = _route_explanation_headline(action, selected, next_action)
    summary = _route_explanation_summary(action, selected, next_action, why)
    next_action_label = next_action.replace("_", " ") if next_action else ""
    return {
        "schema_version": ROUTE_EXPLANATION_SCHEMA_VERSION,
        "selected_workflow": selected,
        "selected_harness": harness,
        "action": action,
        "confidence": str(route.get("confidence", "low")),
        "score": _int_value(route.get("score", 0)),
        "why_this_workflow": why,
        "next_action": next_action,
        "next_action_label": next_action_label,
        "recommended_reply": _route_recommended_reply(action, selected, next_action_label, not_evidence_yet),
        "primary_action_label": _route_primary_action_label(action, selected, next_action_label),
        "primary_action_hint": _route_primary_action_hint(action, selected, next_action_label, not_evidence_yet),
        "not_evidence_yet": not_evidence_yet,
        "claim_boundary": claim_boundary,
        "headline": headline,
        "summary": summary,
        "rendering_hint": "Show this as the compact why / next / not-yet-evidence card in chat surfaces.",
    }


def explicit_skill_invocation(message: str, definitions: list[SkillDefinition] | None = None) -> str | None:
    definitions = definitions or routable_definitions()
    return explicit_skill_name(message, {definition.name for definition in definitions})


def _explicit_loop_signal(message: str, recommendations: list[dict[str, object]]) -> bool:
    has_loop_recommendation = any(str(item.get("skill", "")) == "loop" for item in recommendations[:3])
    if not has_loop_recommendation:
        return False
    return explicit_loop_invocation_signal(message)


def routing_record_payload(
    decision: dict[str, object],
    message: str,
    *,
    source_event_id: str = "",
    channel_ref: str = "",
    user_ref: str = "",
) -> dict[str, object]:
    payload = {
        "source": decision["source"],
        "action": decision["action"],
        "selected_skill": decision["selected_skill"],
        "selected_harness": decision["selected_harness"],
        "candidate_skill": decision["candidate_skill"],
        "candidate_harness": decision["candidate_harness"],
        "confidence": decision["confidence"],
        "score": decision["score"],
        "threshold": decision["threshold"],
        "explicit": decision["explicit"],
        "ambiguous": decision["ambiguous"],
        "reason": decision["reason"],
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "message_length": len(message),
        "source_event_id": source_event_id,
        "channel_ref": channel_ref,
        "user_ref": user_ref,
        "recommendations": _compact_recommendations(decision.get("recommendations", [])),
    }
    workflow_route_plan = compact_workflow_route_plan(decision.get("workflow_route_plan"))
    if workflow_route_plan:
        payload["workflow_route_plan"] = workflow_route_plan
    task_card = decision.get("task_card")
    if isinstance(task_card, dict) and task_card:
        payload["task_card"] = task_card
    learning_candidate_card = decision.get("learning_candidate_card")
    if isinstance(learning_candidate_card, dict) and learning_candidate_card:
        payload["learning_candidate_card"] = learning_candidate_card
    return payload


def _is_ambiguous(recommendations: list[dict[str, object]]) -> bool:
    if len(recommendations) < 2:
        return False
    first = _int_value(recommendations[0]["score"])
    second = _int_value(recommendations[1]["score"])
    return is_ambiguous_scores(first, second)


def _meets_threshold(confidence: str, threshold: str) -> bool:
    return meets_confidence_threshold(confidence, threshold)


def _specific_capability_catalog_match(recommendations: list[dict[str, object]]) -> dict[str, object] | None:
    for recommendation in recommendations:
        skill = str(recommendation.get("skill", ""))
        if skill == _ROUTER_SKILL or skill not in _SPECIFIC_CAPABILITY_CATALOG_SKILLS:
            continue
        if _int_value(recommendation.get("score", 0)) < _SPECIFIC_CAPABILITY_CATALOG_MIN_SCORE:
            continue
        confidence = str(recommendation.get("confidence", "low"))
        if not _meets_threshold(confidence, "high"):
            continue
        matched = _string_list(recommendation.get("matched", []))
        next_action = str(recommendation.get("next_action", ""))
        if not next_action or next_action == "clarify_or_route":
            continue
        if any(item.startswith("guard:") for item in matched) or any(item.startswith("trigger:") for item in matched):
            return recommendation
    return None


def _is_broad_capability_catalog_question(message: str) -> bool:
    text = message.strip().lower()
    if any(phrase in text for phrase in _BROAD_CAPABILITY_CATALOG_PHRASES):
        return True
    if "/" in text or "," in text:
        topic_hits = sum(1 for token in _BROAD_CAPABILITY_TOPIC_TOKENS if token in text)
        if topic_hits >= 2:
            return True
    named_hits = sum(1 for skill in _SPECIFIC_CAPABILITY_CATALOG_SKILLS if skill in text)
    return named_hits >= 2


def _prioritize_recommendation(
    recommendations: list[dict[str, object]],
    selected: dict[str, object],
) -> list[dict[str, object]]:
    selected_skill = str(selected.get("skill", ""))
    return [selected] + [item for item in recommendations if str(item.get("skill", "")) != selected_skill]


def _clarification(action: str, candidate_skill: str, candidate_confidence: str, threshold: str, reason: str = "") -> str:
    if action == "dispatch":
        return ""
    if action == "fallback":
        if _is_file_lookup_reason(reason):
            return "Answer this as a file or text lookup, or ask for the target file/path if it is missing."
        if _is_direct_answer_reason(reason):
            return "Answer directly in the current chat; do not open an OMH workflow unless the user asks for one."
        return "Ask which workflow or outcome the user wants before choosing a specialist skill."
    return f"Ask whether to use `{candidate_skill}`; confidence was {candidate_confidence}, below threshold {threshold}."


def _routing_prompt(action: str, selected_skill: str, candidate_skill: str, reason: str, message: str) -> str:
    return _routing_prompt_template(action, selected_skill, candidate_skill, reason).replace("{message}", message)


def _routing_prompt_template(action: str, selected_skill: str, candidate_skill: str, reason: str) -> str:
    return f"{_routing_instruction(action, selected_skill, candidate_skill, reason)}\n\nRouting reason: {reason}\n\nUser message:\n{{message}}"


def _routing_instruction(action: str, selected_skill: str, candidate_skill: str, reason: str = "") -> str:
    if action == "dispatch":
        return f"Use the `{selected_skill}` workflow for this chat message."
    elif action == "clarify":
        return f"Use the `oh-my-hermes` router before dispatching to `{candidate_skill}`."
    if _is_file_lookup_reason(reason):
        return "Answer this as a file or text lookup; do not dispatch to a workflow keyword unless the user explicitly asks."
    if _is_direct_answer_reason(reason):
        return "Answer directly in chat; do not open an OMH workflow, picker, or coding handoff."
    return "Use the `oh-my-hermes` router and ask one concise clarification question."


def _is_file_lookup_reason(reason: str) -> bool:
    return reason == FILE_LOOKUP_REASON


def _is_direct_answer_reason(reason: str) -> bool:
    return reason == DIRECT_ANSWER_REASON


def _is_plain_direct_answer_question(message: str, *, candidate_score: int) -> bool:
    if candidate_score > 4:
        return False
    text = message.strip().lower()
    if not text:
        return False
    if _contains_direct_answer_blocker(text):
        return False
    if any(text.startswith(starter) for starter in _DIRECT_ANSWER_STARTERS):
        return True
    return any(keyword in text for keyword in _DIRECT_ANSWER_KEYWORDS) and "?" in text


def _contains_direct_answer_blocker(text: str) -> bool:
    word_text = f" {' '.join(''.join(character if character.isalnum() else ' ' for character in text).split())} "
    for marker in _DIRECT_ANSWER_BLOCKERS:
        if marker.isascii() and marker.replace("-", "").replace(" ", "").isalnum():
            if f" {marker} " in word_text:
                return True
        elif marker in text:
            return True
    return False


def _compact_recommendations(recommendations: object) -> list[dict[str, object]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, object]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": _int_value(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": _string_list(item.get("matched", [])),
                "next_action": str(item.get("next_action", "")),
                "evidence_boundary": str(item.get("evidence_boundary", "")),
                "wrapper_guidance": str(item.get("wrapper_guidance", "")),
            }
        )
    return compact


def _selected_recommendation(route: dict[str, object]) -> dict[str, object]:
    selected = str(route.get("selected_skill", ""))
    recommendations = route.get("recommendations", [])
    if not isinstance(recommendations, list):
        return {}
    first: dict[str, object] = {}
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        if not first:
            first = item
        if str(item.get("skill", "")) == selected:
            return item
    return first


def _route_next_action(route: dict[str, object], recommendation: dict[str, object]) -> str:
    action = str(route.get("action", "fallback"))
    if action == "dispatch":
        return str(recommendation.get("next_action") or "dispatch_to_workflow")
    if action == "fallback" and _is_file_lookup_reason(str(route.get("reason", ""))):
        return "answer_file_lookup"
    if action == "fallback" and _is_direct_answer_reason(str(route.get("reason", ""))):
        return "answer_directly"
    if action == "clarify":
        return "answer_clarification"
    return "ask_one_clarification"


def _route_claim_boundary(route: dict[str, object], recommendation: dict[str, object]) -> str:
    if _is_file_lookup_reason(str(route.get("reason", ""))):
        return "No OMH workflow, execution, or file inspection has started."
    if _is_direct_answer_reason(str(route.get("reason", ""))):
        return "No OMH workflow, picker, handoff, execution, or file inspection has started."
    boundary = str(recommendation.get("evidence_boundary", "")).strip()
    if boundary:
        return boundary
    if str(route.get("action", "")) == "dispatch":
        return "Routing guidance is not workflow execution evidence."
    return "No execution has started."


def _route_explanation_reason(route: dict[str, object]) -> str:
    reason = str(route.get("reason", "")).strip()
    if reason:
        return _human_route_reason(reason)
    clarification = str(route.get("clarification", "")).strip()
    if clarification:
        return clarification
    return "Selected from catalog metadata, trigger phrases, and deterministic guardrail policy."


def _human_route_reason(reason: str) -> str:
    for prefix in (
        "Matched guard/trigger metadata; ",
        "Matched high-level task abstraction before workflow routing. ",
    ):
        if reason.startswith(prefix):
            return _capitalize_sentence(reason[len(prefix) :])
    return reason


def _capitalize_sentence(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _route_explanation_headline(action: str, selected: str, next_action: str) -> str:
    if action == "dispatch":
        return f"Use `{selected}` for this request."
    if action == "clarify":
        return "Ask one question before choosing a workflow."
    if next_action == "answer_file_lookup":
        return "Answer as a file or text lookup."
    if next_action == "answer_directly":
        return "Answer directly in chat."
    return "Keep this in the router until the target is clear."


def _route_explanation_summary(action: str, selected: str, next_action: str, why: str) -> str:
    if action == "dispatch":
        return f"`{selected}` is selected because {why} Next action: `{next_action}`."
    if action == "clarify":
        return f"The router needs one clarification before dispatch. Best candidate: `{selected}`."
    if next_action == "answer_file_lookup":
        return f"Answer directly as a file or text lookup; do not dispatch a workflow. Reason: {why}"
    if next_action == "answer_directly":
        return f"Answer directly without opening an OMH workflow. Reason: {why}"
    return f"The router should not dispatch yet. Reason: {why}"


def _route_recommended_reply(
    action: str,
    selected: str,
    next_action_label: str,
    not_evidence_yet: list[str],
) -> str:
    if action == "dispatch":
        not_evidence = _first_not_evidence(not_evidence_yet)
        suffix = f" This is still not {not_evidence} evidence." if not_evidence else " This is routing guidance, not execution evidence."
        return f"I will use `{selected}` first and start with {next_action_label}.{suffix}"
    if action == "clarify":
        return "I need one clarification before choosing a workflow; no plan or execution has started."
    if next_action_label == "answer file lookup":
        return "I will answer this as a file or text lookup; no file inspection or workflow execution has started."
    if next_action_label == "answer directly":
        return "I will answer directly in chat; no OMH workflow, handoff, or execution has started."
    return "I will keep this in the router until the target is clear; no workflow or execution has started."


def _route_primary_action_label(action: str, selected: str, next_action_label: str) -> str:
    if action == "dispatch":
        return f"Open {selected}"
    if action == "clarify":
        return "Answer clarification"
    if next_action_label == "answer file lookup":
        return "Answer file lookup"
    if next_action_label == "answer directly":
        return "Answer directly"
    return "Clarify request"


def _route_primary_action_hint(
    action: str,
    selected: str,
    next_action_label: str,
    not_evidence_yet: list[str],
) -> str:
    if action == "dispatch":
        not_evidence = _first_not_evidence(not_evidence_yet)
        suffix = f"; do not claim {not_evidence} until observed" if not_evidence else "; keep evidence claims separate"
        return f"Route to `{selected}` and run `{next_action_label}`{suffix}."
    if action == "clarify":
        return "Ask one blocking question, then reroute with the answer."
    if next_action_label == "answer directly":
        return "Answer in the current chat without opening a workflow, picker, or handoff."
    return "Answer directly or ask for the missing target before dispatching a workflow."


def _first_not_evidence(items: list[str]) -> str:
    return items[0].replace("_", " ") if items else ""


def _not_evidence_from_boundary(boundary: str) -> list[str]:
    text = boundary.lower()
    if "file inspection" in text:
        items = ["file inspection"]
        if "execution" in text:
            items.append("execution")
        return items
    items: list[str] = []
    for marker, label in (
        ("plan acceptance", "plan acceptance"),
        ("dispatch", "executor/runtime dispatch"),
        ("execution", "execution"),
        ("implementation", "implementation"),
        ("image", "image generation"),
        ("file", "file generation/export"),
        ("download", "download"),
        ("search", "source retrieval"),
        ("api", "API access"),
        ("credential", "credential validation"),
        ("connector", "connector invocation"),
        ("delivery", "delivery"),
        ("attachment", "attachment"),
        ("review", "review"),
        ("verification", "verification"),
        ("ci", "CI"),
        ("merge", "merge"),
    ):
        if marker in text and label not in items:
            items.append(label)
    if items:
        return items
    if "prepared" in text:
        return ["execution", "verification", "delivery"]
    if "no execution" in text:
        return ["execution"]
    return ["completion claim without observed evidence"]


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
