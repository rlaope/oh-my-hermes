"""Agent board to task status projection adapter tests."""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.workflows.task_status_projection_adapter import (
    projection_event_from_agent_board,
)

class TaskStatusProjectionAdapterTests(unittest.TestCase):
    def test_complete_done_becomes_worker_done(self) -> None:
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

        event = projection_event_from_agent_board(request)

        self.assertEqual(event.task_ref, "T1")
        self.assertEqual(event.status, "worker_done")
        self.assertTrue(event.revision.startswith("evidence:"))
        self.assertEqual(len(event.revision), 73)

    def test_blocked_task_becomes_blocked(self) -> None:
        request = {
            "request_ref": "request:block",
            "operation": "block",
            "state": "observed",
            "task_refs": ["T1"],
            "observation_ref": "observation:8",
            "observed_receipts": [
                {
                    "state": "observed",
                    "operation": "block",
                    "task_id": "T1",
                    "landed_status": "blocked",
                }
            ],
        }

        event = projection_event_from_agent_board(request)

        self.assertEqual(event.status, "blocked")

    def test_unobserved_request_produces_no_event(self) -> None:
        request = {
            "request_ref": "request:prepared",
            "operation": "complete",
            "state": "prepared",
            "task_refs": ["T1"],
            "observation_ref": "observation:9",
            "observed_receipts": [],
        }

        self.assertIsNone(projection_event_from_agent_board(request))

    def test_worker_done_requires_observed_evidence(self) -> None:
        request = {
            "request_ref": "request:fake",
            "operation": "complete",
            "state": "observed",
            "task_refs": ["T1"],
            "observation_ref": "observation:10",
            "observed_receipts": [
                {
                    "state": "observed",
                    "operation": "complete",
                    "task_id": "T1",
                    "landed_status": "running",
                }
            ],
        }

        self.assertIsNone(projection_event_from_agent_board(request))
