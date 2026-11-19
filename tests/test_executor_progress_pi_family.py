from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.executor_progress import (
    ALLOWED_EXECUTOR_PROFILES,
    ROUTING_METRIC_SIGNAL_KEYS,
    ExecutorProgressError,
    build_progress_binding,
    build_progress_event,
    build_progress_report,
    build_safe_progress_signal,
    normalize_executor_profile,
    observe_executor_progress,
    project_active_executor_status,
    validate_progress_binding,
    validate_progress_event,
    validate_progress_report,
    write_progress_binding,
)
from omh.paths import resolve_paths
from omh.coding.pi_family_interop import PI_DISTRIBUTION_HOST, PI_FORK_HOST


class OmoRuntimeProgressProfileTests(unittest.TestCase):
    def test_every_pi_family_host_alias_normalizes_to_one_observable_lane(self) -> None:
        for value in ("pi-family-runtime", "pi_family_runtime", "pi", PI_DISTRIBUTION_HOST, PI_FORK_HOST, "opencode", f"  {PI_DISTRIBUTION_HOST.capitalize()}  ", "OPENCODE"):
            with self.subTest(value=value):
                self.assertEqual(normalize_executor_profile(value), "pi_family_runtime")

        self.assertIn("pi_family_runtime", ALLOWED_EXECUTOR_PROFILES)
        with self.assertRaisesRegex(ExecutorProgressError, "unsupported executor profile for progress: gemini"):
            normalize_executor_profile("gemini")

    def test_hermes_guard_still_requires_observed_local_execution(self) -> None:
        with self.assertRaisesRegex(ExecutorProgressError, "Hermes orchestration is not an active executor"):
            normalize_executor_profile("hermes")
        with self.assertRaisesRegex(ExecutorProgressError, "hermes_local requires explicit observed local execution"):
            normalize_executor_profile("hermes-local")
        with self.assertRaisesRegex(ExecutorProgressError, "hermes_local requires explicit observed local execution"):
            normalize_executor_profile("hermes_local")

        self.assertEqual(normalize_executor_profile("hermes", observed_hermes_execution=True), "hermes_local")
        self.assertEqual(normalize_executor_profile("hermes-local", observed_hermes_execution=True), "hermes_local")

    def test_all_three_validators_accept_the_pi_family_runtime_profile(self) -> None:
        binding = build_progress_binding(
            target_type="run",
            target_id="run-pi-family-1",
            executor_profile=PI_DISTRIBUTION_HOST,
            now="2026-06-24T00:00:00Z",
        )
        self.assertEqual(binding["executor_profile"], "pi_family_runtime")
        self.assertEqual(binding["binding_id"], "run:run-pi-family-1:pi_family_runtime")
        self.assertEqual(validate_progress_binding(binding), [])

        event = build_progress_event(
            binding,
            event_type="repo_exploration",
            summary="The pi-family runtime is inspecting the repository.",
            observed_at="2026-06-24T00:01:00Z",
        )
        self.assertEqual(validate_progress_event(event), [])

        report = build_progress_report(binding, event, reported_at="2026-06-24T00:01:30Z")
        self.assertEqual(validate_progress_report(report), [])

    def test_validator_message_names_every_accepted_profile(self) -> None:
        errors = validate_progress_event({"executor_profile": "gemini"})
        self.assertIn(f"executor_profile must be one of {', '.join(ALLOWED_EXECUTOR_PROFILES)}", errors)


class RoutingMetricSignalTests(unittest.TestCase):
    def test_routed_model_metrics_reach_the_live_row_and_the_event_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-pi-family-1",
                    executor_profile="pi",
                    now="2026-06-24T00:00:00Z",
                ),
            )
            signal = build_safe_progress_signal(
                executor_profile="pi",
                explicit_event_type="diff_started",
                explicit_summary="The pi-family runtime changed files.",
                routed_model="anthropic/claude-opus-4",
                routed_reasoning_effort="high",
                tokens_total=12345,
                elapsed_seconds=97,
                category="deep",
                fallback_count=2,
                turn_count=3,
                tool_count=14,
                cost_usd=0.1346,
                tokens_per_second=45.2,
                cache_hit_percentage=0,
                context_percentage=41.5,
            )

            for key in ROUTING_METRIC_SIGNAL_KEYS:
                self.assertIn(key, signal)

            observe_executor_progress(paths, binding, signal, observed_at="2026-06-24T00:03:00Z")
            projection = project_active_executor_status(paths, now="2026-06-24T00:04:00Z")

            row = projection["active_executors"][0]
            self.assertEqual(row["executor_profile"], "pi_family_runtime")
            self.assertEqual(row["routed_model"], "anthropic/claude-opus-4")
            self.assertEqual(row["routed_reasoning_effort"], "high")
            self.assertEqual(row["tokens_total"], 12345)
            self.assertEqual(row["elapsed_seconds"], 97)
            self.assertEqual(row["category"], "deep")
            self.assertEqual(row["fallback_count"], 2)
            self.assertEqual(row["turn_count"], 3)
            self.assertEqual(row["tool_count"], 14)
            self.assertEqual(row["cost_usd"], 0.1346)
            self.assertEqual(row["tokens_per_second"], 45.2)
            self.assertEqual(row["cache_hit_percentage"], 0)
            self.assertEqual(row["context_percentage"], 41.5)
            self.assertEqual(row["latest_event"]["routed_model"], "anthropic/claude-opus-4")
            self.assertEqual(row["latest_event"]["tokens_total"], 12345)
            self.assertIn("not result", row["claim_boundary"])

    def test_an_unobserved_token_count_stays_absent_instead_of_becoming_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            binding = write_progress_binding(
                paths,
                build_progress_binding(
                    target_type="run",
                    target_id="run-pi-family-2",
                    executor_profile="opencode",
                    now="2026-06-24T00:00:00Z",
                ),
            )
            signal = build_safe_progress_signal(
                executor_profile="opencode",
                explicit_event_type="repo_exploration",
                explicit_summary="The pi-family runtime is inspecting the repository.",
                routed_model="anthropic/claude-opus-4",
            )

            self.assertNotIn("tokens_total", signal)
            self.assertNotIn("elapsed_seconds", signal)
            self.assertNotIn("routed_reasoning_effort", signal)

            observe_executor_progress(paths, binding, signal, observed_at="2026-06-24T00:03:00Z")
            row = project_active_executor_status(paths, now="2026-06-24T00:04:00Z")["active_executors"][0]

            self.assertEqual(row["routed_model"], "anthropic/claude-opus-4")
            self.assertNotIn("tokens_total", row)
            self.assertNotIn("elapsed_seconds", row)
            self.assertNotIn("tokens_total", row["latest_event"])

    def test_an_explicit_zero_token_count_is_kept_as_an_observation(self) -> None:
        signal = build_safe_progress_signal(
            executor_profile=PI_DISTRIBUTION_HOST,
            explicit_event_type="repo_exploration",
            explicit_summary="The pi-family runtime is inspecting the repository.",
            tokens_total=0,
        )
        self.assertEqual(signal["tokens_total"], 0)

    def test_negative_and_non_numeric_counts_are_dropped_rather_than_stored(self) -> None:
        signal = build_safe_progress_signal(
            executor_profile=PI_DISTRIBUTION_HOST,
            explicit_event_type="repo_exploration",
            explicit_summary="The pi-family runtime is inspecting the repository.",
            tokens_total=-1,
            elapsed_seconds="not-a-number",  # type: ignore[arg-type]
        )
        self.assertNotIn("tokens_total", signal)
        self.assertNotIn("elapsed_seconds", signal)

    def test_raw_and_hidden_signal_keys_are_still_rejected_next_to_routing_metrics(self) -> None:
        binding = build_progress_binding(
            target_type="run",
            target_id="run-pi-family-3",
            executor_profile="pi",
            now="2026-06-24T00:00:00Z",
        )
        event = build_progress_event(
            binding,
            event_type="diff_started",
            summary="The pi-family runtime changed files.",
            observed_at="2026-06-24T00:01:00Z",
            signal=build_safe_progress_signal(
                executor_profile="pi",
                routed_model="anthropic/claude-opus-4",
                routed_reasoning_effort="high",
            ),
        )
        # `routed_reasoning_effort` names an effort level, not reasoning
        # content: it must not be mistaken for the banned `reasoning` key.
        self.assertEqual(validate_progress_event(event), [])
        self.assertEqual(event["signal"]["routed_reasoning_effort"], "high")

        leaked = json.loads(json.dumps(event))
        leaked["signal"]["reasoning"] = "private chain of thought"
        errors = validate_progress_event(leaked)
        self.assertIn("signal.reasoning is not allowed in progress artifacts", errors)

        leaked_transcript = json.loads(json.dumps(event))
        leaked_transcript["signal"]["transcript"] = "full session transcript"
        self.assertIn(
            "signal.transcript is not allowed in progress artifacts",
            validate_progress_event(leaked_transcript),
        )

    def test_free_text_cannot_ride_in_on_the_routed_model_key(self) -> None:
        signal = build_safe_progress_signal(
            executor_profile="pi",
            routed_model="anthropic/claude-opus-4 " + "x" * 400,
        )
        self.assertLessEqual(len(signal["routed_model"]), 120)

    def test_category_rejects_values_outside_the_closed_routing_vocabulary(self) -> None:
        signal = build_safe_progress_signal(
            executor_profile="pi",
            category="sk-proj-secret-token",
        )

        self.assertNotIn("category", signal)

if __name__ == "__main__":
    unittest.main()
