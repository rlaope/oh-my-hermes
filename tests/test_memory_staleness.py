"""Stale project memory must announce itself before it steers anything.

Issue #830. Three contracts, in the order a record meets them:

1. A recall pack bound for a handoff names every record whose freshness is
   unconfirmed, instead of quietly shrinking. Silence was the defect.
2. Correcting or superseding a record keeps the prior revision and its
   provenance, including the digest of the source it cited.
3. Freshness is a function of stored metadata, the caller's ``now``, and
   locally observable source bytes -- nothing else. Unknown never reads fresh.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.local_store import atomic_write_text
from omh.memory import (
    approve_project_memory_candidate,
    build_project_memory_recall_pack,
    capture_project_memory_candidate,
    memory_recall_pack_for_handoff,
    validate_project_memory_record,
    validate_project_memory_recall_pack,
)
from project_identity_fixture import memory_paths as resolve_paths
from omh.workflows import memory as memory_workflow
from omh.workflows.memory_lifecycle import (
    apply_memory_correction,
    apply_memory_reapproval,
    apply_memory_restore,
    apply_memory_retirement,
    build_memory_correction,
    build_memory_reapproval,
    build_memory_restore,
    build_memory_retirement,
)
from omh.workflows.memory_lifecycle_executor import execute_memory_lifecycle
from omh.runtime.artifacts import _memory_recall_pack_summary as artifact_pack_summary
from omh.wrapper.briefing import _memory_recall_pack_summary as briefing_pack_summary
from omh.wrapper.continuity import _warning_count as continuity_warning_count

PAST = "2020-01-01T00:00:00Z"


def _approved(paths, summary: str, **capture) -> dict:
    captured = capture_project_memory_candidate(paths, summary, **capture)
    return approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]


def _record_path(paths, record_id: str) -> Path:
    return paths.memory_dir / "records" / f"{record_id}.json"


def _mutate_record(paths, record_id: str, **fields) -> dict:
    """Rewrite a stored record's non-digested metadata.

    ``canonical_payload_digest`` covers schema/id/revision/type/summary/scope
    only, so deadlines and source evidence can be edited without invalidating
    the admission digest or its review record.
    """
    path = _record_path(paths, record_id)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored.update(fields)
    atomic_write_text(path, json.dumps(stored), private=True)
    return stored


def _source_file(root: Path, name: str, body: str) -> Path:
    path = root / name
    # atomic_write_text, never Path.write_text: these bytes are hashed, and
    # Path.write_text would newline-translate them to CRLF on Windows, which
    # would make the same fixture digest differently per platform.
    atomic_write_text(path, body)
    return path


class HandoffFreshnessWarningTests(unittest.TestCase):
    """AC1: warn before a stale or expired record influences a handoff."""

    def test_handoff_pack_names_the_stale_record_instead_of_dropping_it(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "Release notes ship from the changelog", record_type="decision")
            _mutate_record(
                paths,
                record["record_id"],
                revalidation={"deadline": PAST},
                staleness={"stale_after": PAST, "stale_after_days": None, "review_due_at": PAST},
            )

            pack = memory_recall_pack_for_handoff(paths, "release notes changelog", executor_target="codex")

            self.assertIsNotNone(pack, "a stale-only pack must still reach the handoff as a warning")
            assert pack is not None
            self.assertEqual(pack["record_count"], 0, "a stale record is never promoted into the handoff")
            self.assertEqual(pack["included_records"], [])
            [warning] = pack["freshness_warnings"]
            self.assertEqual(warning["record_id"], record["record_id"])
            self.assertEqual(warning["state"], "stale")
            self.assertEqual(warning["reason_code"], "stale_review_required")
            self.assertEqual(warning["review_due_at"], PAST)
            self.assertFalse(warning["delivered"], "the warning says the record was held back")
            self.assertIn("revalidation deadline passed", warning["detail"])
            self.assertIn("Confirm, replace, or retire", warning["next_action"])
            self.assertEqual(validate_project_memory_recall_pack(pack), [])

    def test_expired_records_warn_too_and_stay_out_of_the_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "Nightly job runs at 02:00 UTC", ttl_days=5)
            expires_at = datetime.fromisoformat(str(record["ttl"]["expires_at"]).replace("Z", "+00:00"))

            pack = build_project_memory_recall_pack(paths, "nightly job", now=expires_at + timedelta(days=1))

            self.assertEqual(pack["record_count"], 0)
            [warning] = pack["freshness_warnings"]
            self.assertEqual(warning["record_id"], record["record_id"])
            self.assertEqual(warning["state"], "expired")
            self.assertEqual(warning["reason_code"], "expired_standard")

    def test_fresh_records_produce_no_warning_noise(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approved(paths, "Docs gates are byte-exact comparisons")
            _approved(paths, "Unrelated note about branch naming")

            pack = build_project_memory_recall_pack(paths, "docs gates")

            self.assertEqual(pack["record_count"], 1)
            self.assertEqual(
                pack["freshness_warnings"],
                [],
                "a record cut for no query overlap is not a freshness problem",
            )

    def test_include_stale_delivers_the_record_and_still_warns(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "CI runner image is ubuntu-24.04")
            _mutate_record(
                paths,
                record["record_id"],
                revalidation={"deadline": PAST},
                staleness={"stale_after": PAST, "stale_after_days": None, "review_due_at": PAST},
            )

            pack = build_project_memory_recall_pack(paths, "ci runner ubuntu", include_stale=True)

            [item] = pack["included_records"]
            self.assertFalse(item["replay_evaluation"]["eligible"], "inspection never launders eligibility")
            [warning] = pack["freshness_warnings"]
            self.assertTrue(warning["delivered"], "a surfaced stale record still carries its warning")
            self.assertEqual(warning["reason_code"], "stale_review_required")

    def test_the_warning_survives_delegation_and_its_brief(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "Coverage gate sits at 80 percent")
            _mutate_record(
                paths,
                record["record_id"],
                revalidation={"deadline": PAST},
                staleness={"stale_after": PAST, "stale_after_days": None, "review_due_at": PAST},
            )
            pack = memory_recall_pack_for_handoff(paths, "coverage gate percent", executor_target="codex")
            assert pack is not None

            for name, summarize in (("wrapper brief", briefing_pack_summary), ("runtime artifact", artifact_pack_summary)):
                with self.subTest(surface=name):
                    summary = summarize(pack)
                    self.assertEqual(
                        [entry["record_id"] for entry in summary["freshness_warnings"]],
                        [record["record_id"]],
                        "a summary that drops the warning puts the user back where they started",
                    )
                    self.assertEqual(summary["record_count"], 0)

    def test_a_pack_with_nothing_to_say_is_still_omitted_from_the_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "Branch names start with agent or claude")
            # Reference tier: a query that matches nothing re-admits only the
            # active tier, so an active record would give this pack something to say.
            memory_workflow.apply_memory_attention_change(paths, record["record_id"], tier="reference")

            self.assertIsNone(
                memory_recall_pack_for_handoff(paths, "wholly unrelated payment gateway topic"),
                "no records and no warnings means no pack; warnings must not fabricate one",
            )


class SupersessionProvenanceTests(unittest.TestCase):
    """AC2: revalidating or superseding preserves the prior revision."""

    def test_correction_writes_the_prior_revision_with_its_supersession_link(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "deploy.md", "staging first\n")
            record = _approved(paths, "Deploys go through staging first", record_type="decision", source_ref=str(source))
            now = datetime.now(timezone.utc)

            plan = build_memory_correction(paths, record["record_id"], 1, "Deploys go staging, then canary", now=now)
            apply_memory_correction(paths, plan, transaction_executor=execute_memory_lifecycle)

            history = json.loads(
                (paths.memory_dir / "history" / f"{record['record_id']}.r1.json").read_text(encoding="utf-8")
            )
            self.assertEqual(history["revision"], 1, "the prior revision is preserved verbatim, not rewritten")
            self.assertEqual(history["summary"], record["summary"])
            self.assertEqual(history["admission"], record["admission"], "its approval provenance survives")
            self.assertEqual(history["source_evidence"], record["source_evidence"])
            self.assertEqual(
                history["superseded_by"],
                {
                    "schema_version": "project_memory_record/v2",
                    "id": record["record_id"],
                    "id_key": "record_id",
                    "revision": 2,
                    "scope": record["scope"],
                },
            )
            self.assertEqual(
                validate_project_memory_record(history),
                [],
                "the superseded copy is a valid record, so supersession is a first-class record state",
            )

    def test_a_live_record_marked_superseded_is_refused_and_warned_about(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "Config lives in pyproject.toml")
            _mutate_record(
                paths,
                record["record_id"],
                superseded_by={
                    "schema_version": "project_memory_record/v2",
                    "id": record["record_id"],
                    "id_key": "record_id",
                    "revision": 2,
                    "scope": record["scope"],
                },
            )

            pack = build_project_memory_recall_pack(paths, "pyproject config")

            self.assertEqual(pack["record_count"], 0)
            [warning] = pack["freshness_warnings"]
            self.assertEqual(warning["reason_code"], "superseded")
            self.assertIn("newer revision supersedes", warning["detail"])

    def test_source_evidence_survives_capture_approve_correct_reapprove(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "runbook.md", "restart the worker\n")
            record = _approved(paths, "Worker restarts are manual", source_ref=str(source))
            now = datetime.now(timezone.utc)

            plan = build_memory_correction(paths, record["record_id"], 1, "Worker restarts are scripted", now=now)
            apply_memory_correction(paths, plan, transaction_executor=execute_memory_lifecycle)
            candidate = next(
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((paths.memory_dir / "candidates").glob("*.json"))
                if json.loads(path.read_text(encoding="utf-8")).get("lifecycle") == "correction"
            )
            self.assertEqual(candidate["replacement"]["source_evidence"], record["source_evidence"])

            reapproval = build_memory_reapproval(paths, candidate["candidate_id"], reviewer_claim="operator", now=now)
            apply_memory_reapproval(paths, reapproval, transaction_executor=execute_memory_lifecycle)

            live = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            self.assertEqual(live["revision"], 2)
            self.assertEqual(
                live["source_evidence"],
                record["source_evidence"],
                "a corrected revision keeps watching the same source; otherwise one correction blinds it forever",
            )

    def test_source_evidence_survives_retire_and_restore(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "policy.md", "two reviewers\n")
            record = _approved(paths, "Merges need two reviewers", ttl_days=30, source_ref=str(source))
            later = datetime.now(timezone.utc) + timedelta(days=60)

            retire = build_memory_retirement(paths, record["record_id"], 1, now=later)
            apply_memory_retirement(paths, retire, transaction_executor=execute_memory_lifecycle)
            restore = build_memory_restore(paths, record["record_id"], 1, now=later)
            apply_memory_restore(paths, restore, transaction_executor=execute_memory_lifecycle)
            candidate_id = str(restore.mutations[0].payload["candidate_id"])
            reapproval = build_memory_reapproval(paths, candidate_id, reviewer_claim="operator", now=later)
            apply_memory_reapproval(paths, reapproval, transaction_executor=execute_memory_lifecycle)

            live = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            self.assertEqual(live["revision"], 2)
            self.assertEqual(live["source_evidence"], record["source_evidence"])


class DeterministicFreshnessTests(unittest.TestCase):
    """AC3: freshness derives from stored metadata and observable source bytes."""

    def test_the_same_metadata_and_now_always_yield_the_same_verdict(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "gate.md", "byte exact\n")
            record = _approved(paths, "Doc gates compare bytes", source_ref=str(source))
            stored = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            probe = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)

            verdicts = [memory_workflow._record_staleness(stored, now=probe) for _ in range(3)]

            self.assertEqual(verdicts[0], verdicts[1])
            self.assertEqual(verdicts[1], verdicts[2])
            self.assertEqual(verdicts[0]["state"], "fresh")
            self.assertEqual(verdicts[0]["source_state"], "unchanged")

    def test_a_changed_source_digest_flips_the_state_and_nothing_else_does(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "schema.md", "one field\n")
            record = _approved(paths, "The schema has one field", source_ref=str(source))
            stored = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            probe = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
            self.assertEqual(memory_workflow._record_staleness(stored, now=probe)["state"], "fresh")

            _source_file(root, "schema.md", "two fields\n")

            after = memory_workflow._record_staleness(stored, now=probe)
            self.assertEqual(after["state"], "stale", "the cited source moved, so the record is due for review")
            self.assertEqual(after["reason"], "source_changed")
            self.assertEqual(after["source_state"], "changed")

    def test_an_unreadable_source_is_unknown_and_never_fresh(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "vanishing.md", "here for now\n")
            record = _approved(paths, "The vanishing note still applies", source_ref=str(source))
            stored = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            probe = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)

            source.unlink()

            verdict = memory_workflow._record_staleness(stored, now=probe)
            self.assertEqual(verdict["state"], "unknown")
            self.assertNotEqual(verdict["state"], "fresh")
            self.assertEqual(verdict["reason"], "source_unreadable")
            self.assertEqual(verdict["source_state"], "unreadable")

    def test_a_source_that_moved_is_kept_out_of_recall_and_named(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "owners.md", "team alpha owns it\n")
            record = _approved(paths, "Team alpha owns the parser", source_ref=str(source))
            self.assertEqual(build_project_memory_recall_pack(paths, "parser owner")["record_count"], 1)

            _source_file(root, "owners.md", "team beta owns it\n")

            pack = build_project_memory_recall_pack(paths, "parser owner")
            self.assertEqual(pack["record_count"], 0, "a source-moved record is never silently promoted")
            [excluded] = [entry for entry in pack["excluded_records"] if entry["record_id"] == record["record_id"]]
            self.assertEqual(excluded["reason"], "source_changed")
            [warning] = pack["freshness_warnings"]
            self.assertEqual(warning["reason_code"], "source_changed")
            self.assertIn("local source it cites changed", warning["detail"])

    def test_an_unverifiable_source_is_kept_out_of_recall_and_named(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = _source_file(root, "gone.md", "still here\n")
            record = _approved(paths, "The parser rejects empty input", source_ref=str(source))

            source.unlink()

            pack = build_project_memory_recall_pack(paths, "parser empty input")
            self.assertEqual(pack["record_count"], 0, "unknown freshness must never read as approved context")
            [warning] = pack["freshness_warnings"]
            self.assertEqual(warning["record_id"], record["record_id"])
            self.assertEqual(warning["state"], "unknown")
            self.assertEqual(warning["reason_code"], "source_unverifiable")

    def test_only_an_absolute_local_path_earns_source_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            _source_file(root, "relative.md", "content\n")

            for source_ref in ("relative.md", "PR #123", str(root / "absent.md"), str(root)):
                with self.subTest(source_ref=source_ref):
                    captured = capture_project_memory_candidate(paths, f"Note about {source_ref}", source_ref=source_ref)
                    self.assertNotIn(
                        "source_evidence",
                        captured["candidate"],
                        "a ref OMH cannot digest locally carries no evidence and stays deadline-only",
                    )

    def test_review_due_at_names_the_date_stale_after_already_held(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            record = _approved(paths, "Router triggers need a negative case", stale_after_days=90)

            self.assertEqual(record["staleness"]["review_due_at"], record["staleness"]["stale_after"])
            self.assertTrue(record["staleness"]["review_due_at"])
            verdict = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc))
            self.assertEqual(verdict["review_due_at"], record["staleness"]["stale_after"])

    def test_editing_only_one_deadline_spelling_cannot_restore_freshness(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "Only one spelling was edited")
            future = "2099-01-01T00:00:00Z"

            for edited in ({"stale_after": PAST, "review_due_at": future}, {"stale_after": future, "review_due_at": PAST}):
                with self.subTest(**edited):
                    stored = _mutate_record(paths, record["record_id"], staleness={**edited, "stale_after_days": None})
                    verdict = memory_workflow._record_staleness(stored, now=datetime.now(timezone.utc))
                    self.assertEqual(verdict["state"], "stale", "the deadline that already passed decides")
                    self.assertEqual(verdict["review_due_at"], PAST)

    def test_a_legacy_record_without_review_due_at_keeps_its_deadline(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "Older record written before the field was named")
            stored = _mutate_record(
                paths,
                record["record_id"],
                staleness={"stale_after": PAST, "stale_after_days": None},
            )

            verdict = memory_workflow._record_staleness(stored, now=datetime.now(timezone.utc))

            self.assertEqual(verdict["state"], "stale")
            self.assertEqual(verdict["review_due_at"], PAST, "the old spelling still supplies the deadline")


class RetentionDayBoundsTests(unittest.TestCase):
    """A deadline nobody meant must be refused, not reinterpreted.

    The `>= 1` guard lived only in the argparse layer, so the CLI rejected
    `--ttl-days 0` and `--ttl-days -5` while `capture_project_memory_candidate`
    behind it accepted both from the plugin bundle, the wrapper, or any other
    caller. There was no upper bound anywhere, and a large value reached
    `created_at + timedelta(days=N)`, whose OverflowError is not a ValueError
    and so escaped the CLI's error handling as a raw Python traceback.
    """

    def _capture(self, paths, **kwargs):
        return capture_project_memory_candidate(paths, "retention bound probe", **kwargs)

    def test_zero_and_negative_day_counts_are_refused_at_the_workflow_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for field, kwargs in (("ttl_days", {"ttl_days": 0}), ("ttl_days", {"ttl_days": -5}),
                                  ("stale_after_days", {"stale_after_days": 0}),
                                  ("stale_after_days", {"stale_after_days": -5})):
                with self.subTest(str(kwargs)):
                    with self.assertRaises(ValueError) as caught:
                        self._capture(paths, **kwargs)
                    self.assertIn(field, str(caught.exception))

    def test_an_unbounded_day_count_is_a_value_error_not_an_overflow(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for days in (memory_workflow.MAX_RETENTION_DAYS + 1, 10**9, 10**12):
                with self.subTest(days):
                    with self.assertRaises(ValueError):
                        self._capture(paths, ttl_days=days)

    def test_the_longest_expressible_deadline_is_accepted(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = self._capture(paths, ttl_days=memory_workflow.MAX_RETENTION_DAYS)
            self.assertTrue(captured["candidate"]["ttl"]["expires_at"])

    def test_no_ttl_still_means_a_record_that_never_expires(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            candidate = self._capture(paths, record_type="fact")["candidate"]
            self.assertEqual(candidate["ttl"], {"ttl_days": None, "expires_at": ""})
            # An episode keeps its 30-day default rather than inheriting None.
            episode = capture_project_memory_candidate(paths, "episode bound probe", record_type="episode")
            self.assertEqual(episode["candidate"]["ttl"]["ttl_days"], 30)
            self.assertTrue(episode["candidate"]["ttl"]["expires_at"])

    def test_a_candidate_and_its_approved_record_state_the_same_deadline(self) -> None:
        # `ttl_days=0` used to produce a candidate reading `expires_at: ""`
        # (never expires) and a record reading `expires_at == created_at`
        # (expired on arrival). A reviewer approved one and got the other.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for kwargs in ({}, {"ttl_days": 7}, {"record_type": "episode"}, {"ttl_days": 1}):
                with self.subTest(str(kwargs)):
                    captured = capture_project_memory_candidate(paths, f"parity probe {kwargs}", **kwargs)
                    candidate = captured["candidate"]
                    record = approve_project_memory_candidate(paths, str(candidate["candidate_id"]))["record"]
                    self.assertEqual(candidate["ttl"]["expires_at"], record["ttl"]["expires_at"])
                    self.assertEqual(candidate["ttl"]["ttl_days"], record["ttl"]["ttl_days"])

    def test_approval_keeps_the_candidate_deadline_across_a_clock_boundary(self) -> None:
        captured_at = "2026-08-13T12:00:00Z"
        approved_at = "2026-08-13T12:00:01Z"
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            memory_workflow.read_project_memory_policy(paths)
            with patch.object(
                memory_workflow, "utc_now", side_effect=(captured_at, captured_at, approved_at, approved_at)
            ):
                candidate = self._capture(paths, ttl_days=7)["candidate"]
                record = approve_project_memory_candidate(paths, str(candidate["candidate_id"]))["record"]

        self.assertEqual(candidate["ttl"]["expires_at"], "2026-08-20T12:00:00Z")
        self.assertEqual(record["ttl"]["expires_at"], candidate["ttl"]["expires_at"])


class DurableRecordsAreActuallyPermanentTests(unittest.TestCase):
    """`durable` is the class for a record that does not expire. It has to mean it.

    The 90-day review default keyed off `record_type` alone, so a durable
    record read `stale/review_due` after 90 days and carried a freshness
    warning into every recall from then on -- identical to a standard record,
    which made declaring one durable buy nothing. `build_retention` had always
    said otherwise ("durable: no default expiry; revalidation deadline is
    optional"); the staleness layer never read the class.

    The only escape was to guess a large `stale_after_days`. With zero and
    negative counts refused and `None` meaning "apply the type default", there
    was no value that meant *no review deadline*.
    """

    LATER = timedelta(days=100)

    def _record(self, paths, summary: str, **kwargs):
        captured = capture_project_memory_candidate(paths, summary, **kwargs)
        return approve_project_memory_candidate(paths, str(captured["candidate"]["candidate_id"]))["record"]

    def test_a_durable_record_never_falls_due_for_review_on_its_own(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for record_type in ("fact", "decision", "lesson", "procedure"):
                with self.subTest(record_type):
                    record = self._record(paths, f"durable {record_type}", record_type=record_type, retention_class="durable")
                    self.assertEqual(record["staleness"]["review_due_at"], "")
                    self.assertEqual(record["staleness"]["stale_after"], "")
                    state = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc) + self.LATER)
                    self.assertEqual(state["state"], "fresh")

    def test_a_durable_record_still_honours_a_deadline_it_was_given(self) -> None:
        # The class says the deadline is optional, not forbidden.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = self._record(paths, "durable but worth rereading", retention_class="durable", stale_after_days=30)
            self.assertTrue(record["staleness"]["review_due_at"])
            state = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc) + self.LATER)
            self.assertEqual((state["state"], state["reason"]), ("stale", "review_due"))

    def test_standard_and_volatile_records_keep_their_deadlines(self) -> None:
        # Overroute guard: the fix must not quietly make everything permanent.
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for label, kwargs, expected in (
                ("standard fact", {}, "review_due"),
                ("standard decision", {"record_type": "decision"}, "review_due"),
                # Volatile carries a review date too, but a 7-day TTL reaches it
                # first and expiry outranks review-due in the one verdict.
                ("volatile fact", {"retention_class": "volatile"}, "retention_expired"),
            ):
                with self.subTest(label):
                    record = self._record(paths, f"{label} keeps its deadline", **kwargs)
                    self.assertTrue(record["staleness"]["review_due_at"], "a non-durable record keeps its review date")
                    state = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc) + self.LATER)
                    self.assertEqual(state["reason"], expected)

    def test_a_durable_record_is_not_an_immortal_one_by_accident(self) -> None:
        # Durable removes the review prompt, never the other freshness checks:
        # a moved or unreadable cited source still lowers trust.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            source = root / "cited.md"
            atomic_write_text(source, "the original claim\n")
            record = self._record(paths, "durable with a cited source", retention_class="durable", source_ref=str(source))
            self.assertEqual(memory_workflow._record_staleness(record)["state"], "fresh")
            atomic_write_text(source, "the claim, edited\n")
            changed = memory_workflow._record_staleness(record)
            self.assertEqual((changed["state"], changed["reason"]), ("stale", "source_changed"))


class ReviewDueSoonWarningTests(unittest.TestCase):
    """A record announces its deadline while confirming still keeps recall intact."""

    def test_a_delivered_record_warns_inside_the_pre_deadline_window(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "staging runs postgres 15", tags=["staging"])
            probe = datetime.now(timezone.utc) + timedelta(days=80)  # 10 days before the 90-day deadline
            pack = build_project_memory_recall_pack(paths, "postgres staging", now=probe)
            self.assertEqual(pack["record_count"], 1)
            self.assertEqual(validate_project_memory_recall_pack(pack), [])
            warnings = pack["freshness_warnings"]
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0]["record_id"], record["record_id"])
            self.assertEqual(warnings[0]["reason_code"], "review_due_soon")
            self.assertTrue(warnings[0]["delivered"])
            self.assertIn("omh memory confirm", warnings[0]["next_action"])

    def test_outside_the_window_and_undelivered_records_stay_silent(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approved(paths, "staging runs postgres 15", tags=["staging"])
            _approved(paths, "we lint with ruff", tags=["lint"])
            quiet = build_project_memory_recall_pack(
                paths, "postgres staging", now=datetime.now(timezone.utc) + timedelta(days=60)
            )
            self.assertEqual(quiet["freshness_warnings"], [])
            # Inside the window, the record this query never delivered stays
            # silent: due-soon is advance notice about the pack's own content,
            # not a store-wide page.
            windowed = build_project_memory_recall_pack(
                paths, "postgres staging", now=datetime.now(timezone.utc) + timedelta(days=80)
            )
            self.assertEqual(
                [warning["reason_code"] for warning in windowed["freshness_warnings"]],
                ["review_due_soon"],
            )
            self.assertTrue(windowed["freshness_warnings"][0]["delivered"])

    def test_the_window_boundaries_are_exact(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            _approved(paths, "staging runs postgres 15", tags=["staging"])
            base = datetime.now(timezone.utc)
            outside = build_project_memory_recall_pack(paths, "postgres staging", now=base + timedelta(days=75))
            self.assertEqual(outside["freshness_warnings"], [])
            inside = build_project_memory_recall_pack(paths, "postgres staging", now=base + timedelta(days=76))
            self.assertEqual([w["reason_code"] for w in inside["freshness_warnings"]], ["review_due_soon"])
            past = build_project_memory_recall_pack(paths, "postgres staging", now=base + timedelta(days=91))
            self.assertEqual(past["record_count"], 0)
            self.assertEqual([w["reason_code"] for w in past["freshness_warnings"]], ["stale_review_required"])
            self.assertFalse(past["freshness_warnings"][0]["delivered"])

    def test_advisory_notices_never_displace_blocking_warnings(self) -> None:
        # Synthetic pack entries, driven straight through the warning builder:
        # 12 delivered due-soon notices would fill the budget on their own,
        # and the one record that actually left the pack must still be named.
        advisory_entries = [
            {
                "record_id": f"mem_advisory{index:02d}",
                "eligibility_reason": "eligible",
                "staleness": {"state": "fresh", "reason": "review_due_soon", "review_due_at": "2099-01-01T00:00:00Z"},
            }
            for index in range(12)
        ]
        held_back = [
            {
                "record_id": "mem_heldback",
                "eligibility_reason": "stale_review_required",
                "staleness": {"state": "stale", "reason": "review_due", "review_due_at": PAST},
            }
        ]
        warnings = memory_workflow._freshness_warnings(advisory_entries, held_back)
        self.assertLessEqual(len(warnings), 12)
        self.assertEqual(warnings[0]["record_id"], "mem_heldback")
        self.assertEqual(warnings[0]["reason_code"], "stale_review_required")

    def test_wrapper_continuity_does_not_count_advisory_notices(self) -> None:
        self.assertEqual(
            continuity_warning_count(
                {"freshness_warnings": [{"reason_code": "review_due_soon"}, {"reason_code": "stale_review_required"}]}
            ),
            1,
        )
        self.assertEqual(
            continuity_warning_count({"freshness_warnings": [{"reason_code": "review_due_soon"}]}),
            0,
        )
        # An explicit producer count and unknown warning shapes stay untouched:
        # both fail toward warning, never toward silence.
        self.assertEqual(continuity_warning_count({"freshness_warning_count": 3}), 3)
        self.assertEqual(continuity_warning_count({"freshness_warnings": ["not-a-mapping"]}), 1)


class AbsoluteDeadlineTests(unittest.TestCase):
    """Deadlines as dates, not day counts: 'the 18th', anchored once, exactly."""

    def test_an_absolute_review_date_lands_verbatim_and_reads_explicit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            future = (datetime.now(timezone.utc) + timedelta(days=23)).date().isoformat()
            captured = capture_project_memory_candidate(paths, "vendor contract renewal due", stale_after=future)
            self.assertEqual(captured["candidate"]["staleness"]["cadence_source"], "explicit")
            record = approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]
            # A bare date means the START of that UTC day -- review-due the
            # moment the 18th begins, never quietly late on its last second.
            self.assertEqual(record["staleness"]["review_due_at"], f"{future}T00:00:00Z")
            self.assertIsNone(record["staleness"]["stale_after_days"])

    def test_an_absolute_expiry_survives_approval_and_gates_recall(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            future = (datetime.now(timezone.utc) + timedelta(days=23)).date().isoformat()
            captured = capture_project_memory_candidate(paths, "promo code FALL26 is valid", tags=["promo"], expires_at=future)
            record = approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]
            # `build_retention` cannot re-derive a date it was never handed a
            # day count for; approval must carry the candidate's date over.
            self.assertEqual(record["retention"]["expires_at"], f"{future}T00:00:00Z")
            self.assertEqual(record["ttl"]["expires_at"], f"{future}T00:00:00Z")
            edge = datetime.fromisoformat(f"{future}T00:00:00+00:00")
            before = build_project_memory_recall_pack(paths, "promo code", now=edge - timedelta(seconds=1))
            after = build_project_memory_recall_pack(paths, "promo code", now=edge)
            self.assertEqual((before["record_count"], after["record_count"]), (1, 0))

    def test_an_absolute_review_date_survives_a_durable_reclass(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            future = (datetime.now(timezone.utc) + timedelta(days=15)).date().isoformat()
            captured = capture_project_memory_candidate(paths, "date-pinned but durable", stale_after=future)
            record = approve_project_memory_candidate(
                paths, captured["candidate"]["candidate_id"], retention_class="durable"
            )["record"]
            # Explicit is explicit in either shape: the reviewer saw this
            # date on the card, and a flag about retention must not drop it.
            self.assertEqual(record["retention"].get("class"), "durable")
            self.assertEqual(record["staleness"]["review_due_at"], f"{future}T00:00:00Z")
            self.assertEqual(record["revalidation"].get("deadline"), f"{future}T00:00:00Z")

    def test_workflow_class_gates_refuse_durable_ttl_and_volatile_cadence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            # The workflow is the plugin-bundle-facing API; these gates must
            # not live only in argparse. A durable candidate carrying a TTL
            # is exactly how a "never expires" record once learned to expire.
            with self.assertRaises(ValueError):
                capture_project_memory_candidate(paths, "durable with ttl", retention_class="durable", ttl_days=10)
            with self.assertRaises(ValueError):
                capture_project_memory_candidate(paths, "volatile with cadence", retention_class="volatile", stale_after_days=5)
            # Day-count carry-over parity is untouched: a standard fact with
            # an explicit TTL keeps its capture-time deadline at approval.
            captured = capture_project_memory_candidate(paths, "standard with ttl", ttl_days=10)
            record = approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]
            self.assertEqual(record["retention"]["expires_at"], captured["candidate"]["ttl"]["expires_at"])

    def test_an_absolute_expiry_scales_its_advance_notice_window_too(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            near = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
            captured = capture_project_memory_candidate(paths, "two-day absolute note", expires_at=near)
            record = approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]
            verdict = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc))
            # A 2-day absolute deadline must not warn from birth any more
            # than a 2-day TTL would; the span derives from the dates.
            self.assertEqual(verdict["reason"], "")

    def test_confirm_accepts_an_absolute_date_and_names_a_cadence_reset(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            future = (datetime.now(timezone.utc) + timedelta(days=15)).date().isoformat()
            captured = capture_project_memory_candidate(paths, "contract-pinned record", stale_after=future)
            record = approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])["record"]
            later = (datetime.now(timezone.utc) + timedelta(days=40)).date().isoformat()
            pinned = memory_workflow.confirm_project_memory_record(paths, record["record_id"], stale_after=later)
            self.assertTrue(pinned["applied"])
            self.assertEqual(pinned["review_due_at"], f"{later}T00:00:00Z")
            self.assertIsNone(pinned["stale_after_days"])
            self.assertFalse(pinned["cadence_reset"])
            # A flagless confirm on a date-pinned record has no day count to
            # honour; it re-anchors relative and must say so out loud.
            reset = memory_workflow.confirm_project_memory_record(paths, record["record_id"])
            self.assertTrue(reset["cadence_reset"])
            self.assertIn("--stale-after DATE", reset["next_action"])
            with self.assertRaises(ValueError):
                memory_workflow.confirm_project_memory_record(
                    paths, record["record_id"], stale_after=later, stale_after_days=30
                )

    def test_absolute_deadline_normalization_edges(self) -> None:
        now = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
        # An offset timestamp normalizes to UTC; truncation happens before
        # the future check so a sub-second future instant is refused.
        self.assertEqual(
            memory_workflow._absolute_deadline("2027-01-15T09:00:00+09:00", field="x", now=now),
            "2027-01-15T00:00:00Z",
        )
        for bad in ("2026-2-3", "2027-02-29", "2026-13-01"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                memory_workflow._absolute_deadline(bad, field="x", now=now)
        with self.assertRaises(ValueError):
            memory_workflow._absolute_deadline((now + timedelta(microseconds=400000)).isoformat(), field="x", now=now)

    def test_absolute_deadline_inputs_fail_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            future = (datetime.now(timezone.utc) + timedelta(days=23)).date().isoformat()
            refusals = (
                (dict(stale_after="2020-01-01"), "must be in the future"),
                (dict(stale_after="three weeks"), "YYYY-MM-DD or an ISO timestamp"),
                (dict(stale_after=future, stale_after_days=10), "at most one of"),
                (dict(expires_at=future, ttl_days=5), "at most one of"),
                (dict(expires_at=future, retention_class="durable"), "durable memory cannot set expires_at"),
                (dict(stale_after=future, retention_class="volatile"), "volatile memory keeps"),
            )
            for kwargs, fragment in refusals:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError) as raised:
                    capture_project_memory_candidate(paths, "a fact", **kwargs)
                self.assertIn(fragment, str(raised.exception))


class RelativeTimeProseTests(unittest.TestCase):
    """A summary saying '3주 뒤' is a fact with a hidden expiry; review it."""

    def _auto_safe(self, paths) -> None:
        paths.setup_profile_path.parent.mkdir(parents=True, exist_ok=True)
        paths.setup_profile_path.write_text(
            json.dumps({"schema_version": "setup_profile/v1", "memory_policy": {"mode": "auto-safe"}}),
            encoding="utf-8",
        )

    def test_relative_time_prose_forces_review_even_under_auto_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._auto_safe(paths)
            control = capture_project_memory_candidate(paths, "the staging db is postgres 15")
            self.assertTrue(control["auto_approved"])
            for summary in (
                "계약 만료는 3주 2일 뒤",
                "renew the cert in 3 weeks",
                "내일 배포 예정",
                "내일부터 새 정책이 적용된다",
                "cert rotation is tomorrow",
                "2년 뒤 갱신 예정",
                "3日後にリリースする",
                "3天后发布新版本",
                "renouveler le certificat dans 3 semaines",
                "le contrat expire la semaine prochaine",
                "migration prévue demain",
                "gel du code le mois prochain",
                "livrer le correctif d'ici vendredi",
                "décision prise aujourd’hui",
                "renouvellement dans 2 années",
                "we migrated 3 days ago",
                "decided last week",
                "last month we switched",
                "the cert was rotated a year ago",
                "we talked about it the other day",
                "on a migré il y a 3 jours",
                "décidé la semaine dernière",
                "le mois dernier on a changé",
                "décidé l’année dernière",
                "déploiement fait avant-hier",
                # Spelled numbers, vague quantifiers and anchored weekdays
                # (#2048): the everyday forms, not only the digit one.
                "we migrated two weeks ago",
                "the flag flipped ten days ago",
                "rotated a few days ago",
                "switched several weeks ago",
                "upgraded a couple of days ago",
                "renew the cert in two weeks",
                "the freeze starts in a few days",
                "decided last Monday",
                "ship it next Friday",
                "on a migré il y a une semaine",
                "décidé il y a deux semaines",
                "changé il y a quelques jours",
                "migré il y a plusieurs semaines",
                "renouveler dans deux semaines",
                "gel du code dans quelques jours",
                "décidé lundi dernier",
                "livré vendredi dernier",
                "revue jeudi prochain",
                "we recently moved the cache to redis",
                "on a récemment migré la base",
            ):
                with self.subTest(summary=summary):
                    captured = capture_project_memory_candidate(paths, summary)
                    self.assertFalse(captured["auto_approved"])
                    sensitivity = captured["candidate"]["time_sensitivity"]
                    self.assertTrue(sensitivity["relative_phrase"])
                    self.assertIn("--stale-after", sensitivity["next_action"])

    def test_ordinary_prose_with_bare_relational_words_stays_untouched(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._auto_safe(paths)
            # "후/전/주" as ordinary grammar, compounds around deictic words,
            # and a number without a time unit must not trip the lint.
            for summary in (
                "리뷰 후 머지하는 프로세스를 따른다",
                "배포 전 체크리스트를 확인한다",
                "매주 회고를 진행한다",
                "3개의 서비스로 구성된다",
                "오늘의집 스타일 UI를 참고한다",
                "下周期性任务由调度器管理",
                # French: a number without a time unit, and the cue nouns
                # "semaine"/"mois"/"prochaine" in ordinary use.
                "Le déploiement couvre 3 environnements",
                "La prochaine version ajoute le mode sombre",
                "Le rapport compare chaque semaine au mois précédent",
                # German "hier" means "here": the French "hier" (yesterday)
                # is deliberately not a cue, so this stays untouched.
                "Die Konfiguration liegt hier im Repo",
                # Past-relative cues need a number plus unit or a bound noun.
                "the last step is to merge",
                "last but not least, run the linter",
                "last-mile delivery is out of scope",
                "the agoraphobic user prefers dark mode",
                "migrated on 2026-10-05",
                "the other branch is stale",
                "il y a des cas limites",
                "le dernier commit est sur main",
                # Spelled quantities and weekdays still need their anchor; a
                # weekday rule ("the last Friday of each month") is recurring.
                "the release goes out the last Friday of each month",
                "le déploiement a lieu le dernier vendredi du mois",
                "one day we will migrate to postgres 16",
                "the config lives in two places",
                "deux semaines de congés par an",
                "last Friday of the month is the release window",
                # "in a/one <unit>" reads as a duration; "most/least recently"
                # and "plus/moins récemment" are a sort order.
                "the prototype was built in a day",
                "the migration finished in one week",
                "evict the least recently used entry",
                "list the most recently updated files first",
                "trier par le plus récemment modifié",
            ):
                with self.subTest(summary=summary):
                    captured = capture_project_memory_candidate(paths, summary)
                    self.assertTrue(captured["auto_approved"])
                    self.assertNotIn("time_sensitivity", captured["candidate"])

    def test_the_review_card_carries_the_time_sensitivity_verdict(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(paths, "계약 만료는 3주 2일 뒤")
            card = memory_workflow.build_project_memory_review_card(captured["candidate"])
            self.assertIn("relative-time phrase", card["time_sensitivity"]["detail"])


class ExpiresSoonWarningTests(unittest.TestCase):
    """The retention twin of review-due-soon: TTL expiry gets advance notice."""

    def test_an_expiring_episode_warns_while_still_delivered(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "incident: cache stampede after deploy", record_type="episode", tags=["incident"])
            probe = datetime.now(timezone.utc) + timedelta(days=20)  # 10 days before the 30-day TTL
            pack = build_project_memory_recall_pack(paths, "incident cache", now=probe)
            self.assertEqual(pack["record_count"], 1)
            warnings = pack["freshness_warnings"]
            self.assertEqual([w["reason_code"] for w in warnings], ["expires_soon"])
            self.assertTrue(warnings[0]["delivered"])
            self.assertEqual(warnings[0]["expires_at"], record["ttl"]["expires_at"])
            self.assertIn("cannot extend a TTL", warnings[0]["next_action"])
            self.assertEqual(validate_project_memory_recall_pack(pack), [])
            quiet = build_project_memory_recall_pack(
                paths, "incident cache", now=datetime.now(timezone.utc) + timedelta(days=10)
            )
            self.assertEqual(quiet["freshness_warnings"], [])

    def test_the_window_scales_down_for_short_lived_records(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "a week-long volatile note", ttl_days=7)
            # 7-day TTL -> 3-day window: silent on approval day and mid-life,
            # warning near the end. A window wider than the record's life
            # would be a permanent banner, not advance notice.
            day0 = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc))
            self.assertEqual(day0["reason"], "")
            day3 = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc) + timedelta(days=3))
            self.assertEqual(day3["reason"], "")
            day5 = memory_workflow._record_staleness(record, now=datetime.now(timezone.utc) + timedelta(days=5))
            self.assertEqual(day5["reason"], "expires_soon")

    def test_expiry_notice_outranks_the_review_notice_when_both_windows_overlap(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "a fact that expires and comes due together", ttl_days=90)
            probe = datetime.now(timezone.utc) + timedelta(days=80)
            verdict = memory_workflow._record_staleness(record, now=probe)
            self.assertEqual((verdict["state"], verdict["reason"]), ("fresh", "expires_soon"))


class CadencePolicyTests(unittest.TestCase):
    """The three memory clocks are policy tunables, not baked-in constants."""

    def _write_policy(self, paths, **cadence) -> None:
        paths.setup_profile_path.parent.mkdir(parents=True, exist_ok=True)
        paths.setup_profile_path.write_text(
            json.dumps(
                {
                    "schema_version": "setup_profile/v1",
                    "memory_policy": {"mode": "review-first", **cadence},
                }
            ),
            encoding="utf-8",
        )

    def test_policy_cadence_overrides_reach_capture_and_the_warning_window(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._write_policy(paths, stale_after_days_default=30, episode_ttl_days=60, due_soon_days=3)
            fact = _approved(paths, "fact on a 30-day cadence", tags=["cadence"])
            self.assertEqual(fact["staleness"]["stale_after_days"], 30)
            episode = _approved(paths, "episode on a 60-day ttl", record_type="episode")
            self.assertEqual(episode["ttl"]["ttl_days"], 60)
            # The 3-day window: quiet 4 days out, warning 2 days out.
            quiet = build_project_memory_recall_pack(
                paths, "cadence fact", now=datetime.now(timezone.utc) + timedelta(days=26)
            )
            self.assertEqual(quiet["freshness_warnings"], [])
            warned = build_project_memory_recall_pack(
                paths, "cadence fact", now=datetime.now(timezone.utc) + timedelta(days=28)
            )
            self.assertEqual([w["reason_code"] for w in warned["freshness_warnings"]], ["review_due_soon"])

    def test_invalid_overrides_fall_back_to_named_defaults_and_are_disclosed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self._write_policy(paths, stale_after_days_default=-5, episode_ttl_days="soon", due_soon_days=True)
            policy = memory_workflow.read_project_memory_policy(paths)
            self.assertEqual(policy["stale_after_days_default"], 90)
            self.assertEqual(policy["episode_ttl_days"], 30)
            self.assertEqual(policy["due_soon_days"], 14)

    def test_capture_cadence_survives_approval_and_flagless_confirm(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "captured on a yearly cadence", stale_after_days=365)
            self.assertEqual(record["staleness"]["stale_after_days"], 365)
            result = memory_workflow.confirm_project_memory_record(paths, record["record_id"])
            self.assertEqual(result["stale_after_days"], 365)
            self.assertFalse(result["shortened"])


class DurablePromotionTests(unittest.TestCase):
    """`omh memory approve --retention-class durable` drops the default review clock."""

    def test_durable_override_removes_deadline_and_recalls_forever(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(paths, "the license is Apache-2.0", tags=["license"])
            record = approve_project_memory_candidate(
                paths, captured["candidate"]["candidate_id"], retention_class="durable"
            )["record"]
            self.assertEqual(record["retention"].get("class"), "durable")
            self.assertEqual(record["staleness"]["review_due_at"], "")
            self.assertEqual(record["revalidation"], {})
            self.assertEqual(validate_project_memory_record(record), [])
            far = build_project_memory_recall_pack(
                paths, "license apache", now=datetime.now(timezone.utc) + timedelta(days=400)
            )
            self.assertEqual(far["record_count"], 1)
            self.assertEqual(far["freshness_warnings"], [])

    def test_an_explicit_capture_cadence_survives_the_durable_override(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(paths, "durable but still reviewed", stale_after_days=30)
            record = approve_project_memory_candidate(
                paths, captured["candidate"]["candidate_id"], retention_class="durable"
            )["record"]
            # The captor chose 30 days deliberately; a flag about retention
            # must not silently remove a review date the reviewer saw.
            self.assertEqual(record["retention"].get("class"), "durable")
            self.assertEqual(record["staleness"]["stale_after_days"], 30)
            self.assertNotEqual(record["staleness"]["review_due_at"], "")
            self.assertEqual(record["revalidation"].get("deadline"), record["staleness"]["review_due_at"])

    def test_policy_default_cadence_reaches_the_override_rederive(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            paths.setup_profile_path.parent.mkdir(parents=True, exist_ok=True)
            paths.setup_profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": "setup_profile/v1",
                        "memory_policy": {"mode": "review-first", "stale_after_days_default": 30},
                    }
                ),
                encoding="utf-8",
            )
            captured = capture_project_memory_candidate(paths, "durable capture, standard approval", retention_class="durable")
            record = approve_project_memory_candidate(
                paths, captured["candidate"]["candidate_id"], retention_class="standard"
            )["record"]
            self.assertEqual(record["staleness"]["stale_after_days"], 30)

    def test_supplying_the_same_class_is_a_validated_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(paths, "a plain standard fact")
            plain = approve_project_memory_candidate(
                paths, captured["candidate"]["candidate_id"], retention_class="standard"
            )["record"]
            self.assertEqual(plain["staleness"]["stale_after_days"], 90)
            other = capture_project_memory_candidate(paths, "another fact")
            with self.assertRaises(ValueError):
                approve_project_memory_candidate(paths, other["candidate"]["candidate_id"], retention_class="eternal")

    def test_unknown_override_class_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            captured = capture_project_memory_candidate(paths, "a fact")
            with self.assertRaises(ValueError):
                approve_project_memory_candidate(
                    paths, captured["candidate"]["candidate_id"], retention_class="forever"
                )


class MemoryConfirmationTests(unittest.TestCase):
    """`omh memory confirm` is the missing verb behind the freshness warning."""

    def test_confirm_returns_a_review_due_record_to_recall(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "staging runs postgres 15", tags=["staging"])
            _mutate_record(
                paths,
                record["record_id"],
                revalidation={"deadline": PAST},
                staleness={"stale_after": PAST, "stale_after_days": None, "review_due_at": PAST},
            )
            dark = build_project_memory_recall_pack(paths, "postgres staging")
            self.assertEqual(dark["record_count"], 0)
            self.assertEqual(dark["excluded_records"][0]["reason"], "stale_review_required")

            result = memory_workflow.confirm_project_memory_record(
                paths, record["record_id"], confirmed_by="operator"
            )
            self.assertTrue(result["applied"])
            self.assertTrue(result["was_stale"])
            self.assertEqual(result["previous_review_due_at"], PAST)

            restored = build_project_memory_recall_pack(paths, "postgres staging")
            self.assertEqual(restored["record_count"], 1)
            self.assertEqual(restored["freshness_warnings"], [])
            stored = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            self.assertEqual(stored["revalidation"]["deadline"], result["review_due_at"])
            self.assertEqual(stored["staleness"]["review_due_at"], result["review_due_at"])
            self.assertEqual(stored["staleness"]["stale_after"], result["review_due_at"])
            self.assertEqual(stored["revalidation"]["confirmed_by"], "operator")
            self.assertEqual(validate_project_memory_record(stored), [])

    def test_confirm_refuses_what_a_new_deadline_cannot_fix(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")

            missing = memory_workflow.confirm_project_memory_record(paths, "mem_ffffffffffffffff")
            self.assertEqual((missing["applied"], missing["reason_code"]), (False, "record_not_found"))

            durable = _approved(paths, "the license is Apache-2.0", retention_class="durable")
            no_deadline = memory_workflow.confirm_project_memory_record(paths, durable["record_id"])
            self.assertEqual((no_deadline["applied"], no_deadline["reason_code"]), (False, "no_review_deadline"))

            expired = _approved(paths, "volatile branch note", ttl_days=1)
            _mutate_record(paths, expired["record_id"], ttl={"ttl_days": 1, "expires_at": PAST})
            dead = memory_workflow.confirm_project_memory_record(paths, expired["record_id"])
            self.assertEqual((dead["applied"], dead["reason_code"]), (False, "retention_expired"))

            source = _source_file(root, "cited.md", "the original claim\n")
            cited = _approved(paths, "claim with a cited source", source_ref=str(source))
            atomic_write_text(source, "the claim, edited\n")
            moved = memory_workflow.confirm_project_memory_record(paths, cited["record_id"])
            self.assertEqual((moved["applied"], moved["reason_code"]), (False, "source_requires_correction"))

            replaced = _approved(paths, "an already superseded claim")
            _mutate_record(paths, replaced["record_id"], superseded_by="mem_0000000000000001")
            stale_rev = memory_workflow.confirm_project_memory_record(paths, replaced["record_id"])
            self.assertEqual((stale_rev["applied"], stale_rev["reason_code"]), (False, "superseded"))

            garbled = _approved(paths, "a record about to be corrupted")
            atomic_write_text(_record_path(paths, garbled["record_id"]), "{", private=True)
            unreadable = memory_workflow.confirm_project_memory_record(paths, garbled["record_id"])
            self.assertEqual((unreadable["applied"], unreadable["reason_code"]), (False, "record_unreadable"))

            legacy = _approved(paths, "a legacy-schema record")
            _mutate_record(paths, legacy["record_id"], schema_version="project_memory_record/v1")
            old_schema = memory_workflow.confirm_project_memory_record(paths, legacy["record_id"])
            self.assertEqual((old_schema["applied"], old_schema["reason_code"]), (False, "unsupported_record_schema"))

            with self.assertRaises(ValueError):
                memory_workflow.confirm_project_memory_record(paths, "../escape")

    def test_confirm_heals_a_legacy_stale_after_only_record_to_full_parity(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "written before review_due_at existed")
            _mutate_record(paths, record["record_id"], revalidation={}, staleness={"stale_after": PAST})
            result = memory_workflow.confirm_project_memory_record(paths, record["record_id"])
            self.assertTrue(result["applied"])
            self.assertTrue(result["was_stale"])
            stored = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            self.assertEqual(stored["revalidation"]["deadline"], result["review_due_at"])
            self.assertEqual(stored["staleness"]["review_due_at"], result["review_due_at"])
            self.assertEqual(stored["staleness"]["stale_after"], result["review_due_at"])

    def test_confirm_bounds_the_actor_and_names_a_shortened_deadline(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "a slow-rotting claim", stale_after_days=365)
            result = memory_workflow.confirm_project_memory_record(
                paths, record["record_id"], confirmed_by="ci-token-bot " + "A" * 5000
            )
            self.assertTrue(result["applied"])
            # Sensitive-looking prose degrades to a redaction and a bound, the
            # same way the attention reason does -- never to a record-level
            # validation error naming a field the operator cannot see.
            stored = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            self.assertLessEqual(len(stored["revalidation"]["confirmed_by"]), 240)
            self.assertNotIn("ci-token-bot", stored["revalidation"]["confirmed_by"])
            # A flagless confirm honours the captured 365-day cadence, so
            # nothing shortened; an explicit shorter cadence does, and the
            # payload must say so instead of shortening silently.
            self.assertFalse(result["shortened"])
            shorter = memory_workflow.confirm_project_memory_record(
                paths, record["record_id"], stale_after_days=30
            )
            self.assertTrue(shorter["shortened"])
            self.assertIn("earlier", shorter["next_action"])

    def test_confirm_persists_and_reuses_an_explicit_cadence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record = _approved(paths, "reviewed on a slow cadence")
            first = memory_workflow.confirm_project_memory_record(
                paths, record["record_id"], stale_after_days=180
            )
            self.assertEqual(first["stale_after_days"], 180)
            stored = json.loads(_record_path(paths, record["record_id"]).read_text(encoding="utf-8"))
            self.assertEqual(stored["staleness"]["stale_after_days"], 180)
            # A later flagless confirm honours the stored cadence instead of
            # silently resetting the record to the 90-day default.
            second = memory_workflow.confirm_project_memory_record(paths, record["record_id"])
            self.assertEqual(second["stale_after_days"], 180)

    def test_confirm_all_due_reblesses_only_clean_deadline_records(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            overdue = _approved(paths, "staging runs postgres 15", tags=["staging"])
            fresh = _approved(paths, "we lint with ruff", tags=["lint"])
            source = _source_file(root, "cited.md", "the original claim\n")
            tainted = _approved(paths, "claim with a cited source", source_ref=str(source))
            for record_id in (overdue["record_id"], tainted["record_id"]):
                _mutate_record(
                    paths,
                    record_id,
                    revalidation={"deadline": PAST},
                    staleness={"stale_after": PAST, "stale_after_days": None, "review_due_at": PAST},
                )
            atomic_write_text(source, "the claim, edited\n")

            batch = memory_workflow.confirm_due_project_memory_records(paths)
            self.assertEqual(batch["due_count"], 2)
            self.assertEqual([entry["record_id"] for entry in batch["confirmed"]], [overdue["record_id"]])
            self.assertEqual(len(batch["skipped"]), 1)
            self.assertEqual(batch["skipped"][0]["record_id"], tainted["record_id"])
            self.assertEqual(batch["skipped"][0]["reason_code"], "source_requires_correction")
            self.assertIn("Correct or retire", batch["skipped"][0]["detail"])
            # The fresh record was never touched: its deadline still derives
            # from capture, not from the batch run.
            untouched = json.loads(_record_path(paths, fresh["record_id"]).read_text(encoding="utf-8"))
            self.assertEqual(untouched["staleness"]["review_due_at"], fresh["staleness"]["review_due_at"])

    def test_a_write_rejection_mid_batch_is_contained_and_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            clean = _approved(paths, "a record that confirms cleanly", tags=["clean"])
            poisoned = _approved(paths, "a record whose write will be refused", tags=["poison"])
            for record_id in (clean["record_id"], poisoned["record_id"]):
                _mutate_record(
                    paths,
                    record_id,
                    revalidation={"deadline": PAST},
                    staleness={"stale_after": PAST, "stale_after_days": None, "review_due_at": PAST},
                )
            # An unknown top-level key makes `_write_project_memory_record`
            # raise at validation time -- after the gates, at the write. The
            # batch must absorb it, keep going, and say what happened.
            _mutate_record(paths, poisoned["record_id"], unexpected_key="boom")
            batch = memory_workflow.confirm_due_project_memory_records(paths)
            self.assertEqual(batch["due_count"], 2)
            self.assertEqual([entry["record_id"] for entry in batch["confirmed"]], [clean["record_id"]])
            self.assertEqual(batch["skipped"][0]["record_id"], poisoned["record_id"])
            self.assertEqual(batch["skipped"][0]["reason_code"], "write_rejected")
            self.assertIn("unsupported keys", batch["skipped"][0]["detail"])

    def test_batch_names_expired_records_it_will_not_touch(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            expired = _approved(paths, "an expired volatile note", ttl_days=1)
            _mutate_record(paths, expired["record_id"], ttl={"ttl_days": 1, "expires_at": PAST})
            batch = memory_workflow.confirm_due_project_memory_records(paths)
            self.assertEqual(batch["due_count"], 0)
            self.assertEqual(batch["expired_count"], 1)
            self.assertIn("omh memory retire", batch["next_action"])

    def test_batch_rejects_an_invalid_cadence_even_on_an_empty_store(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            with self.assertRaises(ValueError):
                memory_workflow.confirm_due_project_memory_records(paths, stale_after_days=-5)


if __name__ == "__main__":
    unittest.main()
