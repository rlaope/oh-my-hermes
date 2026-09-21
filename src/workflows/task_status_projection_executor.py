"""Execution boundary for task status projection delivery actions."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import TypedDict

from .task_status_projection_delivery import (
    ProjectionDeliveryAction,
)


SCHEMA_VERSION = "task_status_projection_execution/v1"

CLAIM_BOUNDARY = (
    "A prepared execution is not delivery evidence. "
    "Only an external observation can establish delivery."
)


class ProjectionDeliveryExecution(TypedDict):
    schema_version: str
    execution_id: str
    action_id: str
    action: str
    status: str
    idempotency_key: str
    claim_boundary: str


def prepare_projection_delivery_execution(
    action: ProjectionDeliveryAction,
) -> ProjectionDeliveryExecution:
    _validate_action(action)

    identity = {
        "action_id": action["action_id"],
        "idempotency_key": action["idempotency_key"],
    }

    digest = sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    return {
        "schema_version": SCHEMA_VERSION,
        "execution_id": f"execution:{digest[:32]}",
        "action_id": action["action_id"],
        "action": action["action"],
        "status": "prepared",
        "idempotency_key": action["idempotency_key"],
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _validate_action(
    action: ProjectionDeliveryAction,
) -> None:
    if not isinstance(action, dict):
        raise ValueError("invalid delivery action")

    if not action.get("action_id"):
        raise ValueError("missing action_id")

    if not action.get("idempotency_key"):
        raise ValueError("missing idempotency_key")

    if not action.get("action"):
        raise ValueError("missing action")
