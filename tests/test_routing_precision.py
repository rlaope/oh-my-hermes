from __future__ import annotations

import json
import unittest

from _cli_harness import run_cli
from omh.quality.routing_precision import build_routing_precision_demo, routing_precision_errors


class RoutingPrecisionTests(unittest.TestCase):
    def test_routing_precision_demo_checks_negative_controls(self) -> None:
        payload = build_routing_precision_demo(source="discord")

        self.assertEqual(payload["schema_version"], "routing_precision/v1")
        self.assertEqual(payload["source"], "discord")
        self.assertTrue(payload["summary"]["all_passing"])
        self.assertEqual(payload["summary"]["case_count"], 55)
        self.assertEqual(payload["summary"]["passing_count"], 55)
        self.assertEqual(payload["summary"]["negative_case_count"], 55)
        self.assertEqual(payload["summary"]["negative_passing_count"], 55)
        self.assertEqual(payload["summary"]["direct_answer_count"], 52)
        self.assertEqual(payload["summary"]["file_lookup_count"], 3)
        self.assertEqual(payload["summary"]["overroute_count"], 0)
        self.assertEqual(payload["summary"]["catalog_picker_count"], 0)
        self.assertEqual(payload["summary"]["generic_ack_count"], 0)
        self.assertEqual(payload["summary"]["intervention_case_count"], 113)
        self.assertEqual(payload["summary"]["intervention_passing_count"], 113)
        self.assertEqual(payload["summary"]["missed_intervention_count"], 0)
        self.assertEqual(payload["summary"]["intervention_generic_ack_count"], 0)
        self.assertEqual(payload["summary"]["total_case_count"], 168)
        self.assertEqual(payload["summary"]["total_passing_count"], 168)
        self.assertEqual(routing_precision_errors(payload), [])
        self.assertIn("over-intervention and missed-intervention guards", payload["claim_boundary"])

        cases = {case["id"]: case for case in payload["cases"]}
        self.assertEqual(cases["repo-file-list"]["observed"]["next_action"], "answer_file_lookup")
        self.assertEqual(cases["general-python-help"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["python-virtualenv-help"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["soft-prefix-python-help"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["paragraph-summary"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["short-translation"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["short-summary"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-sentence-translation"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-paragraph-summary"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["short-thanks"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["short-ok"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["context-what-happened"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["context-what-did-i-ask"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-error-troubleshooting"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-error-slang"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-log-review"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["command-not-found-help"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["spanish-thanks"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["japanese-thanks"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["spanish-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["french-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["japanese-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["chinese-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["hindi-thanks"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["hindi-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["hindi-summary"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["hindi-translation"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["spanish-explanation"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["japanese-summary"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["spanish-translation"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["localized-command-not-found"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["python-loop-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["strategy-pattern-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["memory-leak-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["source-control-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["kubernetes-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["graphql-korean-explanation"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["kubernetes-korean-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-error-meaning"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["korean-time-question-generic-noise"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(
            cases["quoted-sentence-translation-generic-noise"]["observed"]["next_action"],
            "answer_directly",
        )
        self.assertEqual(cases["regex-write-generic-noise"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["exclamatory-thanks-direct"]["observed"]["next_action"], "answer_directly")
        for case in cases.values():
            self.assertFalse(case["observed"]["overrouted"])
            self.assertFalse(case["observed"]["catalog_picker_opened"])
            self.assertEqual(case["observed"]["route_action"], "fallback")
            self.assertEqual(case["observed"]["route_workflow"], "oh-my-hermes")

        interventions = {case["id"]: case for case in payload["intervention_cases"]}
        self.assertEqual(interventions["safe-feature-plan"]["observed"]["route_workflow"], "ralplan")
        self.assertEqual(interventions["hindi-safe-feature-plan"]["observed"]["route_workflow"], "ralplan")
        self.assertEqual(interventions["korean-omh-response-slow"]["observed"]["route_workflow"], "ops-observability-card")
        self.assertEqual(
            interventions["korean-omh-response-slow"]["observed"]["next_action"],
            "prepare_ops_observability_card",
        )
        self.assertEqual(interventions["korean-update-version-unchanged"]["observed"]["route_workflow"], "doctor")
        self.assertEqual(interventions["korean-update-health-uncertain"]["observed"]["route_workflow"], "doctor")
        self.assertEqual(interventions["korean-first-run-confusing"]["observed"]["response_kind"], "quickstart")
        self.assertEqual(
            interventions["korean-agent-cannot-see-omh-context"]["observed"]["next_action"],
            "record_missed_route",
        )
        self.assertEqual(interventions["source-acquisition"]["observed"]["route_workflow"], "source-finder")
        self.assertEqual(interventions["hindi-source-finder"]["observed"]["route_workflow"], "source-finder")
        self.assertEqual(interventions["hindi-paper-learning"]["observed"]["route_workflow"], "paper-learning")
        self.assertEqual(interventions["hindi-web-research"]["observed"]["route_workflow"], "web-research")
        self.assertEqual(interventions["hindi-issue-to-pr"]["observed"]["route_workflow"], "github-event-ops")
        self.assertEqual(interventions["korean-source-dataset-github"]["observed"]["route_workflow"], "source-finder")
        self.assertEqual(interventions["visual-summary"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(interventions["korean-meeting-vertical-image-card"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(
            interventions["korean-meeting-vertical-image-card"]["observed"]["next_action"],
            "prepare_visual_prompt_card",
        )
        self.assertEqual(interventions["korean-photo-meeting-vertical-image-card"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(
            interventions["korean-photo-meeting-vertical-image-card"]["observed"]["next_action"],
            "prepare_visual_prompt_card",
        )
        self.assertEqual(interventions["korean-pretty-meeting-image-card"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(
            interventions["korean-pretty-meeting-image-card"]["observed"]["next_action"],
            "prepare_visual_prompt_card",
        )
        self.assertEqual(interventions["korean-github-pr-reviewer-image-card"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(
            interventions["korean-github-pr-reviewer-image-card"]["observed"]["next_action"],
            "prepare_visual_prompt_card",
        )
        self.assertEqual(interventions["korean-release-announcement-card"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(
            interventions["korean-release-announcement-card"]["observed"]["next_action"],
            "prepare_visual_prompt_card",
        )
        self.assertEqual(interventions["korean-omh-loop-feature-image"]["observed"]["route_workflow"], "img-summary")
        self.assertEqual(
            interventions["korean-omh-loop-feature-image"]["observed"]["next_action"],
            "prepare_visual_prompt_card",
        )
        self.assertEqual(
            interventions["korean-image-generator-connector-readiness"]["observed"]["route_workflow"],
            "toolbelt-readiness",
        )
        self.assertEqual(
            interventions["korean-image-generator-connector-readiness"]["observed"]["next_action"],
            "prepare_toolbelt_readiness",
        )
        self.assertEqual(interventions["korean-hermes-coding-team-only"]["observed"]["route_workflow"], "team")
        self.assertEqual(
            interventions["korean-hermes-coding-team-only"]["observed"]["next_action"],
            "show_runtime_handoff",
        )
        self.assertEqual(interventions["feedback-triage"]["observed"]["route_workflow"], "feedback-triage")
        self.assertEqual(interventions["catalog-picker"]["observed"]["response_kind"], "skill_picker")
        self.assertEqual(interventions["omh-risky-refactor-context"]["observed"]["response_kind"], "context_brief")
        self.assertEqual(interventions["exact-ops-review-capability"]["observed"]["route_workflow"], "ops-review")
        self.assertEqual(interventions["exact-github-event-capability"]["observed"]["route_workflow"], "github-event-ops")
        self.assertEqual(interventions["korean-pr-open-ci-failed"]["observed"]["route_workflow"], "github-event-ops")
        self.assertEqual(interventions["exact-paper-learning-capability"]["observed"]["route_workflow"], "paper-learning")
        self.assertEqual(interventions["short-korean-paper-learning"]["observed"]["route_workflow"], "paper-learning")
        self.assertEqual(interventions["korean-agent-status-slang"]["observed"]["route_workflow"], "agent-ops-review")
        self.assertEqual(
            interventions["korean-agent-status-slang"]["observed"]["next_action"],
            "refresh_agent_ops_status",
        )
        self.assertEqual(interventions["korean-agent-status-briefing"]["observed"]["route_workflow"], "agent-ops-review")
        self.assertEqual(
            interventions["korean-agent-status-briefing"]["observed"]["next_action"],
            "refresh_agent_ops_status",
        )
        self.assertEqual(interventions["korean-agent-progress-question"]["observed"]["route_workflow"], "agent-ops-review")
        self.assertEqual(
            interventions["korean-agent-progress-question"]["observed"]["next_action"],
            "refresh_agent_ops_status",
        )
        self.assertEqual(interventions["english-agent-status-update"]["observed"]["route_workflow"], "agent-ops-review")
        self.assertEqual(
            interventions["english-agent-status-update"]["observed"]["next_action"],
            "refresh_agent_ops_status",
        )
        self.assertEqual(interventions["english-agent-current-work"]["observed"]["route_workflow"], "agent-ops-review")
        self.assertEqual(
            interventions["english-agent-current-work"]["observed"]["next_action"],
            "refresh_agent_ops_status",
        )
        for case_id in (
            "korean-agent-status-now-slang",
            "korean-agent-status-doing-compact",
            "korean-agent-status-current-work",
            "korean-agent-status-work-report",
            "english-agent-current-work-now",
            "english-agent-going-on-rn",
        ):
            with self.subTest(case_id=case_id):
                self.assertEqual(interventions[case_id]["observed"]["route_workflow"], "agent-ops-review")
                self.assertEqual(interventions[case_id]["observed"]["next_action"], "refresh_agent_ops_status")
        self.assertEqual(interventions["loopable-project"]["observed"]["route_workflow"], "loop")
        self.assertEqual(interventions["one-cycle-delivery"]["observed"]["route_workflow"], "ultraprocess")
        self.assertEqual(interventions["scheduled-research-blueprint"]["observed"]["route_workflow"], "automation-blueprint")
        self.assertEqual(interventions["korean-morning-market-research"]["observed"]["route_workflow"], "research-department")
        self.assertEqual(
            interventions["korean-morning-market-research"]["observed"]["next_action"],
            "prepare_research_department_plan",
        )
        self.assertEqual(
            interventions["korean-codex-start-current-task"]["observed"]["route_workflow"],
            "executor-runtime-readiness",
        )
        self.assertEqual(
            interventions["korean-codex-start-current-task"]["observed"]["next_action"],
            "prepare_executor_runtime_readiness",
        )
        self.assertEqual(
            interventions["claude-code-open-this-work-korean"]["observed"]["route_workflow"],
            "executor-runtime-readiness",
        )
        self.assertEqual(
            interventions["claude-code-open-this-work-korean"]["observed"]["next_action"],
            "prepare_executor_runtime_readiness",
        )
        self.assertEqual(
            interventions["hermes-direct-coding-owner-korean"]["observed"]["route_workflow"],
            "executor-runtime-readiness",
        )
        self.assertEqual(
            interventions["hermes-direct-coding-owner-korean"]["observed"]["next_action"],
            "prepare_executor_runtime_readiness",
        )
        self.assertEqual(
            interventions["korean-memory-pile-cleanup"]["observed"]["route_workflow"],
            "memory-sync",
        )
        self.assertEqual(
            interventions["korean-memory-pile-cleanup"]["observed"]["next_action"],
            "prepare_memory_sync",
        )
        self.assertEqual(
            interventions["korean-memory-stored-context"]["observed"]["route_workflow"],
            "memory-sync",
        )
        self.assertEqual(
            interventions["korean-memory-stored-context"]["observed"]["next_action"],
            "prepare_memory_sync",
        )
        self.assertEqual(
            interventions["korean-hermes-wrong-memory"]["observed"]["route_workflow"],
            "memory-sync",
        )
        self.assertEqual(
            interventions["korean-hermes-wrong-memory"]["observed"]["next_action"],
            "prepare_memory_sync",
        )
        self.assertEqual(interventions["workflow-learning"]["observed"]["route_workflow"], "workflow-learning")
        self.assertEqual(
            interventions["korean-workflow-trace-skill-improvement"]["observed"]["route_workflow"],
            "workflow-learning",
        )
        self.assertEqual(
            interventions["korean-workflow-trace-skill-improvement"]["observed"]["next_action"],
            "audit_learning_readiness",
        )
        self.assertEqual(interventions["korean-test-until-pass-coding"]["observed"]["route_workflow"], "ultraprocess")
        self.assertEqual(interventions["korean-test-until-pass-coding"]["observed"]["next_action"], "choose_executor")
        self.assertEqual(
            interventions["korean-codex-current-activity-status"]["observed"]["route_workflow"],
            "ultraprocess",
        )
        self.assertEqual(
            interventions["korean-codex-current-activity-status"]["observed"]["next_action"],
            "show_coding_handoff_status",
        )
        self.assertEqual(interventions["korean-setup-output-improvement"]["observed"]["route_workflow"], "ultraprocess")
        self.assertEqual(
            interventions["korean-setup-output-improvement"]["observed"]["next_action"],
            "answer_clarification",
        )
        self.assertEqual(interventions["korean-hud-menubar-restart"]["observed"]["route_workflow"], "agent-ops-review")
        self.assertEqual(
            interventions["korean-hud-menubar-restart"]["observed"]["next_action"],
            "show_agent_ops_review",
        )
        self.assertEqual(
            interventions["korean-menubar-monitor-reopen"]["observed"]["route_workflow"],
            "agent-ops-review",
        )
        self.assertEqual(
            interventions["korean-menubar-monitor-reopen"]["observed"]["next_action"],
            "show_agent_ops_review",
        )
        self.assertEqual(
            interventions["korean-wrong-memory-review"]["observed"]["route_workflow"],
            "memory-sync",
        )
        self.assertEqual(
            interventions["korean-wrong-memory-review"]["observed"]["next_action"],
            "prepare_memory_sync",
        )
        self.assertEqual(
            interventions["korean-stored-profile-fix"]["observed"]["route_workflow"],
            "memory-sync",
        )
        self.assertEqual(
            interventions["korean-stored-profile-fix"]["observed"]["next_action"],
            "prepare_memory_sync",
        )
        self.assertEqual(
            interventions["korean-explicit-codex-delegation-bugfix"]["observed"]["route_workflow"],
            "executor-runtime-readiness",
        )
        self.assertEqual(
            interventions["korean-explicit-codex-delegation-bugfix"]["observed"]["next_action"],
            "prepare_executor_runtime_readiness",
        )
        self.assertEqual(interventions["korean-keep-running-until-done"]["observed"]["route_workflow"], "loop")
        self.assertEqual(
            interventions["korean-keep-running-until-done"]["observed"]["next_action"],
            "ask_goal_boundary",
        )
        self.assertEqual(
            interventions["korean-idea-to-service-deploy"]["observed"]["route_workflow"],
            "idea-to-deploy",
        )
        self.assertEqual(
            interventions["korean-idea-to-service-deploy"]["observed"]["next_action"],
            "present_app_delivery_loop",
        )
        self.assertEqual(
            interventions["korean-agents-idle-status-freeform"]["observed"]["route_workflow"],
            "agent-ops-review",
        )
        self.assertEqual(
            interventions["korean-agents-idle-status-freeform"]["observed"]["next_action"],
            "refresh_agent_ops_status",
        )
        self.assertEqual(
            interventions["english-anything-still-running-status"]["observed"]["route_workflow"],
            "agent-ops-review",
        )
        self.assertEqual(
            interventions["english-anything-still-running-status"]["observed"]["next_action"],
            "refresh_agent_ops_status",
        )
        self.assertEqual(
            interventions["korean-update-broken-install-check"]["observed"]["route_workflow"],
            "doctor",
        )
        self.assertEqual(
            interventions["korean-update-broken-install-check"]["observed"]["next_action"],
            "run_local_operator_check",
        )
        for case in interventions.values():
            self.assertTrue(case["passed"])
            self.assertNotEqual(case["observed"]["response_kind"], "ack")

    def test_routing_precision_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "routing-precision", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("OMH routing precision", stdout)
        self.assertIn("55/55 negative-control cases passing", stdout)
        self.assertIn("Interventions: 113/113 expected workflow cases passing", stdout)
        self.assertIn("overroutes: 0", stdout)
        self.assertIn("catalog pickers: 0", stdout)
        self.assertIn("generic ack: 0", stdout)
        self.assertIn("missed interventions: 0", stdout)
        self.assertIn(
            "Repo file lookup stays direct: ok; "
            "route=fallback -> answering as a file or text lookup",
            stdout,
        )
        self.assertIn(
            "Korean short status slang opens agent ops review: ok; "
            "agent-ops-review -> refreshing agent operations status",
            stdout,
        )
        self.assertNotIn("(`answer_file_lookup`)", stdout)
        self.assertNotIn("(`refresh_agent_ops_status`)", stdout)

        status, stdout, stderr = run_cli(["demo", "routing-precision", "--json"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "routing_precision/v1")
        self.assertTrue(payload["summary"]["all_passing"])
        self.assertEqual(payload["summary"]["missed_intervention_count"], 0)


if __name__ == "__main__":
    unittest.main()
