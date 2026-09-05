from __future__ import annotations

import json
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from _local_package import load_local_package
from _platform_support import requires_fcntl_locks, requires_symlinks

load_local_package()
from omh.paths import resolve_paths
from omh.workflows import memory_batches as memory_batches_workflow
from omh.workflows.memory import (
    _memory_snapshots,
    apply_approved_memory_update_batch,
    apply_memory_update_batch,
    build_handoff_context_pack,
    review_memory_update_batch,
    stage_memory_update_batch,
)


def _batch(label: str, *, scope: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "memory_update_batch/v1",
        "source_surface": "test",
        "updates": [
            {
                "op": "update",
                "item_id": label,
                "scope": scope or {"kind": "project", "ref": "default"},
                "key": label.replace("-", "_"),
                "value": f"value for {label}",
                "summary": f"Remember {label}",
            }
        ],
    }


def _apply_worker(home: str, batch_id: str, barrier: object, ready: object, queue: object) -> None:
    paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
    ready.set()
    barrier.wait(timeout=10)
    result = apply_approved_memory_update_batch(paths, batch_id)
    queue.put((result["status"], result["batch_id"]))


class MemoryBatchTests(TestCase):
    def _stage_and_remember(self, paths, batch: dict[str, object]) -> dict[str, object]:
        staged = stage_memory_update_batch(paths, batch)
        decisions = {item["item_id"]: "remember" for item in staged["items"]}
        reviewed = review_memory_update_batch(paths, staged["batch_id"], decisions, reviewer_label="operator-label")
        self.assertEqual(reviewed["status"], "reviewed")
        return staged

    def test_legacy_direct_apply_is_review_required_and_write_free(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")

            result = apply_memory_update_batch(paths, _batch("unreviewed-direct"))

            self.assertEqual(result["status"], "review_required")
            self.assertFalse(result["applied"])
            self.assertFalse(paths.memory_dir.exists())

    def test_stage_review_apply_binds_immutable_decisions_and_keeps_receipt_metadata_only(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = stage_memory_update_batch(paths, _batch("release-command"))
            self.assertEqual(apply_approved_memory_update_batch(paths, staged["batch_id"])["status"], "review_required")
            review_memory_update_batch(paths, staged["batch_id"], {staged["items"][0]["item_id"]: "remember"}, reviewer_label="operator-label")
            item = staged["items"][0]
            with self.assertRaisesRegex(ValueError, "immutable"):
                review_memory_update_batch(paths, staged["batch_id"], {item["item_id"]: "refuse"}, reviewer_label="operator-label")

            self.assertTrue(item["item_id"].startswith("item_"))
            self.assertEqual(item["retention_class"], "standard")
            self.assertTrue(staged["batch_id"].startswith("batch_"))
            self.assertNotIn(item["item_id"], {row["item_id"] for row in build_handoff_context_pack(paths)["included_context"]})

            applied = apply_approved_memory_update_batch(
                paths,
                staged["batch_id"],
                now=datetime(2026, 9, 6, 1, 0, tzinfo=timezone.utc),
            )
            repeated = apply_approved_memory_update_batch(
                paths,
                staged["batch_id"],
                now=datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc),
            )
            handoff = build_handoff_context_pack(paths)
            receipt = applied["receipt"]

            self.assertEqual(applied["status"], "applied")
            self.assertEqual(repeated["status"], "applied")
            self.assertIn(item["item_id"], [row["item_id"] for row in handoff["included_context"]])
            self.assertEqual(receipt["operation_id"], staged["operation_id"])
            self.assertNotIn("value", json.dumps(receipt))
            self.assertNotIn("summary", json.dumps(receipt))
            self.assertNotIn("hash", json.dumps(receipt))
            self.assertNotIn(str(paths.memory_dir), json.dumps(receipt))

    def test_later_reviewed_update_replaces_an_item_written_by_an_earlier_batch(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            first = self._stage_and_remember(paths, _batch("first-record"))
            self.assertTrue(apply_approved_memory_update_batch(paths, first["batch_id"])["applied"])
            item_id = first["items"][0]["item_id"]

            second_batch = _batch(item_id)
            second_updates = second_batch["updates"]
            self.assertIsInstance(second_updates, list)
            assert isinstance(second_updates, list)
            second_update = second_updates[0]
            self.assertIsInstance(second_update, dict)
            assert isinstance(second_update, dict)
            second_update.update(
                {
                    "key": "first_record",
                    "value": "second synthetic value",
                    "summary": "Replace the first synthetic value",
                }
            )
            second = self._stage_and_remember(paths, second_batch)

            applied = apply_approved_memory_update_batch(paths, second["batch_id"])
            scope = json.loads((paths.memory_dir / "scopes" / "project.json").read_text(encoding="utf-8"))

            self.assertTrue(applied["applied"])
            self.assertEqual(scope["items"][item_id]["value"], "second synthetic value")
            self.assertEqual(scope["items"][item_id]["batch_id"], second["batch_id"])

    def test_stage_rejects_unsafe_content_without_writing_a_candidate(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            unsafe = _batch("unsafe")
            unsafe["updates"][0]["value"] = "token=protected"

            with self.assertRaisesRegex(ValueError, "unsafe"):
                stage_memory_update_batch(paths, unsafe)

            self.assertFalse(paths.memory_dir.exists())

    def test_stage_rejects_structural_credentials_without_writing_a_candidate(self) -> None:
        for value in (
            "gh" + "u_" + "a" * 36,
            "Ab3dEf4G" * 5 + "=",
            "mQvHzLrNaPeTgWuYbJxDcFkSiOoUaZcV",
            "JBSWYDPFJBSWYDPFJBSWYDPFJBSWYDPF",
        ):
            with self.subTest(value_kind=value[:4]), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                unsafe = _batch("structural-credential")
                updates = unsafe["updates"]
                self.assertIsInstance(updates, list)
                assert isinstance(updates, list)
                update = updates[0]
                self.assertIsInstance(update, dict)
                assert isinstance(update, dict)
                update["value"] = value

                with self.assertRaisesRegex(ValueError, "unsafe"):
                    stage_memory_update_batch(paths, unsafe)

                self.assertFalse(paths.memory_dir.exists())

    def test_batch_surface_and_reviewer_labels_reject_credentials_before_writes(self) -> None:
        credential = "gh" + "u_" + "a" * 36
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            unsafe_surface = _batch("unsafe-surface")
            unsafe_surface["source_surface"] = credential

            with self.assertRaises(ValueError) as surface_error:
                stage_memory_update_batch(paths, unsafe_surface)

            self.assertNotIn(credential, str(surface_error.exception))
            self.assertFalse(paths.memory_dir.exists())

            staged = stage_memory_update_batch(paths, _batch("unsafe-reviewer"))
            decisions = {item["item_id"]: "remember" for item in staged["items"]}
            with self.assertRaises(ValueError) as reviewer_error:
                review_memory_update_batch(
                    paths,
                    staged["batch_id"],
                    decisions,
                    reviewer_label=credential,
                )

            self.assertNotIn(credential, str(reviewer_error.exception))
            self.assertFalse((paths.memory_dir / "reviews").exists())

    def test_batch_control_metadata_rejects_credentials_before_candidate_persistence(self) -> None:
        credential = "gh" + "u_" + "a" * 36
        for field in ("item_id", "scope_ref", "retention_class"):
            with self.subTest(field=field), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                batch = _batch("control-metadata")
                updates = batch["updates"]
                assert isinstance(updates, list)
                update = updates[0]
                assert isinstance(update, dict)
                if field == "item_id":
                    update["item_id"] = credential
                    update["key"] = "safe_key"
                elif field == "scope_ref":
                    update["scope"] = {"kind": "project", "ref": credential}
                else:
                    update["retention_class"] = credential

                with self.assertRaises(ValueError) as caught:
                    stage_memory_update_batch(paths, batch)

                self.assertNotIn(credential, str(caught.exception))
                self.assertFalse(paths.memory_dir.exists())

    def test_apply_revalidates_tampered_batch_scope_before_any_write(self) -> None:
        credential = "gh" + "u_" + "a" * 36
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = self._stage_and_remember(paths, _batch("tampered-scope"))
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["items"][0]["scope"]["ref"] = credential
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertNotIn(credential, json.dumps(result, sort_keys=True))
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_binds_the_reviewed_operation_before_any_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = self._stage_and_remember(paths, _batch("tampered-op"))
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["items"][0]["op"] = "forget"
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_binds_reviewed_target_before_any_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = self._stage_and_remember(paths, _batch("tampered-target"))
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["items"][0]["target_ref"] = "different-safe-target"
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_binds_reviewed_source_scope_before_any_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            batch = _batch("tampered-source-scope")
            updates = batch["updates"]
            assert isinstance(updates, list)
            update = updates[0]
            assert isinstance(update, dict)
            update["op"] = "change_scope"
            update["from_scope"] = {"kind": "project", "ref": "default"}
            update["to_scope"] = {"kind": "thread", "ref": "thread-1"}
            staged = self._stage_and_remember(paths, batch)
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["items"][0]["from_scope"] = {"kind": "project", "ref": "different-project"}
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_binds_reviewed_retention_before_any_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = self._stage_and_remember(paths, _batch("tampered-retention"))
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["items"][0]["retention"]["class"] = "durable"
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_rejects_a_stored_review_whose_decision_was_changed(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = stage_memory_update_batch(paths, _batch("tampered-review-decision"))
            item_id = staged["items"][0]["item_id"]
            reviewed = review_memory_update_batch(
                paths,
                staged["batch_id"],
                {item_id: "refuse"},
                reviewer_label="operator-label",
            )
            review_path = paths.memory_dir / "reviews" / f"{reviewed['items'][0]['review_id']}.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["decision"] = "remember"
            review_path.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_rejects_changed_stored_review_metadata(self) -> None:
        mutations = {
            "reviewer_label": "forged-reviewer",
            "reviewed_at": "2027-01-01T00:00:00Z",
            "policy_version": "forged-policy",
            "forged_authorization": "accepted",
        }
        for field, value in mutations.items():
            with self.subTest(field=field), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                staged = stage_memory_update_batch(paths, _batch(f"tampered-review-{field}"))
                item_id = staged["items"][0]["item_id"]
                reviewed = review_memory_update_batch(
                    paths,
                    staged["batch_id"],
                    {item_id: "remember"},
                    reviewer_label="operator-label",
                )
                review_path = paths.memory_dir / "reviews" / f"{reviewed['items'][0]['review_id']}.json"
                review = json.loads(review_path.read_text(encoding="utf-8"))
                review[field] = value
                review_path.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                result = apply_approved_memory_update_batch(paths, staged["batch_id"])

                self.assertFalse(result["applied"])
                self.assertEqual(result["reason_code"], "review_linkage_invalid")
                self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_binds_candidate_control_metadata_before_any_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = self._stage_and_remember(paths, _batch("tampered-apply-operation"))
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["apply_operation_id"] = "op_apply_forged"
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertFalse((paths.memory_dir / "scopes").exists())
            self.assertFalse((paths.memory_dir / "operations" / "op_apply_forged.json").exists())

    def test_apply_rejects_operation_id_owned_by_another_reviewed_batch(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            first = self._stage_and_remember(paths, _batch("first-operation-owner"))
            second = stage_memory_update_batch(
                paths,
                _batch(
                    "second-operation-owner",
                    scope={"kind": "thread", "ref": "second-thread"},
                ),
            )
            second_path = paths.memory_dir / "candidates" / f"{second['batch_id']}.json"
            second_candidate = json.loads(second_path.read_text(encoding="utf-8"))
            second_candidate["apply_operation_id"] = first["operation_id"]
            second_path.write_text(
                json.dumps(second_candidate, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            review_memory_update_batch(
                paths,
                second["batch_id"],
                {second["items"][0]["item_id"]: "remember"},
                reviewer_label="operator-label",
            )
            self.assertTrue(apply_approved_memory_update_batch(paths, first["batch_id"])["applied"])

            result = apply_approved_memory_update_batch(paths, second["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "operation_identity_conflict")
            self.assertFalse(
                (paths.memory_dir / "scopes" / "threads" / "second-thread.json").exists()
            )

    def test_review_retry_overwrites_unsealed_orphan_authorization(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = stage_memory_update_batch(paths, _batch("interrupted-review"))
            item_id = staged["items"][0]["item_id"]
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            real_write = memory_batches_workflow.atomic_write_json

            def interrupt_seal(path, payload, **kwargs):
                if Path(path) == candidate_path and isinstance(payload, dict) and "review_seals" in payload:
                    raise RuntimeError("injected candidate seal interruption")
                return real_write(path, payload, **kwargs)

            with patch.object(memory_batches_workflow, "atomic_write_json", side_effect=interrupt_seal):
                with self.assertRaisesRegex(RuntimeError, "candidate seal interruption"):
                    review_memory_update_batch(
                        paths,
                        staged["batch_id"],
                        {item_id: "remember"},
                        reviewer_label="operator-label",
                    )

            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertNotIn("review_seals", candidate)
            review_path = paths.memory_dir / "reviews" / f"{candidate['items'][0]['review_id']}.json"
            orphan = json.loads(review_path.read_text(encoding="utf-8"))
            orphan["reviewed_at"] = "2030-01-01T00:00:00Z"
            orphan["forged_authorization"] = "accepted"
            review_path.write_text(json.dumps(orphan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            review_memory_update_batch(
                paths,
                staged["batch_id"],
                {item_id: "remember"},
                reviewer_label="operator-label",
            )
            stored = json.loads(review_path.read_text(encoding="utf-8"))

            self.assertNotEqual(stored["reviewed_at"], "2030-01-01T00:00:00Z")
            self.assertNotIn("forged_authorization", stored)
            self.assertTrue(apply_approved_memory_update_batch(paths, staged["batch_id"])["applied"])

    def test_deleting_or_rewriting_candidate_review_state_cannot_change_a_refusal(self) -> None:
        for mutation in ("delete_seals", "rewrite_request"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                staged = stage_memory_update_batch(paths, _batch(f"sealed-refusal-{mutation}"))
                item_id = staged["items"][0]["item_id"]
                review_memory_update_batch(
                    paths,
                    staged["batch_id"],
                    {item_id: "refuse"},
                    reviewer_label="operator-label",
                )
                candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                candidate.pop("review_seals")
                if mutation == "rewrite_request":
                    candidate["review_request"]["decisions"][item_id] = "remember"
                candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "immutable"):
                    review_memory_update_batch(
                        paths,
                        staged["batch_id"],
                        {item_id: "remember"},
                        reviewer_label="operator-label",
                    )

                result = apply_approved_memory_update_batch(paths, staged["batch_id"])
                self.assertFalse(result["applied"])
                self.assertEqual(result["reason_code"], "review_linkage_invalid")
                self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_rejects_scope_drift_since_staging_before_overwrite(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            scope_path = paths.memory_dir / "scopes" / "project.json"
            scope_path.parent.mkdir(parents=True)
            original = {
                "schema_version": "omh_memory_scope/v2",
                "scope": {"kind": "project", "ref": "default"},
                "items": {
                    "live-target": {
                        "item_id": "live-item",
                        "revision": 1,
                        "key": "live_key",
                        "summary": "Original reviewed value",
                        "value": "original",
                    }
                },
                "tombstones": {},
            }
            scope_path.write_text(json.dumps(original, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            staged = self._stage_and_remember(paths, _batch("live-target"))
            changed = json.loads(scope_path.read_text(encoding="utf-8"))
            changed["items"]["live-target"]["revision"] = 2
            changed["items"]["live-target"]["value"] = "changed-after-review"
            scope_path.write_text(json.dumps(changed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            changed_bytes = scope_path.read_bytes()

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "scope_precondition_changed")
            self.assertEqual(scope_path.read_bytes(), changed_bytes)

    def test_change_scope_rejects_source_scope_identity_drift_after_review(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            source_path = paths.memory_dir / "scopes" / "project.json"
            source_path.parent.mkdir(parents=True)
            source = {
                "schema_version": "omh_memory_scope/v2",
                "scope": {"kind": "project", "ref": "default"},
                "items": {
                    "move-target": {
                        "item_id": "move-item",
                        "revision": 1,
                        "key": "move_key",
                        "summary": "Move reviewed value",
                        "value": "move value",
                    }
                },
                "tombstones": {},
            }
            source_path.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            batch = _batch("move-target")
            updates = batch["updates"]
            self.assertIsInstance(updates, list)
            assert isinstance(updates, list)
            update = updates[0]
            self.assertIsInstance(update, dict)
            assert isinstance(update, dict)
            update.update(
                {
                    "op": "change_scope",
                    "from_scope": {"kind": "project", "ref": "default"},
                    "to_scope": {"kind": "thread", "ref": "destination"},
                    "key": "move_key",
                    "summary": "Move reviewed value",
                    "value": "move value",
                }
            )
            staged = self._stage_and_remember(paths, batch)
            drifted = json.loads(source_path.read_text(encoding="utf-8"))
            drifted["scope"] = {"kind": "thread", "ref": "other-thread"}
            source_path.write_text(json.dumps(drifted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            drifted_bytes = source_path.read_bytes()

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "scope_precondition_changed")
            self.assertEqual(source_path.read_bytes(), drifted_bytes)
            self.assertFalse((paths.memory_dir / "scopes" / "threads" / "destination.json").exists())

    def test_multiscope_preflight_rejects_all_drift_before_removing_source(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            source_path = paths.memory_dir / "scopes" / "project.json"
            source_path.parent.mkdir(parents=True)
            source = {
                "schema_version": "omh_memory_scope/v2",
                "scope": {"kind": "project", "ref": "default"},
                "items": {
                    "live-target": {
                        "item_id": "live-item",
                        "revision": 1,
                        "key": "live_key",
                        "summary": "Original reviewed value",
                        "value": "original",
                    }
                },
                "tombstones": {},
            }
            source_path.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            batch = _batch("live-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            update = updates[0]
            update.update(
                {
                    "op": "change_scope",
                    "from_scope": {"kind": "project", "ref": "default"},
                    "to_scope": {"kind": "run", "ref": "destination"},
                }
            )
            staged = self._stage_and_remember(paths, batch)
            source_bytes = source_path.read_bytes()
            destination_path = paths.memory_dir / "scopes" / "runs" / "destination.json"
            destination_path.parent.mkdir(parents=True)
            destination_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "run", "ref": "destination"},
                        "items": {"live-item": {"item_id": "live-item", "value": "concurrent"}},
                        "tombstones": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "scope_precondition_changed")
            self.assertEqual(source_path.read_bytes(), source_bytes)

    def test_multiscope_post_preflight_drift_does_not_remove_source(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            source_path = paths.memory_dir / "scopes" / "project.json"
            source_path.parent.mkdir(parents=True)
            source = {
                "schema_version": "omh_memory_scope/v2",
                "scope": {"kind": "project", "ref": "default"},
                "items": {
                    "live-target": {
                        "item_id": "live-item",
                        "revision": 1,
                        "key": "live_key",
                        "summary": "Original reviewed value",
                        "value": "original",
                    }
                },
                "tombstones": {},
            }
            source_path.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            batch = _batch("live-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates[0].update(
                {
                    "op": "change_scope",
                    "from_scope": {"kind": "project", "ref": "default"},
                    "to_scope": {"kind": "run", "ref": "destination"},
                }
            )
            staged = self._stage_and_remember(paths, batch)
            source_bytes = source_path.read_bytes()
            destination_path = paths.memory_dir / "scopes" / "runs" / "destination.json"
            calls = 0

            def drift_destination_after_preflight(_name: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    destination_path.parent.mkdir(parents=True)
                    destination_path.write_text(
                        json.dumps(
                            {
                                "schema_version": "omh_memory_scope/v2",
                                "scope": {"kind": "run", "ref": "destination"},
                                "items": {"live-item": {"item_id": "live-item", "value": "concurrent"}},
                                "tombstones": {},
                            },
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )

            result = apply_approved_memory_update_batch(
                paths,
                staged["batch_id"],
                write_hook=drift_destination_after_preflight,
            )

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "scope_precondition_changed")
            self.assertEqual(source_path.read_bytes(), source_bytes)

            destination_path.unlink()
            recovered = apply_approved_memory_update_batch(paths, staged["batch_id"])
            self.assertTrue(recovered["applied"])

    def test_multiscope_malformed_destination_is_rejected_before_source_mutation(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            source_path = paths.memory_dir / "scopes" / "project.json"
            destination_path = paths.memory_dir / "scopes" / "runs" / "destination.json"
            source_path.parent.mkdir(parents=True)
            destination_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {
                            "move-target": {
                                "item_id": "move-item",
                                "revision": 1,
                                "key": "move_key",
                                "summary": "Move reviewed value",
                                "value": "move value",
                            }
                        },
                        "tombstones": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            destination_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "run", "ref": "destination"},
                        "items": [],
                        "tombstones": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            batch = _batch("move-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates[0].update(
                {
                    "op": "change_scope",
                    "from_scope": {"kind": "project", "ref": "default"},
                    "to_scope": {"kind": "run", "ref": "destination"},
                    "key": "move_key",
                }
            )
            staged = self._stage_and_remember(paths, batch)
            source_bytes = source_path.read_bytes()
            destination_bytes = destination_path.read_bytes()

            first = apply_approved_memory_update_batch(paths, staged["batch_id"])
            second = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(first["applied"])
            self.assertEqual(first["reason_code"], "scope_precondition_changed")
            self.assertEqual(second, first)
            self.assertEqual(source_path.read_bytes(), source_bytes)
            self.assertEqual(destination_path.read_bytes(), destination_bytes)
            self.assertFalse(
                (paths.memory_dir / "operations" / f"{staged['operation_id']}.json").exists()
            )

    def test_multiscope_retry_recovers_after_first_durable_scope_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            source_path = paths.memory_dir / "scopes" / "project.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {
                            "move-target": {
                                "item_id": "move-item",
                                "revision": 1,
                                "key": "move_key",
                                "summary": "Move reviewed value",
                                "value": "move value",
                            }
                        },
                        "tombstones": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            batch = _batch("move-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates[0].update(
                {
                    "op": "change_scope",
                    "from_scope": {"kind": "project", "ref": "default"},
                    "to_scope": {"kind": "thread", "ref": "thread-1"},
                    "key": "move_key",
                    "summary": "Move reviewed value",
                    "value": "move value",
                }
            )
            staged = self._stage_and_remember(paths, batch)
            real_write = memory_batches_workflow.atomic_write_json
            crashed = False

            def crash_after_first_scope(path, payload, **kwargs):
                nonlocal crashed
                real_write(path, payload, **kwargs)
                if not crashed and "scopes" in Path(path).parts:
                    crashed = True
                    raise RuntimeError("injected crash after first durable scope write")

            with patch.object(memory_batches_workflow, "atomic_write_json", crash_after_first_scope):
                with self.assertRaisesRegex(RuntimeError, "injected crash"):
                    apply_approved_memory_update_batch(paths, staged["batch_id"])

            recovered = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertTrue(recovered["applied"])
            source = json.loads(source_path.read_text(encoding="utf-8"))
            destination = json.loads(
                (paths.memory_dir / "scopes" / "threads" / "thread-1.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("move-target", source["items"])
            self.assertEqual(source["tombstones"]["move-target"]["reason_code"], "scope_changed")
            self.assertIn("move-item", destination["items"])

    def test_multiscope_retry_rejects_scope_identity_drift_after_partial_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            source_path = paths.memory_dir / "scopes" / "project.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {
                            "move-target": {
                                "item_id": "move-item",
                                "revision": 1,
                                "key": "move_key",
                                "summary": "Move reviewed value",
                                "value": "move value",
                            }
                        },
                        "tombstones": {},
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            batch = _batch("move-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates[0].update(
                {
                    "op": "change_scope",
                    "from_scope": {"kind": "project", "ref": "default"},
                    "to_scope": {"kind": "thread", "ref": "thread-1"},
                    "key": "move_key",
                    "summary": "Move reviewed value",
                    "value": "move value",
                }
            )
            staged = self._stage_and_remember(paths, batch)
            real_write = memory_batches_workflow.atomic_write_json
            crashed = False

            def crash_after_first_scope(path, payload, **kwargs):
                nonlocal crashed
                real_write(path, payload, **kwargs)
                if not crashed and "scopes" in Path(path).parts:
                    crashed = True
                    raise RuntimeError("injected crash after first durable scope write")

            with patch.object(memory_batches_workflow, "atomic_write_json", crash_after_first_scope):
                with self.assertRaisesRegex(RuntimeError, "injected crash"):
                    apply_approved_memory_update_batch(paths, staged["batch_id"])

            altered = json.loads(source_path.read_text(encoding="utf-8"))
            altered["scope"] = {"kind": "thread", "ref": "forged-thread"}
            source_path.write_text(
                json.dumps(altered, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            altered_bytes = source_path.read_bytes()

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "scope_precondition_changed")
            self.assertEqual(source_path.read_bytes(), altered_bytes)
            self.assertFalse(
                (paths.memory_dir / "scopes" / "threads" / "thread-1.json").exists()
            )

    @requires_symlinks
    def test_multiscope_rejects_symlinked_destination_parent_without_external_write(self) -> None:
        for timing in ("before_apply", "after_preflight"):
            with self.subTest(timing=timing), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                source_path = paths.memory_dir / "scopes" / "project.json"
                source_path.parent.mkdir(parents=True)
                source_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "omh_memory_scope/v2",
                            "scope": {"kind": "project", "ref": "default"},
                            "items": {
                                "move-target": {
                                    "item_id": "move-item",
                                    "revision": 1,
                                    "key": "move_key",
                                    "summary": "Move reviewed value",
                                    "value": "move value",
                                }
                            },
                            "tombstones": {},
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                batch = _batch("move-target")
                updates = batch["updates"]
                if not isinstance(updates, list) or not isinstance(updates[0], dict):
                    self.fail("batch fixture updates must contain a mapping")
                updates[0].update(
                    {
                        "op": "change_scope",
                        "from_scope": {"kind": "project", "ref": "default"},
                        "to_scope": {"kind": "run", "ref": "destination"},
                        "key": "move_key",
                    }
                )
                staged = self._stage_and_remember(paths, batch)
                source_bytes = source_path.read_bytes()
                destination_parent = paths.memory_dir / "scopes" / "runs"
                outside = Path(home) / "outside"
                outside.mkdir()

                if timing == "before_apply":
                    destination_parent.symlink_to(outside, target_is_directory=True)
                    result = apply_approved_memory_update_batch(paths, staged["batch_id"])
                else:
                    calls = 0

                    def replace_destination_parent(_name: str) -> None:
                        nonlocal calls
                        calls += 1
                        if calls == 2:
                            destination_parent.symlink_to(outside, target_is_directory=True)

                    result = apply_approved_memory_update_batch(
                        paths,
                        staged["batch_id"],
                        write_hook=replace_destination_parent,
                    )

                self.assertFalse(result["applied"])
                self.assertEqual(result["reason_code"], "scope_precondition_changed")
                self.assertEqual(source_path.read_bytes(), source_bytes)
                self.assertFalse((outside / "destination.json").exists())

    def test_stage_rejects_live_logical_key_under_a_different_ref(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            scope_path = paths.memory_dir / "scopes" / "project.json"
            scope_path.parent.mkdir(parents=True)
            scope_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {
                            "item-a": {
                                "item_id": "item-a",
                                "revision": 1,
                                "key": "shared_key",
                                "summary": "Existing logical target",
                                "value": "existing value",
                            }
                        },
                        "tombstones": {},
                    }
                ),
                encoding="utf-8",
            )
            batch = _batch("target-b")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates[0]["key"] = "shared_key"

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                stage_memory_update_batch(paths, batch)

            self.assertFalse((paths.memory_dir / "candidates").exists())

    def test_interrupted_review_request_binds_candidate_before_orphan_replacement(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            staged = stage_memory_update_batch(paths, _batch("request-binding"))
            item_id = staged["items"][0]["item_id"]
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            real_write = memory_batches_workflow.atomic_write_json

            def interrupt_seal(path, payload, **kwargs):
                if Path(path) == candidate_path and isinstance(payload, dict) and "review_seals" in payload:
                    raise RuntimeError("injected candidate seal interruption")
                return real_write(path, payload, **kwargs)

            with patch.object(memory_batches_workflow, "atomic_write_json", side_effect=interrupt_seal):
                with self.assertRaisesRegex(RuntimeError, "candidate seal interruption"):
                    review_memory_update_batch(
                        paths,
                        staged["batch_id"],
                        {item_id: "remember"},
                        reviewer_label="operator-label",
                    )

            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            review_path = paths.memory_dir / "reviews" / f"{candidate['items'][0]['review_id']}.json"
            review_path.unlink()
            candidate["source_surface"] = "mutated-after-review-request"
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "immutable"):
                review_memory_update_batch(
                    paths,
                    staged["batch_id"],
                    {item_id: "remember"},
                    reviewer_label="operator-label",
                )

    def test_review_rejects_tampered_duplicate_candidate_item_id(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            batch = _batch("first-review-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates.append(
                {
                    "op": "update",
                    "item_id": "second-review-target",
                    "scope": {"kind": "run", "ref": "run-1"},
                    "key": "second_review_target",
                    "value": "second value",
                    "summary": "Second review target",
                }
            )
            staged = stage_memory_update_batch(paths, batch)
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            duplicate_id = candidate["items"][0]["item_id"]
            candidate["items"][1]["item_id"] = duplicate_id
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                review_memory_update_batch(
                    paths,
                    staged["batch_id"],
                    {duplicate_id: "remember"},
                    reviewer_label="operator-label",
                )

            self.assertFalse((paths.memory_dir / "reviews").exists())

    def test_review_rejects_unbound_retention_and_unsafe_review_id(self) -> None:
        for mutation in ("retention", "review_id"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                staged = stage_memory_update_batch(paths, _batch(f"review-{mutation}"))
                candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                item_id = candidate["items"][0]["item_id"]
                if mutation == "retention":
                    candidate["items"][0]["retention"]["class"] = "durable"
                else:
                    candidate["items"][0]["review_id"] = "../escaped-review"
                candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                with self.assertRaises(ValueError):
                    review_memory_update_batch(
                        paths,
                        staged["batch_id"],
                        {item_id: "remember"},
                        reviewer_label="operator-label",
                    )

                self.assertFalse((paths.memory_dir / "escaped-review.json").exists())
                self.assertFalse((paths.memory_dir / "reviews").exists())

    def test_concurrent_add_of_same_logical_target_rejects_second_candidate(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            first = self._stage_and_remember(paths, _batch("shared-target"))
            second = self._stage_and_remember(paths, _batch("shared-target"))

            self.assertEqual(
                apply_approved_memory_update_batch(paths, first["batch_id"])["status"],
                "applied",
            )
            rejected = apply_approved_memory_update_batch(paths, second["batch_id"])

            self.assertFalse(rejected["applied"])
            self.assertEqual(rejected["reason_code"], "scope_precondition_changed")
            scope = json.loads((paths.memory_dir / "scopes" / "project.json").read_text(encoding="utf-8"))
            matching = [item for item in scope["items"].values() if item.get("key") == "shared_target"]
            first_items = first["items"]
            if not isinstance(first_items, list) or not isinstance(first_items[0], dict):
                self.fail("staged batch items must contain a mapping")
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["item_id"], first_items[0]["item_id"])

    def test_stage_rejects_update_and_forget_for_same_scope_target(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            batch = _batch("shared-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates.append(
                {
                    "op": "forget",
                    "item_id": "shared-target",
                    "scope": {"kind": "project", "ref": "default"},
                }
            )

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                stage_memory_update_batch(paths, batch)

    def test_stage_rejects_duplicate_candidate_item_id_across_scopes(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            scopes = (
                (
                    paths.memory_dir / "scopes" / "project.json",
                    {"kind": "project", "ref": "default"},
                    "project-target",
                    "project_key",
                ),
                (
                    paths.memory_dir / "scopes" / "runs" / "run-1.json",
                    {"kind": "run", "ref": "run-1"},
                    "run-target",
                    "run_key",
                ),
            )
            for path, scope, target_ref, key in scopes:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "schema_version": "omh_memory_scope/v2",
                            "scope": scope,
                            "items": {
                                target_ref: {
                                    "item_id": "shared-id",
                                    "revision": 1,
                                    "key": key,
                                    "summary": f"Existing {key}",
                                    "value": f"value for {key}",
                                }
                            },
                            "tombstones": {},
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            batch = {
                "schema_version": "memory_update_batch/v1",
                "source_surface": "test",
                "updates": [
                    {
                        "op": "update",
                        "item_id": target_ref,
                        "scope": scope,
                    }
                    for _path, scope, target_ref, _key in scopes
                ],
            }

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                stage_memory_update_batch(paths, batch)

    def test_stage_rejects_distinct_ref_update_and_forget_for_same_logical_key(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            scope_path = paths.memory_dir / "scopes" / "project.json"
            scope_path.parent.mkdir(parents=True)
            scope_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {
                            "old-ref": {
                                "item_id": "old-ref",
                                "revision": 1,
                                "key": "shared_key",
                                "summary": "Existing logical target",
                                "value": "existing value",
                            }
                        },
                        "tombstones": {},
                    }
                ),
                encoding="utf-8",
            )
            batch = _batch("new-ref")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates[0]["key"] = "shared_key"
            updates.append(
                {
                    "op": "forget",
                    "item_id": "old-ref",
                    "scope": {"kind": "project", "ref": "default"},
                }
            )

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                stage_memory_update_batch(paths, batch)

    def test_stage_rejects_duplicate_logical_key_in_same_scope(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            batch = _batch("first-target")
            updates = batch["updates"]
            if not isinstance(updates, list) or not isinstance(updates[0], dict):
                self.fail("batch fixture updates must contain a mapping")
            updates.append(
                {
                    "op": "update",
                    "item_id": "second-target",
                    "scope": {"kind": "project", "ref": "default"},
                    "key": updates[0]["key"],
                    "summary": "Second logical copy",
                    "value": "second value",
                }
            )

            with self.assertRaisesRegex(ValueError, "ambiguous"):
                stage_memory_update_batch(paths, batch)

    def test_unrelated_batch_does_not_poison_interrupted_batch_recovery(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            first_batch = {
                "schema_version": "memory_update_batch/v1",
                "source_surface": "test",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "project-item",
                        "scope": {"kind": "project", "ref": "default"},
                        "key": "project_item",
                        "value": "project value",
                        "summary": "Project item",
                    },
                    {
                        "op": "update",
                        "item_id": "thread-item",
                        "scope": {"kind": "thread", "ref": "thread-1"},
                        "key": "thread_item",
                        "value": "thread value",
                        "summary": "Thread item",
                    },
                ],
            }
            first = self._stage_and_remember(paths, first_batch)
            calls = 0

            def interrupt_second(_name: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("injected interruption")

            with self.assertRaisesRegex(RuntimeError, "injected interruption"):
                apply_approved_memory_update_batch(paths, first["batch_id"], write_hook=interrupt_second)
            operation_paths = list((paths.memory_dir / "operations").glob("op_apply_*.json"))
            self.assertEqual(len(operation_paths), 1)
            operation_path = operation_paths[0]

            second = self._stage_and_remember(
                paths,
                _batch("run-item", scope={"kind": "run", "ref": "run-2"}),
            )
            self.assertEqual(
                apply_approved_memory_update_batch(paths, second["batch_id"])["status"],
                "applied",
            )
            interrupted = json.loads(operation_path.read_text(encoding="utf-8"))
            self.assertEqual(interrupted["state"], "interrupted")
            self.assertEqual(
                apply_approved_memory_update_batch(paths, first["batch_id"])["status"],
                "applied",
            )

    def test_stage_rejects_credential_shaped_legacy_item_id_without_echo(self) -> None:
        credential = "gh" + "u_" + "a" * 36
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            scope_path = paths.memory_dir / "scopes" / "project.json"
            scope_path.parent.mkdir(parents=True)
            scope_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v2",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {
                            "legacy-target": {
                                "item_id": credential,
                                "key": "safe_key",
                                "summary": "Safe legacy summary",
                                "value": "safe legacy value",
                            }
                        },
                        "tombstones": {},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as caught:
                stage_memory_update_batch(paths, _batch("legacy-target"))

            self.assertNotIn(credential, str(caught.exception))
            self.assertFalse((paths.memory_dir / "candidates").exists())

    def test_apply_rejects_missing_wrong_or_extra_review_seals_before_any_write(self) -> None:
        for mutation in ("missing", "wrong", "extra"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                staged = self._stage_and_remember(paths, _batch(f"{mutation}-review-seal"))
                candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                item_id = staged["items"][0]["item_id"]
                seals = candidate["review_seals"]
                self.assertIsInstance(seals, dict)
                if mutation == "missing":
                    seals.pop(item_id)
                elif mutation == "wrong":
                    seals[item_id] = "0" * 64
                else:
                    seals["phantom-item"] = "0" * 64
                candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

                result = apply_approved_memory_update_batch(paths, staged["batch_id"])

                self.assertFalse(result["applied"])
                self.assertEqual(result["reason_code"], "review_linkage_invalid")
                self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_apply_binds_full_candidate_item_membership_before_any_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            batch = _batch("remember-membership")
            updates = batch["updates"]
            if not isinstance(updates, list):
                self.fail("batch fixture updates must be a list")
            updates.append(
                {
                    "op": "update",
                    "item_id": "defer-membership",
                    "scope": {"kind": "project", "ref": "default"},
                    "key": "defer_membership",
                    "value": "value for deferred membership",
                    "summary": "Remember deferred membership",
                }
            )
            staged = stage_memory_update_batch(paths, batch)
            decisions = {
                staged["items"][0]["item_id"]: "remember",
                staged["items"][1]["item_id"]: "defer",
            }
            review_memory_update_batch(paths, staged["batch_id"], decisions, reviewer_label="operator-label")
            candidate_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            removed = candidate["items"].pop()
            candidate["review_seals"].pop(removed["item_id"])
            candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertFalse(result["applied"])
            self.assertEqual(result["reason_code"], "review_linkage_invalid")
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_refused_or_deferred_items_never_write(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            batch = _batch("remember")
            batch["updates"].append(
                {
                    "op": "update",
                    "item_id": "defer",
                    "scope": {"kind": "project", "ref": "default"},
                    "key": "defer",
                    "value": "value for defer",
                    "summary": "Remember defer",
                }
            )
            staged = stage_memory_update_batch(paths, batch)
            decisions = {staged["items"][0]["item_id"]: "remember", staged["items"][1]["item_id"]: "defer"}
            review_memory_update_batch(paths, staged["batch_id"], decisions, reviewer_label="operator-label")

            result = apply_approved_memory_update_batch(paths, staged["batch_id"])

            self.assertEqual(result["status"], "review_required")
            self.assertFalse((paths.memory_dir / "scopes").exists())

    def test_interrupted_apply_is_ineligible_until_exactly_once_recovery(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            batch = _batch("project-item")
            batch["updates"].append(
                {
                    "op": "update",
                    "item_id": "thread-item",
                    "scope": {"kind": "thread", "ref": "thread-1"},
                    "key": "thread_item",
                    "value": "value for thread-item",
                    "summary": "Remember thread-item",
                }
            )
            staged = self._stage_and_remember(paths, batch)
            writes = 0

            def interrupt_on_second_write(_name: str) -> None:
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise RuntimeError("injected named write interruption")

            with self.assertRaisesRegex(RuntimeError, "injected named write interruption"):
                apply_approved_memory_update_batch(paths, staged["batch_id"], write_hook=interrupt_on_second_write)

            interrupted = build_handoff_context_pack(paths)
            self.assertFalse({item["item_id"] for item in interrupted["included_context"]} & {row["item_id"] for row in staged["items"]})
            self.assertEqual(
                apply_approved_memory_update_batch(paths, staged["batch_id"])["status"],
                "applied",
            )
            recovered = build_handoff_context_pack(paths)
            ids = [item["item_id"] for item in recovered["included_context"]]
            self.assertTrue({row["item_id"] for row in staged["items"]} <= set(ids))

    def test_v1_scope_item_keeps_legacy_review_reason(self) -> None:
        with TemporaryDirectory() as home:
            paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
            scope_path = paths.memory_dir / "scopes" / "project.json"
            scope_path.parent.mkdir(parents=True)
            scope_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v1",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {"legacy-item": {"item_id": "legacy-item", "key": "legacy", "summary": "Legacy item", "value": "legacy value"}},
                    }
                ),
                encoding="utf-8",
            )

            item = next(item for snapshot in _memory_snapshots(paths) for item in snapshot["items"] if item["item_id"] == "legacy-item")

            self.assertEqual(item["replay_evaluation"]["reason_code"], "review_required_legacy")

    @requires_fcntl_locks
    def test_two_process_apply_serializes_same_scope_and_preserves_different_scopes(self) -> None:
        for distinct_scopes in (False, True):
            with self.subTest(distinct_scopes=distinct_scopes), TemporaryDirectory() as home:
                paths = resolve_paths(Path(home) / ".omh", Path(home) / ".hermes")
                first = self._stage_and_remember(paths, _batch("first-item"))
                second_scope = {"kind": "thread", "ref": "thread-2"} if distinct_scopes else None
                second = self._stage_and_remember(paths, _batch("second-item", scope=second_scope))
                context = multiprocessing.get_context("spawn")
                barrier = context.Barrier(3)
                first_ready, second_ready, queue = context.Event(), context.Event(), context.Queue()
                workers = [
                    context.Process(target=_apply_worker, args=(home, staged["batch_id"], barrier, ready, queue))
                    for staged, ready in ((first, first_ready), (second, second_ready))
                ]
                for worker in workers:
                    worker.start()
                self.assertTrue(first_ready.wait(timeout=10))
                self.assertTrue(second_ready.wait(timeout=10))
                barrier.wait(timeout=10)
                for worker in workers:
                    worker.join(timeout=10)
                    self.assertEqual(worker.exitcode, 0)
                self.assertCountEqual([queue.get(timeout=2), queue.get(timeout=2)], [("applied", first["batch_id"]), ("applied", second["batch_id"])])
                ids = {item["item_id"] for item in build_handoff_context_pack(paths)["included_context"]}
                self.assertTrue({first["items"][0]["item_id"], second["items"][0]["item_id"]} <= ids)
