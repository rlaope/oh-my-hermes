from __future__ import annotations

import unittest

from omh.workflows.task_status_projection_observation import (
    DeliveryObservation,
)
from omh.workflows.task_status_projection_workflow import (
    TaskStatusProjectionWorkflow,
)


class TaskStatusProjectionWorkflowIntegrationTests(unittest.TestCase):
    def test_workflow_stays_prepared_without_delivery_observation(self) -> None:
        workflow = TaskStatusProjectionWorkflow()

        result = workflow.run(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            revision="revision:1",
        )

        self.assertEqual(
            result["status"],
            "prepared_not_observed",
        )

        self.assertEqual(
            result["projection_id"],
            "projection:abc123",
        )

        self.assertEqual(
            result["task_ref"],
            "T1",
        )

        self.assertTrue(
            result["execution_id"].startswith(
                "execution:"
            ),
        )

        self.assertNotIn(
            "observation",
            result,
        )

    def test_workflow_accepts_matching_delivery_observation(self) -> None:
        workflow = TaskStatusProjectionWorkflow()

        prepared = workflow.run(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            revision="revision:1",
        )

        observation = DeliveryObservation(
            execution_id=prepared["execution_id"],
            provider_ref="provider:message-1",
            outcome="accepted",
            detail="connector receipt",
        )

        result = workflow.run(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            revision="revision:1",
            observation=observation,
        )

        self.assertEqual(
            result["status"],
            "observed",
        )

        self.assertEqual(
            result["observation"]["outcome"],
            "accepted",
        )

        self.assertEqual(
            result["observation"]["provider_ref"],
            "provider:message-1",
        )

    def test_same_input_produces_same_execution_identity(self) -> None:
        workflow = TaskStatusProjectionWorkflow()

        first = workflow.run(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            revision="revision:1",
        )

        second = workflow.run(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            revision="revision:1",
        )

        self.assertEqual(
            first["execution_id"],
            second["execution_id"],
        )

    def test_different_revision_creates_new_execution_identity(self) -> None:
        workflow = TaskStatusProjectionWorkflow()

        first = workflow.run(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            revision="revision:1",
        )

        second = workflow.run(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            revision="revision:2",
        )

        self.assertNotEqual(
            first["execution_id"],
            second["execution_id"],
        )
