"""Report-first project identity migration preserves reviewed source revisions."""
from __future__ import annotations

import json
import os
from unittest.mock import patch
from pathlib import Path
from typing import Any
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package
from test_project_identity import repository
from project_identity_fixture import pin_review_first

load_local_package()


class ProjectIdentityMigrationTests(unittest.TestCase):
    _root: Path | None = None
    _original: bytes | None = None

    @property
    def api(self):
        from omh.workflows import memory_project_identity
        return memory_project_identity

    @property
    def memory(self):
        from omh.workflows import memory
        return memory

    @property
    def root(self) -> Path:
        assert self._root is not None
        return self._root

    @property
    def paths(self):
        from omh.paths import resolve_paths
        return resolve_paths(self.root / ".omh", self.root.parent / "hermes")

    @property
    def original(self) -> bytes:
        assert self._original is not None
        return self._original

    @property
    def record(self) -> dict[str, Any]:
        record = json.loads(self.original)
        assert isinstance(record, dict)
        return record

    @property
    def record_path(self) -> Path:
        return self.paths.memory_dir / "records" / f'{self.record["record_id"]}.json'

    def setUp(self):
        temporary = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(temporary / "user")}))
        self._root = repository(temporary / "repo")
        # Both stores approve by hand below, so neither may default to auto-safe.
        from omh.paths import resolve_paths
        pin_review_first(self.paths)
        pin_review_first(resolve_paths(temporary / "user", self.paths.hermes_home))
        candidate = self.memory.capture_project_memory_candidate(self.paths, "legacy sentinel fact", scope_ref="repo", retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        record = self.memory.approve_project_memory_candidate(self.paths, candidate["candidate_id"])["record"]
        assert isinstance(record, dict)
        self._original = (self.paths.memory_dir / "records" / f'{record["record_id"]}.json').read_bytes()

    def report(self):
        return self.api.build_project_identity_migration_report(self.paths, root=self.root)

    def migrate(self, digest):
        return self.api.migrate_project_identity(self.paths, approve=digest, root=self.root)

    def test_report_is_read_only_and_digest_bound(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = self.report()
        self.assertEqual(report["schema_version"], "project_identity_migration_report/v1")
        self.assertEqual(len(report["entries"]), 1)
        self.assertEqual(report["entries"][0]["current_ref"], "repo")
        self.assertEqual(report["entries"][0]["store"], "project")
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertEqual(before, {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        with self.assertRaisesRegex(ValueError, "approval_digest_mismatch"):
            self.migrate("0" * 64)
        self.assertEqual(self.record_path.read_bytes(), self.original)
        candidate = self.memory.capture_project_memory_candidate(self.paths, "new legacy fact", scope_ref="repo")["candidate"]
        assert isinstance(candidate, dict)
        self.memory.approve_project_memory_candidate(self.paths, candidate["candidate_id"])
        with self.assertRaisesRegex(ValueError, "approval_digest_mismatch"):
            self.migrate(report["report_digest"])

    def test_approved_source_change_is_skipped_after_report(self):
        self._assert_approved_source_change_is_skipped("report")

    def test_approved_source_change_is_skipped_at_locked_preflight(self):
        self._assert_approved_source_change_is_skipped("preflight")

    def _assert_approved_source_change_is_skipped(self, seam: str):
        from datetime import datetime, timezone
        from omh.workflows._memory_lifecycle_plans import _approved_record, _review
        from omh.system.local_store import atomic_write_json
        from omh.workflows import memory_project_identity as migration
        approved = self.report()
        original_report = migration.build_project_identity_migration_report
        original_execute = migration.execute_memory_lifecycle
        current = json.loads(self.record_path.read_bytes())
        changed = _approved_record({**current, "summary": f"separately reviewed {seam}"}, current["record_id"], current["revision"] + 1, "independent-reviewer", datetime.now(timezone.utc))
        admission = changed["admission"]
        assert isinstance(admission, dict)
        review_id = admission["review_id"]
        review = _review(changed, review_id, "independent-reviewer")

        def replace_source():
            atomic_write_json(self.paths.memory_dir / "reviews" / f"{review_id}.json", review, private=True)
            atomic_write_json(self.record_path, changed, private=True)

        def race_report(*args, **kwargs):
            report = original_report(*args, **kwargs)
            replace_source()
            return report

        def race_execute(*args, **kwargs):
            replace_source()
            return original_execute(*args, **kwargs)

        target = "build_project_identity_migration_report" if seam == "report" else "execute_memory_lifecycle"
        with patch.object(migration, target, side_effect=race_report if seam == "report" else race_execute):
            receipt = self.migrate(approved["report_digest"])
        self.assertEqual(json.loads(self.record_path.read_bytes()), changed)
        self.assertEqual(receipt["successors"], [])
        self.assertEqual(receipt["skipped"], [{"record_id": current["record_id"], "store": "project", "reason_code": "source_changed_since_report"}])
        self.assertFalse((self.paths.memory_dir / "history" / f'{current["record_id"]}.r{current["revision"]}.json').exists())
        self.assertNotEqual(self.report()["report_digest"], approved["report_digest"])

    def test_approved_review_change_is_not_rebound_to_fresh_review(self):
        from omh.workflows import memory_project_identity as migration
        from omh.system.local_store import atomic_write_json
        approved = self.report()
        original_report = migration.build_project_identity_migration_report
        record = self.record
        review_path = self.paths.memory_dir / "reviews" / f'{record["admission"]["review_id"]}.json'
        original_review = json.loads(review_path.read_bytes())

        def race_report(*args, **kwargs):
            report = original_report(*args, **kwargs)
            atomic_write_json(review_path, {**original_review, "reviewer_claim": "different-reviewer"}, private=True)
            return report

        with patch.object(migration, "build_project_identity_migration_report", side_effect=race_report):
            receipt = self.migrate(approved["report_digest"])
        self.assertEqual(self.record_path.read_bytes(), self.original)
        self.assertEqual(receipt["successors"], [])
        self.assertEqual(receipt["skipped"][0]["reason_code"], "source_changed_since_report")

    def test_successor_original_preservation_idempotency_and_rollback(self):
        report = self.report()
        receipt = self.migrate(report["report_digest"])
        self.assertEqual(receipt["schema_version"], "project_identity_migration_receipt/v1")
        self.assertEqual(len(receipt["successors"]), 1)
        current = json.loads(self.record_path.read_text(encoding="utf-8"))
        self.assertEqual(current["revision"], self.record["revision"] + 1)
        self.assertEqual(current["scope"]["ref"], report["resolution"]["identity"])
        history = self.paths.memory_dir / "history" / f'{self.record["record_id"]}.r{self.record["revision"]}.json'
        self.assertEqual(history.read_bytes(), self.original)
        self.assertEqual(self.report()["entries"], [])
        self.assertEqual(self.migrate(report["report_digest"])["successors"], [])
        self.api.rollback_project_identity_migration(self.paths, receipt["receipt_id"], root=self.root)
        self.assertEqual(self.record_path.read_bytes(), self.original)
        pack = self.memory.build_project_memory_recall_pack(self.paths, scope_kind="project", scope_ref="repo")
        included = pack["included_records"]
        assert isinstance(included, list)
        self.assertEqual([r["record_id"] for r in included], [self.record["record_id"]])
        self.assertTrue(list((self.paths.memory_dir / "archive").glob("*.json")))

    def test_report_and_migration_cover_both_stores(self):
        from omh.paths import resolve_paths
        user = resolve_paths(self.root.parent / "user", self.paths.hermes_home)
        candidate = self.memory.capture_project_memory_candidate(user, "user store legacy", scope_ref="old-project", retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        self.memory.approve_project_memory_candidate(user, candidate["candidate_id"])
        report = self.report()
        self.assertEqual({row["store"] for row in report["entries"]}, {"project", "user"})
        receipt = self.migrate(report["report_digest"])
        self.assertEqual(len(receipt["successors"]), 2)
        self.api.rollback_project_identity_migration(self.paths, receipt["receipt_id"], root=self.root)
        self.assertEqual(len(self.report()["entries"]), 2)

    def test_interrupted_migration_is_not_recalled_and_resumes(self):
        from omh.workflows import memory_store
        from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
        original_step = memory_store.apply_memory_operation_step
        report = self.report()

        def interrupt(paths, step):
            result = original_step(paths, step)
            if step["name"] == "write_successor":
                raise RuntimeError("injected_after_successor_write")
            return result

        with patch.object(memory_store, "apply_memory_operation_step", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "injected_after_successor_write"):
                self.migrate(report["report_digest"])
        provider = OmhMemoryProvider(self.paths.omh_home)
        provider.initialize("s", platform="cli", cwd=self.root)
        self.assertNotIn(self.record["record_id"], provider.prefetch("sentinel fact"))
        self.migrate(report["report_digest"])
        provider.initialize("s", platform="cli", cwd=self.root)
        self.assertIn(self.record["record_id"], provider.prefetch("sentinel fact"))

    def test_interrupted_rollback_resumes_without_rewriting_original(self):
        from omh.workflows import memory_store
        receipt = self.migrate(self.report()["report_digest"])
        original_step = memory_store.apply_memory_operation_step

        def interrupt(paths, step):
            result = original_step(paths, step)
            if step["name"] == "retire_successor":
                raise RuntimeError("injected_after_retirement")
            return result

        with patch.object(memory_store, "apply_memory_operation_step", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "injected_after_retirement"):
                self.api.rollback_project_identity_migration(self.paths, receipt["receipt_id"], root=self.root)
        self.api.rollback_project_identity_migration(self.paths, receipt["receipt_id"], root=self.root)
        self.assertEqual(self.record_path.read_bytes(), self.original)

    def test_automatic_recall_never_mixes_stable_and_legacy(self):
        from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
        candidate = self.memory.capture_project_memory_candidate(self.paths, "stable sentinel fact", retention_class="durable")["candidate"]
        assert isinstance(candidate, dict)
        stable = self.memory.approve_project_memory_candidate(self.paths, candidate["candidate_id"])["record"]
        assert isinstance(stable, dict)
        live = OmhMemoryProvider(self.paths.omh_home)
        live.initialize("s", platform="cli", cwd=self.root)
        text = live.prefetch("sentinel fact")
        self.assertIn(stable["record_id"], text)
        self.assertNotIn(self.record["record_id"], text)
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        refs = [s["ref"] for s in receipt["lens"]["scope_allowlist"] if s["kind"] == "project"]
        self.assertEqual(refs, [self.report()["resolution"]["identity"]])


if __name__ == "__main__":
    unittest.main()
