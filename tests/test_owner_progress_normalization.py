"""Contracts for the normalized progress vocabulary (issue #813).

Three acceptance criteria, one class each:

1. Supported owner fixtures normalize DETERMINISTICALLY.
2. Unmapped events and unmapped owners stay VISIBLE.
3. No normalized event upgrades preparation into execution or verification.

Plus the four collapse sites that used to lose an owner's word silently, each
asserted at the surface that used to lose it.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402
from omh.coding import status_board  # noqa: E402
from omh.coding.status_board import (  # noqa: E402
    STATUS_VOCABULARY,
    build_status_board,
    normalize_status,
    unmapped_status_source,
)
from omh.context_safety import (  # noqa: E402
    build_progress_event as build_chat_progress_event,
    unmapped_progress_event_source,
)
from omh.coding.executors import EXECUTOR_PROFILES  # noqa: E402
from omh.coding.context_safety import progress_event_type_vocabulary  # noqa: E402
from omh.coding.unit_telemetry import _STRUCTURED_SOURCE_BY_OWNER  # noqa: E402
from omh.executor_progress import (  # noqa: E402
    ALLOWED_EXECUTOR_PROFILES,
    CALLER_REPORTED_SUMMARY,
    CLOSING_EVENT_TYPES,
    PARSED_STREAM_SUMMARY,
    PROGRESS_EVENT_TYPES,
    PROGRESS_SUMMARY_SOURCES,
    TERMINAL_EVENT_TYPES,
    ExecutorProgressError,
    build_progress_binding,
    build_progress_event,
    build_safe_progress_signal,
    correlation_root_for,
    infer_progress_event_type,
    normalize_executor_profile,
    progress_event_normalization,
    update_binding_reporter_state,
)
from omh.owner_progress_normalization import (  # noqa: E402
    MAPPING_CONFIDENCES,
    MAPPING_NOTES,
    MAX_SOURCE_EVENT_CHARS,
    NORMALIZED_PROGRESS_EVENT_TYPES,
    OWNER_PROGRESS_NORMALIZATION_CLAIM_BOUNDARY,
    OWNER_PROGRESS_NORMALIZATION_SCHEMA_VERSION,
    OWNERS_WITH_PROGRESS_LANE,
    PROGRESS_EVIDENCE_TIERS,
    UNMAPPED_NORMALIZED_EVENT,
    is_known_owner,
    normalization_owners,
    normalization_raises_evidence,
    normalization_row_raises_evidence,
    normalization_table_violations,
    normalize_owner_progress_event,
    normalize_shared_progress_event,
    owner_evidence_ceiling,
    owner_progress_mapping_table,
    progress_evidence_rank,
    progress_evidence_tier,
    shared_dialect_source_events,
    source_event_evidence_tier,
)
from omh.system.paths import OmhPaths  # noqa: E402

_FANOUT_ID = "fanout-0123456789ab"
_NOW = "2026-08-06T12:00:00Z"

# Owners in `EXECUTOR_PROFILES` that have no progress lane today. Named here so
# the test fails loudly when one of them grows a dialect and this file is not
# updated with it.
OWNERS_WITHOUT_PROGRESS_LANE = ("omx-runtime", "omc-runtime", "generic")

# The normalizer's owner names against the binding lane's profile spellings.
# The two sets are deliberately spelled differently (see the module docstring);
# this is the only place the test suite crosses between them.
_PROFILE_BY_OWNER = {
    "codex": "codex",
    "claude-code": "claude_code",
    "omo-runtime": "omo_runtime",
    "hermes": "hermes_local",
}


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")


def _prepared_run(root: Path, executor_profile: str) -> tuple[list[str], str]:
    """A recorded run with a progress binding, ready for `progress observe`.

    Returns the shared CLI prefix and the run id, so a test asserts against the
    same command line an operator types.
    """
    base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
    status, stdout, stderr = run_cli(
        base
        + [
            "runtime",
            "record",
            "--skill",
            "oh-my-hermes",
            "--harness",
            "coding-handling",
            "--status",
            "started",
            "--trigger",
            "self-corroboration regression",
        ]
    )
    assert status == 0, stderr
    run_id = str(json.loads(stdout)["run"]["run_id"])
    bind = [*base, "runtime", "progress", "bind", "--run", run_id, "--executor-profile", executor_profile]
    if executor_profile == "hermes_local":
        bind.append("--observed-hermes-execution")
    status, _stdout, stderr = run_cli(bind)
    assert status == 0, stderr
    return base, run_id


class NormalizationRecordShapeTests(unittest.TestCase):
    def test_record_carries_the_five_named_fields_and_its_boundary(self) -> None:
        record = normalize_owner_progress_event(
            "codex",
            "targeted_tests_passed",
            source_version="codex_progress_summary/v1",
            correlation="codex_session:sess-1",
        )

        self.assertEqual(record["schema_version"], OWNER_PROGRESS_NORMALIZATION_SCHEMA_VERSION)
        self.assertEqual(record["source_event"], "targeted_tests_passed")
        self.assertEqual(record["source_version"], "codex_progress_summary/v1")
        self.assertEqual(record["correlation"], "codex_session:sess-1")
        self.assertEqual(record["normalized_event"], "tests_passed")
        self.assertEqual(record["mapping_confidence"], "lossy")
        self.assertEqual(record["claim_boundary"], OWNER_PROGRESS_NORMALIZATION_CLAIM_BOUNDARY)
        self.assertIn("not result", record["claim_boundary"])

    def test_the_normalized_vocabulary_is_the_shipped_one_plus_the_unmapped_value(self) -> None:
        self.assertEqual(PROGRESS_EVENT_TYPES, NORMALIZED_PROGRESS_EVENT_TYPES)
        self.assertEqual(NORMALIZED_PROGRESS_EVENT_TYPES[-1], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(len(NORMALIZED_PROGRESS_EVENT_TYPES), 13)
        self.assertEqual(len(set(NORMALIZED_PROGRESS_EVENT_TYPES)), 13)

    def test_the_unmapped_value_never_ends_a_binding(self) -> None:
        """An unrecognized word settles nothing, so it must not close or exempt."""
        self.assertNotIn(UNMAPPED_NORMALIZED_EVENT, TERMINAL_EVENT_TYPES)
        self.assertNotIn(UNMAPPED_NORMALIZED_EVENT, CLOSING_EVENT_TYPES)

    def test_owner_coverage_is_the_fanout_owner_set(self) -> None:
        self.assertEqual(normalization_owners(), tuple(EXECUTOR_PROFILES))
        self.assertEqual(
            sorted([*OWNERS_WITH_PROGRESS_LANE, *OWNERS_WITHOUT_PROGRESS_LANE]),
            sorted(EXECUTOR_PROFILES),
        )
        for owner in EXECUTOR_PROFILES:
            with self.subTest(owner=owner):
                self.assertTrue(is_known_owner(owner))
        self.assertFalse(is_known_owner("gemini"))

    def test_correlation_keeps_the_shape_the_progress_lane_already_uses(self) -> None:
        for kwargs, expected in (
            ({"claude_session_ref": "claude-1"}, "claude_session:claude-1"),
            ({"codex_session_ref": "codex-1"}, "codex_session:codex-1"),
            ({"process_session_id": "proc-1"}, "process_session:proc-1"),
            ({}, "binding:run:run-1:codex"),
        ):
            with self.subTest(kwargs=kwargs):
                correlation = correlation_root_for(binding_id="run:run-1:codex", **kwargs)
                self.assertEqual(correlation, expected)
                record = normalize_owner_progress_event("codex", "tests_passed", correlation=correlation)
                self.assertEqual(record["correlation"], correlation)


class DeterministicOwnerFixtureTests(unittest.TestCase):
    """AC1: a supported owner's word always normalizes the same way."""

    CODEX_FIXTURES = (
        ("blocker_encountered", "executor_blocked", "lossy"),
        ("targeted_tests_failed", "tests_failed", "lossy"),
        ("full_tests_passed", "tests_passed", "lossy"),
        ("tests_passed", "tests_passed", "exact"),
        ("file_changed", "diff_started", "lossy"),
        ("files_area_chosen", "repo_exploration", "lossy"),
        ("failure_discovered", "executor_failed", "lossy"),
        # Codex's own runtime stream words, confirmed in this repo.
        ("turn.completed", "executor_completed", "lossy"),
        ("item.completed", "progress_observed", "lossy"),
    )

    CLAUDE_FIXTURES = (
        ("system", "executor_dispatched", "lossy"),
        ("assistant", "progress_observed", "lossy"),
        ("result", "executor_completed", "lossy"),
        ("full_tests_started", "tests_started", "lossy"),
        ("repo_exploration", "repo_exploration", "exact"),
        ("dispatch_to_executor", "executor_dispatched", "lossy"),
    )

    def test_codex_fixtures_normalize_to_the_declared_events(self) -> None:
        for source_event, expected, confidence in self.CODEX_FIXTURES:
            with self.subTest(source_event=source_event):
                record = normalize_owner_progress_event("codex", source_event)
                self.assertEqual(record["normalized_event"], expected)
                self.assertEqual(record["mapping_confidence"], confidence)
                self.assertEqual(record["source_event"], source_event)
                self.assertTrue(record["owner_supported"])

    def test_claude_code_fixtures_normalize_to_the_declared_events(self) -> None:
        for source_event, expected, confidence in self.CLAUDE_FIXTURES:
            with self.subTest(source_event=source_event):
                record = normalize_owner_progress_event("claude-code", source_event)
                self.assertEqual(record["normalized_event"], expected)
                self.assertEqual(record["mapping_confidence"], confidence)
                self.assertEqual(record["owner"], "claude-code")

    def test_owner_dialects_are_not_interchangeable(self) -> None:
        """A native word of one owner is not silently borrowed by another."""
        self.assertEqual(normalize_owner_progress_event("codex", "turn.completed")["normalized_event"], "executor_completed")
        borrowed = normalize_owner_progress_event("claude-code", "turn.completed")
        self.assertEqual(borrowed["normalized_event"], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(borrowed["mapping_note"], "source_event_not_in_owner_dialect")
        self.assertEqual(borrowed["source_event"], "turn.completed")

    def test_repeated_runs_are_byte_identical(self) -> None:
        for owner in OWNERS_WITH_PROGRESS_LANE:
            for source_event in ("tests_passed", "workflow_started", "not_a_real_event"):
                with self.subTest(owner=owner, source_event=source_event):
                    rendered = {
                        json.dumps(
                            normalize_owner_progress_event(
                                owner,
                                source_event,
                                source_version="dialect/v1",
                                correlation="binding:run:run-1:codex",
                            ),
                            sort_keys=True,
                        )
                        for _ in range(5)
                    }
                    self.assertEqual(len(rendered), 1)

    def test_every_omo_host_alias_normalizes_to_one_owner_and_one_record(self) -> None:
        for source_event in ("full_tests_failed", "workflow_completed", "status_update"):
            with self.subTest(source_event=source_event):
                records = [
                    json.dumps(normalize_owner_progress_event(alias, source_event), sort_keys=True)
                    for alias in ("omo-runtime", "omo_runtime", "pi", "senpi", "opencode", "  SenPi  ", "OPENCODE")
                ]
                self.assertEqual(len(set(records)), 1)
        record = normalize_owner_progress_event("senpi", "workflow_completed")
        self.assertEqual(record["owner"], "omo-runtime")
        self.assertEqual(record["normalized_event"], "executor_completed")

    def test_progress_lane_profile_spellings_fold_onto_their_owner(self) -> None:
        for spelling, owner in (
            ("claude_code", "claude-code"),
            ("omo_runtime", "omo-runtime"),
            ("hermes_local", "hermes"),
            ("codex", "codex"),
        ):
            with self.subTest(spelling=spelling):
                record = normalize_owner_progress_event(spelling, "tests_started")
                self.assertEqual(record["owner"], owner)
                self.assertEqual(record["normalized_event"], "tests_started")

    def test_every_record_carries_a_confidence_and_a_justification(self) -> None:
        for owner in (*EXECUTOR_PROFILES, "gemini", ""):
            for source_event in ("tests_passed", "workflow_started", "unknown_word", ""):
                with self.subTest(owner=owner, source_event=source_event):
                    record = normalize_owner_progress_event(owner, source_event)
                    self.assertIn(record["mapping_confidence"], MAPPING_CONFIDENCES)
                    self.assertIn(record["mapping_note"], MAPPING_NOTES)
                    self.assertIn(record["normalized_event"], NORMALIZED_PROGRESS_EVENT_TYPES)
                    self.assertIn(record["source_evidence_tier"], PROGRESS_EVIDENCE_TIERS)
                    self.assertIn(record["normalized_evidence_tier"], PROGRESS_EVIDENCE_TIERS)

    def test_an_absent_source_event_is_absent_not_unmapped_guesswork(self) -> None:
        record = normalize_owner_progress_event("codex", "   ")
        self.assertEqual(record["source_event"], "")
        self.assertEqual(record["mapping_confidence"], "absent")
        self.assertEqual(record["mapping_note"], "no_source_event_reported")
        self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)


class UnmappedStaysVisibleTests(unittest.TestCase):
    """AC2: nothing is dropped, collapsed, or raised into silence."""

    def test_an_unrecognized_word_is_returned_not_raised(self) -> None:
        record = normalize_owner_progress_event("codex", "quantum_tests_teleported")
        self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(record["source_event"], "quantum_tests_teleported")
        self.assertEqual(record["mapping_note"], "source_event_not_in_owner_dialect")
        self.assertEqual(record["mapping_confidence"], "unmapped")

    def test_owners_without_a_progress_lane_return_a_visible_record(self) -> None:
        for owner in OWNERS_WITHOUT_PROGRESS_LANE:
            with self.subTest(owner=owner):
                record = normalize_owner_progress_event(owner, "tests_passed")
                self.assertFalse(record["owner_supported"])
                self.assertEqual(record["owner"], owner)
                self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)
                self.assertEqual(record["mapping_note"], "owner_has_no_progress_lane")
                # The word survives even though the owner has no dialect: a
                # later dialect can be written against what was actually said.
                self.assertEqual(record["source_event"], "tests_passed")
                self.assertEqual(owner_progress_mapping_table(owner), {})

    def test_a_missing_dialect_is_distinguished_from_an_unknown_owner(self) -> None:
        self.assertEqual(
            normalize_owner_progress_event("omx-runtime", "tests_passed")["mapping_note"],
            "owner_has_no_progress_lane",
        )
        self.assertEqual(
            normalize_owner_progress_event("gemini", "tests_passed")["mapping_note"],
            "owner_is_not_a_known_fanout_owner",
        )

    def test_a_pathological_word_is_bounded_but_never_deleted(self) -> None:
        record = normalize_owner_progress_event("codex", "x" * 5000)
        self.assertEqual(len(record["source_event"]), MAX_SOURCE_EVENT_CHARS)
        self.assertTrue(str(record["source_event"]).endswith("..."))
        self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)

    def test_a_multiline_word_cannot_smuggle_a_blob_into_a_record(self) -> None:
        record = normalize_owner_progress_event("codex", "line one\nline two\ttail")
        self.assertNotIn("\n", record["source_event"])
        self.assertNotIn("\t", record["source_event"])
        self.assertEqual(record["source_event"], "line oneline twotail")

    # --- the four collapse sites -------------------------------------------

    def test_collapse_site_infer_no_longer_rounds_an_unknown_word_to_progress(self) -> None:
        """executor_progress.infer_progress_event_type fall-through."""
        signal = build_safe_progress_signal(
            executor_profile="codex",
            codex_progress_summary={
                "schema_version": "codex_progress_summary/v1",
                "latest_progress_event": {"event_type": "sentiment_analysed"},
            },
        )
        self.assertEqual(infer_progress_event_type(signal), UNMAPPED_NORMALIZED_EVENT)
        # The raw word is retained by the signal the event carries.
        self.assertEqual(signal["latest_progress_event_type"], "sentiment_analysed")

    def test_collapse_site_infer_still_reports_progress_when_nothing_was_said(self) -> None:
        """No source word means nothing was lost, so the honest answer is unchanged."""
        signal = build_safe_progress_signal(executor_profile="codex")
        self.assertEqual(infer_progress_event_type(signal), "progress_observed")

    def test_collapse_site_unknown_explicit_event_is_recorded_not_raised(self) -> None:
        """executor_progress.build_safe_progress_signal used to raise and drop everything."""
        signal = build_safe_progress_signal(
            executor_profile="claude_code",
            explicit_event_type="hallucinated_event",
        )
        self.assertEqual(signal["explicit_event_type"], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(signal["unmapped_source_event"], "hallucinated_event")
        self.assertEqual(infer_progress_event_type(signal), UNMAPPED_NORMALIZED_EVENT)

    def test_a_mapped_explicit_event_carries_no_unmapped_key(self) -> None:
        signal = build_safe_progress_signal(
            executor_profile="claude_code",
            explicit_event_type="tests_passed",
        )
        self.assertEqual(signal["explicit_event_type"], "tests_passed")
        self.assertNotIn("unmapped_source_event", signal)

    def test_collapse_site_unknown_owner_rejection_names_which_kind_it_is(self) -> None:
        """executor_progress.normalize_executor_profile raised with no verdict at all."""
        with self.assertRaisesRegex(ExecutorProgressError, "unsupported executor profile for progress: gemini"):
            normalize_executor_profile("gemini")
        with self.assertRaisesRegex(ExecutorProgressError, "a known fanout owner with no progress lane"):
            normalize_executor_profile("omx-runtime")
        # And the owner the lane cannot carry is still answerable elsewhere.
        self.assertEqual(
            normalize_owner_progress_event("omx-runtime", "tests_passed")["normalized_event"],
            UNMAPPED_NORMALIZED_EVENT,
        )

    def test_collapse_site_chat_event_records_the_word_it_refused(self) -> None:
        """context_safety._normalize_progress_event_type kept the downgrade, lost the word."""
        event = build_chat_progress_event("vibes_checked", "something happened")
        self.assertEqual(event["event_type"], "status_update")
        self.assertEqual(event["omitted"]["unmapped_source_event"], "vibes_checked")
        self.assertEqual(unmapped_progress_event_source("vibes_checked"), "vibes_checked")

    def test_chat_event_omits_nothing_when_the_word_was_accepted(self) -> None:
        event = build_chat_progress_event("targeted_tests_passed", "tests passed")
        self.assertEqual(event["event_type"], "targeted_tests_passed")
        self.assertNotIn("unmapped_source_event", event["omitted"])
        self.assertEqual(unmapped_progress_event_source("targeted_tests_passed"), "")
        self.assertEqual(unmapped_progress_event_source(""), "")

    def test_collapse_site_status_board_keeps_the_downgrade_and_the_word(self) -> None:
        """status_board.normalize_status kept the safe downgrade, lost the word."""
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            fanout_dir = paths.fanout_contracts_dir / _FANOUT_ID
            fanout_dir.mkdir(parents=True, exist_ok=True)
            (fanout_dir / "dispatch_summary.json").write_text(
                json.dumps(
                    {
                        "fanout_id": _FANOUT_ID,
                        "units": [
                            {"unit_id": "u-odd", "owner": "codex", "status": "quiesced"},
                            {"unit_id": "u-known", "owner": "codex", "status": "completed"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(status_board, "read_inflight_markers", return_value=[]):
                payload = build_status_board(paths, now=_NOW)

        rows = {str(unit["unit_id"]): unit for unit in payload["units"]}
        self.assertEqual(rows["u-odd"]["status"], "prepared_not_observed")
        self.assertEqual(rows["u-odd"]["unmapped_source_status"], "quiesced")
        self.assertEqual(rows["u-known"]["status"], "completed")
        self.assertNotIn("unmapped_source_status", rows["u-known"])

    def test_status_source_helper_reports_only_a_real_discard(self) -> None:
        for status in STATUS_VOCABULARY:
            with self.subTest(status=status):
                self.assertEqual(normalize_status(status), status)
                self.assertEqual(unmapped_status_source(status), "")
        self.assertEqual(unmapped_status_source(""), "")
        self.assertEqual(unmapped_status_source(None), "")
        self.assertEqual(unmapped_status_source("skipped"), "skipped")


class EvidenceTierTests(unittest.TestCase):
    """AC3: normalization never buys evidence the source did not carry."""

    def test_the_tier_ladder_is_ordered_weakest_first(self) -> None:
        self.assertEqual(
            PROGRESS_EVIDENCE_TIERS,
            ("preparation", "dispatch", "progress", "result_claimed", "verified"),
        )
        ranks = [progress_evidence_rank(tier) for tier in PROGRESS_EVIDENCE_TIERS]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(len(set(ranks)), len(ranks))

    def test_an_unrecognized_tier_can_never_outrank_a_real_one(self) -> None:
        self.assertEqual(progress_evidence_rank("not_a_tier"), -1)
        self.assertLess(progress_evidence_rank("not_a_tier"), progress_evidence_rank("preparation"))

    def test_every_normalized_event_sits_at_a_declared_tier(self) -> None:
        for event in NORMALIZED_PROGRESS_EVENT_TYPES:
            with self.subTest(event=event):
                self.assertIn(progress_evidence_tier(event), PROGRESS_EVIDENCE_TIERS)
        self.assertEqual(progress_evidence_tier(UNMAPPED_NORMALIZED_EVENT), "preparation")
        self.assertEqual(progress_evidence_tier("executor_dispatched"), "dispatch")
        self.assertEqual(progress_evidence_tier("tests_passed"), "verified")
        self.assertEqual(progress_evidence_tier("tests_failed"), "verified")

    def test_no_shipped_row_would_raise_the_evidence_tier(self) -> None:
        self.assertEqual(normalization_table_violations(), [])

    def test_no_owner_word_normalizes_above_the_evidence_it_declares(self) -> None:
        for owner in OWNERS_WITH_PROGRESS_LANE:
            table = owner_progress_mapping_table(owner)
            self.assertTrue(table)
            for source_event, mapping in sorted(table.items()):
                with self.subTest(owner=owner, source_event=source_event):
                    record = normalize_owner_progress_event(owner, source_event)
                    self.assertLessEqual(
                        progress_evidence_rank(str(record["normalized_evidence_tier"])),
                        progress_evidence_rank(mapping.source_evidence_tier),
                    )

    def test_a_preparation_class_word_never_becomes_execution_or_verification(self) -> None:
        upgraded = ("dispatch", "progress", "result_claimed", "verified")
        for owner in OWNERS_WITH_PROGRESS_LANE:
            table = owner_progress_mapping_table(owner)
            preparation_words = [
                source_event
                for source_event, mapping in table.items()
                if mapping.source_evidence_tier == "preparation"
            ]
            self.assertIn("workflow_started", preparation_words)
            for source_event in preparation_words:
                with self.subTest(owner=owner, source_event=source_event):
                    record = normalize_owner_progress_event(owner, source_event)
                    self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)
                    self.assertEqual(record["mapping_note"], "no_normalized_event_at_source_evidence_tier")
                    self.assertNotIn(record["normalized_evidence_tier"], upgraded)

    def test_the_guard_refuses_an_upgrading_mapping_on_its_own(self) -> None:
        """The predicate is testable without a binding, a signal, or a table."""
        self.assertTrue(
            normalization_raises_evidence(source_evidence_tier="preparation", normalized_event="tests_passed")
        )
        self.assertTrue(
            normalization_raises_evidence(source_evidence_tier="progress", normalized_event="executor_completed")
        )
        self.assertFalse(
            normalization_raises_evidence(source_evidence_tier="verified", normalized_event="tests_passed")
        )
        self.assertFalse(
            normalization_raises_evidence(source_evidence_tier="result_claimed", normalized_event="diff_started")
        )
        # A downgrade is always allowed: claiming less is never the failure.
        self.assertFalse(
            normalization_raises_evidence(source_evidence_tier="verified", normalized_event=UNMAPPED_NORMALIZED_EVENT)
        )

    def test_an_unmapped_result_is_never_read_as_liveness(self) -> None:
        signal = build_safe_progress_signal(
            executor_profile="codex",
            explicit_event_type="hallucinated_event",
        )
        self.assertEqual(infer_progress_event_type(signal), UNMAPPED_NORMALIZED_EVENT)
        self.assertNotIn(UNMAPPED_NORMALIZED_EVENT, TERMINAL_EVENT_TYPES)


class EndStateNeedsCorroborationTests(unittest.TestCase):
    """AC3, at the lane: an END STATE is the lane's verdict, never the owner's.

    The normalizer alone cannot enforce this. `workflow_completed` declares
    `result_claimed` and `executor_completed` sits at `result_claimed`, so the
    tier ladder sees no upgrade at all -- and yet the word ALONE reaching
    `executor_completed` closes the binding on the owner's say-so, while the
    executor is still running. The repo already refuses the same shape of
    self-report in `_change_reported_but_not_observed`.
    """

    def _signal(self, owner: str, source_event: str, **overrides: object) -> dict:
        """A signal carrying the owner's narration WORD and nothing else.

        `activity_observed` is what `omh runtime progress observe` itself writes
        when only `--profile-latest-event` is passed, so this is the shape the
        reported reproduction produces, not a contrived one.
        """
        profile = _PROFILE_BY_OWNER[owner]
        summary: dict[str, object] = {
            "status": "activity_observed",
            "event_count": 1,
            "latest_progress_event": {"event_type": source_event},
            "observable_activity": [],
            "summary": "",
        }
        summary.update(overrides)
        if profile == "codex":
            summary["schema_version"] = "codex_progress_summary/v1"
            return build_safe_progress_signal(executor_profile=profile, codex_progress_summary=summary)
        return build_safe_progress_signal(
            executor_profile=profile,
            observed_hermes_execution=profile == "hermes_local",
            profile_progress_summary=summary,
        )

    def test_the_owner_to_profile_map_covers_every_lane(self) -> None:
        self.assertEqual(sorted(_PROFILE_BY_OWNER), sorted(OWNERS_WITH_PROGRESS_LANE))
        self.assertEqual(sorted(_PROFILE_BY_OWNER.values()), sorted(ALLOWED_EXECUTOR_PROFILES))

    def _terminal_words(self, owner: str) -> list[str]:
        return sorted(
            source_event
            for source_event, mapping in owner_progress_mapping_table(owner).items()
            if mapping.normalized_event in TERMINAL_EVENT_TYPES
        )

    def test_every_owner_word_that_would_end_something_is_held_back(self) -> None:
        for owner in OWNERS_WITH_PROGRESS_LANE:
            words = self._terminal_words(owner)
            self.assertTrue(words, owner)
            for source_event in words:
                with self.subTest(owner=owner, source_event=source_event):
                    signal = self._signal(owner, source_event)
                    event_type = infer_progress_event_type(signal)
                    self.assertNotIn(event_type, TERMINAL_EVENT_TYPES)
                    self.assertNotIn(event_type, CLOSING_EVENT_TYPES)
                    self.assertEqual(event_type, UNMAPPED_NORMALIZED_EVENT)
                    # Visible, not rounded: the raw word is still readable.
                    self.assertEqual(signal["latest_progress_event_type"], source_event)

    def test_the_reported_reproductions_no_longer_close_a_binding(self) -> None:
        """`--profile-latest-event workflow_completed`, `turn.completed`, `result`."""
        for owner, source_event in (
            ("omo-runtime", "workflow_completed"),
            ("hermes", "workflow_completed"),
            ("codex", "turn.completed"),
            ("claude-code", "result"),
        ):
            with self.subTest(owner=owner, source_event=source_event):
                profile = _PROFILE_BY_OWNER[owner]
                signal = self._signal(owner, source_event)
                binding = build_progress_binding(
                    target_type="run",
                    target_id="run-836",
                    executor_profile=profile,
                    observed_hermes_execution=profile == "hermes_local",
                    now=_NOW,
                )
                event = build_progress_event(
                    binding,
                    event_type=infer_progress_event_type(signal),
                    signal=signal,
                    observed_at=_NOW,
                )
                updated = update_binding_reporter_state(binding, event, reported=True, reported_at=_NOW)
                self.assertEqual(updated["state"], "active")
                self.assertEqual(event["event_type"], UNMAPPED_NORMALIZED_EVENT)
                # An unrecognized end state says nothing about liveness either.
                self.assertEqual(event["status"], "observed")

    def test_an_independent_signal_still_earns_the_end_state(self) -> None:
        """The guard withholds a word, it does not delete the ladder.

        Every corroborating signal here is one the LANE observed rather than was
        told: a summary this repo parsed out of a codex stream it also hashed,
        and the state of the spawned process. The rows that used to sit here for
        `claude-code` and `hermes` -- an end-state `status` inside a summary
        built from the caller's own `--profile-*` arguments -- moved to
        `CallerReportedNarrationCannotCorroborateItselfTests`: that status is
        the same caller's sentence in a second field, so it corroborates
        nothing. Their profiles keep their end states through `--process-status`
        instead, which is what the rows below assert.
        """
        for owner, source_event, overrides, expected in (
            ("codex", "turn.completed", {"status": "completed_or_passed_observed"}, "executor_completed"),
            ("codex", "failure_discovered", {"status": "failed_or_error_observed"}, "executor_failed"),
            (
                "codex",
                "targeted_tests_passed",
                {"observable_activity": ["Codex ran tests."]},
                "tests_passed",
            ),
        ):
            with self.subTest(owner=owner, source_event=source_event):
                signal = self._signal(owner, source_event, **overrides)
                self.assertEqual(infer_progress_event_type(signal), expected)
        for owner, source_event, process_status, expected in (
            ("claude-code", "result", "exited_zero", "executor_completed"),
            ("hermes", "blocker_encountered", "blocked", "executor_blocked"),
            ("omo-runtime", "workflow_completed", "completed", "executor_completed"),
        ):
            with self.subTest(owner=owner, source_event=source_event, process_status=process_status):
                signal = self._signal(owner, source_event)
                signal["process_status"] = process_status
                self.assertEqual(infer_progress_event_type(signal), expected)

    def test_a_process_status_alone_still_reads_as_the_end_state(self) -> None:
        """The lane's own observation of the process is not owner narration."""
        signal = build_safe_progress_signal(executor_profile="claude_code", process_status="exited_zero")
        self.assertEqual(infer_progress_event_type(signal), "executor_completed")

    def test_a_running_process_is_not_promoted_by_a_completion_word(self) -> None:
        signal = self._signal("codex", "turn.completed")
        signal["process_status"] = "running"
        self.assertEqual(infer_progress_event_type(signal), "running_no_diff_observed")

    def test_a_non_terminal_word_is_never_withheld(self) -> None:
        for owner, source_event, expected in (
            ("codex", "files_area_chosen", "repo_exploration"),
            ("codex", "commit_created", "diff_started"),
            ("claude-code", "full_tests_started", "tests_started"),
            ("omo-runtime", "status_update", "progress_observed"),
        ):
            with self.subTest(owner=owner, source_event=source_event):
                self.assertEqual(infer_progress_event_type(self._signal(owner, source_event)), expected)

    def test_an_explicit_event_is_the_caller_speaking_not_owner_narration(self) -> None:
        """`--event` states the observation outright; that standing is unchanged.

        Documented boundary, narrowed rather than removed: a caller that names
        this repo's own vocabulary is declaring the observation in OMH's terms
        and standing behind it -- the same standing `_CHANGE_CLAIM_EVENT_TYPES`
        gives an explicit `diff_started`, and the standing the wrapper's
        observed-result path depends on. What is no longer covered is an owner
        word RELAYED through the same flag; see
        `AnExplicitEventCannotLaunderAnOwnerWordTests`.
        """
        signal = build_safe_progress_signal(
            executor_profile="codex",
            explicit_event_type="executor_completed",
        )
        self.assertEqual(infer_progress_event_type(signal), "executor_completed")
        self.assertNotIn("explicit_source_event", signal)


class CallerReportedNarrationCannotCorroborateItselfTests(unittest.TestCase):
    """R1: one act cannot be both the narration and the witness to it.

    Holding the end state back from `latest_progress_event_type` closed the
    three reported reproductions and left the leak one field over. For every
    profile that does not go through the codex summary path,
    `commands.runtime._profile_progress_summary` builds the summary's `status`
    straight out of `--profile-status`, and `_end_state_corroborated` then read
    that status as an INDEPENDENT signal agreeing with the word beside it. So a
    single `omh runtime progress observe` call still reached a terminal,
    binding-closing event out of nothing but what the caller said -- the
    original defect wearing the corroborator's hat.

    What a signal now has to carry to end something is a signal omh OBSERVED:
    the state of the process it sampled, git facts, or a summary this repo
    parsed out of a stream it also hashed. Everything the caller narrates --
    whichever field it arrives in -- is treated as the one statement it is.
    """

    # One row is one observation that says the run ended twice over: the
    # narration word, and the status that would have corroborated it. The last
    # two rows are each half on its own, because either half alone used to be
    # enough.
    _SELF_CORROBORATING_CLAIMS = (
        ("completed_or_passed_observed", "workflow_completed"),
        ("blocked", "blocker_encountered"),
        ("failed_or_error_observed", "failure_discovered"),
        ("completed_or_passed_observed", "full_tests_passed"),
        ("completed_or_passed_observed", ""),
        ("activity_observed", "workflow_completed"),
    )
    # The fanout owner set, split by what a self-report can even reach.
    _CALLER_REPORTED_OWNERS = ("claude-code", "omo-runtime", "hermes")
    _PARSED_STREAM_OWNERS = ("codex",)

    def _caller_reported_signal(self, owner: str, *, status: str, source_event: str) -> dict:
        """The signal one `omh runtime progress observe` invocation produces.

        Assembled exactly as `_profile_progress_summary` assembles it, empty
        `observable_activity` included, so these are the shipped shapes rather
        than contrived ones.
        """
        profile = _PROFILE_BY_OWNER[owner]
        return build_safe_progress_signal(
            executor_profile=profile,
            observed_hermes_execution=profile == "hermes_local",
            profile_progress_summary={
                "status": status,
                "event_count": 1,
                "latest_progress_event": {"event_type": source_event},
                "observable_activity": [],
                "summary": "",
            },
        )

    def _event_and_binding_state(self, profile: str, signal: dict) -> tuple[dict, str]:
        binding = build_progress_binding(
            target_type="run",
            target_id="run-813-self-corroboration",
            executor_profile=profile,
            observed_hermes_execution=profile == "hermes_local",
            now=_NOW,
        )
        event = build_progress_event(
            binding,
            event_type=infer_progress_event_type(signal),
            signal=signal,
            observed_at=_NOW,
        )
        updated = update_binding_reporter_state(binding, event, reported=True, reported_at=_NOW)
        return event, str(updated["state"])

    def test_the_owner_split_covers_the_whole_fanout_owner_set(self) -> None:
        """No owner may sit outside one of the three answers below."""
        self.assertEqual(
            sorted(self._CALLER_REPORTED_OWNERS + self._PARSED_STREAM_OWNERS + OWNERS_WITHOUT_PROGRESS_LANE),
            sorted(EXECUTOR_PROFILES),
        )

    def test_no_fanout_owner_can_corroborate_its_own_end_state(self) -> None:
        """Every profile in the fanout owner set, every self-corroborating shape."""
        for owner in EXECUTOR_PROFILES:
            for status, source_event in self._SELF_CORROBORATING_CLAIMS:
                with self.subTest(owner=owner, status=status, source_event=source_event):
                    if owner in OWNERS_WITHOUT_PROGRESS_LANE:
                        # No binding can exist for these, so there is nothing to
                        # close: the lane refuses the owner before the words.
                        with self.assertRaises(ExecutorProgressError):
                            normalize_executor_profile(owner)
                        continue
                    if owner in self._PARSED_STREAM_OWNERS:
                        # A codex binding reads `--codex-log-jsonl` and nothing
                        # else; the caller-reported route is not merely refused
                        # here, it is never read.
                        signal = build_safe_progress_signal(
                            executor_profile=_PROFILE_BY_OWNER[owner],
                            profile_progress_summary={
                                "status": status,
                                "latest_progress_event": {"event_type": source_event},
                            },
                        )
                        self.assertNotIn("progress_status", signal)
                        self.assertNotIn("progress_summary_source", signal)
                    else:
                        signal = self._caller_reported_signal(owner, status=status, source_event=source_event)
                        self.assertEqual(signal["progress_summary_source"], CALLER_REPORTED_SUMMARY)
                    event, state = self._event_and_binding_state(_PROFILE_BY_OWNER[owner], signal)
                    self.assertNotIn(event["event_type"], TERMINAL_EVENT_TYPES)
                    self.assertNotIn(event["event_type"], CLOSING_EVENT_TYPES)
                    self.assertEqual(state, "active")
                    # An unsupported end state says nothing about liveness either.
                    self.assertNotEqual(event["status"], "completed")

    def test_the_refused_claim_stays_visible_instead_of_reading_as_progress(self) -> None:
        """A refusal that rounded to `progress_observed` would hide the claim."""
        for owner in self._CALLER_REPORTED_OWNERS:
            for status, source_event in self._SELF_CORROBORATING_CLAIMS:
                with self.subTest(owner=owner, status=status, source_event=source_event):
                    signal = self._caller_reported_signal(owner, status=status, source_event=source_event)
                    self.assertEqual(infer_progress_event_type(signal), UNMAPPED_NORMALIZED_EVENT)
                    self.assertEqual(signal.get("latest_progress_event_type", ""), source_event)
                    self.assertEqual(signal["progress_status"], status)

    def test_an_observed_signal_still_earns_the_end_state_and_closes_the_binding(self) -> None:
        """Do not over-correct: a real completion must still complete.

        The narration is identical to the refused rows above. What is added is
        one signal the caller did not narrate -- the state of the process omh
        sampled -- and that is enough to admit the caller's own word again,
        including the summary status the row above could not use.
        """
        for owner, process_status, expected in (
            ("claude-code", "exited_zero", "executor_completed"),
            ("omo-runtime", "completed", "executor_completed"),
            ("hermes", "blocked", "executor_blocked"),
            ("claude-code", "exited_nonzero", "executor_failed"),
        ):
            with self.subTest(owner=owner, process_status=process_status):
                profile = _PROFILE_BY_OWNER[owner]
                signal = build_safe_progress_signal(
                    executor_profile=profile,
                    observed_hermes_execution=profile == "hermes_local",
                    process_status=process_status,
                    profile_progress_summary={
                        "status": "completed_or_passed_observed",
                        "event_count": 1,
                        "latest_progress_event": {"event_type": "workflow_completed"},
                        "observable_activity": [],
                        "summary": "",
                    },
                )
                event, state = self._event_and_binding_state(profile, signal)
                self.assertEqual(event["event_type"], expected)
                self.assertIn(event["event_type"], TERMINAL_EVENT_TYPES)
                self.assertIn(event["event_type"], CLOSING_EVENT_TYPES)
                self.assertEqual(state, "closed")

    def test_a_parsed_codex_stream_still_corroborates_its_own_stream(self) -> None:
        """The path the other profiles are now measured against.

        A codex summary is not the caller's argument: `codex_progress` derives
        it from a JSONL stream this repo read, counted, and hashed, and
        `_safe_progress_summary` refuses anything not stamped
        `codex_progress_summary/v1`.
        """
        signal = build_safe_progress_signal(
            executor_profile="codex",
            codex_progress_summary={
                "schema_version": "codex_progress_summary/v1",
                "status": "completed_or_passed_observed",
                "event_count": 2,
                "latest_progress_event": {"event_type": "turn.completed"},
            },
        )
        self.assertEqual(signal["progress_summary_source"], PARSED_STREAM_SUMMARY)
        event, state = self._event_and_binding_state("codex", signal)
        self.assertEqual(event["event_type"], "executor_completed")
        self.assertEqual(state, "closed")

    def test_the_provenance_marker_is_one_of_the_two_declared_values(self) -> None:
        caller_reported = self._caller_reported_signal("claude-code", status="running", source_event="status_update")
        self.assertIn(caller_reported["progress_summary_source"], PROGRESS_SUMMARY_SOURCES)
        self.assertEqual(caller_reported["progress_summary_source"], CALLER_REPORTED_SUMMARY)
        # No summary at all carries no claim about where one came from.
        self.assertNotIn(
            "progress_summary_source",
            build_safe_progress_signal(executor_profile="claude_code", process_status="running"),
        )

    def test_an_unmarked_signal_is_read_as_caller_reported(self) -> None:
        """Fail closed: nobody recorded where this came from, so it corroborates nothing.

        This is the shape a hand-built signal has, and the shape every signal
        written before the marker existed has. Granting it corroborating
        standing by default would reopen the defect for exactly the signals
        whose provenance is unknown.
        """
        self.assertEqual(
            infer_progress_event_type(
                {
                    "executor_profile": "claude_code",
                    "progress_status": "completed_or_passed_observed",
                    "latest_progress_event_type": "workflow_completed",
                }
            ),
            UNMAPPED_NORMALIZED_EVENT,
        )

    def test_the_cli_reproduction_no_longer_closes_a_binding(self) -> None:
        """End to end, the way it was reported: one `progress observe` call."""
        for profile in ("claude_code", "omo_runtime", "hermes_local"):
            with self.subTest(profile=profile), TemporaryDirectory() as tmp:
                base, run_id = _prepared_run(Path(tmp), profile)
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "runtime",
                        "progress",
                        "observe",
                        "--run",
                        run_id,
                        "--full",
                        "--profile-status",
                        "completed_or_passed_observed",
                        "--profile-latest-event",
                        "workflow_completed",
                    ]
                )
                self.assertEqual(stderr, "")
                self.assertEqual(status, 0)
                refused = json.loads(stdout)
                self.assertEqual(refused["event"]["event_type"], UNMAPPED_NORMALIZED_EVENT)
                self.assertEqual(refused["event"]["status"], "observed")
                self.assertEqual(refused["binding"]["state"], "active")
                self.assertEqual(
                    refused["event"]["signal"]["progress_summary_source"],
                    CALLER_REPORTED_SUMMARY,
                )

                # The same caller, one observation later, reporting something it
                # looked at rather than something it was told.
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "runtime",
                        "progress",
                        "observe",
                        "--run",
                        run_id,
                        "--full",
                        "--process-status",
                        "exited_zero",
                        "--profile-status",
                        "completed_or_passed_observed",
                        "--profile-latest-event",
                        "workflow_completed",
                    ]
                )
                self.assertEqual(stderr, "")
                self.assertEqual(status, 0)
                observed = json.loads(stdout)
                self.assertEqual(observed["event"]["event_type"], "executor_completed")
                self.assertEqual(observed["binding"]["state"], "closed")

    def test_a_codex_binding_rejects_the_caller_reported_route_at_the_cli(self) -> None:
        with TemporaryDirectory() as tmp:
            base, run_id = _prepared_run(Path(tmp), "codex")
            status, _stdout, stderr = run_cli(
                base
                + [
                    "runtime",
                    "progress",
                    "observe",
                    "--run",
                    run_id,
                    "--profile-status",
                    "completed_or_passed_observed",
                ]
            )
            self.assertEqual(status, 2)
            self.assertIn("--profile-* flags would be ignored", stderr)


class AnExplicitEventCannotLaunderAnOwnerWordTests(unittest.TestCase):
    """The third gap: `--event` as a way in for the word the lane just refused.

    `--event` is the caller stating the observation outright, and that exception
    is kept: the CLI bounds its choices to `PROGRESS_EVENT_TYPES`, so a caller
    reaching it has named this repo's vocabulary itself, and the wrapper's
    observed-result path (`record_codex_result`) depends on that standing.

    What was not defensible is the library boundary underneath it.
    `build_safe_progress_signal` normalizes an explicit word through the same
    owner dialect as any other, so `workflow_completed`, `result` and
    `turn.completed` -- the exact three reproductions -- became
    `executor_completed` through the explicit field and skipped the
    corroboration rule entirely. That is the executor's own word, in a different
    field, which is what the rule is about.
    """

    def _signal(self, profile: str, explicit_event_type: str, **kwargs: object) -> dict:
        return build_safe_progress_signal(
            executor_profile=profile,
            observed_hermes_execution=profile == "hermes_local",
            explicit_event_type=explicit_event_type,
            **kwargs,
        )

    def test_an_owner_end_state_word_declared_as_an_event_is_refused(self) -> None:
        for profile, source_event in (
            ("claude_code", "workflow_completed"),
            ("claude_code", "result"),
            ("codex", "turn.completed"),
            ("omo_runtime", "workflow_completed"),
            ("hermes_local", "blocker_encountered"),
        ):
            with self.subTest(profile=profile, source_event=source_event):
                signal = self._signal(profile, source_event)
                self.assertEqual(signal["explicit_source_event"], source_event)
                self.assertEqual(infer_progress_event_type(signal), UNMAPPED_NORMALIZED_EVENT)

    def test_the_same_word_is_admitted_once_something_observed_agrees(self) -> None:
        signal = self._signal("claude_code", "workflow_completed", process_status="exited_zero")
        self.assertEqual(infer_progress_event_type(signal), "executor_completed")

    def test_a_non_terminal_owner_word_is_still_translated(self) -> None:
        """The narrowing is about end states, not about translation."""
        for profile, source_event, expected in (
            ("claude_code", "full_tests_started", "tests_started"),
            ("claude_code", "commit_created", "diff_started"),
            ("codex", "item.completed", "progress_observed"),
        ):
            with self.subTest(profile=profile, source_event=source_event):
                signal = self._signal(profile, source_event)
                self.assertEqual(signal["explicit_source_event"], source_event)
                self.assertEqual(infer_progress_event_type(signal), expected)

    def test_the_refusal_keeps_the_raw_word_and_says_which_refusal_it_was(self) -> None:
        signal = self._signal("claude_code", "workflow_completed")
        binding = build_progress_binding(
            target_type="run",
            target_id="run-813-explicit",
            executor_profile="claude_code",
            now=_NOW,
        )
        event = build_progress_event(
            binding,
            event_type=infer_progress_event_type(signal),
            signal=signal,
            observed_at=_NOW,
        )
        record = progress_event_normalization(event)
        self.assertEqual(record["source_event"], "workflow_completed")
        self.assertEqual(record["mapping_note"], "self_reported_end_state_not_corroborated")
        self.assertEqual(update_binding_reporter_state(binding, event, reported=True, reported_at=_NOW)["state"], "active")

    def test_the_cli_cannot_express_the_relay_at_all(self) -> None:
        """`--event` choices are the OMH vocabulary, so the owner word never fits.

        Argparse rejects it before any omh code runs, which is why the explicit
        exception survives at the CLI: a caller that gets through has named an
        OMH event itself rather than passed an executor's word along.
        """
        with TemporaryDirectory() as tmp:
            base, run_id = _prepared_run(Path(tmp), "claude_code")
            for source_event in ("workflow_completed", "result", "turn.completed"):
                with self.subTest(source_event=source_event), self.assertRaises(SystemExit) as raised:
                    run_cli(base + ["runtime", "progress", "observe", "--run", run_id, "--event", source_event])
                self.assertEqual(raised.exception.code, 2)


class ARefusedEndStateCannotBeResurrectedTests(unittest.TestCase):
    """The second gap: re-reading a stored signal must not re-open the verdict.

    A refused observation is written with the whole signal that produced it, and
    two readers re-derive from that signal afterwards --
    `infer_progress_event_type` for anything replaying one, and
    `progress_event_normalization` for the projection's reasoning. Either could
    have reached a friendlier answer than the one on disk, which would make the
    refusal a display detail rather than a verdict.
    """

    def _stored_event(self, **summary: object) -> dict:
        signal = build_safe_progress_signal(
            executor_profile="claude_code",
            profile_progress_summary=dict(summary),
        )
        binding = build_progress_binding(
            target_type="run",
            target_id="run-813-stored",
            executor_profile="claude_code",
            now=_NOW,
        )
        return build_progress_event(
            binding,
            event_type=infer_progress_event_type(signal),
            signal=signal,
            observed_at=_NOW,
        )

    def test_re_inference_over_the_stored_signal_reaches_the_same_verdict(self) -> None:
        for summary in (
            {"status": "activity_observed", "latest_progress_event": {"event_type": "workflow_completed"}},
            {"status": "completed_or_passed_observed", "latest_progress_event": {"event_type": "workflow_completed"}},
            {"status": "completed_or_passed_observed"},
            {"status": "blocked"},
        ):
            with self.subTest(summary=sorted(summary)):
                event = self._stored_event(**summary)
                self.assertEqual(event["event_type"], UNMAPPED_NORMALIZED_EVENT)
                # The signal round-trips through JSON on the way to disk.
                stored = json.loads(json.dumps(event["signal"]))
                self.assertEqual(infer_progress_event_type(stored), UNMAPPED_NORMALIZED_EVENT)

    def test_a_status_only_refusal_explains_itself_as_the_lane_refusal(self) -> None:
        """The shape with no word at all: the pure normalizer can only say "nothing said"."""
        event = self._stored_event(status="completed_or_passed_observed")
        record = progress_event_normalization(event)
        self.assertEqual(record["mapping_note"], "self_reported_end_state_not_corroborated")
        self.assertEqual(record["mapping_confidence"], "unmapped")
        self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)
        self.assertIn(record["mapping_note"], MAPPING_NOTES)

    def test_a_word_the_vocabulary_refused_keeps_the_vocabulary_note(self) -> None:
        """Precedence: the more precise refusal is the one that is reported.

        When both refusals apply -- an unknown word arriving next to a
        caller-reported end-state status -- the word never had a home in this
        owner's dialect, and saying so is what an operator can act on.
        """
        event = self._stored_event(
            status="completed_or_passed_observed",
            latest_progress_event={"event_type": "vibes_checked"},
        )
        record = progress_event_normalization(event)
        self.assertEqual(event["event_type"], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(record["source_event"], "vibes_checked")
        self.assertEqual(record["mapping_note"], "source_event_not_in_owner_dialect")

    def test_the_projection_keeps_the_refusal_after_a_round_trip(self) -> None:
        from omh.executor_progress import (
            append_progress_event,
            project_active_executor_status,
            write_progress_binding,
        )

        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            binding = build_progress_binding(
                target_type="run",
                target_id="run-813-projection",
                executor_profile="claude_code",
                now=_NOW,
            )
            signal = build_safe_progress_signal(
                executor_profile="claude_code",
                profile_progress_summary={
                    "status": "completed_or_passed_observed",
                    "latest_progress_event": {"event_type": "workflow_completed"},
                },
            )
            event = build_progress_event(
                binding,
                event_type=infer_progress_event_type(signal),
                signal=signal,
                observed_at=_NOW,
            )
            write_progress_binding(paths, binding)
            append_progress_event(paths, binding, event)
            projection = project_active_executor_status(paths, now=_NOW)

        latest = projection["latest_progress_events"][0]
        self.assertEqual(latest["event_type"], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(latest["normalization"]["source_event"], "workflow_completed")
        self.assertEqual(latest["normalization"]["mapping_note"], "self_reported_end_state_not_corroborated")
        self.assertEqual(projection["active_executors"][0]["state"], "active")


class AntiUpgradeGuardIsCapableOfFailingTests(unittest.TestCase):
    """The shipped table cannot exercise the guard, so the guard is checked directly."""

    def test_a_row_cannot_declare_its_own_source_tier(self) -> None:
        """Every source tier is derived from the WORD, shared by every owner.

        Restating the tier per row is what made the check vacuous: all shipped
        rows declared `source tier == target tier`, so the comparison compared a
        value with itself and no row could ever fail it.
        """
        for owner in OWNERS_WITH_PROGRESS_LANE:
            for source_event, mapping in owner_progress_mapping_table(owner).items():
                with self.subTest(owner=owner, source_event=source_event):
                    self.assertEqual(mapping.source_evidence_tier, source_event_evidence_tier(source_event))

    def test_a_deliberately_upgrading_row_is_caught(self) -> None:
        """Constructed here on purpose; never shipped.

        `session_started` is a preparation-class word. Declaring it as a
        dispatch -- the exact row the review named -- must fail the guard.
        """
        upgrading = {"session_started": "executor_dispatched"}
        self.assertEqual(normalization_table_violations(upgrading), ["session_started->executor_dispatched"])
        self.assertTrue(
            normalization_row_raises_evidence(
                source_event="session_started",
                normalized_event="executor_dispatched",
            )
        )

    def test_a_classified_preparation_word_cannot_buy_any_higher_tier(self) -> None:
        for normalized_event in ("executor_dispatched", "diff_started", "executor_completed", "tests_passed"):
            with self.subTest(normalized_event=normalized_event):
                self.assertTrue(
                    normalization_row_raises_evidence(
                        source_event="workflow_started",
                        normalized_event=normalized_event,
                    )
                )

    def test_an_unclassified_word_sits_at_the_floor(self) -> None:
        self.assertEqual(source_event_evidence_tier("nobody_classified_this"), "preparation")
        self.assertEqual(
            normalization_table_violations({"nobody_classified_this": "progress_observed"}),
            ["nobody_classified_this->progress_observed"],
        )

    def test_a_downgrading_or_equal_row_is_not_a_violation(self) -> None:
        self.assertEqual(normalization_table_violations({"full_tests_passed": "tests_passed"}), [])
        self.assertEqual(normalization_table_violations({"turn.completed": "progress_observed"}), [])
        self.assertEqual(normalization_table_violations({"workflow_started": UNMAPPED_NORMALIZED_EVENT}), [])

    def test_the_shipped_tables_are_still_clean(self) -> None:
        self.assertEqual(normalization_table_violations(), [])


class OwnerEvidenceCeilingTests(unittest.TestCase):
    """DEFECT 3: an unreadable stream cannot produce a verification claim."""

    def test_omo_runtime_cannot_reach_a_verified_normalized_event(self) -> None:
        verified_words = [
            source_event
            for source_event, target in (
                ("tests_passed", "tests_passed"),
                ("tests_failed", "tests_failed"),
                ("targeted_tests_passed", "tests_passed"),
                ("targeted_tests_failed", "tests_failed"),
                ("full_tests_passed", "tests_passed"),
                ("full_tests_failed", "tests_failed"),
            )
            if target
        ]
        for alias in ("omo-runtime", "omo_runtime", "pi", "senpi", "opencode"):
            for source_event in verified_words:
                with self.subTest(alias=alias, source_event=source_event):
                    record = normalize_owner_progress_event(alias, source_event)
                    self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)
                    self.assertNotEqual(record["normalized_evidence_tier"], "verified")
                    self.assertEqual(
                        record["mapping_note"],
                        "owner_stream_cannot_carry_the_source_evidence_tier",
                    )
                    # The word survives, so a later readable stream can be
                    # mapped against what was actually said.
                    self.assertEqual(record["source_event"], source_event)

    def test_no_owner_word_at_all_reaches_verified_for_an_unreadable_stream(self) -> None:
        for source_event in owner_progress_mapping_table("omo-runtime"):
            with self.subTest(source_event=source_event):
                record = normalize_owner_progress_event("omo-runtime", source_event)
                self.assertNotEqual(record["normalized_evidence_tier"], "verified")

    def test_the_ceiling_follows_this_repos_telemetry_contract(self) -> None:
        """`unit_telemetry._STRUCTURED_SOURCE_BY_OWNER` is the contract, not a hint.

        It names the owners whose structured stream this repo can read. Any lane
        owner absent from it must either be capped below `verified` or be the
        one documented exception -- `hermes`, which is not a spawned CLI at all
        and so never appears in a table about spawned stdout.
        """
        readable = set(_STRUCTURED_SOURCE_BY_OWNER)
        self.assertEqual(readable, {"codex", "claude", "claude-code"})
        for owner in OWNERS_WITH_PROGRESS_LANE:
            with self.subTest(owner=owner):
                if owner in readable or owner == "hermes":
                    self.assertEqual(owner_evidence_ceiling(owner), "verified")
                else:
                    self.assertLess(
                        progress_evidence_rank(owner_evidence_ceiling(owner)),
                        progress_evidence_rank("verified"),
                    )
        self.assertEqual(owner_evidence_ceiling("omo-runtime"), "result_claimed")

    def test_a_readable_owner_still_reaches_verified(self) -> None:
        for owner in ("codex", "claude-code", "hermes"):
            with self.subTest(owner=owner):
                record = normalize_owner_progress_event(owner, "full_tests_passed")
                self.assertEqual(record["normalized_event"], "tests_passed")
                self.assertEqual(record["normalized_evidence_tier"], "verified")

    def test_an_omo_verification_word_never_becomes_a_verified_lane_event(self) -> None:
        signal = build_safe_progress_signal(
            executor_profile="omo_runtime",
            # The end state is observed: omh sampled the process it spawned. The
            # summary beside it is the caller's own words and no longer
            # corroborates anything, so this asserts what it always meant to --
            # that a corroborated END STATE still cannot buy the VERIFICATION
            # tier for an owner whose test run nothing here can read.
            process_status="exited_zero",
            profile_progress_summary={
                "status": "completed_or_passed_observed",
                "latest_progress_event": {"event_type": "full_tests_passed"},
            },
        )
        self.assertEqual(infer_progress_event_type(signal), "executor_completed")

    def test_a_caller_reported_omo_completion_alone_earns_nothing(self) -> None:
        """The same signal without the observed process status."""
        signal = build_safe_progress_signal(
            executor_profile="omo_runtime",
            profile_progress_summary={
                "status": "completed_or_passed_observed",
                "latest_progress_event": {"event_type": "full_tests_passed"},
            },
        )
        self.assertEqual(infer_progress_event_type(signal), UNMAPPED_NORMALIZED_EVENT)


class ChatVocabularyContainmentTests(unittest.TestCase):
    """DEFECT 5: the missing half of the mirror gate.

    The bundle's event-type copy is gated against `PROGRESS_EVENT_TYPES`. The
    other mirror -- the chat/workflow vocabulary in `context_safety` against the
    normalizer's shared dialect -- had no gate at all, so adding a routine chat
    value would make every executor signal carrying it normalize to
    `unmapped_source_event`.
    """

    def test_every_chat_progress_event_type_is_a_source_word_the_normalizer_knows(self) -> None:
        chat_vocabulary = set(progress_event_type_vocabulary())
        shared = set(shared_dialect_source_events())
        self.assertTrue(chat_vocabulary)
        self.assertEqual(sorted(chat_vocabulary - shared), [])
        for source_event in sorted(chat_vocabulary):
            with self.subTest(source_event=source_event):
                for owner in OWNERS_WITH_PROGRESS_LANE:
                    self.assertIn(source_event, owner_progress_mapping_table(owner))

    def test_every_chat_progress_event_type_carries_a_declared_source_tier(self) -> None:
        # `hermes` adds no owner-native words, so its table IS the shared dialect.
        shared = owner_progress_mapping_table("hermes")
        for source_event in progress_event_type_vocabulary():
            with self.subTest(source_event=source_event):
                self.assertIn(source_event_evidence_tier(source_event), PROGRESS_EVIDENCE_TIERS)
                self.assertEqual(
                    normalization_table_violations({source_event: shared[source_event].normalized_event}),
                    [],
                )


class SilentLossTests(unittest.TestCase):
    """DEFECT 6: four small losses, each real on its own."""

    def test_a_rebuilt_chat_event_keeps_the_words_the_first_build_refused(self) -> None:
        """(a) `compact_progress_events` used to drop the note on the way into a card."""
        from omh.context_safety import compact_progress_events

        event = build_chat_progress_event("vibes_checked", "something happened", status="cancelled")
        compacted, omitted = compact_progress_events([event])
        self.assertEqual(omitted, 0)
        self.assertEqual(compacted[0]["event_type"], "status_update")
        self.assertEqual(compacted[0]["omitted"]["unmapped_source_event"], "vibes_checked")
        self.assertEqual(compacted[0]["omitted"]["unmapped_source_status"], "cancelled")

    def test_a_rebuilt_chat_event_invents_nothing_when_nothing_was_refused(self) -> None:
        from omh.context_safety import compact_progress_events

        event = build_chat_progress_event("targeted_tests_passed", "tests passed", status="passed")
        compacted, _omitted = compact_progress_events([event])
        for key in ("unmapped_source_event", "unmapped_source_status", "unmapped_source_severity"):
            self.assertNotIn(key, compacted[0]["omitted"])

    def test_an_unrecognized_status_and_severity_are_recorded_not_only_downgraded(self) -> None:
        """(b) the same collapse the event type was fixed for, one line down."""
        event = build_chat_progress_event(
            "targeted_tests_passed",
            "tests passed",
            status="cancelled",
            severity="catastrophic",
        )
        self.assertEqual(event["status"], "observed")
        self.assertEqual(event["severity"], "info")
        self.assertEqual(event["omitted"]["unmapped_source_status"], "cancelled")
        self.assertEqual(event["omitted"]["unmapped_source_severity"], "catastrophic")
        self.assertNotIn("unmapped_source_event", event["omitted"])

    def test_a_reported_status_is_distinguishable_from_no_status_at_all(self) -> None:
        reported = build_chat_progress_event("status_update", "x", status="cancelled")
        silent = build_chat_progress_event("status_update", "x")
        self.assertEqual(reported["status"], silent["status"])
        self.assertNotEqual(reported["omitted"], silent["omitted"])

    def test_a_signal_with_no_owner_still_resolves_the_shared_dialect(self) -> None:
        """(c) re-inference over a stored signal must not be weakened by a missing owner."""
        self.assertEqual(infer_progress_event_type({"latest_progress_event_type": "full_tests_started"}), "tests_started")
        self.assertEqual(infer_progress_event_type({"latest_progress_event_type": "commit_created"}), "diff_started")
        self.assertEqual(
            infer_progress_event_type({"latest_progress_event_type": "workflow_completed", "process_status": "exited_zero"}),
            "executor_completed",
        )
        # An owner-NATIVE word is the one case that genuinely differs by owner,
        # so it stays unmapped without one.
        self.assertEqual(
            infer_progress_event_type({"latest_progress_event_type": "turn.completed", "process_status": "exited_zero"}),
            "executor_completed",
        )
        self.assertEqual(normalize_shared_progress_event("turn.completed")["normalized_event"], UNMAPPED_NORMALIZED_EVENT)

    def test_the_owner_less_resolver_cannot_buy_a_verification_claim(self) -> None:
        record = normalize_shared_progress_event("full_tests_passed")
        self.assertEqual(record["normalized_event"], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(record["mapping_note"], "owner_stream_cannot_carry_the_source_evidence_tier")
        self.assertEqual(record["owner"], "")
        self.assertFalse(record["owner_supported"])

    def test_serializing_one_signal_twice_is_byte_identical(self) -> None:
        """(d) a set literal put persisted keys in per-process hash order."""
        signal = build_safe_progress_signal(
            executor_profile="codex",
            process_status="running",
            routed_model="gpt-5.6-sol",
            routed_reasoning_effort="xhigh",
            tokens_total=10,
            elapsed_seconds=5,
            codex_progress_summary={
                "schema_version": "codex_progress_summary/v1",
                "status": "activity_observed",
                "latest_progress_event": {"event_type": "repo_exploration"},
            },
        )
        rendered = {json.dumps(dict(signal)) for _ in range(5)}
        self.assertEqual(len(rendered), 1)
        # Deterministic ORDER, not merely deterministic content: `sort_keys`
        # would hide exactly the defect this pins.
        self.assertEqual(list(signal), list(json.loads(json.dumps(signal))))
        self.assertEqual(list(signal)[0], "executor_profile")


class NormalizationRecordHasAConsumerTests(unittest.TestCase):
    """DEFECT 7: an operator seeing `unmapped_source_event` can reach the reasoning."""

    def _event(self, **signal_kwargs: object) -> dict:
        binding = build_progress_binding(
            target_type="run",
            target_id="run-836-consumer",
            executor_profile="codex",
            now=_NOW,
        )
        signal = build_safe_progress_signal(executor_profile="codex", **signal_kwargs)
        return build_progress_event(
            binding,
            event_type=infer_progress_event_type(signal),
            signal=signal,
            observed_at=_NOW,
        )

    def test_a_refused_word_explains_itself_from_the_stored_event_alone(self) -> None:
        event = self._event(
            codex_progress_summary={
                "schema_version": "codex_progress_summary/v1",
                "status": "activity_observed",
                "latest_progress_event": {"event_type": "turn.completed"},
            }
        )
        record = progress_event_normalization(event)
        self.assertEqual(record["schema_version"], OWNER_PROGRESS_NORMALIZATION_SCHEMA_VERSION)
        self.assertEqual(record["source_event"], "turn.completed")
        self.assertEqual(record["mapping_confidence"], "unmapped")
        self.assertEqual(record["mapping_note"], "self_reported_end_state_not_corroborated")
        self.assertEqual(record["source_evidence_tier"], "result_claimed")
        self.assertEqual(record["normalized_evidence_tier"], "preparation")
        self.assertEqual(record["claim_boundary"], OWNER_PROGRESS_NORMALIZATION_CLAIM_BOUNDARY)

    def test_the_two_refusals_do_not_read_the_same(self) -> None:
        vocabulary_refusal = progress_event_normalization(self._event(explicit_event_type="hallucinated_event"))
        self.assertEqual(vocabulary_refusal["mapping_note"], "source_event_not_in_owner_dialect")
        self.assertEqual(vocabulary_refusal["source_event"], "hallucinated_event")

    def test_every_note_it_can_produce_is_in_the_closed_vocabulary(self) -> None:
        for event in (
            self._event(explicit_event_type="hallucinated_event"),
            self._event(
                codex_progress_summary={
                    "schema_version": "codex_progress_summary/v1",
                    "status": "activity_observed",
                    "latest_progress_event": {"event_type": "turn.completed"},
                }
            ),
        ):
            record = progress_event_normalization(event)
            with self.subTest(note=record["mapping_note"]):
                self.assertIn(record["mapping_note"], MAPPING_NOTES)
                self.assertIn(record["mapping_confidence"], MAPPING_CONFIDENCES)

    def test_a_mapped_event_carries_no_record_at_all(self) -> None:
        event = self._event(process_status="exited_zero")
        self.assertEqual(event["event_type"], "executor_completed")
        self.assertEqual(progress_event_normalization(event), {})

    def test_the_progress_status_projection_carries_the_record(self) -> None:
        """The read-only consumer: `omh runtime progress-status` shows the reasoning."""
        from omh.executor_progress import (
            append_progress_event,
            project_active_executor_status,
            write_progress_binding,
        )

        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            binding = build_progress_binding(
                target_type="run",
                target_id="run-836-projection",
                executor_profile="codex",
                now=_NOW,
            )
            signal = build_safe_progress_signal(
                executor_profile="codex",
                codex_progress_summary={
                    "schema_version": "codex_progress_summary/v1",
                    "status": "activity_observed",
                    "latest_progress_event": {"event_type": "turn.completed"},
                },
            )
            event = build_progress_event(
                binding,
                event_type=infer_progress_event_type(signal),
                signal=signal,
                observed_at=_NOW,
            )
            write_progress_binding(paths, binding)
            append_progress_event(paths, binding, event)
            projection = project_active_executor_status(paths, now=_NOW)

        latest = projection["latest_progress_events"][0]
        self.assertEqual(latest["event_type"], UNMAPPED_NORMALIZED_EVENT)
        self.assertEqual(latest["normalization"]["source_event"], "turn.completed")
        self.assertEqual(latest["normalization"]["mapping_note"], "self_reported_end_state_not_corroborated")
        row = projection["active_executors"][0]
        self.assertEqual(row["latest_event"]["normalization"]["source_event"], "turn.completed")

    def test_a_mapped_projection_row_stays_the_shape_it_already_was(self) -> None:
        from omh.executor_progress import (
            append_progress_event,
            project_active_executor_status,
            write_progress_binding,
        )

        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            binding = build_progress_binding(
                target_type="run",
                target_id="run-836-mapped",
                executor_profile="codex",
                now=_NOW,
            )
            signal = build_safe_progress_signal(executor_profile="codex", explicit_event_type="diff_started")
            event = build_progress_event(
                binding,
                event_type=infer_progress_event_type(signal),
                signal=signal,
                observed_at=_NOW,
            )
            write_progress_binding(paths, binding)
            append_progress_event(paths, binding, event)
            projection = project_active_executor_status(paths, now=_NOW)

        self.assertNotIn("normalization", projection["latest_progress_events"][0])


if __name__ == "__main__":
    unittest.main()
