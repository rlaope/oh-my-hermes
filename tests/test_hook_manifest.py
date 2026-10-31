from __future__ import annotations

import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.capabilities.hooks import hook_manifest
from omh.install.hook_integrity import HOOK_REVIEWS, VALID_HOOK_EVENTS
from omh.plugin_bundle.omh.awareness import awareness_primer_context, awareness_route_hint
from omh.plugin_bundle.omh.awareness_delivery import read_awareness_delivery
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
from omh.plugin_bundle.omh.hooks.tool_hooks import post_tool_call, pre_tool_call
from omh.plugin_bundle.omh.tool_bursts import tool_call_activity


def sionic_omh_usage_evaluation_prompt() -> str:
    return """이번 Sionic 작업에서 OMH가 얼마나 관여했는지 사용성 평가하고,
왜 OMH를 덜 썼는지 분석해서 라우터 강화 플랜으로 잡아줘.
Sionic은 마크다운 노트뿐 아니라 위키 페이지/site 생성도 포함했어.
결과창에는 Background process proc_d5eb61ddcf80 finished with exit code 0~
Here's the final output: 같은 raw output, turn.completed usage, Self-improvement review 줄이 보였고
이걸 프리티하게 OMH wrapper report로 정리해야 했어.

[OMH Awareness]
status=prepared_not_observed; Evidence boundary: pasted status is diagnostic evidence.
[OMH Route Hint]
intent=delivery_intent; selected=ultraprocess; confidence=medium.
mentioned_workflows=ultraprocess.
not_executed=Codex.
[omh]
selected_workflow=ultraprocess
latest_runtime_run=not_executed=Codex
execution_observed=false
review_observed=false
ci_observed=false
merge_observed=false
"""


class HookManifestTests(unittest.TestCase):
    def test_hook_manifest_projects_plugin_yaml_and_wrapper_events(self) -> None:
        manifest = hook_manifest()

        self.assertEqual(manifest["schema_version"], "omh_hook_manifest/v1")
        tools = {item["name"]: item for item in manifest["plugin_tools"]}
        hooks = {item["name"]: item for item in manifest["plugin_hooks"]}
        events = {item["name"]: item for item in manifest["wrapper_events"]}

        self.assertIn("omh_capabilities", tools)
        self.assertTrue(tools["omh_capabilities"]["supported_by_plugin_bundle"])
        self.assertTrue(tools["omh_capabilities"]["supported_by_cli_backend"])
        self.assertFalse(tools["omh_capabilities"]["observed_in_this_environment"])
        self.assertIn("omh_context", tools)
        self.assertTrue(tools["omh_context"]["supported_by_plugin_bundle"])
        self.assertTrue(tools["omh_context"]["supported_by_cli_backend"])
        self.assertTrue(tools["omh_context"]["supported_by_wrapper_contract"])
        self.assertEqual(tools["omh_context"]["cli_backend_surface"], "omh context brief")
        self.assertIn("omh_recommend", tools)
        self.assertTrue(tools["omh_recommend"]["supported_by_plugin_bundle"])
        self.assertTrue(tools["omh_recommend"]["supported_by_cli_backend"])
        self.assertTrue(tools["omh_recommend"]["supported_by_wrapper_contract"])
        self.assertIn("omh_interact", tools)
        self.assertTrue(tools["omh_interact"]["supported_by_plugin_bundle"])
        self.assertTrue(tools["omh_interact"]["supported_by_cli_backend"])
        self.assertTrue(tools["omh_interact"]["supported_by_wrapper_contract"])
        self.assertEqual(tools["omh_interact"]["cli_backend_surface"], "omh chat interact")
        self.assertIn("omh_probe", tools)
        self.assertTrue(tools["omh_probe"]["supported_by_plugin_bundle"])
        self.assertTrue(tools["omh_probe"]["supported_by_cli_backend"])
        self.assertTrue(tools["omh_probe"]["supported_by_wrapper_contract"])
        self.assertIn("pre_llm_call", hooks)
        self.assertIn("omh_awareness_primer", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("omh_context_brief", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("omh_active_workflow", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("omh_context_budget", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("omh_route_hint", hooks["pre_llm_call"]["payload_fields"])
        self.assertIn("bounded_status_context", hooks["pre_llm_call"]["payload_fields"])
        self.assertNotIn("omh_generic_tool_checkpoint", hooks["pre_tool_call"]["payload_fields"])
        self.assertEqual(hooks["pre_tool_call"]["payload_fields"], ["context", "action", "message"])
        self.assertIn("executor_opened", events)
        self.assertIn("selected_executor_profile", events["executor_opened"]["payload_fields"])
        self.assertIn("native_command_registered", events)
        self.assertIn("registration_schema", events["native_command_registered"]["payload_fields"])
        self.assertIn("native_command_rendered", events)
        self.assertIn("render_kind", events["native_command_rendered"]["payload_fields"])
        self.assertIn("not proof", hooks["pre_llm_call"]["claim_boundary"])

    def test_hook_manifest_never_claims_an_observed_or_invoked_hook(self) -> None:
        """#803 AC3, on the manifest side: availability is not invocation.

        The integrity record in `install.hook_integrity` refines this manifest
        rather than replacing it, so the boundary has to hold in both. Here it
        is the resting state of the static projection: nothing OMH can compute
        without a host observation may set an observed flag.
        """
        manifest = hook_manifest()

        for hook in manifest["plugin_hooks"]:
            with self.subTest(hook=hook["name"]):
                self.assertFalse(hook["observed_in_this_environment"])
                self.assertIn("not proof that Hermes loaded or invoked", hook["claim_boundary"])
        for tool in manifest["plugin_tools"]:
            self.assertFalse(tool["observed_in_this_environment"])
        for event in manifest["wrapper_events"]:
            self.assertFalse(event["observed_in_this_environment"])

    def test_every_manifest_hook_has_a_reviewed_integrity_record(self) -> None:
        """#803 AC1, on the manifest side: no hook ships without a review.

        Adding a hook to `PROVIDED_HOOKS` is what makes it appear here. If it
        can appear here without a `HOOK_REVIEWS` entry, it reaches Hermes with
        no reviewed digest and no declared event scope behind it.
        """
        names = {hook["name"] for hook in hook_manifest()["plugin_hooks"]}

        self.assertEqual(names, set(HOOK_REVIEWS))
        self.assertEqual(names, set(VALID_HOOK_EVENTS))

    def test_pre_llm_call_records_delivery_in_explicit_omh_home(self) -> None:
        with TemporaryDirectory() as explicit_home, TemporaryDirectory() as env_home:
            with patch.dict(os.environ, {"OMH_HOME": env_home}):
                result = pre_llm_call(
                    user_message="prepare a safe feature plan",
                    is_first_turn=True,
                    omh_home=explicit_home,
                )

            self.assertIsNotNone(result)
            self.assertEqual(read_awareness_delivery(explicit_home)["delivery_count"], 1)
            self.assertEqual(read_awareness_delivery(env_home)["delivery_count"], 0)

    def test_pre_llm_call_does_not_rewrite_delivery_ledger_for_idle_turns(self) -> None:
        with TemporaryDirectory() as explicit_home, TemporaryDirectory() as env_home:
            with patch.dict(os.environ, {"OMH_HOME": env_home}):
                result = pre_llm_call(
                    user_message="",
                    is_first_turn=False,
                    session_id="session-idle",
                    task_id="task-idle",
                    turn_id="turn-idle",
                    omh_home=explicit_home,
                )

            self.assertIsNone(result)
            self.assertFalse(os.path.exists(os.path.join(explicit_home, "runtime", "awareness_delivery.json")))
            self.assertEqual(read_awareness_delivery(env_home)["delivery_count"], 0)

    def test_generic_first_turn_skips_setup_only_context_and_hud(self) -> None:
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status",
                    return_value={"runtime_state_present": True, "runs": []},
                ) as status_read,
                patch("omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_hud") as hud_read,
            ):
                result = pre_llm_call(
                    user_message="Hello, how are you?",
                    is_first_turn=True,
                    omh_home=omh_home,
                )

            # What this test is about: a first turn does not pay for the
            # setup-only status and HUD reads. The primer it now carries is
            # message-independent, so it costs neither read.
            status_read.assert_not_called()
            hud_read.assert_not_called()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertIn("[OMH Awareness]", result["context"])
            self.assertNotIn("Native bridge status context", result["context"])
            # A greeting still matches no workflow, so nothing claims a route.
            self.assertNotIn("[OMH Route Hint]", result["context"])

    def test_relevant_first_turn_keeps_route_hint_without_setup_status(self) -> None:
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status",
                    return_value={"runtime_state_present": True, "runs": []},
                ),
                patch("omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_hud") as hud_read,
            ):
                result = pre_llm_call(
                    user_message="make an image explaining the cron feature",
                    is_first_turn=True,
                    omh_home=omh_home,
                )

            self.assertIsNotNone(result)
            self.assertIn("[OMH Awareness]", result["context"])
            self.assertIn("selected=img-summary", result["context"])
            self.assertNotIn("Native bridge status context", result["context"])
            hud_read.assert_not_called()

    def test_first_turn_task_routes_do_not_depend_on_mid_session_matcher(self) -> None:
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.awareness_context_matches_message",
                    return_value=False,
                ) as matcher,
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status",
                    return_value={"runtime_state_present": True, "runs": []},
                ),
            ):
                results = [
                    pre_llm_call(
                        user_message=message,
                        is_first_turn=True,
                        omh_home=omh_home,
                    )
                    for message in ("prepare a safe feature plan", "implement this", "review this PR")
                ]

            matcher.assert_not_called()
            self.assertTrue(all(result is not None for result in results))
            self.assertTrue(all("[OMH Route Hint]" in result["context"] for result in results if result))

    def test_repeated_route_guidance_is_suppressed_within_one_session(self) -> None:
        with TemporaryDirectory() as omh_home:
            first = pre_llm_call(
                user_message="review this PR",
                is_first_turn=True,
                session_id="session-a",
                task_id="task-a",
                turn_id="turn-1",
                omh_home=omh_home,
            )
            with open(
                os.path.join(omh_home, "runtime", "awareness_delivery.json"), "rb"
            ) as handle:
                before_suppression = handle.read()
            second = pre_llm_call(
                user_message="review this PR",
                is_first_turn=False,
                session_id="session-a",
                task_id="task-a",
                turn_id="turn-2",
                omh_home=omh_home,
            )
            with open(
                os.path.join(omh_home, "runtime", "awareness_delivery.json"), "rb"
            ) as handle:
                after_suppression = handle.read()
            different_route = pre_llm_call(
                user_message="make an image explaining the cron feature",
                is_first_turn=False,
                session_id="session-a",
                task_id="task-a",
                turn_id="turn-3",
                omh_home=omh_home,
            )
            other_session = pre_llm_call(
                user_message="review this PR",
                is_first_turn=True,
                session_id="session-b",
                task_id="task-b",
                turn_id="turn-1",
                omh_home=omh_home,
            )

            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertEqual(after_suppression, before_suppression)
            self.assertIsNotNone(different_route)
            self.assertIsNotNone(other_session)
            delivery = read_awareness_delivery(omh_home)
            self.assertEqual(delivery["delivery_count"], 3)
            self.assertEqual(delivery["suppressed_count"], 0)
            self.assertGreater(delivery["accumulated_context_chars"], 0)
            written = os.path.join(omh_home, "runtime", "awareness_delivery.json")
            with open(written, encoding="utf-8") as handle:
                serialized = handle.read()
            for raw_identifier in ("session-a", "session-b", "task-a", "task-b", "turn-1"):
                self.assertNotIn(raw_identifier, serialized)

    def test_prior_api_content_primer_is_not_replayed_for_a_new_route(self) -> None:
        with TemporaryDirectory() as omh_home:
            primer = awareness_primer_context()
            result = pre_llm_call(
                user_message="review this PR",
                conversation_history=[
                    {
                        "role": "user",
                        "content": "make an image explaining the cron feature",
                        "api_content": "make an image explaining the cron feature\n\n" + primer,
                    }
                ],
                is_first_turn=False,
                session_id="session-a",
                task_id="task-a",
                turn_id="turn-2",
                omh_home=omh_home,
            )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertNotIn("[OMH Awareness]", result["context"])
            self.assertIn("[OMH Route Hint]", result["context"])

    def test_prior_api_content_primer_suppresses_primer_only_match(self) -> None:
        with TemporaryDirectory() as omh_home:
            primer = awareness_primer_context()
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.awareness_context_matches_message",
                    return_value=True,
                ),
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.awareness_route_hint",
                    return_value={"status": "no_hint"},
                ),
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.awareness_route_hint_context_from_payload",
                    return_value="",
                ),
            ):
                result = pre_llm_call(
                    user_message="is OMH memory compatible with codebase memory?",
                    conversation_history=[
                        {
                            "role": "user",
                            "content": "prepare a safe feature plan",
                            "api_content": "prepare a safe feature plan\n\n" + primer,
                        }
                    ],
                    is_first_turn=False,
                    session_id="session-a",
                    omh_home=omh_home,
                )

            self.assertIsNone(result)

    def test_user_pasted_primer_in_sidecar_content_does_not_suppress_delivery(self) -> None:
        with TemporaryDirectory() as omh_home:
            primer = awareness_primer_context()
            result = pre_llm_call(
                user_message="review this PR",
                conversation_history=[
                    {
                        "role": "user",
                        "content": primer,
                        "api_content": primer + "\n\n[Other Plugin] unrelated context",
                    }
                ],
                is_first_turn=False,
                session_id="session-a",
                omh_home=omh_home,
            )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertIn("[OMH Awareness]", result["context"])

    def test_first_turn_route_failure_keeps_degradation_signal(self) -> None:
        route_failure = {
            "status": "no_hint",
            "degradation": {
                "components": [
                    {
                        "component": "localized_routing_text",
                        "error_type": "RuntimeError",
                    }
                ]
            },
        }
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.awareness_route_hint",
                    return_value=route_failure,
                ),
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status",
                    return_value={"runtime_state_present": True, "runs": []},
                ),
            ):
                result = pre_llm_call(
                    user_message="Hello, how are you?",
                    is_first_turn=True,
                    omh_home=omh_home,
                )

            self.assertIsNotNone(result)
            self.assertEqual(
                result["omh_degradation"]["components"],
                [{"component": "localized_routing_text", "error_type": "RuntimeError"}],
            )
            self.assertIn("[OMH Degraded] components=localized_routing_text", result["context"])

    def test_historical_runs_do_not_trigger_status_context(self) -> None:
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_activity",
                    return_value={"active_executors": []},
                ),
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status",
                    return_value={
                        "runtime_state_present": True,
                        "runs": [{"run_id": "old-run", "phase": "completed"}],
                        "active_executors": [],
                    },
                ),
                patch("omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_hud") as hud_read,
            ):
                result = pre_llm_call(
                    user_message="Hello, how are you?",
                    is_first_turn=True,
                    omh_home=omh_home,
                )

            # A completed run is history, so no status block and no HUD read.
            # The first-turn primer is unrelated to run state and rides along.
            hud_read.assert_not_called()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertNotIn("Native bridge status context", result["context"])
            self.assertNotIn("old-run", result["context"])
            self.assertIn("[OMH Awareness]", result["context"])

    def test_active_executor_triggers_status_context(self) -> None:
        active_executor = {
            "executor_profile": "codex",
            "target_type": "wrapper_session",
            "state": "active",
            "latest_event": {"status": "running"},
        }
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_activity",
                    return_value={"active_executors": [active_executor]},
                ),
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status",
                    return_value={
                        "runtime_state_present": True,
                        "runs": [],
                        "active_executors": [active_executor],
                    },
                ),
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_hud",
                    return_value={"display": {"line": "[omh] active"}},
                ) as hud_read,
            ):
                result = pre_llm_call(
                    user_message="Hello, how are you?",
                    is_first_turn=True,
                    omh_home=omh_home,
                )

            self.assertIsNotNone(result)
            self.assertIn("[omh] active", result["context"])
            self.assertIn(
                "- active executor: profile=codex, target_type=wrapper_session, state=active, status=running.",
                result["context"],
            )
            hud_read.assert_called_once()

    def test_active_executor_reuses_single_status_snapshot(self) -> None:
        status = {
            "runtime_state_present": True,
            "runs": [],
            "active_executors": [
                {
                    "executor_profile": "codex",
                    "target_type": "wrapper_session",
                    "state": "active",
                    "latest_event": {"status": "running"},
                }
            ],
        }
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_activity",
                    return_value={"active_executors": status["active_executors"]},
                ),
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status",
                    return_value=status,
                ) as status_read,
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_hud",
                    return_value={"display": {"line": "[omh] active"}},
                ) as hud_read,
            ):
                result = pre_llm_call(
                    user_message="implement this feature",
                    is_first_turn=True,
                    omh_home=omh_home,
                )

            self.assertIsNotNone(result)
            status_read.assert_called_once()
            self.assertIs(hud_read.call_args.kwargs["status"], status)

    def test_idle_turn_skips_full_status_projection(self) -> None:
        with TemporaryDirectory() as omh_home:
            with (
                patch(
                    "omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_activity",
                    return_value={"active_executors": []},
                ),
                patch("omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_status") as status_read,
                patch("omh.plugin_bundle.omh.hooks.llm_hooks.read_omh_hud") as hud_read,
            ):
                result = pre_llm_call(
                    user_message="Hello, how are you?",
                    is_first_turn=False,
                    omh_home=omh_home,
                    include_omh_awareness=False,
                )

            self.assertIsNone(result)
            status_read.assert_not_called()
            hud_read.assert_not_called()

    def test_awareness_route_hint_is_metadata_only_and_message_specific(self) -> None:
        message = "make an image explaining the cron feature with secret-token-123"

        payload = awareness_route_hint(message)
        suppressed = awareness_route_hint(message, max_hints=0)
        serialized = str(payload)

        self.assertEqual(payload["schema_version"], "omh_route_hint/v1")
        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "img-summary")
        self.assertTrue(payload["message_sha256"])
        self.assertEqual(payload["message_length"], len(message))
        self.assertFalse(payload["privacy"]["raw_prompt_stored"])
        self.assertIn("image", payload["hints"][0]["matched_cues"])
        self.assertIn("not workflow execution", payload["claim_boundary"])
        self.assertNotIn(message, serialized)
        self.assertNotIn("secret-token-123", serialized)
        self.assertEqual(suppressed["status"], "no_hint")
        self.assertEqual(suppressed["hints"], [])

    def test_awareness_route_hint_prioritizes_explicit_failure_signal_audit(self) -> None:
        message = "failure-signal-audit check this frontend and agent trace for swallowed errors, false green status, and dangerous fallbacks."

        payload = awareness_route_hint(message)

        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "failure-signal-audit")
        self.assertEqual(payload["primary_next_action"], "prepare_failure_signal_audit")
        self.assertEqual(payload["hints"][0]["id"], "direct_workflow_invocation")
        self.assertIn("remediation", payload["hints"][0]["not_evidence_yet"])
        self.assertNotEqual(payload["primary_workflow"], "frontend")

    def test_awareness_route_hint_prioritizes_explicit_accessibility_audit(self) -> None:
        message = "accessibility-audit check this frontend checkout flow for WCAG 2.2, keyboard navigation, focus order, screen reader labels, and target size."

        payload = awareness_route_hint(message)

        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "accessibility-audit")
        self.assertEqual(payload["primary_next_action"], "prepare_accessibility_audit")
        self.assertEqual(payload["hints"][0]["id"], "direct_workflow_invocation")
        self.assertIn("WCAG PASS", payload["hints"][0]["not_evidence_yet"])
        self.assertNotEqual(payload["primary_workflow"], "frontend")

    def test_awareness_route_hint_prioritizes_explicit_build_failure_triage(self) -> None:
        message = "build-failure-triage CI failed on Python 3.12 pytest and PR checks failed; make a minimal fix handoff."

        payload = awareness_route_hint(message)

        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "build-failure-triage")
        self.assertEqual(payload["primary_next_action"], "prepare_build_failure_triage")
        self.assertEqual(payload["hints"][0]["id"], "direct_workflow_invocation")
        self.assertIn("CI pass", payload["hints"][0]["not_evidence_yet"])
        self.assertNotEqual(payload["primary_workflow"], "verification-gate")

    def test_awareness_route_hint_prioritizes_failed_check_triage_over_workflow_learning(self) -> None:
        message = "CI failed on Python 3.12 pytest and PR checks failed; triage the build failure into a minimal fix handoff."

        payload = awareness_route_hint(message)

        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "build-failure-triage")
        self.assertEqual(payload["primary_next_action"], "prepare_build_failure_triage")
        self.assertEqual(payload["hints"][0]["id"], "build_failure_triage")
        self.assertIn("CI pass", payload["hints"][0]["not_evidence_yet"])
        self.assertNotEqual(payload["primary_workflow"], "workflow-learning")

    def test_awareness_route_hint_keeps_generic_check_matrix_on_verification_gate(self) -> None:
        message = "verify before merge: build lint typecheck tests and DCO evidence matrix"

        payload = awareness_route_hint(message)

        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "verification-gate")
        self.assertEqual(payload["primary_next_action"], "prepare_verification_gate")
        self.assertEqual(payload["hints"][0]["id"], "verification_gate")
        self.assertNotEqual(payload["primary_workflow"], "build-failure-triage")

    def test_awareness_route_hint_routes_fixed_failure_claims_to_verification_gate(self) -> None:
        cases = (
            "I fixed the CI failure; verify before merge",
            "CI failure is fixed, please verify before merge and check DCO",
            "CI passed after the fix; prepare merge readiness verification",
            "CI failure is fixed",
            "CI passed after the fix",
        )

        for message in cases:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertEqual(payload["status"], "hinted")
                self.assertEqual(payload["primary_workflow"], "verification-gate")
                self.assertEqual(payload["primary_next_action"], "prepare_verification_gate")
                self.assertEqual(payload["hints"][0]["id"], "verification_gate")
                self.assertNotEqual(payload["primary_workflow"], "build-failure-triage")

    def test_awareness_route_hint_uses_missed_route_primary_action(self) -> None:
        message = "missed route: Hermes skipped OMH for my image request with secret-token-123"

        payload = awareness_route_hint(message)
        context_result = pre_llm_call(user_message=message, is_first_turn=False)
        context = context_result["context"] if context_result else ""
        serialized = str(payload)

        self.assertEqual(payload["schema_version"], "omh_route_hint/v1")
        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "workflow-learning")
        self.assertEqual(payload["primary_next_action"], "record_missed_route")
        self.assertEqual(payload["hints"][0]["next_action"], "record_missed_route")
        self.assertIn("selected=workflow-learning", context)
        self.assertIn("next_action=record_missed_route", context)
        self.assertNotIn(message, serialized)
        self.assertNotIn(message, context)
        self.assertNotIn("secret-token-123", serialized)
        self.assertNotIn("secret-token-123", context)

    def test_coding_request_naming_omh_gets_no_workflow_learning_hint(self) -> None:
        # These classified meta_discussion: "test" inside "pytest" or "tests",
        # "term" inside "terminal", "log" inside "changelog" and "catalog", with
        # the product name as the routing context. The ~2k-char workflow-learning
        # hint then rode along on every model call of an ordinary coding task.
        cases = (
            "Use OMH to fix the failing test in billing.py",
            "With OMH, add a unit test for the log parser",
            "Have OMH write the missing tests for the date helpers",
            "OMH, update the changelog and the catalog metadata",
            "OMH benchmark task:\nadd minimum_cents to compute_fee in src/pricing.py.\n\n"
            "Run tests with `python -m pytest -q`.\n\nOMH benchmark protocol:\n"
            "Use the available file and terminal tools when task execution requires them.",
        )

        for message in cases:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)
                context_result = pre_llm_call(user_message=message, is_first_turn=False)
                context = context_result["context"] if context_result else ""

                self.assertNotEqual(payload.get("intent_class"), "meta_discussion")
                self.assertNotEqual(payload.get("selected_workflow"), "workflow-learning")
                self.assertNotIn("intent=meta_discussion", context)
                self.assertNotIn("selected=workflow-learning", context)

    def test_omh_meta_test_beside_omh_vocabulary_keeps_workflow_learning_hint(self) -> None:
        # The other side of the case above: an everyday word next to OMH's own
        # vocabulary or routing words is still talk about OMH.
        cases = (
            "OMH developer test: is the route hint vocabulary clear to users?",
            "I'm testing how the OMH router reads workflow names like ultrawork",
            "OMH developer test: Codex handoff vocabulary, not asking to implement.",
        )

        for message in cases:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertEqual(payload["selected_workflow"], "workflow-learning")
                self.assertIn(payload["intent_class"], {"meta_discussion", "feedback_signal"})

    def test_a_late_edit_verb_or_omh_vocabulary_keeps_workflow_learning_hint(self) -> None:
        # #2440 review: an earlier draft cleared every meta cue when an edit
        # verb followed "to" or "and" anywhere, so these talk-about-OMH turns
        # lost workflow-learning and dispatched the coding lane.
        cases = (
            "I asked OMH to fix a test and it opened workflow learning instead",
            "As an OMH operator I'd like to understand the route hint; I don't need to change anything",
            "OMH developer test: does the route hint tell users to add a workflow?",
            "Is the OMH route hint vocabulary and set of trigger words documented?",
            "Use OMH to add a term to the route hint vocabulary",
        )
        for message in cases:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertEqual(payload["selected_workflow"], "workflow-learning")

    def test_a_task_on_what_omh_picked_gets_no_workflow_learning_hint(self) -> None:
        # #2440 review: OMH inside a noun phrase names the task's object.
        cases = (
            "Copy the skills OMH selected into skills.txt",
            "Summarize the files OMH picked for this refactor",
            "Translate the summary OMH selected into Korean",
            "Show me the list OMH routed to ultrawork yesterday as a table",
        )
        for message in cases:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertNotEqual(payload.get("selected_workflow"), "workflow-learning")
                self.assertNotIn(payload.get("intent_class"), {"meta_discussion", "feedback_signal"})

    def test_korean_coding_request_gets_no_meta_hint_but_korean_meta_keeps_it(self) -> None:
        # #2440 review: 로그 matched inside 로그인, 블로그, 프로그램 and 카탈로그, and a
        # Korean code-edit request ending (작성해줘, 고쳐줘) did not count as one.
        coding = (
            "OMH, 로그인 API에 대한 통합 테스트 작성해줘",
            "테스트 코드 좀 작성해줘, OMH 환경이야",
            "개발자 모드 플래그 켜질 때 로그 남기도록 코드 고쳐줘 (OMH 세션)",
            "OMH로 블로그 프로그램 카탈로그 페이지 만들어줘",
        )
        for message in coding:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertNotEqual(payload.get("intent_class"), "meta_discussion")
                self.assertNotEqual(payload.get("selected_workflow"), "workflow-learning")

        meta = (
            "왜 ultraprocess 로그가 떠? Codex handoff 테스트 용어일 뿐이야.",
            "OMH 라우터가 로그를 잘못 읽은 것 같아",
        )
        for message in meta:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertEqual(payload["selected_workflow"], "workflow-learning")
        # A 하다 ending still makes 테스트 the cue (the hint leads with the
        # workflow it names, as on origin/main).
        self.assertEqual(awareness_route_hint("ultraprocess 용어를 테스트해보자")["intent_class"], "meta_discussion")

    def test_a_command_after_what_omh_chose_is_not_a_report(self) -> None:
        # #2440 re-review: a clause opened by OMH counted as a report even when
        # a later clause gave the user's own command.
        commands = (
            "OMH chose the release-cut workflow; go ahead and tag v1.2",
            "The OMH router picked the deploy skill; now run it on staging",
            "The OMH router picked the billing skill; now write the invoice export for me",
            "OMH picked the frontend skill, so build the settings page",
            "OMH picked these files; copy them to the backup folder",
            "OMH chose three skills for this. Run them in order and paste the output",
            "OMH selected five files. Open each one and run black",
            "OMH selected the right files. Now refactor them into one module",
            "OMH selected the wrong Python version, so set it to 3.12 in pyproject",
            # #2440 re-review 3.
            "OMH picked the release branch; bump the version to 2.1",
            "OMH picked the nightly pipeline, kick off a run",
            "OMH selected the build. Ship it",
            "OMH picked these files; check them into git",
            "OMH chose the parser module, find the bug in it",
            "OMH picked this function. Explain it line by line",
            "OMH chose these tests, then run them",
            # #2440 follow-up: "find out" before an object question is a command.
            "OMH picked the config. Find out which keys are unused",
            "OMH chose the module, find out where it is imported",
            "OMH picked the test file; find out whether it covers the parser",
            "OMH chose this function, find out what calls it",
            "OMH picked the API module; find out how many endpoints it exposes",
        )
        for message in commands:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertNotEqual(payload.get("selected_workflow"), "workflow-learning")
                self.assertNotEqual(payload.get("intent_class"), "feedback_signal")

        reports = (
            "OMH picked code-review, and I only asked a question",
            "Ask OMH to fix a test and watch it open workflow learning, that's the bug",
            "OMH picked the wrong skill; show me why",
            "OMH chose ultrawork for a typo, list the reasons it did that",
            "OMH routed my typo to ultrawork, find out what happened",
            "OMH picked the wrong skill again; find out why",
            "OMH chose ultrawork for a typo, find out the reason",
            # #2454 review: near-synonyms of a cause stay reports, not only the listed three.
            "OMH picked the wrong skill again; find out the reasons",
            "OMH chose ultrawork for a typo, find out how that happened",
            "OMH picked the wrong skill, find out what caused it",
            "OMH chose ultrawork for 'hi'; find out where that decision came from",
        )
        for message in reports:
            with self.subTest(message=message):
                self.assertEqual(awareness_route_hint(message)["selected_workflow"], "workflow-learning")

    def test_report_on_omh_routing_keeps_workflow_learning_but_throwaway_tests_do_not(self) -> None:
        # Owner decision on #2440: OMH or its router choosing or reading wrong
        # is talk about OMH; a throwaway test message, or the user's own router,
        # is not.
        reports = (
            "the OMH router misread my last message; let's look at why",
            "OMH's router chose the wrong workflow for my question",
        )
        for message in reports:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertEqual(payload["selected_workflow"], "workflow-learning")
                self.assertEqual(payload["intent_class"], "feedback_signal")

        not_reports = (
            "This is a test message for OMH",
            "I'm testing OMH right now, ignore this message",
            "Our router picked the cheapest shipping option for every order; is that normal?",
            "fix the bug where the OMH router picked the wrong locale",
        )
        for message in not_reports:
            with self.subTest(message=message):
                payload = awareness_route_hint(message)

                self.assertNotEqual(payload.get("selected_workflow"), "workflow-learning")
                self.assertNotIn(payload.get("intent_class"), {"meta_discussion", "feedback_signal"})

    def test_awareness_route_hint_marks_workflow_vocabulary_as_mentioned_not_selected(self) -> None:
        message = "왜 ultraprocess 로그가 떠? Codex handoff 테스트 용어일 뿐이야."

        payload = awareness_route_hint(message)
        context_result = pre_llm_call(user_message=message, is_first_turn=False)
        context = context_result["context"] if context_result else ""

        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "workflow-learning")
        self.assertEqual(payload["selected_workflow"], "workflow-learning")
        self.assertIn(payload["intent_class"], {"meta_discussion", "feedback_signal"})
        # The legacy spelling is accepted as input and reported under the name
        # the installed skill answers to (#1249); the runtime term is
        # engine-agnostic and passes through verbatim.
        self.assertIn("ulw-process", payload["mentioned_workflows"])
        self.assertIn("Codex", payload["mentioned_runtime_terms"])
        self.assertIn("ulw-process", payload["not_executed"])
        self.assertIn("Codex", payload["not_executed"])
        self.assertIn("selected=workflow-learning", context)
        self.assertIn("mentioned_workflows=ulw-process", context)
        self.assertIn("not_executed=ulw-process, Codex", context)
        self.assertNotIn("selected=ultraprocess", context)
        self.assertNotIn(message, context)

    def test_awareness_route_hint_treats_pasted_omh_status_as_diagnostic(self) -> None:
        message = sionic_omh_usage_evaluation_prompt()

        payload = awareness_route_hint(message, max_hints=3)
        context_result = pre_llm_call(user_message=message, is_first_turn=False)
        context = context_result["context"] if context_result else ""

        self.assertEqual(payload["status"], "hinted")
        self.assertEqual(payload["primary_workflow"], "workflow-learning")
        self.assertEqual(payload["selected_workflow"], "workflow-learning")
        self.assertIn(payload["intent_class"], {"meta_discussion", "feedback_signal"})
        self.assertIn("ulw-process", payload["mentioned_workflows"])
        self.assertIn("Codex", payload["mentioned_runtime_terms"])
        self.assertIn("ulw-process", payload["not_executed"])
        self.assertIn("Codex", payload["not_executed"])
        self.assertEqual(payload["hints"][0]["workflow"], "workflow-learning")
        self.assertIn("selected=workflow-learning", context)
        self.assertIn("not_executed=ulw-process, Codex", context)
        self.assertNotIn("selected=ultraprocess", context)
        self.assertNotIn(message, context)

    def test_pre_llm_call_includes_bounded_route_hint_without_raw_message(self) -> None:
        message = "make an image explaining the cron feature with secret-token-123"

        result = pre_llm_call(user_message=message, is_first_turn=False)
        context = result["context"] if result else ""
        context_brief = result["omh_context_brief"] if result else {}

        self.assertIn("[OMH Awareness]", context)
        self.assertIn("[OMH Route Hint]", context)
        self.assertIn("selected=img-summary", context)
        self.assertIn("selected=automation-blueprint", context)
        self.assertIn("first_response_shape=Separate copy/layout/package prep", context)
        self.assertIn("fallback_action=choose_image_generator_or_prompt_only_when_missing", context)
        self.assertIn("fallback_action=confirm_schedule_delivery_and_tools", context)
        self.assertIn("not_evidence_yet=file export, image generation", context)
        self.assertEqual(context_brief["schema_version"], "omh_context_brief/v1")
        self.assertEqual(context_brief["source"], "pre_llm_call")
        self.assertEqual(
            context_brief["generic_tool_checkpoint"]["schema_version"],
            "omh_generic_tool_checkpoint/v1",
        )
        self.assertEqual(context_brief["route_hint"]["primary_workflow"], "img-summary")
        self.assertEqual(context_brief["route_hint"]["primary_next_action"], "prepare_visual_prompt_card")
        self.assertEqual(
            context_brief["route_hint"]["hints"][0]["fallback_action"],
            "choose_image_generator_or_prompt_only_when_missing",
        )
        self.assertIn(
            "generated file or image evidence",
            context_brief["route_hint"]["hints"][0]["workflow_context_card"]["first_response_shape"],
        )
        self.assertFalse(context_brief["message"]["raw_prompt_stored"])
        self.assertFalse(context_brief["message"]["raw_prompt_echoed"])
        self.assertNotIn(message, context)
        self.assertNotIn("secret-token-123", context)
        self.assertNotIn("secret-token-123", str(context_brief))

    def test_pre_llm_call_can_disable_awareness_route_hint(self) -> None:
        result = pre_llm_call(
            user_message="make an image explaining the cron feature",
            is_first_turn=False,
            include_omh_awareness=False,
        )
        context = result["context"] if result else ""

        self.assertNotIn("[OMH Awareness]", context)
        self.assertNotIn("[OMH Route Hint]", context)
        self.assertNotIn("selected=img-summary", context)

    def test_pre_llm_call_includes_catalog_question_hint_without_raw_message(self) -> None:
        message = "what OMH workflows are available with secret-token-123?"

        result = pre_llm_call(user_message=message, is_first_turn=False)
        context_brief = result["omh_context_brief"] if result else {}
        catalog_question = context_brief["catalog_question"]

        self.assertEqual(catalog_question["schema_version"], "omh_catalog_question_hint/v1")
        self.assertEqual(catalog_question["status"], "matched")
        self.assertEqual(catalog_question["next_action"], "show_workflow_picker")
        self.assertEqual(catalog_question["recommended_tool"], "omh_capabilities")
        self.assertEqual(catalog_question["recommended_tool_args"], {"action": "summary"})
        self.assertIn("omh_skill_picker/v1", catalog_question["wrapper_contracts"])
        self.assertIn("omh_capability_summary/v1", catalog_question["wrapper_contracts"])
        self.assertNotIn(message, str(context_brief))
        self.assertNotIn("secret-token-123", str(context_brief))

    def test_pre_tool_call_does_not_emit_unsupported_observer_context(self) -> None:
        cases = (
            ("image_generate", {}),
            ("write_file", {}),
            ("web_search", {}),
            ("codex_session_open", {}),
            ("python_runner", {"tool_family": "search"}),
        )

        for tool_name, extra_kwargs in cases:
            with self.subTest(tool_name=tool_name):
                result = pre_tool_call(
                    tool_name=tool_name,
                    tool_input={"prompt": "secret-token-123 should never appear"},
                    **extra_kwargs,
                )
                self.assertIsNone(result)

    def test_pre_and_post_tool_call_pair_to_close_the_in_flight_entry(self) -> None:
        with TemporaryDirectory() as omh_home:
            pre_tool_call(
                tool_name="terminal",
                tool_call_id="call-1",
                turn_id="turn-1",
                omh_home=omh_home,
            )

            activity = tool_call_activity(omh_home)
            self.assertTrue(activity["live"])
            # post_tool_call has not fired yet on this install -- liveness
            # is unanswerable even while an entry happens to be open.
            self.assertFalse(activity["post_tool_call_observed"])

            result = post_tool_call(
                tool_name="terminal",
                tool_call_id="call-1",
                turn_id="turn-1",
                status="ok",
                duration_ms=42,
                omh_home=omh_home,
            )

            self.assertIsNone(result)
            closed = tool_call_activity(omh_home)
            self.assertFalse(closed["live"])
            # post_tool_call firing at all -- regardless of whether this
            # particular call paired to an open entry -- is what tells the
            # HUD this host's negative liveness claims can be trusted (P2-1).
            self.assertTrue(closed["post_tool_call_observed"])

    def test_post_tool_call_with_no_tool_call_id_closes_nothing_but_is_still_observed(self) -> None:
        with TemporaryDirectory() as omh_home:
            pre_tool_call(tool_name="terminal", omh_home=omh_home)

            result = post_tool_call(tool_name="terminal", omh_home=omh_home)

            self.assertIsNone(result)
            activity = tool_call_activity(omh_home)
            self.assertFalse(activity["live"])
            # No tool_call_id means nothing ever opened to close, but the
            # hook still fired -- that alone is the observed signal.
            self.assertTrue(activity["post_tool_call_observed"])

    def test_a_host_that_never_calls_post_tool_call_reports_liveness_unanswerable(self) -> None:
        with TemporaryDirectory() as omh_home:
            pre_tool_call(
                tool_name="terminal",
                tool_call_id="call-1",
                turn_id="turn-1",
                omh_home=omh_home,
            )

            # post_tool_call is never invoked here -- the host
            # `_host_supports_hook` skipped registering it for.
            activity = tool_call_activity(omh_home)

            self.assertFalse(activity["post_tool_call_observed"])

    def test_an_unknown_delegate_role_is_warned_in_the_child_turn_not_at_the_call(self) -> None:
        # Hermes reads only `action` from a `pre_tool_call` result
        # (`hermes_cli/plugins.py`, `_get_pre_tool_call_directive_details`),
        # so a warning there reached no one. The child runs its goal as its
        # first user message, on platform `subagent`, and `pre_llm_call`
        # warns there.
        goal = "[omh-role:not-a-role] prepare a plan"
        for spelling in ("args", "tool_input"):
            with self.subTest(spelling=spelling):
                self.assertIsNone(pre_tool_call(tool_name="delegate_task", **{spelling: {"goal": goal}}))

        child_turn = pre_llm_call(user_message=goal, platform="subagent", is_first_turn=True)

        self.assertIn("[OMH Role Warning]", str((child_turn or {}).get("context", "")))
        self.assertIn("Unknown role 'not-a-role'", str((child_turn or {}).get("context", "")))
