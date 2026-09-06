from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding.context_safety import (  # noqa: E402
    build_coding_progress_reporting_policy,
    coding_progress_policy_enforcement,
)
from omh.coding.hermes_harness import (  # noqa: E402
    build_hermes_coding_harness,
    validate_hermes_coding_harness,
)
from omh.coding.wait_strategy import (  # noqa: E402
    EXECUTION_WAIT_BINDING_SCHEMA_VERSION,
    EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION,
    EXECUTION_WAIT_TRACE_SCHEMA_VERSION,
    MIDPOINT_PEEK_BUDGET,
    WAIT_HOST_CAPABILITIES,
    WAIT_MECHANISMS,
    WAIT_OBSERVATION_MODES,
    WAIT_TERMINAL_STATES,
    arm_wait_binding,
    build_execution_wait_strategy,
    consume_wait_completion,
    evaluate_wait_trace,
    select_wait_mechanism,
    validate_execution_wait_strategy,
    wait_mechanism_ladder,
    wait_strategy_policy_reference,
)
from omh.skills.packaging import (  # noqa: E402
    builtin_skill_reference_templates,
    builtin_skill_templates,
)

FULL_CAPABILITIES = tuple(WAIT_HOST_CAPABILITIES)


def _strategy(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "work_kind": "command",
        "expected_duration_class": "long_running",
        "handle_kind": "background_process",
        "handle_ref": "bg-1",
        "condition": "the command exits",
        "host_capabilities": FULL_CAPABILITIES,
        "cancellation_path": "stop bg-1",
    }
    kwargs.update(overrides)
    return build_execution_wait_strategy(**kwargs)  # type: ignore[arg-type]


class WaitMechanismSelectionTests(unittest.TestCase):
    def test_short_command_runs_once_in_the_foreground(self) -> None:
        selection = select_wait_mechanism(
            work_kind="command",
            expected_duration_class="within_one_call",
            host_capabilities=FULL_CAPABILITIES,
        )

        self.assertEqual(selection["mechanism"], "foreground_bounded_call")
        self.assertEqual(selection["observation_mode"], "single_foreground_return")
        self.assertFalse(selection["capability_degraded"])

    def test_long_command_never_selects_a_foreground_call(self) -> None:
        for duration in ("minutes", "long_running", "unknown"):
            with self.subTest(duration=duration):
                selection = select_wait_mechanism(
                    work_kind="command",
                    expected_duration_class=duration,
                    host_capabilities=FULL_CAPABILITIES,
                )
                self.assertEqual(selection["mechanism"], "background_completion_notification")
                self.assertEqual(selection["observation_mode"], "event_triggered_completion")
                self.assertNotIn("foreground_bounded_call", selection["mechanism_ladder"])

    def test_delegated_lane_relies_on_its_delivered_result(self) -> None:
        selection = select_wait_mechanism(
            work_kind="delegated_lane",
            expected_duration_class="long_running",
            host_capabilities=FULL_CAPABILITIES,
        )

        self.assertEqual(selection["mechanism"], "delegated_result_delivery")
        self.assertEqual(selection["observation_mode"], "delivered_result")

    def test_external_conditions_prefer_a_host_monitor(self) -> None:
        for work_kind in ("ci_pr_deploy", "file_port_log", "external_session"):
            with self.subTest(work_kind=work_kind):
                selection = select_wait_mechanism(
                    work_kind=work_kind,
                    expected_duration_class="long_running",
                    host_capabilities=FULL_CAPABILITIES,
                )
                self.assertEqual(selection["mechanism"], "host_monitor_subscription")
                self.assertEqual(selection["observation_mode"], "subscribed_condition")

    def test_an_unknown_duration_class_does_not_buy_a_foreground_call(self) -> None:
        # Degrading to the conservative rung is the point: guessing "short"
        # from a missing duration is how a long command ends up blocking a turn.
        self.assertNotIn("foreground_bounded_call", wait_mechanism_ladder("command", "unknown"))

    def test_every_mechanism_maps_to_exactly_one_observation_mode(self) -> None:
        modes = set()
        for mechanism in WAIT_MECHANISMS:
            selection = _selection_for_mechanism(mechanism)
            self.assertEqual(selection["mechanism"], mechanism)
            modes.add(selection["observation_mode"])
        self.assertEqual(modes, set(WAIT_OBSERVATION_MODES))


class HostCapabilityFallbackTests(unittest.TestCase):
    def test_no_monitor_falls_back_to_one_bounded_watcher_with_a_deadline(self) -> None:
        strategy = _strategy(
            work_kind="ci_pr_deploy",
            handle_kind="watcher_process",
            handle_ref="watch-7",
            host_capabilities=("background_watcher",),
        )

        self.assertEqual(strategy["mechanism"], "bounded_background_watcher")
        self.assertEqual(strategy["observation_mode"], "bounded_watcher")
        self.assertEqual(strategy["fallback_mechanism"], "adaptive_backoff_fallback")
        self.assertTrue(strategy["selection"]["capability_degraded"])
        self.assertEqual(strategy["selection"]["missing_capabilities"], ["host_monitor_subscription"])
        self.assertGreater(strategy["deadline_seconds"], 0)
        self.assertTrue(strategy["deadline_is_hard"])

    def test_a_host_with_nothing_gets_bounded_adaptive_backoff_and_cannot_spin(self) -> None:
        strategy = _strategy(
            work_kind="external_session",
            handle_kind="external_session",
            handle_ref="session-9",
            host_capabilities=(),
        )

        self.assertEqual(strategy["mechanism"], "adaptive_backoff_fallback")
        self.assertEqual(strategy["observation_mode"], "adaptive_backoff")
        # Nothing below the last rung, so the deadline is what ends the wait.
        self.assertEqual(strategy["fallback_mechanism"], "")
        self.assertEqual(
            strategy["selection"]["fallback_reason"],
            "no_further_mechanism_available_deadline_is_terminal",
        )
        self.assertGreater(strategy["deadline_seconds"], 0)
        self.assertTrue(strategy["deadline_is_hard"])
        self.assertTrue(strategy["cancellation"]["available"])
        self.assertEqual(validate_execution_wait_strategy(strategy), [])

    def test_degrading_names_the_missing_capability_instead_of_hiding_it(self) -> None:
        strategy = _strategy(host_capabilities=("foreground_timeout",))

        self.assertEqual(strategy["mechanism"], "adaptive_backoff_fallback")
        self.assertEqual(
            strategy["selection"]["missing_capabilities"],
            ["background_completion_notification", "background_watcher"],
        )
        self.assertIn("degraded_to_adaptive_backoff_fallback", strategy["selection"]["selection_reason"])

    def test_an_unrecognized_capability_is_recorded_not_silently_dropped(self) -> None:
        strategy = _strategy(host_capabilities=("background_watcher", "telepathy"))

        self.assertEqual(strategy["selection"]["unrecognized_host_capabilities"], ["telepathy"])
        self.assertNotIn("telepathy", strategy["selection"]["host_capabilities_observed"])


class WaitStrategyPayloadTests(unittest.TestCase):
    def test_a_complete_strategy_validates(self) -> None:
        strategy = _strategy()

        self.assertEqual(strategy["schema_version"], EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION)
        self.assertEqual(strategy["binding_state"], "armed")
        self.assertFalse(strategy["raw_content_included"])
        self.assertFalse(strategy["handle"]["raw_content_included"])
        self.assertEqual(list(strategy["terminal_states"]), list(WAIT_TERMINAL_STATES))
        self.assertEqual(validate_execution_wait_strategy(strategy), [])

    def test_a_wait_with_no_cancellation_path_is_rejected(self) -> None:
        strategy = _strategy(cancellation_path="")

        self.assertFalse(strategy["cancellation"]["available"])
        self.assertIn(
            "execution wait strategy must name a cancellation path",
            validate_execution_wait_strategy(strategy),
        )

    def test_a_wait_with_no_deadline_is_rejected(self) -> None:
        strategy = _strategy()
        strategy["deadline_seconds"] = 0

        self.assertIn(
            "execution wait strategy must carry a positive hard deadline",
            validate_execution_wait_strategy(strategy),
        )

    def test_a_handle_with_no_reference_is_rejected(self) -> None:
        strategy = _strategy(handle_ref="")

        self.assertIn(
            "execution wait strategy handle must carry an observed reference",
            validate_execution_wait_strategy(strategy),
        )

    def test_an_observation_mode_that_contradicts_its_mechanism_is_rejected(self) -> None:
        strategy = _strategy()
        strategy["observation_mode"] = "subscribed_condition"

        self.assertIn(
            "execution wait strategy observation_mode does not match its mechanism",
            validate_execution_wait_strategy(strategy),
        )

    def test_raw_log_text_never_reaches_the_condition_field(self) -> None:
        strategy = _strategy(
            condition="[Background process bg-1 finished with exit code 0~ Here's the final output:] secret",
        )

        self.assertNotIn("Background process", str(strategy["condition"]))
        self.assertNotIn("final output", str(strategy["condition"]))

    def test_a_refused_vocabulary_value_is_recorded_rather_than_lost(self) -> None:
        strategy = _strategy(work_kind="vibes")

        self.assertEqual(strategy["work_kind"], "command")
        self.assertEqual(strategy["omitted"]["unmapped_source_work_kind"], "vibes")


class TerminalStateTests(unittest.TestCase):
    def test_completion_notification_closes_the_binding_once(self) -> None:
        binding = arm_wait_binding(_strategy())
        self.assertEqual(binding["schema_version"], EXECUTION_WAIT_BINDING_SCHEMA_VERSION)
        self.assertEqual(binding["binding_state"], "armed")
        self.assertFalse(binding["completion_consumed"])

        closed = consume_wait_completion(
            binding,
            outcome="completed",
            summary="exit code 0 recorded",
            evidence_refs=("run-1",),
        )

        self.assertEqual(closed["binding_state"], "completed")
        self.assertTrue(closed["completion_consumed"])
        self.assertEqual(closed["terminal_evidence"]["evidence_refs"], ["run-1"])
        self.assertEqual(closed["observation_mode"], "event_triggered_completion")
        self.assertEqual(closed["handle"]["reference"], "bg-1")

    def test_a_duplicate_completion_does_not_reopen_or_overwrite(self) -> None:
        closed = consume_wait_completion(arm_wait_binding(_strategy()), outcome="completed")

        again = consume_wait_completion(closed, outcome="failed", summary="late duplicate")

        self.assertEqual(again["binding_state"], "completed")
        self.assertTrue(again["duplicate_completion_ignored"])
        self.assertNotIn("late duplicate", str(again["terminal_evidence"]))

    def test_every_terminal_state_carries_bounded_evidence_and_a_recovery_action(self) -> None:
        for outcome in WAIT_TERMINAL_STATES:
            with self.subTest(outcome=outcome):
                closed = consume_wait_completion(arm_wait_binding(_strategy()), outcome=outcome)
                self.assertEqual(closed["binding_state"], outcome)
                self.assertTrue(closed["terminal_evidence"]["summary"])
                self.assertTrue(closed["terminal_evidence"]["recovery_action"])
                self.assertFalse(closed["terminal_evidence"]["raw_content_included"])

    def test_lost_handle_recovers_by_re_observing_rather_than_re_running(self) -> None:
        closed = consume_wait_completion(arm_wait_binding(_strategy()), outcome="lost_handle")

        self.assertEqual(
            closed["terminal_evidence"]["recovery_action"],
            "re_observe_the_handle_once_then_report_it_as_unobservable",
        )

    def test_an_unknown_outcome_fails_closed_and_records_the_refused_word(self) -> None:
        closed = consume_wait_completion(arm_wait_binding(_strategy()), outcome="probably_fine")

        self.assertEqual(closed["binding_state"], "failed")
        self.assertEqual(closed["unmapped_source_outcome"], "probably_fine")

    def test_terminal_evidence_never_carries_raw_process_output(self) -> None:
        closed = consume_wait_completion(
            arm_wait_binding(_strategy()),
            outcome="failed",
            summary="[Background process bg-1 finished with exit code 1~ Here's the final output:]",
        )

        self.assertNotIn("Background process", closed["terminal_evidence"]["summary"])


class NoPollTraceTests(unittest.TestCase):
    def test_one_launch_and_one_completion_event_passes(self) -> None:
        trace = evaluate_wait_trace([{"call": "launch"}, {"call": "completion_event"}])

        self.assertEqual(trace["schema_version"], EXECUTION_WAIT_TRACE_SCHEMA_VERSION)
        self.assertTrue(trace["no_poll"])
        self.assertEqual(trace["violations"], [])
        self.assertEqual(trace["agent_status_read_count"], 0)
        self.assertEqual(trace["terminal_call"], "completion_event")

    def test_repeated_status_reads_before_completion_are_flagged(self) -> None:
        trace = evaluate_wait_trace(
            [
                {"call": "launch"},
                {"call": "agent_status_read", "decision_changing": True},
                {"call": "agent_status_read", "decision_changing": True},
                {"call": "agent_status_read", "decision_changing": True},
                {"call": "completion_event"},
            ]
        )

        self.assertFalse(trace["no_poll"])
        self.assertIn("polling_loop_detected", trace["violations"])
        self.assertEqual(trace["agent_status_read_count"], 3)

    def test_one_decision_changing_midpoint_peek_is_allowed(self) -> None:
        trace = evaluate_wait_trace(
            [
                {"call": "launch"},
                {"call": "agent_status_read", "decision_changing": True},
                {"call": "completion_event"},
            ]
        )

        self.assertTrue(trace["no_poll"])
        self.assertEqual(trace["decision_changing_peek_count"], MIDPOINT_PEEK_BUDGET)

    def test_a_peek_that_changes_nothing_is_not_diagnosis(self) -> None:
        trace = evaluate_wait_trace(
            [{"call": "launch"}, {"call": "agent_status_read"}, {"call": "completion_event"}]
        )

        self.assertFalse(trace["no_poll"])
        self.assertEqual(trace["violations"], ["non_decision_changing_peek"])

    def test_user_requested_status_reads_are_always_allowed(self) -> None:
        trace = evaluate_wait_trace(
            [
                {"call": "launch"},
                {"call": "user_requested_status_read"},
                {"call": "user_requested_status_read"},
                {"call": "user_requested_status_read"},
                {"call": "completion_event"},
            ]
        )

        self.assertTrue(trace["no_poll"])
        self.assertEqual(trace["user_requested_status_read_count"], 3)
        self.assertEqual(trace["agent_status_read_count"], 0)

    def test_cancellation_and_deadline_expiry_terminate_a_trace(self) -> None:
        for terminal in ("cancellation", "deadline_expiry"):
            with self.subTest(terminal=terminal):
                trace = evaluate_wait_trace([{"call": "launch"}, {"call": terminal}])
                self.assertTrue(trace["no_poll"])
                self.assertEqual(trace["terminal_call"], terminal)

    def test_a_wait_that_never_terminates_is_a_violation(self) -> None:
        trace = evaluate_wait_trace([{"call": "launch"}])

        self.assertIn("unterminated_wait", trace["violations"])

    def test_a_trace_without_a_launch_is_a_violation(self) -> None:
        trace = evaluate_wait_trace([{"call": "completion_event"}])

        self.assertIn("missing_launch", trace["violations"])

    def test_work_continuing_after_a_terminal_state_is_a_violation(self) -> None:
        trace = evaluate_wait_trace(
            [{"call": "launch"}, {"call": "completion_event"}, {"call": "agent_status_read"}]
        )

        self.assertIn("calls_after_terminal_state", trace["violations"])

    def test_a_non_sequence_trace_is_reported_not_treated_as_clean(self) -> None:
        trace = evaluate_wait_trace(None)  # type: ignore[arg-type]

        self.assertFalse(trace["no_poll"])
        self.assertEqual(trace["violations"], ["trace_is_not_a_recorded_call_sequence"])


class ProgressPolicyWiringTests(unittest.TestCase):
    def test_the_progress_policy_carries_the_wait_strategy_contract(self) -> None:
        policy = build_coding_progress_reporting_policy(next_action="wait_for_executor_evidence")
        wait = policy["wait_strategy"]

        self.assertTrue(policy["timed_polling_rejected"])
        self.assertEqual(wait["schema_version"], EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION)
        self.assertEqual(
            wait["precondition"],
            "select_and_arm_the_wait_strategy_before_starting_long_running_work",
        )
        self.assertEqual(wait["mechanisms"], list(WAIT_MECHANISMS))
        self.assertEqual(wait["observation_modes"], list(WAIT_OBSERVATION_MODES))
        self.assertTrue(wait["deadline_required"])
        self.assertTrue(wait["cancellation_path_required"])
        self.assertEqual(wait["selected_mechanism"], "")

    def test_a_dispatch_records_its_selected_mechanism_and_observation_mode(self) -> None:
        policy = build_coding_progress_reporting_policy(
            next_action="dispatch_to_executor",
            wait_mechanism="background_completion_notification",
        )

        self.assertEqual(policy["wait_strategy"]["selected_mechanism"], "background_completion_notification")
        self.assertEqual(policy["wait_strategy"]["selected_observation_mode"], "event_triggered_completion")

    def test_a_refused_mechanism_is_recorded_rather_than_read_as_unselected(self) -> None:
        reference = wait_strategy_policy_reference(mechanism="just_keep_checking")

        self.assertEqual(reference["selected_mechanism"], "")
        self.assertEqual(reference["omitted"]["unmapped_source_mechanism"], "just_keep_checking")

    def test_polling_as_a_wait_mechanism_is_a_named_forbidden_pattern(self) -> None:
        policy = build_coding_progress_reporting_policy()

        self.assertIn(
            "waiting_by_repeated_status_reads_instead_of_a_bound_completion_signal",
            policy["forbidden_patterns"],
        )

    def test_the_existing_bounded_output_backstop_is_untouched(self) -> None:
        enforcement = coding_progress_policy_enforcement()

        self.assertFalse(enforcement["declarative_only"])
        self.assertEqual(enforcement["mechanism"], "bounded_tail_plus_run_context_budget_ledger")
        self.assertEqual(enforcement["degraded_output"], "summary_only_with_artifact_pointers")
        self.assertIn("omh runtime show", enforcement["bounded_surfaces"])

    def test_the_enforcement_block_states_the_dispatch_precondition(self) -> None:
        binding = coding_progress_policy_enforcement()["wait_binding"]

        self.assertEqual(binding["precondition"], "select_and_arm_the_wait_strategy_before_dispatch")
        self.assertEqual(binding["records"], ["executor_handle", "observation_mode"])
        self.assertTrue(binding["completion_consumed_once"])
        self.assertEqual(binding["terminal_states"], list(WAIT_TERMINAL_STATES))
        self.assertTrue(binding["unbounded_idle_or_busy_wait_rejected"])


class HermesHarnessWaitBindingTests(unittest.TestCase):
    def test_the_harness_states_the_background_dispatch_precondition(self) -> None:
        harness = build_hermes_coding_harness(
            runtime_handoff={"selected_executor_profile": "hermes"},
            session={"session_id": "s-1", "current_run_id": "r-1"},
        )
        binding = harness["wait_binding"]

        self.assertEqual(validate_hermes_coding_harness(harness), [])
        self.assertEqual(
            binding["precondition"],
            "select_and_arm_the_wait_strategy_before_dispatching_a_background_lane",
        )
        self.assertEqual(binding["records"], ["executor_handle", "observation_mode"])
        self.assertEqual(binding["terminal_states"], list(WAIT_TERMINAL_STATES))
        self.assertIn("not dispatch", binding["claim_boundary"])

    def test_a_harness_whose_wait_binding_lost_its_terminal_states_is_rejected(self) -> None:
        harness = build_hermes_coding_harness(
            runtime_handoff={"selected_executor_profile": "hermes"},
            session={"session_id": "s-1"},
        )
        harness["wait_binding"]["terminal_states"] = ["completed"]

        self.assertIn(
            "hermes_coding_harness wait_binding must carry the canonical terminal states",
            validate_hermes_coding_harness(harness),
        )


class GeneratedSurfaceTests(unittest.TestCase):
    """The discipline must reach the surfaces an agent actually reads."""

    def setUp(self) -> None:
        self.skills = {template.name: template.content for template in builtin_skill_templates()}
        self.references = {
            (template.skill_name, template.relative_path): template.content
            for template in builtin_skill_reference_templates()
        }

    def test_the_shared_rail_carries_the_capability_ladder(self) -> None:
        rail = self.references[("oh-my-hermes", "references/skill-common-rail.md")]

        self.assertIn("## Waiting On Long-Running Work", rail)
        self.assertIn(EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION, rail)
        self.assertIn("the host's monitor or subscription", rail)
        self.assertIn("adaptive backoff outside model turns", rail)
        for state in WAIT_TERMINAL_STATES:
            self.assertIn(f"`{state}`", rail)

    def test_the_executing_engines_and_command_overlay_share_one_discipline(self) -> None:
        marker = "Choose the wait strategy before starting long-running work"
        for skill in ("ultrawork", "loop", "command-operator"):
            with self.subTest(skill=skill):
                self.assertIn(marker, self.skills[skill])

    def test_the_engines_state_the_armed_wait_instead_of_re_reading_status(self) -> None:
        for skill in ("ultrawork", "loop"):
            with self.subTest(skill=skill):
                self.assertIn(
                    "name the armed wait it is waiting on -- handle, bound completion signal, deadline -- "
                    "instead of re-reading status",
                    self.skills[skill],
                )

    def test_the_discipline_names_no_host_specific_tool(self) -> None:
        # Executor-neutral by contract: a tool name here is unfollowable on a
        # harness that does not have it.
        rail = self.references[("oh-my-hermes", "references/skill-common-rail.md")]
        section = rail.split("## Waiting On Long-Running Work", 1)[1].split("\n## ", 1)[0]
        for forbidden in ("codex", "claude code", "bashoutput", "sleep ", "ps aux"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, section.casefold())


def _selection_for_mechanism(mechanism: str) -> dict[str, object]:
    cases = {
        "foreground_bounded_call": ("command", "within_one_call", FULL_CAPABILITIES),
        "background_completion_notification": ("command", "long_running", FULL_CAPABILITIES),
        "delegated_result_delivery": ("delegated_lane", "long_running", FULL_CAPABILITIES),
        "host_monitor_subscription": ("ci_pr_deploy", "long_running", FULL_CAPABILITIES),
        "bounded_background_watcher": ("ci_pr_deploy", "long_running", ("background_watcher",)),
        "adaptive_backoff_fallback": ("ci_pr_deploy", "long_running", ()),
    }
    work_kind, duration, capabilities = cases[mechanism]
    return select_wait_mechanism(
        work_kind=work_kind,
        expected_duration_class=duration,
        host_capabilities=capabilities,
    )


if __name__ == "__main__":
    unittest.main()
