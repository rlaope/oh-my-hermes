"""Task status projection integration tests."""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.workflows.task_status_projection import TaskStatusProjectionStore
from omh.workflows.task_status_projection_adapter import (
    projection_event_from_agent_board,
)


class TaskStatusProjectionIntegrationTests(unittest.TestCase):
    def test_observed_agent_board_evidence_appends_to_projection(self) -> None:
        request = {
            "request_ref": "request:abc",
            "operation": "complete",
            "state": "observed",
            "task_refs": ["T1"],
            "observation_ref": "observation:7",
            "observed_receipts": [
                {
                    "state": "observed",
                    "operation": "complete",
                    "task_id": "T1",
                    "landed_status": "done",
                }
            ],
        }

        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        event = projection_event_from_agent_board(request)

        self.assertIsNotNone(event)

        row = store.append(event)

        self.assertEqual(row["sequence"], 1)
        self.assertEqual(row["task_ref"], "T1")
        self.assertEqual(row["status"], "worker_done")
        self.assertEqual(store.snapshot()["current"]["status"], "worker_done")

    def test_prepared_agent_board_request_does_not_append(self) -> None:
        request = {
            "request_ref": "request:prepared",
            "operation": "complete",
            "state": "prepared",
            "task_refs": ["T1"],
            "observation_ref": "observation:8",
            "observed_receipts": [],
        }

        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        event = projection_event_from_agent_board(request)

        self.assertIsNone(event)

        with self.assertRaises(ValueError) as ctx:
            store.snapshot()

        self.assertEqual(str(ctx.exception), "projection_has_no_status")

    def test_foreign_task_evidence_is_rejected(self) -> None:
        request = {
            "request_ref": "request:foreign",
            "operation": "complete",
            "state": "observed",
            "task_refs": ["T2"],
            "observation_ref": "observation:9",
            "observed_receipts": [
                {
                    "state": "observed",
                    "operation": "complete",
                    "task_id": "T2",
                    "landed_status": "done",
                }
            ],
        }

        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        event = projection_event_from_agent_board(request)

        self.assertIsNotNone(event)

        with self.assertRaises(ValueError) as ctx:
            store.append(event)

        self.assertEqual(str(ctx.exception), "task_ref_mismatch")

    def test_replayed_agent_board_evidence_is_rejected(self) -> None:
        request = {
            "request_ref": "request:replay",
            "operation": "complete",
            "state": "observed",
            "task_refs": ["T1"],
            "observation_ref": "observation:10",
            "observed_receipts": [
                {
                    "state": "observed",
                    "operation": "complete",
                    "task_id": "T1",
                    "landed_status": "done",
                }
            ],
        }

        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        event = projection_event_from_agent_board(request)

        self.assertIsNotNone(event)

        first = store.append(event)
        self.assertEqual(first["sequence"], 1)

        with self.assertRaises(ValueError) as ctx:
            store.append(event)

        self.assertEqual(str(ctx.exception), "event_replay")

    def test_replayed_evidence_is_rejected_after_restore(self) -> None:
        request = {
            "request_ref": "request:restore-replay",
            "operation": "complete",
            "state": "observed",
            "task_refs": ["T1"],
            "observation_ref": "observation:11",
            "observed_receipts": [
                {
                    "state": "observed",
                    "operation": "complete",
                    "task_id": "T1",
                    "landed_status": "done",
                }
            ],
        }

        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        event = projection_event_from_agent_board(request)

        self.assertIsNotNone(event)

        store.append(event)
        snapshot = store.snapshot()

        restored = TaskStatusProjectionStore.restore(snapshot)

        with self.assertRaises(ValueError) as ctx:
            restored.append(event)

        self.assertEqual(str(ctx.exception), "event_replay")


    def test_agent_board_lifecycle_preserves_history_and_cursor(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        requests = [
            {
                "request_ref": "request:running-1",
                "operation": "show",
                "state": "observed",
                "task_refs": ["T1"],
                "observation_ref": "observation:20",
                "observed_receipts": [
                    {
                        "state": "observed",
                        "operation": "show",
                        "task_id": "T1",
                        "landed_status": "running",
                    }
                ],
            },
            {
                "request_ref": "request:blocked-1",
                "operation": "block",
                "state": "observed",
                "task_refs": ["T1"],
                "observation_ref": "observation:21",
                "observed_receipts": [
                    {
                        "state": "observed",
                        "operation": "block",
                        "task_id": "T1",
                        "landed_status": "blocked",
                    }
                ],
            },
            {
                "request_ref": "request:running-2",
                "operation": "show",
                "state": "observed",
                "task_refs": ["T1"],
                "observation_ref": "observation:22",
                "observed_receipts": [
                    {
                        "state": "observed",
                        "operation": "show",
                        "task_id": "T1",
                        "landed_status": "running",
                    }
                ],
            },
            {
                "request_ref": "request:done-1",
                "operation": "complete",
                "state": "observed",
                "task_refs": ["T1"],
                "observation_ref": "observation:23",
                "observed_receipts": [
                    {
                        "state": "observed",
                        "operation": "complete",
                        "task_id": "T1",
                        "landed_status": "done",
                    }
                ],
            },
        ]

        events = [
            projection_event_from_agent_board(request)
            for request in requests
        ]

        self.assertTrue(all(event is not None for event in events))

        rows = [store.append(event) for event in events]

        self.assertEqual(
            [row["sequence"] for row in rows],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [row["status"] for row in rows],
            ["running", "blocked", "running", "worker_done"],
        )

        snapshot = store.snapshot()

        self.assertEqual(snapshot["current"]["status"], "worker_done")
        self.assertEqual(snapshot["cursor"]["sequence"], 4)
        self.assertEqual(
            [event["sequence"] for event in snapshot["history"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [event["status"] for event in snapshot["history"]],
            ["running", "blocked", "running", "worker_done"],
        )
        self.assertEqual(
            snapshot["cursor"]["event_ref"],
            snapshot["history"][-1]["event_ref"],
        )

        restored = TaskStatusProjectionStore.restore(snapshot)
        restored_snapshot = restored.snapshot()

        self.assertEqual(restored_snapshot, snapshot)