"""Provider-neutral delivery actions for task status projections."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import TypedDict

from .task_status_projection import Cursor

SCHEMA_VERSION = "task_status_projection_delivery/v1"
CLAIM_BOUNDARY = (
    "A prepared delivery action is not delivery evidence. "
    "Only a validated external observation can establish delivery."
)

_ACTIONS = (
    "create_projection",
    "update_current",
    "append_lifecycle",
)

_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_MAX_IDEMPOTENCY_CHARS = 128


class ProjectionDeliveryAction(TypedDict):
    schema_version: str
    action_id: str
    action: str
    projection_id: str
    board_ref: str
    task_ref: str
    destination_ref: str
    cursor: Cursor
    revision: str
    idempotency_key: str
    claim_boundary: str


@dataclass(frozen=True)
class ProjectionDeliveryRequest:
    projection_id: str
    board_ref: str
    task_ref: str
    destination_ref: str
    cursor: Cursor
    revision: str
    action: str

    def build(self) -> ProjectionDeliveryAction:
        _reference(self.projection_id, "projection_id")
        _reference(self.board_ref, "board_ref")
        _reference(self.task_ref, "task_ref")
        _reference(self.destination_ref, "destination_ref")
        _reference(self.revision, "revision")

        if self.action not in _ACTIONS:
            raise ValueError("invalid projection delivery action")

        sequence = self.cursor.get("sequence")
        event_ref = self.cursor.get("event_ref")

        if not isinstance(sequence, int) or sequence < 0:
            raise ValueError("invalid projection delivery cursor")

        if not isinstance(event_ref, str) or len(event_ref) > 256:
            raise ValueError("invalid projection delivery event_ref")

        identity = {
            "action": self.action,
            "projection_id": self.projection_id,
            "board_ref": self.board_ref,
            "task_ref": self.task_ref,
            "destination_ref": self.destination_ref,
            "sequence": sequence,
            "event_ref": event_ref,
            "revision": self.revision,
        }

        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        action_id = f"projection-action:{digest[:32]}"
        idempotency_key = f"projection:{digest}"

        if len(idempotency_key) > _MAX_IDEMPOTENCY_CHARS:
            raise ValueError("invalid projection delivery idempotency_key")

        return {
            "schema_version": SCHEMA_VERSION,
            "action_id": action_id,
            "action": self.action,
            "projection_id": self.projection_id,
            "board_ref": self.board_ref,
            "task_ref": self.task_ref,
            "destination_ref": self.destination_ref,
            "cursor": {
                "sequence": sequence,
                "event_ref": event_ref,
            },
            "revision": self.revision,
            "idempotency_key": idempotency_key,
            "claim_boundary": CLAIM_BOUNDARY,
        }


def _reference(value: str, field: str) -> None:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise ValueError(f"invalid {field}")