from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.operator_productivity import (
    build_agent_operator_productivity_card,
    validate_agent_operator_productivity_card,
)
from omh.routing.recommend import recommend_skills
from omh.skills.catalog import harness_definition, installable_skill_names, primary_harness_for_skill


class OperatorProductivityTests(unittest.TestCase):
    def test_card_exposes_manager_quality_and_throughput_boundaries(self) -> None:
        card = build_agent_operator_productivity_card(
            "관리자 입장에서 AI agent 서치 코딩 리뷰 작업 품질과 생산량을 점검해줘",
            created_at="2026-06-18T00:00:00Z",
            card_id="20260618T000000Z-agent-ops-test",
        )

        self.assertEqual(card["schema_version"], "agent_operator_productivity/v1")
        self.assertEqual(card["kind"], "agent-ops-review")
        self.assertEqual(card["observation_status"], "prepared")
        self.assertEqual(card["projection"]["authority"], "projection_only")
        self.assertEqual(card["manager_view"]["role"], "third_party_operator")
        self.assertEqual(card["manager_view"]["focus"], "mixed")
        self.assertIn("quality", card["manager_view"]["goal"])
        lane_ids = [lane["lane"] for lane in card["workflow_quality"]["lanes"]]
        self.assertEqual(lane_ids, ["intake", "research", "coding", "review", "status"])
        self.assertIn("executor_dispatch_observed", card["status_card"]["blockers"])
        self.assertIn("verification_passed", card["not_evidence_until_observed"])
        self.assertIn("provider_cost_or_token_truth", card["status_card"]["not_observed"])
        self.assertIn("separate cheap checks", " ".join(item["lever"] for item in card["throughput_levers"]))
        self.assertEqual(validate_agent_operator_productivity_card(card), [])

    def test_card_rejects_observed_runtime_claims(self) -> None:
        card = build_agent_operator_productivity_card(
            "show coding progress quality",
            created_at="2026-06-18T00:00:00Z",
            card_id="20260618T000000Z-agent-ops-claim",
        )
        card["status_card"]["quality_state"] = "passed"

        errors = validate_agent_operator_productivity_card(card)

        self.assertIn("must not claim observed runtime or completion status", "; ".join(errors))

    def test_ops_cli_prepares_stores_lists_and_validates_agent_review_cards(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, stdout, stderr = run_cli(
                base
                + [
                    "ops",
                    "agent-review",
                    "--dry-run",
                    "--focus",
                    "coding",
                    "show manager quality and throughput for Codex coding review work",
                ]
            )

            self.assertEqual(status, 0, stderr)
            preview = json.loads(stdout)
            self.assertFalse(preview["store"]["written"])
            self.assertEqual(preview["card"]["manager_view"]["focus"], "coding")
            self.assertEqual(preview["card"]["status_card"]["next_action"], "prepare_coding_lane")
            self.assertFalse((root / ".omh" / "agent-ops").exists())

            status, stdout, stderr = run_cli(
                base
                + [
                    "ops",
                    "agent-review",
                    "--focus",
                    "review",
                    "review AI agent work quality blockers and CI gaps",
                ]
            )

            self.assertEqual(status, 0, stderr)
            created = json.loads(stdout)
            card_id = created["card"]["card_id"]
            self.assertTrue(created["store"]["written"])
            self.assertTrue((root / ".omh" / "agent-ops" / "reviews" / f"{card_id}.json").exists())

            status, stdout, stderr = run_cli(base + ["ops", "agent-review-list"])
            self.assertEqual(status, 0, stderr)
            listed = json.loads(stdout)
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["cards"][0]["card_id"], card_id)

            status, stdout, stderr = run_cli(base + ["ops", "agent-review-show", card_id])
            self.assertEqual(status, 0, stderr)
            shown = json.loads(stdout)
            self.assertEqual(shown["card"]["card_id"], card_id)

            status, stdout, stderr = run_cli(base + ["ops", "agent-review-show", "../outside"])
            self.assertNotEqual(status, 0)
            self.assertIn("letters, digits, and hyphens", stderr)

            status, stdout, stderr = run_cli(base + ["ops", "validate"])
            self.assertEqual(status, 0, stderr)
            validation = json.loads(stdout)
            self.assertTrue(validation["ok"])
            self.assertEqual(validation["agent_ops_reviews"]["card_count"], 1)

    def test_recommend_routes_manager_productivity_requests_to_agent_ops_review(self) -> None:
        recommendations = recommend_skills(
            "관리자 입장에서 AI agent 서치 코딩 리뷰 작업 품질과 생산량을 점검해줘",
            limit=3,
        )

        self.assertEqual(recommendations[0]["skill"], "agent-ops-review")
        self.assertEqual(recommendations[0]["next_action"], "prepare_agent_ops_review")
        self.assertIn("manager-facing", recommendations[0]["wrapper_guidance"])
        self.assertIn("not source retrieval", recommendations[0]["evidence_boundary"])

    def test_chat_interact_renders_manager_card_without_shell_catalog_approval(self) -> None:
        status, stdout, stderr = run_cli(
            [
                "chat",
                "interact",
                "--source",
                "discord",
                "as a manager, show AI agent research coding review quality blockers and throughput",
            ]
        )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["chat_response"]["kind"], "agent_ops_review")
        self.assertEqual(payload["next_action"], "show_agent_ops_review")
        state = payload["chat_response"]["state"]
        self.assertEqual(state["artifact_schema"], "agent_operator_productivity/v1")
        self.assertEqual(state["quality_state"], "prepared_not_observed")
        self.assertIn("executor_dispatch_observed", state["blockers"])
        self.assertIn("show_agent_ops_review", {action["id"] for action in payload["chat_response"]["actions"]})
        self.assertNotIn("omh list", json.dumps(payload))

    def test_chat_interact_renders_status_refresh_for_short_status_questions(self) -> None:
        cases = (
            ("작업상황 브리핑해줘", "지금 상황", "관리자 관점"),
            ("무슨일이노", "지금 상황", "shell 명령"),
            ("status update please", "Progress, blockers, and throughput", "quality gates"),
            ("今何してる？", "現在の状況", "workflow 状態"),
        )
        for message in cases:
            with self.subTest(message=message[0]):
                prompt, headline_marker, body_marker = message
                status, stdout, stderr = run_cli(["chat", "interact", "--source", "discord", prompt])

                self.assertEqual(status, 0, stderr)
                payload = json.loads(stdout)
                self.assertEqual(payload["route"]["selected_skill"], "agent-ops-review")
                self.assertEqual(payload["chat_response"]["kind"], "agent_ops_review")
                self.assertEqual(payload["next_action"], "refresh_agent_ops_status")
                self.assertIn(headline_marker, payload["chat_response"]["headline"])
                self.assertIn(body_marker, payload["chat_response"]["body"])

    def test_catalog_installs_agent_ops_review_and_maps_harness(self) -> None:
        self.assertIn("agent-ops-review", installable_skill_names())
        self.assertEqual(primary_harness_for_skill("agent-ops-review"), "agent-ops-review")
        harness = harness_definition("agent-ops-review")
        self.assertEqual(harness.quality_tier, "manager-review-gated")
        self.assertIn("show_agent_ops_review", harness.wrapper_actions)
