"""Provider-neutral task status projection contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from threading import RLock
from typing import TypedDict


SCHEMA_VERSION = "task_status_projection/v1"

MAX_HISTORY = 64
MAX_FIELD_CHARS = 512
MAX_CURSOR_CHARS = 256

_PROJECTION_STATES = {
    "prepared",
    "observed",
    "retry",
    "provider_refused",
    "ambiguous_delivery",
    "closed",
}

_TASK_STATES = {
    "queued",
    "running",
    "stale",
    "blocked",
    "worker_done",
    "reviewed",
    "verification_passed",
    "merged",
}

_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")

CLAIM_BOUNDARY = (
    "Projection delivery does not prove task execution, review approval, "
    "verification, CI, merge or shipment."
)


class DisclosurePolicy(TypedDict):
    allowed_fields: list[str]
    max_field_chars: int


class Cursor(TypedDict):
    sequence: int
    event_ref: str


class CurrentStatus(TypedDict):
    task_ref: str
    status: str
    revision: str


class LifecycleEvent(TypedDict):
    sequence: int
    event_ref: str
    task_ref: str
    status: str
    revision: str


class TaskStatusProjection(TypedDict):
    schema_version: str
    projection_id: str
    board_ref: str
    task_ref: str
    destination_ref: str
    state: str
    cursor: Cursor
    disclosure_policy: DisclosurePolicy
    current: CurrentStatus
    history: list[LifecycleEvent]
    claim_boundary: str


def _cursor(sequence: int, event_ref: str) -> Cursor:
    if sequence < 0:
        raise ValueError("invalid cursor sequence")

    _bounded_string(event_ref, "event_ref", MAX_CURSOR_CHARS)

    return {
        "sequence": sequence,
        "event_ref": event_ref,
    }


def _reference(value: object, name: str) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise ValueError(f"invalid {name}")

    return value


def _bounded_string(
    value: object,
    name: str,
    limit: int = MAX_FIELD_CHARS,
) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"invalid {name}")

    return value


def _digest(parts: list[str]) -> str:
    payload = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(payload.encode()).hexdigest()


def _projection_id(
    board_ref: str,
    task_ref: str,
    destination_ref: str,
) -> str:
    return (
        f"projection:"
        f"{_digest([board_ref, task_ref, destination_ref])[:32]}"
    )


@dataclass(frozen=True)
class ProjectionEvent:
    task_ref: str
    status: str
    revision: str

    def validate(self) -> None:
        _reference(self.task_ref, "task_ref")
        _bounded_string(self.revision, "revision")

        if self.status not in _TASK_STATES:
            raise ValueError("invalid task status")


class TaskStatusProjectionStore:
    def __init__(
        self,
        *,
        board_ref: str,
        task_ref: str,
        destination_ref: str,
        allowed_fields: list[str] | tuple[str, ...],
        max_field_chars: int = MAX_FIELD_CHARS,
    ) -> None:
        self._revisions: set[str] = set()
        self._lock = RLock()
        self._board_ref = _reference(board_ref, "board_ref")
        self._task_ref = _reference(task_ref, "task_ref")
        self._destination_ref = _reference(
            destination_ref,
            "destination_ref",
        )

        if not 1 <= len(allowed_fields) <= 32:
            raise ValueError("invalid allowed_fields")

        normalized_fields = []

        for field in allowed_fields:
            normalized_fields.append(
                _bounded_string(field, "allowed_field", 64)
            )

        if not 1 <= max_field_chars <= MAX_FIELD_CHARS:
            raise ValueError("invalid max_field_chars")

        self._projection_id = _projection_id(
            self._board_ref,
            self._task_ref,
            self._destination_ref,
        )
        self._allowed_fields = tuple(dict.fromkeys(normalized_fields))
        self._max_field_chars = max_field_chars
        self._sequence = 0
        self._history: list[LifecycleEvent] = []
        self._current: CurrentStatus | None = None
        self._state = "prepared"

    @property
    def projection_id(self) -> str:
        return self._projection_id

    def append(self, event: ProjectionEvent) -> LifecycleEvent:
        event.validate()

        with self._lock:
            if event.task_ref != self._task_ref:
                raise ValueError("task_ref_mismatch")

            if event.revision in self._revisions:
                raise ValueError("event_replay")

            if self._current is not None:
                previous_revision = self._current["revision"]

                if event.revision == previous_revision:
                    raise ValueError("revision_not_advanced")

            self._sequence += 1

            row: LifecycleEvent = {
                "sequence": self._sequence,
                "event_ref": f"event:{self._sequence}",
                "task_ref": event.task_ref,
                "status": event.status,
                "revision": event.revision,
            }

            self._current = {
                "task_ref": event.task_ref,
                "status": event.status,
                "revision": event.revision,
            }

            self._revisions.add(event.revision)
            self._history.append(row)

            if len(self._history) > MAX_HISTORY:
                del self._history[: len(self._history) - MAX_HISTORY]

            return dict(row)

    def mark_observed(self) -> None:
        with self._lock:
            if self._state == "closed":
                raise ValueError("projection_closed")

            self._state = "observed"

    def mark_retry(self) -> None:
        with self._lock:
            if self._state == "closed":
                raise ValueError("projection_closed")

            self._state = "retry"

    def mark_provider_refused(self) -> None:
        with self._lock:
            if self._state == "closed":
                raise ValueError("projection_closed")

            self._state = "provider_refused"

    def mark_ambiguous_delivery(self) -> None:
        with self._lock:
            if self._state == "closed":
                raise ValueError("projection_closed")

            self._state = "ambiguous_delivery"

    def close(self) -> None:
        with self._lock:
            self._state = "closed"

    def to_snapshot(self) -> TaskStatusProjection:
        return self.snapshot()

    @classmethod
    def restore(
        cls,
        snapshot: TaskStatusProjection,
    ) -> TaskStatusProjectionStore:
        if snapshot["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported projection schema")

        projection = cls(
            board_ref=snapshot["board_ref"],
            task_ref=snapshot["task_ref"],
            destination_ref=snapshot["destination_ref"],
            allowed_fields=tuple(
                snapshot["disclosure_policy"]["allowed_fields"]
            ),
            max_field_chars=snapshot["disclosure_policy"]["max_field_chars"],
        )

        if snapshot["projection_id"] != projection.projection_id:
            raise ValueError("projection identity mismatch")

        history = snapshot["history"]

        if not history:
            raise ValueError("projection history is required")

        expected_sequence = history[0]["sequence"]

        for event in history:
            if event["sequence"] != expected_sequence:
                raise ValueError("history sequence mismatch")

            if event["event_ref"] != f"event:{event['sequence']}":
                raise ValueError("history event reference mismatch")

            if event["task_ref"] != projection._task_ref:
                raise ValueError("history task mismatch")

            if event["status"] not in _TASK_STATES:
                raise ValueError("invalid history task status")

            _bounded_string(event["revision"], "history revision")

            expected_sequence += 1

        current = snapshot["current"]

        if current["task_ref"] != projection._task_ref:
            raise ValueError("current task mismatch")

        latest_event = history[-1]

        if current["revision"] != latest_event["revision"]:
            raise ValueError("current revision mismatch")

        if current["status"] != latest_event["status"]:
            raise ValueError("current status mismatch")

        if snapshot["task_ref"] != projection._task_ref:
            raise ValueError("snapshot task mismatch")

        sequence = snapshot["cursor"]["sequence"]

        if sequence != latest_event["sequence"]:
            raise ValueError("projection cursor sequence mismatch")

        if snapshot["cursor"]["event_ref"] != f"event:{sequence}":
            raise ValueError("projection cursor mismatch")

        if snapshot["state"] not in _PROJECTION_STATES:
            raise ValueError("invalid projection state")

        projection._history = list(history)
        projection._current = dict(current)
        projection._state = snapshot["state"]
        projection._sequence = sequence
        projection._revisions = {
            event["revision"]
            for event in projection._history
        }

        return projection

    def snapshot(self) -> TaskStatusProjection:
        with self._lock:
            current = self._current

            if current is None:
                raise ValueError("projection_has_no_status")

            event_ref = self._history[-1]["event_ref"]

            return {
                "schema_version": SCHEMA_VERSION,
                "projection_id": self._projection_id,
                "board_ref": self._board_ref,
                "task_ref": self._task_ref,
                "destination_ref": self._destination_ref,
                "state": self._state,
                "cursor": _cursor(self._sequence, event_ref),
                "disclosure_policy": {
                    "allowed_fields": list(self._allowed_fields),
                    "max_field_chars": self._max_field_chars,
                },
                "current": dict(current),
                "history": [
                    dict(item)
                    for item in self._history
                ],
                "claim_boundary": CLAIM_BOUNDARY,
            }
