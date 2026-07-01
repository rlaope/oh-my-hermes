from __future__ import annotations

import re
from typing import Final

from .agentic_playbook_contract import (
    AGENTIC_PLAYBOOK_SCHEMA_VERSION,
    JsonObject,
    JsonValue,
    PayloadObject,
    bool_at,
    build_agentic_playbook,
    dict_at,
    string_at,
)
from ..workflows.hermes_planning import is_coding_shaped_task


_CLARIFICATION: Final = "Do you want a quick answer, or should I prepare the staged implementation workflow?"
_CLASSIFICATION_BOUNDARY: Final = "Classification is routing guidance only; it is not execution evidence."
_LIGHT_ANTI_SIGNAL_TERMS: Final = (
    ("non_coding_troubleshooting", ("trackpad", "scroll", "mouse", "keyboard", "터치패드", "마우스")),
    ("status_only_question", ("status", "상태", "진행상황")),
    ("simple_explanation", ("why", "what does", "explain", "왜", "뭐야", "설명")),
    ("skill_catalog_question", ("skills", "workflows", "available", "스킬", "워크플로우")),
)
_ATTACH_SUPPORT_TERMS: Final = (
    ("release_or_merge_signal", ("merge", "release", "ci", "pr", "릴리즈", "머지")),
    ("review_signal", ("review", "code review", "fix-after-review", "리뷰")),
    ("handoff_signal", ("handoff", "delegate", "executor", "runtime", "team", "swarm", "서브", "에이전트")),
)
_CODING_DELEGATE_WORK_OWNER_MODES: Final = ("external_executor", "prompt_only_handoff", "runtime_handoff")


class _ClassificationEvidence:
    __slots__: tuple[str, ...] = ("anti_signals", "clarification", "reasons", "source_contracts")

    def __init__(self) -> None:
        self.reasons: list[str] = []
        self.anti_signals: list[str] = []
        self.source_contracts: list[str] = []
        self.clarification: str = ""

    def clarified(self, question: str) -> _ClassificationEvidence:
        evidence = _ClassificationEvidence()
        evidence.reasons = list(self.reasons)
        evidence.anti_signals = list(self.anti_signals)
        evidence.source_contracts = list(self.source_contracts)
        evidence.clarification = question
        return evidence


def classify_agentic_playbook(
    message: str,
    *,
    route_payload: PayloadObject | None = None,
    delegation_payload: PayloadObject | None = None,
) -> JsonObject:
    evidence = _ClassificationEvidence()
    route_action = _record_route_contracts(route_payload, evidence)
    delegation_action = _record_delegation_contracts(delegation_payload, evidence)
    coding_shaped = _record_message_signals(message, evidence)

    if route_action == "clarify":
        return _classification("clarify", "low", evidence.clarified(_CLARIFICATION))

    if (delegation_action == "delegate" or _has_coding_delegate_contract(evidence)) and (
        coding_shaped or _has_attach_signal(evidence)
    ):
        return _classification("attach_playbook", "high", evidence)

    if not coding_shaped:
        return _classification("light_path", "high", evidence)

    if evidence.anti_signals:
        return _classification("light_path", "medium", evidence)

    return _classification("clarify", "low", evidence.clarified(_CLARIFICATION))


def maybe_build_agentic_playbook(
    message: str,
    *,
    route_payload: PayloadObject | None = None,
    delegation_payload: PayloadObject | None = None,
) -> JsonObject | None:
    classification = classify_agentic_playbook(
        message,
        route_payload=route_payload,
        delegation_payload=delegation_payload,
    )
    if classification["decision"] != "attach_playbook":
        return None
    return build_agentic_playbook(classification, delegation_payload=delegation_payload)


def _classification(decision: str, confidence: str, evidence: _ClassificationEvidence) -> JsonObject:
    payload: JsonObject = {
        "schema_version": AGENTIC_PLAYBOOK_SCHEMA_VERSION,
        "decision": decision,
        "confidence": confidence,
        "reasons": _json_strings(unique(evidence.reasons)),
        "matched_signals": _json_strings(unique(evidence.reasons)),
        "anti_signals": _json_strings(unique(evidence.anti_signals)),
        "source_contracts": _json_strings(unique(evidence.source_contracts)),
        "claim_boundary": _CLASSIFICATION_BOUNDARY,
    }
    if evidence.clarification:
        payload["clarification"] = evidence.clarification
    return payload


def _record_route_contracts(route_payload: PayloadObject | None, evidence: _ClassificationEvidence) -> str:
    route_action = string_at(route_payload, "action")
    if route_action:
        evidence.source_contracts.append(f"route_action_{route_action}")
    if string_at(route_payload, "selected_skill"):
        evidence.source_contracts.append("route_selected_skill")
    return route_action


def _record_delegation_contracts(
    delegation_payload: PayloadObject | None, evidence: _ClassificationEvidence
) -> str:
    delegation_action = string_at(dict_at(delegation_payload, "delegation"), "action")
    if delegation_action:
        evidence.source_contracts.append(f"delegation_action_{delegation_action}")
    selected_executor = string_at(delegation_payload, "selected_executor_profile")
    if selected_executor:
        evidence.reasons.append("selected_executor_profile")
        evidence.source_contracts.append("selected_executor_profile")
    if bool_at(dict_at(delegation_payload, "executor_selection"), "choice_required"):
        evidence.source_contracts.append("executor_choice_required")
    if bool_at(delegation_payload, "available"):
        evidence.reasons.append("coding_delegate_available")
        evidence.source_contracts.append("coding_delegate_available")
    if bool_at(delegation_payload, "executor_choice_required"):
        evidence.reasons.append("executor_choice_required")
        evidence.source_contracts.append("executor_choice_required")
    work_owner_mode = string_at(delegation_payload, "work_owner_mode")
    if work_owner_mode in _CODING_DELEGATE_WORK_OWNER_MODES:
        evidence.reasons.append(f"{work_owner_mode}_work_owner")
        evidence.source_contracts.append(f"work_owner_mode_{work_owner_mode}")
    if delegation_action == "delegate":
        evidence.reasons.append("delegation_action_delegate")
    return delegation_action


def _record_message_signals(message: str, evidence: _ClassificationEvidence) -> bool:
    coding_shaped = is_coding_shaped_task(message)
    if coding_shaped:
        evidence.reasons.append("coding_shaped_task")
        evidence.source_contracts.append("hermes_planning.is_coding_shaped_task")
    lowered = f" {message.lower()} "
    tokens = set(re.findall(r"[0-9a-z가-힣]+", lowered))
    _append_matching_terms(lowered, tokens, _ATTACH_SUPPORT_TERMS, evidence.reasons)
    _append_matching_terms(lowered, tokens, _LIGHT_ANTI_SIGNAL_TERMS, evidence.anti_signals)
    return coding_shaped


def _append_matching_terms(
    lowered: str,
    tokens: set[str],
    terms_by_signal: tuple[tuple[str, tuple[str, ...]], ...],
    target: list[str],
) -> None:
    for signal, terms in terms_by_signal:
        if any(_term_matches(lowered, tokens, term) for term in terms):
            target.append(signal)


def _has_attach_signal(evidence: _ClassificationEvidence) -> bool:
    attach_reasons = {"release_or_merge_signal", "review_signal", "handoff_signal"}
    return any(reason in attach_reasons for reason in evidence.reasons)


def _has_coding_delegate_contract(evidence: _ClassificationEvidence) -> bool:
    contract_reasons = {
        "coding_delegate_available",
        "executor_choice_required",
        "external_executor_work_owner",
        "prompt_only_handoff_work_owner",
        "runtime_handoff_work_owner",
    }
    return any(reason in contract_reasons for reason in evidence.reasons)


def _term_matches(lowered: str, tokens: set[str], term: str) -> bool:
    return term in tokens if len(term) <= 2 else term in lowered


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _json_strings(values: list[str]) -> list[JsonValue]:
    result: list[JsonValue] = []
    for value in values:
        result.append(value)
    return result
