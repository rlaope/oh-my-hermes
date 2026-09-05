from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from _local_package import load_local_package

load_local_package()
from omh.local_store import atomic_write_json
from omh.paths import OmhPaths
from omh.plugin_bundle.omh import memory_governance as governance
from omh.workflows.memory_lifecycle_executor import execute_memory_lifecycle, lifecycle_operation_steps
from omh.workflows.memory_store import apply_memory_operation_step, run_memory_operation
from omh.workflows.memory_lifecycle import (
    apply_memory_correction,
    apply_memory_prune,
    apply_memory_reapproval,
    apply_memory_restore,
    apply_memory_retirement,
    build_memory_correction,
    build_memory_prune,
    build_memory_reapproval,
    build_memory_restore,
    build_memory_retirement,
    lifecycle_replay_status,
    make_lifecycle_receipt,
    validate_lifecycle_receipt,
)

NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


def _paths(root: str) -> OmhPaths:
    return OmhPaths(Path(root) / "omh", Path(root) / "hermes")


def _record(record_id: str, revision: int, scope: str, retention: str, *, admitted_at: datetime = NOW) -> tuple[dict[str, Any], dict[str, Any]]:
    value: dict[str, Any] = {
        "schema_version": governance.PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "revision": revision,
        "record_type": "fact",
        "summary": f"{record_id} review-visible summary",
        "scope": {"kind": "project", "ref": scope},
        "source_class": "omh_local",
        "retention": governance.build_retention(retention, record_type="fact", admitted_at=admitted_at, ttl_days=7 if retention == "standard" else None),
    }
    identity = governance.stable_artifact_identity(value)
    digest = governance.canonical_payload_digest(value)
    value["admission"] = {"state": "approved_manual", "review_id": f"review-{record_id}-{revision}", "artifact_identity": identity, "payload_digest": digest}
    review = {"schema_version": governance.PROJECT_MEMORY_REVIEW_RECORD_SCHEMA_VERSION, "review_id": value["admission"]["review_id"], "artifact_identity": identity, "decision": "approved_manual", "payload_digest": digest}
    return value, review


def _write_fixture(paths: OmhPaths, record_id: str = "mem-one", revision: int = 1, scope: str = "one", retention: str = "volatile", *, admitted_at: datetime = NOW - timedelta(days=7)) -> dict[str, Any]:
    record, review = _record(record_id, revision, scope, retention, admitted_at=admitted_at)
    atomic_write_json(paths.memory_dir / "records" / f"{record_id}.json", record, private=True)
    atomic_write_json(paths.memory_dir / "reviews" / f"{review['review_id']}.json", review, private=True)
    return record


class _Executor:
    def __init__(self, *, interrupt_after: str = "") -> None:
        self.interrupt_after, self.interrupted = interrupt_after, False
        self.applied: dict[str, set[str]] = {}
        self.outcomes: dict[str, list[dict[str, object]]] = {}

    def __call__(self, paths: OmhPaths, plan: Any) -> dict[str, object]:
        done = self.applied.setdefault(plan.operation_id, set())
        outcomes = self.outcomes.setdefault(plan.operation_id, [])
        for mutation in plan.mutations:
            if mutation.name in done:
                continue
            target = paths.memory_dir / mutation.target
            if mutation.action == "move":
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(paths.memory_dir / str(mutation.source), target)
            elif mutation.action == "write":
                atomic_write_json(target, dict(mutation.payload or {}), private=True)
            elif mutation.action == "delete":
                target.unlink(missing_ok=True)
            elif mutation.action == "rewrite_jsonl":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("\n".join(json.dumps(item, sort_keys=True) for item in mutation.payload or ()) + "\n", encoding="utf-8")
            else:
                raise AssertionError(mutation.action)
            done.add(mutation.name)
            outcomes.append({"target_id": mutation.target_id, "artifact_kind": mutation.artifact_kind, "outcome": "removed", "reason_code": "applied"})
            if mutation.name == self.interrupt_after and not self.interrupted:
                self.interrupted = True
                raise RuntimeError("interrupted")
        return {"receipt": make_lifecycle_receipt(plan, outcomes)}


class MemoryLifecycleTests(unittest.TestCase):
    def test_volatile_ttl_and_exact_expiry_keep_review_metadata(self) -> None:
        record, _ = _record("mem-boundary", 1, "one", "volatile", admitted_at=NOW)
        before = lifecycle_replay_status(record, now=NOW + timedelta(days=7) - timedelta(microseconds=1))
        boundary = lifecycle_replay_status(record, now=NOW + timedelta(days=7))
        self.assertTrue(before["replay_eligible"])
        self.assertEqual(boundary["reason_code"], "expired_volatile")
        self.assertEqual(boundary["record_id"], "mem-boundary")
        self.assertNotIn("summary", json.dumps(boundary))
        for ttl in (1, 7):
            self.assertEqual(governance.build_retention("volatile", record_type="fact", admitted_at=NOW, ttl_days=ttl)["ttl_days"], ttl)
        for ttl in (0, 8):
            with self.assertRaises(ValueError):
                governance.build_retention("volatile", record_type="fact", admitted_at=NOW, ttl_days=ttl)

    def test_retire_restore_reapprove_and_restore_conflict(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, executor = _paths(tmp), _Executor()
            _write_fixture(paths, retention="standard")
            retirement = build_memory_retirement(paths, "mem-one", 1, now=NOW)
            apply_memory_retirement(paths, retirement, transaction_executor=executor)
            archive_path = paths.memory_dir / "archive" / "mem-one.r1.json"
            archive_before = archive_path.read_text()
            self.assertTrue(archive_path.exists())
            self.assertTrue((paths.memory_dir / "tombstones/retired-mem-one-r1.json").exists())
            restore = build_memory_restore(paths, "mem-one", 1, now=NOW, candidate_id="cand-restore")
            apply_memory_restore(paths, restore, transaction_executor=executor)
            candidate = json.loads((paths.memory_dir / "candidates/cand-restore.json").read_text())
            self.assertEqual(candidate["admission"]["state"], "pending_review")
            self.assertEqual(candidate["origin"]["revision"], 1)
            self.assertEqual(archive_path.read_text(), archive_before)
            reapproval = build_memory_reapproval(paths, "cand-restore", reviewer_claim="reviewer", now=NOW)
            apply_memory_reapproval(paths, reapproval, transaction_executor=executor)
            self.assertEqual(json.loads((paths.memory_dir / "records/mem-one.json").read_text())["revision"], 2)
            conflict = build_memory_restore(paths, "mem-one", 1, now=NOW, candidate_id="cand-conflict")
            self.assertFalse(conflict.report["eligible"])
            self.assertEqual(conflict.report["reason_code"], "newer_live_revision_conflict")

    def test_restore_rescans_legacy_archive_before_creating_a_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, executor = _paths(tmp), _Executor()
            _write_fixture(paths, retention="standard")
            retirement = build_memory_retirement(paths, "mem-one", 1, now=NOW)
            apply_memory_retirement(paths, retirement, transaction_executor=executor)
            archive_path = paths.memory_dir / "archive/mem-one.r1.json"
            archive = json.loads(archive_path.read_text())
            credential = "gh" + "u_" + "a" * 36
            archive["source"] = credential
            atomic_write_json(archive_path, archive, private=True)

            plan = build_memory_restore(paths, "mem-one", 1, now=NOW, candidate_id="cand-unsafe")

            self.assertFalse(plan.report["eligible"])
            self.assertEqual(plan.report["reason_code"], "safety_blocked_in_source")
            self.assertEqual(plan.mutations, ())
            self.assertNotIn(credential, json.dumps(plan.report, sort_keys=True))
            self.assertFalse((paths.memory_dir / "candidates/cand-unsafe.json").exists())

    def test_reapproval_rescans_existing_candidate_before_writing_a_record(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, executor = _paths(tmp), _Executor()
            _write_fixture(paths, retention="standard")
            apply_memory_retirement(
                paths,
                build_memory_retirement(paths, "mem-one", 1, now=NOW),
                transaction_executor=executor,
            )
            restore = build_memory_restore(paths, "mem-one", 1, now=NOW, candidate_id="cand-existing")
            apply_memory_restore(paths, restore, transaction_executor=executor)
            candidate_path = paths.memory_dir / "candidates/cand-existing.json"
            candidate = json.loads(candidate_path.read_text())
            credential = "gh" + "u_" + "a" * 36
            candidate["replacement"]["summary"] = credential
            atomic_write_json(candidate_path, candidate, private=True)

            plan = build_memory_reapproval(paths, "cand-existing", reviewer_claim="reviewer", now=NOW)

            self.assertFalse(plan.report["eligible"])
            self.assertEqual(plan.report["reason_code"], "safety_blocked_in_summary")
            self.assertEqual(plan.mutations, ())
            self.assertNotIn(credential, json.dumps(plan.report, sort_keys=True))
            self.assertFalse((paths.memory_dir / "records/mem-one.json").exists())

    def test_reapproval_rejects_credential_shaped_reviewer_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, executor = _paths(tmp), _Executor()
            _write_fixture(paths, retention="standard")
            apply_memory_retirement(
                paths,
                build_memory_retirement(paths, "mem-one", 1, now=NOW),
                transaction_executor=executor,
            )
            restore = build_memory_restore(paths, "mem-one", 1, now=NOW, candidate_id="cand-reviewer")
            apply_memory_restore(paths, restore, transaction_executor=executor)
            credential = "gh" + "u_" + "a" * 36

            plan = build_memory_reapproval(
                paths,
                "cand-reviewer",
                reviewer_claim=credential,
                now=NOW,
            )

            self.assertFalse(plan.report["eligible"])
            self.assertEqual(plan.report["reason_code"], "unsafe_reviewer_claim")
            self.assertEqual(plan.mutations, ())
            self.assertNotIn(credential, json.dumps(plan.report, sort_keys=True))

    def test_correction_targets_one_revision_and_supersedes_before_replay(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, executor = _paths(tmp), _Executor()
            original = _write_fixture(paths, retention="standard", admitted_at=NOW)
            plan = build_memory_correction(paths, "mem-one", 1, "corrected candidate", now=NOW, candidate_id="cand-correct")
            apply_memory_correction(paths, plan, transaction_executor=executor)
            history = json.loads((paths.memory_dir / "history/mem-one.r1.json").read_text())
            review = json.loads(next((paths.memory_dir / "reviews").glob("*.json")).read_text())
            result = governance.evaluate_memory_replay(history, now=NOW, review_resolver={str(review["review_id"]): review})
            self.assertEqual(history["superseded_by"]["revision"], 2)
            self.assertEqual(result["reason_code"], "superseded")
            self.assertTrue((paths.memory_dir / "candidates/cand-correct.json").exists())
            wrong = build_memory_correction(paths, "mem-one", 1, "ignored", now=NOW, candidate_id="cand-wrong")
            self.assertFalse(wrong.report["eligible"])
            self.assertEqual(original["revision"], 1)

    def test_correction_rejects_credential_shaped_summary_before_creating_a_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths, retention="standard", admitted_at=NOW)
            credential = "gh" + "u_" + "a" * 36

            plan = build_memory_correction(
                paths,
                "mem-one",
                1,
                credential,
                now=NOW,
                candidate_id="cand-unsafe",
            )

            self.assertFalse(plan.report["eligible"])
            self.assertEqual(plan.report["reason_code"], "safety_blocked_in_summary")
            self.assertEqual(plan.mutations, ())
            self.assertNotIn(credential, json.dumps(plan.report, sort_keys=True))
            self.assertTrue((paths.memory_dir / "records/mem-one.json").exists())

    def test_prune_is_scoped_and_manifest_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, executor = _paths(tmp), _Executor()
            _write_fixture(paths, "mem-one", scope="one")
            _write_fixture(paths, "mem-two", scope="two")
            plan = build_memory_prune(paths, "mem-one", 1, now=NOW)
            self.assertTrue(plan.report["eligible"])
            self.assertNotIn("mem-two", json.dumps(plan.report["manifest"]))
            atomic_write_json(paths.memory_dir / "archive/mem-one.r1.json", _record("mem-one", 1, "one", "volatile", admitted_at=NOW - timedelta(days=7))[0], private=True)
            with self.assertRaisesRegex(ValueError, "manifest_mismatch"):
                apply_memory_prune(paths, plan, transaction_executor=executor, confirm_hard_delete_local=True)
            plan = build_memory_prune(paths, "mem-one", 1, now=NOW)
            apply_memory_prune(paths, plan, transaction_executor=executor, confirm_hard_delete_local=True)
            self.assertFalse((paths.memory_dir / "records/mem-one.json").exists())
            self.assertTrue((paths.memory_dir / "tombstones/hard-deleted-mem-one-r1.json").exists())
            self.assertTrue((paths.memory_dir / "records/mem-two.json").exists())

    def test_prune_rejects_symlinks_and_path_escape(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            with self.assertRaises(ValueError):
                build_memory_prune(paths, "../escape", 1, now=NOW)
            fixture = _write_fixture(paths)
            atomic_write_json(paths.memory_dir / "blocks/provider.json", {"source_class": "provider", "source_record_identity": governance.stable_artifact_identity(fixture)}, private=True)
            provider_plan = build_memory_prune(paths, "mem-one", 1, now=NOW)
            self.assertEqual(provider_plan.report["reason_code"], "external_target")
            (paths.memory_dir / "blocks/provider.json").unlink()
            record = paths.memory_dir / "records/mem-one.json"
            record.unlink()
            record.symlink_to(Path(tmp) / "outside.json")
            plan = build_memory_prune(paths, "mem-one", 1, now=NOW)
            self.assertFalse(plan.report["eligible"])
            self.assertEqual(plan.report["reason_code"], "symlink_target")

    def test_interrupted_prune_resume_applies_each_mutation_once(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths)
            plan = build_memory_prune(paths, "mem-one", 1, now=NOW)
            executor = _Executor(interrupt_after=plan.mutations[0].name)
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                apply_memory_prune(paths, plan, transaction_executor=executor, confirm_hard_delete_local=True)
            result = apply_memory_prune(paths, plan, transaction_executor=executor, confirm_hard_delete_local=True, resume=True)
            self.assertEqual(result["receipt"]["state"], "completed")
            self.assertEqual(len(executor.applied[plan.operation_id]), len(plan.mutations))

    def test_receipts_are_bounded_metadata_only(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths)
            plan = build_memory_prune(paths, "mem-one", 1, now=NOW)
            with self.assertRaisesRegex(ValueError, "hard_delete_confirmation_required"):
                apply_memory_prune(paths, plan, transaction_executor=_Executor(), confirm_hard_delete_local=False)
            receipt = make_lifecycle_receipt(plan, [{"target_id": "record:mem-one:r1", "artifact_kind": "record", "outcome": "removed", "reason_code": "applied"}])
            self.assertEqual(validate_lifecycle_receipt(receipt), [])
            self.assertTrue(validate_lifecycle_receipt({**receipt, "summary": "private", "absolute_path": "/tmp/x", "content_hash": "x"}))

    def test_fix_1_restore_rejects_hard_delete_tombstone(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths, retention="standard")
            apply_memory_retirement(paths, build_memory_retirement(paths, "mem-one", 1, now=NOW), transaction_executor=_Executor())
            atomic_write_json(paths.memory_dir / "tombstones/hard-deleted-mem-one-r1.json", {"reason_code": "hard_deleted_local"}, private=True)
            restore = build_memory_restore(paths, "mem-one", 1, now=NOW, candidate_id="cand-restore")
            self.assertFalse(restore.report["eligible"])
            self.assertEqual(restore.report["reason_code"], "tombstoned_identity")
            self.assertTrue((paths.memory_dir / "archive/mem-one.r1.json").exists())

    def test_fix_2_prune_preserves_unlinked_journal_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            record = _write_fixture(paths, retention="volatile", admitted_at=NOW - timedelta(days=7))
            identity = governance.stable_artifact_identity(record)
            journal = json.dumps({"record_identity": identity}) + "\n" + json.dumps({"record_identity": {"id": "other"}}) + "\n"
            (paths.memory_dir / "write_journal.jsonl").parent.mkdir(parents=True, exist_ok=True)
            (paths.memory_dir / "write_journal.jsonl").write_text(journal)
            apply_memory_prune(paths, build_memory_prune(paths, "mem-one", 1, now=NOW), transaction_executor=_Executor(), confirm_hard_delete_local=True)
            if (paths.memory_dir / "write_journal.jsonl").exists():
                remaining = [json.loads(line) for line in (paths.memory_dir / "write_journal.jsonl").read_text().splitlines() if line.strip()]
                self.assertEqual(len(remaining), 1)
                self.assertEqual(remaining[0]["record_identity"]["id"], "other")

    def test_fix_3_prune_removes_index_dangling_references(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths, retention="volatile", admitted_at=NOW - timedelta(days=7))
            index = {"records": {"mem-one": {}, "mem-two": {}}, "projects": {"p": {"items": ["records/mem-one", "records/mem-two"]}}}
            atomic_write_json(paths.memory_dir / "index.json", index, private=True)
            apply_memory_prune(paths, build_memory_prune(paths, "mem-one", 1, now=NOW), transaction_executor=_Executor(), confirm_hard_delete_local=True)
            if (paths.memory_dir / "index.json").exists():
                result = json.loads((paths.memory_dir / "index.json").read_text())
                self.assertNotIn("mem-one", result.get("records", {}))
                self.assertIn("mem-two", result.get("records", {}))
                self.assertNotIn("records/mem-one", result.get("projects", {}).get("p", {}).get("items", []))

    def test_fix_4_prune_recursively_cleans_composite_index_shapes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths, retention="volatile", admitted_at=NOW - timedelta(days=7))
            index = {
                "record_files": [
                    {"path": "records/mem-one.json"},
                    {"path": "records/mem-two.json", "metadata": {"owner": "keep"}},
                    ["records/mem-one.json", {"record_id": "mem-one"}, "records/mem-two.json"],
                    {
                        "mixed": {"paths": ["records/mem-one.json", "records/mem-two.json"], "state": "keep"},
                        "unrelated": {"nested": [{"value": "keep"}]},
                    },
                ],
                "records": {"mem-one": {"path": "records/mem-one.json"}, "mem-two": {"nested": ["keep"]}},
            }
            atomic_write_json(paths.memory_dir / "index.json", index, private=True)

            plan = build_memory_prune(paths, "mem-one", 1, now=NOW)
            apply_memory_prune(paths, plan, transaction_executor=_Executor(), confirm_hard_delete_local=True)

            result = json.loads((paths.memory_dir / "index.json").read_text())
            self.assertEqual(result["record_files"][0]["path"], "records/mem-two.json")
            self.assertEqual(result["record_files"][1], ["records/mem-two.json"])
            self.assertEqual(result["record_files"][2]["mixed"]["paths"], ["records/mem-two.json"])
            self.assertEqual(result["record_files"][2]["mixed"]["state"], "keep")
            self.assertEqual(result["record_files"][2]["unrelated"], {"nested": [{"value": "keep"}]})
            self.assertNotIn("mem-one", result["records"])
            self.assertEqual(result["records"]["mem-two"], {"nested": ["keep"]})

    def test_store_executor_applies_restore_correction_and_prune_with_exact_receipts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths, "restore", retention="standard")
            retirement = build_memory_retirement(paths, "restore", 1, now=NOW)
            apply_memory_retirement(paths, retirement, transaction_executor=execute_memory_lifecycle)
            archive_path = paths.memory_dir / "archive/restore.r1.json"
            archive_before = archive_path.read_text()
            restore = build_memory_restore(paths, "restore", 1, now=NOW)
            restored = apply_memory_restore(paths, restore, transaction_executor=execute_memory_lifecycle)
            self.assertTrue(restored["applied"])
            self.assertEqual(validate_lifecycle_receipt(restored["receipt"]), [])
            self.assertEqual(archive_path.read_text(), archive_before)
            candidate_path = paths.memory_dir / restore.mutations[0].target
            self.assertEqual(json.loads(candidate_path.read_text())["admission"]["state"], "pending_review")

            _write_fixture(paths, "correct", retention="standard")
            correction = build_memory_correction(paths, "correct", 1, "replacement", now=NOW)
            corrected = apply_memory_correction(paths, correction, transaction_executor=execute_memory_lifecycle)
            self.assertTrue(corrected["applied"])
            self.assertTrue((paths.memory_dir / "history/correct.r1.json").exists())
            self.assertFalse((paths.memory_dir / "records/correct.json").exists())
            self.assertEqual(json.loads(paths.memory_dir.joinpath(correction.mutations[-1].target).read_text())["admission"]["state"], "pending_review")

            _write_fixture(paths, "prune", retention="volatile", admitted_at=NOW - timedelta(days=7))
            journal_path = paths.memory_dir / "write_journal.jsonl"
            journal_path.write_text(json.dumps({"record_identity": {"id": "unlinked", "revision": 1}}) + "\n", encoding="utf-8")
            atomic_write_json(paths.memory_dir / "blocks/provider.json", {"source_class": "provider", "record_identity": {"id": "unlinked", "revision": 1}}, private=True)
            atomic_write_json(paths.memory_dir / "blocks/native.json", {"source_class": "hermes_native", "record_identity": {"id": "unlinked", "revision": 1}}, private=True)
            prune = build_memory_prune(paths, "prune", 1, now=NOW)
            pruned = apply_memory_prune(paths, prune, transaction_executor=execute_memory_lifecycle, confirm_hard_delete_local=True)
            receipt = pruned["receipt"]
            self.assertTrue(pruned["applied"])
            self.assertEqual(
                set(receipt),
                {"schema_version", "operation_id", "operation_type", "record_id", "revision", "scope", "actor_class", "created_at", "completed_at", "state", "outcomes"},
            )
            self.assertEqual(validate_lifecycle_receipt(receipt), [])
            self.assertEqual(
                {outcome["target_id"] for outcome in receipt["outcomes"]},
                {mutation.target_id for mutation in prune.mutations} | {item["target_id"] for item in prune.preserved},
            )
            self.assertTrue((paths.memory_dir / "tombstones/hard-deleted-prune-r1.json").exists())
            self.assertEqual(journal_path.read_text(), json.dumps({"record_identity": {"id": "unlinked", "revision": 1}}) + "\n")
            self.assertTrue((paths.memory_dir / "blocks/provider.json").exists())
            self.assertTrue((paths.memory_dir / "blocks/native.json").exists())

    def test_store_executor_resumes_interrupted_correction_with_cumulative_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths, "resume", retention="standard")
            plan = build_memory_correction(paths, "resume", 1, "replacement", now=NOW)
            steps = lifecycle_operation_steps(plan)
            interrupted = {"value": False}

            def writer(active_paths: OmhPaths, step: dict[str, object]) -> str:
                outcome = apply_memory_operation_step(active_paths, step)
                if step["name"] == "write_superseded_history" and not interrupted["value"]:
                    interrupted["value"] = True
                    raise RuntimeError("interrupted")
                return outcome

            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                run_memory_operation(
                    paths,
                    operation_id=plan.operation_id,
                    operation_type="memory_lifecycle_correct",
                    steps=steps,
                    step_writer=writer,
                    now=NOW,
                )
            operation_path = paths.memory_operations_dir / f"{plan.operation_id}.json"
            interrupted_record = json.loads(operation_path.read_text())
            self.assertEqual(interrupted_record["state"], "interrupted")
            self.assertTrue((paths.memory_dir / "history/resume.r1.json").exists())
            self.assertTrue((paths.memory_dir / "records/resume.json").exists())

            resumed = apply_memory_correction(paths, plan, transaction_executor=execute_memory_lifecycle)
            completed_record = json.loads(operation_path.read_text())
            self.assertTrue(resumed["applied"])
            self.assertEqual(completed_record["state"], "completed")
            self.assertEqual(completed_record["recovery_count"], 1)
            self.assertEqual(
                {outcome["target_id"] for outcome in resumed["receipt"]["outcomes"]},
                {mutation.target_id for mutation in plan.mutations},
            )
            self.assertFalse((paths.memory_dir / "records/resume.json").exists())
            self.assertTrue((paths.memory_dir / plan.mutations[-1].target).exists())

    def test_collision_regression_records_key_with_survivors(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write_fixture(paths, "records", revision=1, scope="r", retention="volatile", admitted_at=NOW - timedelta(days=7))
            _write_fixture(paths, "mem-two", revision=1, scope="two", retention="standard")
            _write_fixture(paths, "mem-three", revision=1, scope="three", retention="standard")
            index = {
                "records": {
                    "records": {"scope": "r", "path": "records/records.json"},
                    "mem-two": {"scope": "two", "path": "records/mem-two.json"},
                    "mem-three": {"scope": "three", "path": "records/mem-three.json"},
                }
            }
            atomic_write_json(paths.memory_dir / "index.json", index, private=True)
            before_index = (paths.memory_dir / "index.json").read_text()
            plan = build_memory_prune(paths, "records", 1, now=NOW)
            self.assertTrue(plan.report["eligible"])
            after_build = (paths.memory_dir / "index.json").read_text()
            self.assertEqual(before_index, after_build, "Build phase must not mutate index")
            apply_memory_prune(paths, plan, transaction_executor=_Executor(), confirm_hard_delete_local=True)
            result = json.loads((paths.memory_dir / "index.json").read_text())
            self.assertIn("records", result, "Top-level 'records' table must survive")
            record_entries = result.get("records", {})
            self.assertIn("mem-two", record_entries, "Unrelated mem-two must survive in index")
            self.assertIn("mem-three", record_entries, "Unrelated mem-three must survive in index")
            self.assertTrue((paths.memory_dir / "records/mem-two.json").exists(), "mem-two file must exist")
            self.assertTrue((paths.memory_dir / "records/mem-three.json").exists(), "mem-three file must exist")
            self.assertFalse((paths.memory_dir / "records/records.json").exists(), "records file must be pruned")


if __name__ == "__main__":
    unittest.main()
