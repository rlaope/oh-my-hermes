from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final, NamedTuple, TypeAlias, TypeGuard

from .executors import executor_label


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
PayloadObject: TypeAlias = Mapping[str, object]

AGENTIC_PLAYBOOK_SCHEMA_VERSION: Final = "agentic_playbook/v1"
PREPARED_STATUS: Final = "prepared_not_observed"
CLAIM_BOUNDARY: Final = (
    "Prepared agentic playbook status remains prepared_not_observed; it is not execution, worker/subagent launch, "
    "implementation, review, CI, merge-readiness, or merge evidence."
)
BLOCKED_BEFORE_OBSERVATION: Final = (
    "worker_or_subagent_launch",
    "executor_dispatch",
    "implementation",
    "verification",
    "review_completion",
    "ci",
    "merge_readiness",
    "merge",
)
ROLE_FLOW: Final = ("interviewer", "pre_build_reviewer", "builder", "post_build_reviewer")


class _StepSpec(NamedTuple):
    step_id: str
    label: str
    owner: str
    owner_kind: str
    expected_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]


_STEP_SPECS: Final[tuple[_StepSpec, ...]] = (
    _StepSpec(
        step_id="interviewer",
        label="Interviewer",
        owner="Hermes / OMH planning surface",
        owner_kind="planning_surface",
        expected_inputs=("user request", "route/delegation source contracts"),
        expected_outputs=("clarified scope", "acceptance criteria"),
    ),
    _StepSpec(
        step_id="pre_build_reviewer",
        label="Reviewer",
        owner="Hermes / OMH review gate",
        owner_kind="prepared_review_gate",
        expected_inputs=("scope", "risks", "handoff readiness"),
        expected_outputs=("reviewed prepared plan", "known blockers"),
    ),
    _StepSpec(
        step_id="builder",
        label="Builder",
        owner="",
        owner_kind="selected_executor_runtime",
        expected_inputs=("accepted handoff", "selected executor/runtime owner"),
        expected_outputs=("implementation evidence from the selected owner",),
    ),
    _StepSpec(
        step_id="post_build_reviewer",
        label="Reviewer",
        owner="reviewer / verifier",
        owner_kind="observed_evidence_consumer",
        expected_inputs=("observed implementation", "tests", "review evidence"),
        expected_outputs=("review findings", "merge-readiness boundary"),
    ),
)


def build_agentic_playbook(
    classification: PayloadObject,
    *,
    delegation_payload: PayloadObject | None = None,
) -> JsonObject:
    selected_executor = string_at(delegation_payload, "selected_executor_profile")
    choice_required = bool_at(dict_at(delegation_payload, "executor_selection"), "choice_required")
    builder_owner = selected_executor if selected_executor else "executor_choice_required"
    builder_label = executor_label(selected_executor) if selected_executor else "executor choice required"
    return {
        "schema_version": AGENTIC_PLAYBOOK_SCHEMA_VERSION,
        "status": PREPARED_STATUS,
        "classification": public_classification(classification),
        "steps": _steps(builder_owner),
        "builder": _builder_payload(builder_owner, builder_label),
        "selected_executor_profile": selected_executor or "",
        "observation_contract": {
            "required_schema": "runtime_observation/v1",
            "status_before_observation": PREPARED_STATUS,
            "claim_boundary": "Prepared playbook status cannot advance without observed runtime or executor evidence.",
        },
        "not_observed": _json_strings(BLOCKED_BEFORE_OBSERVATION),
        "next_action": "choose_executor" if choice_required or not selected_executor else "prepare_selected_executor_handoff",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def chat_response_with_agentic_playbook(response: PayloadObject, playbook: PayloadObject) -> JsonObject:
    updated = _json_object(response)
    state = _json_object(dict_at(updated, "state"))
    state["agentic_playbook"] = _response_projection(playbook)
    updated["state"] = state

    summary = render_agentic_playbook_summary(playbook)
    body = str(updated.get("body", "")).strip()
    updated["body"] = f"{body}\n\n{summary}" if body else summary

    boundary = str(updated.get("claim_boundary", "")).strip()
    updated["claim_boundary"] = f"{boundary} {CLAIM_BOUNDARY}".strip()
    return updated


def render_agentic_playbook_summary(playbook: PayloadObject) -> str:
    builder = dict_at(playbook, "builder")
    owner_label = string_at(builder, "owner_label") or string_at(builder, "owner")
    return (
        "Prepared staged workflow: Interviewer -> Reviewer -> Builder -> Reviewer. "
        f"Builder owner: {owner_label}. Status: prepared_not_observed."
    )


def public_classification(classification: PayloadObject) -> JsonObject:
    return {
        "decision": string_at(classification, "decision"),
        "confidence": string_at(classification, "confidence"),
        "reasons": string_list_at(classification, "reasons"),
        "anti_signals": string_list_at(classification, "anti_signals"),
        "source_contracts": string_list_at(classification, "source_contracts"),
        "claim_boundary": string_at(classification, "claim_boundary"),
    }


def dict_at(payload: PayloadObject | None, key: str) -> PayloadObject:
    value = payload.get(key) if payload else None
    if not _is_payload_mapping(value):
        return {}
    return {str(item_key): item_value for item_key, item_value in value.items()}


def string_at(payload: PayloadObject | None, key: str) -> str:
    value = payload.get(key) if payload else None
    return str(value) if value else ""


def bool_at(payload: PayloadObject | None, key: str) -> bool:
    value = payload.get(key) if payload else None
    return bool(value)


def string_list_at(payload: PayloadObject, key: str) -> list[JsonValue]:
    value = payload.get(key)
    if not _is_object_list(value):
        return []
    result: list[JsonValue] = []
    for item in value:
        if item:
            result.append(str(item))
    return result


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _steps(builder_owner: str) -> list[JsonValue]:
    return [_step_from_spec(spec, builder_owner) for spec in _STEP_SPECS]


def _step_from_spec(spec: _StepSpec, builder_owner: str) -> JsonObject:
    owner = builder_owner if spec.step_id == "builder" else spec.owner
    return {
        "id": spec.step_id,
        "label": spec.label,
        "owner": owner,
        "owner_kind": spec.owner_kind,
        "expected_inputs": _json_strings(spec.expected_inputs),
        "expected_outputs": _json_strings(spec.expected_outputs),
        "status": PREPARED_STATUS,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _builder_payload(builder_owner: str, builder_label: str) -> JsonObject:
    return {
        "id": "builder",
        "label": "Builder",
        "owner": builder_owner,
        "owner_label": builder_label,
        "owner_kind": "selected_executor_runtime",
        "claim_boundary": (
            "Builder is a Hermes-visible role label; implementation belongs to the selected executor/runtime "
            "and requires observed evidence."
        ),
    }


def _response_projection(playbook: PayloadObject) -> JsonObject:
    builder = dict_at(playbook, "builder")
    return {
        "schema_version": string_at(playbook, "schema_version") or AGENTIC_PLAYBOOK_SCHEMA_VERSION,
        "status": string_at(playbook, "status") or PREPARED_STATUS,
        "role_flow": _json_strings(ROLE_FLOW),
        "builder_owner": string_at(builder, "owner"),
        "builder_owner_kind": string_at(builder, "owner_kind"),
        "claim_boundary": string_at(playbook, "claim_boundary") or CLAIM_BOUNDARY,
    }


def _json_strings(values: Iterable[str]) -> list[JsonValue]:
    result: list[JsonValue] = []
    for value in values:
        result.append(value)
    return result


def _json_object(payload: PayloadObject) -> JsonObject:
    result: JsonObject = {}
    for key, value in payload.items():
        result[str(key)] = _json_value(value)
    return result


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if _is_object_list(value):
        array_result: list[JsonValue] = []
        for item in value:
            array_result.append(_json_value(item))
        return array_result
    if _is_payload_mapping(value):
        object_result: JsonObject = {}
        for key, item in value.items():
            object_result[str(key)] = _json_value(item)
        return object_result
    return str(value)


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _is_payload_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)
