"""Convert bounded agent-board evidence into task status projection events."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from omh.workflows.task_status_projection import ProjectionEvent


_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")

_STATUS_MAP = {
    "triage": "queued",
    "todo": "queued",
    "ready": "queued",
    "running": "running",
    "blocked": "blocked",
    "done": "worker_done",
}

_MAX_REVISION_CHARS = 256


def _reference(value: object, field: str) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _revision(
    request_ref: str,
    observation_ref: str,
    task_ref: str,
    status: str,
) -> str:
    raw = f"{request_ref}|{observation_ref}|{task_ref}|{status}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    value = f"evidence:{digest}"
    if len(value) > _MAX_REVISION_CHARS:
        raise ValueError("revision exceeds maximum length")
    return value


def projection_event_from_agent_board(
    request: Mapping[str, object],
) -> ProjectionEvent | None:
    if request.get("state") != "observed":
        return None

    request_ref = _reference(request.get("request_ref"), "request_ref")
    observation_ref = _reference(
        request.get("observation_ref"),
        "observation_ref",
    )

    task_refs = request.get("task_refs")
    if not isinstance(task_refs, list) or len(task_refs) != 1:
        return None

    task_ref = _reference(task_refs[0], "task_ref")

    receipts = request.get("observed_receipts")
    if not isinstance(receipts, list) or len(receipts) != 1:
        return None

    receipt = receipts[0]
    if not isinstance(receipt, Mapping):
        return None

    if receipt.get("state") != "observed":
        return None

    if receipt.get("task_id") != task_ref:
        return None

    landed_status = receipt.get("landed_status")
    if not isinstance(landed_status, str):
        return None

    status = _STATUS_MAP.get(landed_status)
    if status is None:
        return None

    operation = request.get("operation")
    if operation == "complete" and landed_status != "done":
        return None

    if operation == "block" and landed_status != "blocked":
        return None

    return ProjectionEvent(
        task_ref=task_ref,
        status=status,
        revision=_revision(
            request_ref,
            observation_ref,
            task_ref,
            status,
        ),
    )