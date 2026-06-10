from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import build_coding_delegation_payload
from omh.hermes_planning import build_hermes_plan_payload
from omh.skills.render import workflow_reference_payload


class WrapperGoldenExampleTests(unittest.TestCase):
    def test_status_ladder_golden_examples_cover_required_scenarios(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "wrapper_golden_examples/v1")
        scenarios = {item["scenario"]: item for item in payload["scenarios"]}

        required = {
            "clarify_needed",
            "plan_presented",
            "deep_interview_blocked_plan",
            "handoff_prepared",
            "dispatched_executor_not_observed",
            "review_pending",
            "status_card_review_pending",
            "ci_pending",
            "ci_failed",
            "merge_ready",
            "merged",
            "contradictory_merge_ready_without_ci",
        }
        self.assertEqual(set(scenarios), required)

        for item in payload["scenarios"]:
            response = item["expected_response"]
            self.assertEqual(response["schema_version"], "chat_response/v1")
            self.assertIn(item["source"], {"discord", "slack"})
            self.assertTrue(item["claim_boundary"])
            self.assertTrue(item["observed_evidence"])
            self.assertTrue(item["not_evidence"])
            self.assertTrue(response["headline"])
            self.assertTrue(response["body"])
            self.assertIsInstance(response["action_ids"], list)
            self.assertNotIn("omh ", json.dumps(item).lower())
            self.assertNotIn("token", json.dumps(item).lower())
            if "expected_status_card" in item:
                card = item["expected_status_card"]
                self.assertEqual(card["schema_version"], "status_card/v1")
                self.assertIsInstance(card["steps"], list)
                self.assertTrue(all({"id", "state"} <= set(step) for step in card["steps"]))
            if "expected_deep_interview" in item:
                interview = item["expected_deep_interview"]
                self.assertEqual(interview["schema_version"], "deep_interview_contract/v1")
                self.assertTrue(interview["required"])
                self.assertEqual(interview["question_style"], "one_question")

    def test_discord_and_slack_examples_share_platform_neutral_action_ids(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        action_ids = {action_id for item in payload["scenarios"] for action_id in item["expected_response"]["action_ids"]}

        self.assertLessEqual(
            action_ids,
            {
                "answer:clarify",
                "accept_plan",
                "revise_plan",
                "choose_executor",
                "show_prompt_handoff",
                "copy_prompt_handoff",
                "send_to_executor",
                "send_to_codex",
                "show_status",
                "cancel",
            },
        )
        self.assertIn("show_status", action_ids)

    def test_contradictory_fixture_names_upstream_blocker(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        item = next(item for item in payload["scenarios"] if item["scenario"] == "contradictory_merge_ready_without_ci")

        self.assertIn("CI evidence is still missing", item["expected_response"]["headline"])
        self.assertIn("cannot override", item["expected_response"]["body"])
        self.assertIn("upstream CI blocker", item["claim_boundary"])

    def test_status_card_fixture_keeps_review_pending_visible(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        item = next(item for item in payload["scenarios"] if item["scenario"] == "status_card_review_pending")
        steps = {step["id"]: step["state"] for step in item["expected_status_card"]["steps"]}

        self.assertEqual(item["expected_status_card"]["severity"], "attention")
        self.assertEqual(steps["execution"], "complete")
        self.assertEqual(steps["verification"], "complete")
        self.assertEqual(steps["review"], "pending")
        self.assertEqual(steps["merge_ready"], "pending")

    def test_deep_interview_fixture_is_one_question_before_plan(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        item = next(item for item in payload["scenarios"] if item["scenario"] == "deep_interview_blocked_plan")
        interview = item["expected_deep_interview"]

        self.assertEqual(item["expected_response"]["kind"], "clarification")
        self.assertEqual(interview["question_style"], "one_question")
        self.assertIn("target outcome", interview["missing_decisions"])
        self.assertEqual(interview["after_answer_next_action"], "rerun_hermes_plan")

    def test_harness_quality_examples_cover_wrapper_visible_quality_gates(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/harness-quality.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "harness_quality_examples/v1")
        examples = {item["scenario"]: item for item in payload["examples"]}

        self.assertEqual(
            set(examples),
            {"coding_handoff_quality", "planning_quality", "research_quality", "clarification_quality"},
        )
        self.assertEqual(examples["coding_handoff_quality"]["expected_quality"]["schema_version"], "harness_quality/v1")
        self.assertIn("send_to_executor", examples["coding_handoff_quality"]["expected_quality"]["wrapper_actions"])
        self.assertIn("executor_result_observed", examples["coding_handoff_quality"]["expected_quality"]["evidence_ladder"])
        self.assertIn("accept_plan", examples["planning_quality"]["expected_quality"]["wrapper_actions"])
        self.assertIn("primary_sources_checked", examples["research_quality"]["expected_quality"]["evidence_ladder"])
        self.assertIn("answer:clarify", examples["clarification_quality"]["expected_quality"]["wrapper_actions"])

        for item in payload["examples"]:
            serialized = json.dumps(item).lower()
            self.assertTrue(item["user_visible_upgrade"])
            self.assertTrue(item["claim_boundary"])
            self.assertNotIn("token", serialized)
            self.assertNotIn("omh ", serialized)

    def test_harness_quality_golden_examples_match_live_contract_sources(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/harness-quality.json").read_text(encoding="utf-8"))

        for item in payload["examples"]:
            with self.subTest(item["scenario"]):
                source_quality = self._source_harness_quality(item)
                for key, value in item["expected_quality"].items():
                    self.assertEqual(source_quality[key], value)

    def test_hermes_agent_integration_examples_match_status_ladder(self) -> None:
        payload = json.loads(Path("examples/wrapper-golden/hermes-agent-integration.json").read_text(encoding="utf-8"))
        ladder = json.loads(Path("examples/wrapper-golden/status-ladder.json").read_text(encoding="utf-8"))
        ladder_scenarios = {item["scenario"]: item for item in ladder["scenarios"]}

        self.assertEqual(payload["schema_version"], "hermes_agent_integration_examples/v1")
        self.assertTrue(Path(payload["runbook"]).exists())
        self.assertIn("chat rendering", payload["hermes_surface_contract"]["hermes_surface_owns"])
        self.assertIn("Hermes core patching", payload["hermes_surface_contract"]["non_goals"])
        self.assertIn("hidden executor launch", payload["hermes_surface_contract"]["non_goals"])

        contracts = {item["schema_version"]: item for item in payload["consumed_contracts"]}
        self.assertEqual(
            set(contracts),
            {"chat_interaction/v1", "chat_response/v1", "coding_executor_handoff/v1", "status_card/v1"},
        )
        self.assertIn("chat_interaction/v1", contracts)
        self.assertIn("status_card/v1", contracts)
        self.assertIn("coding_executor_handoff/v1", contracts)
        self.assertIn("chat_response", contracts["chat_interaction/v1"]["required_fields"])
        self.assertIn("claim_boundary", contracts["status_card/v1"]["required_fields"])
        live_handoff = build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex")[
            "executor_handoff"
        ]
        for field in contracts["coding_executor_handoff/v1"]["required_fields"]:
            self.assertIn(field, live_handoff)
        self.assertEqual(live_handoff["codex_skill"], "$ai-slop-cleaner")
        self.assertEqual(live_handoff["codex_invocation"]["syntax"], "$skill")
        self.assertIn("{message}", live_handoff["codex_invocation"]["dispatch_text_template"])
        self.assertNotIn("recommended_workflow", contracts["coding_executor_handoff/v1"]["required_fields"])
        self.assertNotIn("verification_expectations", contracts["coding_executor_handoff/v1"]["required_fields"])

        transitions = payload["state_transitions"]
        source_scenarios = {item["source_scenario"] for item in transitions}
        self.assertEqual(len(transitions), len(ladder_scenarios))
        self.assertEqual(source_scenarios, set(ladder_scenarios))
        self.assertIn("clarifying", {item["to_state"] for item in transitions})
        self.assertIn("awaiting_review", {item["to_state"] for item in transitions})
        self.assertIn("awaiting_ci", {item["to_state"] for item in transitions})
        self.assertIn("blocked", {item["to_state"] for item in transitions})
        self.assertIn("merge_ready", {item["to_state"] for item in transitions})
        self.assertIn("merged", {item["to_state"] for item in transitions})

        for item in transitions:
            with self.subTest(item["scenario"]):
                source = ladder_scenarios[item["source_scenario"]]
                self.assertEqual(item["claim_boundary"], source["claim_boundary"])
                self.assertEqual(item["observed_evidence"], source["observed_evidence"])
                self.assertEqual(item["not_evidence"], source["not_evidence"])
                self.assertIn(item["wrapper_action"], source["expected_response"]["action_ids"])
                self.assertNotIn("token", json.dumps(item).lower())

    def test_hermes_surface_shims_render_fixture_events(self) -> None:
        cases = (
            (
                "examples/discord-adapter-shim.py",
                "examples/wrapper-events/discord-safe-feature.json",
                "discord",
                "I want to safely add a feature to this repo",
            ),
            (
                "examples/slack-adapter-shim.py",
                "examples/wrapper-events/slack-risky-refactor.json",
                "slack",
                "risky refactor with review",
            ),
        )

        for script, fixture, source, raw_message in cases:
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, script, fixture],
                    cwd=Path.cwd(),
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertEqual(result.stderr, "")
                self.assertEqual(result.returncode, 0)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["schema_version"], "wrapper_adapter_shim/v1")
                self.assertEqual(payload["source"], source)
                self.assertEqual(payload["redaction_policy"], "metadata_only")
                self.assertEqual(payload["response"]["kind"], "plan")
                self.assertTrue(payload["response"]["headline"])
                self.assertIn("not execution evidence", payload["response"]["claim_boundary"])
                self.assertIn("accept_plan", {action["id"] for action in payload["actions"]})
                self.assertIn("executor_result", payload["not_evidence_until_observed"])
                self.assertNotIn(raw_message, result.stdout)

    def _source_harness_quality(self, item: dict[str, object]) -> dict[str, object]:
        source = item["source_payload"]
        if source == "coding_delegation/v1.harness_quality":
            payload = build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex")
            return payload["harness_quality"]
        if source == "hermes_plan/v1.wrapper_contract.harness_quality":
            payload = build_hermes_plan_payload("implementation plan with review", source="discord")
            return payload["wrapper_contract"]["harness_quality"]
        if source == "workflow_catalog/v1.harnesses[].harness_quality":
            workflow_catalog = workflow_reference_payload()
            catalog_harnesses = {harness["name"]: harness["harness_quality"] for harness in workflow_catalog["harnesses"]}
            return catalog_harnesses[item["harness"]]
        self.fail(f"unsupported golden source payload: {source}")


if __name__ == "__main__":
    unittest.main()
