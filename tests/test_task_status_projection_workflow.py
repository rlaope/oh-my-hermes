from __future__ import annotations

import unittest

from omh.workflows.task_status_projection_observation import (
    DeliveryObservation,
)
from omh.workflows.task_status_projection_workflow import (
    TaskStatusProjectionWorkflow,
)


class TaskStatusProjectionWorkflowTests(unittest.TestCase):
    def test_run_stays_unobserved_without_delivery_receipt(self) -> None:
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
            result["task_ref"],
            "T1",
        )

        self.assertIn(
            "execution_id",
            result,
        )

        self.assertNotIn(
            "observation",
            result,
        )

    def test_run_accepts_only_matching_explicit_observation(self) -> None:
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
            result["observation"]["provider_ref"],
            "provider:message-1",
        )

    def test_run_rejects_observation_for_other_execution(self) -> None:
        workflow = TaskStatusProjectionWorkflow()

        observation = DeliveryObservation(
            execution_id="execution:foreign",
            provider_ref="provider:message-1",
            outcome="accepted",
            detail="connector receipt",
        )

        with self.assertRaisesRegex(
            ValueError,
            "does not match",
        ):
            workflow.run(
                projection_id="projection:abc123",
                board_ref="board:main",
                task_ref="T1",
                destination_ref="destination:ops",
                revision="revision:1",
                observation=observation,
            )
