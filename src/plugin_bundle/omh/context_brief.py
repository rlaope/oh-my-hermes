from __future__ import annotations

import hashlib

from .awareness import (
    awareness_generic_tool_checkpoint_payload,
    awareness_primer_context,
    awareness_primer_payload,
    awareness_route_hint,
    awareness_route_hint_context_from_payload,
)

OMH_CONTEXT_BRIEF_SCHEMA_VERSION = "omh_context_brief/v1"


def build_context_brief(
    message: str = "",
    *,
    source: str = "generic",
    max_hints: int = 2,
    include_prompt_context: bool = False,
    route_hint_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build bounded Hermes-facing OMH operating context."""
    text = str(message or "")
    limit = bounded_context_hint_limit(max_hints, default=2)
    primer = awareness_primer_payload()
    if route_hint_payload is not None:
        route_hint = route_hint_payload
    elif text.strip():
        route_hint = awareness_route_hint(text, max_hints=limit)
    else:
        route_hint = awareness_route_hint("", max_hints=0)
    payload: dict[str, object] = {
        "schema_version": OMH_CONTEXT_BRIEF_SCHEMA_VERSION,
        "source": source,
        "purpose": (
            "Give Hermes a compact OMH mental model before generic chat, image, file, search, or coding tools."
        ),
        "message": {
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
            "length": len(text),
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
        },
        "chat_rule": primer["chat_rule"],
        "first_turn_rule": primer["first_turn_rule"],
        "all_skill_context_rule": primer["all_skill_context_rule"],
        "capability_families": _capability_family_cards(),
        "lanes": primer["lanes"],
        "workflow_context_cards": primer["workflow_context_cards"],
        "workflow_cues": primer["workflow_cues"],
        "generic_tool_checkpoint": awareness_generic_tool_checkpoint_payload(),
        "route_hint": route_hint,
        "tool_hints": primer["tool_hints"],
        "fallback_rule": primer["fallback_rule"],
        "evidence_boundary": primer["evidence_boundary"],
        "normal_response_contract": {
            "schema_version": "omh_context_response_contract/v1",
            "when_user_asks_capabilities": "Summarize lanes and offer the workflow picker instead of requesting shell approval.",
            "when_request_matches_lane": "Name the OMH workflow, the reason, the next action, and what is not evidence yet.",
            "when_generic_tool_is_available": (
                "Do not skip OMH merely because a generic tool can render, search, edit files, or run code."
            ),
            "when_missing_connector_or_executor": (
                "Offer setup or selection fallback instead of claiming generation, delivery, dispatch, or execution."
            ),
        },
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
            "stored_fields": ["message hash", "message length", "matched cue labels", "workflow hint"],
        },
        "claim_boundary": (
            "OMH context is advisory routing and status context only. It is not workflow execution, image generation, "
            "file export, source retrieval, executor dispatch, implementation, verification, review, CI, merge, "
            "delivery, or proof that live Hermes selected the workflow."
        ),
    }
    if include_prompt_context:
        prompt_context_parts = [awareness_primer_context()]
        route_hint_context = awareness_route_hint_context_from_payload(route_hint) if text.strip() else ""
        if route_hint_context:
            prompt_context_parts.append(route_hint_context)
        payload["prompt_context"] = "\n".join(prompt_context_parts)
        payload["prompt_context_boundary"] = (
            "Prompt context is for Hermes routing guidance only; it is not workflow execution or observed evidence."
        )
    catalog_hint = _catalog_question_hint(text)
    if catalog_hint:
        payload["catalog_question"] = catalog_hint
    return payload


def _capability_family_cards() -> list[dict[str, object]]:
    try:
        from omh.capabilities.families import capability_family_cards
    except ImportError:
        from .tools.capability_tool import standalone_capability_family_cards

        return standalone_capability_family_cards()
    return capability_family_cards()


def bounded_context_hint_limit(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, 10))


def _catalog_question_hint(message: str) -> dict[str, object]:
    if not _is_catalog_question(message):
        return {}
    return {
        "schema_version": "omh_catalog_question_hint/v1",
        "status": "matched",
        "next_action": "show_workflow_picker",
        "recommended_tool": "omh_capabilities",
        "recommended_tool_args": {"action": "summary"},
        "wrapper_contracts": ["omh_skill_picker/v1", "omh_capability_summary/v1"],
        "direct_invocation_aliases": ["./omh", "/omh", "./skills", "/skills"],
        "response_rule": (
            "Answer in chat by summarizing OMH lanes and offering the workflow picker; "
            "do not ask the user to approve `omh list` for catalog discovery."
        ),
        "claim_boundary": (
            "A catalog answer or workflow picker is routing/help context only; it is not plan acceptance, dispatch, "
            "execution, review, CI, or verification evidence."
        ),
    }


def _is_catalog_question(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    try:
        from omh.routing.catalog_questions import is_skill_catalog_question
    except Exception:
        return _standalone_catalog_question(text)
    try:
        return bool(is_skill_catalog_question(text))
    except Exception:
        return _standalone_catalog_question(text)


def _standalone_catalog_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    if any(marker in text for marker in ("src/", "tests/", "docs/", ".py", ".md", "readme", "section")):
        return False
    explicit = (
        "what commands are available",
        "what skills are available",
        "what workflows are available",
        "available commands",
        "available skills",
        "available workflows",
        "skill menu",
        "workflow menu",
        "workflow picker",
        "what can omh do",
        "what does omh do",
        "how can omh help",
        "omh 기능",
        "omh로 뭐 할 수",
        "omh가 뭐 해",
        "omh는 뭐 해",
        "使えるスキル",
        "利用可能なスキル",
        "利用可能なワークフロー",
        "有哪些命令",
        "有哪些技能",
        "有哪些工作流",
        "可用命令",
        "可用技能",
        "可用工作流",
    )
    if any(phrase in text for phrase in explicit):
        return True
    has_context = any(marker in text for marker in ("omh", "oh-my-hermes", "oh my hermes", "hermes", "헤르메스"))
    has_catalog_word = any(
        word in text
        for word in (
            "command",
            "commands",
            "skill",
            "skills",
            "workflow",
            "workflows",
            "스킬",
            "워크플로",
            "워크플로우",
            "명령",
            "기능",
            "スキル",
            "ワークフロー",
            "技能",
            "工作流",
            "命令",
        )
    )
    has_availability = any(
        word in text
        for word in (
            "available",
            "do you have",
            "can you do",
            "menu",
            "picker",
            "뭐",
            "무엇",
            "어떤",
            "알려",
            "보여",
            "있어",
            "가능",
            "一覧",
            "有哪些",
            "可用",
        )
    )
    return has_catalog_word and (has_context or has_availability)
