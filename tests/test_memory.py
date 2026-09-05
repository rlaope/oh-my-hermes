from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package
from _platform_support import requires_posix, requires_posix_permissions
from _credential_fixtures import AWS_ACCESS_KEY_ID

load_local_package()
from omh.coding_delegation import build_coding_delegation_payload
from omh.coding_lifecycle import start_codex_delegation_lifecycle
from omh.plugin_bundle.omh import memory_governance
from omh.workflows import memory as memory_workflow
from omh.memory import (
    StaleMemoryReviewError,
    apply_approved_memory_update_batch,
    apply_memory_update_batch,
    approve_project_memory_candidate,
    build_handoff_context_pack,
    build_memory_inspection,
    apply_memory_retirement,
    build_memory_retirement,
    build_memory_review_card,
    build_project_memory_recall_pack,
    build_project_memory_review,
    build_project_memory_status,
    capture_project_memory_candidate,
    memory_recall_pack_for_handoff,
    read_handoff_context_pack_file,
    reject_project_memory_candidate,
    review_memory_update_batch,
    stage_memory_update_batch,
    validate_project_memory_recall_pack,
)
from omh.memory import file_lock
from omh.paths import resolve_paths
from omh.profiles.setup import write_setup_profile
from omh.targets import record_target_observation


def _read_only_record(paths):
    records_dir = paths.memory_dir / "records"
    files = sorted(records_dir.glob("*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _write_v2_record_with_matching_review(paths, record_path, record) -> None:
    admission = record.get("admission")
    if isinstance(admission, dict):
        digest = memory_governance.canonical_payload_digest(record)
        admission["payload_digest"] = digest
        review = paths.memory_dir / "reviews" / f"{admission['review_id']}.json"
        review_payload = json.loads(review.read_text(encoding="utf-8"))
        review_payload["payload_digest"] = digest
        review.write_text(json.dumps(review_payload), encoding="utf-8")
    record_path.write_text(json.dumps(record), encoding="utf-8")


class MemoryContractTests(unittest.TestCase):
    def test_project_memory_capture_review_approve_and_recall_are_local_and_typed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            captured = capture_project_memory_candidate(
                paths,
                "Use unittest discovery before release checklist changes",
                record_type="procedure",
                tags=["tests", "release"],
                stale_after_days=120,
            )

            candidate = captured["candidate"]
            candidate_id = candidate["candidate_id"]
            self.assertEqual(candidate["schema_version"], "project_memory_candidate/v1")
            self.assertEqual(candidate["status"], "pending_review")
            self.assertTrue((paths.memory_dir / "candidates" / f"{candidate_id}.json").exists())
            self.assertFalse((paths.memory_dir / "records").exists())

            review = build_project_memory_review(paths)
            self.assertEqual(review["schema_version"], "project_memory_review_queue/v1")
            self.assertEqual(review["cards"][0]["schema_version"], "project_memory_review_card/v1")
            self.assertIn("not execution", review["claim_boundary"])

            approved = approve_project_memory_candidate(paths, candidate_id, approved_by="user")
            record = approved["record"]
            self.assertEqual(record["schema_version"], "project_memory_record/v2")
            self.assertEqual(record["admission"]["state"], "approved_manual")
            self.assertTrue((paths.memory_dir / "records" / f"{record['record_id']}.json").exists())

            recall = build_project_memory_recall_pack(paths, "release tests", executor_target="codex")
            self.assertEqual(recall["schema_version"], "project_memory_recall_pack/v1")
            self.assertEqual(recall["record_count"], 1)
            self.assertEqual(recall["included_records"][0]["record_id"], record["record_id"])
            self.assertIn("prepared context", recall["claim_boundary"])

            status = build_project_memory_status(paths)
            self.assertEqual(status["counts"]["approved_records"], 1)
            self.assertEqual(status["counts"]["pending_review"], 0)

    def test_project_memory_safety_blocks_secrets_and_review_marks_short_lived_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            blocked = capture_project_memory_candidate(
                paths,
                "Private token is abc-secret-token",
                content="Traceback (most recent call last):\npassword=secret",
            )
            blocked_candidate = blocked["candidate"]

            self.assertEqual(blocked_candidate["status"], "blocked_review_required")
            self.assertEqual(blocked_candidate["safety"]["status"], "blocked")
            self.assertNotIn("abc-secret-token", json.dumps(blocked_candidate))
            with self.assertRaises(ValueError):
                approve_project_memory_candidate(paths, blocked_candidate["candidate_id"])

            rejected = reject_project_memory_candidate(paths, blocked_candidate["candidate_id"], reason="contains password=secret")
            self.assertEqual(rejected["decision"], "rejected")
            self.assertIn("not execution", rejected["claim_boundary"])
            self.assertNotIn("password=secret", json.dumps(rejected))

            needs_review = capture_project_memory_candidate(paths, "PR #123 fixed this temporarily", record_type="lesson")
            self.assertEqual(needs_review["candidate"]["safety"]["status"], "safe")
            self.assertEqual(needs_review["candidate"]["safety"]["review_reasons"], [])

    def test_project_memory_bare_credentials_are_blocked_and_redacted_before_review(self) -> None:
        credentials = (
            AWS_ACCESS_KEY_ID,
            "gh" + "p_" + "a" * 36,
            "sk" + "-" + "a" * 48,
            "https://user:pass@example.com",
            "-----BEGIN PRIVATE KEY-----",
        )
        for credential in credentials:
            with self.subTest(credential_kind=credential[:4]), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                write_setup_profile(paths, memory_mode="auto-safe")

                captured = capture_project_memory_candidate(
                    paths,
                    f"Observed {credential}",
                    tags=[credential],
                    source=credential,
                    source_ref=credential,
                )
                candidate = captured["candidate"]
                serialized = json.dumps(captured, sort_keys=True)
                self.assertEqual(candidate["status"], "blocked_review_required")
                self.assertFalse(captured["auto_approved"])
                self.assertNotIn(credential, serialized)
                self.assertNotIn(credential, json.dumps(build_project_memory_review(paths), sort_keys=True))

                with self.assertRaises(ValueError):
                    approve_project_memory_candidate(paths, candidate["candidate_id"])
                rejected = reject_project_memory_candidate(paths, candidate["candidate_id"], reason=f"blocked {credential}")
                self.assertNotIn(credential, json.dumps(rejected, sort_keys=True))
                self.assertFalse((paths.memory_dir / "records").exists())

    def test_project_memory_auto_safe_policy_auto_approves_safe_candidates(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")

            captured = capture_project_memory_candidate(paths, "Prefer docs workflow checks for generated workflow docs", record_type="procedure")

            self.assertTrue(captured["auto_approved"])
            self.assertEqual(captured["record"]["schema_version"], "project_memory_record/v2")
            self.assertEqual(build_project_memory_status(paths)["counts"]["approved_records"], 1)

    def test_staleness_uses_injected_now_and_utc_naive_rule(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths,
                "Deterministic staleness fixture for release tests",
                record_type="procedure",
                tags=["release", "tests"],
                ttl_days=5,
            )
            record = _read_only_record(paths)
            expires_at = datetime.fromisoformat(str(record["ttl"]["expires_at"]).replace("Z", "+00:00"))

            before = build_project_memory_recall_pack(paths, "release tests", now=expires_at - timedelta(seconds=1))
            self.assertEqual(before["record_count"], 1)

            boundary = build_project_memory_recall_pack(paths, "release tests", now=expires_at)
            self.assertEqual(boundary["record_count"], 0)
            self.assertEqual(boundary["excluded_records"][0]["reason"], "expired_standard")

            after = build_project_memory_recall_pack(paths, "release tests", now=expires_at + timedelta(days=30))
            self.assertEqual(after["record_count"], 0)
            self.assertEqual(after["excluded_records"][0]["reason"], "expired_standard")

    @requires_posix
    def test_recall_reads_naive_expiry_as_utc_under_any_host_timezone(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths,
                "Naive timestamp fixture for release tests",
                record_type="procedure",
                tags=["release", "tests"],
                ttl_days=5,
            )
            record = _read_only_record(paths)
            record_path = paths.memory_dir / "records" / f"{record['record_id']}.json"
            mutated = json.loads(record_path.read_text(encoding="utf-8"))
            mutated["ttl"]["expires_at"] = "2026-07-28T12:00:00"  # naive, by definition UTC
            mutated["retention"]["expires_at"] = "2026-07-28T12:00:00"
            _write_v2_record_with_matching_review(paths, record_path, mutated)

            probe_now = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
            original = os.environ.get("TZ")
            try:
                results = []
                for tz in ("Pacific/Kiritimati", "Pacific/Niue"):
                    os.environ["TZ"] = tz
                    time.tzset()
                    pack = build_project_memory_recall_pack(paths, "release tests", now=probe_now)
                    results.append((pack["record_count"], pack["excluded_records"][0]["reason"]))
                self.assertEqual(results[0], results[1])
                self.assertEqual(results[0], (0, "expired_standard"))
            finally:
                if original is None:
                    os.environ.pop("TZ", None)
                else:
                    os.environ["TZ"] = original
                time.tzset()

    def test_memory_retirement_report_is_fail_closed_and_write_free(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths, "Expired fixture keeps release tests honest", record_type="procedure", tags=["release"], ttl_days=5
            )
            capture_project_memory_candidate(
                paths, "Expiring fixture keeps release tests honest", record_type="procedure", tags=["release"], ttl_days=7
            )
            records_dir = paths.memory_dir / "records"
            by_ttl = {}
            for path in records_dir.glob("*.json"):
                data = json.loads(path.read_text(encoding="utf-8"))
                by_ttl[data["ttl"]["ttl_days"]] = data
            expired_id = by_ttl[5]["record_id"]
            expiring_id = by_ttl[7]["record_id"]
            created = datetime.fromisoformat(str(by_ttl[5]["ttl"]["expires_at"]).replace("Z", "+00:00"))
            probe_now = created + timedelta(days=1)  # 5d TTL expired, 7d TTL expiring within window

            (records_dir / "mem_corrupt.json").write_text("{", encoding="utf-8")
            (records_dir / "mem_link.json").symlink_to("/etc/hosts")
            (records_dir / "mem_other.json").write_text(json.dumps({"schema_version": "other/v1"}), encoding="utf-8")
            rejected = dict(by_ttl[5])
            rejected["record_id"] = "mem_rejfix"
            rejected["review_status"] = "rejected"
            (records_dir / "mem_rejfix.json").write_text(json.dumps(rejected), encoding="utf-8")
            mismatch = dict(by_ttl[5])
            mismatch["record_id"] = "mem_realid"
            (records_dir / "mem_wrongname.json").write_text(json.dumps(mismatch), encoding="utf-8")
            malformed = dict(by_ttl[5])
            malformed["record_id"] = "mem_badttl"
            malformed["ttl"] = {"ttl_days": 1, "expires_at": "garbage"}
            (records_dir / "mem_badttl.json").write_text(json.dumps(malformed), encoding="utf-8")
            no_ttl = dict(by_ttl[5])
            no_ttl["record_id"] = "mem_nottl"
            no_ttl["ttl"] = {"ttl_days": None, "expires_at": ""}
            (records_dir / "mem_nottl.json").write_text(json.dumps(no_ttl), encoding="utf-8")

            names_before = sorted(p.name for p in records_dir.glob("*.json"))
            mtimes_before = {p.name: p.lstat().st_mtime_ns for p in records_dir.glob("*.json")}

            report = build_memory_retirement(paths, now=probe_now)

            self.assertEqual(report["schema_version"], "omh_memory_retirement_report/v1")
            self.assertFalse(report["applied"])
            self.assertEqual(report["window_days"], 7)
            self.assertEqual([row["record_id"] for row in report["expired"]], [expired_id])
            self.assertEqual([row["record_id"] for row in report["expiring_soon"]], [expiring_id])
            reasons = {row["path_name"]: row["reason"] for row in report["skipped"]}
            self.assertEqual(reasons["mem_corrupt.json"], "corrupt_json")
            self.assertEqual(reasons["mem_link.json"], "symlink_or_not_file")
            self.assertEqual(reasons["mem_other.json"], "not_canonical")
            self.assertEqual(reasons["mem_rejfix.json"], "not_canonical")
            self.assertEqual(reasons["mem_wrongname.json"], "unsafe_record_id")
            self.assertEqual(reasons["mem_badttl.json"], "malformed_expires_at")
            self.assertNotIn("mem_nottl.json", reasons)
            self.assertEqual(report["counts"]["expired"], 1)
            self.assertEqual(report["counts"]["expiring_soon"], 1)
            self.assertEqual(report["redaction_policy"], "metadata_only")
            self.assertTrue(report["claim_boundary"])
            self.assertNotIn("summary", json.dumps(report["expired"] + report["expiring_soon"]))

            self.assertEqual(sorted(p.name for p in records_dir.glob("*.json")), names_before)
            self.assertEqual({p.name: p.lstat().st_mtime_ns for p in records_dir.glob("*.json")}, mtimes_before)
    def test_over_budget_cut_names_a_same_topic_sibling(self) -> None:
        """A cut record sharing a tag with a kept record gets a sibling hint,
        so a same-topic disagreement cannot vanish silently; unrelated cuts
        carry no hint (issue #740)."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            for idx in range(3):
                capture_project_memory_candidate(
                    paths,
                    f"Deploy policy variant {idx} for release tests",
                    record_type="procedure",
                    tags=["release", "tests"],
                )
            capture_project_memory_candidate(
                paths,
                "Unrelated onboarding note for docs",
                record_type="procedure",
                tags=["onboarding"],
            )
            pack = build_project_memory_recall_pack(paths, "release tests deploy policy", limit=2)
            self.assertTrue(pack["truncated"])
            kept_ids = {str(item["record_id"]) for item in pack["included_records"]}
            cut = [item for item in pack["excluded_records"] if item["reason"] == "over_budget"]
            self.assertTrue(cut)
            tagged_cut = [item for item in cut if "sibling_included" in item]
            self.assertTrue(tagged_cut)
            for item in tagged_cut:
                self.assertIn(item["sibling_included"], kept_ids)
            self.assertEqual(validate_project_memory_recall_pack(pack), [])

    def test_project_memory_recall_pack_budget_marks_truncation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            for idx in range(4):
                capture_project_memory_candidate(
                    paths,
                    f"Release tests procedure variant {idx} keeps workflow docs verified",
                    record_type="procedure",
                    tags=["release", "tests"],
                )

            untouched = build_project_memory_recall_pack(paths, "release tests")
            self.assertEqual(untouched["record_count"], 4)
            self.assertFalse(untouched["truncated"])
            self.assertEqual(validate_project_memory_recall_pack(untouched), [])

            by_records = build_project_memory_recall_pack(paths, "release tests", limit=2)
            self.assertTrue(by_records["truncated"])
            self.assertEqual(by_records["record_count"], 2)
            over_budget = [item for item in by_records["excluded_records"] if item["reason"] == "over_budget"]
            self.assertEqual(len(over_budget), 2)
            included_ids = {item["record_id"] for item in by_records["included_records"]}
            self.assertFalse(included_ids & {item["record_id"] for item in over_budget})
            self.assertEqual(included_ids, {item["record_id"] for item in untouched["included_records"][:2]})
            self.assertEqual(validate_project_memory_recall_pack(by_records), [])

            summary_chars = len(str(untouched["included_records"][0]["summary"]))
            by_chars = build_project_memory_recall_pack(paths, "release tests", max_chars=summary_chars * 2)
            self.assertTrue(by_chars["truncated"])
            self.assertEqual(by_chars["record_count"], 2)
            self.assertEqual(
                sum(1 for item in by_chars["excluded_records"] if item["reason"] == "over_budget"),
                2,
            )
            self.assertEqual(validate_project_memory_recall_pack(by_chars), [])

    def test_project_memory_recall_matches_cjk_queries_and_keeps_cjk_tags(self) -> None:
        """Korean chat must be able to reach approved records.

        The old ASCII-only tokenizer reduced every CJK query to zero tokens, so
        each record was excluded as no_query_overlap and Korean-speaking
        sessions always received an empty recall pack: long-term project memory
        looked like it did not exist. CJK tags were also dropped at capture.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            captured = capture_project_memory_candidate(
                paths,
                "배포는 staging 환경을 먼저 거친다",
                record_type="procedure",
                tags=["배포", "release"],
            )
            self.assertIn("배포", captured["candidate"]["tags"])

            # Particle-inflected query: "배포" must match "배포는" in the summary.
            recall = build_project_memory_recall_pack(paths, "배포 정책 알려줘")
            self.assertEqual(recall["record_count"], 1)
            self.assertGreater(recall["included_records"][0]["score"], 0)
            self.assertEqual(validate_project_memory_recall_pack(recall), [])

            # Overroute guard: an unrelated Korean query still recalls nothing.
            miss = build_project_memory_recall_pack(paths, "결제 모듈 장애")
            self.assertEqual(miss["record_count"], 0)
            self.assertEqual(miss["excluded_records"][0]["reason"], "no_query_overlap")

    def test_project_memory_recall_reaches_two_letter_technical_terms(self) -> None:
        """CI, DB, UI, QA and friends must be findable.

        The >=3 ASCII length floor dropped every two-letter word, which produced
        two opposite failures against the same store. "CI" tokenized to nothing,
        so the no-indexable-tokens fallback returned every record with no
        exclusion reason at all; "ci failures" tokenized to {failures}, so the
        record whose summary began with "CI" and carried `ci` as a tag came back
        as no_query_overlap. The tag bonus could not save it either -- the query
        token was dropped before the tag comparison ran.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(paths, "CI runs on GitHub Actions for every push", tags=["ci"])
            capture_project_memory_candidate(paths, "Postgres is the primary DB for the api service", tags=["db"])
            capture_project_memory_candidate(paths, "Terraform provisions the staging cluster", tags=["infra"])

            recall = build_project_memory_recall_pack(paths, "ci failures")
            self.assertEqual([item["summary"] for item in recall["included_records"]],
                             ["CI runs on GitHub Actions for every push"])
            self.assertEqual(validate_project_memory_recall_pack(recall), [])

            # The bare term used to return the whole store through the fallback.
            bare = build_project_memory_recall_pack(paths, "CI")
            self.assertEqual(bare["record_count"], 1)

            natural = build_project_memory_recall_pack(paths, "which DB do we use")
            self.assertEqual([item["summary"] for item in natural["included_records"]],
                             ["Postgres is the primary DB for the api service"])

            # Overroute guard: an unrelated query still recalls nothing.
            miss = build_project_memory_recall_pack(paths, "quantum tunnelling")
            self.assertEqual(miss["record_count"], 0)
            self.assertEqual(miss["excluded_records"][0]["reason"], "no_query_overlap")

    def test_two_letter_function_words_stay_out_of_the_recall_index(self) -> None:
        """The floor kept English filler out; naming it must keep doing that.

        Without the stopword list, "we", "do", "is", "of" would index and a
        query built only from them would match every record that contains one.
        """
        from omh.workflows.memory import _memory_tokens

        self.assertEqual(_memory_tokens("we do it"), set())
        self.assertEqual(_memory_tokens("is it up to us"), set())
        # Real two-letter terms are not filler and stay indexable.
        for term in ("ci", "db", "ui", "qa", "ml", "pr", "js", "go", "s3", "ai", "ux", "vs", "id"):
            self.assertIn(term, _memory_tokens(f"the {term} thing"), term)
        # A short token is a whole word, never a fragment of a longer one.
        self.assertNotIn("ru", _memory_tokens("runs"))
        self.assertNotIn("ci", _memory_tokens("circular"))
        self.assertNotIn("db", _memory_tokens("dbname"))

    def test_project_memory_recall_treats_nfd_and_nfc_queries_alike(self) -> None:
        """macOS pipelines hand over decomposed Hangul; ranking must not differ."""
        import unicodedata

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths, "배포는 staging 환경을 먼저 거친다", record_type="procedure", tags=["배포"]
            )
            nfc = build_project_memory_recall_pack(paths, "배포 정책")
            nfd = build_project_memory_recall_pack(paths, unicodedata.normalize("NFD", "배포 정책"))
            self.assertEqual(nfc["record_count"], 1)
            self.assertEqual(
                [item["score"] for item in nfc["included_records"]],
                [item["score"] for item in nfd["included_records"]],
            )
            self.assertGreater(nfd["included_records"][0]["score"], 1)

    def test_project_memory_recall_skips_corrupt_store_files(self) -> None:
        """A crash-truncated record file must cost only itself, not all recall."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths, "배포는 staging 환경을 먼저 거친다", record_type="procedure", tags=["배포"]
            )
            records_dir = paths.memory_dir / "records"
            (records_dir / "zz-truncated.json").write_text('{"schema_version": "project_mem', encoding="utf-8")
            (records_dir / "zz-not-json.json").write_text("{not json", encoding="utf-8")

            pack = build_project_memory_recall_pack(paths, "배포 정책")
            self.assertEqual(pack["record_count"], 1)
            self.assertEqual(validate_project_memory_recall_pack(pack), [])
            status = build_project_memory_status(paths)
            self.assertEqual(status["counts"]["approved_records"], 1)

    def test_project_memory_recall_query_without_indexable_tokens_falls_back(self) -> None:
        """A query with no indexable tokens must not silently empty the pack."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths,
                "Run release tests before merge",
                record_type="procedure",
                tags=["release"],
            )

            pack = build_project_memory_recall_pack(paths, "\U0001f44d\U0001f64f")
            self.assertTrue(pack["task_ref"]["query_supplied"])
            self.assertEqual(pack["record_count"], 1)
            self.assertEqual(validate_project_memory_recall_pack(pack), [])

    def test_project_memory_recall_pack_feeds_coding_handoff_when_enabled(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(
                paths,
                "Run setup diagnostics before changing installation health checks",
                record_type="procedure",
                tags=["setup", "diagnose"],
            )
            approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])

            message = "diagnose installation health in src/commands/setup.py"
            recall = memory_recall_pack_for_handoff(paths, message, executor_target="codex")
            payload = build_coding_delegation_payload(
                message,
                source="discord",
                executor_target="codex",
                memory_recall_pack=recall,
            )
            lifecycle = start_codex_delegation_lifecycle(paths, message, source="discord")

            self.assertIn("memory_recall_pack", payload["executor_handoff"])
            self.assertEqual(payload["executor_handoff"]["memory_recall_pack"]["record_count"], 1)
            record_handoff = lifecycle["coding_delegation"]["executor_handoff"]
            self.assertIn("memory_recall_pack", record_handoff)
            persisted_pack = record_handoff["memory_recall_pack"]
            self.assertEqual(persisted_pack["record_count"], 1)
            # The persisted lifecycle record is what the wrapper re-serves to
            # the executor, so the redacted summaries must survive compaction:
            # dropping them made lifecycle-backed delegation recall-blind
            # while prompt-only executors kept the summaries.
            self.assertEqual(len(persisted_pack["included_records"]), 1)
            self.assertIn("setup diagnostics", persisted_pack["included_records"][0]["summary"])
            self.assertEqual(persisted_pack["excluded_records"], [])
            self.assertEqual(validate_project_memory_recall_pack(persisted_pack), [])
            self.assertIn("not execution", persisted_pack["claim_boundary"])

    def test_inspection_separates_sources_and_detects_stale_conflicts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            write_setup_profile(paths, ["prompt-only-coding"])
            record_target_observation(
                paths,
                source="discord",
                source_metadata={"target_ref": "team-thread", "agent_count": "3"},
            )
            wrapper_snapshot = _wrapper_snapshot(
                [
                    {
                        "item_id": "executor-pref",
                        "key": "default_executor",
                        "value": "codex",
                        "summary": "Use Codex by default",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                    {
                        "item_id": "target-mode",
                        "key": "target_mode",
                        "value": "single_agent_target",
                        "summary": "Assume one Hermes agent",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                    {
                        "item_id": "release-verified",
                        "key": "verification_status",
                        "value": "verified",
                        "summary": "Release is verified",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                    {
                        "item_id": "private-note",
                        "key": "note",
                        "value": "raw-secret-token-123",
                        "summary": "Private note",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                ]
            )

            inspection = build_memory_inspection(paths, wrapper_snapshot=wrapper_snapshot)

            self.assertEqual(inspection["schema_version"], "memory_inspection/v1")
            source_levels = {snapshot["source"]: snapshot["truth_level"] for snapshot in inspection["snapshots"]}
            self.assertEqual(source_levels["setup_profile"], "preference_default")
            self.assertEqual(source_levels["target_topology"], "setup_evidence")
            self.assertEqual(source_levels["wrapper_snapshot"], "supplied_hint")
            conflict_keys = {conflict["key"] for conflict in inspection["conflicts"]}
            self.assertIn("default_executor", conflict_keys)
            self.assertIn("target_mode", conflict_keys)
            self.assertIn("verification_status", conflict_keys)
            self.assertNotIn("raw-secret-token-123", json.dumps(inspection))

    def test_wrapper_snapshot_cannot_claim_runtime_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            wrapper_snapshot = _wrapper_snapshot(
                [
                    {
                        "item_id": "release-verified",
                        "key": "verification_status",
                        "value": "verified",
                        "summary": "Release is verified",
                        "scope": {"kind": "project", "ref": "default"},
                    }
                ]
            )
            wrapper_snapshot["source"] = "runtime_evidence"

            inspection = build_memory_inspection(paths, wrapper_snapshot=wrapper_snapshot)

            wrapper_sources = [snapshot for snapshot in inspection["snapshots"] if snapshot["source"] == "wrapper_snapshot"]
            self.assertEqual(len(wrapper_sources), 1)
            self.assertEqual(wrapper_sources[0]["truth_level"], "supplied_hint")
            self.assertIn("verification_status", {conflict["key"] for conflict in inspection["conflicts"]})
            review_items = {item["item_id"]: item for item in inspection["review_items"]}
            self.assertTrue(review_items["release-verified"]["blocked"])

    def test_review_card_is_distinct_from_runtime_status_card(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            inspection = build_memory_inspection(paths, wrapper_snapshot=_wrapper_snapshot([]))

            card = build_memory_review_card(inspection)

            self.assertEqual(card["schema_version"], "memory_review_card/v1")
            self.assertNotEqual(card["schema_version"], "status_card/v1")
            action_ids = {action["id"] for action in card["actions"]}
            self.assertIn("keep_memory", action_ids)
            self.assertIn("forget_memory", action_ids)
            self.assertIn("update_memory", action_ids)
            self.assertIn("change_memory_scope", action_ids)
            self.assertIn("apply_memory_updates", action_ids)
            self.assertIn("Memory review is not runtime execution evidence", card["claim_boundary"])

    def test_direct_batch_apply_requires_review_and_staging_enforces_safety(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            approved_by = {
                "schema_version": "memory_update_batch/v1",
                "approved_by": "user",
                "source_surface": "discord",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "executor-pref",
                        "scope": {"kind": "project", "ref": "default"},
                        "value": "claude-code",
                        "summary": "Prefer Claude Code prompt-only handoffs",
                    }
                ],
            }
            without_approval = {key: value for key, value in approved_by.items() if key != "approved_by"}

            for batch in (approved_by, without_approval):
                result = apply_memory_update_batch(paths, batch)
                self.assertEqual(result["status"], "review_required")
                self.assertFalse(result["applied"])
                self.assertFalse(paths.memory_dir.exists())

            secret_batch = {
                "schema_version": "memory_update_batch/v1",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "private-note",
                        "scope": {"kind": "project", "ref": "default"},
                        "key": "note",
                        "value": "raw-secret-token-123",
                        "summary": "Private note",
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "unsafe"):
                stage_memory_update_batch(paths, secret_batch)
            self.assertFalse(paths.memory_dir.exists())

            unsafe_scope = {
                "schema_version": "memory_update_batch/v1",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "bad",
                        "scope": {"kind": "thread", "ref": "../../escape"},
                        "value": "bad",
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "scope"):
                stage_memory_update_batch(paths, unsafe_scope)
            self.assertFalse(paths.memory_dir.exists())

    def test_memory_inspection_ignores_symlink_scope_escapes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            outside = root / "outside.json"
            outside.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v1",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {"outside": {"item_id": "outside", "key": "note", "value": "outside-secret-token"}},
                    }
                ),
                encoding="utf-8",
            )
            scopes = paths.memory_dir / "scopes"
            scopes.mkdir(parents=True)
            (scopes / "escape.json").symlink_to(outside)

            inspection = build_memory_inspection(paths)

            self.assertNotIn("outside-secret-token", json.dumps(inspection))
            self.assertNotIn("outside", {item["item_id"] for item in inspection["review_items"]})

    def test_memory_inspection_summary_and_pack_limits_bound_output(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            batch = {
                "schema_version": "memory_update_batch/v1",
                "updates": [
                    {
                        "op": "update",
                        "item_id": f"context-{index}",
                        "scope": {"kind": "project", "ref": "default"},
                        "key": f"context_{index}",
                        "value": f"value-{index}",
                        "summary": f"Context item {index}",
                    }
                    for index in range(4)
                ],
            }
            staged = stage_memory_update_batch(paths, batch)
            decisions = {item["item_id"]: "remember" for item in staged["items"]}
            review_memory_update_batch(paths, staged["batch_id"], decisions, reviewer_label="operator")
            applied = apply_approved_memory_update_batch(paths, staged["batch_id"])
            self.assertTrue(applied["applied"])
            self.assertIn("receipt", applied)

            inspection = build_memory_inspection(paths, summary=True, review_item_limit=2)
            pack = build_handoff_context_pack(paths, context_limit=2)

            self.assertEqual(inspection["snapshots"], [])
            self.assertGreaterEqual(inspection["snapshot_count"], 1)
            self.assertTrue(inspection["snapshot_summary"])
            self.assertGreater(inspection["review_item_count"], len(inspection["review_items"]))
            self.assertLessEqual(len(inspection["review_items"]), 2)
            self.assertEqual(len(pack["included_context"]), 2)

    def test_handoff_context_pack_attaches_only_when_conflict_free(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            batch = {
                "schema_version": "memory_update_batch/v1",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "repo-verification",
                        "scope": {"kind": "project", "ref": "default"},
                        "key": "verification_command",
                        "value": "uv run python -m unittest discover -s tests -v",
                        "summary": "Run the unittest suite",
                        "reason": "Project verification default",
                    }
                ],
            }
            staged = stage_memory_update_batch(paths, batch)
            review_memory_update_batch(
                paths,
                staged["batch_id"],
                {staged["items"][0]["item_id"]: "remember"},
                reviewer_label="operator",
            )
            self.assertTrue(apply_approved_memory_update_batch(paths, staged["batch_id"])["applied"])

            pack = build_handoff_context_pack(paths, executor_target="codex")
            payload = build_coding_delegation_payload(
                "risky refactor with token-secret-123",
                source="discord",
                executor_target="codex",
                include_message=True,
                context_pack=pack,
            )

            self.assertEqual(pack["schema_version"], "handoff_context_pack/v1")
            self.assertEqual(pack["blocked_by_conflicts"], [])
            self.assertIn("context_pack", payload["executor_handoff"])
            self.assertEqual(payload["executor_handoff"]["context_pack"]["schema_version"], "handoff_context_pack/v1")
            self.assertNotIn("token-secret-123", json.dumps(payload["executor_handoff"]["context_pack"]))

    def test_conflicting_context_pack_is_blocked_instead_of_attached(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, ["prompt-only-coding"])
            inspection = build_memory_inspection(
                paths,
                wrapper_snapshot=_wrapper_snapshot(
                    [
                        {
                            "item_id": "executor-pref",
                            "key": "default_executor",
                            "value": "codex",
                            "summary": "Use Codex by default",
                            "scope": {"kind": "project", "ref": "default"},
                        }
                    ]
                ),
            )
            pack = build_handoff_context_pack(paths, inspection=inspection, executor_target="codex")

            payload = build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", context_pack=pack)

            self.assertTrue(pack["blocked_by_conflicts"])
            self.assertNotIn("context_pack", payload["executor_handoff"])
            self.assertIn("context_pack_blocked", payload["executor_handoff"])

    def test_malformed_context_pack_is_rejected_before_attachment(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            malformed = build_handoff_context_pack(paths, executor_target="codex")
            malformed["blocked_by_conflicts"] = "none"
            malformed["redaction_policy"] = "raw"
            malformed["included_context"] = [{"item_id": "bad", "key": "note", "value": "raw-secret-token"}]
            pack_path = root / "pack.json"
            pack_path.write_text(json.dumps(malformed), encoding="utf-8")

            with self.assertRaises(ValueError):
                read_handoff_context_pack_file(pack_path)
            with self.assertRaises(ValueError):
                build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", context_pack=malformed)

    def test_volatile_seven_day_boundary_is_consistent_across_recall_snapshots_and_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths,
                "Volatile release note for this week",
                record_type="fact",
                tags=["release"],
                retention_class="volatile",
            )
            record = _read_only_record(paths)
            record_path = paths.memory_dir / "records" / f"{record['record_id']}.json"
            stored = json.loads(record_path.read_text(encoding="utf-8"))
            admitted_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            retention = memory_governance.build_retention("volatile", record_type="fact", admitted_at=admitted_at)
            stored["retention"] = retention
            stored["ttl"] = {"ttl_days": retention["ttl_days"], "expires_at": retention["expires_at"]}
            _write_v2_record_with_matching_review(paths, record_path, stored)
            expires_at = datetime.fromisoformat(str(retention["expires_at"]).replace("Z", "+00:00"))

            before = build_project_memory_recall_pack(paths, "release", now=expires_at - timedelta(microseconds=1))
            before_snapshot = memory_workflow._memory_snapshots(paths, now=expires_at - timedelta(microseconds=1))
            at_boundary = build_project_memory_recall_pack(paths, "release", now=expires_at)
            boundary_snapshot = memory_workflow._memory_snapshots(paths, now=expires_at)
            handoff = build_handoff_context_pack(paths, now=expires_at)

            self.assertEqual(before["record_count"], 1)
            self.assertTrue(
                next(item for snapshot in before_snapshot for item in snapshot["items"] if item["item_id"] == record["record_id"])["replay_evaluation"]["eligible"]
            )
            reason = next(item["reason"] for item in at_boundary["excluded_records"] if item["record_id"] == record["record_id"])
            self.assertEqual(reason, "expired_volatile")
            self.assertEqual(
                next(item for snapshot in boundary_snapshot for item in snapshot["items"] if item["item_id"] == record["record_id"])["replay_evaluation"]["reason_code"],
                reason,
            )
            self.assertNotIn(record["record_id"], {item["item_id"] for item in handoff["included_context"]})
            self.assertEqual(next(item["reason"] for item in handoff["excluded_context"] if item["item_id"] == record["record_id"]), reason)

    def test_tampered_summary_is_rejected_at_every_replay_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(paths, "Run release checks", record_type="procedure", tags=["release"])
            record = _read_only_record(paths)
            record_path = paths.memory_dir / "records" / f"{record['record_id']}.json"
            tampered = json.loads(record_path.read_text(encoding="utf-8"))
            tampered["summary"] = "Run a different release process"
            record_path.write_text(json.dumps(tampered), encoding="utf-8")

            recall = build_project_memory_recall_pack(paths, "release")
            snapshots = memory_workflow._memory_snapshots(paths)
            handoff = build_handoff_context_pack(paths)

            self.assertEqual(next(item["reason"] for item in recall["excluded_records"] if item["record_id"] == record["record_id"]), "payload_digest_mismatch")
            self.assertEqual(
                next(item for snapshot in snapshots for item in snapshot["items"] if item["item_id"] == record["record_id"])["replay_evaluation"]["reason_code"],
                "payload_digest_mismatch",
            )
            self.assertEqual(next(item["reason"] for item in handoff["excluded_context"] if item["item_id"] == record["record_id"]), "payload_digest_mismatch")

    def test_stale_record_requires_a_bounded_exact_revision_override(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(paths, "Release policy remains current", record_type="procedure", tags=["release"])
            record = _read_only_record(paths)
            record_path = paths.memory_dir / "records" / f"{record['record_id']}.json"
            stored = json.loads(record_path.read_text(encoding="utf-8"))
            deadline = "2026-07-30T11:59:00Z"
            stored["revalidation"] = {"deadline": deadline}
            _write_v2_record_with_matching_review(paths, record_path, stored)
            now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
            identity = memory_governance.stable_artifact_identity(stored)
            override = {
                "artifact_identity": identity,
                "run_id": "run-1",
                "revalidation_deadline": deadline,
                "confirmed_at": "2026-07-30T12:00:00Z",
                "expires_at": "2026-07-30T13:00:00Z",
                "reviewer_claim": "operator",
            }

            stale = build_project_memory_recall_pack(paths, "release", now=now, run_id="run-1")
            wrong_revision = build_project_memory_recall_pack(
                paths,
                "release",
                now=now,
                run_id="run-1",
                stale_override={**override, "artifact_identity": {**identity, "revision": 2}},
            )
            allowed = build_project_memory_recall_pack(paths, "release", now=now, run_id="run-1", stale_override=override)

            self.assertEqual(stale["excluded_records"][0]["reason"], "stale_review_required")
            self.assertEqual(wrong_revision["excluded_records"][0]["reason"], "stale_override_invalid")
            self.assertEqual(allowed["record_count"], 1)
            self.assertEqual(allowed["included_records"][0]["eligibility_reason"], "eligible")

    def test_budget_and_admission_exclusions_have_distinct_reason_codes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            for index in range(3):
                capture_project_memory_candidate(
                    paths,
                    f"Release policy {index}",
                    record_type="procedure",
                    tags=["release"],
                )
            records = sorted((paths.memory_dir / "records").glob("*.json"))
            expired = json.loads(records[0].read_text(encoding="utf-8"))
            expired["retention"]["expires_at"] = "2020-01-01T00:00:00Z"
            expired["ttl"] = {"ttl_days": 1, "expires_at": "2020-01-01T00:00:00Z"}
            _write_v2_record_with_matching_review(paths, records[0], expired)

            pack = build_project_memory_recall_pack(paths, "release", limit=1, now=datetime(2026, 7, 30, tzinfo=timezone.utc))
            reasons = {item["reason"] for item in pack["excluded_records"]}

            self.assertIn("expired_standard", reasons)
            self.assertIn("over_budget", reasons)

    def test_expired_record_is_never_packable_through_memory_snapshots(self) -> None:
        """Regression: the old snapshot path bypassed recall's TTL exclusion."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(
                paths,
                "Release checks must run before deployment",
                record_type="procedure",
                tags=["release"],
                ttl_days=1,
            )
            record = _read_only_record(paths)
            record_path = paths.memory_dir / "records" / f"{record['record_id']}.json"
            expired_at = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
            stored = json.loads(record_path.read_text(encoding="utf-8"))
            stored["ttl"] = {"ttl_days": 1, "expires_at": expired_at.isoformat().replace("+00:00", "Z")}
            if isinstance(stored.get("retention"), dict):
                stored["retention"]["expires_at"] = stored["ttl"]["expires_at"]
                digest = memory_governance.canonical_payload_digest(stored)
                stored["admission"]["payload_digest"] = digest
                review_path = paths.memory_dir / "reviews" / f"{stored['admission']['review_id']}.json"
                review = json.loads(review_path.read_text(encoding="utf-8"))
                review["payload_digest"] = digest
                review_path.write_text(json.dumps(review), encoding="utf-8")
            record_path.write_text(json.dumps(stored), encoding="utf-8")

            recall = build_project_memory_recall_pack(paths, "release", now=expired_at)
            snapshots = memory_workflow._memory_snapshots(paths, now=expired_at)
            handoff = build_handoff_context_pack(paths, now=expired_at)

            reason = next(item["reason"] for item in recall["excluded_records"] if item["record_id"] == record["record_id"])
            snapshot_item = next(
                item
                for snapshot in snapshots
                for item in snapshot["items"]
                if item["item_id"] == record["record_id"]
            )
            self.assertEqual(snapshot_item["replay_evaluation"]["reason_code"], reason)
            self.assertNotIn(record["record_id"], {item["item_id"] for item in handoff["included_context"]})
            self.assertEqual(
                next(item["reason"] for item in handoff["excluded_context"] if item["item_id"] == record["record_id"]),
                reason,
            )

    def test_pending_staged_scope_candidate_is_review_visible_but_not_handoff_context(self) -> None:
        """Staging keeps pending scope data out of prompt-input files until exact review/apply."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            staged = stage_memory_update_batch(
                paths,
                {
                    "schema_version": "memory_update_batch/v1",
                    "updates": [
                        {
                            "op": "update",
                            "item_id": "unreviewed-scope-item",
                            "scope": {"kind": "project", "ref": "default"},
                            "key": "release_command",
                            "value": "uv run python -m unittest",
                            "summary": "Run unit tests before release",
                        }
                    ],
                },
            )

            pending_path = paths.memory_dir / "candidates" / f"{staged['batch_id']}.json"
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            apply_result = apply_approved_memory_update_batch(paths, staged["batch_id"])
            handoff = build_handoff_context_pack(paths)

            self.assertEqual(staged["status"], "pending_review")
            self.assertEqual(pending["status"], "pending_review")
            self.assertEqual(pending["items"][0]["artifact"]["admission"]["state"], "pending_review")
            self.assertEqual(apply_result["status"], "review_required")
            self.assertFalse(apply_result["applied"])
            self.assertFalse((paths.memory_dir / "scopes").exists())
            self.assertNotIn(staged["items"][0]["item_id"], {item["item_id"] for item in handoff["included_context"]})


class ProjectMemoryRevisionReviewTests(unittest.TestCase):
    """Review actions bind to the candidate revision the reviewer actually saw."""

    @staticmethod
    def _card(paths, candidate_id: str) -> dict:
        review = build_project_memory_review(paths, candidate_id=candidate_id)
        return review["cards"][0]

    @staticmethod
    def _store_bytes(paths) -> dict[str, bytes]:
        """Every candidate, record, and review-decision file, byte for byte."""
        return {
            str(path.relative_to(paths.memory_dir)): path.read_bytes()
            for name in ("candidates", "records", "reviews")
            for path in sorted((paths.memory_dir / name).glob("*.json"))
        }

    def _recapture_same_candidate_id(self, paths, candidate_id: str, summary: str) -> dict:
        """Overwrite one candidate id with a new payload, as a recapture does."""
        superseded = capture_project_memory_candidate(paths, summary, record_type="procedure")["candidate"]
        (paths.memory_dir / "candidates" / f"{superseded['candidate_id']}.json").unlink()
        replacement = {**superseded, "candidate_id": candidate_id}
        (paths.memory_dir / "candidates" / f"{candidate_id}.json").write_text(
            json.dumps(replacement), encoding="utf-8"
        )
        return replacement

    def test_stale_review_card_is_rejected_without_writes(self) -> None:
        # Given: a reviewer holding a card for a candidate that was recaptured
        # underneath them, so the id still resolves but the payload moved.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(
                paths, "Run the byte gates before every release", record_type="procedure"
            )
            candidate_id = str(captured["candidate"]["candidate_id"])
            stale_card = self._card(paths, candidate_id)
            self._recapture_same_candidate_id(paths, candidate_id, "Skip the byte gates when in a hurry")
            before = self._store_bytes(paths)

            # When: the held card's revision is submitted with the approval.
            with self.assertRaises(StaleMemoryReviewError) as approving:
                approve_project_memory_candidate(
                    paths, candidate_id, expected_revision=str(stale_card["review_revision"])
                )

            # Then: the review is refused as stale and nothing on disk moved.
            self.assertIn("stale_review", str(approving.exception))
            self.assertEqual(self._store_bytes(paths), before)
            self.assertFalse((paths.memory_dir / "records").exists())

    def test_matching_revision_approves_and_rejects(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            approving = capture_project_memory_candidate(paths, "Deploys go through staging first")["candidate"]
            rejecting = capture_project_memory_candidate(paths, "Deploys skip staging on Fridays")["candidate"]

            approved = approve_project_memory_candidate(
                paths,
                str(approving["candidate_id"]),
                expected_revision=str(self._card(paths, str(approving["candidate_id"]))["review_revision"]),
            )
            rejected = reject_project_memory_candidate(
                paths,
                str(rejecting["candidate_id"]),
                reason="contradicts the staging rule",
                expected_revision=str(self._card(paths, str(rejecting["candidate_id"]))["review_revision"]),
            )

            self.assertEqual(approved["decision"], "approved_manual")
            self.assertEqual(approved["candidate"]["status"], "approved")
            self.assertTrue((paths.memory_dir / "records" / f"{approved['record']['record_id']}.json").exists())
            self.assertEqual(rejected["decision"], "rejected")
            self.assertEqual(rejected["candidate"]["status"], "rejected")

    def test_recaptured_candidate_gets_a_new_revision_and_the_new_one_works(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(
                paths, "Run the byte gates before every release", record_type="procedure"
            )
            candidate_id = str(captured["candidate"]["candidate_id"])
            first_revision = str(self._card(paths, candidate_id)["review_revision"])
            self._recapture_same_candidate_id(paths, candidate_id, "Skip the byte gates when in a hurry")

            second_revision = str(self._card(paths, candidate_id)["review_revision"])
            approved = approve_project_memory_candidate(
                paths, candidate_id, expected_revision=second_revision
            )

            self.assertNotEqual(first_revision, second_revision)
            self.assertEqual(approved["record"]["summary"], "Skip the byte gates when in a hurry")

    def test_omitted_revision_still_approves_for_non_interactive_callers(self) -> None:
        # Migration safety: the in-process API keeps working without a revision;
        # only the interactive CLI path requires one.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(paths, "Deploys go through staging first")

            approved = approve_project_memory_candidate(paths, str(captured["candidate"]["candidate_id"]))

            self.assertEqual(approved["decision"], "approved_manual")

    def test_auto_safe_approval_binds_to_the_candidate_it_just_created(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")

            captured = capture_project_memory_candidate(
                paths, "Prefer docs workflow checks for generated workflow docs", record_type="procedure"
            )

            self.assertTrue(captured["auto_approved"])
            self.assertEqual(captured["candidate"]["status"], "approved")
            self.assertEqual(captured["record"]["schema_version"], "project_memory_record/v2")

    def test_replacement_between_check_and_write_cannot_slip_through(self) -> None:
        # Given: a reviewer approving with the revision their card showed, and
        # a concurrent recapture that replaces the payload under the same id.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(
                paths, "Run the byte gates before every release", record_type="procedure"
            )
            candidate_id = str(captured["candidate"]["candidate_id"])
            reviewed_revision = str(self._card(paths, candidate_id)["review_revision"])
            candidate_path = paths.memory_dir / "candidates" / f"{candidate_id}.json"
            replacement = {
                **json.loads(candidate_path.read_text(encoding="utf-8")),
                "summary": "Skip the byte gates when in a hurry",
            }
            # The recapture is a real mutator: it takes the store lock, as
            # every mutating memory path does. It is released at the door of
            # the approval's critical section and completes before the
            # approval acquires the lock, so the payload is already replaced
            # when the decision's protected section begins. A decision that
            # validated its revision before that point is working from a read
            # the store has since invalidated, and would approve text the
            # reviewer never saw; a decision that reads and validates inside
            # the lock sees the replacement and must refuse.
            approval_reached_lock = threading.Event()
            replacement_written = threading.Event()
            failures: list[BaseException] = []

            def replace_candidate() -> None:
                try:
                    self.assertTrue(approval_reached_lock.wait(timeout=10))
                    with file_lock(paths.memory_index_path, private=True):
                        candidate_path.write_text(json.dumps(replacement), encoding="utf-8")
                except BaseException as error:  # surfaced in the main thread
                    failures.append(error)
                finally:
                    replacement_written.set()

            real_lock = memory_workflow.file_lock

            @contextmanager
            def lock_once_the_replacement_is_durable(lock_path, **kwargs):
                approval_reached_lock.set()
                self.assertTrue(replacement_written.wait(timeout=10))
                with real_lock(lock_path, **kwargs) as held:
                    yield held

            writer = threading.Thread(target=replace_candidate)
            writer.start()
            try:
                # When: the approval submits the revision its card showed.
                with patch.object(
                    memory_workflow, "file_lock", lock_once_the_replacement_is_durable
                ):
                    with self.assertRaises(StaleMemoryReviewError) as approving:
                        approve_project_memory_candidate(
                            paths, candidate_id, expected_revision=reviewed_revision
                        )
            finally:
                approval_reached_lock.set()
                writer.join(timeout=10)
                self.assertFalse(writer.is_alive())
                self.assertEqual(failures, [])

            # Then: the decision is refused, and no record, review decision, or
            # candidate mutation was written on the payload nobody reviewed.
            self.assertIn("stale_review", str(approving.exception))
            self.assertFalse((paths.memory_dir / "records").exists())
            self.assertFalse((paths.memory_dir / "reviews").exists())
            stored = json.loads(candidate_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["status"], "pending_review")
            self.assertEqual(stored["summary"], replacement["summary"])

    def test_displayed_time_sensitivity_change_moves_the_revision(self) -> None:
        # Given: a candidate whose card displays a time-sensitivity warning --
        # the reviewer reads `detail` and `next_action` to decide whether the
        # relative-time phrase is acceptable, so both are decision inputs.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(paths, "The contract expires in 3 weeks")
            candidate_id = str(captured["candidate"]["candidate_id"])
            candidate_path = paths.memory_dir / "candidates" / f"{candidate_id}.json"
            before_card = self._card(paths, candidate_id)
            self.assertIn("time_sensitivity", before_card)

            # When: only the displayed time-sensitivity guidance is rewritten
            # under the same candidate id, leaving every other field alone.
            stored = json.loads(candidate_path.read_text(encoding="utf-8"))
            stored["time_sensitivity"] = {
                **stored["time_sensitivity"],
                "detail": "Superseded guidance: this deadline already passed and the fact now reads wrong.",
                "next_action": "Reject this candidate; do not approve it as-is.",
            }
            candidate_path.write_text(json.dumps(stored), encoding="utf-8")
            after_card = self._card(paths, candidate_id)

            # Then: the card shows different guidance, so the revision that
            # fingerprints it must have moved -- and the old card must be stale.
            self.assertNotEqual(after_card["time_sensitivity"], before_card["time_sensitivity"])
            self.assertNotEqual(after_card["review_revision"], before_card["review_revision"])
            with self.assertRaises(StaleMemoryReviewError):
                approve_project_memory_candidate(
                    paths, candidate_id, expected_revision=str(before_card["review_revision"])
                )

    def test_every_displayed_candidate_field_is_bound_to_the_revision(self) -> None:
        # Given: a rendered card and the exact set of fields it displays that
        # come from the candidate. Static labels (schema, actions, boundary)
        # are not candidate-derived, so they are not revision inputs.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(
                paths, "The audit window closes in 2 days", record_type="procedure", tags=["audit"]
            )
            candidate = dict(captured["candidate"])
            baseline_card = memory_workflow.build_project_memory_review_card(candidate)
            baseline_revision = memory_workflow.project_memory_review_revision(candidate)
            mutations: dict[str, dict] = {
                "summary": {"summary": "The audit window never closes"},
                "record_type": {"record_type": "constraint"},
                "scope": {"scope": {"kind": "project", "ref": "other-project"}},
                "tags": {"tags": ["unaudited"]},
                "created_at": {"created_at": "2999-12-31T23:59:59Z"},
                "duplicate_of": {"duplicate_of": "rec_previously_stored"},
                "safety.status": {"safety": {**candidate["safety"], "status": "blocked"}},
                "safety.extra": {"safety": {**candidate["safety"], "safe_to_auto_approve": True}},
                "time_sensitivity.detail": {
                    "time_sensitivity": {**candidate["time_sensitivity"], "detail": "different guidance"}
                },
                "time_sensitivity.next_action": {
                    "time_sensitivity": {**candidate["time_sensitivity"], "next_action": "reject it"}
                },
            }

            # When: each displayed field is mutated one at a time.
            unbound = []
            for name, patch in mutations.items():
                mutated = {**candidate, **patch}
                card_moved = memory_workflow.build_project_memory_review_card(mutated) != baseline_card
                revision_moved = (
                    memory_workflow.project_memory_review_revision(mutated) != baseline_revision
                )
                if card_moved and not revision_moved:
                    unbound.append(name)

            # Then: no field the card displays can change without the revision.
            self.assertEqual(unbound, [])

    def test_revision_is_metadata_only_and_never_carries_sensitive_content(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(
                paths,
                "Deploy runbook lives in the ops repo",
                content="password=hunter2-not-persisted",
            )
            candidate_id = str(captured["candidate"]["candidate_id"])

            card = self._card(paths, candidate_id)

            self.assertNotIn("hunter2-not-persisted", json.dumps(card))
            self.assertRegex(str(card["review_revision"]), r"^rev_[0-9a-f]{32}$")


class RetirementApplyTests(unittest.TestCase):
    def _seed(self, tmp: str, *, ttl_days: int = 5) -> tuple:
        paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
        write_setup_profile(paths, memory_mode="auto-safe")
        capture_project_memory_candidate(
            paths, "Retire apply fixture keeps release tests honest", record_type="procedure", tags=["release"], ttl_days=ttl_days
        )
        record = _read_only_record(paths)
        expires = datetime.fromisoformat(str(record["ttl"]["expires_at"]).replace("Z", "+00:00"))
        return paths, record, expires

    @staticmethod
    def _journal_lines(paths) -> list[dict]:
        journal = paths.memory_dir / "archive" / "retirements.jsonl"
        if not journal.exists():
            return []
        return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]

    @requires_posix_permissions
    def test_apply_moves_journals_and_updates_candidate_and_index(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, record, expires = self._seed(tmp)
            rid = record["record_id"]
            probe_now = expires + timedelta(days=1)
            payload = apply_memory_retirement(paths, now=probe_now)
            self.assertTrue(payload["applied"])
            records_dir = paths.memory_dir / "records"
            self.assertEqual(list(records_dir.glob("*.json")), [])
            compact = probe_now.replace(microsecond=0).isoformat().replace("+00:00", "Z").replace("-", "").replace(":", "")
            dest = paths.memory_dir / "archive" / f"{rid}.{compact}.json"
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            lines = self._journal_lines(paths)
            self.assertEqual(len(lines), 1)
            self.assertEqual(
                sorted(lines[0]),
                ["claim_boundary", "expires_at", "record_id", "redaction_policy", "retired_at", "schema_version"],
            )
            self.assertEqual(lines[0]["schema_version"], "omh_memory_retirement_journal/v1")
            self.assertEqual(lines[0]["record_id"], rid)
            index = json.loads((paths.memory_dir / "index.json").read_text(encoding="utf-8"))
            self.assertNotIn(f"records/{rid}.json", index["record_files"])
            candidates = [json.loads(p.read_text(encoding="utf-8")) for p in (paths.memory_dir / "candidates").glob("*.json")]
            self.assertEqual([c["status"] for c in candidates], ["retired"])

    def test_apply_double_retire_never_overwrites(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, record, expires = self._seed(tmp)
            first_now = expires + timedelta(days=1)
            apply_memory_retirement(paths, now=first_now)
            candidate_id = json.loads(next(iter((paths.memory_dir / "candidates").glob("*.json"))).read_text(encoding="utf-8"))["candidate_id"]
            approve_project_memory_candidate(paths, candidate_id, approved_by="user")
            second_now = first_now + timedelta(hours=1)
            apply_memory_retirement(paths, now=second_now)
            archives = sorted(p.name for p in (paths.memory_dir / "archive").glob("*.json"))
            self.assertEqual(len(archives), 2)
            self.assertEqual(len(self._journal_lines(paths)), 2)

    def test_apply_reconciles_crash_artifacts_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, record, expires = self._seed(tmp)
            rid = record["record_id"]
            probe_now = expires + timedelta(days=1)
            retired_at = probe_now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            compact = retired_at.replace("-", "").replace(":", "")
            archive_dir = paths.memory_dir / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            # simulate a crash immediately after os.replace: archive file exists, no journal, candidate approved
            os.replace(paths.memory_dir / "records" / f"{rid}.json", archive_dir / f"{rid}.{compact}.json")
            payload = apply_memory_retirement(paths, now=probe_now)
            reconciled = payload["reconciled"]
            self.assertEqual(len(reconciled), 1)
            lines = self._journal_lines(paths)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["retired_at"], retired_at)
            candidates = [json.loads(p.read_text(encoding="utf-8")) for p in (paths.memory_dir / "candidates").glob("*.json")]
            self.assertEqual([c["status"] for c in candidates], ["retired"])
            # partial crash: journal present but candidate flipped back (approved) - repair candidate only
            candidate_path = next(iter((paths.memory_dir / "candidates").glob("*.json")))
            partial = json.loads(candidate_path.read_text(encoding="utf-8"))
            partial["status"] = "approved"
            candidate_path.write_text(json.dumps(partial), encoding="utf-8")
            payload2 = apply_memory_retirement(paths, now=probe_now)
            self.assertEqual(len(payload2["reconciled"]), 1)
            self.assertEqual(len(self._journal_lines(paths)), 1)
            # idempotency: nothing left to repair
            payload3 = apply_memory_retirement(paths, now=probe_now)
            self.assertEqual(payload3["reconciled"], [])
            self.assertEqual(len(self._journal_lines(paths)), 1)

    def test_apply_blocks_until_store_lock_released(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, record, expires = self._seed(tmp)
            probe_now = expires + timedelta(days=1)
            order: list[str] = []
            lock_held = threading.Event()
            release = threading.Event()

            def holder() -> None:
                with file_lock(paths.memory_index_path, private=True):
                    lock_held.set()
                    release.wait(timeout=10)
                    order.append("released")

            def applier() -> None:
                apply_memory_retirement(paths, now=probe_now)
                order.append("applied")

            holder_thread = threading.Thread(target=holder)
            applier_thread = threading.Thread(target=applier)
            holder_thread.start()
            self.assertTrue(lock_held.wait(timeout=10))
            applier_thread.start()
            release.set()
            holder_thread.join(timeout=10)
            applier_thread.join(timeout=10)
            self.assertEqual(order, ["released", "applied"])

    def test_window_days_threads_through_apply(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, record, expires = self._seed(tmp, ttl_days=20)
            probe_now = expires - timedelta(days=10)  # not expired; expiring only inside a 30-day window
            payload = apply_memory_retirement(paths, now=probe_now, window_days=30)
            self.assertEqual(payload["window_days"], 30)
            self.assertEqual(payload["counts"]["expiring_soon"], 1)
            self.assertEqual(payload["counts"]["expired"], 0)
            self.assertEqual(len(list((paths.memory_dir / "records").glob("*.json"))), 1)
            self.assertEqual(self._journal_lines(paths), [])

    def test_apply_clears_expiring_only_brief_but_keeps_mixed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, record, expires = self._seed(tmp)
            probe_now = expires + timedelta(days=1)
            brief_path = paths.omh_home / "memory" / "consolidation.json"
            brief_path.parent.mkdir(parents=True, exist_ok=True)
            brief_path.write_text(
                json.dumps({"schema_version": "omh_memory_consolidation_handoff/v1", "due": True, "reasons": ["expiring_records:1"]}),
                encoding="utf-8",
            )
            apply_memory_retirement(paths, now=probe_now)
            cleared = json.loads(brief_path.read_text(encoding="utf-8"))
            self.assertFalse(cleared["due"])
            self.assertTrue(cleared.get("superseded_at"))

            brief_path.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_consolidation_handoff/v1",
                        "due": True,
                        "reasons": ["expiring_records:1", "context_compaction_observed"],
                    }
                ),
                encoding="utf-8",
            )
            apply_memory_retirement(paths, now=probe_now)
            mixed = json.loads(brief_path.read_text(encoding="utf-8"))
            self.assertTrue(mixed["due"])

    def test_status_counts_expired_records(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, record, expires = self._seed(tmp)
            record_path = paths.memory_dir / "records" / f"{record['record_id']}.json"
            mutated = json.loads(record_path.read_text(encoding="utf-8"))
            mutated["ttl"]["expires_at"] = "2020-01-01T00:00:00Z"
            mutated["retention"]["expires_at"] = "2020-01-01T00:00:00Z"
            _write_v2_record_with_matching_review(paths, record_path, mutated)
            status = build_project_memory_status(paths)
            self.assertEqual(status["counts"]["expired_records"], 1)



def _wrapper_snapshot(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "memory_snapshot/v1",
        "source": "wrapper_snapshot",
        "scope": {"kind": "project", "ref": "default"},
        "items": items,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Wrapper supplied memory candidates are not trusted until reviewed.",
    }


class UnreadableRecordVisibilityTests(unittest.TestCase):
    """A record this build cannot admit must be named, not lost.

    Failing closed on an unrecognized record is right. Failing closed silently
    is the defect: a v1 record without an approved review status and any record
    from a newer schema were dropped by the store reader with no count in
    `memory status` and nothing in `omh doctor`, so four files on disk read as
    two and a store that had quietly shrunk looked exactly like a smaller one.
    The forward case is the one that will happen -- the record schema has moved
    once already, and a shared `~/.omh` across two `omh` versions, a downgrade,
    or a half-finished migration all produce records this build refuses.
    """

    def _store(self, root: Path):
        paths = resolve_paths(root / ".omh", root / ".hermes")
        write_setup_profile(paths, memory_mode="auto-safe")
        capture_project_memory_candidate(paths, "api gateway timeout is 30 seconds", tags=["api"])
        records_dir = paths.memory_dir / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        base = {
            "record_type": "fact",
            "scope": {"kind": "project", "ref": "default"},
            "tags": ["api"],
            "source": "cli",
            "created_at": "2026-01-01T00:00:00Z",
            "approved_at": "2026-01-01T00:00:00Z",
            "ttl": {"ttl_days": None, "expires_at": ""},
        }
        for record_id, extra in (
            ("mem_v1approved", {"schema_version": "project_memory_record/v1", "review_status": "approved"}),
            ("mem_v1noreview", {"schema_version": "project_memory_record/v1"}),
            ("mem_futurev3", {"schema_version": "project_memory_record/v3"}),
        ):
            payload = {**base, **extra, "record_id": record_id, "summary": f"{record_id} fact"}
            (records_dir / f"{record_id}.json").write_text(json.dumps(payload), encoding="utf-8")
        (records_dir / "mem_corrupt.json").write_text("{", encoding="utf-8")
        return paths

    def test_every_record_file_is_accounted_for_by_status(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._store(Path(tmp))
            status = build_project_memory_status(paths)
            self.assertEqual(status["counts"]["unreadable_records"], 3)
            by_name = {item["path_name"]: item["reason"] for item in status["unreadable_records"]}
            self.assertEqual(by_name["mem_corrupt.json"], "unreadable_file")
            self.assertEqual(by_name["mem_futurev3.json"], "unsupported_record_schema")
            self.assertEqual(by_name["mem_v1noreview.json"], "legacy_review_status_missing")
            # The schema version is reported so an operator can tell a newer
            # OMH's record from a corrupt file without opening either.
            versions = {item["path_name"]: item["schema_version"] for item in status["unreadable_records"]}
            self.assertEqual(versions["mem_futurev3.json"], "project_memory_record/v3")

            # Nothing that used to be admitted stopped being admitted: the
            # approved v1 record still counts and still fails closed on replay.
            self.assertEqual(status["counts"]["approved_records"], 1)
            self.assertEqual(status["counts"]["review_required_legacy"], 1)

    def test_a_healthy_store_reports_nothing_unreadable(self) -> None:
        # Overroute guard: the count must stay zero for an ordinary store, or
        # it is noise an operator learns to ignore.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, memory_mode="auto-safe")
            capture_project_memory_candidate(paths, "a perfectly ordinary fact", tags=["api"])
            status = build_project_memory_status(paths)
            self.assertEqual(status["counts"]["unreadable_records"], 0)
            self.assertEqual(status["unreadable_records"], [])

    def test_doctor_names_the_files_it_cannot_admit(self) -> None:
        from omh.maintenance.doctor import run_doctor

        with TemporaryDirectory() as tmp:
            paths = self._store(Path(tmp))
            check = next(item for item in run_doctor(paths) if item.name == "memory_records")
            self.assertTrue(check.ok, "an unadmitted record is a thing to know, never a fault")
            self.assertEqual(check.severity, "warning")
            self.assertIn("mem_futurev3.json", check.message)
            self.assertIn("not admitted by this build", check.message)


class CallerSuppliedQueryIntentTests(unittest.TestCase):
    """Recency intent a non-English speaker can actually reach.

    `_TEMPORAL_QUERY_CUES` is English-only, so every non-English phrasing of
    "recently" resolved to `default` and never got the doubled recency weight:
    `어제 뭐 정했지`, `최근 배포 결정`, `3일 전에 정한 거`, `最近の変更`.

    Growing the cue table is the fix the routing-language policy exists to stop
    (`tests/test_routing_language_policy.py`): per-language trigger tables do
    not scale, and non-English intent resolution belongs to model selection
    over supplied candidates. So the caller states the intent instead -- Hermes
    read the message and knows, in any language.
    """

    def _store(self, root: Path):
        paths = resolve_paths(root / ".omh", root / ".hermes")
        write_setup_profile(paths, memory_mode="auto-safe")
        capture_project_memory_candidate(paths, "배포는 블루그린 방식으로 적용한다", tags=["deploy"])
        return paths

    def test_a_stated_intent_reaches_the_pack_in_any_language(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._store(Path(tmp))
            for query in ("어제 뭐 정했지", "最近の変更", "3일 전에 정한 거", ""):
                with self.subTest(query):
                    derived = build_project_memory_recall_pack(paths, query)
                    self.assertEqual(derived["query_intent"], "default")
                    stated = build_project_memory_recall_pack(paths, query, query_intent="temporal")
                    self.assertEqual(stated["query_intent"], "temporal")
                    self.assertEqual(validate_project_memory_recall_pack(stated), [])

    def test_the_english_cue_table_still_answers_when_nothing_is_stated(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._store(Path(tmp))
            for query, expected in (("recent changes", "temporal"), ("the most recent deploy", "temporal"),
                                    ("deploy strategy", "default"), ("배포 방식", "default")):
                with self.subTest(query):
                    self.assertEqual(build_project_memory_recall_pack(paths, query)["query_intent"], expected)
                    # `auto` is the same thing said out loud.
                    self.assertEqual(
                        build_project_memory_recall_pack(paths, query, query_intent="auto")["query_intent"], expected
                    )

    def test_a_stated_default_overrides_an_english_cue(self) -> None:
        # The caller read the message; a cue word inside it does not outrank
        # that. "recent" appears here and the caller says it is not the point.
        with TemporaryDirectory() as tmp:
            paths = self._store(Path(tmp))
            pack = build_project_memory_recall_pack(paths, "recent deploy strategy", query_intent="default")
            self.assertEqual(pack["query_intent"], "default")

    def test_an_unrecognized_intent_is_refused_not_ignored(self) -> None:
        # A caller that misspells its intent should learn that, rather than
        # silently receive the default ranking it did not ask for.
        with TemporaryDirectory() as tmp:
            paths = self._store(Path(tmp))
            with self.assertRaises(ValueError):
                build_project_memory_recall_pack(paths, "배포", query_intent="recent")

    def test_intent_reorders_peers_and_never_changes_what_matches(self) -> None:
        # The whole reason this is safe: intent only weights recency inside
        # rank fusion. If it could change the matched set it would be a
        # second, undeclared, retrieval policy.
        with TemporaryDirectory() as tmp:
            paths = self._store(Path(tmp))
            capture_project_memory_candidate(paths, "결제 실패가 나면 즉시 롤백한다", tags=["payment"])
            default = build_project_memory_recall_pack(paths, "배포")
            temporal = build_project_memory_recall_pack(paths, "배포", query_intent="temporal")
            self.assertEqual(
                {item["record_id"] for item in default["included_records"]},
                {item["record_id"] for item in temporal["included_records"]},
            )

if __name__ == "__main__":
    unittest.main()
