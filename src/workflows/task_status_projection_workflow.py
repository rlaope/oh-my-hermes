"""Task status projection workflow orchestration."""

from __future__ import annotations

from pathlib import Path

from .task_status_projection_execution_store import (
    append_if_missing,
)
from .task_status_projection_executor import (
    ProjectionDeliveryExecution,
    prepare_projection_delivery_execution,
)
from .task_status_projection_observation import (
    DeliveryObservation,
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
        observation: DeliveryObservation | None = None,
    ) -> dict:
        action = {
            "schema_version": "task_status_projection_delivery/v1",
            "action_id": self._id(
                "projection-action",
                projection_id,
                task_ref,
                destination_ref,
                revision,
            ),
            "action": "update_current",
            "projection_id": projection_id,
            "board_ref": board_ref,
            "task_ref": task_ref,
            "destination_ref": destination_ref,
            "sequence": 0,
            "event_ref": "event:0",
            "revision": revision,
            "idempotency_key": self._id(
                "projection-idempotency",
                projection_id,
                task_ref,
                destination_ref,
                revision,
            ),
            "claim_boundary": (
                "A prepared delivery action is not delivery evidence. "
                "Only a validated external observation can establish delivery."
            ),
        }

        execution = prepare_projection_delivery_execution(
            action,
        )

        if self._execution_path is not None:
            execution, _ = append_if_missing(
                self._execution_path,
                execution,
            )

        result = {
            "status": "prepared_not_observed",
            "projection_id": projection_id,
            "board_ref": board_ref,
            "task_ref": task_ref,
            "execution_id": execution["execution_id"],
        }

        if observation is None:
            return result

        observation_record = observation.build()

        if observation_record["execution_id"] != execution["execution_id"]:
            raise ValueError(
                "observation execution_id does not match prepared execution"
            )

        if self._observation_path is not None:
            observation_record, _ = append_observation_if_missing(
                self._observation_path,
                observation_record,
            )

        result["status"] = (
            "observed"
            if observation_record["outcome"] == "accepted"
            else observation_record["outcome"]
        )
        result["observation"] = observation_record

        return result

    def _id(
        self,
        prefix: str,
        *parts: str,
    ) -> str:
        import hashlib

        digest = hashlib.sha256(
            ":".join(parts).encode()
        ).hexdigest()

        return f"{prefix}:{digest[:32]}"
