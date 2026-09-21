from __future__ import annotations

import unittest

from omh.workflows.task_status_projection_executor import (
    CLAIM_BOUNDARY,
    SCHEMA_VERSION,
    prepare_projection_delivery_execution,
)
from omh.workflows.task_status_projection_delivery import (
    ProjectionDeliveryRequest,
)


class TaskStatusProjectionExecutorTests(unittest.TestCase):
    def _action(self):
        return ProjectionDeliveryRequest(
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

    def test_prepares_execution_from_delivery_action(self) -> None:
        execution = prepare_projection_delivery_execution(
            self._action()
        )

        self.assertEqual(
            execution["schema_version"],
            SCHEMA_VERSION,
        )
        self.assertTrue(
            execution["execution_id"].startswith("execution:")
        )
        self.assertEqual(
            execution["action"],
            "update_current",
        )
        self.assertEqual(
            execution["status"],
            "prepared",
        )
        self.assertEqual(
            execution["action_id"],
            self._action()["action_id"],
        )
        self.assertEqual(
            execution["claim_boundary"],
            CLAIM_BOUNDARY,
        )

    def test_same_action_is_idempotent(self) -> None:
        first = prepare_projection_delivery_execution(
            self._action()
        )
        second = prepare_projection_delivery_execution(
            self._action()
        )

        self.assertEqual(
            first,
            second,
        )

    def test_rejects_invalid_action(self) -> None:
        with self.assertRaises(ValueError):
            prepare_projection_delivery_execution(
                {}
            )


if __name__ == "__main__":
    unittest.main()
