from __future__ import annotations

import json
import multiprocessing
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from _local_package import load_local_package
from _platform_support import requires_fcntl_locks

load_local_package()
from omh.local_store import atomic_write_json, ensure_dir, read_json_object_result
from omh.paths import OmhPaths
from omh.workflows.memory_store import (
    apply_memory_operation_step,
    prune_expired_memory_evidence,
    recover_memory_operations,
    run_memory_operation,
    validate_memory_receipt,
    write_memory_tombstone,
)

NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


def _paths(root: str) -> OmhPaths:
    base = Path(root)
    return OmhPaths(base / "omh", base / "hermes")


def _stage(paths: OmhPaths, name: str, payload: dict[str, Any]) -> None:
    atomic_write_json(paths.memory_dir / "staging" / name, payload, private=True)


def _process_writer(root: str, operation_id: str, marker: str, barrier: Any, ready: Any) -> None:
    paths = _paths(root)
    barrier.wait()

    def writer(active_paths: OmhPaths, step: dict[str, str]) -> None:
        target = active_paths.memory_dir / step["target"]
        current, _ = read_json_object_result(target)
        entries = dict(current.get("entries", {})) if current else {}
        entries[step["key"]] = marker
        atomic_write_json(target, {"entries": entries}, private=True)
        ready.set()

    run_memory_operation(
        paths,
        operation_id=operation_id,
        operation_type="scope_update",
        steps=[{"name": "merge_scope", "action": "merge", "target": "scopes/project.json", "key": marker}],
        step_writer=writer,
        now=NOW,
    )


class MemoryOperationTests(unittest.TestCase):
    def test_paths_expose_memory_lifecycle_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            self.assertEqual(paths.memory_operations_dir, paths.memory_dir / "operations")
            self.assertEqual(paths.memory_tombstones_dir, paths.memory_dir / "tombstones")
            self.assertEqual(paths.memory_migrations_dir, paths.memory_dir / "migrations")
            self.assertEqual(paths.memory_history_dir, paths.memory_dir / "history")
            self.assertEqual(paths.memory_archive_dir, paths.memory_dir / "archive")

    def test_multi_step_operation_completes_with_one_metadata_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "first.json", {"entry": "first"})
            _stage(paths, "second.json", {"entry": "second"})
            rebuilds: list[str] = []

            def rebuild(active_paths: OmhPaths) -> None:
                self.assertTrue((active_paths.memory_dir / "records/two.json").exists())
                rebuilds.append("rebuilt")

            result = run_memory_operation(
                paths,
                operation_id="op-multi",
                operation_type="migration",
                steps=[
                    {"name": "copy_candidate", "action": "copy", "source": "staging/first.json", "target": "candidates/one.json"},
                    {"name": "move_record", "action": "move", "source": "staging/second.json", "target": "records/two.json"},
                ],
                rebuild_index=rebuild,
                now=NOW,
            )
            stored, error = read_json_object_result(paths.memory_operations_dir / "op-multi.json")
            self.assertIsNone(error)
            self.assertEqual(result["state"], "completed")
            self.assertEqual(stored, result)
            self.assertEqual(len([key for key in result if key == "receipt"]), 1)
            self.assertEqual(validate_memory_receipt(result["receipt"]), [])
            self.assertEqual(rebuilds, ["rebuilt"])
            self.assertTrue((paths.memory_dir / "candidates/one.json").exists())
            self.assertTrue((paths.memory_dir / "records/two.json").exists())
            self.assertFalse((paths.memory_dir / "staging/second.json").exists())

    def test_operation_id_cannot_be_reused_for_a_different_request(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "first.json", {"entry": "first"})
            _stage(paths, "second.json", {"entry": "second"})
            operation_id = "op-request-binding"
            run_memory_operation(
                paths,
                operation_id=operation_id,
                operation_type="write",
                steps=[
                    {
                        "name": "write_first",
                        "action": "copy",
                        "source": "staging/first.json",
                        "target": "records/first.json",
                    }
                ],
                now=NOW,
            )
            operation_path = paths.memory_operations_dir / f"{operation_id}.json"
            completed_bytes = operation_path.read_bytes()

            with self.assertRaisesRegex(ValueError, "already bound"):
                run_memory_operation(
                    paths,
                    operation_id=operation_id,
                    operation_type="write",
                    steps=[
                        {
                            "name": "write_second",
                            "action": "copy",
                            "source": "staging/second.json",
                            "target": "records/second.json",
                        }
                    ],
                    now=NOW,
                )

            self.assertEqual(operation_path.read_bytes(), completed_bytes)
            self.assertTrue((paths.memory_dir / "records" / "first.json").exists())
            self.assertFalse((paths.memory_dir / "records" / "second.json").exists())

    def test_interrupted_named_write_recovers_once_without_duplicate_move(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "one.json", {"entry": "one"})
            _stage(paths, "two.json", {"entry": "two"})
            failed = {"value": False}

            def writer(active_paths: OmhPaths, step: dict[str, str]) -> None:
                if step["name"] == "move_two" and not failed["value"]:
                    failed["value"] = True
                    raise RuntimeError("injected")
                apply_memory_operation_step(active_paths, step)

            kwargs = {
                "operation_id": "op-recover",
                "operation_type": "migration",
                "steps": [
                    {"name": "copy_one", "action": "copy", "source": "staging/one.json", "target": "candidates/one.json"},
                    {"name": "move_two", "action": "move", "source": "staging/two.json", "target": "records/two.json"},
                ],
                "step_writer": writer,
                "now": NOW,
            }
            with self.assertRaisesRegex(RuntimeError, "injected"):
                run_memory_operation(paths, **kwargs)
            interrupted, _ = read_json_object_result(paths.memory_operations_dir / "op-recover.json")
            assert interrupted is not None
            self.assertEqual(interrupted["state"], "interrupted")
            self.assertEqual(interrupted["steps"][1]["state"], "interrupted")
            recovered = run_memory_operation(paths, **kwargs)
            repeated = run_memory_operation(paths, **kwargs)
            self.assertEqual(recovered["state"], "completed")
            self.assertEqual(recovered["recovery_count"], 1)
            self.assertEqual(repeated["recovery_count"], 1)
            self.assertTrue((paths.memory_dir / "records/two.json").exists())
            self.assertFalse((paths.memory_dir / "staging/two.json").exists())

    def test_cancelled_operation_resumes_from_interrupted_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "resume.json", {"entry": "resumed"})
            cancelled = {"value": False}

            def writer(active_paths: OmhPaths, step: dict[str, str]) -> None:
                if not cancelled["value"]:
                    cancelled["value"] = True
                    raise KeyboardInterrupt
                apply_memory_operation_step(active_paths, step)

            kwargs = {
                "operation_id": "op-cancel",
                "operation_type": "write",
                "steps": [{"name": "resume", "action": "copy", "source": "staging/resume.json", "target": "records/resume.json"}],
                "step_writer": writer,
                "now": NOW,
            }
            with self.assertRaises(KeyboardInterrupt):
                run_memory_operation(paths, **kwargs)
            recovered = recover_memory_operations(paths, step_writer=writer, now=NOW)
            self.assertEqual(recovered[0]["state"], "completed")
            self.assertEqual(recovered[0]["recovery_count"], 1)

    def test_repeated_interruptions_resume_without_duplicate_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "repeat.json", {"entry": "repeat"})
            attempts = {"count": 0}

            def writer(active_paths: OmhPaths, step: dict[str, str]) -> None:
                attempts["count"] += 1
                if attempts["count"] < 3:
                    raise RuntimeError("interrupted")
                apply_memory_operation_step(active_paths, step)

            kwargs = {"operation_id": "op-repeat", "operation_type": "write", "steps": [{"name": "repeat", "action": "move", "source": "staging/repeat.json", "target": "records/repeat.json"}], "step_writer": writer, "now": NOW}
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                run_memory_operation(paths, **kwargs)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                run_memory_operation(paths, **kwargs)
            recovered = run_memory_operation(paths, **kwargs)
            self.assertEqual(recovered["recovery_count"], 2)
            self.assertEqual(attempts["count"], 3)
            self.assertTrue((paths.memory_dir / "records/repeat.json").exists())
            self.assertFalse((paths.memory_dir / "staging/repeat.json").exists())

    def test_builtin_payload_steps_atomically_write_replace_and_remove(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            atomic_write_json(paths.memory_dir / "records/remove.json", {"remove": True}, private=True)

            result = run_memory_operation(
                paths,
                operation_id="op-lifecycle-builtins",
                operation_type="memory_lifecycle_prune",
                steps=[
                    {"name": "write", "action": "write_json", "target": "candidates/new.json", "payload": {"nested": {"value": "written"}}},
                    {"name": "rewrite", "action": "rewrite_jsonl", "target": "write_journal.jsonl", "payload": [{"event": "survives"}]},
                    {"name": "delete", "action": "delete", "target": "records/remove.json"},
                ],
                now=NOW,
            )

            self.assertEqual(result["state"], "completed")
            self.assertEqual(json.loads((paths.memory_dir / "candidates/new.json").read_text()), {"nested": {"value": "written"}})
            self.assertEqual((paths.memory_dir / "write_journal.jsonl").read_text(), '{"event":"survives"}\n')
            self.assertFalse((paths.memory_dir / "records/remove.json").exists())
            self.assertEqual([step.get("outcome") for step in result["steps"]], ["written", "rewritten", "removed"])

            with self.assertRaisesRegex(ValueError, "write_json requires an object payload"):
                run_memory_operation(
                    paths,
                    operation_id="op-invalid-payload",
                    operation_type="memory_lifecycle_restore",
                    steps=[{"name": "bad", "action": "write_json", "target": "candidates/bad.json", "payload": []}],
                    now=NOW,
                )
            self.assertFalse((paths.memory_operations_dir / "op-invalid-payload.json").exists())

    def test_interrupted_builtin_steps_recover_from_the_durable_payload_log(self) -> None:
        cases = {
            "write_json": ({"name": "write", "action": "write_json", "target": "candidates/recovered.json", "payload": {"value": "recovered"}}, "written"),
            "delete": ({"name": "delete", "action": "delete", "target": "records/remove.json"}, "already_absent"),
            "rewrite_jsonl": ({"name": "rewrite", "action": "rewrite_jsonl", "target": "write_journal.jsonl", "payload": [{"event": "recovered"}]}, "rewritten"),
            "move": ({"name": "move", "action": "move", "source": "staging/move.json", "target": "records/moved.json"}, "already_present"),
        }
        for action, (step, expected_outcome) in cases.items():
            with self.subTest(action=action), TemporaryDirectory() as tmp:
                paths = _paths(tmp)
                if action == "delete":
                    atomic_write_json(paths.memory_dir / "records/remove.json", {"remove": True}, private=True)
                if action == "move":
                    _stage(paths, "move.json", {"moved": True})
                interrupted = {"value": False}

                def writer(active_paths: OmhPaths, active_step: dict[str, object]) -> str:
                    outcome = apply_memory_operation_step(active_paths, active_step)
                    if not interrupted["value"]:
                        interrupted["value"] = True
                        raise RuntimeError("interrupted")
                    return outcome

                with self.assertRaisesRegex(RuntimeError, "interrupted"):
                    run_memory_operation(
                        paths,
                        operation_id=f"op-recover-{action}",
                        operation_type="memory_lifecycle_test",
                        steps=[step],
                        step_writer=writer,
                        now=NOW,
                    )
                recovered = recover_memory_operations(paths, now=NOW)
                record = recovered[0]
                self.assertEqual(record["state"], "completed")
                self.assertEqual(record["recovery_count"], 1)
                self.assertEqual(record["steps"][0]["outcome"], expected_outcome)
                if action == "write_json":
                    self.assertEqual(json.loads((paths.memory_dir / "candidates/recovered.json").read_text()), {"value": "recovered"})
                elif action == "delete":
                    self.assertFalse((paths.memory_dir / "records/remove.json").exists())
                elif action == "rewrite_jsonl":
                    self.assertEqual((paths.memory_dir / "write_journal.jsonl").read_text(), '{"event":"recovered"}\n')
                else:
                    self.assertTrue((paths.memory_dir / "records/moved.json").exists())
                    self.assertFalse((paths.memory_dir / "staging/move.json").exists())

    def test_malformed_step_is_rejected_before_an_operation_record_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            with self.assertRaisesRegex(ValueError, "invalid memory operation step"):
                run_memory_operation(paths, operation_id="op-bad", operation_type="write", steps=[{"name": "bad", "action": "copy", "source": "staging/a.json", "target": "records/a.json", "summary": "private"}], now=NOW)
            self.assertFalse(paths.memory_operations_dir.exists())

    @requires_fcntl_locks
    def test_two_processes_serialize_same_target_without_lost_updates(self) -> None:
        with TemporaryDirectory() as tmp:
            context = multiprocessing.get_context("spawn")
            barrier = context.Barrier(2)
            first_ready, second_ready = context.Event(), context.Event()
            workers = [
                context.Process(target=_process_writer, args=(tmp, "op-process-a", "a", barrier, first_ready)),
                context.Process(target=_process_writer, args=(tmp, "op-process-b", "b", barrier, second_ready)),
            ]
            for worker in workers:
                worker.start()
            self.assertTrue(first_ready.wait(20))
            self.assertTrue(second_ready.wait(20))
            for worker in workers:
                worker.join(20)
                self.assertEqual(worker.exitcode, 0)
            state, error = read_json_object_result(_paths(tmp).memory_dir / "scopes/project.json")
            self.assertIsNone(error)
            self.assertEqual(state, {"entries": {"a": "a", "b": "b"}})

    def test_different_scopes_stay_isolated(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "project.json", {"scope": "project"})
            _stage(paths, "target.json", {"scope": "target"})
            run_memory_operation(paths, operation_id="op-project", operation_type="write", steps=[{"name": "project", "action": "copy", "source": "staging/project.json", "target": "scopes/project.json"}], now=NOW)
            run_memory_operation(paths, operation_id="op-target", operation_type="write", steps=[{"name": "target", "action": "copy", "source": "staging/target.json", "target": "scopes/targets/alpha.json"}], now=NOW)
            project, _ = read_json_object_result(paths.memory_dir / "scopes/project.json")
            target, _ = read_json_object_result(paths.memory_dir / "scopes/targets/alpha.json")
            index, _ = read_json_object_result(paths.memory_index_path)
            self.assertEqual(project, {"scope": "project"})
            self.assertEqual(target, {"scope": "target"})
            self.assertEqual(index["schema_version"], "omh_memory_index/v1")

    def test_evidence_sweep_drops_only_expired_operation_and_tombstone_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            old = (NOW - timedelta(days=30)).isoformat().replace("+00:00", "Z")
            recent = (NOW - timedelta(days=29)).isoformat().replace("+00:00", "Z")
            ensure_dir(paths.memory_operations_dir, private=True)
            atomic_write_json(paths.memory_operations_dir / "old.json", {"schema_version": "memory_operation/v1", "operation_id": "old", "state": "completed", "created_at": old}, private=True)
            atomic_write_json(paths.memory_operations_dir / "recent.json", {"schema_version": "memory_operation/v1", "operation_id": "recent", "state": "completed", "created_at": recent}, private=True)
            write_memory_tombstone(paths, {"tombstone_id": "old-tomb", "record_id": "old", "revision": 1, "tombstoned_at": old})
            write_memory_tombstone(paths, {"tombstone_id": "recent-tomb", "record_id": "recent", "revision": 1, "tombstoned_at": recent})
            atomic_write_json(paths.memory_dir / "records/user.json", {"summary": "user memory"}, private=True)
            result = prune_expired_memory_evidence(paths, now=NOW)
            self.assertEqual(result["removed_operations"], ["old"])
            self.assertEqual(result["removed_tombstones"], ["old-tomb"])
            self.assertTrue((paths.memory_operations_dir / "recent.json").exists())
            self.assertTrue((paths.memory_tombstones_dir / "recent-tomb.json").exists())
            self.assertTrue((paths.memory_dir / "records/user.json").exists())

    def test_receipt_allowlist_rejects_content_bearing_fields(self) -> None:
        errors = validate_memory_receipt({"operation_id": "op", "state": "completed", "summary": "secret", "value": "secret", "content_hash": "hash", "absolute_path": "/tmp/private"})
        self.assertEqual(errors, ["receipt has unsupported fields: absolute_path, content_hash, summary, value"])

    def test_deterministic_validation_failure_marks_record_failed_and_blocks_retry(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "good.json", {"entry": "good"})
            ensure_dir(paths.memory_dir / "staging", private=True)
            Path(paths.memory_dir / "staging" / "bad.json").symlink_to(paths.memory_dir / "staging" / "good.json")
            with self.assertRaisesRegex(ValueError, "operation source is a symlink"):
                run_memory_operation(
                    paths,
                    operation_id="op-fail-symlink",
                    operation_type="migration",
                    steps=[{"name": "copy_bad", "action": "copy", "source": "staging/bad.json", "target": "candidates/result.json"}],
                    now=NOW,
                )
            failed, _ = read_json_object_result(paths.memory_operations_dir / "op-fail-symlink.json")
            self.assertIsNotNone(failed)
            self.assertEqual(failed["state"], "failed")
            self.assertEqual(failed["steps"][0]["state"], "failed")
            retry = run_memory_operation(paths, operation_id="op-fail-symlink", operation_type="migration", steps=[{"name": "copy_bad", "action": "copy", "source": "staging/bad.json", "target": "candidates/result.json"}], now=NOW)
            self.assertEqual(retry["state"], "failed")
            self.assertFalse((paths.memory_dir / "candidates/result.json").exists())

    def test_invalid_stuck_operation_is_rewritten_terminal_corrupt_before_later_work(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            ensure_dir(paths.memory_operations_dir, private=True)
            atomic_write_json(
                paths.memory_operations_dir / "op-invalid.json",
                {
                    "schema_version": "memory_operation/v1",
                    "operation_id": "op-invalid",
                    "operation_type": "write",
                    "state": "interrupted",
                    "created_at": "not-a-timestamp",
                    "updated_at": "not-a-timestamp",
                    "recovery_count": 0,
                    "steps": [],
                },
                private=True,
            )

            recovered = recover_memory_operations(paths, now=NOW)
            persisted, error = read_json_object_result(paths.memory_operations_dir / "op-invalid.json")

            self.assertIsNone(error)
            self.assertEqual(recovered[0]["state"], "corrupt")
            self.assertEqual(persisted["state"], "corrupt")
            self.assertEqual(recover_memory_operations(paths, now=NOW)[0]["state"], "corrupt")
            _stage(paths, "good.json", {"entry": "good"})
            result = run_memory_operation(
                paths,
                operation_id="op-after-corrupt",
                operation_type="write",
                steps=[{"name": "copy_good", "action": "copy", "source": "staging/good.json", "target": "records/result.json"}],
                now=NOW,
            )
            self.assertEqual(result["state"], "completed")
            self.assertTrue((paths.memory_dir / "records/result.json").exists())

    def test_unrelated_operation_completes_after_permanent_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _stage(paths, "good.json", {"entry": "good"})
            ensure_dir(paths.memory_dir / "staging", private=True)
            Path(paths.memory_dir / "staging" / "bad.json").symlink_to(paths.memory_dir / "staging" / "good.json")
            with self.assertRaisesRegex(ValueError, "operation source is a symlink"):
                run_memory_operation(
                    paths,
                    operation_id="op-first-fail",
                    operation_type="write",
                    steps=[{"name": "copy_bad", "action": "copy", "source": "staging/bad.json", "target": "candidates/result.json"}],
                    now=NOW,
                )
            first_failed, _ = read_json_object_result(paths.memory_operations_dir / "op-first-fail.json")
            self.assertEqual(first_failed["state"], "failed")
            result = run_memory_operation(
                paths,
                operation_id="op-second-ok",
                operation_type="write",
                steps=[{"name": "copy_good", "action": "copy", "source": "staging/good.json", "target": "records/result.json"}],
                now=NOW,
            )
            self.assertEqual(result["state"], "completed")
            self.assertTrue((paths.memory_dir / "records/result.json").exists())
            first_still_failed, _ = read_json_object_result(paths.memory_operations_dir / "op-first-fail.json")
            self.assertEqual(first_still_failed["state"], "failed")


if __name__ == "__main__":
    unittest.main()
