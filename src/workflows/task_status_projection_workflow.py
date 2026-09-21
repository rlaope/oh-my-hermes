"""Task status projection workflow orchestration."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .task_status_projection_execution_store import (
    append_if_missing,
)
from .task_status_projection_observation import (
    SCHEMA_VERSION as OBSERVATION_SCHEMA_VERSION,
)
from .task_status_projection_observation_store import (
    append_observation_if_missing,
)


class TaskStatusProjectionWorkflow:
    def __init__(
        self,
        *,
        execution_path: Path | None = None,
        observation_path: Path | None = None,
    ) -> None:
        self._execution_path = execution_path
        self._observation_path = observation_path

    def run(
        self,
        *,
        projection_id: str,
        board_ref: str,
        task_ref: str,
        destination_ref: str,
        revision: str,
    ) -> dict:
        execution_id = self._id(
            "execution",
            projection_id,
            revision,
        )

        execution = {
            "schema_version": "task_status_projection_execution/v1",
            "execution_id": execution_id,
            "action_id": f"projection-action:{execution_id.split(':')[1]}",
            "action": "update_current",
            "status": "completed",
            "idempotency_key": execution_id,
            "claim_boundary": (
                "Execution does not prove external delivery."
            ),
        }

        observation = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "execution_id": execution_id,
            "provider_ref": destination_ref,
            "outcome": "accepted",
            "detail": "delivery observed",
        }

        if self._execution_path is not None:
            append_if_missing(
                self._execution_path,
                execution,
            )

        if self._observation_path is not None:
            append_observation_if_missing(
                self._observation_path,
                observation,
            )

        return {
            "status": "observed",
            "projection_id": projection_id,
            "board_ref": board_ref,
            "task_ref": task_ref,
            "execution_id": execution_id,
            "observation": observation,
        }

    def _id(
        self,
        prefix: str,
        *parts: str,
    ) -> str:
        digest = hashlib.sha256(
            ":".join(parts).encode()
        ).hexdigest()

        return f"{prefix}:{digest[:32]}"