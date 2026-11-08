from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import memory_admission, memory_governance
from omh.memory import (
    approve_project_memory_candidate,
    build_memory_retirement,
    build_project_memory_recall_pack,
    build_project_memory_review,
    capture_project_memory_candidate,
    read_memory_pins,
    reject_project_memory_candidate,
    set_memory_pin,
    validate_project_memory_recall_pack,
)
from project_identity_fixture import memory_paths as resolve_paths
from omh.profiles.setup import write_setup_profile
from omh.runtime.records import _compact_memory_recall_pack


def _approve_capture(paths, summary, **kwargs):
    captured = capture_project_memory_candidate(paths, summary, **kwargs)
    return approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]


def _rewrite_record(paths, record_id, **fields):
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


class MemoryPinTests(unittest.TestCase):
    def test_pin_requires_existing_record_and_unpin_cleans_stale_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approve_capture(paths, "anchor fact")

            with self.assertRaisesRegex(ValueError, "not found"):
                set_memory_pin(paths, "mem_00000000000000ee", pinned=True)

            report = set_memory_pin(paths, record["record_id"], pinned=True)
            self.assertEqual(report["pinned_record_ids"], [record["record_id"]])
            self.assertEqual(read_memory_pins(paths), [record["record_id"]])

            set_memory_pin(paths, record["record_id"], pinned=False)
            self.assertEqual(read_memory_pins(paths), [])
            # Unpinning an id that was never pinned is a no-op, not an error.
            set_memory_pin(paths, "mem_00000000000000ee", pinned=False)

    def test_pinned_record_leads_the_pack_and_skips_only_the_overlap_cut(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            anchor = _approve_capture(paths, "Always run the byte gates before commit")
            match = _approve_capture(paths, "Deploy checklist for staging", tags=["deploy"])
            set_memory_pin(paths, anchor["record_id"], pinned=True)

            pack = build_project_memory_recall_pack(paths, "deploy staging")

            ids = [item["record_id"] for item in pack["included_records"]]
            self.assertEqual(ids[0], anchor["record_id"], "the pinned anchor leads despite zero query overlap")
            self.assertIn(match["record_id"], ids)
            self.assertTrue(pack["included_records"][0]["ranking"]["pinned"])
            self.assertFalse(pack["included_records"][1]["ranking"]["pinned"])
            self.assertEqual(validate_project_memory_recall_pack(pack), [])

    def test_pin_never_overrides_expiry_eligibility(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            volatile = _approve_capture(paths, "volatile anchor", retention_class="volatile", ttl_days=1)
            set_memory_pin(paths, volatile["record_id"], pinned=True)

            future = datetime.now(timezone.utc) + timedelta(days=8)
            pack = build_project_memory_recall_pack(paths, "", now=future)

            self.assertEqual(pack["included_records"], [])
            self.assertIn(volatile["record_id"], {entry["record_id"] for entry in pack["excluded_records"]})

            report = build_memory_retirement(paths, now=future)
            [row] = report["expired"]
            self.assertTrue(row["pinned"], "retirement annotates the pin instead of blocking on it")

    def test_pin_cap_is_enforced(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            records = [_approve_capture(paths, f"anchor {index}") for index in range(13)]
            for record in records[:12]:
                set_memory_pin(paths, record["record_id"], pinned=True)
            with self.assertRaisesRegex(ValueError, "at most 12"):
                set_memory_pin(paths, records[12]["record_id"], pinned=True)

    def test_pins_reserve_a_slot_for_query_driven_recall(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for index in range(6):
                pinned = _approve_capture(paths, f"unrelated anchor number {index}")
                set_memory_pin(paths, pinned["record_id"], pinned=True)
            match = _approve_capture(paths, "Deploy checklist for staging", tags=["deploy"])

            pack = build_project_memory_recall_pack(paths, "deploy staging", limit=5)

            ids = [item["record_id"] for item in pack["included_records"]]
            self.assertIn(match["record_id"], ids, "a full pin budget must not blank query-driven recall")
            self.assertEqual(len(ids), 5)
            self.assertTrue(all(item["ranking"]["pinned"] for item in pack["included_records"][:4]))

    def test_pinned_record_respects_the_perspective_lens(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            scoped = _approve_capture(paths, "codex-only anchor", observed="codex")
            set_memory_pin(paths, scoped["record_id"], pinned=True)

            pack = build_project_memory_recall_pack(paths, "", observed="claude-code")

            self.assertEqual(pack["included_records"], [], "a pin never overrides the perspective lens")

    def test_corrupt_pins_store_reads_as_empty_and_heals_on_next_pin(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approve_capture(paths, "healing anchor")
            (paths.memory_dir / "pins.json").write_text("{broken", encoding="utf-8")

            self.assertEqual(read_memory_pins(paths), [])
            pack = build_project_memory_recall_pack(paths, "")
            self.assertEqual(pack["record_count"], 1)

            set_memory_pin(paths, record["record_id"], pinned=True)
            self.assertEqual(read_memory_pins(paths), [record["record_id"]])


class AgeTierTests(unittest.TestCase):
    def test_age_tier_degrades_old_records_within_equal_relevance(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            young = _approve_capture(paths, "young architecture note")
            old = _approve_capture(paths, "old architecture note")
            now = datetime.now(timezone.utc)
            young_at = (now - timedelta(days=5)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            old_at = (now - timedelta(days=400)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            _rewrite_record(paths, young["record_id"], approved_at=young_at)
            _rewrite_record(paths, old["record_id"], approved_at=old_at)

            pack = build_project_memory_recall_pack(paths, "", now=now)

            by_id = {item["record_id"]: item for item in pack["included_records"]}
            self.assertEqual(by_id[young["record_id"]]["ranking"]["age_tier"], 0)
            self.assertEqual(by_id[old["record_id"]]["ranking"]["age_tier"], 2)
            self.assertEqual([item["record_id"] for item in pack["included_records"]][0], young["record_id"])
            self.assertLess(
                by_id[old["record_id"]]["ranking"]["decayed_score_micro"],
                by_id[young["record_id"]]["ranking"]["decayed_score_micro"] / 2,
                "a tier-2 record decays to a quarter weight",
            )
            old_ranking = by_id[old["record_id"]]["ranking"]
            self.assertEqual(
                old_ranking["decayed_score_micro"], round(old_ranking["rrf_score_micro"] * 0.25),
                "rrf_score_micro stays pure fusion; decay lands in its own field",
            )

    def test_age_tier_reads_naive_timestamps_as_utc_and_tolerates_garbage(self) -> None:
        from omh.workflows.memory import _age_tier

        now = datetime(2026, 7, 30, tzinfo=timezone.utc)
        self.assertEqual(_age_tier("2026-06-20T00:00:00", now=now), 1, "naive timestamps read as UTC, host-independent")
        self.assertEqual(_age_tier("2027-01-01T00:00:00Z", now=now), 0, "future approved_at clamps to age zero")
        self.assertEqual(_age_tier("not-a-timestamp", now=now), 0)
        self.assertEqual(_age_tier("", now=now), 0)

    def test_compacted_ranking_keeps_age_tier_and_pin_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approve_capture(paths, "compaction anchor")
            set_memory_pin(paths, record["record_id"], pinned=True)

            pack = build_project_memory_recall_pack(paths, "")
            compacted = _compact_memory_recall_pack(pack)

            [item] = compacted["included_records"]
            self.assertIs(item["ranking"]["pinned"], True)
            self.assertEqual(item["ranking"]["age_tier"], 0)


class DuplicateDetectionTests(unittest.TestCase):
    def test_exact_normalized_duplicate_is_flagged_and_never_auto_approved(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            original = _approve_capture(paths, "Deploys go through staging first")

            write_setup_profile(paths, memory_mode="auto-safe")
            fresh = capture_project_memory_candidate(paths, "fresh auto-safe fact", tags=["ok"])
            self.assertTrue(fresh["auto_approved"], "sanity: auto-safe policy approves non-duplicates")

            duplicate = capture_project_memory_candidate(paths, "  deploys   go through STAGING first ")
            candidate = duplicate["candidate"]
            self.assertEqual(candidate["duplicate_of"], original["record_id"])
            self.assertFalse(duplicate["auto_approved"], "a duplicate must wait for a reviewer")
            self.assertEqual(candidate["status"], "pending_review")

            review = build_project_memory_review(paths, candidate_id=str(candidate["candidate_id"]))
            [card] = review["cards"]
            self.assertEqual(card["duplicate_of"], original["record_id"])

    def test_distinct_summaries_are_not_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approve_capture(paths, "Deploys go through staging first")
            captured = capture_project_memory_candidate(paths, "Deploys go through staging first, then canary")
            self.assertNotIn("duplicate_of", captured["candidate"])

    def test_long_summaries_dedupe_at_the_stored_truncation_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            long_summary = "release pipeline detail " * 30
            first = capture_project_memory_candidate(paths, long_summary)
            self.assertTrue(first["auto_approved"])

            second = capture_project_memory_candidate(paths, long_summary)

            self.assertEqual(second["candidate"].get("duplicate_of"), first["record"]["record_id"])
            self.assertFalse(second["auto_approved"], "truncated stored summaries must still dedupe verbatim re-captures")

    def test_expired_record_does_not_block_the_ttl_refresh_recapture(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            stale = _approve_capture(paths, "volatile fact to refresh", retention_class="volatile", ttl_days=1)
            past = (datetime.now(timezone.utc) - timedelta(days=8)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            _rewrite_record(
                paths, stale["record_id"],
                approved_at=past,
                ttl={"ttl_days": 1, "expires_at": (datetime.now(timezone.utc) - timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z")},
            )

            refreshed = capture_project_memory_candidate(paths, "volatile fact to refresh")

            self.assertNotIn("duplicate_of", refreshed["candidate"], "an expired predecessor must not deny its own refresh")

    def test_approved_record_never_carries_duplicate_of(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            original = _approve_capture(paths, "Deploys go through staging first")
            duplicate = capture_project_memory_candidate(paths, "Deploys go through staging first")
            self.assertEqual(duplicate["candidate"]["duplicate_of"], original["record_id"])

            approved = approve_project_memory_candidate(paths, duplicate["candidate"]["candidate_id"])["record"]

            self.assertNotIn("duplicate_of", approved, "duplicate_of is review-time context, not record payload")


class HeldRecaptureTests(unittest.TestCase):
    """A held candidate captured again is retired in favour of the newer one."""

    def setUp(self) -> None:
        tmp = Path(self.enterContext(TemporaryDirectory()))
        self.paths = resolve_paths(tmp / ".omh", tmp / ".hermes")
        write_setup_profile(self.paths, memory_mode="review-first")

    def _candidate(self, candidate_id: str) -> dict:
        path = self.paths.memory_dir / "candidates" / f"{candidate_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_recapture_retires_the_held_one_with_its_reason(self) -> None:
        first = capture_project_memory_candidate(self.paths, "Deploys go through staging first")["candidate"]
        second = capture_project_memory_candidate(self.paths, "  deploys   go through STAGING first ")

        earlier = self._candidate(first["candidate_id"])
        self.assertEqual(earlier["status"], "retired")
        self.assertEqual(earlier["retirement_reason"], "recaptured")
        self.assertEqual(earlier["recaptured_as"], second["candidate"]["candidate_id"])
        self.assertTrue(earlier["retired_at"])
        self.assertEqual(second["retired_held_candidates"], [first["candidate_id"]])
        self.assertEqual(second["candidate"]["status"], "pending_review")
        review = build_project_memory_review(self.paths)
        self.assertEqual([card["candidate_id"] for card in review["cards"]], [second["candidate"]["candidate_id"]])
        with self.assertRaisesRegex(ValueError, "retired by a recapture"):
            approve_project_memory_candidate(self.paths, first["candidate_id"])

    def test_a_different_candidate_is_untouched(self) -> None:
        first = capture_project_memory_candidate(self.paths, "Deploys go through staging first")["candidate"]
        other_text = capture_project_memory_candidate(self.paths, "Deploys go through staging first, then canary")
        other_scope = capture_project_memory_candidate(
            self.paths, "Deploys go through staging first", scope_kind="project", scope_ref="another-project"
        )

        self.assertEqual(self._candidate(first["candidate_id"])["status"], "pending_review")
        self.assertNotIn("retired_held_candidates", other_text)
        self.assertNotIn("retired_held_candidates", other_scope)

    def test_a_retired_copy_cannot_be_rejected_either(self) -> None:
        first = capture_project_memory_candidate(self.paths, "Deploys go through staging first")["candidate"]
        capture_project_memory_candidate(self.paths, "Deploys go through staging first")

        with self.assertRaisesRegex(ValueError, "retired by a recapture"):
            reject_project_memory_candidate(self.paths, first["candidate_id"], reason="stale")
        self.assertEqual(self._candidate(first["candidate_id"])["status"], "retired")

    def test_the_same_summary_under_another_perspective_is_another_memory(self) -> None:
        codex = capture_project_memory_candidate(
            self.paths, "Runs the lint step before pushing", observer="hermes", observed="codex"
        )["candidate"]
        claude = capture_project_memory_candidate(
            self.paths, "Runs the lint step before pushing", observer="hermes", observed="claude-code"
        )
        self.assertEqual(self._candidate(codex["candidate_id"])["status"], "pending_review")
        self.assertNotIn("retired_held_candidates", claude)

        again = capture_project_memory_candidate(
            self.paths, "Runs the lint step before pushing", observer="hermes", observed="codex"
        )
        self.assertEqual(again["retired_held_candidates"], [codex["candidate_id"]])
        self.assertEqual(self._candidate(claude["candidate"]["candidate_id"])["status"], "pending_review")

    def test_an_auto_safe_approval_that_raises_retires_nothing(self) -> None:
        held = capture_project_memory_candidate(self.paths, "Deploys go through staging first")["candidate"]
        write_setup_profile(self.paths, memory_mode="auto-safe")

        with patch.object(memory_admission, "approve_project_memory_candidate", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                capture_project_memory_candidate(self.paths, "Deploys go through staging first")

        self.assertEqual(self._candidate(held["candidate_id"])["status"], "pending_review")

    def test_recapture_of_an_approved_or_rejected_one_behaves_as_before(self) -> None:
        approved = capture_project_memory_candidate(self.paths, "Deploys go through staging first")["candidate"]
        record = approve_project_memory_candidate(self.paths, approved["candidate_id"])["record"]
        rejected = capture_project_memory_candidate(self.paths, "Releases ship on Fridays")["candidate"]
        reject_project_memory_candidate(self.paths, rejected["candidate_id"], reason="not true")

        again_approved = capture_project_memory_candidate(self.paths, "Deploys go through staging first")
        again_rejected = capture_project_memory_candidate(self.paths, "Releases ship on Fridays")

        self.assertEqual(self._candidate(approved["candidate_id"])["status"], "approved")
        self.assertEqual(again_approved["candidate"]["duplicate_of"], record["record_id"])
        self.assertEqual(again_approved["candidate"]["status"], "pending_review")
        self.assertEqual(self._candidate(rejected["candidate_id"])["status"], "rejected")
        self.assertEqual(again_rejected["candidate"]["status"], "pending_review")
        self.assertNotIn("retired_held_candidates", again_approved)
        self.assertNotIn("retired_held_candidates", again_rejected)

    def test_an_auto_safe_recapture_retires_the_copy_held_for_a_relative_date(self) -> None:
        write_setup_profile(self.paths, memory_mode="auto-safe")
        held = capture_project_memory_candidate(self.paths, "The deploy freeze ends tomorrow")
        self.assertEqual(held["review_reason"], "relative_time_phrase")

        again = capture_project_memory_candidate(self.paths, "The deploy freeze ends tomorrow")

        self.assertEqual(again["retired_held_candidates"], [held["candidate"]["candidate_id"]])
        self.assertEqual(build_project_memory_review(self.paths)["pending_count"], 1)


if __name__ == "__main__":
    unittest.main()
