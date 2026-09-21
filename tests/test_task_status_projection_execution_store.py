from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.workflows.task_status_projection_execution_store import (
    append_if_missing,
    find_execution_by_action,
    read_executions,
)
from omh.workflows.task_status_projection_executor import (
    prepare_projection_delivery_execution,
)
from omh.workflows.task_status_projection_delivery import (
    ProjectionDeliveryRequest,
)


class TaskStatusProjectionExecutionStoreTests(unittest.TestCase):
    def _execution(self):
        action = ProjectionDeliveryRequest(
            projection_id="projection:abc123",
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            cursor={
                "sequence": 3,
                "event_ref": "event:3",
            },
            revision="revision:abc",
            action="update_current",
        ).build()

        return prepare_projection_delivery_execution(action)

    def test_appends_and_reads_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "executions.jsonl"

            execution = self._execution()

            append_if_missing(
                path,
                execution,
            )

            rows = read_executions(path)

            self.assertEqual(
                len(rows),
                1,
            )

            self.assertEqual(
                rows[0]["execution_id"],
                execution["execution_id"],
            )

    def test_finds_execution_by_action_id(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "executions.jsonl"

            execution = self._execution()

            append_if_missing(
                path,
                execution,
            )

            found = find_execution_by_action(
                path,
                execution["action_id"],
            )

            self.assertEqual(
                found["action_id"],
                execution["action_id"],
            )

    def test_same_action_is_not_written_twice(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "executions.jsonl"

            execution = self._execution()

            first, created_first = append_if_missing(
                path,
                execution,
            )

            second, created_second = append_if_missing(
                path,
                execution,
            )

            self.assertTrue(created_first)
            self.assertFalse(created_second)

            self.assertEqual(
                first,
                second,
            )

            self.assertEqual(
                len(read_executions(path)),
                1,
            )


if __name__ == "__main__":
    unittest.main()
