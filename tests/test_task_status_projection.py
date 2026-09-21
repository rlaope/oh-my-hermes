"""Task status projection contract tests."""

from __future__ import annotations

import unittest

import pytest

from _local_package import load_local_package

load_local_package()

from omh.workflows.task_status_projection import (
    CLAIM_BOUNDARY,
    SCHEMA_VERSION,
    ProjectionEvent,
    TaskStatusProjectionStore,
)


class TaskStatusProjectionTests(unittest.TestCase):
    def store(self) -> TaskStatusProjectionStore:
        return TaskStatusProjectionStore(
            board_ref="qa-board",
            task_ref="T1",
            destination_ref="destination:test",
            allowed_fields=("task_ref", "status", "revision"),
        )

    def test_schema_and_stable_projection_identity(self) -> None:
        first = self.store()
        second = self.store()

        self.assertEqual(first.projection_id, second.projection_id)

        first.append(ProjectionEvent("T1", "queued", "r1"))
        snapshot = first.snapshot()

        self.assertEqual(snapshot["schema_version"], SCHEMA_VERSION)
        self.assertEqual(snapshot["projection_id"], first.projection_id)
        self.assertEqual(snapshot["board_ref"], "qa-board")
        self.assertEqual(snapshot["task_ref"], "T1")
        self.assertEqual(snapshot["destination_ref"], "destination:test")

    def test_current_status_and_append_only_history(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        projection.append(ProjectionEvent("T1", "running", "r2"))
        projection.append(ProjectionEvent("T1", "worker_done", "r3"))

        snapshot = projection.snapshot()

        self.assertEqual(snapshot["current"]["status"], "worker_done")
        self.assertEqual(snapshot["current"]["revision"], "r3")
        self.assertEqual(
            [event["status"] for event in snapshot["history"]],
            ["queued", "running", "worker_done"],
        )
        self.assertEqual(snapshot["cursor"]["sequence"], 3)
        self.assertEqual(snapshot["cursor"]["event_ref"], "event:3")

    def test_task_status_and_delivery_state_are_independent(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "merged", "r7"))
        projection.mark_provider_refused()

        snapshot = projection.snapshot()

        self.assertEqual(snapshot["current"]["status"], "merged")
        self.assertEqual(snapshot["state"], "provider_refused")

    def test_delivery_state_transitions(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        projection.mark_observed()
        self.assertEqual(projection.snapshot()["state"], "observed")

        projection.mark_retry()
        self.assertEqual(projection.snapshot()["state"], "retry")

        projection.mark_ambiguous_delivery()
        self.assertEqual(projection.snapshot()["state"], "ambiguous_delivery")

        projection.mark_provider_refused()
        self.assertEqual(projection.snapshot()["state"], "provider_refused")

        projection.close()
        self.assertEqual(projection.snapshot()["state"], "closed")

    def test_invalid_task_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProjectionEvent("T1", "completed", "r1").validate()

    def test_foreign_task_is_rejected(self) -> None:
        projection = self.store()

        with self.assertRaises(ValueError):
            projection.append(ProjectionEvent("T2", "running", "r1"))

    def test_closed_projection_cannot_change_delivery_state(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        projection.close()

        with self.assertRaises(ValueError):
            projection.mark_retry()

    def test_history_is_bounded(self) -> None:
        projection = self.store()

        for index in range(70):
            projection.append(
                ProjectionEvent("T1", "running", f"revision-{index}")
            )

        snapshot = projection.snapshot()

        self.assertEqual(len(snapshot["history"]), 64)
        self.assertEqual(snapshot["history"][0]["sequence"], 7)
        self.assertEqual(snapshot["history"][-1]["sequence"], 70)

    def test_claim_boundary_is_explicit(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        snapshot = projection.snapshot()

        self.assertEqual(snapshot["claim_boundary"], CLAIM_BOUNDARY)
        self.assertNotIn("workspace_path", snapshot)
        self.assertNotIn("body", snapshot)
        self.assertNotIn("prompt", snapshot)
        self.assertNotIn("secret", snapshot)

    def test_same_event_reference_is_not_replayed(self) -> None:
        projection = self.store()

        first = projection.append(
            ProjectionEvent("T1", "running", "r1")
        )

        with self.assertRaises(ValueError):
            projection.append(
                ProjectionEvent("T1", "running", "r1")
            )

        snapshot = projection.snapshot()

        self.assertEqual(len(snapshot["history"]), 1)
        self.assertEqual(snapshot["cursor"]["event_ref"], first["event_ref"])

    def test_revision_must_advance(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))

        with self.assertRaises(ValueError):
            projection.append(ProjectionEvent("T1", "running", "r1"))

    def test_invalid_revision_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ProjectionEvent("T1", "queued", "").validate()

    def test_projection_identity_changes_with_destination(self) -> None:
        first = TaskStatusProjectionStore(
            board_ref="qa-board",
            task_ref="T1",
            destination_ref="destination:a",
            allowed_fields=("task_ref", "status"),
        )
        second = TaskStatusProjectionStore(
            board_ref="qa-board",
            task_ref="T1",
            destination_ref="destination:b",
            allowed_fields=("task_ref", "status"),
        )

        self.assertNotEqual(first.projection_id, second.projection_id)

    def test_prepared_projection_snapshot_has_no_status(self) -> None:
        projection = self.store()

        snapshot = projection.snapshot()

        self.assertEqual(snapshot["state"], "prepared")
        self.assertIsNone(snapshot["current"])
        self.assertEqual(snapshot["history"], [])
        self.assertEqual(snapshot["cursor"]["sequence"], 0)
        self.assertEqual(snapshot["cursor"]["event_ref"], "")

    def test_to_snapshot_preserves_projection_state(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        projection.append(ProjectionEvent("T1", "running", "r2"))
        projection.mark_observed()

        snapshot = projection.to_snapshot()

        self.assertEqual(snapshot["projection_id"], projection.projection_id)
        self.assertEqual(snapshot["state"], "observed")
        self.assertEqual(snapshot["current"]["status"], "running")
        self.assertEqual(snapshot["cursor"]["sequence"], 2)
        self.assertEqual(len(snapshot["history"]), 2)

    def test_restore_preserves_projection_state(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        projection.append(ProjectionEvent("T1", "running", "r2"))
        projection.mark_observed()

        saved = projection.snapshot()
        restored = TaskStatusProjectionStore.restore(saved)

        self.assertEqual(restored.projection_id, projection.projection_id)
        self.assertEqual(restored.snapshot()["state"], "observed")
        self.assertEqual(
            restored.snapshot()["current"]["status"],
            "running",
        )
        self.assertEqual(
            restored.snapshot()["cursor"],
            saved["cursor"],
        )
        self.assertEqual(
            restored.snapshot()["history"],
            saved["history"],
        )

    def test_restore_rejects_wrong_schema(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        snapshot = projection.snapshot()
        snapshot["schema_version"] = "task_status_projection/v999"

        with self.assertRaises(ValueError):
            TaskStatusProjectionStore.restore(snapshot)

    def test_restore_rejects_projection_identity_mismatch(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        snapshot = projection.snapshot()
        snapshot["projection_id"] = "projection:tampered"

        with self.assertRaises(ValueError):
            TaskStatusProjectionStore.restore(snapshot)

    def test_restore_rejects_cursor_mismatch(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        snapshot = projection.snapshot()
        snapshot["cursor"]["sequence"] = 99

        with self.assertRaises(ValueError):
            TaskStatusProjectionStore.restore(snapshot)

    def test_restore_rejects_empty_history(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        snapshot = projection.snapshot()
        snapshot["history"] = []

        with self.assertRaises(ValueError):
            TaskStatusProjectionStore.restore(snapshot)

    def test_cursor_is_monotonic(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        first = projection.snapshot()["cursor"]

        projection.append(ProjectionEvent("T1", "running", "r2"))
        second = projection.snapshot()["cursor"]

        self.assertLess(first["sequence"], second["sequence"])
        self.assertEqual(first["event_ref"], "event:1")
        self.assertEqual(second["event_ref"], "event:2")

    def test_restore_rejects_history_task_mismatch(self) -> None:
        projection = self.store()

        projection.append(
            ProjectionEvent(
                task_ref="T1",
                status="queued",
                revision="rev-1",
            )
        )

        snapshot = projection.snapshot()
        snapshot["history"][0]["task_ref"] = "T2"

        with pytest.raises(ValueError, match="history task mismatch"):
            TaskStatusProjectionStore.restore(snapshot)

    def test_restore_rejects_current_task_mismatch(self) -> None:
        projection = self.store()

        projection.append(
            ProjectionEvent(
                task_ref="T1",
                status="queued",
                revision="rev-1",
            )
        )

        snapshot = projection.snapshot()
        snapshot["current"]["task_ref"] = "T2"

        with pytest.raises(ValueError, match="current task mismatch"):
            TaskStatusProjectionStore.restore(snapshot)

    def test_restore_rejects_current_revision_mismatch(self) -> None:
        projection = self.store()

        projection.append(
            ProjectionEvent(
                task_ref="T1",
                status="queued",
                revision="rev-1",
            )
        )

        snapshot = projection.snapshot()
        snapshot["current"]["revision"] = "rev-2"

        with pytest.raises(ValueError, match="current revision mismatch"):
            TaskStatusProjectionStore.restore(snapshot)

    def test_restore_rejects_history_sequence_gap(self) -> None:
        projection = self.store()

        projection.append(
            ProjectionEvent(
                task_ref="T1",
                status="queued",
                revision="rev-1",
            )
        )
        projection.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="rev-2",
            )
        )

        snapshot = projection.snapshot()
        snapshot["history"][1]["sequence"] = 3

        with pytest.raises(ValueError, match="history sequence mismatch"):
            TaskStatusProjectionStore.restore(snapshot)

    def test_restored_projection_can_continue_lifecycle(self) -> None:
        projection = self.store()

        projection.append(ProjectionEvent("T1", "queued", "r1"))
        projection.append(ProjectionEvent("T1", "running", "r2"))
        projection.mark_retry()

        saved = projection.snapshot()
        restored = TaskStatusProjectionStore.restore(saved)

        restored.append(ProjectionEvent("T1", "worker_done", "r3"))
        restored.mark_observed()

        snapshot = restored.snapshot()

        self.assertEqual(snapshot["state"], "observed")
        self.assertEqual(snapshot["current"]["status"], "worker_done")
        self.assertEqual(snapshot["current"]["revision"], "r3")
        self.assertEqual(snapshot["cursor"]["sequence"], 3)
        self.assertEqual(
            [event["status"] for event in snapshot["history"]],
            ["queued", "running", "worker_done"],
        )

    def test_restore_preserves_bounded_history_cursor(self) -> None:
        projection = self.store()

        for index in range(70):
            projection.append(
                ProjectionEvent(
                    "T1",
                    "running",
                    f"revision-{index}",
                )
            )

        saved = projection.snapshot()
        restored = TaskStatusProjectionStore.restore(saved)

        snapshot = restored.snapshot()

        self.assertEqual(len(snapshot["history"]), 64)
        self.assertEqual(snapshot["history"][0]["sequence"], 7)
        self.assertEqual(snapshot["history"][-1]["sequence"], 70)
        self.assertEqual(snapshot["cursor"]["sequence"], 70)
        self.assertEqual(snapshot["cursor"]["event_ref"], "event:70")

        restored.append(
            ProjectionEvent(
                "T1",
                "worker_done",
                "revision-70",
            )
        )

        snapshot = restored.snapshot()

        self.assertEqual(len(snapshot["history"]), 64)
        self.assertEqual(snapshot["history"][-1]["sequence"], 71)
        self.assertEqual(snapshot["cursor"]["sequence"], 71)
        self.assertEqual(snapshot["current"]["status"], "worker_done")

    def test_restore_rejects_replayed_revision(self) -> None:
        projection = self.store()

        projection.append(
            ProjectionEvent(
                "T1",
                "queued",
                "r1",
            )
        )
        projection.append(
            ProjectionEvent(
                "T1",
                "running",
                "r2",
            )
        )

        restored = TaskStatusProjectionStore.restore(projection.snapshot())

        with self.assertRaises(ValueError):
            restored.append(
                ProjectionEvent(
                    "T1",
                    "running",
                    "r2",
                )
            )

        snapshot = restored.snapshot()

        self.assertEqual(len(snapshot["history"]), 2)
        self.assertEqual(snapshot["cursor"]["sequence"], 2)
        self.assertEqual(snapshot["current"]["revision"], "r2")

    def test_disclosure_policy_limits_published_fields(self) -> None:
        projection = TaskStatusProjectionStore(
            board_ref="qa-board",
            task_ref="T1",
            destination_ref="destination:test",
            allowed_fields=("task_ref", "status"),
            max_field_chars=128,
        )

        projection.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision-1",
            )
        )

        snapshot = projection.snapshot()

        self.assertEqual(
            snapshot["disclosure_policy"]["allowed_fields"],
            ["task_ref", "status"],
        )
        self.assertEqual(
            snapshot["disclosure_policy"]["max_field_chars"],
            128,
        )
        self.assertNotIn(
            "revision",
            snapshot["disclosure_policy"]["allowed_fields"],
        )
        self.assertNotIn("workspace_path", snapshot)
        self.assertNotIn("body", snapshot)
        self.assertNotIn("prompt", snapshot)
        self.assertNotIn("secret", snapshot)


    def test_prepared_state_is_not_delivery_success(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        self.assertEqual(store._state, "prepared")

    def test_delivery_lifecycle_states_are_distinct(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        event = ProjectionEvent(
            task_ref="T1",
            status="running",
            revision="revision:1",
        )
        store.append(event)

        store.mark_observed()
        self.assertEqual(store.snapshot()["state"], "observed")

        store.mark_retry()
        self.assertEqual(store.snapshot()["state"], "retry")

        store.mark_provider_refused()
        self.assertEqual(
            store.snapshot()["state"],
            "provider_refused",
        )

        store.mark_ambiguous_delivery()
        self.assertEqual(
            store.snapshot()["state"],
            "ambiguous_delivery",
        )

    def test_closed_projection_rejects_lifecycle_changes(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        store.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision:2",
            )
        )
        store.close()

        self.assertEqual(store.snapshot()["state"], "closed")

        for operation in (
            store.mark_observed,
            store.mark_retry,
            store.mark_provider_refused,
            store.mark_ambiguous_delivery,
        ):
            with self.assertRaises(ValueError) as ctx:
                operation()

            self.assertEqual(str(ctx.exception), "projection_closed")

    def test_delivery_state_survives_snapshot_restore(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        store.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision:1",
            )
        )

        store.mark_ambiguous_delivery()

        snapshot = store.snapshot()

        restored = TaskStatusProjectionStore.restore(snapshot)

        self.assertEqual(
            restored.snapshot()["state"],
            "ambiguous_delivery",
        )

    def test_destination_change_closes_old_projection_and_creates_new_one(
        self,
    ) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:old",
            allowed_fields=["task_ref", "status"],
        )

        store.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision:1",
            )
        )
        store.mark_observed()

        old_projection_id = store.projection_id

        new_store = store.change_destination("destination:new")

        old_snapshot = store.snapshot()

        self.assertEqual(old_snapshot["state"], "closed")
        self.assertEqual(
            old_snapshot["destination_ref"],
            "destination:old",
        )

        self.assertNotEqual(
            old_projection_id,
            new_store.projection_id,
        )

        new_store.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision:2",
            )
        )

        new_snapshot = new_store.snapshot()

        self.assertEqual(
            new_snapshot["state"],
            "prepared",
        )
        self.assertEqual(
            new_snapshot["destination_ref"],
            "destination:new",
        )
        self.assertEqual(
            new_snapshot["current"]["status"],
            "running",
        )

    def test_destination_change_rejects_unchanged_destination(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        with self.assertRaises(ValueError) as ctx:
            store.change_destination("destination:ops")

        self.assertEqual(str(ctx.exception), "destination_unchanged")

    def test_closed_projection_cannot_change_destination(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:old",
            allowed_fields=["task_ref", "status"],
        )

        store.close()

        with self.assertRaises(ValueError) as ctx:
            store.change_destination("destination:new")

        self.assertEqual(str(ctx.exception), "projection_closed")

    def test_closed_projection_rejects_new_events(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        store.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision:1",
            )
        )
        store.close()

        with self.assertRaises(ValueError) as ctx:
            store.append(
                ProjectionEvent(
                    task_ref="T1",
                    status="worker_done",
                    revision="revision:2",
                )
            )

        self.assertEqual(str(ctx.exception), "projection_closed")

    def test_closed_projection_rejects_delivery_state_changes(
        self,
    ) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        store.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision:1",
            )
        )
        store.close()

        for method_name in (
            "mark_observed",
            "mark_retry",
            "mark_provider_refused",
            "mark_ambiguous_delivery",
        ):
            with self.subTest(method=method_name):
                with self.assertRaises(ValueError) as ctx:
                    getattr(store, method_name)()

                self.assertEqual(str(ctx.exception), "projection_closed")


    def test_prepared_projection_can_be_snapshotted(self) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        snapshot = store.snapshot()

        self.assertEqual(snapshot["state"], "prepared")
        self.assertEqual(snapshot["projection_id"], store.projection_id)
        self.assertEqual(snapshot["cursor"]["sequence"], 0)
        self.assertEqual(snapshot["cursor"]["event_ref"], "")
        self.assertEqual(snapshot["history"], [])
        self.assertIsNone(snapshot["current"])

    def test_prepared_projection_can_be_restored_before_first_event(
        self,
    ) -> None:
        store = TaskStatusProjectionStore(
            board_ref="board:main",
            task_ref="T1",
            destination_ref="destination:ops",
            allowed_fields=["task_ref", "status"],
        )

        snapshot = store.snapshot()
        restored = TaskStatusProjectionStore.restore(snapshot)

        self.assertEqual(
            restored.projection_id,
            store.projection_id,
        )

        row = restored.append(
            ProjectionEvent(
                task_ref="T1",
                status="running",
                revision="revision:1",
            )
        )

        self.assertEqual(row["sequence"], 1)
        self.assertEqual(row["status"], "running")


if __name__ == "__main__":
    unittest.main()