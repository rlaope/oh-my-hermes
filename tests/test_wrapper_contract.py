from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()
from omh.context_safety import CONTEXT_ARTIFACT_REF_SCHEMA_VERSION
from omh.paths import OmhPaths, resolve_paths
from omh.profiles.setup import write_setup_profile
from omh.wrapper_contract import (
    build_chat_interaction_payload,
    build_chat_response_from_status,
    build_chat_status_interaction,
    build_status_card_from_status,
    messenger_rendering_contract,
)
from omh.wrapper.native_commands import build_native_command_surface, render_native_command_response
from omh.wrapper.route_hints import build_chat_route_hint_payload


class WrapperContractTests(unittest.TestCase):
    def test_chat_interaction_omits_raw_message_by_default(self) -> None:
        message = "risky refactor with private-token-123"

        payload = build_chat_interaction_payload(message, source="discord")

        serialized = json.dumps(payload)
        self.assertEqual(payload["schema_version"], "chat_interaction/v1")
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["message_length"], len(message))
        self.assertNotIn(message, serialized)
        self.assertEqual(payload["plan"]["plan"]["task_statement"], "{message}")
        self.assertEqual(payload["chat_response"]["schema_version"], "chat_response/v1")
        self.assertNotIn("omh ", json.dumps(payload["chat_response"]).lower())

    def test_chat_interaction_include_message_is_explicit_stdout_policy(self) -> None:
        message = "risky refactor with private-token-123"

        payload = build_chat_interaction_payload(message, source="discord", include_message=True)

        self.assertEqual(payload["message"], message)
        self.assertEqual(payload["redaction_policy"], "stdout_includes_message")
        self.assertEqual(payload["plan"]["plan"]["task_statement"], message)

    def test_event_metadata_is_canonical_and_thread_key_is_stable(self) -> None:
        event = {
            "event": {
                "id": "drop-me",
                "text": "diagnose installation health",
                "channel": "c1",
                "user": "u1",
                "ts": "123.4",
            },
            "unsupported": "nope",
        }

        payload = build_chat_interaction_payload(event, source="slack", source_metadata={"source_event_id": "m1", "raw": "drop"})

        self.assertEqual(payload["source_metadata"]["source_event_id"], "m1")
        self.assertEqual(payload["source_metadata"]["channel_ref"], "c1")
        self.assertEqual(payload["source_metadata"]["user_ref"], "u1")
        self.assertEqual(payload["source_metadata"]["timestamp"], "123.4")
        self.assertNotIn("raw", payload["source_metadata"])
        self.assertEqual(payload["thread_key"], "slack:c1:m1")

    def test_route_hint_payload_is_metadata_only_and_wrapper_renderable(self) -> None:
        message = "Users report a checkout bug"

        payload = build_chat_route_hint_payload(
            message,
            source="discord",
            source_metadata={"channel_ref": "c1", "user_ref": "u1"},
        )

        self.assertEqual(payload["schema_version"], "chat_route_hint/v1")
        self.assertEqual(payload["route_hint"]["schema_version"], "omh_route_hint/v1")
        self.assertEqual(payload["route_hint"]["primary_workflow"], "feedback-triage")
        self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "feedback-triage")
        self.assertEqual(payload["generic_tool_checkpoint"]["schema_version"], "omh_generic_tool_checkpoint/v1")
        self.assertIn("prep/status/learning", payload["generic_tool_checkpoint"]["body"])
        checkpoint_routes = {
            route["tool_family"]: route for route in payload["generic_tool_checkpoint"]["routes"]
        }
        self.assertEqual(checkpoint_routes["image_tools"]["primary_workflow"], "img-summary")
        self.assertEqual(checkpoint_routes["file_tools"]["primary_workflow"], "materials-package")
        self.assertEqual(checkpoint_routes["search_tools"]["primary_workflow"], "web-research")
        self.assertIn("source-finder", checkpoint_routes["search_tools"]["preferred_workflows"])
        self.assertEqual(checkpoint_routes["coding_tools"]["primary_workflow"], "ultraprocess")
        self.assertIn("prep/status/learning", payload["chat_response"]["body"])
        self.assertNotIn("generic_tool_checkpoint", payload["chat_response"]["state"])
        self.assertEqual(payload["chat_response"]["messenger_rendering"]["profile"], "discord")
        self.assertIn("prep/status/learning", payload["chat_response"]["messenger_rendering"]["checkpoint_text"])
        self.assertIn(
            "generic_tool_checkpoint_path",
            payload["wrapper_contract"],
        )
        self.assertTrue(payload["wrapper_contract"]["safe_to_render_without_shell_approval"])
        action_ids = {action["id"] for action in payload["chat_response"]["actions"]}
        self.assertIn("open_workflow", action_ids)
        self.assertIn("route_for_me", action_ids)
        self.assertIn("open_picker", action_ids)
        self.assertNotIn(message, json.dumps(payload))

    def test_route_hint_payload_prioritizes_missed_route_feedback(self) -> None:
        message = "missed route: Hermes skipped OMH for my image request with secret-token-123"

        payload = build_chat_route_hint_payload(message, source="discord")

        self.assertEqual(payload["route_hint"]["primary_workflow"], "workflow-learning")
        self.assertEqual(payload["route_hint"]["primary_next_action"], "record_missed_route")
        self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "workflow-learning")
        self.assertEqual(payload["chat_response"]["state"]["next_action"], "record_missed_route")
        self.assertIn("workflow-learning", payload["chat_response"]["body"])
        self.assertIn("record_missed_route", json.dumps(payload["route_hint"]))
        self.assertNotIn(message, json.dumps(payload))
        self.assertNotIn("secret-token-123", json.dumps(payload))

    def test_route_hint_payload_has_picker_fallback_when_no_hint_matches(self) -> None:
        payload = build_chat_route_hint_payload("zzzzzz", source="slack")

        self.assertEqual(payload["route_hint"]["status"], "no_hint")
        self.assertEqual(payload["chat_response"]["kind"], "no_route_hint")
        self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "")
        self.assertEqual(payload["generic_tool_checkpoint"]["schema_version"], "omh_generic_tool_checkpoint/v1")
        self.assertIn("Before generic tools", payload["generic_tool_checkpoint"]["body"])
        self.assertIn("Before generic tools", payload["chat_response"]["body"])
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertIn("open_picker", actions)
        self.assertIn("clarify", actions)
        self.assertNotIn("zzzzzz", json.dumps(payload))

    def test_route_hint_payload_opens_picker_for_catalog_questions(self) -> None:
        message = "what OMH workflows are available?"

        payload = build_chat_route_hint_payload(message, source="discord")

        self.assertEqual(payload["route_hint"]["status"], "hinted")
        self.assertTrue(payload["route_hint"]["catalog_question"])
        self.assertEqual(payload["route_hint"]["primary_workflow"], "oh-my-hermes")
        self.assertEqual(payload["route_hint"]["primary_next_action"], "choose_skill")
        self.assertEqual(payload["chat_response"]["kind"], "workflow_route_hint")
        self.assertEqual(payload["chat_response"]["headline"], "[omh] workflow picker is ready.")
        self.assertTrue(payload["chat_response"]["state"]["route_hint"]["catalog_question"])
        self.assertIn("instead of asking for shell approval", payload["chat_response"]["body"])
        actions = payload["chat_response"]["actions"]
        self.assertEqual([action["id"] for action in actions], ["open_workflow", "route_for_me"])
        self.assertEqual(actions[0]["submit_text"], "./omh")
        backend_commands = payload["wrapper_contract"]["next_backend_commands"]
        self.assertEqual([command["id"] for command in backend_commands], ["open_workflow", "route_for_me"])
        self.assertEqual(backend_commands[0]["command"], "omh chat interact --source <source> --json ./omh")
        self.assertNotIn(message, json.dumps(payload))

    def test_chat_interaction_renders_task_abstraction_card_without_cli_copy(self) -> None:
        message = (
            "Reproduce this Hermes and Friren setup on another MacBook, backup the state to private GitHub, "
            "and transfer the Discord gateway without duplicate responders."
        )

        payload = build_chat_interaction_payload(message, source="discord")

        self.assertEqual(payload["schema_version"], "chat_interaction/v1")
        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "agent-ops-review")
        self.assertEqual(payload["route"]["task_card"]["schema_version"], "omh_task_card/v1")
        self.assertEqual(payload["route"]["task_card"]["task_type"], "runtime_portability")
        self.assertEqual(payload["chat_response"]["kind"], "task_card")
        self.assertEqual(payload["chat_response"]["state"]["task_card"]["route_level"], "task_abstraction")
        self.assertEqual(payload["next_action"], "prepare_agent_ops_review")
        self.assertIn("runtime portability", payload["chat_response"]["body"])
        self.assertIn("not a migration workflow", payload["chat_response"]["body"])
        self.assertIn("encrypt before private GitHub upload", payload["chat_response"]["body"])
        self.assertNotIn("omh migration", json.dumps(payload).lower())
        self.assertNotIn(message, json.dumps(payload))

    def test_chat_interaction_renders_omh_maintenance_card_without_coding_handoff(self) -> None:
        payload = build_chat_interaction_payload("omh update", source="discord")

        self.assertEqual(payload["schema_version"], "chat_interaction/v1")
        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "oh-my-hermes")
        self.assertEqual(payload["route"]["task_card"]["task_type"], "omh_cli_maintenance")
        self.assertEqual(payload["route"]["task_card"]["route_level"], "operator_maintenance_command")
        self.assertEqual(payload["chat_response"]["kind"], "task_card")
        self.assertEqual(payload["next_action"], "run_omh_update")
        self.assertIn("maintenance update path", payload["chat_response"]["body"])
        self.assertIn("code changes require a separate request", payload["chat_response"]["body"])
        self.assertIn("run requested command", payload["chat_response"]["body"])
        self.assertIn("Hermes reload", payload["chat_response"]["claim_boundary"])
        self.assertIn("coding work", payload["chat_response"]["claim_boundary"])
        self.assertNotIn("prepare_coding_handoff", json.dumps(payload))

    def test_chat_interaction_surfaces_target_change_notice_without_overclaiming(self) -> None:
        notice = {
            "schema_version": "omh_target_change_notice/v1",
            "action": "ask_to_apply_target_change",
            "headline": "Hermes target setup changed.",
            "body": "I now see multiple Hermes agent targets for this workspace. Please confirm before I persist the target registry update.",
            "target_id": "hermes-123",
            "topology": {
                "schema_version": "omh_target_topology/v1",
                "mode": "multi_agent_targets",
                "transition": "single_to_multi",
                "active_agent_count": 2,
                "requires_skill_scope_awareness": True,
            },
            "apply_payload": {
                "schema_version": "omh_target_apply_payload/v1",
                "source": "chat:discord",
                "source_metadata": {
                    "agent_ref": "agent-b",
                    "hermes_home": "/tmp/hermes-b",
                    "agent_count": "2",
                },
                "persistence_contract": "Pass this source_metadata back to the OMH wrapper backend with target-change apply enabled; no raw chat prompt is required.",
            },
            "persistence": "pending_user_confirmation",
            "claim_boundary": "Target topology is setup evidence only; it does not prove another Hermes agent executed this workflow.",
        }

        payload = build_chat_interaction_payload("risky refactor", source="discord", target_notice=notice)

        actions = {action["id"] for action in payload["chat_response"]["actions"]}
        self.assertEqual(payload["target_notice"]["action"], "ask_to_apply_target_change")
        self.assertEqual(payload["target_topology"]["transition"], "single_to_multi")
        self.assertEqual(payload["chat_response"]["state"]["target_topology"]["active_agent_count"], 2)
        self.assertIn("show_target_status", actions)
        self.assertIn("apply_target_change", actions)
        apply_action = next(action for action in payload["chat_response"]["actions"] if action["id"] == "apply_target_change")
        self.assertEqual(apply_action["payload"]["target_observation"]["source_metadata"]["agent_ref"], "agent-b")
        self.assertNotIn("message", json.dumps(apply_action["payload"]))
        self.assertIn("Target topology is setup evidence only", payload["chat_response"]["claim_boundary"])
        rendering = payload["chat_response"]["messenger_rendering"]
        self.assertIn("multiple Hermes agent targets", rendering["body_preview"])
        self.assertIn("Target topology is setup evidence only", rendering["claim_boundary"])

    def test_delegate_mode_uses_setup_default_codex_executor_when_available(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, default_executor="codex")

            payload = build_chat_interaction_payload(
                "implement a focused parser fix in src/omh/parser.py and update tests",
                source="discord",
                mode="delegate",
                paths=paths,
            )

        self.assertEqual(payload["next_action"], "send_to_executor")
        self.assertEqual(payload["executor_resolution"]["source"], "setup_profile")
        self.assertEqual(payload["executor_resolution"]["default_executor"], "codex")
        self.assertEqual(payload["delegation"]["selected_executor_profile"], "codex")
        self.assertIn("executor_handoff", payload["delegation"])
        self.assertEqual(payload["chat_response"]["state"]["executor_target"], "codex")

    def test_delegate_mode_preserves_explicit_executor_override_over_setup_default(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, default_executor="codex")

            payload = build_chat_interaction_payload(
                "implement a focused parser fix in src/omh/parser.py and update tests",
                source="discord",
                mode="delegate",
                executor_target="claude-code",
                paths=paths,
            )

        self.assertEqual(payload["next_action"], "show_prompt_handoff")
        self.assertEqual(payload["executor_resolution"]["source"], "explicit")
        self.assertEqual(payload["executor_resolution"]["default_executor"], "codex")
        self.assertEqual(payload["executor_resolution"]["resolved_executor_target"], "claude-code")
        self.assertEqual(payload["delegation"]["selected_executor_profile"], "claude-code")
        self.assertNotIn("executor_handoff", payload["delegation"])
        self.assertIn("prompt_handoff", payload["delegation"])

    def test_auto_plan_coding_request_carries_setup_executor_owner(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, default_executor="claude-code")

            payload = build_chat_interaction_payload(
                "risky refactor with tests",
                source="discord",
                paths=paths,
            )

        coding_delegate = payload["plan"]["wrapper_contract"]["coding_delegate"]
        state = payload["chat_response"]["state"]
        self.assertEqual(payload["mode"], "plan")
        self.assertTrue(coding_delegate["available"])
        self.assertEqual(coding_delegate["executor_target"], "claude-code")
        self.assertEqual(coding_delegate["selected_executor_profile"], "claude-code")
        self.assertEqual(coding_delegate["prepared_handoff_field"], "prompt_handoff")
        self.assertEqual(coding_delegate["executor_resolution"]["source"], "setup_profile")
        self.assertEqual(state["selected_executor_profile"], "claude-code")
        self.assertFalse(state["executor_choice_required"])
        self.assertIn("not dispatch", state["prepared_handoff_boundary"])

    def test_plan_mode_choose_executor_default_exposes_choice_requirement(self) -> None:
        payload = build_chat_interaction_payload(
            "risky refactor with tests",
            source="discord",
            mode="plan",
        )

        coding_delegate = payload["plan"]["wrapper_contract"]["coding_delegate"]
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(coding_delegate["executor_target"], "choose")
        self.assertTrue(coding_delegate["executor_choice_required"])
        self.assertEqual(coding_delegate["after_acceptance_next_action"], "choose_executor")
        self.assertTrue(payload["chat_response"]["state"]["executor_choice_required"])
        self.assertIn("choose_executor", actions)
        self.assertTrue(actions["choose_executor"]["enabled"])

    def test_route_coding_workflow_uses_setup_runtime_handoff_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, default_executor="omx-runtime")

            payload = build_chat_interaction_payload(
                "research the repo, plan, implement, code-review, sync docs, and prepare a PR",
                source="discord",
                paths=paths,
            )

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "ultraprocess")
        self.assertEqual(payload["next_action"], "show_runtime_handoff")
        self.assertEqual(payload["executor_resolution"]["source"], "setup_profile")
        self.assertEqual(payload["delegation"]["selected_executor_profile"], "omx-runtime")
        self.assertEqual(payload["delegation"]["runtime_handoff"]["status"], "prepared_not_observed")
        self.assertEqual(payload["chat_response"]["state"]["selected_executor_profile"], "omx-runtime")
        self.assertEqual(payload["chat_response"]["state"]["handoff_status"], "prepared_not_observed")
        self.assertIn("prepared only", payload["chat_response"]["claim_boundary"])
        self.assertIn("has not started", payload["chat_response"]["claim_boundary"])

    def test_route_coding_workflow_requires_executor_choice_without_default(self) -> None:
        payload = build_chat_interaction_payload(
            "research the repo, plan, implement, code-review, sync docs, and prepare a PR",
            source="discord",
        )

        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "ultraprocess")
        self.assertEqual(payload["next_action"], "choose_executor")
        self.assertTrue(payload["delegation"]["executor_selection"]["choice_required"])
        self.assertTrue(payload["chat_response"]["state"]["executor_choice_required"])
        self.assertIn("choose_executor", actions)
        self.assertIn("not dispatch", payload["chat_response"]["claim_boundary"])

    def test_clarify_mode_has_no_handoff_actions(self) -> None:
        payload = build_chat_interaction_payload("fix maybe", mode="delegate")

        actions = {action["id"] for action in payload["chat_response"]["actions"]}
        self.assertEqual(payload["next_action"], "answer_clarification")
        self.assertNotIn("prepare_handoff", actions)
        self.assertNotIn("send_to_codex", actions)
        self.assertNotIn("executor_handoff", json.dumps(payload))

    def test_delegate_mode_exposes_executor_neutral_action_for_codex_handoff(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", mode="delegate", source="discord", executor_target="codex")

        actions = {action["id"] for action in payload["chat_response"]["actions"] if action["enabled"]}
        readiness = payload["delegation"]["executor_readiness"]
        self.assertEqual(payload["next_action"], "send_to_executor")
        self.assertEqual(payload["delegation"]["executor_handoff"]["schema_version"], "coding_executor_handoff/v1")
        self.assertEqual(payload["delegation"]["executor_handoff"]["send_action"], "send_to_executor")
        self.assertTrue(payload["delegation"]["executor_handoff"]["codex_skill"].startswith("$"))
        self.assertEqual(readiness["schema_version"], "executor_readiness/v1")
        self.assertEqual(readiness["profile"], "codex")
        self.assertEqual(readiness["probe"]["command"], "codex")
        self.assertTrue(readiness["first_use_only"])
        self.assertTrue(readiness["fallback_policy"]["retry_after_state_change"])
        self.assertEqual(payload["delegation"]["executor_handoff"]["executor_readiness"]["profile"], "codex")
        self.assertEqual(payload["chat_response"]["state"]["executor_readiness"]["profile"], "codex")
        self.assertIn("send_to_executor", actions)
        self.assertIn("send_to_codex", actions)

    def test_delegate_mode_defaults_to_executor_choice(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", mode="delegate", source="discord")

        actions = {action["id"] for action in payload["chat_response"]["actions"] if action["enabled"]}
        readiness = payload["delegation"]["executor_readiness"]
        option_profiles = {option["profile"]: option for option in payload["delegation"]["executor_selection"]["options"]}
        self.assertEqual(payload["next_action"], "choose_executor")
        self.assertEqual(payload["delegation"]["executor_selection"]["status"], "executor_choice_required")
        self.assertTrue(payload["delegation"]["executor_selection"]["choice_required"])
        self.assertEqual(readiness["schema_version"], "executor_readiness/v1")
        self.assertEqual(readiness["status"], "choice_required")
        self.assertTrue(readiness["first_use_only"])
        self.assertIn("profiles", readiness)
        self.assertEqual(option_profiles["codex"]["readiness_probe"]["probe"]["command"], "codex")
        self.assertEqual(option_profiles["claude-code"]["readiness_probe"]["probe"]["command"], "claude")
        self.assertTrue(option_profiles["codex"]["readiness_probe"]["fallback_policy"]["retry_after_state_change"])
        self.assertEqual(payload["chat_response"]["state"]["executor_readiness"]["status"], "choice_required")
        self.assertNotIn("executor_handoff", payload["delegation"])
        self.assertIn("choose_executor", actions)

    def test_delegate_mode_can_prepare_prompt_only_handoff(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", mode="delegate", source="discord", executor_target="claude-code")

        actions = {action["id"] for action in payload["chat_response"]["actions"] if action["enabled"]}
        readiness = payload["delegation"]["executor_readiness"]
        self.assertEqual(payload["next_action"], "show_prompt_handoff")
        self.assertEqual(payload["delegation"]["work_owner_mode"], "prompt_only_handoff")
        self.assertFalse(payload["delegation"]["dispatchable"])
        self.assertEqual(payload["delegation"]["prompt_handoff"]["schema_version"], "coding_prompt_handoff/v1")
        self.assertEqual(readiness["profile"], "claude-code")
        self.assertEqual(readiness["probe"]["command"], "claude")
        self.assertEqual(payload["delegation"]["prompt_handoff"]["executor_readiness"]["profile"], "claude-code")
        self.assertNotIn("executor_handoff", payload["delegation"])
        self.assertIn("show_prompt_handoff", actions)
        self.assertIn("copy_prompt_handoff", actions)

    def test_delegate_mode_can_prepare_runtime_handoff(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", mode="delegate", source="discord", executor_target="omx-runtime")

        actions = {action["id"] for action in payload["chat_response"]["actions"]}
        runtime = payload["delegation"]["runtime_handoff"]
        readiness = payload["delegation"]["executor_readiness"]
        self.assertEqual(payload["next_action"], "show_runtime_handoff")
        self.assertEqual(payload["delegation"]["work_owner_mode"], "runtime_handoff")
        self.assertFalse(payload["delegation"]["dispatchable"])
        self.assertEqual(runtime["schema_version"], "coding_runtime_handoff/v1")
        self.assertEqual(runtime["runtime_profile"]["runtime_family"], "omx")
        self.assertEqual(readiness["profile"], "omx-runtime")
        self.assertEqual(readiness["probe"]["command"], "omx")
        self.assertEqual(runtime["executor_readiness"]["profile"], "omx-runtime")
        self.assertTrue(runtime["runtime_profile"]["supports_team_swarm"])
        self.assertTrue(runtime["runtime_profile"]["supports_tmux_workers"])
        self.assertTrue(runtime["runtime_profile"]["supports_worker_protocol"])
        self.assertTrue(runtime["runtime_profile"]["supports_worktree_guidance"])
        self.assertIn("team", runtime["team_contract"]["modes"])
        self.assertIn("swarm", runtime["team_contract"]["modes"])
        self.assertTrue(any("tmux" in value for value in runtime["team_contract"]["worker_protocol"]))
        self.assertIn("show_runtime_handoff", actions)
        self.assertIn("start_runtime", actions)
        self.assertIn("prepare_worktree", actions)
        self.assertNotIn("prompt_handoff", payload["delegation"])

    def test_delegate_mode_can_prepare_hermes_coding_team_path(self) -> None:
        payload = build_chat_interaction_payload("coordinate a safe coding team for a risky refactor", mode="delegate", source="discord", executor_target="hermes")

        actions = {action["id"] for action in payload["chat_response"]["actions"]}
        runtime = payload["delegation"]["runtime_handoff"]
        team_path = runtime["hermes_coding_team_path"]
        modes = {mode["id"] for mode in team_path["start_modes"]}

        self.assertEqual(payload["next_action"], "show_runtime_handoff")
        self.assertEqual(runtime["runtime_profile"]["runtime_family"], "omh")
        self.assertTrue(runtime["runtime_profile"]["supports_hermes_coding_team_path"])
        self.assertEqual(team_path["schema_version"], "hermes_coding_team_path/v1")
        self.assertEqual(team_path["status"], "prepared_not_observed")
        self.assertIn("solo", modes)
        self.assertIn("team", modes)
        self.assertIn("swarm", modes)
        self.assertIn("runtime_start", team_path["status_ladder"])
        self.assertIn("worker_dispatch", team_path["status_ladder"])
        self.assertIn("show_coding_team_path", actions)
        self.assertIn("start_hermes_coding", actions)
        self.assertIn("record_runtime_observation", actions)
        self.assertIn("record_runtime_observation", team_path["wrapper_actions"])
        self.assertIn("prepared only", payload["chat_response"]["claim_boundary"].lower())

    def test_route_mode_surfaces_recommendation_policy_actions(self) -> None:
        payload = build_chat_interaction_payload(
            "prepare weekly ops review from customer feedback and release risks",
            source="discord",
        )

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "prepare_ops_review")
        response = payload["chat_response"]
        actions = {str(action["id"]): action for action in response["actions"]}

        self.assertEqual(response["kind"], "ops_review")
        self.assertEqual(response["plain_headline"], "I can turn this into an operating review.")
        self.assertEqual(response["state"]["selected_workflow"], "ops-review")
        self.assertEqual(response["state"]["policy_next_action"], "prepare_ops_review")
        self.assertEqual(response["state"]["artifact_schema"], "ops_review_card/v1")
        self.assertIn("observed status", response["body"])
        self.assertIn("release risks", response["body"])
        self.assertIn("Unknowns stay visible", response["body"])
        self.assertTrue(actions["prepare_ops_review"]["enabled"])
        self.assertIn("prepare_report_package", actions)
        self.assertIn("source status review", response["state"]["evidence_not_observed"])
        self.assertIn("release decision", response["state"]["workflow_explanation"]["not_evidence_yet"])
        self.assertIn("not implementation", payload["chat_response"]["claim_boundary"])

    def test_workflow_learning_route_exposes_audit_card_actions(self) -> None:
        messages = (
            "learn from this workflow run",
            "I want Hermes to learn from this workflow and improve the skill next time",
        )

        for message in messages:
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                serialized = json.dumps(payload)
                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], "workflow-learning")
                self.assertEqual(payload["next_action"], "audit_learning_readiness")
                response = payload["chat_response"]
                self.assertEqual(response["kind"], "workflow_learning")
                self.assertEqual(response["state"]["learning_audit_card_schema"], "learning_audit_card/v1")
                self.assertEqual(response["state"]["learning_intent"], "readiness_audit")
                self.assertEqual(response["state"]["primary_learning_action"], "audit_learning_readiness")
                self.assertTrue(response["state"]["human_gate_required"])
                self.assertIn("workflow_learning_trace/v1", response["state"]["artifact_schemas"])
                self.assertIn("workflow_eval_result/v1", response["state"]["artifact_schemas"])
                self.assertIn("learning_missed_route_result/v1", response["state"]["artifact_schemas"])
                self.assertIn("improvement_candidate/v1", response["state"]["artifact_schemas"])
                self.assertIn("improvement_candidate_review_card/v1", response["state"]["artifact_schemas"])
                self.assertIn("improvement_patch_proposal/v1", response["state"]["artifact_schemas"])
                self.assertIn("workflow_learning_review_queue/v1", response["state"]["artifact_schemas"])
                self.assertIn("regression_case/v1", response["state"]["artifact_schemas"])
                self.assertIn("workflow_learning_export/v1", response["state"]["artifact_schemas"])
                self.assertEqual(
                    response["state"]["learning_review_queue_schema"],
                    "workflow_learning_review_queue/v1",
                )
                self.assertEqual(
                    response["state"]["improvement_candidate_review_card_schema"],
                    "improvement_candidate_review_card/v1",
                )
                actions = {action["id"]: action for action in response["actions"]}
                self.assertTrue(actions["audit_learning_readiness"]["enabled"])
                self.assertEqual(actions["audit_learning_readiness"]["style"], "primary")
                self.assertIn("record_workflow_learning_trace", actions)
                self.assertIn("record_missed_route", actions)
                self.assertIn("show_learning_review_queue", actions)
                self.assertIn("show_learning_eval", actions)
                self.assertIn("propose_skill_improvement", actions)
                self.assertIn("review_improvement", actions)
                self.assertIn("prepare_patch_proposal", actions)
                self.assertIn("show_patch_proposal", actions)
                self.assertIn("copy_patch_handoff", actions)
                self.assertIn("add_regression_case", actions)
                self.assertIn("export_learning_bundle", actions)
                self.assertIn("replay_regression_cases", actions)
                self.assertIn("check_learning_index", actions)
                self.assertIn("rebuild_learning_index", actions)
                self.assertIn("show_status", actions)
                self.assertIn("automatic skill patch", response["state"]["evidence_not_observed"])
                self.assertIn("not model training", response["claim_boundary"])
                self.assertIn("review_queue", response["state"]["learning_flow"])
                self.assertIn("record_missed_route", response["state"]["learning_flow"])
                self.assertIn("prepare_patch_proposal", response["state"]["learning_flow"])
                self.assertIn("human_review_improvement_candidate", response["state"]["learning_flow"])
                self.assertNotIn(message, serialized)

    def test_missed_route_feedback_makes_record_missed_route_primary(self) -> None:
        messages = (
            "OMH 안 썼어",
            "Hermes did not use OMH for my image request; record this as workflow learning",
            "missed route: Hermes skipped OMH for my image request",
            "missed route: OMH was not used",
        )

        for message in messages:
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                serialized = json.dumps(payload)
                response = payload["chat_response"]
                actions = {action["id"]: action for action in response["actions"]}
                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], "workflow-learning")
                self.assertEqual(payload["next_action"], "record_missed_route")
                self.assertEqual(response["kind"], "workflow_learning")
                self.assertEqual(response["state"]["learning_intent"], "missed_route")
                self.assertEqual(response["state"]["primary_learning_action"], "record_missed_route")
                self.assertEqual(actions["record_missed_route"]["style"], "primary")
                self.assertEqual(actions["audit_learning_readiness"]["style"], "secondary")
                self.assertIn("missed-route feedback", response["body"])
                self.assertIn("human review", response["body"])
                self.assertIn("automatic skill patch", response["state"]["evidence_not_observed"])
                self.assertNotIn(message, serialized)

    def test_chat_interaction_renders_learning_candidate_card_with_learn_prompt(self) -> None:
        message = (
            "make a skill from this: for PR #123 on commit abcdef123456 and run_abc123def456, "
            "run git diff --check before gh pr create"
        )

        payload = build_chat_interaction_payload(
            message,
            source="discord",
            source_metadata={
                "project_ref": "omhm",
                "channel_ref": "C-learning",
                "thread_ref": "T-learning",
                "target_ref": "hermes-agent",
                "workflow_ref": "workflow-learning",
                "executor_ref": "codex",
            },
        )
        response = payload["chat_response"]
        card = payload["learning_candidate_card"]
        actions = {action["id"]: action for action in response["actions"]}
        serialized = json.dumps(payload)

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "copy_learn_prompt")
        self.assertEqual(response["kind"], "learning_candidate")
        self.assertEqual(card["schema_version"], "learning_candidate_card/v1")
        self.assertEqual(card["persistence_target"], "skill_candidate")
        self.assertEqual(card["scope"]["project_ref"], "omhm")
        self.assertEqual(card["scope"]["channel_ref"], "C-learning")
        self.assertEqual(card["scope"]["thread_ref"], "T-learning")
        self.assertEqual(card["scope"]["target_ref"], "hermes-agent")
        self.assertEqual(card["scope"]["workflow"], "workflow-learning")
        self.assertEqual(card["scope"]["executor_runtime"], "codex")
        self.assertEqual(response["state"]["learning_candidate_status"], "prepared_not_observed")
        self.assertIn("prepared_not_observed", response["claim_boundary"])
        self.assertIn("copy_learn_prompt", actions)
        self.assertEqual(actions["copy_learn_prompt"]["payload"]["command"], "/learn")
        self.assertIn("Use observed facts only", actions["copy_learn_prompt"]["payload"]["copy_text"])
        self.assertIn("reusable Hermes skill", actions["copy_learn_prompt"]["payload"]["copy_text"])
        self.assertNotIn("#123", serialized)
        self.assertNotIn("abcdef123456", serialized)
        self.assertNotIn("run_abc123def456", serialized)

    def test_chat_interaction_memory_candidate_uses_review_action_without_learn_prompt(self) -> None:
        payload = build_chat_interaction_payload(
            "다음부터 이렇게 답해줘: 짧게 한국어로 요약해",
            source="discord",
        )
        response = payload["chat_response"]
        actions = {action["id"]: action for action in response["actions"]}
        card = payload["learning_candidate_card"]

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "prepare_memory_curation_review")
        self.assertEqual(response["kind"], "learning_candidate")
        self.assertEqual(card["persistence_target"], "memory_candidate")
        self.assertNotIn("learn_prompt", card)
        self.assertNotIn("copy_learn_prompt", actions)
        self.assertIn("prepare_memory_curation_review", actions)
        self.assertIn("memory curation review", response["body"])

    def test_learning_candidate_scope_does_not_treat_agent_ref_as_executor_runtime(self) -> None:
        payload = build_chat_interaction_payload(
            "learn this: when opening PRs, run git diff --check before gh pr create",
            source="discord",
            source_metadata={"agent_ref": "hermes-chat-target"},
        )

        card = payload["learning_candidate_card"]

        self.assertEqual(card["scope"]["executor_runtime"], "")

    def test_route_mode_exposes_visible_omh_usage_trace_for_web_research(self) -> None:
        payload = build_chat_interaction_payload(
            "web-research로 Hermes Agent와 Oh My Codex/OpenCode 계열을 비교해서 OMHM 포지셔닝 근거를 찾아줘.",
            source="discord",
        )

        response = payload["chat_response"]
        trace = response["usage_trace"]
        rendering = response["messenger_rendering"]
        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "web-research")
        self.assertEqual(trace["schema_version"], "omh_usage_trace/v1")
        self.assertEqual(trace["visible_prefix"], "[omh] web-research")
        self.assertEqual(trace["selected_harness"], "research")
        self.assertEqual(trace["evidence_state"], "prepared_not_observed")
        self.assertEqual(response["kind"], "web_research")
        explanation = response["state"]["workflow_explanation"]
        self.assertEqual(explanation["schema_version"], "omh_workflow_explanation/v1")
        self.assertEqual(explanation["selected_workflow"], "web-research")
        self.assertEqual(explanation["selected_harness"], "research")
        self.assertEqual(explanation["workflow_context_id"], "research_and_ops")
        self.assertEqual(explanation["workflow_context_card"]["id"], "research_and_ops")
        self.assertEqual(explanation["workflow_context_card"]["label"], "Research and ops")
        self.assertIn("web-research", explanation["workflow_context_card"]["representative_workflows"])
        self.assertIn("Payment failures keep coming up", explanation["workflow_context_card"]["user_examples"])
        self.assertIn("source/synthesis split", explanation["workflow_context_card"]["first_response_shape"])
        self.assertEqual(trace["workflow_context_id"], "research_and_ops")
        self.assertIn("why_this_workflow", explanation)
        self.assertEqual(explanation["next_action"], "run_hermes_research")
        self.assertIn("source retrieval", explanation["not_evidence_yet"])
        self.assertIn("citation verification", explanation["not_evidence_yet"])
        self.assertNotIn("implementation", explanation["not_evidence_yet"])
        self.assertTrue(response["headline"].startswith("[omh] web-research - "))
        self.assertEqual(response["plain_headline"], "I can gather source-backed current evidence for this.")
        self.assertIn("source boundaries", response["body"])
        self.assertIn("citation confidence", response["body"])
        actions = {action["id"]: action for action in response["actions"]}
        self.assertTrue(actions["run_hermes_research"]["enabled"])
        self.assertTrue(actions["record_source_observation"]["enabled"])
        self.assertTrue(actions["prepare_report_package"]["enabled"])
        self.assertEqual(rendering["schema_version"], "omh_messenger_rendering/v1")
        self.assertIn("markdown_table", rendering["avoid_blocks"])
        self.assertEqual(rendering["table_policy"], "convert_tables_to_bullets_for_messenger")
        self.assertEqual(rendering["prefix_policy"]["default"], "once_per_response_first_line")
        self.assertEqual(rendering["prefix_policy"]["repeat_when"], "adapter_splits_response_across_separate_messages_or_chunks")
        self.assertIn("not execution evidence", trace["claim_boundary"])

    def test_messenger_rendering_converts_markdown_tables_to_bullets(self) -> None:
        body = "\n".join(
            [
                "비교는 이렇게 보면 됩니다.",
                "",
                "| 계열 | 강점 | OMH 포지션 |",
                "| --- | --- | --- |",
                "| Hermes Agent | Skills, memory, gateway | Workflow layer |",
                "| OpenCode | TUI coding loop | Handoff target |",
                "",
                "표 이후 문단입니다.",
            ]
        )

        rendering = messenger_rendering_contract(
            visible_prefix="[omh] web-research",
            first_line="[omh] web-research - 비교 결과입니다.",
            body=body,
            claim_boundary="Research summary is not execution evidence.",
        )

        self.assertIn("markdown_table_to_bullets", rendering["transforms_applied"])
        self.assertIn("- Hermes Agent: 강점: Skills, memory, gateway; OMH 포지션: Workflow layer", rendering["body_text"])
        self.assertIn("- OpenCode: 강점: TUI coding loop; OMH 포지션: Handoff target", rendering["body_text"])
        self.assertNotIn("| --- |", rendering["body_text"])
        self.assertIn("Hermes Agent", rendering["body_preview"])
        self.assertTrue(any(block["type"] == "bullet" and "Hermes Agent" in block["text"] for block in rendering["body_blocks"]))

    def test_messenger_rendering_preserves_tables_for_rich_markdown_profile(self) -> None:
        body = "\n".join(
            [
                "비교는 이렇게 보면 됩니다.",
                "",
                "| 계열 | 강점 |",
                "| --- | --- |",
                "| Hermes | Gateway |",
            ]
        )

        rendering = messenger_rendering_contract(
            visible_prefix="[omh] web-research",
            first_line="[omh] web-research - 비교 결과입니다.",
            body=body,
            claim_boundary="Research summary is not execution evidence.",
            render_profile="rich_markdown",
        )

        self.assertEqual(rendering["render_profile"], "rich_markdown")
        self.assertEqual(rendering["body_format"], "rich_markdown")
        self.assertEqual(rendering["body_text"], body)
        self.assertEqual(rendering["transforms_applied"], [])
        self.assertIn("| --- | --- |", rendering["body_text"])
        self.assertIn("markdown_table", rendering["preferred_blocks"])
        self.assertNotIn("markdown_table", rendering["avoid_blocks"])
        self.assertEqual(rendering["table_policy"], "preserve_markdown_tables_when_supported")
        self.assertTrue(any(block["type"] == "markdown_table" for block in rendering["body_blocks"]))
        self.assertIn("- Hermes: 강점: Gateway", rendering["fallback_body_text"])
        self.assertIn("markdown_table_to_bullets", rendering["fallback_transforms_applied"])

    def test_status_interaction_uses_source_rendering_profile(self) -> None:
        table_body = "\n".join(
            [
                "| Surface | Result |",
                "| --- | --- |",
                "| Hermes TUI | preserve table |",
            ]
        )
        status = {"next_action": "custom_table_status", "safe_summary": table_body}

        hermes_payload = build_chat_status_interaction(status, source="hermes")
        discord_payload = build_chat_status_interaction(status, source="discord")
        overridden_payload = build_chat_status_interaction(
            status,
            source="hermes",
            source_metadata={"render_profile": "limited_markdown"},
        )

        hermes_rendering = hermes_payload["chat_response"]["messenger_rendering"]
        discord_rendering = discord_payload["chat_response"]["messenger_rendering"]
        overridden_rendering = overridden_payload["chat_response"]["messenger_rendering"]
        self.assertEqual(hermes_rendering["render_profile"], "rich_markdown")
        self.assertIn("| --- | --- |", hermes_rendering["body_text"])
        self.assertIn("- Hermes TUI: Result: preserve table", hermes_rendering["fallback_body_text"])
        self.assertEqual(discord_rendering["render_profile"], "limited_markdown")
        self.assertNotIn("| --- | --- |", discord_rendering["body_text"])
        self.assertIn("- Hermes TUI: Result: preserve table", discord_rendering["body_text"])
        self.assertEqual(overridden_rendering["render_profile"], "limited_markdown")
        self.assertNotIn("| --- | --- |", overridden_rendering["body_text"])

    def test_messenger_rendering_converts_tables_without_outer_pipes(self) -> None:
        body = "\n".join(
            [
                "계열 | 강점",
                "--- | ---",
                "Hermes | Gateway",
            ]
        )

        rendering = messenger_rendering_contract(
            visible_prefix="[omh] web-research",
            first_line="[omh] web-research - 비교 결과입니다.",
            body=body,
            claim_boundary="Research summary is not execution evidence.",
        )

        self.assertEqual(rendering["body_text"], "- Hermes: 강점: Gateway")
        self.assertIn("markdown_table_to_bullets", rendering["transforms_applied"])

    def test_messenger_rendering_preserves_pipe_characters_inside_cells(self) -> None:
        body = "\n".join(
            [
                "| Case | Example | Notes |",
                "| --- | --- | --- |",
                "| Escaped | `a\\|b` | keeps escaped \\| text |",
                "| Code span | `x|y` | keeps inline code pipe |",
            ]
        )

        rendering = messenger_rendering_contract(
            visible_prefix="[omh] web-research",
            first_line="[omh] web-research - 비교 결과입니다.",
            body=body,
            claim_boundary="Research summary is not execution evidence.",
        )

        self.assertIn("- Escaped: Example: `a|b`; Notes: keeps escaped | text", rendering["body_text"])
        self.assertIn("- Code span: Example: `x|y`; Notes: keeps inline code pipe", rendering["body_text"])
        self.assertIn("markdown_table_to_bullets", rendering["transforms_applied"])

    def test_messenger_rendering_keeps_tables_inside_code_fences(self) -> None:
        body = "\n".join(
            [
                "예제는 그대로 보여줘야 합니다.",
                "",
                "```markdown",
                "| key | value |",
                "| --- | --- |",
                "| a | b |",
                "```",
            ]
        )

        rendering = messenger_rendering_contract(
            visible_prefix="[omh] web-research",
            first_line="[omh] web-research - 예제입니다.",
            body=body,
            claim_boundary="Research summary is not execution evidence.",
        )

        self.assertEqual(rendering["transforms_applied"], [])
        self.assertIn("| --- | --- |", rendering["body_text"])

    def test_native_render_uses_messenger_safe_body_for_tables(self) -> None:
        body = "\n".join(
            [
                "| 계열 | 강점 |",
                "| --- | --- |",
                "| Hermes | Gateway |",
            ]
        )
        rendering = messenger_rendering_contract(
            visible_prefix="[omh] web-research",
            first_line="[omh] web-research - 비교 결과입니다.",
            body=body,
            claim_boundary="Not execution evidence.",
        )
        rendered = render_native_command_response(
            {
                "thread_key": "discord:c1:m1",
                "chat_response": {
                    "kind": "plan",
                    "headline": "[omh] web-research - 비교 결과입니다.",
                    "body": body,
                    "state": {"phase": "planning"},
                    "messenger_rendering": rendering,
                    "actions": [],
                },
            },
            source="discord",
        )

        self.assertEqual(rendered["body"], body)
        self.assertEqual(rendered["body_text"], "- Hermes: 강점: Gateway")
        self.assertEqual(rendered["body_text_source"], "messenger_rendering.body_text")
        self.assertEqual(rendered["render_warnings"], [])

    def test_native_render_warns_when_messenger_safe_body_is_missing(self) -> None:
        body = "\n".join(
            [
                "| 계열 | 강점 |",
                "| --- | --- |",
                "| Hermes | Gateway |",
            ]
        )
        rendered = render_native_command_response(
            {
                "thread_key": "discord:c1:m1",
                "chat_response": {
                    "kind": "plan",
                    "headline": "[omh] web-research - 비교 결과입니다.",
                    "body": body,
                    "state": {"phase": "planning"},
                    "messenger_rendering": {"schema_version": "omh_messenger_rendering/v1"},
                    "actions": [],
                },
            },
            source="discord",
        )

        self.assertEqual(rendered["body"], body)
        self.assertEqual(rendered["body_text"], body)
        self.assertEqual(rendered["body_text_source"], "missing_messenger_rendering.body_text")
        self.assertIn("missing_messenger_safe_body", rendered["render_warnings"])

    def test_route_mode_exposes_visible_omh_usage_trace_for_multiple_workflows(self) -> None:
        cases = (
            ("릴리즈 전에 README claim이 실제 코드와 맞는가 봐줘", "code-review"),
            ("쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?", "ultraqa"),
            ("결제 실패 이슈가 자주 나와", "feedback-triage"),
        )

        for message, workflow in cases:
            with self.subTest(workflow=workflow):
                response = build_chat_interaction_payload(message, source="discord")["chat_response"]

                self.assertEqual(response["usage_trace"]["visible_prefix"], f"[omh] {workflow}")
                self.assertTrue(response["headline"].startswith(f"[omh] {workflow} - "))
                self.assertNotIn("[omh]", response["body"])

    def test_feedback_triage_interaction_shows_investigation_before_coding(self) -> None:
        payload = build_chat_interaction_payload("결제 실패 이슈가 자주 나와", source="discord")

        response = payload["chat_response"]
        trace = response["usage_trace"]
        explanation = response["state"]["workflow_explanation"]
        actions = {action["id"]: action for action in response["actions"]}

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "feedback-triage")
        self.assertEqual(payload["next_action"], "triage_feedback")
        self.assertEqual(response["kind"], "feedback_triage")
        self.assertEqual(trace["visible_prefix"], "[omh] feedback-triage")
        self.assertEqual(trace["evidence_state"], "prepared_not_observed")
        self.assertEqual(response["plain_headline"], "I can triage this signal before anyone codes.")
        self.assertIn("cluster reports", response["body"])
        self.assertIn("reproduction questions", response["body"])
        self.assertIn("coding handoff only follows", response["body"])
        self.assertTrue(actions["triage_feedback"]["enabled"])
        self.assertFalse(actions["prepare_coding_handoff"]["enabled"])
        self.assertIn("classified bug/request/question", actions["prepare_coding_handoff"]["payload"]["requires"])
        self.assertTrue(actions["prepare_report_package"]["enabled"])
        self.assertIn("completed feedback triage", explanation["not_evidence_yet"])
        self.assertIn("reproduction evidence", explanation["not_evidence_yet"])
        self.assertIn("coding handoff", explanation["not_evidence_yet"])
        self.assertIn("verification", explanation["not_evidence_yet"])
        self.assertIn("feedback-triage", explanation["recommended_reply"])
        self.assertIn("triage feedback", explanation["recommended_reply"])
        self.assertIn("not evidence of completed feedback triage", explanation["recommended_reply"])
        self.assertNotIn("not completed feedback triage evidence", explanation["recommended_reply"])
        self.assertEqual(explanation["primary_action_label"], "Open feedback-triage")
        self.assertIn("do not claim completed feedback triage", explanation["primary_action_hint"])

    def test_plan_interaction_keeps_route_specific_reason_in_workflow_explanation(self) -> None:
        payload = build_chat_interaction_payload("I want to safely add a feature to this repo", source="discord")

        response = payload["chat_response"]
        explanation = response["state"]["workflow_explanation"]

        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["route"]["selected_skill"], "ralplan")
        self.assertEqual(response["kind"], "plan")
        self.assertEqual(explanation["selected_workflow"], "ralplan")
        self.assertIn("safe feature-change language", explanation["why_this_workflow"])
        self.assertEqual(explanation["next_action"], "accept_or_revise_plan")
        self.assertEqual(explanation["route_next_action"], "present_plan")
        self.assertIn("accept or revise plan", explanation["recommended_reply"])
        self.assertIn("not evidence of plan acceptance", explanation["recommended_reply"])
        self.assertIn("preparing a reviewed plan", explanation["route_recommended_reply"])
        self.assertIn("not evidence of execution", explanation["route_recommended_reply"])
        self.assertIn("do not claim plan acceptance", explanation["primary_action_hint"])
        self.assertIn("do not claim execution", explanation["route_primary_action_hint"])

    def test_review_quality_cards_expose_verification_boundaries(self) -> None:
        cases = (
            (
                "쿠버네티스 장애 상황에서 Cloudy가 적절히 진단하나?",
                "ultraqa",
                "qa_review",
                "I can turn this into QA scenarios and observed checks.",
                "scenario execution",
                "dispatch_to_workflow",
            ),
            (
                "AI가 했다고 했는데 실제로 뭐 했는지 모르겠다",
                "code-review",
                "review_check",
                "I can review the claims before we call this done.",
                "completed review",
                "prepare_review_or_followup_handoff",
            ),
            (
                "run an incident postmortem SLO error budget service reliability review",
                "reliability-review",
                "reliability_review",
                "I can review reliability without declaring the system healthy.",
                "SLO pass",
                "prepare_reliability_review",
            ),
        )

        for message, workflow, kind, headline, not_evidence, primary_action in cases:
            with self.subTest(workflow=workflow):
                payload = build_chat_interaction_payload(message, source="discord")

                response = payload["chat_response"]
                explanation = response["state"]["workflow_explanation"]
                actions = {str(action["id"]): action for action in response["actions"]}

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], workflow)
                self.assertEqual(response["kind"], kind)
                self.assertEqual(response["plain_headline"], headline)
                self.assertEqual(response["state"]["selected_workflow"], workflow)
                self.assertEqual(response["state"]["artifact_schema"], f"{kind}_card/v1")
                self.assertEqual(response["actions"][0]["id"], primary_action)
                self.assertIn(not_evidence, explanation["not_evidence_yet"])
                self.assertIn("verification", response["claim_boundary"].lower())
                if workflow in {"code-review", "reliability-review"}:
                    self.assertFalse(actions["prepare_coding_handoff"]["enabled"])
                if workflow == "ultraqa":
                    self.assertEqual(actions["dispatch_to_workflow"]["payload"]["claim_boundary"], "route_only_not_scenario_execution")

    def test_delivery_runtime_cards_expose_execution_boundaries(self) -> None:
        cases = (
            (
                "take this product idea from plan to deploy and monitor safely",
                "idea-to-deploy",
                "app_delivery_loop",
                "I can shape this into a product delivery loop.",
                "implementation",
                "present_app_delivery_loop",
            ),
            (
                "run a CTO loop for roadmap architecture tradeoffs delivery risk and release readiness",
                "cto-loop",
                "cto_loop",
                "I can run this as a leadership decision loop.",
                "architecture sign-off",
                "run_cto_loop",
            ),
            (
                "deploy and monitor this release with rollback and health checks",
                "deploy-and-monitor",
                "deploy_monitor_plan",
                "I can prepare the deploy and monitor plan.",
                "deploy execution",
                "prepare_deploy_monitor_plan",
            ),
            (
                "Claude Code로 넘길지 Codex로 넘길지 정해줘",
                "executor-runtime-readiness",
                "executor_runtime_readiness",
                "I can check which coding path is ready.",
                "executor dispatch",
                "prepare_executor_runtime_readiness",
            ),
        )

        for message, workflow, kind, headline, not_evidence, primary_action in cases:
            with self.subTest(workflow=workflow):
                payload = build_chat_interaction_payload(message, source="discord")

                response = payload["chat_response"]
                explanation = response["state"]["workflow_explanation"]
                actions = {str(action["id"]): action for action in response["actions"]}

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], workflow)
                self.assertEqual(response["kind"], kind)
                self.assertEqual(response["plain_headline"], headline)
                self.assertEqual(response["state"]["selected_workflow"], workflow)
                self.assertEqual(response["state"]["artifact_schema"], f"{kind}_card/v1")
                self.assertEqual(response["actions"][0]["id"], primary_action)
                self.assertIn(not_evidence, explanation["not_evidence_yet"])
                self.assertIn("execution", response["claim_boundary"].lower())
                if workflow in {"idea-to-deploy", "cto-loop"}:
                    self.assertFalse(actions["prepare_coding_handoff"]["enabled"])
                if workflow == "executor-runtime-readiness":
                    self.assertTrue(actions["choose_executor"]["enabled"])

    def test_workflow_operations_cards_expose_observation_boundaries(self) -> None:
        cases = (
            (
                "매일 아침 릴리즈 위험을 확인하고 변화가 있으면 슬랙에 알려줘",
                "automation-blueprint",
                "automation_blueprint",
                "I can turn this into a scheduled ops blueprint.",
                "host cron creation",
                "prepare_scheduled_ops_blueprint",
            ),
            (
                "우리 팀 Hermes agent 여러 명이 같이 일할 때 역할과 보드를 잡아줘",
                "agent-board",
                "agent_board",
                "I can prepare a board for multiple Hermes agents.",
                "target acceptance",
                "prepare_agent_board_card",
            ),
            (
                "Hermes가 기억하고 있는 프로젝트 맥락이 오래된 것 같아 정리해줘",
                "memory-curation-review",
                "memory_curation",
                "I can review memory and context before anything is changed.",
                "approved memory write",
                "prepare_memory_curation_review",
            ),
            (
                "route Discord Slack Telegram threads with delivery policy",
                "gateway-intent-card",
                "gateway_intent",
                "I can normalize this gateway intent before platform work.",
                "platform login",
                "prepare_gateway_intent_card",
            ),
            (
                "이 보고서를 파일로 만들어서 첨부할 수 있게 준비해줘",
                "deliverable-package",
                "deliverable_package",
                "I can prepare the deliverable package and its delivery trail.",
                "binary generation",
                "prepare_deliverable_package",
            ),
            (
                "does OMH support voice commands?",
                "voice-operator",
                "voice_operator",
                "I can turn the short request into a safe operator card.",
                "speech recognition proof",
                "prepare_voice_operator_card",
            ),
            (
                "can OMH help with MCP setup?",
                "toolbelt-readiness",
                "toolbelt_readiness",
                "I can check the tools this workflow needs before claiming it can run.",
                "MCP installation",
                "prepare_toolbelt_readiness",
            ),
            (
                "show token cost latency run history for this automation loop",
                "ops-observability-card",
                "ops_observability",
                "I can prepare observability without inventing provider truth.",
                "provider billing truth",
                "prepare_ops_observability_card",
            ),
            (
                "회의록 히스토리 관리하고 스크럼 스프린트 회고 운영 리듬 정리해줘",
                "operating-rhythm",
                "operating_rhythm",
                "I can turn this into an operating rhythm record.",
                "meeting completion",
                "prepare_operating_record",
            ),
            (
                "첨부한 엑셀을 월간 보고서 PDF랑 PPT로 만들 수 있게 정리해줘",
                "materials-package",
                "materials_package",
                "I can prepare the material package without pretending files exist.",
                "binary export",
                "prepare_material_package",
            ),
            (
                "I need a weekly leadership brief from support tickets, competitor news, and release risks",
                "research-department",
                "research_department",
                "I can organize this into a research department flow.",
                "source retrieval",
                "prepare_research_department_plan",
            ),
            (
                "GitHub issue 들어온 걸 PR 만들 수 있게 정리해줘",
                "github-event-ops",
                "github_event_ops",
                "I can prepare this GitHub event without claiming webhook work happened.",
                "webhook receipt",
                "prepare_github_event_ops_card",
            ),
        )

        for message, workflow, kind, headline, not_evidence, primary_action in cases:
            with self.subTest(workflow=workflow):
                payload = build_chat_interaction_payload(message, source="discord")

                response = payload["chat_response"]
                explanation = response["state"]["workflow_explanation"]
                actions = {str(action["id"]): action for action in response["actions"]}

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], workflow)
                self.assertEqual(response["kind"], kind)
                self.assertEqual(response["plain_headline"], headline)
                self.assertEqual(response["state"]["selected_workflow"], workflow)
                self.assertEqual(response["state"]["artifact_schema"], f"{kind}_card/v1")
                self.assertEqual(response["actions"][0]["id"], primary_action)
                self.assertIn(not_evidence, explanation["not_evidence_yet"])
                self.assertIn(not_evidence, response["claim_boundary"])
                if workflow == "github-event-ops":
                    self.assertFalse(actions["prepare_coding_handoff"]["enabled"])
                if workflow == "research-department":
                    self.assertTrue(actions["run_hermes_research"]["enabled"])
                if workflow == "memory-curation-review":
                    self.assertTrue(actions["show_memory_status"]["enabled"])
                if workflow in {"gateway-intent-card", "toolbelt-readiness", "automation-blueprint"}:
                    self.assertIn("prepare_toolbelt_readiness", actions)

    def test_blocker_status_uses_status_usage_trace_label(self) -> None:
        response = build_chat_response_from_status({"next_action": "surface_ci_blocker"})

        self.assertEqual(response["kind"], "blocker")
        self.assertTrue(response["headline"].startswith("[omh] status - "))
        self.assertEqual(response["usage_trace"]["visible_prefix"], "[omh] status")
        self.assertEqual(response["usage_trace"]["evidence_state"], "observed_partial")

    def test_omh_first_use_questions_render_quickstart_card_without_shell(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            for message in (
                "what should I do next with OMH setup?",
                "omh 상태랑 다음 액션 알려줘",
                "OMH 설치됐는데 이제 뭐해?",
                "is OMH installed correctly?",
            ):
                with self.subTest(message=message):
                    payload = build_chat_interaction_payload(message, source="discord", paths=paths)

                    self.assertEqual(payload["mode"], "status")
                    self.assertEqual(payload["next_action"], "show_quickstart")
                    self.assertEqual(payload["route"]["selected_skill"], "oh-my-hermes")
                    self.assertEqual(payload["route"]["recommendations"][0]["matched"], ["omh_quickstart_question"])
                    self.assertEqual(payload["chat_response"]["kind"], "quickstart")
                    self.assertTrue(payload["chat_response"]["headline"].startswith("[omh] quickstart - "))
                    self.assertIn("OMH quickstart is", payload["chat_response"]["body"])
                    self.assertIn("Local status:", payload["chat_response"]["body"])
                    self.assertIn("Next in Hermes:", payload["chat_response"]["body"])
                    self.assertIn("Use OMH request-to-handoff", payload["chat_response"]["body"])
                    self.assertIn("Boundary:", payload["chat_response"]["body"])
                    rendering_blocks = payload["chat_response"]["messenger_rendering"]["body_blocks"]
                    self.assertGreaterEqual(
                        sum(1 for block in rendering_blocks if block["type"] == "bullet"),
                        5,
                    )
                    state = payload["chat_response"]["state"]
                    self.assertEqual(state["status_source"], "omh_quickstart")
                    self.assertEqual(state["quickstart_card"]["schema_version"], "omh_quickstart_card/v1")
                    self.assertEqual(state["quickstart_card"]["source"], "discord")
                    roadmap = state["capability_gap_roadmap"]
                    self.assertEqual(roadmap["schema_version"], "omh_capability_gap_roadmap/v1")
                    self.assertGreaterEqual(roadmap["summary"]["baseline_product_gaps"], 1)
                    self.assertEqual(state["roadmap_next_actions"][0]["id"], "run_setup")
                    self.assertEqual(state["workflow_explanation"]["label"], "quickstart")
                    self.assertNotIn(message, json.dumps(payload))

    def test_explicit_omh_status_questions_can_still_render_probe_roadmap(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            payload = build_chat_interaction_payload("show OMH status", source="discord", paths=paths)

            self.assertEqual(payload["mode"], "status")
            self.assertEqual(payload["next_action"], "show_status")
            self.assertEqual(payload["route"]["selected_skill"], "oh-my-hermes")
            self.assertEqual(payload["chat_response"]["kind"], "status")
            self.assertTrue(payload["chat_response"]["headline"].startswith("[omh] status - "))
            self.assertIn("Current status:", payload["chat_response"]["body"])
            self.assertIn("OMH setup gaps:", payload["chat_response"]["body"])
            self.assertIn("Next action:", payload["chat_response"]["body"])
            self.assertNotIn("- Next:", payload["chat_response"]["body"])
            self.assertIn("Boundary:", payload["chat_response"]["body"])
            rendering_blocks = payload["chat_response"]["messenger_rendering"]["body_blocks"]
            self.assertGreaterEqual(
                sum(1 for block in rendering_blocks if block["type"] == "bullet"),
                4,
            )
            state = payload["chat_response"]["state"]
            self.assertEqual(state["status_source"], "omh_probe")
            roadmap = state["capability_gap_roadmap"]
            self.assertEqual(roadmap["schema_version"], "omh_capability_gap_roadmap/v1")
            self.assertGreaterEqual(roadmap["summary"]["baseline_product_gaps"], 1)
            self.assertEqual(state["roadmap_next_actions"][0]["id"], "run_setup")
            self.assertEqual(state["workflow_explanation"]["label"], "status")

    def test_direct_omh_invocation_exposes_skill_picker(self) -> None:
        payload = build_chat_interaction_payload("./omh", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "choose_skill")
        self.assertEqual(payload["route"]["selected_skill"], "oh-my-hermes")
        self.assertEqual(payload["chat_response"]["kind"], "skill_picker")
        self.assertIn("Best default:", payload["chat_response"]["body"])
        self.assertIn("Families:", payload["chat_response"]["body"])
        self.assertIn("Route for me:", payload["chat_response"]["body"])
        rendering_blocks = payload["chat_response"]["messenger_rendering"]["body_blocks"]
        self.assertGreaterEqual(
            sum(1 for block in rendering_blocks if block["type"] == "bullet"),
            5,
        )
        picker = payload["chat_response"]["state"]["skill_picker"]
        self.assertEqual(picker["schema_version"], "omh_skill_picker/v1")
        self.assertEqual(picker["selection_mode"], "single_select")
        option_ids = {option["id"] for option in picker["options"]}
        self.assertTrue({"oh-my-hermes", "deep-interview", "ralplan", "loop", "ultraprocess"} <= option_ids)
        self.assertIn("source-finder", option_ids)
        self.assertIn("paper-learning", option_ids)
        self.assertEqual(picker["featured_options"][0]["id"], "oh-my-hermes")
        picker_families = {family["id"]: family for family in picker["capability_families"]}
        self.assertEqual(picker_families["plan_and_decide"]["label"], "Plan and decide")
        self.assertIn("paper-learning", picker_families["learn_and_gather"]["primary_workflows"])
        self.assertIn("img-summary", picker_families["create_materials_and_visuals"]["primary_workflows"])
        self.assertIn("Claude Code", picker_families["delegate_coding_and_ship"]["executor_choices"])
        picker_family_workflows = [
            workflow
            for family in picker["capability_families"]
            for workflow in family["primary_workflows"]
        ]
        self.assertEqual(len(picker_family_workflows), len(set(picker_family_workflows)))
        picker_groups = {group["id"]: group for group in picker["groups"]}
        self.assertTrue({"intent_to_plan", "company_product_ops", "deliverables_and_visuals", "coding_and_runtime"} <= picker_groups.keys())
        self.assertIn("loop", picker_groups["intent_to_plan"]["option_ids"])
        self.assertIn("source-finder", picker_groups["company_product_ops"]["option_ids"])
        self.assertIn("paper-learning", picker_groups["company_product_ops"]["option_ids"])
        self.assertIn("img-summary", picker_groups["deliverables_and_visuals"]["option_ids"])
        self.assertIn("code-review", picker_groups["coding_and_runtime"]["option_ids"])
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertIn("choose_skill", actions)
        self.assertIn("search_skills", actions)
        self.assertEqual(actions["choose_skill"]["payload"]["schema_version"], "omh_skill_picker/v1")
        self.assertEqual(actions["choose_skill"]["payload"]["featured_options"][0]["id"], "oh-my-hermes")
        action_families = {family["id"]: family for family in actions["choose_skill"]["payload"]["capability_families"]}
        self.assertIn("code-review", action_families["delegate_coding_and_ship"]["primary_workflows"])
        action_groups = {group["id"]: group for group in actions["choose_skill"]["payload"]["groups"]}
        self.assertIn("feedback-triage", action_groups["company_product_ops"]["option_ids"])
        self.assertIn("source-finder", action_groups["company_product_ops"]["option_ids"])
        self.assertIn("paper-learning", action_groups["company_product_ops"]["option_ids"])
        self.assertIn("routing intent only", payload["chat_response"]["claim_boundary"])

    def test_natural_catalog_questions_open_picker_without_shell(self) -> None:
        for message in (
            "what can OMH do?",
            "what can I do with OMH?",
            "what does OMH do?",
            "how can OMH help my team?",
            "Can OMH help with planning, research, and coding?",
            "what can OMH do for planning/research/coding?",
            "Can OMH help with planning/research/coding?",
            "OMH로 뭐 할 수 있어?",
            "OMH가 뭐 해줄 수 있어?",
            "OMH는 뭘 도와줘?",
            "OMH가 우리 팀에서 어떻게 쓰여?",
            "OMH로 계획/리서치/코딩까지 도와줄 수 있어?",
            "OMH에서 deep-interview/ralplan/loop는 뭐야?",
            "OMH 명령어 뭐 있어?",
            "OMH로 할 수 있는 workflow가 뭐야?",
            "skill들은 뭐 있어?",
            "what OMH workflows are available?",
            "¿Qué comandos de OMH están disponibles?",
            "Quelles commandes OMH sont disponibles ?",
            "Welche OMH Workflows gibt es?",
            "OMHで使えるスキルは？",
            "OMH 有哪些工作流？",
            "Quais workflows do OMH estão disponíveis?",
            "Какие команды OMH доступны?",
        ):
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["next_action"], "choose_skill")
                self.assertEqual(payload["chat_response"]["kind"], "skill_picker")
                self.assertTrue(payload["chat_response"]["state"]["catalog_question"])
                self.assertIn("shell command", payload["chat_response"]["body"])
                self.assertIn("planning, ops, deliverables, coding handoffs, loops, and status", payload["chat_response"]["body"])
                self.assertIn("Start here:", payload["chat_response"]["body"])
                self.assertIn("Capability families:", payload["chat_response"]["body"])
                self.assertIn("Route for me:", payload["chat_response"]["body"])
                rendering_blocks = payload["chat_response"]["messenger_rendering"]["body_blocks"]
                self.assertGreaterEqual(
                    sum(1 for block in rendering_blocks if block["type"] == "bullet"),
                    7,
                )
                picker = payload["chat_response"]["state"]["skill_picker"]
                option_ids = {option["id"] for option in picker["options"]}
                self.assertTrue({"oh-my-hermes", "loop", "ultraprocess"} <= option_ids)
                self.assertIn("source-finder", option_ids)
                self.assertIn("paper-learning", option_ids)
                self.assertEqual(picker["featured_options"][0]["id"], "oh-my-hermes")
                picker_groups = {group["id"]: group for group in picker["groups"]}
                self.assertIn("ultraprocess", picker_groups["intent_to_plan"]["option_ids"])
                self.assertIn("img-summary", picker_groups["deliverables_and_visuals"]["option_ids"])
                primer = payload["chat_response"]["state"]["context_primer"]
                self.assertEqual(primer["schema_version"], "omh_context_primer/v1")
                self.assertIn("Hermes workflow layer", primer["summary"])
                primer_families = {family["id"]: family for family in primer["capability_families"]}
                self.assertIn("ralplan", primer_families["plan_and_decide"]["primary_workflows"])
                self.assertIn("img-summary", primer_families["create_materials_and_visuals"]["primary_workflows"])
                self.assertIn("Codex", primer_families["delegate_coding_and_ship"]["executor_choices"])
                groups = {group["id"]: group for group in primer["workflow_groups"]}
                self.assertTrue({"intent_to_plan", "company_product_ops", "deliverables_and_visuals", "coding_and_runtime"} <= groups.keys())
                self.assertIn("img-summary", groups["deliverables_and_visuals"]["workflows"])
                self.assertIn("loop", groups["intent_to_plan"]["workflows"])
                self.assertIn("feedback-triage", groups["company_product_ops"]["workflows"])
                self.assertIn("source-finder", groups["company_product_ops"]["workflows"])
                self.assertIn("paper-learning", groups["company_product_ops"]["workflows"])
                self.assertIn("code-review", groups["coding_and_runtime"]["workflows"])
                primer_cards = {card["id"]: card for card in primer["workflow_context_cards"]}
                self.assertIn("source-finder", primer_cards["research_and_ops"]["representative_workflows"])
                self.assertIn("paper-learning", primer_cards["research_and_ops"]["representative_workflows"])
                self.assertIn("img-summary", primer_cards["materials_and_visuals"]["representative_workflows"])
                self.assertIn("ultraprocess", primer_cards["coding_handoff"]["representative_workflows"])
                self.assertIn("Prepared plans", primer["evidence_rule"])
                capability_summary = payload["chat_response"]["state"]["capability_summary"]
                self.assertEqual(capability_summary["schema_version"], "omh_capability_summary/v1")
                summary_families = {family["id"]: family for family in capability_summary["capability_families"]}
                lanes = {lane["id"]: lane for lane in capability_summary["lanes"]}
                summary_cards = {card["id"]: card for card in capability_summary["workflow_context_cards"]}
                self.assertTrue({"intent_to_plan", "materials_and_visuals", "coding_handoff"} <= lanes.keys())
                self.assertIn("paper-learning", summary_families["learn_and_gather"]["primary_workflows"])
                self.assertIn("Claude Code", summary_families["delegate_coding_and_ship"]["executor_choices"])
                self.assertIn("img-summary", lanes["materials_and_visuals"]["primary_skills"])
                self.assertIn("ultraprocess", lanes["intent_to_plan"]["primary_skills"])
                self.assertIn("feedback-triage", summary_cards["research_and_ops"]["representative_workflows"])
                self.assertIn("source-finder", summary_cards["research_and_ops"]["representative_workflows"])
                self.assertIn("paper-learning", summary_cards["research_and_ops"]["representative_workflows"])
                self.assertIn("code-review", lanes["coding_handoff"]["primary_skills"])
                intent_playbooks = {playbook["id"] for playbook in lanes["intent_to_plan"]["representative_playbooks"]}
                self.assertIn("request-to-handoff", intent_playbooks)
                self.assertTrue(
                    any("Prepared OMH capability" in boundary for boundary in capability_summary["evidence_boundary"])
                )
                self.assertNotIn("run_local_operator_check", json.dumps(payload))

    def test_omh_intro_questions_render_context_brief_before_picker(self) -> None:
        for message in (
            "what is OMH and how do I use it?",
            "explain OMH for a new Hermes user",
            "OMH가 뭐야? 어떻게 써?",
            "OMH 사용법 소개해줘",
        ):
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["next_action"], "show_context_brief")
                self.assertEqual(payload["route"]["selected_skill"], "oh-my-hermes")
                self.assertEqual(payload["route"]["recommendations"][0]["matched"], ["omh_intro_question"])
                response = payload["chat_response"]
                self.assertEqual(response["kind"], "context_brief")
                self.assertTrue(response["headline"].startswith("[omh] context - "))
                self.assertIn("Hermes workflow layer", response["body"])
                self.assertIn("install once", response["body"])
                self.assertIn("Use it for:", response["body"])
                self.assertIn("How to start:", response["body"])
                self.assertIn("workflow picker", response["body"])
                rendering_blocks = response["messenger_rendering"]["body_blocks"]
                self.assertGreaterEqual(len(rendering_blocks), 5)
                self.assertGreaterEqual(
                    sum(1 for block in rendering_blocks if block["type"] == "bullet"),
                    3,
                )
                state = response["state"]
                self.assertEqual(state["status_source"], "omh_context_brief")
                self.assertEqual(state["context_brief"]["schema_version"], "omh_context_brief/v1")
                self.assertEqual(state["context_brief"]["source"], "discord")
                self.assertEqual(state["workflow_explanation"]["label"], "context")
                actions = {action["id"]: action for action in response["actions"]}
                self.assertEqual(actions["show_context_brief"]["style"], "primary")
                self.assertEqual(actions["show_skill_picker"]["style"], "secondary")
                self.assertEqual(actions["show_quickstart"]["style"], "secondary")
                self.assertNotIn(message, json.dumps(payload))

    def test_non_catalog_command_and_skill_questions_do_not_open_picker(self) -> None:
        for message in (
            "show me the command to install OMH",
            "what command is available to install OMH?",
            "what command should I run to verify installation?",
            "what can OMH do to install itself?",
            "what skills are needed to debug this Python error?",
            "what does OMH do in src/omh/routing/catalog_questions.py?",
            "explain what OMH does in this README section",
            "search docs/WORKFLOWS.md for loop",
            "show img-summary in README.md",
            "how can Hermes help my team?",
            "list files that mention command injection",
            "¿Qué comando debería ejecutar para instalar OMH?",
            "Quel workflow dois-je utiliser pour ce bug Python?",
            "Welche Datei erwähnt command injection?",
        ):
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertNotEqual(payload["chat_response"]["kind"], "skill_picker")
                self.assertNotEqual(payload["next_action"], "choose_skill")
                self.assertNotIn("catalog_question", payload["chat_response"]["state"])
                self.assertNotIn("capability_summary", payload["chat_response"]["state"])

    def test_file_lookup_fallback_card_uses_lookup_copy(self) -> None:
        for message in ("search docs/WORKFLOWS.md for loop", "README 파일 찾아줘"):
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "clarify")
                self.assertEqual(payload["route"]["action"], "fallback")
                self.assertEqual(payload["next_action"], "answer_file_lookup")
                response = payload["chat_response"]
                self.assertEqual(response["kind"], "clarification")
                self.assertIn("file or text lookup", response["body"])
                self.assertIn("file or text lookup", response["state"]["routing_instruction"])
                self.assertEqual(response["state"]["lookup_kind"], "file_or_text")
                explanation = response["state"]["workflow_explanation"]
                self.assertIn("I will answer this as a file or text lookup", explanation["route_recommended_reply"])
                self.assertNotIn("target is clear", explanation["route_recommended_reply"])
                self.assertIn("file inspection", explanation["claim_boundary"])
                self.assertIn("file inspection", explanation["not_evidence_yet"])
                self.assertNotIn("review", explanation["not_evidence_yet"])
                self.assertNotIn("choose the right workflow", response["body"])
                actions = {action["id"]: action for action in response["actions"]}
                self.assertIn("answer:file_lookup", actions)
                self.assertTrue(actions["answer:file_lookup"]["enabled"])

    def test_plain_how_to_and_text_transform_use_direct_answer_card(self) -> None:
        for message in (
            "how do I create a virtualenv in Python?",
            "just explain Python virtualenv",
            "can you explain Python virtualenv",
            "summarize this paragraph in Korean",
            "what is OAuth in simple terms?",
        ):
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "clarify")
                self.assertEqual(payload["route"]["action"], "fallback")
                self.assertEqual(payload["next_action"], "answer_directly")
                response = payload["chat_response"]
                self.assertEqual(response["kind"], "clarification")
                self.assertEqual(response["plain_headline"], "This does not need an OMH workflow.")
                self.assertEqual(response["state"]["lookup_kind"], "direct_answer")
                self.assertIn("Answer directly in the current chat", response["body"])
                self.assertIn("No OMH workflow", response["claim_boundary"])
                actions = {action["id"]: action for action in response["actions"]}
                self.assertIn("answer:direct", actions)
                self.assertTrue(actions["answer:direct"]["enabled"])

    def test_interaction_route_explanation_matches_special_route_overrides(self) -> None:
        payload = build_chat_interaction_payload("What is OMH and how should I use it?", source="discord")

        route = payload["route"]
        explanation = route["route_explanation"]
        self.assertEqual(route["selected_skill"], "oh-my-hermes")
        self.assertEqual(
            route["routing_instruction"],
            "Show the OMH context brief and offer the workflow picker as the next action.",
        )
        self.assertEqual(explanation["schema_version"], "route_explanation/v1")
        self.assertEqual(explanation["selected_workflow"], "oh-my-hermes")
        self.assertEqual(explanation["next_action"], "show_context_brief")
        self.assertIn("Context brief output", explanation["claim_boundary"])
        self.assertIn("execution", explanation["not_evidence_yet"])

    def test_partial_dot_slash_invocation_exposes_omh_command_preview_only(self) -> None:
        cases = {
            "./": "./omh",
            "/": "/omh",
            "./o": "./omh",
            "/om": "/omh",
        }

        for message, insert_text in cases.items():
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["next_action"], "show_command_preview")
                self.assertEqual(payload["chat_response"]["kind"], "command_preview")
                preview = payload["chat_response"]["state"]["command_preview"]
                self.assertEqual(preview["schema_version"], "omh_command_preview/v1")
                self.assertEqual(preview["selection_mode"], "single_top_level_command")
                self.assertEqual([suggestion["label"] for suggestion in preview["suggestions"]], ["omh"])
                self.assertEqual(preview["suggestions"][0]["insert_text"], insert_text)
                self.assertTrue(preview["top_level_aliases_only"])
                self.assertTrue(preview["hide_installed_workflows_until_picker_opens"])
                self.assertIn("telegram", preview["rendering_hints"])
                self.assertNotIn("loop", json.dumps(preview))
                self.assertNotIn("ralplan", json.dumps(preview))

    def test_native_command_surfaces_cover_major_messenger_registration_paths(self) -> None:
        cases = {
            "discord": "discord_application_command_manifest/v1",
            "slack": "slack_command_shortcut_manifest/v1",
            "telegram": "telegram_bot_command_menu/v1",
            "hermes": "hermes_tui_command_preview/v1",
        }

        for source, registration_schema in cases.items():
            with self.subTest(source=source):
                surface = build_native_command_surface(source)

                self.assertEqual(surface["schema_version"], "omh_native_command_surface/v1")
                self.assertEqual(surface["source"], source)
                self.assertEqual(surface["command"], "omh")
                self.assertEqual(surface["preview_contract"]["only_top_level_suggestions"], ["omh"])
                self.assertEqual(surface["fallback_card"]["schema_version"], "omh_command_fallback_card/v1")
                self.assertEqual(surface["fallback_card"]["primary_action"]["label"], "Open omh")
                self.assertEqual(surface["registration"]["schema_version"], registration_schema)
                self.assertIn("featured_options", " ".join(surface["rendering_steps"]))
                self.assertIn("skill_picker.groups", " ".join(surface["rendering_steps"]))
                self.assertIn("platform command installed", surface["not_evidence"])
                self.assertIn("not observed platform registration", surface["claim_boundary"])

    def test_command_preview_can_render_platform_native_fallback_card(self) -> None:
        interaction = build_chat_interaction_payload("./", source="discord")

        rendered = render_native_command_response(interaction, source="discord")

        self.assertEqual(rendered["schema_version"], "omh_native_command_render/v1")
        self.assertEqual(rendered["source"], "discord")
        self.assertEqual(rendered["response_kind"], "command_preview")
        self.assertEqual(rendered["usage_trace"]["schema_version"], "omh_usage_trace/v1")
        self.assertEqual(rendered["messenger_rendering"]["schema_version"], "omh_messenger_rendering/v1")
        self.assertEqual(rendered["render_kind"], "fallback_card")
        self.assertEqual(rendered["card"]["primary_action"]["submit_text"], "./omh")
        self.assertEqual(rendered["component"]["kind"], "discord_message_components")
        self.assertEqual(rendered["component"]["buttons"][0]["label"], "Open omh")
        self.assertIn("workflow selected", rendered["not_evidence"])

    def test_native_render_exposes_grouped_skill_picker(self) -> None:
        interaction = build_chat_interaction_payload("./omh", source="discord")

        rendered = render_native_command_response(interaction, source="discord")

        self.assertEqual(rendered["schema_version"], "omh_native_command_render/v1")
        self.assertEqual(rendered["render_kind"], "workflow_picker")
        self.assertEqual(rendered["picker_schema"], "omh_skill_picker/v1")
        self.assertEqual(rendered["featured_options"][0]["id"], "oh-my-hermes")
        rendered_groups = {group["id"]: group for group in rendered["groups"]}
        self.assertIn("intent_to_plan", rendered_groups)
        self.assertIn("deliverables_and_visuals", rendered_groups)
        component = rendered["component"]
        self.assertEqual(component["kind"], "discord_select_menu")
        self.assertEqual(component["featured_options"][0]["value"], "oh-my-hermes")
        component_groups = {group["id"]: group for group in component["groups"]}
        self.assertIn("loop", {option["value"] for option in component_groups["intent_to_plan"]["options"]})
        self.assertIn("img-summary", {option["value"] for option in component_groups["deliverables_and_visuals"]["options"]})
        self.assertIn("fallback_options", component)

    def test_direct_skills_invocation_uses_picker_not_management_skill(self) -> None:
        payload = build_chat_interaction_payload("./skills", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "choose_skill")
        self.assertEqual(payload["route"]["selected_skill"], "oh-my-hermes")
        self.assertNotEqual(payload["route"]["selected_skill"], "skill")
        self.assertEqual(payload["chat_response"]["kind"], "skill_picker")
        aliases = payload["chat_response"]["state"]["direct_invocation_aliases"]
        self.assertIn("./skills", aliases)

    def test_loop_interaction_exposes_start_card_without_raw_goal_by_default(self) -> None:
        message = "./loop make OMH a 10k-star quality Hermes-native project"

        payload = build_chat_interaction_payload(message, source="discord")

        serialized = json.dumps(payload)
        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "start_loop_cycle")
        self.assertEqual(payload["chat_response"]["kind"], "loop")
        self.assertEqual(payload["loop_start_card"]["schema_version"], "loop_start_card/v1")
        self.assertEqual(payload["loop_start_card"]["status"], "started_prepared")
        self.assertEqual(payload["loop_start_card"]["goal_summary"], "{message}")
        self.assertEqual(payload["loop_start_card"]["loop_invocation"]["progress_policy"], "do_not_stop_until_gate")
        self.assertEqual(payload["loop_start_card"]["loopability_assessment"]["loopability"], "needs_reframe")
        self.assertEqual(payload["chat_response"]["state"]["loop_start_card"]["schema_version"], "loop_start_card/v1")
        self.assertEqual(payload["chat_response"]["state"]["loopability_assessment"]["goal_kind"], "ambition")
        action_ids = {action["id"] for action in payload["chat_response"]["actions"]}
        self.assertIn("start_loop", action_ids)
        self.assertIn("start_loop", action_ids)
        self.assertIn("show_loop_queue", action_ids)
        self.assertNotIn("10k-star quality", serialized)
        self.assertEqual(action_ids, {action["id"] for action in payload["chat_response"]["actions"]})

    def test_loop_interaction_routes_tiny_goal_to_direct_task_action(self) -> None:
        payload = build_chat_interaction_payload("./loop change the button color", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "route_direct_task")
        self.assertEqual(payload["chat_response"]["kind"], "loop")
        self.assertEqual(payload["loop_start_card"]["loopability_assessment"]["goal_kind"], "task")
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertTrue(actions["route_direct_task"]["enabled"])
        self.assertFalse(actions["start_loop"]["enabled"])

    def test_terse_loop_invocation_starts_agentic_loop_without_picker(self) -> None:
        payload = build_chat_interaction_payload("loop reinforcement omh", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "start_loop_cycle")
        self.assertEqual(payload["chat_response"]["kind"], "loop")
        self.assertNotEqual(payload["chat_response"]["kind"], "skill_picker")
        self.assertEqual(payload["loop_start_card"]["status"], "started_prepared")
        self.assertEqual(payload["loop_start_card"]["loop_invocation"]["progress_policy"], "do_not_stop_until_gate")
        self.assertIn("deep-interview", payload["loop_start_card"]["core_skills"])
        self.assertIn("ralplan", payload["loop_start_card"]["core_skills"])
        self.assertIn("ultragoal", payload["loop_start_card"]["core_skills"])
        self.assertIn("team", payload["loop_start_card"]["core_skills"])
        self.assertEqual(payload["chat_response"]["state"]["permission_profile_required"], False)
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertTrue(actions["start_loop"]["enabled"])
        self.assertFalse(actions["run_loop_tick"]["enabled"])
        self.assertEqual(
            1,
            sum(1 for action in payload["chat_response"]["actions"] if action["id"] == "start_loop"),
        )

        korean = build_chat_interaction_payload("OMH 루프 강화 ㄱㄱ", source="discord")
        self.assertEqual(korean["mode"], "route")
        self.assertTrue(korean["route"]["explicit"])
        self.assertEqual(korean["next_action"], "start_loop_cycle")
        self.assertEqual(korean["chat_response"]["kind"], "loop")
        self.assertEqual(korean["loop_start_card"]["loop_invocation"]["progress_policy"], "do_not_stop_until_gate")

        empty_command = build_chat_interaction_payload("./loop", source="discord")
        self.assertEqual(empty_command["next_action"], "ask_goal_boundary")
        self.assertIn("clarification", empty_command["chat_response"]["headline"].lower())
        empty_actions = {action["id"]: action for action in empty_command["chat_response"]["actions"]}
        self.assertFalse(empty_actions["start_loop"]["enabled"])
        self.assertFalse(empty_actions["choose_permission_profile"]["enabled"])

        help_command = build_chat_interaction_payload("omh loop help", source="discord")
        self.assertEqual(help_command["next_action"], "ask_goal_boundary")
        self.assertTrue(help_command["route"]["explicit"])
        help_actions = {action["id"]: action for action in help_command["chat_response"]["actions"]}
        self.assertFalse(help_actions["start_loop"]["enabled"])

    def test_loop_mentions_do_not_force_explicit_loop_dispatch(self) -> None:
        lookup = build_chat_interaction_payload("look up OMH loop docs", source="discord")

        self.assertNotEqual(lookup["next_action"], "start_loop_cycle")
        lookup_actions = {action["id"]: action for action in lookup["chat_response"].get("actions", [])}
        if "start_loop" in lookup_actions:
            self.assertFalse(lookup_actions["start_loop"]["enabled"])

        loopback = build_chat_interaction_payload("loopback interface on OMH is broken", source="discord")
        self.assertNotEqual(loopback["next_action"], "start_loop_cycle")

    def test_loopable_north_star_stays_loop_before_coding_handoff(self) -> None:
        payload = build_chat_interaction_payload("100k star OSS 만들기 위해 first-run friction 줄여줘", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "loop")
        self.assertEqual(payload["next_action"], "choose_permission_profile")
        self.assertEqual(payload["chat_response"]["kind"], "loop")
        self.assertNotIn("delegation", payload)
        self.assertEqual(payload["chat_response"]["state"]["loopability_assessment"]["loopability"], "loopable")
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertIn("choose_permission_profile", actions)
        self.assertIn("start_loop", actions)
        self.assertTrue(actions["start_loop"]["enabled"])

    def test_ultraprocess_interaction_exposes_process_actions(self) -> None:
        cases = (
            (
                "research the repo, plan, implement, code-review, sync docs, and prepare a PR",
                "choose_executor",
                True,
                "choose_executor",
                "Choose coding agent",
            ),
            (
                "이 이슈를 Codex로 구현하게 맡기고 진행상태 추적해줘",
                "show_coding_handoff_status",
                False,
                "show_coding_handoff_status",
                "Show coding status",
            ),
        )

        for message, next_action, choice_required, primary_action, primary_label in cases:
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["next_action"], next_action)
                self.assertEqual(payload["chat_response"]["kind"], "handoff")
                self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "ultraprocess")
                self.assertEqual(payload["chat_response"]["state"]["executor_choice_required"], choice_required)
                self.assertEqual(payload["delegation"]["executor_selection"]["choice_required"], choice_required)
                explanation = payload["chat_response"]["state"]["workflow_explanation"]
                self.assertEqual(explanation["selected_workflow"], "ultraprocess")
                self.assertEqual(explanation["workflow_context_id"], "intent_to_plan")
                self.assertIn("ultraprocess", explanation["workflow_context_card"]["representative_workflows"])
                self.assertIn(
                    "executor/runtime dispatch" if choice_required else "execution",
                    explanation["not_evidence_yet"],
                )
                actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
                self.assertTrue(actions[primary_action]["enabled"])
                self.assertEqual(actions[primary_action]["label"], primary_label)
                if choice_required:
                    self.assertIn("not dispatch", payload["chat_response"]["claim_boundary"])
                else:
                    self.assertIn("not execution evidence", payload["chat_response"]["claim_boundary"])

    def test_codex_status_question_surfaces_session_evidence_boundary(self) -> None:
        payload = build_chat_interaction_payload("Codex 작업이 어디까지 진행됐는지 알려줘", source="discord")

        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        state = payload["chat_response"]["state"]
        self.assertEqual(payload["route"]["selected_skill"], "ultraprocess")
        self.assertEqual(payload["next_action"], "show_coding_handoff_status")
        self.assertEqual(payload["executor_resolution"]["source"], "message_mention")
        self.assertEqual(payload["executor_resolution"]["resolved_executor_target"], "codex")
        self.assertEqual(state["selected_executor_profile"], "codex")
        self.assertTrue(state["coding_status_request"])
        self.assertTrue(state["route_context"]["coding_status_request"])
        self.assertIn("session evidence is not attached yet", payload["chat_response"]["headline"])
        self.assertEqual(actions["show_coding_handoff_status"]["label"], "Show coding status")
        self.assertEqual(actions["send_to_executor"]["label"], "Open in Codex")
        self.assertEqual(actions["send_to_codex"]["label"], "Open in Codex")
        self.assertFalse(actions["attach_executor_session"]["enabled"])
        self.assertIn("wrapper session id", actions["attach_executor_session"]["payload"]["disabled_reason"])

    def test_claude_code_status_question_surfaces_prompt_session_boundary(self) -> None:
        payload = build_chat_interaction_payload("Claude Code session looks stuck", source="discord")

        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        state = payload["chat_response"]["state"]
        self.assertEqual(payload["route"]["selected_skill"], "ultraprocess")
        self.assertEqual(payload["next_action"], "show_coding_handoff_status")
        self.assertEqual(payload["executor_resolution"]["source"], "message_mention")
        self.assertEqual(payload["executor_resolution"]["resolved_executor_target"], "claude-code")
        self.assertEqual(state["selected_executor_profile"], "claude-code")
        self.assertTrue(state["coding_status_request"])
        self.assertIn("session evidence is not attached yet", payload["chat_response"]["headline"])
        self.assertEqual(actions["show_coding_handoff_status"]["label"], "Show coding status")
        self.assertEqual(actions["show_prompt_handoff"]["label"], "Show Claude Code prompt")
        self.assertEqual(actions["copy_prompt_handoff"]["label"], "Copy Claude Code prompt")
        self.assertEqual(actions["choose_executor"]["label"], "Change coding agent")
        self.assertFalse(actions["attach_executor_session"]["enabled"])

    def test_visual_summary_interaction_exposes_prompt_card_actions(self) -> None:
        cases = (
            "Make a PR summary card",
            "크론 기능 설명 이미지 하나 만들어줘",
            "이 회의록을 세로 이미지 카드로 만들어줘",
            "이미지 생성 기능 뭐 있어?",
            "what image generation features does OMH have?",
            "does OMH support image generation?",
            "이미지 생성해줘",
            "이미지 만들어줘",
            "generate an image",
            "프리렌이 OMH 안 쓰고 일반 도구로 이미지 만들었어",
        )

        for message in cases:
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["next_action"], "prepare_visual_prompt_card")
                self.assertEqual(payload["chat_response"]["kind"], "img_summary")
                self.assertIn("shareable image-card brief", payload["chat_response"]["body"])
                self.assertIn("If no image tool is connected", payload["chat_response"]["body"])
                self.assertNotIn("visual_prompt_card/v1", payload["chat_response"]["body"])
                self.assertNotIn("image_generation_capability/v1", payload["chat_response"]["body"])
                self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "img-summary")
                self.assertEqual(payload["chat_response"]["state"]["artifact_schema"], "visual_prompt_card/v1")
                self.assertEqual(payload["chat_response"]["state"]["observation_schema"], "visual_observation/v1")
                self.assertEqual(payload["chat_response"]["state"]["image_generation_capability"], "unknown")
                setup = payload["chat_response"]["state"]["image_generation_setup"]
                self.assertEqual(setup["schema_version"], "image_generation_setup/v1")
                self.assertTrue(setup["required"])
                self.assertEqual(setup["recommended_option"], "gpt-image")
                self.assertEqual(setup["next_action"], "choose_image_generator")
                self.assertIn("GPT image tool", {option["label"] for option in setup["options"]})
                actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
                self.assertTrue(actions["show_visual_prompt_card"]["enabled"])
                self.assertTrue(actions["copy_visual_prompt"]["enabled"])
                self.assertTrue(actions["choose_image_generator"]["enabled"])
                self.assertTrue(actions["setup_image_generator"]["enabled"])
                self.assertTrue(actions["record_visual_image"]["enabled"])
                self.assertNotIn("generate_visual_image", actions)
                self.assertIn("not generated image", payload["chat_response"]["claim_boundary"])
                self.assertIn("visual QA", payload["chat_response"]["state"]["evidence_not_observed"])
                explanation = payload["chat_response"]["state"]["workflow_explanation"]
                self.assertEqual(explanation["selected_workflow"], "img-summary")
                self.assertEqual(explanation["workflow_context_id"], "materials_and_visuals")
                self.assertEqual(explanation["workflow_context_card"]["id"], "materials_and_visuals")
                self.assertIn("generated file or image evidence", explanation["workflow_context_card"]["first_response_shape"])
                self.assertIn("workflow's triggers", explanation["why_this_workflow"])
                self.assertIn("image_generation_setup/v1", explanation["why_this_workflow"])
                self.assertIn("visual QA", explanation["not_evidence_yet"])

    def test_paper_learning_interaction_uses_learning_evidence_not_coding_gates(self) -> None:
        payload = build_chat_interaction_payload("explique ce PDF de recherche simplement", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "prepare_paper_learning")
        self.assertEqual(payload["chat_response"]["kind"], "paper_learning")
        self.assertIn("paper-learning card", payload["chat_response"]["body"])
        self.assertNotIn("CI", payload["chat_response"]["body"])
        self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "paper-learning")
        self.assertEqual(payload["chat_response"]["state"]["artifact_schema"], "paper_learning_card/v1")
        self.assertEqual(payload["chat_response"]["state"]["source_state_schema"], "paper_source_state/v1")
        self.assertEqual(payload["chat_response"]["state"]["coverage_ledger_schema"], "paper_coverage_ledger/v1")
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertTrue(actions["choose_explanation_level"]["enabled"])
        self.assertTrue(actions["show_paper_learning"]["enabled"])
        self.assertTrue(actions["record_file_text_extraction_observed"]["enabled"])
        self.assertIn("full PDF extraction", payload["chat_response"]["claim_boundary"])
        self.assertIn("figure OCR", payload["chat_response"]["state"]["evidence_not_observed"])
        explanation = payload["chat_response"]["state"]["workflow_explanation"]
        self.assertEqual(explanation["selected_workflow"], "paper-learning")
        self.assertIn("full PDF extraction", explanation["not_evidence_yet"])
        self.assertNotIn("review", explanation["not_evidence_yet"])
        self.assertNotIn("CI", explanation["not_evidence_yet"])

    def test_source_finder_interaction_uses_acquisition_evidence_not_coding_gates(self) -> None:
        payload = build_chat_interaction_payload("trouve le dépôt GitHub et le PDF public", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "prepare_source_finder_plan")
        self.assertEqual(payload["chat_response"]["kind"], "source_finder")
        self.assertIn("source-finder plan", payload["chat_response"]["body"])
        self.assertNotIn("CI", payload["chat_response"]["body"])
        self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "source-finder")
        self.assertEqual(payload["chat_response"]["state"]["artifact_schema"], "source_finder_plan/v1")
        self.assertEqual(payload["chat_response"]["state"]["candidate_schema"], "source_candidate_set/v1")
        self.assertEqual(payload["chat_response"]["state"]["acquisition_status_schema"], "source_acquisition_status/v1")
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertTrue(actions["show_source_candidates"]["enabled"])
        self.assertTrue(actions["record_source_link_observed"]["enabled"])
        self.assertTrue(actions["route_to_downstream_workflow"]["enabled"])
        self.assertIn("web search", payload["chat_response"]["claim_boundary"])
        self.assertIn("download", payload["chat_response"]["state"]["evidence_not_observed"])
        explanation = payload["chat_response"]["state"]["workflow_explanation"]
        self.assertEqual(explanation["selected_workflow"], "source-finder")
        self.assertIn("web search", explanation["not_evidence_yet"])
        self.assertNotIn("review", explanation["not_evidence_yet"])
        self.assertNotIn("CI", explanation["not_evidence_yet"])

    def test_generic_catalog_question_still_uses_picker(self) -> None:
        payload = build_chat_interaction_payload("OMH 기능 뭐 있어?", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["route"]["selected_skill"], "oh-my-hermes")
        self.assertEqual(payload["chat_response"]["kind"], "skill_picker")
        self.assertEqual(payload["next_action"], "choose_skill")
        self.assertIn("skill_picker", payload["chat_response"]["state"])

    def test_specific_capability_catalog_questions_skip_generic_picker(self) -> None:
        cases = (
            ("does OMH support scheduled automation?", "automation-blueprint", "prepare_scheduled_ops_blueprint"),
            ("can OMH help with MCP setup?", "toolbelt-readiness", "prepare_toolbelt_readiness"),
            ("does OMH support memory cleanup?", "memory-curation-review", "prepare_memory_curation_review"),
            ("does OMH support voice commands?", "voice-operator", "prepare_voice_operator_card"),
            ("OMH로 GitHub issue webhook 처리 가능해?", "github-event-ops", "prepare_github_event_ops_card"),
            ("what can OMH do for research brief?", "research-brief", "run_hermes_research"),
            ("what can OMH do for GitHub event ops?", "github-event-ops", "prepare_github_event_ops_card"),
            ("what can OMH do for coding agents?", "executor-runtime-readiness", "prepare_executor_runtime_readiness"),
            ("what can OMH do for reliability review?", "reliability-review", "prepare_reliability_review"),
            ("what can OMH do for deploy and monitor?", "deploy-and-monitor", "prepare_deploy_monitor_plan"),
            ("what can OMH do for CTO loop?", "cto-loop", "run_cto_loop"),
        )

        for message, selected_workflow, next_action in cases:
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], selected_workflow)
                self.assertEqual(payload["next_action"], next_action)
                self.assertNotEqual(payload["chat_response"]["kind"], "skill_picker")
                actions = payload["chat_response"]["actions"]
                action_ids = [str(action["id"]) for action in actions]
                self.assertEqual(action_ids[0], next_action)
                self.assertIn("show_status" if selected_workflow != "memory-curation-review" else "show_memory_status", action_ids)
                self.assertEqual(actions[0]["style"], "primary")
                self.assertEqual(
                    payload["chat_response"]["state"]["workflow_explanation"]["selected_workflow"],
                    selected_workflow,
                )

    def test_complex_operator_patterns_route_to_dedicated_surfaces(self) -> None:
        cases = (
            (
                "Codex랑 Claude Code 중 어떤 런타임으로 넘겨야 해?",
                "executor-runtime-readiness",
                "prepare_executor_runtime_readiness",
                "executor_runtime_readiness",
            ),
            (
                "음성으로 짧게 말한 요청을 안전하게 정리해줘",
                "voice-operator",
                "prepare_voice_operator_card",
                "voice_operator",
            ),
            (
                "GitHub PR이 열리면 리뷰하고 CI 실패 원인을 정리해줘",
                "github-event-ops",
                "prepare_github_event_ops_card",
                "github_event_ops",
            ),
            (
                "우리 팀 Hermes agent 여러 명으로 작업 보드 관리하고 싶어",
                "agent-board",
                "prepare_agent_board_card",
                "agent_board",
            ),
            (
                "GitHub issue 들어온 걸 PR 만들 수 있게 정리해줘",
                "github-event-ops",
                "prepare_github_event_ops_card",
                "github_event_ops",
            ),
            (
                "Hermes가 기억하고 있는 프로젝트 맥락이 오래된 것 같아 정리해줘",
                "memory-curation-review",
                "prepare_memory_curation_review",
                "memory_curation",
            ),
            (
                "첨부한 엑셀을 월간 보고서 PDF랑 PPT로 만들 수 있게 정리해줘",
                "materials-package",
                "prepare_material_package",
                "materials_package",
            ),
            (
                "Codex 작업이 어디까지 진행됐는지 알려줘",
                "ultraprocess",
                "show_coding_handoff_status",
                "handoff",
            ),
            (
                "Claude Code로 넘길지 Codex로 넘길지 정해줘",
                "executor-runtime-readiness",
                "prepare_executor_runtime_readiness",
                "executor_runtime_readiness",
            ),
            (
                "우리 팀 Hermes agent 여러 명이 같이 일할 때 역할과 보드를 잡아줘",
                "agent-board",
                "prepare_agent_board_card",
                "agent_board",
            ),
            (
                "릴리즈 전에 README 주장과 실제 기능이 맞는지 검토해줘",
                "code-review",
                "prepare_review_or_followup_handoff",
                "review_check",
            ),
        )

        for message, selected_workflow, next_action, response_kind in cases:
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], selected_workflow)
                self.assertEqual(payload["next_action"], next_action)
                self.assertEqual(payload["chat_response"]["kind"], response_kind)
                self.assertIn(selected_workflow, payload["chat_response"]["headline"])
                self.assertEqual(
                    payload["chat_response"]["state"]["workflow_explanation"]["selected_workflow"],
                    selected_workflow,
                )
                self.assertIn(
                    "workflow_context_card",
                    payload["chat_response"]["state"]["workflow_explanation"],
                )

    def test_ack_workflow_chat_copy_stays_human_friendly(self) -> None:
        cases = (
            (
                "매일 아침 릴리즈 위험을 확인하고 변화가 있으면 슬랙에 알려줘",
                "automation-blueprint",
                "prepare_scheduled_ops_blueprint",
                "recurring workflow",
                "automation_blueprint",
            ),
            (
                "내 경쟁사 시장 뉴스를 매일 수집하고 분석해서 브리핑해줘",
                "research-department",
                "prepare_research_department_plan",
                "Scout, Analyst, and Briefer",
                "research_department",
            ),
            (
                "이 회의록을 PPT와 PDF로 정리해줘",
                "materials-package",
                "prepare_material_package",
                "material package",
                "materials_package",
            ),
            (
                "이 보고서를 파일로 만들어서 첨부할 수 있게 준비해줘",
                "deliverable-package",
                "prepare_deliverable_package",
                "deliverable path",
                "deliverable_package",
            ),
            (
                "can OMH help with MCP setup?",
                "toolbelt-readiness",
                "prepare_toolbelt_readiness",
                "MCP servers, CLIs, APIs",
                "toolbelt_readiness",
            ),
            (
                "does OMH support memory cleanup?",
                "memory-curation-review",
                "prepare_memory_curation_review",
                "approve/reject/update",
                "memory_curation",
            ),
            (
                "does OMH support voice commands?",
                "voice-operator",
                "prepare_voice_operator_card",
                "voice or mobile-style request",
                "voice_operator",
            ),
            (
                "OMH로 GitHub issue webhook 처리 가능해?",
                "github-event-ops",
                "prepare_github_event_ops_card",
                "triage labels",
                "github_event_ops",
            ),
            (
                "we need a competitor market scan and strategy memo for next week's leadership meeting",
                "strategy-brief",
                "prepare_strategy_brief",
                "decision frame",
                "strategy_brief",
            ),
            (
                "AI가 했다고 했는데 실제로 뭐 했는지 모르겠다",
                "code-review",
                "prepare_review_or_followup_handoff",
                "claims to inspect",
                "review_check",
            ),
            (
                "route Discord Slack Telegram threads with delivery policy",
                "gateway-intent-card",
                "prepare_gateway_intent_card",
                "gateway intent",
                "gateway_intent",
            ),
            (
                "show token cost latency run history for this automation loop",
                "ops-observability-card",
                "prepare_ops_observability_card",
                "observability card",
                "ops_observability",
            ),
            (
                "turn this sprint retro into a report package with decisions and actions",
                "report-package",
                "prepare_report_package",
                "source inputs",
                "report_package",
            ),
        )

        for message, selected_workflow, next_action, body_marker, response_kind in cases:
            with self.subTest(message=message):
                payload = build_chat_interaction_payload(message, source="discord")

                self.assertEqual(payload["mode"], "route")
                self.assertEqual(payload["route"]["selected_skill"], selected_workflow)
                self.assertEqual(payload["next_action"], next_action)
                self.assertEqual(payload["chat_response"]["kind"], response_kind)
                self.assertIn(body_marker, payload["chat_response"]["body"])
                action_ids = [str(action["id"]) for action in payload["chat_response"]["actions"]]
                self.assertEqual(action_ids[0], next_action)
                self.assertIn("workflow_context_id", payload["chat_response"]["usage_trace"])
                self.assertNotIn("/v1", payload["chat_response"]["body"])
                self.assertNotIn("schema", payload["chat_response"]["body"].lower())
                self.assertNotIn("artifact", payload["chat_response"]["body"].lower())

    def test_recommendation_policy_next_actions_are_visible_ack_actions(self) -> None:
        from omh.routing import recommend
        from omh.wrapper import contract

        policies = {
            **recommend._SKILL_POLICIES,
            **recommend._CATEGORY_POLICIES,
            **recommend._HERMES_ROLE_POLICIES,
        }
        control_actions = {
            "answer_clarification",
            "ask_clarification",
            "cancel",
            "clarify_or_route",
            "dispatch_to_workflow",
            "show_workflow_guidance",
        }

        missing: list[str] = []
        for name, policy in sorted(policies.items()):
            next_action = policy.next_action
            if not next_action or next_action in control_actions:
                continue
            if next_action not in contract.VISIBLE_ACTIONS:
                missing.append(f"{name}:{next_action}:not-visible")
            if next_action not in contract._ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION:
                missing.append(f"{name}:{next_action}:no-ack-primary")

        self.assertEqual(missing, [])

    def test_cancel_routes_to_control_action_without_plan_ui(self) -> None:
        payload = build_chat_interaction_payload("cancel", source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "cancel")
        self.assertEqual(payload["chat_response"]["kind"], "cancellation")
        self.assertNotIn("plan", payload)
        actions = {action["id"] for action in payload["chat_response"]["actions"]}
        self.assertIn("cancel", actions)
        self.assertNotIn("accept_plan", actions)

    def test_plan_mode_disables_prepare_handoff_before_acceptance(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", source="discord")

        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertEqual(payload["chat_response"]["kind"], "plan")
        self.assertTrue(actions["accept_plan"]["enabled"])
        self.assertFalse(actions["prepare_handoff"]["enabled"])

    def test_status_copy_does_not_overclaim_missing_verification(self) -> None:
        response = build_chat_response_from_status(
            {
                "run_id": "run-1",
                "next_action": "record_verification_evidence",
                "execution": {"observed": True, "status": "completed"},
                "verification": {"observed": False},
                "review": {"required": False},
            }
        )

        text = json.dumps(response).lower()
        self.assertEqual(response["kind"], "status")
        self.assertIn("verification evidence", text)
        self.assertNotIn("this has been merged", text)
        self.assertNotIn("done", text)
        self.assertEqual(response["status_card"]["schema_version"], "status_card/v1")
        self.assertEqual(response["status_card"]["steps"][2]["id"], "verification")
        self.assertEqual(response["status_card"]["steps"][2]["state"], "pending")

    def test_status_copy_names_dispatched_coding_agent(self) -> None:
        response = build_chat_response_from_status(
            {
                "run_id": "run-1",
                "next_action": "wait_for_executor_evidence",
                "prepared": {"executor_target": "codex"},
                "execution": {"observed": False},
                "verification": {"observed": False},
                "review": {"required": False},
            }
        )

        self.assertEqual(response["plain_headline"], "The coding handoff (Codex) was dispatched.")
        self.assertEqual(response["status_card"]["headline"], "The coding handoff (Codex) was dispatched.")
        self.assertIn("waiting for Codex executor evidence", response["body"])

    def test_status_card_exposes_platform_neutral_progress_steps(self) -> None:
        card = build_status_card_from_status(
            {
                "run_id": "run-1",
                "next_action": "record_ci_evidence",
                "prepared": {"handoff_available": True},
                "execution": {"observed": True, "status": "completed"},
                "verification": {"observed": True, "status": "completed"},
                "review": {"required": True, "status": "passed"},
                "ci": {"status": "not_observed"},
                "merge_readiness": {"status": "not_observed"},
                "merge": {"status": "not_observed"},
            }
        )

        steps = {step["id"]: step["state"] for step in card["steps"]}
        self.assertEqual(card["schema_version"], "status_card/v1")
        self.assertEqual(card["severity"], "attention")
        self.assertEqual(card["primary_action"], "show_status")
        self.assertEqual(steps["handoff"], "complete")
        self.assertEqual(steps["execution"], "complete")
        self.assertEqual(steps["verification"], "complete")
        self.assertEqual(steps["review"], "complete")
        self.assertEqual(steps["ci"], "pending")
        self.assertEqual(steps["merge_ready"], "pending")

    def test_status_card_preserves_generic_event_progress_without_raw_payloads(self) -> None:
        raw_log = "workflow transcript " + ("W" * 5000)
        card = build_status_card_from_status(
            {
                "run_id": "research-goal-1",
                "next_action": "show_status",
                "safe_summary": "Research workflow is waiting on source evidence.",
                "progress_events": [
                    {
                        "event_type": "blocker_encountered",
                        "summary": "Blocker encountered: source evidence is missing.\n```log\n" + raw_log + "\n```",
                        "status": "blocked",
                        "severity": "blocked",
                        "file_refs": ["docs/DIRECTION.md", "x" * 1000],
                        "artifact_refs": [
                            {
                                "schema_version": CONTEXT_ARTIFACT_REF_SCHEMA_VERSION,
                                "source": "workflow-transcript.log",
                                "raw_content": raw_log,
                                "raw_content_included": True,
                                "byte_count": len(raw_log.encode("utf-8")),
                            }
                        ],
                    }
                ],
            }
        )

        rendered = json.dumps(card)
        event = card["latest_progress_event"]
        self.assertEqual(event["schema_version"], "omh_progress_event/v1")
        self.assertEqual(event["event_type"], "blocker_encountered")
        self.assertEqual(event["status"], "blocked")
        self.assertEqual(event["severity"], "blocked")
        self.assertLessEqual(len(event["summary"]), 220)
        self.assertLessEqual(max(len(ref) for ref in event["file_refs"]), 160)
        self.assertEqual(event["artifact_refs"][0]["schema_version"], CONTEXT_ARTIFACT_REF_SCHEMA_VERSION)
        self.assertFalse(event["artifact_refs"][0]["raw_content_included"])
        self.assertNotIn("W" * 1000, rendered)
        self.assertNotIn("```", rendered)
        self.assertIn("not execution", event["claim_boundary"])

    def test_status_card_preserves_harness_ladder_progress(self) -> None:
        card = build_status_card_from_status(
            {
                "run_id": "run-1",
                "next_action": "dispatch_to_executor",
                "prepared": {"handoff_available": True},
                "harness_progress": {
                    "schema_version": "harness_progress/v1",
                    "harness": "coding-handling",
                    "quality_tier": "handoff-gated",
                    "steps": [
                        {"id": "coding_delegation_prepared", "state": "complete"},
                        {"id": "executor_dispatch_observed", "state": "pending"},
                    ],
                    "completed": 1,
                    "total": 2,
                    "complete": False,
                    "next_step": "executor_dispatch_observed",
                },
            }
        )

        self.assertEqual(card["harness_progress"]["schema_version"], "harness_progress/v1")
        self.assertEqual(card["harness_progress"]["next_step"], "executor_dispatch_observed")


if __name__ == "__main__":
    unittest.main()
