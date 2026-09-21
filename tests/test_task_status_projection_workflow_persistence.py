from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from omh.workflows.task_status_projection_workflow import (
    TaskStatusProjectionWorkflow,
)


class TaskStatusProjectionWorkflowPersistenceTests(unittest.TestCase):
    def test_same_workflow_execution_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            execution_path = Path(tmp) / "executions.jsonl"
            observation_path = Path(tmp) / "observations.jsonl"

            workflow = TaskStatusProjectionWorkflow(
                execution_path=execution_path,
                observation_path=observation_path,
            )

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

            executions = execution_path.read_text().splitlines()
            observations = observation_path.read_text().splitlines()

            self.assertEqual(
                len(executions),
                1,
            )

            self.assertEqual(
                len(observations),
                1,
            )
