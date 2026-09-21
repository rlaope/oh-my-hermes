from __future__ import annotations

import unittest

from omh.workflows.task_status_projection_observation import (
    SCHEMA_VERSION,
    DeliveryObservation,
)


class TaskStatusProjectionObservationTests(unittest.TestCase):
    def test_builds_successful_observation(self) -> None:
        observation = DeliveryObservation(
            execution_id="execution:abc123",
            provider_ref="provider:event:1",
            outcome="accepted",
            detail="remote system accepted request",
        ).build()

        self.assertEqual(
            observation["schema_version"],
            SCHEMA_VERSION,
        )
        self.assertEqual(
            observation["outcome"],
            "accepted",
        )
        self.assertEqual(
            observation["execution_id"],
            "execution:abc123",
        )

    def test_rejects_unknown_outcome(self) -> None:
        with self.assertRaises(ValueError):
            DeliveryObservation(
                execution_id="execution:abc123",
                provider_ref="provider:event:1",
                outcome="done",
                detail="x",
            ).build()

    def test_rejects_invalid_reference(self) -> None:
        with self.assertRaises(ValueError):
            DeliveryObservation(
                execution_id="../bad",
                provider_ref="provider:event:1",
                outcome="accepted",
                detail="x",
            ).build()
