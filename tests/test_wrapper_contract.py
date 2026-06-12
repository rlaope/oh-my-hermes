from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.wrapper_contract import build_chat_interaction_payload, build_chat_response_from_status, build_status_card_from_status


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
        self.assertEqual(payload["next_action"], "send_to_executor")
        self.assertEqual(payload["delegation"]["executor_handoff"]["schema_version"], "coding_executor_handoff/v1")
        self.assertEqual(payload["delegation"]["executor_handoff"]["send_action"], "send_to_executor")
        self.assertTrue(payload["delegation"]["executor_handoff"]["codex_skill"].startswith("$"))
        self.assertIn("send_to_executor", actions)
        self.assertIn("send_to_codex", actions)

    def test_delegate_mode_defaults_to_executor_choice(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", mode="delegate", source="discord")

        actions = {action["id"] for action in payload["chat_response"]["actions"] if action["enabled"]}
        self.assertEqual(payload["next_action"], "choose_executor")
        self.assertEqual(payload["delegation"]["executor_selection"]["status"], "executor_choice_required")
        self.assertTrue(payload["delegation"]["executor_selection"]["choice_required"])
        self.assertNotIn("executor_handoff", payload["delegation"])
        self.assertIn("choose_executor", actions)

    def test_delegate_mode_can_prepare_prompt_only_handoff(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", mode="delegate", source="discord", executor_target="claude-code")

        actions = {action["id"] for action in payload["chat_response"]["actions"] if action["enabled"]}
        self.assertEqual(payload["next_action"], "show_prompt_handoff")
        self.assertEqual(payload["delegation"]["work_owner_mode"], "prompt_only_handoff")
        self.assertFalse(payload["delegation"]["dispatchable"])
        self.assertEqual(payload["delegation"]["prompt_handoff"]["schema_version"], "coding_prompt_handoff/v1")
        self.assertNotIn("executor_handoff", payload["delegation"])
        self.assertIn("show_prompt_handoff", actions)
        self.assertIn("copy_prompt_handoff", actions)

    def test_delegate_mode_can_prepare_runtime_handoff(self) -> None:
        payload = build_chat_interaction_payload("risky refactor", mode="delegate", source="discord", executor_target="omx-runtime")

        actions = {action["id"] for action in payload["chat_response"]["actions"]}
        runtime = payload["delegation"]["runtime_handoff"]
        self.assertEqual(payload["next_action"], "show_runtime_handoff")
        self.assertEqual(payload["delegation"]["work_owner_mode"], "runtime_handoff")
        self.assertFalse(payload["delegation"]["dispatchable"])
        self.assertEqual(runtime["schema_version"], "coding_runtime_handoff/v1")
        self.assertEqual(runtime["runtime_profile"]["runtime_family"], "omx")
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

    def test_route_mode_surfaces_recommendation_policy_actions(self) -> None:
        payload = build_chat_interaction_payload(
            "prepare weekly ops review from customer feedback and release risks",
            source="discord",
        )

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "prepare_ops_review")
        self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "ops-review")
        self.assertEqual(payload["chat_response"]["state"]["policy_next_action"], "prepare_ops_review")
        self.assertIn("observed status", payload["chat_response"]["body"])
        self.assertIn("not implementation", payload["chat_response"]["claim_boundary"])

    def test_loop_interaction_exposes_start_card_without_raw_goal_by_default(self) -> None:
        message = "./loop make OMH a 10k-star quality Hermes-native project"

        payload = build_chat_interaction_payload(message, source="discord")

        serialized = json.dumps(payload)
        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "start_goal_loop")
        self.assertEqual(payload["chat_response"]["kind"], "loop")
        self.assertEqual(payload["loop_start_card"]["schema_version"], "loop_start_card/v1")
        self.assertEqual(payload["loop_start_card"]["goal_summary"], "{message}")
        self.assertEqual(payload["chat_response"]["state"]["loop_start_card"]["schema_version"], "loop_start_card/v1")
        action_ids = {action["id"] for action in payload["chat_response"]["actions"]}
        self.assertIn("choose_permission_profile", action_ids)
        self.assertIn("start_loop", action_ids)
        self.assertIn("show_loop_queue", action_ids)
        self.assertNotIn("10k-star quality", serialized)

    def test_ultraprocess_interaction_exposes_process_actions(self) -> None:
        message = "research the repo, plan, implement, code-review, sync docs, and prepare a PR"

        payload = build_chat_interaction_payload(message, source="discord")

        self.assertEqual(payload["mode"], "route")
        self.assertEqual(payload["next_action"], "start_ultraprocess")
        self.assertEqual(payload["chat_response"]["kind"], "process")
        self.assertEqual(payload["chat_response"]["state"]["selected_workflow"], "ultraprocess")
        self.assertEqual(payload["chat_response"]["state"]["cycle_policy"], "single_cycle")
        self.assertFalse(payload["chat_response"]["state"]["continues_after_feedback"])
        self.assertIn("implementation_handoff", payload["chat_response"]["state"]["process_stages"])
        self.assertIn("stop_or_recommend_next_workflow", payload["chat_response"]["state"]["process_stages"])
        self.assertIn("PR creation", payload["chat_response"]["state"]["evidence_not_observed"])
        actions = {action["id"]: action for action in payload["chat_response"]["actions"]}
        self.assertTrue(actions["start_ultraprocess"]["enabled"])
        self.assertFalse(actions["prepare_handoff"]["enabled"])
        self.assertIn("not implementation", payload["chat_response"]["claim_boundary"])

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
