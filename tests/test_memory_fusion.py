from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.local_store import FileLockTimeout
from omh.plugin_bundle.omh import memory_governance
from omh.workflows import memory as memory_workflow
from omh.workflows.memory_lifecycle import (
    apply_memory_correction,
    apply_memory_reapproval,
    build_memory_correction,
    build_memory_reapproval,
)
from omh.workflows.memory_lifecycle_executor import execute_memory_lifecycle
from omh.memory import (
    apply_memory_retirement,
    approve_project_memory_candidate,
    build_memory_lineage,
    build_memory_retirement,
    build_project_memory_recall_pack,
    capture_project_memory_candidate,
    memory_recall_pack_for_handoff,
    read_recall_usage,
    record_attached_recall_usage,
    record_recall_usage,
    validate_project_memory_recall_pack,
)
from omh.paths import resolve_paths


def _approve_capture(paths, summary, **kwargs):
    captured = capture_project_memory_candidate(paths, summary, **kwargs)
    candidate_id = captured["candidate"]["candidate_id"]
    approved = approve_project_memory_candidate(paths, candidate_id)
    return approved["record"]


def _rewrite_record(paths, record_id, **fields):
    """Rewrite record fields and re-sign the payload digest plus its review."""
    record_path = paths.memory_dir / "records" / f"{record_id}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(fields)
    digest = memory_governance.canonical_payload_digest(record)
    record["admission"]["payload_digest"] = digest
    review_path = paths.memory_dir / "reviews" / f"{record['admission']['review_id']}.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["payload_digest"] = digest
    review_path.write_text(json.dumps(review), encoding="utf-8")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    return record


class RecallRankingFusionTests(unittest.TestCase):
    def test_ranking_block_reports_signal_ranks_and_integer_micro_score(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve_capture(paths, "Deploy uses the staging cluster first", tags=["deploy"])

            pack = build_project_memory_recall_pack(paths, "deploy cluster")

            self.assertEqual(validate_project_memory_recall_pack(pack), [])
            [item] = pack["included_records"]
            ranking = item["ranking"]
            self.assertIsInstance(ranking["rrf_score_micro"], int)
            self.assertEqual(ranking["relevance_rank"], 1)
            self.assertEqual(ranking["recency_rank"], 1)
            self.assertEqual(ranking["usage_rank"], 1)
            self.assertEqual(ranking["times_recalled"], 0)

    def test_keyword_relevance_outranks_one_step_of_recency(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            strong = _approve_capture(paths, "Release checklist runs unittest discovery", tags=["release", "tests"])
            weak = _approve_capture(paths, "Release notes live in the wiki")
            _rewrite_record(paths, strong["record_id"], approved_at="2026-07-01T00:00:00Z")
            _rewrite_record(paths, weak["record_id"], approved_at="2026-07-20T00:00:00Z")

            pack = build_project_memory_recall_pack(paths, "release unittest tests")

            ids = [item["record_id"] for item in pack["included_records"]]
            self.assertEqual(ids[0], strong["record_id"], pack["included_records"])
            self.assertEqual(pack["included_records"][0]["ranking"]["relevance_rank"], 1)
            self.assertEqual(pack["included_records"][0]["ranking"]["recency_rank"], 2)

    def test_recency_breaks_relevance_ties_without_a_query(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            older = _approve_capture(paths, "Older architecture decision")
            newer = _approve_capture(paths, "Newer architecture decision")
            _rewrite_record(paths, older["record_id"], approved_at="2026-06-01T00:00:00Z")
            _rewrite_record(paths, newer["record_id"], approved_at="2026-07-15T00:00:00Z")

            pack = build_project_memory_recall_pack(paths, "")

            ids = [item["record_id"] for item in pack["included_records"]]
            self.assertEqual(ids[0], newer["record_id"])

    def test_top_relevance_record_survives_the_budget_cut(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            strong = _approve_capture(paths, "Release gate runs unittest discovery and ruff", tags=["release", "tests", "ruff"])
            weak_ids = []
            for index in range(3):
                weak = _approve_capture(paths, f"Release note variant {index}")
                weak_ids.append(weak["record_id"])
                record_recall_usage(paths, [weak["record_id"]])
            _rewrite_record(paths, strong["record_id"], approved_at="2026-01-01T00:00:00Z")
            for weak_id in weak_ids:
                _rewrite_record(paths, weak_id, approved_at="2026-07-20T00:00:00Z")

            pack = build_project_memory_recall_pack(paths, "release unittest ruff tests", limit=2)

            included_ids = [item["record_id"] for item in pack["included_records"]]
            self.assertEqual(included_ids[0], strong["record_id"], "newer, used weak matches must not budget-cut the best match")
            self.assertTrue(pack["truncated"])

    def test_delivery_usage_breaks_ties_when_recency_is_equal(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            used = _approve_capture(paths, "Used decision about builds")
            unused = _approve_capture(paths, "Unused decision about builds")
            same_moment = "2026-07-10T00:00:00Z"
            _rewrite_record(paths, used["record_id"], approved_at=same_moment)
            _rewrite_record(paths, unused["record_id"], approved_at=same_moment)
            record_recall_usage(paths, [used["record_id"]])

            pack = build_project_memory_recall_pack(paths, "")

            ids = [item["record_id"] for item in pack["included_records"]]
            self.assertEqual(ids[0], used["record_id"])
            self.assertEqual(pack["included_records"][0]["ranking"]["times_recalled"], 1)


class RecallUsageBookkeepingTests(unittest.TestCase):
    def test_only_attached_handoff_packs_count_usage(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approve_capture(paths, "Codegraph rebuild needs the docs byte gates", tags=["docs"])

            build_project_memory_recall_pack(paths, "docs gates")
            self.assertEqual(read_recall_usage(paths), {})

            pack = memory_recall_pack_for_handoff(paths, "docs gates")
            self.assertIsNotNone(pack)
            self.assertEqual(read_recall_usage(paths), {}, "building a handoff pack is speculative, not delivery")

            record_attached_recall_usage(paths, {"delegation": {}, "executor_selection": {}})
            self.assertEqual(read_recall_usage(paths), {}, "a payload without an attached pack counts nothing")

            record_attached_recall_usage(paths, {"prompt_handoff": {"memory_recall_pack": pack}})
            usage = read_recall_usage(paths)
            self.assertEqual(usage[record["record_id"]]["times_recalled"], 1)

            record_attached_recall_usage(paths, {"executor_handoff": {"memory_recall_pack": pack}})
            usage = read_recall_usage(paths)
            self.assertEqual(usage[record["record_id"]]["times_recalled"], 2)
            self.assertTrue(usage[record["record_id"]]["last_recalled_at"])

    def test_usage_trim_never_evicts_a_just_delivered_record(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve_capture(paths, "Seed record so the store exists")
            same_second = "2026-07-30T00:00:00Z"
            with patch.object(memory_workflow, "_RECALL_USAGE_MAX_ENTRIES", 3):
                record_recall_usage(paths, ["mem_zzz1", "mem_zzz2", "mem_zzz3"], now=same_second)
                result = record_recall_usage(paths, ["mem_aaa0"], now=same_second)

            usage = read_recall_usage(paths)
            self.assertEqual(result["records"]["mem_aaa0"]["times_recalled"], 1)
            self.assertIn("mem_aaa0", usage, "the entry this call added must survive its own trim")
            self.assertLessEqual(len(usage), 3)

    def test_corrupt_usage_store_reads_as_empty_and_never_blocks_recall(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve_capture(paths, "Recall must survive a corrupt usage file")
            (paths.memory_dir / "usage.json").write_text("{not json", encoding="utf-8")

            pack = build_project_memory_recall_pack(paths, "")

            self.assertEqual(read_recall_usage(paths), {})
            self.assertEqual(pack["record_count"], 1)

    def test_retirement_report_annotates_delivery_usage(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approve_capture(paths, "Volatile note", retention_class="volatile", ttl_days=1)
            record_recall_usage(paths, [record["record_id"]])

            report = build_memory_retirement(paths, now=datetime.now(timezone.utc) + timedelta(days=8))

            [row] = report["expired"]
            self.assertEqual(row["record_id"], record["record_id"])
            self.assertEqual(row["recall_usage"]["times_recalled"], 1)


class DerivedFromLineageTests(unittest.TestCase):
    def test_capture_rejects_unknown_and_excess_derived_from_refs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            base = _approve_capture(paths, "Base fact")

            with self.assertRaisesRegex(ValueError, "not found"):
                capture_project_memory_candidate(paths, "Derived", derived_from=["mem_0000000000000000"])
            too_many = [base["record_id"]] + [f"mem_{index:016x}" for index in range(8)]
            with self.assertRaisesRegex(ValueError, "at most 8"):
                capture_project_memory_candidate(paths, "Derived", derived_from=too_many)

    def test_lineage_walks_ancestors_descendants_and_flags_depth_truncation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            root = _approve_capture(paths, "Observed deploy failure")
            middle = _approve_capture(paths, "Deploy failure was the stale cache", derived_from=[root["record_id"]])
            leaf = _approve_capture(paths, "Always purge cache before deploy", derived_from=[middle["record_id"]])

            lineage = build_memory_lineage(paths, middle["record_id"])
            self.assertTrue(lineage["found"])
            self.assertEqual([card["record_id"] for card in lineage["ancestors"]], [root["record_id"]])
            self.assertEqual([card["record_id"] for card in lineage["descendants"]], [leaf["record_id"]])
            self.assertFalse(lineage["truncated"])

            shallow = build_memory_lineage(paths, leaf["record_id"], depth=1)
            self.assertEqual([card["record_id"] for card in shallow["ancestors"]], [middle["record_id"]])
            self.assertTrue(shallow["truncated"])

    def test_lineage_reports_retired_parents_as_unresolved(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            parent = _approve_capture(paths, "Volatile parent", retention_class="volatile", ttl_days=1)
            child = _approve_capture(paths, "Durable child lesson", derived_from=[parent["record_id"]])
            apply_memory_retirement(paths, now=datetime.now(timezone.utc) + timedelta(days=8))

            lineage = build_memory_lineage(paths, child["record_id"])

            self.assertEqual(lineage["ancestors"], [])
            self.assertEqual(
                lineage["unresolved_refs"],
                [{"record_id": parent["record_id"], "referenced_by": child["record_id"]}],
            )

    def test_lineage_is_cycle_safe_and_missing_record_reports_not_found(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            first = _approve_capture(paths, "First of a pair")
            second = _approve_capture(paths, "Second of a pair", derived_from=[first["record_id"]])
            _rewrite_record(paths, first["record_id"], derived_from=[second["record_id"]])

            lineage = build_memory_lineage(paths, first["record_id"], depth=10)
            self.assertEqual([card["record_id"] for card in lineage["ancestors"]], [second["record_id"]])

            missing = build_memory_lineage(paths, "mem_00000000000000ff")
            self.assertFalse(missing["found"])
            self.assertEqual(missing["counts"], {"ancestors": 0, "descendants": 0, "unresolved": 0})

    def test_derived_from_survives_a_correction_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            base = _approve_capture(paths, "Base observation")
            child = _approve_capture(paths, "Conclusion built on the base", derived_from=[base["record_id"]])

            plan = build_memory_correction(
                paths,
                child["record_id"],
                1,
                "Corrected conclusion built on the base",
                now=datetime.now(timezone.utc),
                candidate_id="cand-correct-lineage",
            )
            apply_memory_correction(paths, plan, transaction_executor=execute_memory_lifecycle)

            candidate = json.loads((paths.memory_dir / "candidates" / "cand-correct-lineage.json").read_text(encoding="utf-8"))
            self.assertEqual(candidate["replacement"]["derived_from"], [base["record_id"]])

            reapproval = build_memory_reapproval(
                paths, "cand-correct-lineage", reviewer_claim="operator", now=datetime.now(timezone.utc)
            )
            apply_memory_reapproval(paths, reapproval, transaction_executor=execute_memory_lifecycle)
            live = json.loads((paths.memory_dir / "records" / f"{child['record_id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(live["revision"], 2)
            self.assertEqual(live["derived_from"], [base["record_id"]], "the reapproved live record must keep provenance")

    def test_attached_usage_swallows_store_failures(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve_capture(paths, "Fact whose delivery bookkeeping fails")
            pack = memory_recall_pack_for_handoff(paths, "")
            self.assertIsNotNone(pack)

            for failure in (FileLockTimeout("lock held"), OSError(30, "read-only file system")):
                with patch.object(memory_workflow, "record_recall_usage", side_effect=failure):
                    result = record_attached_recall_usage(paths, {"prompt_handoff": {"memory_recall_pack": pack}})
                self.assertEqual(result["recorded"], 0, failure)
            self.assertEqual(read_recall_usage(paths), {})

    def test_handoff_recall_pack_contains_bounded_retrieval_observation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve_capture(paths, "Memory retrieval uses bounded context budgets", tags=["memory", "retrieval"])

            pack = memory_recall_pack_for_handoff(paths, "memory retrieval", executor_target="codex", limit=1)

            self.assertIsNotNone(pack)
            observation = pack["retrieval_observation"]
            self.assertEqual(observation["schema_version"], "memory_retrieval_observation/v1")
            self.assertEqual(observation["rounds"], 1)
            self.assertEqual(observation["requested_limit"], 1)
            self.assertEqual(observation["selected_records"], 1)
            self.assertGreaterEqual(observation["latency_ms"], 0)
            self.assertGreater(observation["selected_token_estimate"], 0)

    def test_capture_distinguishes_unreadable_from_missing_derived_from(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve_capture(paths, "Seed record so the store exists")
            (paths.memory_dir / "records" / "mem_00000000000000cc.json").write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unreadable"):
                capture_project_memory_candidate(paths, "Derived", derived_from=["mem_00000000000000cc"])

    def test_recall_items_expose_derived_from_and_stay_schema_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            base = _approve_capture(paths, "Base decision about routing")
            derived = _approve_capture(paths, "Derived routing lesson", derived_from=[base["record_id"]])

            pack = build_project_memory_recall_pack(paths, "routing")

            self.assertEqual(validate_project_memory_recall_pack(pack), [])
            by_id = {item["record_id"]: item for item in pack["included_records"]}
            self.assertEqual(by_id[derived["record_id"]]["derived_from"], [base["record_id"]])
            self.assertEqual(by_id[base["record_id"]]["derived_from"], [])


if __name__ == "__main__":
    unittest.main()
