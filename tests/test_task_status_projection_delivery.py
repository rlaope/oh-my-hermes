from __future__ import annotations

import unittest

from omh.workflows.task_status_projection_delivery import (
    CLAIM_BOUNDARY,
    SCHEMA_VERSION,
    ProjectionDeliveryRequest,
    build_projection_delivery_action,
)

from omh.workflows.task_status_projection import (
    TaskStatusProjectionStore,
    ProjectionEvent,
)

class TaskStatusProjectionDeliveryTests(unittest.TestCase):
    def _request(self, **overrides: object) -> ProjectionDeliveryRequest:
        values = {
            "projection_id": "projection:abc123",
            "board_ref": "board:main",
            "task_ref": "T1",
            "destination_ref": "destination:ops",
            "cursor": {
                "sequence": 3,
                "event_ref": "event:3",
            },
            "revision": "evidence:abc123",
            "action": "update_current",
        }
        values.update(overrides)
        return ProjectionDeliveryRequest(**values)

    def test_builds_delivery_action_from_projection_snapshot(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["status"],
        )

        store.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="rev:1",
            )
        )

        projection = store.snapshot()

        action = build_projection_delivery_action(
            projection,
            action="update_current",
        )

        self.assertEqual(action["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            action["projection_id"],
            projection["projection_id"],
        )
        self.assertEqual(
            action["cursor"]["sequence"],
            1,
        )
        self.assertEqual(
            action["cursor"]["event_ref"],
            "event:1",
        )
        self.assertEqual(
            action["revision"],
            "rev:1",
        )
        self.assertEqual(
            action["claim_boundary"],
            CLAIM_BOUNDARY,
        )

    def test_builds_provider_neutral_delivery_action(self) -> None:
        action = self._request().build()

        self.assertEqual(action["schema_version"], SCHEMA_VERSION)
        self.assertEqual(action["action"], "update_current")
        self.assertEqual(action["projection_id"], "projection:abc123")
        self.assertEqual(action["task_ref"], "T1")
        self.assertEqual(action["destination_ref"], "destination:ops")
        self.assertEqual(action["cursor"]["sequence"], 3)
        self.assertEqual(action["cursor"]["event_ref"], "event:3")
        self.assertTrue(action["action_id"].startswith("projection-action:"))
        self.assertTrue(action["idempotency_key"].startswith("projection:"))
        self.assertEqual(action["claim_boundary"], CLAIM_BOUNDARY)

    def test_same_identity_produces_same_action_and_idempotency_key(self) -> None:
        first = self._request().build()
        second = self._request().build()

        self.assertEqual(first, second)

    def test_different_cursor_produces_different_idempotency_key(self) -> None:
        first = self._request().build()
        second = self._request(
            cursor={
                "sequence": 4,
                "event_ref": "event:4",
            }
        ).build()

        self.assertNotEqual(
            first["idempotency_key"],
            second["idempotency_key"],
        )

    def test_rejects_unknown_action(self) -> None:
        with self.assertRaises(ValueError):
            self._request(action="delete_projection").build()

    def test_rejects_invalid_projection_reference(self) -> None:
        with self.assertRaises(ValueError):
            self._request(projection_id="../projection").build()

    def test_rejects_negative_cursor(self) -> None:
        with self.assertRaises(ValueError):
            self._request(
                cursor={
                    "sequence": -1,
                    "event_ref": "event:1",
                }
            ).build()

    def test_rejects_unbounded_event_reference(self) -> None:
        with self.assertRaises(ValueError):
            self._request(
                cursor={
                    "sequence": 1,
                    "event_ref": "x" * 257,
                }
            ).build()


if __name__ == "__main__":
    unittest.main()