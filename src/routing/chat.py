from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

from ..ingress import CHAT_SOURCES, extract_message_text
from .policy import CONFIDENCE_LEVELS, ROUTE_ACTIONS, is_ambiguous_scores, meets_confidence_threshold
from .recommend import recommend_skills
from ..skills.catalog import SkillDefinition, builtin_definitions, primary_harness_for_skill




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

    definitions = builtin_definitions()
    full_recommendations = recommend_skills(message, limit=len(definitions))
    recommendations = tuple(full_recommendations[:limit])
    top = full_recommendations[0]
    explicit_skill = explicit_skill_invocation(message, definitions)
    candidate_skill = str(top["skill"])
    candidate_harness = primary_harness_for_skill(candidate_skill)
    candidate_score = _int_value(top["score"])
    candidate_confidence = str(top["confidence"])
    ambiguous = _is_ambiguous(full_recommendations)

    if explicit_skill:
        selected_skill = explicit_skill
        action = "dispatch"
        reason = "Explicit workflow invocation wins over heuristic routing."
        ambiguous = False
    elif candidate_score == 0:
        selected_skill = "oh-my-hermes"
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        action = "fallback"
        reason = "No strong catalog metadata match; use the router to clarify the workflow."
    elif ambiguous:
        selected_skill = "oh-my-hermes"
        action = "clarify"
        reason = "Top catalog matches are tied; ask one concise clarification before dispatch."
    elif _meets_threshold(candidate_confidence, min_confidence):
        selected_skill = candidate_skill
        action = "dispatch"
        reason = str(top["why"])
    else:
        selected_skill = "oh-my-hermes"
        action = "clarify"
        reason = f"Best match confidence {candidate_confidence} is below {min_confidence}; clarify before dispatch."

    selected_harness = primary_harness_for_skill(selected_skill)
    clarification = _clarification(action, candidate_skill, candidate_confidence, min_confidence)
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
    )
    route["routing_prompt_template"] = _routing_prompt_template(
        str(route["action"]),
        str(route["selected_skill"]),
        str(route["candidate_skill"]),
        str(route["reason"]),
    )
    if not include_message:
        route.pop("routing_prompt", None)
    return route


def explicit_skill_invocation(message: str, definitions: list[SkillDefinition] | None = None) -> str | None:
    definitions = definitions or builtin_definitions()
    names = {definition.name for definition in definitions}
    first = message.strip().split(maxsplit=1)[0].strip(":,")
    for prefix in ("./", "/", "$", "@"):
        if first.startswith(prefix):
            first = first[len(prefix) :]
            break
    first = first.lower().strip(":,")
    return first if first in names else None


def routing_record_payload(
    decision: dict[str, object],
    message: str,
    *,
    source_event_id: str = "",
    channel_ref: str = "",
    user_ref: str = "",
) -> dict[str, object]:
    return {
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


def _is_ambiguous(recommendations: list[dict[str, object]]) -> bool:
    if len(recommendations) < 2:
        return False
    first = _int_value(recommendations[0]["score"])
    second = _int_value(recommendations[1]["score"])
    return is_ambiguous_scores(first, second)


def _meets_threshold(confidence: str, threshold: str) -> bool:
    return meets_confidence_threshold(confidence, threshold)


def _clarification(action: str, candidate_skill: str, candidate_confidence: str, threshold: str) -> str:
    if action == "dispatch":
        return ""
    if action == "fallback":
        return "Ask which workflow or outcome the user wants before choosing a specialist skill."
    return f"Ask whether to use `{candidate_skill}`; confidence was {candidate_confidence}, below threshold {threshold}."


def _routing_prompt(action: str, selected_skill: str, candidate_skill: str, reason: str, message: str) -> str:
    return _routing_prompt_template(action, selected_skill, candidate_skill, reason).replace("{message}", message)


def _routing_prompt_template(action: str, selected_skill: str, candidate_skill: str, reason: str) -> str:
    return f"{_routing_instruction(action, selected_skill, candidate_skill)}\n\nRouting reason: {reason}\n\nUser message:\n{{message}}"


def _routing_instruction(action: str, selected_skill: str, candidate_skill: str) -> str:
    if action == "dispatch":
        return f"Use the `{selected_skill}` workflow for this chat message."
    elif action == "clarify":
        return f"Use the `oh-my-hermes` router before dispatching to `{candidate_skill}`."
    return "Use the `oh-my-hermes` router and ask one concise clarification question."


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
