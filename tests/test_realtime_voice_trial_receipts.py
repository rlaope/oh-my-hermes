"""`realtime_voice_trial_receipt/v1` (issue #1426).

Grouped by success criterion: the schema and validator over trial identity,
requested-versus-observed configuration, per-turn milestones, integrity checks,
fallback, interruption, safety, evidence class, and privacy; latency that only
a complete, unsplit, singly-referenced turn earns; the rejections the issue
names one by one; the hold and block states that must survive rather than
becoming a pass; the fallback answer that reports both paths without promoting
the requested one; the spoken tool-safety rules; two transports through one
code path; the six separated chat and status states; and the neighbouring
records that must stay readable without being promoted.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _credential_fixtures import AWS_ACCESS_KEY_ID
from _local_package import load_local_package

load_local_package()
from omh.quality.routing_precision import ROUTING_INTERVENTION_CASES, ROUTING_PRECISION_CASES
from omh.routing.chat import route_chat_message
from omh.routing.policy import REALTIME_VOICE_CONNECTOR_READINESS_PHRASES
from omh.routing.recommend import _WHOLE_PHRASE_ONLY_TRIGGER_TOKENS
from omh.skills.catalog import builtin_definitions
from omh.workflows.realtime_voice_trial_receipts import (
    ENVIRONMENT_FACETS,
    READINESS_DIMENSIONS,
    READINESS_STATE_KEYS,
    REALTIME_VOICE_READINESS_SCHEMA_VERSION,
    REALTIME_VOICE_TRIAL_RECEIPT_KEYS,
    REALTIME_VOICE_TRIAL_RECEIPT_SCHEMA_VERSION,
    REALTIME_VOICE_TRIAL_STALE_AFTER_SECONDS,
    REALTIME_VOICE_TURN_SCHEMA_VERSION,
    TURN_MILESTONES,
    RealtimeVoiceTrialError,
    answer_realtime_voice_readiness,
    build_prepared_realtime_voice_chat_state,
    build_realtime_voice_trial_receipt,
    build_realtime_voice_turn,
    demo_realtime_voice_trials,
    preserve_realtime_voice_trial_receipt,
    realtime_voice_readiness_errors,
    realtime_voice_trial_receipt_fingerprint,
    realtime_voice_trial_receipt_id,
    turn_latency,
    validate_realtime_voice_trial_receipt,
    validate_realtime_voice_turn,
    voice_fallback,
    voice_stack,
    voice_tool_attempt,
)
from omh.wrapper.contract import build_chat_interaction_payload

_CLEAN_INTEGRITY = {
    "onset": "preserved",
    "segmentation": "intact",
    "dispatch_count": 1,
    "input_completeness": "complete",
    "max_duration_behavior": "not_reached",
    "mute_resume": "not_exercised",
    "transcript_outcome": "final",
}
_CLEAN_STREAMING = {
    "barge_in": "honored",
    "queued_audio": "discarded",
    "replay": "none",
    "backpressure": "none",
}
_CLEAN_MILESTONES = dict(zip(TURN_MILESTONES, (0, 1200, 1320, 1400, 1560, 4000)))


def _turn(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "turn_id": "turn-1",
        "timing_reference": "host_monotonic",
        "milestones": dict(_CLEAN_MILESTONES),
        "terminal_status": "completed",
        "integrity": dict(_CLEAN_INTEGRITY),
        "streaming": dict(_CLEAN_STREAMING),
    }
    kwargs.update(overrides)
    return build_realtime_voice_turn(**kwargs)


def _receipt(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "trial_ref": "trial-1",
        "connector_ref": "voice-connector-a",
        "connector_revision": "build-9f2c14",
        "profile_ref": "support-desk",
        "test_condition": "actual_environment",
        "environment": dict.fromkeys(ENVIRONMENT_FACETS, "intended"),
        "requested_stack": voice_stack(provider="provider-a", model="voice-model-a", transport="webrtc"),
        "observed_stack": voice_stack(provider="provider-a", model="voice-model-a", transport="webrtc"),
        "observed_stack_evidence": "measured",
        "trial_started_at": "2026-09-09T09:00:00Z",
        "trial_ended_at": "2026-09-09T09:04:00Z",
        "turns": (_turn(),),
        "tool_safety": (
            voice_tool_attempt(
                attempt_ref="attempt-1",
                action_class="read_only",
                confidence_state="confident",
                confirmation_state="not_required",
                policy_decision="allowed",
                tool_result_ref="result-1",
            ),
        ),
    }
    kwargs.update(overrides)
    return build_realtime_voice_trial_receipt(**kwargs)


class SchemaTests(unittest.TestCase):
    def test_a_complete_trial_validates_and_reads_ready(self) -> None:
        receipt = _receipt()

        self.assertEqual(receipt["schema_version"], "realtime_voice_trial_receipt/v1")
        self.assertEqual(sorted(receipt), sorted(REALTIME_VOICE_TRIAL_RECEIPT_KEYS))
        self.assertEqual(receipt["turns"][0]["schema_version"], "realtime_voice_turn/v1")
        self.assertTrue(receipt["receipt_id"].startswith("rvt_"))
        self.assertEqual(validate_realtime_voice_trial_receipt(receipt), [])

        answer = answer_realtime_voice_readiness(receipt)
        self.assertEqual(answer["schema_version"], "realtime_voice_readiness/v1")
        self.assertEqual(answer["verdict"], "ready")
        self.assertEqual(sorted(answer["dimensions"]), sorted(READINESS_DIMENSIONS))
        self.assertEqual(realtime_voice_readiness_errors(answer), [])

    def test_receipt_identity_is_the_trial_not_the_reading(self) -> None:
        first = _receipt()
        second = _receipt()
        self.assertEqual(first["receipt_id"], second["receipt_id"])
        self.assertNotEqual(first["receipt_id"], _receipt(trial_ref="trial-2")["receipt_id"])
        relabelled = {**first, "connector_revision": "build-other"}
        self.assertIn(
            "realtime_voice_trial_receipt receipt_id does not match the trial it names",
            validate_realtime_voice_trial_receipt(relabelled),
        )

    def test_a_consumer_carries_the_receipt_unchanged(self) -> None:
        receipt = _receipt()
        before = realtime_voice_trial_receipt_fingerprint(receipt)
        preserved = preserve_realtime_voice_trial_receipt(receipt)
        self.assertEqual(realtime_voice_trial_receipt_fingerprint(preserved), before)
        self.assertEqual(json.dumps(preserved, sort_keys=True), json.dumps(receipt, sort_keys=True))

    def test_unsupported_keys_are_refused_at_every_level(self) -> None:
        self.assertEqual(
            validate_realtime_voice_trial_receipt({**_receipt(), "transcript": "hello"})[0][:52],
            "realtime_voice_trial_receipt has unsupported keys: [",
        )
        self.assertTrue(
            any("unsupported keys" in issue for issue in validate_realtime_voice_turn({**_turn(), "audio": "x"}))
        )
        with self.assertRaises(RealtimeVoiceTrialError):
            _receipt(
                tool_safety=(
                    {
                        **voice_tool_attempt(attempt_ref="a1", action_class="read_only"),
                        "tool_arguments": {"amount": 100},
                    },
                )
            )


class LatencyEligibilityTests(unittest.TestCase):
    def test_latency_needs_one_timing_reference(self) -> None:
        untimed = _turn(timing_reference="unavailable", milestones=dict.fromkeys(TURN_MILESTONES, None))
        reading = turn_latency(untimed)
        self.assertFalse(reading["eligible"])
        self.assertEqual(reading["basis"], "no_declared_timing_reference")
        self.assertIsNone(reading["first_audible_output_ms"])
        # Milestones without a reference are refused outright, not merely ignored.
        with self.assertRaises(RealtimeVoiceTrialError) as mixed:
            _turn(timing_reference="unavailable")
        self.assertIn("one declared timing reference", str(mixed.exception))

    def test_latency_needs_a_complete_milestone_sequence(self) -> None:
        partial = _turn(milestones={**_CLEAN_MILESTONES, "final_transcript": None, "first_output_audio": None})
        reading = turn_latency(partial)
        self.assertFalse(reading["eligible"])
        self.assertEqual(reading["basis"], "incomplete_milestone_sequence")

    def test_latency_needs_an_unsplit_turn(self) -> None:
        split = _turn(integrity={**_CLEAN_INTEGRITY, "segmentation": "premature_split"})
        self.assertEqual(turn_latency(split)["basis"], "segmentation_premature_split")
        merged = _turn(integrity={**_CLEAN_INTEGRITY, "segmentation": "unintended_merge"})
        self.assertEqual(turn_latency(merged)["basis"], "segmentation_unintended_merge")

    def test_an_eligible_turn_reports_measured_offsets(self) -> None:
        reading = turn_latency(_turn())
        self.assertTrue(reading["eligible"])
        self.assertEqual(reading["basis"], "measured")
        self.assertEqual(reading["first_audible_output_ms"], 360)
        self.assertEqual(reading["final_transcript_ms"], 120)

    def test_a_non_monotonic_sequence_is_refused(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError) as reversed_order:
            _turn(milestones={**_CLEAN_MILESTONES, "first_output_audio": 100})
        self.assertIn("is not monotonic", str(reversed_order.exception))

    def test_an_unheld_latency_summary_names_its_basis_instead_of_zero(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(turns=(_turn(timing_reference="unavailable", milestones=dict.fromkeys(TURN_MILESTONES, None)),))
        )
        self.assertEqual(answer["latency"]["eligible_turn_count"], 0)
        self.assertIsNone(answer["latency"]["first_audible_output_ms_max"])
        self.assertEqual(answer["latency"]["basis"], "no_turn_earned_a_latency_reading")
        self.assertEqual(answer["dimensions"]["latency"]["state"], "hold")


class RejectedFixtureTests(unittest.TestCase):
    def test_clipped_onset_blocks_instead_of_passing(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(turns=(_turn(integrity={**_CLEAN_INTEGRITY, "onset": "clipped"}),))
        )
        self.assertEqual(answer["dimensions"]["turn_integrity"]["state"], "block")
        self.assertIn("turn-1: speech_onset_clipped", answer["dimensions"]["turn_integrity"]["reasons"])
        self.assertEqual(answer["verdict"], "blocked")

    def test_premature_endpoint_and_unintended_merge_block(self) -> None:
        for segmentation, reason in (
            ("premature_split", "turn-1: turn_split_prematurely"),
            ("unintended_merge", "turn-1: turns_merged_unintentionally"),
        ):
            with self.subTest(segmentation=segmentation):
                answer = answer_realtime_voice_readiness(
                    _receipt(turns=(_turn(integrity={**_CLEAN_INTEGRITY, "segmentation": segmentation}),))
                )
                self.assertEqual(answer["dimensions"]["turn_integrity"]["state"], "block")
                self.assertIn(reason, answer["dimensions"]["turn_integrity"]["reasons"])

    def test_multiple_dispatch_for_one_utterance_blocks(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(turns=(_turn(integrity={**_CLEAN_INTEGRITY, "dispatch_count": 2}),))
        )
        self.assertIn(
            "turn-1: multiple_dispatch_for_one_utterance",
            answer["dimensions"]["turn_integrity"]["reasons"],
        )
        self.assertEqual(answer["verdict"], "blocked")

    def test_truncated_input_and_overflow_block(self) -> None:
        truncated = answer_realtime_voice_readiness(
            _receipt(
                turns=(
                    _turn(
                        integrity={**_CLEAN_INTEGRITY, "input_completeness": "truncated", "max_duration_behavior": "silently_truncated"},
                        terminal_status="truncated",
                    ),
                )
            )
        )
        reasons = truncated["dimensions"]["turn_integrity"]["reasons"]
        self.assertIn("turn-1: input_truncated", reasons)
        self.assertIn("turn-1: max_duration_truncated_silently", reasons)
        overflow = answer_realtime_voice_readiness(
            _receipt(turns=(_turn(streaming={**_CLEAN_STREAMING, "backpressure": "overflowed"}),))
        )
        self.assertIn("turn-1: output_overflowed", overflow["dimensions"]["turn_integrity"]["reasons"])
        self.assertIn("turn-1: backpressure_overflowed", overflow["dimensions"]["interruption"]["reasons"])

    def test_a_duplicate_turn_is_a_structural_refusal(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError) as duplicate:
            _receipt(turns=(_turn(), _turn()))
        self.assertIn("one accepted utterance is one turn", str(duplicate.exception))

    def test_replay_after_audible_output_blocks_interruption(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(turns=(_turn(streaming={**_CLEAN_STREAMING, "replay": "replayed_from_start"}),))
        )
        self.assertEqual(answer["dimensions"]["interruption"]["state"], "block")
        self.assertIn("turn-1: replayed_after_audible_output", answer["dimensions"]["interruption"]["reasons"])

    def test_an_ignored_barge_in_blocks_interruption(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(turns=(_turn(streaming={**_CLEAN_STREAMING, "barge_in": "ignored"}),))
        )
        self.assertIn("turn-1: barge_in_ignored", answer["dimensions"]["interruption"]["reasons"])

    def test_a_stale_trial_blocks_rather_than_passing(self) -> None:
        receipt = _receipt()
        fresh = answer_realtime_voice_readiness(receipt, now="2026-09-09T10:00:00Z")
        self.assertEqual(fresh["verdict"], "ready")
        stale = answer_realtime_voice_readiness(receipt, now="2026-09-10T10:00:00Z")
        self.assertEqual(stale["verdict"], "blocked")
        self.assertEqual(
            stale["verdict_reasons"],
            [f"trial_is_stale_after_{REALTIME_VOICE_TRIAL_STALE_AFTER_SECONDS}_seconds"],
        )

    def test_a_cross_profile_or_cross_revision_trial_blocks(self) -> None:
        receipt = _receipt()
        other_profile = answer_realtime_voice_readiness(receipt, profile_ref="sales-desk")
        self.assertEqual(other_profile["verdict"], "blocked")
        self.assertIn("trial_observed_another_profile", other_profile["verdict_reasons"][0])
        other_build = answer_realtime_voice_readiness(receipt, connector_revision="build-other")
        self.assertEqual(other_build["verdict"], "blocked")
        self.assertIn("trial_observed_another_connector_revision", other_build["verdict_reasons"][0])

    def test_a_requested_model_cannot_be_filed_as_observed(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError) as echoed:
            _receipt(observed_stack_evidence="unavailable")
        self.assertIn("a requested setting is not an observed one", str(echoed.exception))
        with self.assertRaises(RealtimeVoiceTrialError) as empty:
            _receipt(observed_stack=voice_stack(), observed_stack_evidence="measured")
        self.assertIn("names at least one observed setting", str(empty.exception))

    def test_an_unobserved_stack_holds_instead_of_passing(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(observed_stack=voice_stack(), observed_stack_evidence="unavailable", turns=(_turn(),))
        )
        self.assertEqual(answer["verdict"], "hold")
        self.assertIn("requested_stack_was_not_observed", answer["verdict_reasons"])
        self.assertFalse(answer["evidence_gate"]["requested_stack_observed"])

    def test_an_observed_stack_that_is_not_the_requested_one_holds(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(observed_stack=voice_stack(provider="provider-a", model="fallback-model-a", transport="webrtc"))
        )
        self.assertEqual(answer["verdict"], "hold")
        self.assertIn("requested_stack_was_not_observed", answer["verdict_reasons"])


class HoldStateTests(unittest.TestCase):
    def test_unavailable_transcription_and_playback_milestones_hold(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(
                turns=(
                    _turn(
                        milestones={**_CLEAN_MILESTONES, "final_transcript": None, "first_output_audio": None, "playback_end": None},
                        integrity={**_CLEAN_INTEGRITY, "transcript_outcome": "unobserved"},
                        terminal_status="unobserved",
                    ),
                )
            )
        )
        self.assertEqual(answer["dimensions"]["latency"]["state"], "hold")
        self.assertEqual(answer["dimensions"]["turn_integrity"]["state"], "hold")
        self.assertEqual(answer["verdict"], "hold")
        self.assertFalse(answer["states"]["session_completed"])

    def test_a_synthetic_trial_never_reads_ready(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(
                test_condition="synthetic_fixture",
                environment=dict.fromkeys(ENVIRONMENT_FACETS, "simulated"),
            )
        )
        self.assertEqual(answer["verdict"], "hold")
        self.assertIn("synthetic_evidence_only", answer["verdict_reasons"])
        self.assertTrue(answer["states"]["synthetic_trial_passed"])
        self.assertFalse(answer["states"]["actual_environment_trial_passed"])
        # A synthetic fixture cannot claim the intended room either.
        with self.assertRaises(RealtimeVoiceTrialError) as claimed:
            _receipt(test_condition="synthetic_fixture")
        self.assertIn("never observed the intended room", str(claimed.exception))
        # And the answer validator refuses a hand-built ready synthetic verdict.
        self.assertIn(
            "realtime_voice_readiness a synthetic trial is never ready for a real room, microphone, or network",
            realtime_voice_readiness_errors({**answer, "verdict": "ready"}),
        )

    def test_a_hand_built_ready_verdict_cannot_skip_the_evidence_gate(self) -> None:
        held = answer_realtime_voice_readiness(
            _receipt(environment={**dict.fromkeys(ENVIRONMENT_FACETS, "intended"), "network": "unobserved"})
        )
        self.assertIn(
            "realtime_voice_readiness ready requires the intended room, microphone, network, and transport",
            realtime_voice_readiness_errors({**held, "verdict": "ready"}),
        )
        unobserved_stack = answer_realtime_voice_readiness(
            _receipt(observed_stack=voice_stack(), observed_stack_evidence="unavailable")
        )
        self.assertIn(
            "realtime_voice_readiness ready requires the requested stack to be the one that was observed",
            realtime_voice_readiness_errors({**unobserved_stack, "verdict": "ready"}),
        )

    def test_missing_actual_environment_coverage_holds_and_names_the_facets(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(environment={**dict.fromkeys(ENVIRONMENT_FACETS, "intended"), "room": "simulated", "network": "unobserved"})
        )
        self.assertEqual(answer["verdict"], "hold")
        self.assertEqual(answer["evidence_gate"]["actual_environment_facets_missing"], ["room", "network"])
        self.assertIn("room_not_the_intended_one", answer["verdict_reasons"])
        self.assertIn("network_not_the_intended_one", answer["verdict_reasons"])
        self.assertFalse(answer["states"]["actual_environment_trial_passed"])

    def test_unsupported_barge_in_holds_rather_than_passing_or_blocking(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(turns=(_turn(streaming={**_CLEAN_STREAMING, "barge_in": "unsupported", "queued_audio": "not_applicable"}),))
        )
        self.assertEqual(answer["dimensions"]["interruption"]["state"], "hold")
        self.assertIn("turn-1: barge_in_unsupported", answer["dimensions"]["interruption"]["reasons"])
        self.assertEqual(answer["verdict"], "hold")

    def test_absent_tool_safety_evidence_holds(self) -> None:
        answer = answer_realtime_voice_readiness(_receipt(tool_safety=()))
        self.assertEqual(answer["dimensions"]["tool_safety"]["state"], "hold")
        self.assertEqual(answer["dimensions"]["tool_safety"]["reasons"], ["no_spoken_tool_attempt_observed"])
        self.assertEqual(answer["verdict"], "hold")
        self.assertFalse(answer["states"]["tool_action_observed"])

    def test_a_trial_with_no_turns_holds_every_turn_dimension(self) -> None:
        answer = answer_realtime_voice_readiness(_receipt(turns=()))
        for name in ("turn_integrity", "latency", "interruption"):
            with self.subTest(dimension=name):
                self.assertEqual(answer["dimensions"][name]["state"], "hold")
                self.assertEqual(answer["dimensions"][name]["reasons"], ["no_turn_observed"])
        self.assertFalse(answer["states"]["voice_turn_observed"])


class FallbackTests(unittest.TestCase):
    def test_a_fallback_reports_both_paths_without_promoting_the_requested_one(self) -> None:
        receipt = _receipt(
            fallback=voice_fallback(
                occurred=True,
                requested_path_outcome="failed",
                fallback_path_ref="half-duplex-turn-taking",
                reason="realtime duplex stream dropped mid-response",
                relative_to_audible="after_audible",
            )
        )
        answer = answer_realtime_voice_readiness(receipt)

        self.assertEqual(answer["dimensions"]["fallback"]["state"], "block")
        self.assertIn(
            "requested_path_failed: realtime duplex stream dropped mid-response",
            answer["dimensions"]["fallback"]["reasons"],
        )
        self.assertIn("fallback_path_served: half-duplex-turn-taking", answer["dimensions"]["fallback"]["reasons"])
        self.assertIn("fallback_after_audio_became_audible", answer["dimensions"]["fallback"]["reasons"])
        self.assertFalse(answer["fallback"]["requested_path_ready"])
        self.assertEqual(answer["fallback"]["fallback_path_ref"], "half-duplex-turn-taking")
        self.assertEqual(answer["verdict"], "blocked")

    def test_a_fallback_success_cannot_be_recorded_as_requested_path_success(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError) as promoted:
            _receipt(
                fallback=voice_fallback(
                    occurred=True,
                    requested_path_outcome="succeeded",
                    fallback_path_ref="half-duplex-turn-taking",
                    reason="stream dropped",
                    relative_to_audible="before_audible",
                )
            )
        self.assertIn("never success for the requested voice stack", str(promoted.exception))

    def test_a_fallback_must_say_where_it_sat_against_audible_output(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError) as unplaced:
            _receipt(
                fallback=voice_fallback(
                    occurred=True,
                    requested_path_outcome="failed",
                    fallback_path_ref="half-duplex-turn-taking",
                    reason="stream dropped",
                )
            )
        self.assertIn("before or after audio became audible", str(unplaced.exception))
        with self.assertRaises(RealtimeVoiceTrialError):
            _receipt(fallback=voice_fallback(occurred=False, fallback_path_ref="half-duplex-turn-taking"))


class ToolSafetyTests(unittest.TestCase):
    def test_a_high_impact_action_needs_an_observed_confirmation_or_denial(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(
                tool_safety=(
                    voice_tool_attempt(
                        attempt_ref="attempt-1",
                        action_class="high_impact",
                        confidence_state="confident",
                        confirmation_required=True,
                        confirmation_state="unobserved",
                        policy_decision="deferred",
                    ),
                )
            )
        )
        reasons = answer["dimensions"]["tool_safety"]["reasons"]
        self.assertEqual(answer["dimensions"]["tool_safety"]["state"], "block")
        self.assertIn("attempt-1: high_impact_attempt_without_an_observed_decision", reasons)
        self.assertIn("attempt-1: high_impact_attempt_without_an_observed_confirmation", reasons)

    def test_an_observed_denial_passes_the_dimension(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(
                tool_safety=(
                    voice_tool_attempt(
                        attempt_ref="attempt-1",
                        action_class="high_impact",
                        confidence_state="ambiguous",
                        confirmation_required=True,
                        confirmation_state="refused",
                        policy_decision="denied",
                        denial_reason="spoken command was ambiguous and the confirmation was refused",
                    ),
                )
            )
        )
        self.assertEqual(answer["dimensions"]["tool_safety"]["state"], "pass")
        self.assertTrue(answer["states"]["tool_action_observed"])

    def test_an_ambiguous_or_unconfirmed_command_cannot_be_authorized_execution(self) -> None:
        for overrides, expected in (
            ({"confidence_state": "ambiguous"}, "cannot be reported as authorized execution"),
            ({"confirmation_state": "unobserved"}, "missing or refused confirmation"),
            ({"confirmation_state": "refused"}, "missing or refused confirmation"),
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(RealtimeVoiceTrialError) as refused:
                    _receipt(
                        tool_safety=(
                            voice_tool_attempt(
                                **{
                                    "attempt_ref": "attempt-1",
                                    "action_class": "high_impact",
                                    "confidence_state": "confident",
                                    "confirmation_required": True,
                                    "confirmation_state": "received",
                                    "policy_decision": "allowed",
                                    "tool_result_ref": "result-1",
                                    **overrides,
                                }
                            ),
                        )
                    )
                self.assertIn(expected, str(refused.exception))

    def test_a_high_impact_action_always_requires_confirmation(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError) as unguarded:
            _receipt(
                tool_safety=(
                    voice_tool_attempt(
                        attempt_ref="attempt-1",
                        action_class="high_impact",
                        confidence_state="confident",
                        confirmation_state="not_required",
                        policy_decision="denied",
                        denial_reason="policy blocked it",
                    ),
                )
            )
        self.assertIn("always requires confirmation", str(unguarded.exception))

    def test_a_tool_result_reference_exists_only_for_an_allowed_decision(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError):
            _receipt(
                tool_safety=(
                    voice_tool_attempt(
                        attempt_ref="attempt-1",
                        action_class="read_only",
                        confidence_state="confident",
                        confirmation_state="not_required",
                        policy_decision="deferred",
                        tool_result_ref="result-1",
                    ),
                )
            )


class PrivacyTests(unittest.TestCase):
    def test_raw_phone_numbers_and_participant_identities_are_refused(self) -> None:
        for value in ("+1 415 555 0142", "caller@example.com"):
            with self.subTest(value=value):
                with self.assertRaises(RealtimeVoiceTrialError) as raw:
                    _receipt(profile_ref=value)
                self.assertIn("raw phone number, address, or participant identity", str(raw.exception))

    def test_credentials_and_bodies_are_refused_in_bounded_text(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError) as secret:
            _receipt(
                fallback=voice_fallback(
                    occurred=True,
                    requested_path_outcome="failed",
                    fallback_path_ref="half-duplex-turn-taking",
                    reason=f"gateway rejected {AWS_ACCESS_KEY_ID}",
                    relative_to_audible="before_audible",
                )
            )
        self.assertIn("must not carry credentials", str(secret.exception))
        body = {
            **_receipt(),
            "fallback": {
                **voice_fallback(
                    occurred=True,
                    requested_path_outcome="failed",
                    fallback_path_ref="half-duplex-turn-taking",
                    reason="ok",
                    relative_to_audible="before_audible",
                ),
                "reason": "line one\nline two",
            },
        }
        self.assertTrue(any("one bounded line" in issue for issue in validate_realtime_voice_trial_receipt(body)))

    def test_a_room_or_connector_identity_must_be_an_opaque_reference(self) -> None:
        with self.assertRaises(RealtimeVoiceTrialError):
            _receipt(connector_ref="room: the third floor huddle space")
        with self.assertRaises(RealtimeVoiceTrialError):
            _receipt(requested_stack=voice_stack(provider="provider api_key abc123def456"))


class ProviderNeutralityTests(unittest.TestCase):
    def test_two_transports_travel_the_same_code_path(self) -> None:
        fixtures = demo_realtime_voice_trials()
        webrtc = fixtures["webrtc_actual_environment"]
        telephony = fixtures["telephony_streaming_fallback"]

        self.assertNotEqual(webrtc["requested_stack"]["transport"], telephony["requested_stack"]["transport"])
        self.assertNotEqual(webrtc["requested_stack"]["provider"], telephony["requested_stack"]["provider"])
        self.assertNotEqual(webrtc["requested_stack"]["codec"], telephony["requested_stack"]["codec"])
        for name, receipt in fixtures.items():
            with self.subTest(fixture=name):
                self.assertEqual(validate_realtime_voice_trial_receipt(receipt), [])
                answer = answer_realtime_voice_readiness(receipt)
                self.assertEqual(realtime_voice_readiness_errors(answer), [])
        self.assertEqual(answer_realtime_voice_readiness(webrtc)["verdict"], "ready")
        self.assertEqual(answer_realtime_voice_readiness(telephony)["verdict"], "blocked")
        self.assertEqual(answer_realtime_voice_readiness(fixtures["synthetic_smoke"])["verdict"], "hold")

    def test_no_provider_name_is_hardcoded_in_the_contract(self) -> None:
        import omh.workflows.realtime_voice_trial_receipts as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        vendor_words = ("openai", "deepgram", "elevenlabs", "twilio", "livekit", "azure", "google", "vapi")
        # Only the demo fixtures name any stack at all, and they name opaque
        # placeholders; the validator and verdict never see a vendor.
        for word in vendor_words:
            with self.subTest(word=word):
                self.assertNotIn(word, source.lower())


class SeparatedStateTests(unittest.TestCase):
    def test_the_six_states_are_reported_independently(self) -> None:
        answer = answer_realtime_voice_readiness(
            _receipt(
                test_condition="synthetic_fixture",
                environment=dict.fromkeys(ENVIRONMENT_FACETS, "simulated"),
                tool_safety=(),
            )
        )
        self.assertEqual(sorted(answer["states"]), sorted(READINESS_STATE_KEYS))
        self.assertTrue(answer["states"]["connector_configured"])
        self.assertTrue(answer["states"]["synthetic_trial_passed"])
        self.assertFalse(answer["states"]["actual_environment_trial_passed"])
        self.assertTrue(answer["states"]["voice_turn_observed"])
        self.assertFalse(answer["states"]["tool_action_observed"])
        self.assertTrue(answer["states"]["session_completed"])

    def test_a_prepared_voice_connector_card_observes_nothing(self) -> None:
        payload = build_chat_interaction_payload(
            "realtime voice connector readiness before we adopt it for support calls",
            source="discord",
        )
        state = payload["chat_response"]["state"]
        block = state["realtime_voice_trial"]

        self.assertEqual(payload["chat_response"]["kind"], "external_connector_readiness")
        self.assertEqual(block["receipt_schema"], REALTIME_VOICE_TRIAL_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(block["turn_schema"], REALTIME_VOICE_TURN_SCHEMA_VERSION)
        self.assertEqual(block["readiness_schema"], REALTIME_VOICE_READINESS_SCHEMA_VERSION)
        self.assertEqual(block["readiness_dimensions"], list(READINESS_DIMENSIONS))
        self.assertEqual(block["states"], dict.fromkeys(READINESS_STATE_KEYS, False))
        self.assertEqual(block["network_action"], "none")
        self.assertEqual(block["trial_execution"], "authorized_host_or_connector")
        self.assertEqual(state["evidence_not_observed"][0], "realtime voice trial execution")
        self.assertEqual(build_prepared_realtime_voice_chat_state(), block)

    def test_an_ordinary_connector_card_carries_no_voice_block(self) -> None:
        payload = build_chat_interaction_payload(
            "external tool trial for the weather plugin before adoption", source="discord"
        )
        self.assertNotIn("realtime_voice_trial", payload["chat_response"]["state"])

    def test_the_memory_provider_lane_keeps_its_turns_when_voice_is_mentioned(self) -> None:
        """Two capabilities share one readiness lane without sharing cards.

        `external-connector-readiness` answers both realtime voice adoption
        and optional memory-provider lifecycle, so a message naming one must
        not acquire the other's card. Their vocabularies are disjoint -- the
        memory lane's whole-phrase-only tokens and this lane's voice phrases
        share no token -- and the direction at risk is a memory-provider
        question that happens to say "voice": it reaches the lane, and it
        stays a memory question.
        """
        for message in (
            "memory provider readiness before we enable it",
            "memory provider lifecycle and retention posture",
            "memory provider readiness for the voice assistant",
        ):
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")
                self.assertEqual(payload["chat_response"]["kind"], "external_connector_readiness")
                self.assertNotIn("realtime_voice_trial", payload["chat_response"]["state"])

    def test_the_two_lanes_share_no_trigger_token(self) -> None:
        held_back = _WHOLE_PHRASE_ONLY_TRIGGER_TOKENS["external-connector-readiness"]
        voice_tokens = {
            token
            for phrase in REALTIME_VOICE_CONNECTOR_READINESS_PHRASES
            for token in phrase.replace("-", " ").split()
        }
        self.assertEqual(voice_tokens & held_back, set())


class NeighbouringRecordTests(unittest.TestCase):
    def test_the_connector_lane_names_the_receipt_and_its_boundaries(self) -> None:
        definition = {item.name: item for item in builtin_definitions()}["external-connector-readiness"]
        self.assertTrue(
            any("realtime_voice_trial_receipt/v1" in item for item in definition.expected_outputs)
        )
        self.assertTrue(any("realtime_voice_readiness/v1" in item for item in definition.expected_outputs))
        self.assertTrue(
            any("opens no microphone, call, room, socket, or provider session" in rule for rule in definition.safety_rules)
        )
        self.assertTrue(
            any("never proves the intended room" in rule for rule in definition.safety_rules)
        )
        self.assertTrue(
            any("realtime_voice_trial_receipt/v1" in note for note in definition.recovery_notes)
        )

    def test_voice_and_media_records_cannot_be_promoted(self) -> None:
        definitions = {item.name: item for item in builtin_definitions()}
        voice_rules = definitions["voice-operator"].safety_rules
        self.assertTrue(any("never creates, infers, or upgrades one" in rule for rule in voice_rules))
        media_rules = definitions["media-input-operator"].safety_rules
        self.assertTrue(any("cannot be promoted into one" in rule for rule in media_rules))
        # Both records still declare their own outputs unchanged.
        self.assertTrue(
            any("media_result_manifest/v1" in item for item in definitions["media-input-operator"].expected_outputs)
        )


class RoutingTests(unittest.TestCase):
    def test_realtime_voice_adoption_reaches_the_connector_lane(self) -> None:
        for message in (
            "realtime voice connector readiness before we adopt it for support calls",
            "voice connector trial receipt from the telephony gateway needs a verdict",
            "check the voice turn integrity and barge-in behavior in that trial",
            "실시간 음성 커넥터 준비도를 도입 전에 확인해줘",
        ):
            with self.subTest(message=message):
                decision = route_chat_message(message, source="discord")
                self.assertEqual(decision["selected_skill"], "external-connector-readiness")
                self.assertIn(
                    "direct:realtime_voice_connector_readiness",
                    decision["recommendations"][0]["matched"],
                )

    def test_a_missing_voice_tool_still_belongs_to_toolbelt_readiness(self) -> None:
        decision = route_chat_message("set up a voice tool, the mic connector is not configured yet", source="discord")
        self.assertEqual(decision["selected_skill"], "toolbelt-readiness")

    def test_both_corpora_cover_the_new_lane(self) -> None:
        negatives = {case.id for case in ROUTING_PRECISION_CASES}
        positives = {case.id for case in ROUTING_INTERVENTION_CASES}
        self.assertLessEqual(
            {
                "realtime-voice-phrase-translation-stays-direct",
                "barge-in-definition-stays-direct",
                "voice-memo-file-lookup-stays-a-file-lookup",
                "billing-receipt-question-stays-direct",
            },
            negatives,
        )
        self.assertLessEqual(
            {
                "realtime-voice-adoption-reaches-connector-readiness",
                "voice-trial-receipt-reaches-connector-readiness",
                "voice-turn-integrity-reaches-connector-readiness",
                "korean-realtime-voice-readiness-reaches-connector-readiness",
            },
            positives,
        )


class CommandTests(unittest.TestCase):
    def _write(self, directory: str, receipt: dict[str, object]) -> str:
        path = Path(directory) / "trial.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return str(path)

    def test_plain_text_verdict_reads_without_json(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._write(directory, demo_realtime_voice_trials()["telephony_streaming_fallback"])
            status, stdout, stderr = run_cli(
                ["ops", "realtime-voice-readiness", "--input", path], output_json=False
            )

        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertNotIn("{", stdout)
        self.assertIn("Verdict: blocked (actual_environment)", stdout)
        self.assertIn("fallback: block", stdout)
        self.assertIn("actual_environment_trial_passed: no", stdout)

    def test_json_verdict_carries_the_full_payload(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._write(directory, demo_realtime_voice_trials()["webrtc_actual_environment"])
            status, stdout, _ = run_cli(["ops", "realtime-voice-readiness", "--input", path])

        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "realtime_voice_readiness/v1")
        self.assertEqual(payload["verdict"], "ready")
        self.assertEqual(realtime_voice_readiness_errors(payload), [])

    def test_a_pinned_revision_and_clock_block_a_stale_or_foreign_trial(self) -> None:
        with TemporaryDirectory() as directory:
            path = self._write(directory, demo_realtime_voice_trials()["webrtc_actual_environment"])
            _, stale, _ = run_cli(
                ["ops", "realtime-voice-readiness", "--input", path, "--now", "2026-09-10T10:00:00Z"]
            )
            _, foreign, _ = run_cli(
                ["ops", "realtime-voice-readiness", "--input", path, "--connector-revision", "build-other"]
            )

        self.assertEqual(json.loads(stale)["verdict"], "blocked")
        self.assertEqual(json.loads(foreign)["verdict"], "blocked")

    def test_an_invalid_receipt_is_refused_with_its_violations(self) -> None:
        with TemporaryDirectory() as directory:
            broken = {**demo_realtime_voice_trials()["synthetic_smoke"], "transcript": "hello"}
            path = self._write(directory, broken)
            status, stdout, stderr = run_cli(["ops", "realtime-voice-readiness", "--input", path])

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unsupported keys", stderr)


class IdentityHelperTests(unittest.TestCase):
    def test_receipt_id_helper_matches_the_builder(self) -> None:
        receipt = _receipt()
        self.assertEqual(realtime_voice_trial_receipt_id(receipt), receipt["receipt_id"])


if __name__ == "__main__":
    unittest.main()
