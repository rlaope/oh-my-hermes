from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.chat_router import route_chat_message
from omh.hermes_ops import build_scheduled_ops_blueprint, validate_hermes_ops_blueprint
from omh.paths import OmhPaths
from omh.wrapper_contract import build_chat_interaction_payload
from omh.workflows.recurring_intents import (
    RECURRING_OCCURRENCE_SCHEMA_VERSION,
    RETAINED_OCCURRENCE_LIMIT,
    activate_recurring_intent,
    build_recurring_intent,
    list_recurring_intents,
    preview_recurring_intent,
    record_recurring_intent_occurrence,
    recurring_intent_revision_id,
    revise_recurring_intent,
    show_recurring_intent,
    summarize_recurring_intent,
    update_recurring_intent,
    validate_recurring_intent,
    validate_recurring_intent_store,
    write_recurring_intent,
)
from _route_owner import dispatched_or_asked, route_owner, route_owner_harness

# Rows re-pinned to a clarify by shortlist-first routing (dispatch only on
# strong evidence). Only these rows may pass as a clarify whose first
# candidate is the expected skill; every other row must still dispatch.
_REPINNED_NATURAL_LANGUAGE_RECURRING_REQUEST_REACHES_THE_RECURRING_LAN = frozenset(
    {
        "every weekday morning at 9am sweep stale pull requests and send a Slack digest only if something changed",
    }
)


REQUEST = "every weekday morning at 9am sweep stale pull requests and send a Slack digest only if something changed"

# The five failure-policy decisions an intent needs before it can be activated.
# Kept here so the lifecycle tests below stay about the lifecycle; the gate
# itself is owned by tests/test_recurring_failure_policy.py.
COMPLETE_FAILURE_POLICY = {
    "overlap_posture": "skip_when_running",
    "missed_run_posture": "skip_missed_window",
    "retry_posture": "no_retry",
    "backfill_posture": "no_backfill",
    "failure_pause_posture": "pause_after_consecutive_failures",
    "failure_pause_threshold": 3,
}
COMPLETE_FAILURE_POLICY_CLI_ARGS = [
    "--overlap-posture",
    "skip_when_running",
    "--missed-run-posture",
    "skip_missed_window",
    "--retry-posture",
    "no_retry",
    "--backfill-posture",
    "no_backfill",
    "--failure-pause-posture",
    "pause_after_consecutive_failures",
    "--failure-pause-threshold",
    "3",
]


class RecurringIntentPreparationTests(unittest.TestCase):
    """AC1: a natural-language recurring intent is previewable and savable."""

    def test_natural_language_recurring_request_reaches_the_recurring_lane(self) -> None:
        """No new trigger was added: the recurring lane is the one chat already reaches."""
        for message in (
            REQUEST,
            "make a daily competitor research digest blueprint every morning",
            "매일 아침 경쟁사 뉴스를 조사해서 변화 있으면 슬랙으로 보내줘",
        ):
            with self.subTest(message=message):
                route = route_chat_message(message)

                # Shortlist-first: a request carried by words rather than a
                # phrase asks, with automation-blueprint leading the shortlist.
                self.assertTrue(dispatched_or_asked(route, allow_clarify=message in _REPINNED_NATURAL_LANGUAGE_RECURRING_REQUEST_REACHES_THE_RECURRING_LAN))
                self.assertEqual(route_owner(route, allow_clarify=message in _REPINNED_NATURAL_LANGUAGE_RECURRING_REQUEST_REACHES_THE_RECURRING_LAN), "automation-blueprint")
                self.assertEqual(route_owner_harness(route, allow_clarify=message in _REPINNED_NATURAL_LANGUAGE_RECURRING_REQUEST_REACHES_THE_RECURRING_LAN), "scheduled-ops-blueprint")

    def test_one_off_requests_do_not_become_recurring_intents(self) -> None:
        for message in (
            "summarize this pull request for me right now",
            "fix the failing test in src/routing/chat.py",
            "what does the recurring intent record store?",
        ):
            with self.subTest(message=message):
                route = route_chat_message(message)

                self.assertNotEqual(route["selected_skill"], "automation-blueprint")
                self.assertNotEqual(route["selected_harness"], "scheduled-ops-blueprint")

    def test_the_chat_card_offers_to_save_the_paused_intent_and_names_activation(self) -> None:
        # Re-pinned 2026-09-26: "every weekday morning" says no phrase of
        # automation-blueprint's own, and the scheduled-ops guard that carried
        # it measured 0 right / 1 wrong on the tuning set, under 3:1, so it
        # asks with the scheduler first. The card is pinned on the sentence
        # that says the skill's own phrase ("every morning").
        asked = build_chat_interaction_payload(
            "every weekday morning check release risk and tell me on Slack only if something changed",
            source="discord",
        )
        self.assertEqual(asked["route"]["action"], "clarify")
        self.assertEqual(route_owner(asked["route"], allow_clarify=True), "automation-blueprint")

        payload = build_chat_interaction_payload(
            "every morning check release risk and tell me on Slack only if something changed",
            source="discord",
        )

        response = payload["chat_response"]
        self.assertEqual(payload["route"]["selected_skill"], "automation-blueprint")
        self.assertIn("save it as a paused recurring intent", response["body"])
        self.assertIn("only an approved runtime surface can activate later", response["body"])
        self.assertIn("with an approval reference and a recorded observer", response["body"])
        self.assertIn("save_paused_recurring_intent", response["state"]["recommended_flow"])

    def test_preview_needs_no_command_knowledge_and_reads_back_the_plan(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")

        preview = preview_recurring_intent(intent)

        self.assertTrue(preview["preview_only"])
        self.assertFalse(preview["saved"])
        self.assertFalse(preview["save"]["requires_user_command"])
        self.assertEqual(preview["save"]["user_action"], "confirm_or_correct_the_summary")
        self.assertEqual(preview["save"]["entry_action"], "prepare_scheduled_ops_blueprint")
        self.assertEqual(preview["intent"], intent)
        self.assertIn("Weekday at 9am", preview["human_summary"])
        self.assertIn("slack", preview["human_summary"])
        self.assertIn("OMH runs no scheduler", preview["human_summary"])
        self.assertIn("name the owner accountable for this recurring work", preview["open_decisions"])

    def test_cadence_delivery_and_silence_come_from_the_blueprint_normalizer(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")
        blueprint = build_scheduled_ops_blueprint(REQUEST, created_at="2026-06-16T00:00:00Z")

        self.assertEqual(intent["derived_from"]["schema_version"], "prepared_native_blueprint/v1")
        self.assertEqual(intent["derived_from"]["authority"], "projection_only")
        self.assertEqual(intent["schedule_intent"], blueprint["schedule_intent"])
        self.assertEqual(intent["delivery_intent"], blueprint["delivery_intent"])
        self.assertEqual(intent["silence_policy"], blueprint["silence_policy"])

    def test_korean_recurring_request_prepares_the_same_paused_shape(self) -> None:
        intent = build_recurring_intent(
            "매일 아침 경쟁사 뉴스를 조사해서 변화 있으면 슬랙으로 보내줘",
            created_at="2026-06-16T00:00:00Z",
        )

        self.assertEqual(intent["schedule_intent"]["cadence"], "daily")
        self.assertEqual(intent["delivery_intent"]["surfaces"], ["slack"])
        self.assertEqual(intent["lifecycle"]["state"], "paused")
        self.assertEqual(validate_recurring_intent(intent), [])


class RecurringIntentPausedByDefaultTests(unittest.TestCase):
    """AC2: a new intent is paused and cannot claim that any occurrence ran."""

    def test_fresh_intent_has_no_vocabulary_for_a_run(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")

        self.assertEqual(intent["lifecycle"]["state"], "paused")
        self.assertEqual(intent["lifecycle"]["transitions"], [])
        self.assertEqual(intent["occurrences"], [])
        self.assertFalse(intent["required_approval"]["granted"])
        self.assertTrue(intent["required_approval"]["required"])
        self.assertTrue(intent["claim_boundary"]["omh_runs_no_scheduler"])
        self.assertEqual(summarize_recurring_intent(intent)["occurrence_count"], 0)
        self.assertEqual(validate_recurring_intent(intent), [])

    def test_recording_an_occurrence_on_a_paused_intent_is_refused(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")

        with self.assertRaises(ValueError) as caught:
            record_recurring_intent_occurrence(
                intent,
                runtime_run_ref="run-1",
                runtime_surface="hermes-runtime",
                observer="hermes-runtime",
            )

        self.assertIn("a paused recurring intent cannot record an occurrence", str(caught.exception))

    def test_validator_refuses_a_payload_that_asserts_an_occurrence_ran(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")
        intent["occurrences"] = [
            {
                "schema_version": RECURRING_OCCURRENCE_SCHEMA_VERSION,
                "occurrence_id": "forged",
                "intent_id": intent["intent_id"],
                "intent_revision_id": intent["revision"]["revision_id"],
                "outcome": "ran",
                "observer": "someone",
                "observer_kind": "human",
                "observed_at": "2026-06-17T00:00:00Z",
                "runtime_run": {"surface": "hermes-runtime", "run_ref": "run-1"},
                "evidence_authority": "linked_runtime_run",
                "claim_boundary": "forged",
            }
        ]

        errors = validate_recurring_intent(intent)

        self.assertIn(
            "a recurring intent with no recorded activation transition must not carry occurrences: "
            "it cannot claim that any occurrence ran",
            errors,
        )

    def test_nested_prepared_or_not_observed_guard_still_holds_for_intents(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")
        intent["schedule_intent"]["status"] = "observed"
        intent["delivery_intent"]["delivery_status"] = "delivered"

        rendered = "; ".join(validate_recurring_intent(intent))

        self.assertIn("$.schedule_intent.status must remain prepared or not_observed", rendered)
        self.assertIn("$.delivery_intent.delivery_status must not claim observed runtime", rendered)

    def test_the_blueprint_guard_this_record_reuses_is_unchanged(self) -> None:
        blueprint = build_scheduled_ops_blueprint("daily status digest", created_at="2026-06-16T00:00:00Z")
        blueprint["schedule_intent"]["status"] = "observed"

        rendered = "; ".join(validate_hermes_ops_blueprint(blueprint))

        self.assertIn("$.schedule_intent.status must remain prepared or not_observed", rendered)

    def test_activation_without_a_recorded_observer_is_refused(self) -> None:
        intent = build_recurring_intent(
            REQUEST,
            created_at="2026-06-16T00:00:00Z",
            **COMPLETE_FAILURE_POLICY,
        )

        with self.assertRaises(ValueError) as caught:
            activate_recurring_intent(
                intent,
                observer="   ",
                approval_ref="approval-1",
                activation_surface="hermes-automation",
            )

        self.assertIn("activation requires a recorded observer", str(caught.exception))

        intent["lifecycle"]["state"] = "activated"
        intent["lifecycle"]["transitions"] = [
            {
                "transition": "activated",
                "intent_revision_id": intent["revision"]["revision_id"],
                "observer": "",
                "observer_kind": "approved_runtime_surface",
                "approval_ref": "approval-1",
                "activation_surface": "hermes-automation",
                "reason": "forged",
                "recorded_at": "2026-06-16T02:00:00Z",
            }
        ]
        intent["required_approval"]["granted"] = True

        self.assertIn(
            "$.lifecycle.transitions[0] records an activation without a recorded observer",
            validate_recurring_intent(intent),
        )

    def test_activation_requires_an_approval_reference_and_an_activating_surface(self) -> None:
        intent = build_recurring_intent(
            REQUEST,
            created_at="2026-06-16T00:00:00Z",
            **COMPLETE_FAILURE_POLICY,
        )

        with self.assertRaises(ValueError) as missing_approval:
            activate_recurring_intent(
                intent,
                observer="hermes-runtime",
                approval_ref="",
                activation_surface="hermes-automation",
            )
        with self.assertRaises(ValueError) as missing_surface:
            activate_recurring_intent(
                intent,
                observer="hermes-runtime",
                approval_ref="approval-1",
                activation_surface="",
            )

        self.assertIn("requires a recorded approval reference", str(missing_approval.exception))
        self.assertIn("requires the approved runtime surface that performed it", str(missing_surface.exception))

    def test_overlap_posture_must_be_explicit_before_activation(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")

        self.assertEqual(intent["overlap_posture"]["posture"], "unspecified")
        self.assertFalse(intent["overlap_posture"]["explicit"])
        with self.assertRaises(ValueError) as caught:
            activate_recurring_intent(
                intent,
                observer="hermes-runtime",
                approval_ref="approval-1",
                activation_surface="hermes-automation",
            )

        self.assertIn("activation requires an explicit overlap posture", str(caught.exception))

        intent["lifecycle"]["state"] = "activated"
        intent["lifecycle"]["transitions"] = [
            {
                "transition": "activated",
                "intent_revision_id": intent["revision"]["revision_id"],
                "observer": "hermes-runtime",
                "observer_kind": "approved_runtime_surface",
                "approval_ref": "approval-1",
                "activation_surface": "hermes-automation",
                "reason": "forged",
                "recorded_at": "2026-06-16T02:00:00Z",
            }
        ]
        intent["required_approval"]["granted"] = True

        self.assertIn(
            "an activated recurring intent must carry an explicit overlap posture",
            validate_recurring_intent(intent),
        )


class RecurringIntentRevisionLinkageTests(unittest.TestCase):
    """AC3: every observed occurrence links back to the exact intent revision."""

    def test_revision_id_is_deterministic_and_free_of_wall_clock(self) -> None:
        first = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")
        second = build_recurring_intent(REQUEST, created_at="2027-01-01T23:59:59Z")

        self.assertNotEqual(first["intent_id"], second["intent_id"])
        self.assertEqual(first["revision"]["revision_id"], second["revision"]["revision_id"])
        self.assertEqual(first["revision"]["digest_algorithm"], "sha256")
        self.assertNotIn("created_at", first["revision"]["digest_inputs"])
        self.assertNotIn("updated_at", first["revision"]["digest_inputs"])
        self.assertNotIn("revision.revised_at", first["revision"]["digest_inputs"])

    def test_occurrence_names_the_exact_revision_it_ran_under(self) -> None:
        activated = _activated_intent()

        recorded = record_recurring_intent_occurrence(
            activated,
            runtime_run_ref="run-42",
            runtime_surface="hermes-runtime",
            observer="hermes-runtime",
            observed_at="2026-06-17T00:00:00Z",
        )

        occurrence = recorded["occurrences"][0]
        self.assertEqual(occurrence["intent_revision_id"], recorded["revision"]["revision_id"])
        self.assertEqual(occurrence["runtime_run"], {"surface": "hermes-runtime", "run_ref": "run-42"})
        self.assertEqual(occurrence["evidence_authority"], "linked_runtime_run")
        self.assertIn("linked runtime run owns this execution evidence", occurrence["claim_boundary"])
        self.assertEqual(recorded["observation_status"], "prepared")
        self.assertEqual(summarize_recurring_intent(recorded)["current_revision_occurrence_count"], 1)
        self.assertEqual(validate_recurring_intent(recorded), [])

    def test_a_changed_intent_produces_a_new_revision_that_the_old_occurrence_does_not_cover(self) -> None:
        recorded = record_recurring_intent_occurrence(
            _activated_intent(),
            runtime_run_ref="run-42",
            runtime_surface="hermes-runtime",
            observer="hermes-runtime",
            observed_at="2026-06-17T00:00:00Z",
        )
        original_revision = recorded["revision"]["revision_id"]

        revised = revise_recurring_intent(recorded, revised_at="2026-06-18T00:00:00Z", schedule="every week")

        self.assertNotEqual(revised["revision"]["revision_id"], original_revision)
        self.assertEqual(revised["schedule_intent"]["cadence"], "weekly")
        self.assertEqual(
            [item["revision_id"] for item in revised["revision_history"]],
            [original_revision],
        )
        self.assertEqual(revised["occurrences"][0]["intent_revision_id"], original_revision)
        summary = summarize_recurring_intent(revised)
        self.assertEqual(summary["occurrence_count"], 1)
        self.assertEqual(summary["current_revision_occurrence_count"], 0)
        self.assertEqual(validate_recurring_intent(revised), [])

    def test_revising_an_activated_intent_pauses_it_until_a_new_observer_is_recorded(self) -> None:
        revised = revise_recurring_intent(
            _activated_intent(),
            revised_at="2026-06-18T00:00:00Z",
            owner="someone-else",
            owner_kind="human",
        )

        self.assertEqual(revised["lifecycle"]["state"], "paused")
        self.assertEqual(revised["lifecycle"]["transitions"][-1]["transition"], "paused_by_revision")
        self.assertFalse(revised["required_approval"]["granted"])
        self.assertEqual(revised["required_approval"]["approval_ref"], "")
        with self.assertRaises(ValueError):
            record_recurring_intent_occurrence(
                revised,
                runtime_run_ref="run-43",
                runtime_surface="hermes-runtime",
                observer="hermes-runtime",
            )

    def test_a_revision_that_changes_nothing_is_refused(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")

        with self.assertRaises(ValueError) as caught:
            revise_recurring_intent(intent, revised_at="2026-06-18T00:00:00Z", owner="")

        self.assertIn("must change at least one meaningful field", str(caught.exception))

    def test_occurrence_naming_an_unknown_revision_is_refused(self) -> None:
        recorded = record_recurring_intent_occurrence(
            _activated_intent(),
            runtime_run_ref="run-42",
            runtime_surface="hermes-runtime",
            observer="hermes-runtime",
            observed_at="2026-06-17T00:00:00Z",
        )
        recorded["occurrences"][0]["intent_revision_id"] = "rev-0000000000000000"

        self.assertIn(
            "$.occurrences[0] names unknown intent revision rev-0000000000000000",
            validate_recurring_intent(recorded),
        )

    def test_occurrence_without_a_runtime_run_reference_is_refused(self) -> None:
        activated = _activated_intent()

        with self.assertRaises(ValueError) as caught:
            record_recurring_intent_occurrence(
                activated,
                runtime_run_ref="",
                runtime_surface="hermes-runtime",
                observer="hermes-runtime",
            )

        self.assertIn("occurrence requires a runtime run reference", str(caught.exception))

        recorded = record_recurring_intent_occurrence(
            activated,
            runtime_run_ref="run-42",
            runtime_surface="hermes-runtime",
            observer="hermes-runtime",
            observed_at="2026-06-17T00:00:00Z",
        )
        recorded["occurrences"][0]["runtime_run"] = {"surface": "hermes-runtime", "run_ref": ""}

        self.assertIn(
            "$.occurrences[0] must link a runtime run reference: preparation is never execution",
            validate_recurring_intent(recorded),
        )

    def test_the_same_runtime_run_cannot_be_linked_twice(self) -> None:
        recorded = record_recurring_intent_occurrence(
            _activated_intent(),
            runtime_run_ref="run-42",
            runtime_surface="hermes-runtime",
            observer="hermes-runtime",
            observed_at="2026-06-17T00:00:00Z",
        )

        with self.assertRaises(ValueError) as caught:
            record_recurring_intent_occurrence(
                recorded,
                runtime_run_ref="run-42",
                runtime_surface="hermes-runtime",
                observer="hermes-runtime",
                observed_at="2026-06-18T00:00:00Z",
            )

        self.assertIn("runtime run run-42 is already linked", str(caught.exception))

    def test_retained_occurrences_are_bounded_without_losing_the_recorded_total(self) -> None:
        record = _activated_intent()
        for index in range(RETAINED_OCCURRENCE_LIMIT + 5):
            record = record_recurring_intent_occurrence(
                record,
                runtime_run_ref=f"run-{index}",
                runtime_surface="hermes-runtime",
                observer="hermes-runtime",
                observed_at="2026-06-17T00:00:00Z",
            )

        self.assertEqual(len(record["occurrences"]), RETAINED_OCCURRENCE_LIMIT)
        self.assertEqual(record["occurrences_recorded_total"], RETAINED_OCCURRENCE_LIMIT + 5)
        self.assertEqual(record["occurrences"][-1]["runtime_run"]["run_ref"], f"run-{RETAINED_OCCURRENCE_LIMIT + 4}")
        summary = summarize_recurring_intent(record)
        self.assertEqual(summary["occurrence_count"], RETAINED_OCCURRENCE_LIMIT + 5)
        self.assertEqual(summary["retained_occurrence_count"], RETAINED_OCCURRENCE_LIMIT)
        self.assertEqual(validate_recurring_intent(record), [])

        record["occurrences_recorded_total"] = 1

        self.assertIn(
            "occurrences_recorded_total must not be lower than the retained occurrence count",
            validate_recurring_intent(record),
        )

    def test_editing_a_meaningful_field_without_bumping_the_revision_is_refused(self) -> None:
        intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")
        intent["schedule_intent"]["cadence"] = "monthly"

        rendered = "; ".join(validate_recurring_intent(intent))

        self.assertIn("revision.revision_id must be the digest of the intent's meaningful fields", rendered)
        self.assertIn(recurring_intent_revision_id(intent), rendered)


class RecurringIntentStoreTests(unittest.TestCase):
    def test_store_round_trips_updates_and_validates(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            intent = build_recurring_intent(
                REQUEST,
                owner="demo",
                owner_kind="human",
                created_at="2026-06-16T00:00:00Z",
                **COMPLETE_FAILURE_POLICY,
            )

            written = write_recurring_intent(paths, intent)

            self.assertEqual(show_recurring_intent(paths, written["intent_id"])["title"], written["title"])
            self.assertEqual(len(list_recurring_intents(paths)), 1)
            self.assertTrue(paths.recurring_intents_index_path.exists())
            with self.assertRaises(ValueError):
                write_recurring_intent(paths, intent)

            activated = update_recurring_intent(
                paths,
                activate_recurring_intent(
                    written,
                    observer="hermes-runtime",
                    approval_ref="approval-1",
                    activation_surface="hermes-automation",
                    observed_at="2026-06-16T02:00:00Z",
                ),
            )

            self.assertEqual(show_recurring_intent(paths, activated["intent_id"])["lifecycle"]["state"], "activated")
            self.assertEqual(len(list_recurring_intents(paths)), 1)
            validation = validate_recurring_intent_store(paths)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["intent_count"], 1)
            index = json.loads(paths.recurring_intents_index_path.read_text(encoding="utf-8"))
            self.assertEqual(index["authority"], "cache_only")
            self.assertEqual(index["intents"][0]["lifecycle_state"], "activated")

    def test_update_requires_an_existing_record(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")

            with self.assertRaises(FileNotFoundError):
                update_recurring_intent(paths, intent)

    def test_show_rejects_path_traversal_intent_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)

            for unsafe_id in ("../outside", "/tmp/outside", " unsafe"):
                with self.subTest(unsafe_id=unsafe_id):
                    with self.assertRaises(FileNotFoundError):
                        show_recurring_intent(paths, unsafe_id)

    def test_store_validation_reports_malformed_records(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths_from_tmp(tmp)
            intent = build_recurring_intent(REQUEST, created_at="2026-06-16T00:00:00Z")
            write_recurring_intent(paths, intent)
            broken = paths.recurring_intents_dir / f"{intent['intent_id']}.json"
            broken_record = json.loads(broken.read_text(encoding="utf-8"))
            broken_record["overlap_posture"]["posture"] = "whenever"
            _write_json(broken, broken_record)

            validation = validate_recurring_intent_store(paths)

            self.assertFalse(validation["ok"])
            self.assertIn("unsupported overlap_posture.posture: whenever", " ".join(validation["errors"]))


class RecurringIntentCliTests(unittest.TestCase):
    def test_cli_previews_saves_activates_and_links_one_occurrence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            base = ["--omh-home", str(omh_home), "ops"]

            status, stdout, stderr = run_cli(base + ["recurring-intent", REQUEST, "--dry-run"])

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            preview = json.loads(stdout)
            self.assertEqual(preview["schema_version"], "hermes_recurring_intent_preview/v1")
            self.assertTrue(preview["preview_only"])
            self.assertFalse(preview["saved"])
            self.assertFalse(preview["save"]["requires_user_command"])
            self.assertFalse(preview["store"]["written"])
            self.assertFalse((omh_home / "hermes-ops").exists())
            self.assertTrue(preview["boundary"]["omh_runs_no_scheduler"])
            self.assertFalse(preview["boundary"]["occurrence_executed_by_omh"])
            self.assertEqual(preview["intent"]["lifecycle"]["state"], "paused")

            status, stdout, stderr = run_cli(
                base
                + [
                    "recurring-intent",
                    REQUEST,
                    "--owner",
                    "demo",
                    "--owner-kind",
                    "human",
                    *COMPLETE_FAILURE_POLICY_CLI_ARGS,
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            saved = json.loads(stdout)
            self.assertEqual(saved["schema_version"], "omh_ops_recurring_intent_result/v1")
            self.assertTrue(saved["store"]["written"])
            intent_id = saved["intent"]["intent_id"]
            revision_id = saved["intent"]["revision"]["revision_id"]
            self.assertTrue((omh_home / "hermes-ops" / "recurring-intents" / "intents" / f"{intent_id}.json").exists())

            status, stdout, stderr = run_cli(
                base
                + [
                    "recurring-intent-occurrence",
                    intent_id,
                    "--runtime-run-ref",
                    "run-42",
                    "--runtime-surface",
                    "hermes-runtime",
                    "--observer",
                    "hermes-runtime",
                ]
            )

            self.assertNotEqual(status, 0)
            self.assertIn("a paused recurring intent cannot record an occurrence", stderr)

            status, stdout, stderr = run_cli(
                base
                + [
                    "recurring-intent-activate",
                    intent_id,
                    "--observer",
                    "hermes-runtime",
                    "--approval-ref",
                    "approval-1",
                    "--activation-surface",
                    "hermes-automation",
                ]
            )

            self.assertEqual(status, 0, stderr)
            activated = json.loads(stdout)["intent"]
            self.assertEqual(activated["lifecycle"]["state"], "activated")
            self.assertEqual(activated["lifecycle"]["transitions"][-1]["observer"], "hermes-runtime")
            self.assertEqual(activated["lifecycle"]["transitions"][-1]["approval_ref"], "approval-1")

            status, stdout, stderr = run_cli(
                base
                + [
                    "recurring-intent-occurrence",
                    intent_id,
                    "--runtime-run-ref",
                    "run-42",
                    "--runtime-surface",
                    "hermes-runtime",
                    "--observer",
                    "hermes-runtime",
                ]
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["intent"]["occurrences"][0]["intent_revision_id"], revision_id)

            status, stdout, stderr = run_cli(base + ["recurring-intent-revise", intent_id, "--schedule", "every week"])

            self.assertEqual(status, 0, stderr)
            revised = json.loads(stdout)["intent"]
            self.assertNotEqual(revised["revision"]["revision_id"], revision_id)
            self.assertEqual(revised["lifecycle"]["state"], "paused")

            status, stdout, stderr = run_cli(base + ["recurring-intent-list"])

            self.assertEqual(status, 0, stderr)
            listing = json.loads(stdout)
            self.assertEqual(listing["schema_version"], "omh_ops_recurring_intent_list/v1")
            self.assertEqual(listing["intents"][0]["occurrence_count"], 1)
            self.assertEqual(listing["intents"][0]["current_revision_occurrence_count"], 0)

            status, stdout, stderr = run_cli(base + ["recurring-intent-show", intent_id])

            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["intent"]["intent_id"], intent_id)

            status, stdout, stderr = run_cli(base + ["validate"])

            self.assertEqual(status, 0, stderr)
            validation = json.loads(stdout)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["recurring_intents"]["intent_count"], 1)

    def test_cli_defaults_to_plain_text_for_people(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            base = ["--omh-home", str(omh_home), "ops"]

            status, stdout, stderr = run_cli(base + ["recurring-intent", REQUEST, "--dry-run"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertFalse(stdout.lstrip().startswith("{"))
            self.assertIn("lifecycle: paused", stdout)
            self.assertIn("overlap posture: unspecified", stdout)
            self.assertIn("OMH runs no scheduler", stdout)

            status, stdout, stderr = run_cli(base + ["recurring-intent-list"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertEqual(stdout.strip(), "No recurring intents recorded.")

    def test_cli_rejects_a_traversal_intent_id(self) -> None:
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(Path(tmp) / ".omh"), "ops"]

            status, _stdout, stderr = run_cli(base + ["recurring-intent-show", "../outside"])

            self.assertNotEqual(status, 0)
            self.assertIn("outside", stderr)


def _activated_intent() -> dict:
    intent = build_recurring_intent(
        REQUEST,
        owner="demo",
        owner_kind="human",
        created_at="2026-06-16T00:00:00Z",
        **COMPLETE_FAILURE_POLICY,
    )
    return activate_recurring_intent(
        intent,
        observer="hermes-runtime",
        approval_ref="approval-1",
        activation_surface="hermes-automation",
        observed_at="2026-06-16T02:00:00Z",
    )


def _write_json(path: Path, record: dict) -> None:
    # Windows portability: these bytes are read back and compared, so they must
    # not gain CRLF line endings from Path.write_text.
    from omh.local_store import atomic_write_text

    atomic_write_text(path, json.dumps(record, indent=2, sort_keys=True) + "\n")


def _paths_from_tmp(tmp: str) -> OmhPaths:
    root = Path(tmp)
    return OmhPaths(root / ".omh", root / ".hermes")


if __name__ == "__main__":
    unittest.main()
