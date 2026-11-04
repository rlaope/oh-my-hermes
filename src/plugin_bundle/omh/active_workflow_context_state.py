"""Portable workflow identity shared by the control plane and standalone hook."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final

ALLOWED_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
    "deep-interview": ("plan", "ralplan"),
    "plan": ("dag-ulw", "ultrawork", "ultraqa"),
    "ralplan": ("dag-ulw", "ultrawork", "ultraqa"),
    "refactor-plan": ("dag-ulw",),
}


def session_fingerprint(session_ref: str) -> str:
    """Use the awareness-delivery session identity without retaining host IDs."""
    return "sha256:" + hashlib.sha256(session_ref.encode("utf-8")).hexdigest()


def valid_session_binding(session_ref: str) -> bool:
    return bool(re.fullmatch(r"sha256:[0-9a-f]{64}", session_ref))


@dataclass(frozen=True, slots=True)
class WorkflowRecord:
    workflow: str
    active: bool
    session_ref: str


class WorkflowRecordError(ValueError):
    """The local state file does not carry a usable workflow identity."""


def parse_workflow_record(raw: str, workflow: str) -> WorkflowRecord:
    """Parse only lifecycle identity; never propagate notes or unknown fields."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise WorkflowRecordError("state_not_object")
    name = data.get("workflow", workflow)
    active = data.get("active")
    session = data.get("session_ref", "")
    if (
        data.get("schema_version", 1) != 1
        or not isinstance(name, str)
        or name != workflow
        or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
        or not isinstance(active, bool)
        or not isinstance(session, str)
        or (session and not valid_session_binding(session))
        or data.get("session_binding", "bound" if session else "unbound") != ("bound" if session else "unbound")
        or (active and data.get("lifecycle_outcome") is not None)
    ):
        raise WorkflowRecordError("invalid_workflow_identity")
    return WorkflowRecord(name, active, session)
