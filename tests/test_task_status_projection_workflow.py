from __future__ import annotations

import unittest

from omh.workflows.task_status_projection_workflow import (
    TaskStatusProjectionWorkflow,
)


class TaskStatusProjectionWorkflowTests(unittest.TestCase):
    def test_runs_delivery_flow_and_records_observation(self) -> None:
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
            "observed",
        )

        self.assertEqual(
            result["task_ref"],
            "T1",
        )

        self.assertIn(
            "execution_id",
            result,
        )

        self.assertIn(
            "observation",
            result,
        )
