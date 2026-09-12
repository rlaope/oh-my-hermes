"""Hermes plugin surface for authenticated connector decision-gate answers."""

from __future__ import annotations

from .. import runtime_paths

import json
from collections.abc import Mapping
from typing import Any

from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..runtime_reader import default_omh_home

_REQUIRED_DECISION_GATE_FIELDS = (
    "gate_id", "expected_resume_digest", "choice", "actor", "connector", "channel_ref", "thread_ref",
    "interaction_ref", "authentication_method", "observed_at", "event_id", "wrapper_session_ref",
    "wrapper_expected_revision",
)

OMH_DECISION_GATE_SCHEMA = {
    "name": "omh_decision_gate",
    "description": (
        "Apply one authenticated structured connector decision to one open OMH gate and its bound wrapper session. "
        "This does not accept free-form chat text or credentials. The connector host must authenticate the actor."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "gate_id": {"type": "string"},
            "expected_resume_digest": {"type": "string"},
            "choice": {"type": "string", "enum": ["approve", "decline", "defer"]},
            "actor": {"type": "string", "description": "Stable host-authenticated actor identifier."},
            "connector": {"type": "string"},
            "channel_ref": {"type": "string"},
            "thread_ref": {"type": "string"},
            "interaction_ref": {"type": "string"},
            "authentication_method": {"type": "string", "enum": ["host_authenticated", "signed_connector_event"]},
            "observed_at": {"type": "string"},
            "event_id": {"type": "string"},
            "wrapper_session_ref": {"type": "string"},
            "wrapper_expected_revision": {"type": "integer", "minimum": 0},
            "observation": OBSERVATION_SCHEMA,
        },
        "required": list(_REQUIRED_DECISION_GATE_FIELDS),
        "additionalProperties": False,
    },
}


def omh_decision_gate_handler(
    args: dict[str, Any],
    *,
    trusted_connector_event: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    """Apply only a host-provided event that exactly binds the model request."""
    allowed = set(_REQUIRED_DECISION_GATE_FIELDS) | {"observation"}
    observation = observe_plugin_tool_call("omh_decision_gate", args if isinstance(args, dict) else {}, kwargs)
    if not isinstance(args, dict) or set(args) - allowed or set(_REQUIRED_DECISION_GATE_FIELDS) - set(args):
        return json.dumps(attach_public_observation(_invalid_result("invalid_payload"), observation), sort_keys=True)
    payload = {key: args[key] for key in _REQUIRED_DECISION_GATE_FIELDS}
    from omh.workflows.decision_gate_receipts import validate_connector_decision_payload

    parsed_payload, error = validate_connector_decision_payload(payload)
    if error:
        return json.dumps(attach_public_observation(_invalid_result(error), observation), sort_keys=True)
    if trusted_connector_event is None:
        return json.dumps(attach_public_observation(_invalid_result("untrusted_host_context"), observation), sort_keys=True)
    trusted_payload, trusted_error = validate_connector_decision_payload(trusted_connector_event)
    if trusted_error:
        return json.dumps(attach_public_observation(_invalid_result("invalid_host_context"), observation), sort_keys=True)
    if trusted_payload != parsed_payload:
        return json.dumps(attach_public_observation(_invalid_result("host_context_mismatch"), observation), sort_keys=True)
    from omh.paths import resolve_paths
    from omh.commands.decision_gate import apply_connector_decision_answer

    paths = resolve_paths(
        omh_home=default_omh_home(),
        hermes_home=runtime_paths.default_hermes_home(),
    )
    result = apply_connector_decision_answer(paths, **parsed_payload)
    return json.dumps(attach_public_observation(result, observation), sort_keys=True)


def _invalid_result(reason_code: str = "invalid_payload") -> dict[str, Any]:
    return {
        "schema_version": "connector_decision_gate_result/v1",
        "status": "invalid",
        "reason_code": reason_code,
        "receipt": {},
        "claim_boundary": (
            "A connector decision-gate result is metadata-only and never treats free-form chat text as approval."
        ),
    }
