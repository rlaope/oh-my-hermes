from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.workflows.task_status_projection_observation_store import (
    append_observation_if_missing,
    find_observation,
)


class TaskStatusProjectionObservationStoreTests(unittest.TestCase):
    def _observation(self) -> dict[str, str]:
        return {
            "schema_version": "task_status_projection_observation/v1",
            "execution_id": "execution:abc123",
            "provider_ref": "provider:event:1",
            "outcome": "accepted",
            "detail": "accepted by provider",
        }

    def test_appends_and_reads_observation(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"

            append_observation_if_missing(
                path,
                self._observation(),
            )

            result = find_observation(
                path,
                "execution:abc123",
            )

            self.assertEqual(
                result["outcome"],
                "accepted",
            )

    def test_same_execution_is_not_written_twice(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"

            first = append_observation_if_missing(
                path,
                self._observation(),
            )

            second = append_observation_if_missing(
                path,
                self._observation(),
            )

            self.assertTrue(first)
            self.assertFalse(second)

    def test_missing_observation_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"

            self.assertIsNone(
                find_observation(
                    path,
                    "execution:none",
                )
            )
