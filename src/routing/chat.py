from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

from ..ingress import CHAT_SOURCES, extract_message_text
from .catalog_questions import is_file_or_text_lookup_question, is_skill_catalog_question
from .policy import (
    CONFIDENCE_LEVELS,
    ROUTE_ACTIONS,
    explicit_skill_invocation as explicit_skill_name,
    is_ambiguous_scores,
    meets_confidence_threshold,
)
from .recommend import recommend_skills
from .task_cards import classify_task, task_card_recommendation
from ..skills.catalog import SkillDefinition, primary_harness_for_skill, routable_definitions


FILE_LOOKUP_REASON = (
    "File or text lookup request; answer directly or ask for the target file instead of dispatching to a workflow keyword."
)
_ROUTER_SKILL = "oh-my-hermes"
_SPECIFIC_CAPABILITY_CATALOG_MIN_SCORE = 6
_SPECIFIC_CAPABILITY_CATALOG_SKILLS = frozenset(
    {
        "agent-board",
        "agent-ops-review",
        "automation-blueprint",
        "deliverable-package",
        "executor-runtime-readiness",
        "feedback-triage",
        "github-event-ops",
        "img-summary",
        "loop",
        "materials-package",
        "memory-curation-review",
        "operating-rhythm",
        "ops-observability-card",
        "paper-learning",
        "report-package",
        "research-department",
        "source-finder",
        "strategy-brief",
        "toolbelt-readiness",
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
    recommendations: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["recommendations"] = list(self.recommendations)
        return data


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

    definitions = routable_definitions()
    full_recommendations = recommend_skills(message, limit=len(definitions))
    explicit_skill = explicit_skill_invocation(message, definitions)
    task_card = classify_task(message)
    if task_card and not explicit_skill:
        full_recommendations = _prioritize_recommendation(full_recommendations, task_card_recommendation(task_card))
    catalog_question = is_skill_catalog_question(message)
    specific_catalog_match = (
        _specific_capability_catalog_match(full_recommendations)
        if catalog_question and not _is_broad_capability_catalog_question(message)
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
    file_or_text_lookup = is_file_or_text_lookup_question(message)

    if explicit_skill:
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
    clarification = _clarification(action, candidate_skill, candidate_confidence, min_confidence, reason)
    decision = ChatRouteDecision(
        schema_version=1,
        source=source,
        action=action,
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=candidate_skill,
        candidate_harness=candidate_harness,
        confidence="high" if explicit_skill else candidate_confidence,
        score=max(candidate_score, 1) if explicit_skill else candidate_score,
        threshold=min_confidence,
        explicit=bool(explicit_skill),
        ambiguous=ambiguous,
        reason=reason,
        clarification=clarification,
        routing_prompt=_routing_prompt(action, selected_skill, candidate_skill, reason, message),
        task_card=task_card,
        recommendations=recommendations,
    )
    return decision.to_dict()


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
    return route


def explicit_skill_invocation(message: str, definitions: list[SkillDefinition] | None = None) -> str | None:
    definitions = definitions or routable_definitions()
    return explicit_skill_name(message, {definition.name for definition in definitions})


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
    task_card = decision.get("task_card")
    if isinstance(task_card, dict) and task_card:
        payload["task_card"] = task_card
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
    return "Use the `oh-my-hermes` router and ask one concise clarification question."


def _is_file_lookup_reason(reason: str) -> bool:
    return reason == FILE_LOOKUP_REASON


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
