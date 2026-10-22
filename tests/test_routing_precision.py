from __future__ import annotations

from dataclasses import replace
import json
import unittest

from _cli_harness import run_cli
from omh.quality.routing_precision import build_routing_precision_demo, routing_precision_errors
from omh.routing import recommend as recommend_module
from omh.routing.localization import prepare_routing_text


class RoutingPrecisionTests(unittest.TestCase):
    def test_routing_precision_demo_checks_negative_controls(self) -> None:
        payload = build_routing_precision_demo(source="discord")

        self.assertEqual(payload["schema_version"], "routing_precision/v1")
        self.assertEqual(payload["source"], "discord")
        self.assertTrue(payload["summary"]["all_passing"])
        # The two reviewed pins for the routing corpus totals: these literals
        # and `expected=` in src/maintenance/drift.py. Every other count
        # assertion compares against this producer instead of a literal.
        # omh-docs contributes four measured negatives and five measured interventions.
        # The Indonesian trigger pack adds six negatives and eleven interventions.
        # The Vietnamese trigger pack adds eight negatives and eleven interventions.
        # dag-ulw adds twenty-one negatives and twenty-nine interventions.
        # A complaint, a question or a stop after a skill's bare name adds fifteen negatives and eight interventions.
        # Its review adds nine negatives and ten interventions.
        # market-research adds ten negatives and four interventions; its second
        # review six more negatives, its third two.
        # show-reel adds sixteen noun/reference controls, nine that
        # dispatched it under its first grammar, three asked first sentences
        # and two causatives (a relative clause, `on`) (+30).
        # Hermes' slash-skill scaffold adds four controls (+4), and a question
        # after the /dag-ulw sigil six (+6), a stop or a question after an
        # explicit invocation ten (+10), and the rule after an explicit sigil
        # five: four Japanese or Chinese stops or questions, and a status
        # request after /dag-ulw in Hermes' scaffold (+5). A stop of the
        # invoked skill's own run, a Korean stop said with why, a Chinese bare
        # stop and a question that names the skill add five (+5), and stops
        # of more run words, in Japanese and as a Korean compound, and a
        # question about using the skill four more (+4), and a question that
        # names the skill by its label one (+1). Six Korean stops followed by
        # fillers, a negation or what the person is in the middle of, a
        # question that names ultrawork by its short name and an uppercase
        # sigil's stop add eight (+8).
        # Multi-part work to dag-ulw adds three controls (+3).
        # A negated sweep, a status lookup and one PR's files add three (+3).
        # A report-only review, a past, a single command and a stop with a
        # declarative reason add four (+4).
        # A past, a summary and a condition over every PR add three (+3).
        # One PR in other words, a "does not work" fault and a push over every
        # branch add five (+5); a schedule, one PR or branch singled out and a
        # fault in other words add five more (+5); PR 3 without a counter
        # stays one scope (+1); two more schedule shapes, a count of files and a
        # count of PRs with no breadth word add four (+4); a noun with 마다, an
        # interval and PR 하나 add three (+3).
        # Three science vocabulary controls remain direct answers.
        self.assertEqual(payload["summary"]["case_count"], 1071)
        self.assertEqual(payload["summary"]["passing_count"], payload["summary"]["case_count"])
        self.assertEqual(payload["summary"]["negative_case_count"], payload["summary"]["case_count"])
        self.assertEqual(payload["summary"]["negative_passing_count"], payload["summary"]["case_count"])
        # spend-gate's lunch-budget control is a direct answer (+1), four of
        # its review controls are questions answered directly (+4), and one
        # third-review control is a report answered directly (+1), and so is
        # one fourth-review control (+1). The upstream skill audit's final
        # review adds a /blueprint seed host turn and two loops on a timer
        # that spend nothing, each answered directly (+3), and its follow-up a
        # version question about another tool, answered directly (+1).
        # Reading only the person's words on a gateway turn adds a concept
        # question behind a Discord trigger note and a thank-you under a
        # reply quoting a skill request, each answered directly (+2).
        # Korean admission for the safety gates adds two loops on a timer
        # that send a price alert and a rules document, each Hermes' /loop
        # answered directly (+2); its second review two more that subscribe
        # to an alert and reprice a price list (+2).
        # The plural-possessive masker fix adds a quoted workflow name after
        # "the users'", answered directly as a reference (+1).
        # Four questions about dag-ulw are answered directly (+4), and so are
        # eleven stop, cancel or status words for its run in progress (+11).
        # The dag-ulw routing follow-ups add two Korean cancels, one with a
        # verb ending after other words and one after a word for the run, and
        # a polite request to explain dag ulw, each answered directly (+3).
        # Their review adds six cancels (Korean polite, 부탁해, 그만 돌려,
        # a modified word for the run, a stop adverb, and "can you stop") and
        # two polite questions that weigh dag ulw, each answered directly (+8).
        # The delta review adds three cancels (취소해줘요, 정지해줘, and
        # 지금 바로 취소), each answered directly (+3).
        # The third review adds two questions about stopping dag ulw (how to
        # cancel it, whether it can be stopped), each answered directly (+2).
        # The fourth review adds whether it was cancelled, a cancel decided
        # later, the other run cancelled, and two sigils before an English
        # question, each answered directly (+5).
        # The fifth review makes a cancel request said as a noun a cancel, and
        # adds a processed cancel, a halt request sent, and a cancelled run
        # that keeps going, each answered directly (+4).
        # The sixth review adds four status checks before a past stop and a
        # cancel pressed while the run still goes, each answered directly (+5).
        # The seventh review adds two status checks of a run that stopped and
        # whether cancel was pressed, each answered directly (+3).
        # The last review patch adds 멈춤 said to dag ulw and two status checks
        # of a past stop, each answered directly (+3).
        # A complaint, a question or a stop that opens with a skill's bare
        # name is answered directly (+12). Its review adds a yes-or-no question,
        # a stop with a reason or said twice, and questions that ask for no plan
        # or about the skill itself, each answered directly (+9).
        # TAM SAM SOM explained to a five-year-old is answered directly (+1),
        # and so are two method questions from its second review (+2) and one
        # from its third (+1).
        # show-reel's quoted-translation and film-plot controls are answered
        # directly (+2).
        # Hermes' slash-skill scaffold adds a question and a status word after
        # /dag-ulw, and another skill's slash turn with and without an
        # instruction, each answered directly (+4). A Korean question, whether
        # CI passed, a question after a skill stacked on it, and a Korean
        # question in Hermes' scaffold, each after the /dag-ulw sigil, are
        # answered directly (+4). Ten stops or questions after an explicit
        # invocation are answered directly (+10), and so are a Japanese stop,
        # a Japanese and a Chinese question about the skill, and a status
        # request in Hermes' scaffold after /dag-ulw (+4). Five stops of the
        # invoked skill's own run or questions that name it are answered
        # directly (+5), and so are four more own-run stops and a question
        # about using the skill (+4), and a question that names the skill by
        # its label (+1), and so are the eight stops and questions above (+8).
        # A Korean stop then a negation is answered directly (+1).
        # A stop with a declarative reason is answered directly (+1).
        # The three science vocabulary controls also answer directly.
        self.assertEqual(payload["summary"]["direct_answer_count"], 342)
        # show-reel's README-link control is answered as a file lookup (+1).
        self.assertEqual(payload["summary"]["file_lookup_count"], 11)
        self.assertEqual(payload["summary"]["overroute_count"], 0)
        self.assertEqual(payload["summary"]["catalog_picker_count"], 0)
        self.assertEqual(payload["summary"]["generic_ack_count"], 0)
        # show-reel adds fourteen production/owner interventions, six that
        # keep a film inside another skill's request with that skill, and two
        # chained requests that keep their owner (+22).
        # Hermes' slash-skill scaffold adds /dag-ulw with a request and bare,
        # and /ulw-plan with a request, each routed as typed (+3). Four
        # requests after the /dag-ulw sigil that hold a question word or are
        # asked politely still dispatch (+4), and so do six real requests
        # or diagnosis questions after an explicit invocation (+6). The rule
        # after an explicit sigil adds six stop verbs or questions with a
        # task object that run their skill, five status requests that get
        # OMH's status card, and two status requests that run a skill whose
        # work they are (+13). Two stops of something other than the skill's
        # own run, a stop after the cancel skill, and four this/it questions
        # after a skill that explains or judges what the person points at run
        # their skill (+7). Five questions about "a skill" or a name after
        # an article, a Korean stop verb before its object, and an own-run
        # word inside a domain noun run their skill (+7), and so does a
        # question about rust after /omh-rust (+1). A Korean stop verb before
        # a task noun runs its skill, and /ulw-context status gets the status
        # card (+2), and so does /omh-cancel 상태 보여줘 (+1).
        # Multi-part work to dag-ulw adds four graph runs, a review offered and
        # not started, a check-and-close that stays, three single tasks that
        # stay, agent-ops-review's status and a stop with a loanword object (+11).
        # One fix in many places stays on ultrawork (+1).
        # Two changes on every unit run as a graph and a hold stays (+3).
        # Four request forms run as a graph and four named skills keep the
        # request (+8); three more forms run as a graph and four requests
        # stay where main sends them (+7); a count of PRs runs as a graph (+1).
        # A twice-a-day schedule and my latest pull request stay, and a sweep
        # said now runs as a graph (+3). Every deploy and every push stay, and
        # each service with 마다 runs as a graph (+3).
        # Three unnamed science requests render dedicated computation cards.
        self.assertEqual(payload["summary"]["intervention_case_count"], 1084)
        self.assertEqual(
            payload["summary"]["intervention_passing_count"], payload["summary"]["intervention_case_count"]
        )
        self.assertEqual(payload["summary"]["missed_intervention_count"], 0)
        self.assertEqual(payload["summary"]["intervention_generic_ack_count"], 0)
        self.assertEqual(
            payload["summary"]["total_case_count"],
            payload["summary"]["case_count"] + payload["summary"]["intervention_case_count"],
        )
        self.assertEqual(payload["summary"]["total_passing_count"], payload["summary"]["total_case_count"])
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
        self.assertEqual(cases["owner-default-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["dependency-graph-concept"]["observed"]["next_action"], "answer_directly")
        self.assertEqual(cases["markov-chain-models-work-concept"]["observed"]["next_action"], "answer_directly")
        for case in cases.values():
            self.assertFalse(case["observed"]["overrouted"])
            self.assertFalse(case["observed"]["catalog_picker_opened"])
            # Negative controls stay out of the way as a plain fallback.
            # `clarify` is accepted only for controls that expect the
            # clarification path (the unnamed-CLI paraphrase control), so a
            # fallback control drifting to clarify still fails here.
            if case["expected"]["next_action"] == "answer_clarification":
                self.assertIn(case["observed"]["route_action"], ("fallback", "clarify"))
            else:
                self.assertEqual(case["observed"]["route_action"], "fallback")
            self.assertEqual(case["observed"]["route_workflow"], "oh-my-hermes")

        interventions = {case["id"]: case for case in payload["intervention_cases"]}
        for case_id in (
            "context-canonical-explicit",
            "context-public-label-explicit",
            "context-fuzzy-project-language",
        ):
            with self.subTest(case_id=case_id):
                self.assertEqual(interventions[case_id]["observed"]["route_workflow"], "context")
                self.assertEqual(
                    interventions[case_id]["observed"]["next_action"],
                    "prepare_project_terms_context",
                )
        for case_id in (
            "project-glossary-definition-only",
            "project-glossary-say-instead-only",
            "project-glossary-localized-label-only",
            "project-glossary-distinct-from-only",
            "project-terms-file-lookup",
        ):
            with self.subTest(case_id=case_id):
                self.assertFalse(cases[case_id]["observed"]["overrouted"])
                self.assertNotEqual(cases[case_id]["observed"]["route_workflow"], "context")
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
        self.assertEqual(interventions["hindi-research"]["observed"]["route_workflow"], "web-research")
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
        self.assertEqual(interventions["korean-hermes-coding-team-only"]["observed"]["route_workflow"], "ultrawork")
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
        for case_id in (
            "running-work-board-natural-request",
            "running-work-board-explicit-request",
            "running-work-board-models-request",
        ):
            with self.subTest(case_id=case_id):
                self.assertEqual(interventions[case_id]["observed"]["route_workflow"], "running-work-board")
                self.assertEqual(
                    interventions[case_id]["observed"]["next_action"],
                    "show_running_work_board",
                )
        self.assertEqual(interventions["loopable-project"]["observed"]["route_workflow"], "loop")
        self.assertEqual(interventions["one-cycle-delivery"]["observed"]["route_workflow"], "ultrawork")
        # Re-pinned by the dispatch-evidence gate: `parallel`, `integrate`, and
        # `then` lead by 1, so the route asked with ultrawork as its candidate.
        # Re-pinned again with dag-ulw (2026-10-21): the score is still weak,
        # but "parallel, then integrate" is the request's own phrase for parts
        # joined afterwards, so it dispatches dag-ulw.
        self.assertTrue(interventions["dependency-topology-parallel-then-integrate"]["passed"])
        self.assertEqual(
            interventions["dependency-topology-parallel-then-integrate"]["observed"]["route_workflow"],
            "dag-ulw",
        )
        self.assertEqual(
            interventions["owner-learning-ulw-delivery"]["observed"]["next_action"],
            "choose_executor",
        )
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
        self.assertEqual(interventions["korean-test-until-pass-coding"]["observed"]["route_workflow"], "ultrawork")
        self.assertEqual(interventions["korean-test-until-pass-coding"]["observed"]["next_action"], "choose_executor")
        self.assertEqual(
            interventions["korean-codex-current-activity-status"]["observed"]["route_workflow"],
            "executor-runtime-readiness",
        )
        self.assertEqual(
            interventions["korean-codex-current-activity-status"]["observed"]["next_action"],
            "prepare_executor_runtime_readiness",
        )
        self.assertEqual(interventions["korean-setup-output-improvement"]["observed"]["route_workflow"], "ultrawork")
        self.assertEqual(
            interventions["korean-setup-output-improvement"]["observed"]["next_action"],
            "choose_executor",
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

    def test_apple_style_library_normalization_requires_exact_tokens(self) -> None:
        named = prepare_routing_text("Create an Apple-style product page with GSAP scroll motion.")
        self.assertIn("apple product visual", named.scoring_text)

        for query in (
            "Create an Apple-style product page with notgsap123 scroll motion.",
            "Create an Apple-style product page with xgsap scroll motion.",
            "Create an Apple-style product page with gsap123 scroll motion.",
        ):
            self.assertNotIn("apple product visual", prepare_routing_text(query).scoring_text)

    def test_memory_refusal_and_korean_curation_routes_stay_precise(self) -> None:
        refusal = recommend_module.recommend_skills("do not save this token", limit=1)[0]
        curation = recommend_module.recommend_skills("기억 정리", limit=1)[0]

        self.assertEqual(refusal["skill"], "memory-new")
        self.assertIn("refuse secrets", refusal["wrapper_guidance"])
        self.assertEqual(curation["skill"], "memory-sync")
        self.assertIn("Korean routes", curation["wrapper_guidance"])

    def test_running_work_board_requires_complete_english_trigger_phrases(self) -> None:
        recommendations = recommend_module.recommend_skills("explain how markov chain models work", limit=10)

        board = next(item for item in recommendations if item["skill"] == "running-work-board")
        self.assertLess(board["score"], 8)
        self.assertNotIn("trigger:models", board["matched"])
        self.assertNotIn("trigger:work", board["matched"])

    def test_routing_precision_cli_outputs_summary_and_json(self) -> None:
        status, stdout, stderr = run_cli(["demo", "routing-precision", "--summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("OMH routing precision", stdout)
        summary = build_routing_precision_demo(source="discord")["summary"]
        negatives, interventions = summary["case_count"], summary["intervention_case_count"]
        self.assertIn(f"{negatives}/{negatives} negative-control cases passing", stdout)
        self.assertIn(f"Interventions: {interventions}/{interventions} expected workflow cases passing", stdout)
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


class TrivialMessageGuardTests(unittest.TestCase):
    """A message with no routable content never reaches trigger scoring.

    Observed live on Slack, mid document-harness conversation: the user sent
    the bot a bare "?" and got an OMH catalog menu back, and "뭐" alone
    DISPATCHED agent-ops-review at score 18. Multi-word Korean triggers
    decompose into single-syllable scorer tokens, and the pre-existing
    direct-answer guard applied only at candidate_score <= 4 -- so the noise
    it exists to stop was exactly what disarmed it. The guard now runs before
    any scoring.
    """

    TRIVIAL = ("?", "??", "@mikument-harness?", "뭐", "응?", "그래서?", "네", "ok", "왜?", "뭐지?")

    def test_trivial_messages_fall_back_to_a_direct_answer(self) -> None:
        from omh.routing.chat import DIRECT_ANSWER_REASON, route_chat_message

        for message in self.TRIVIAL:
            with self.subTest(message=message):
                route = route_chat_message(message, source="slack")
                self.assertEqual(route["action"], "fallback")
                self.assertEqual(route["reason"], DIRECT_ANSWER_REASON)

    def test_a_bare_syllable_never_dispatches_a_workflow(self) -> None:
        # The exact live failure: one syllable, high-confidence dispatch.
        from omh.routing.chat import route_chat_message

        route = route_chat_message("뭐", source="slack")
        self.assertNotEqual(route["action"], "dispatch")
        self.assertNotEqual(route["selected_skill"], "agent-ops-review")

    def test_named_skills_stay_routable_as_one_word_messages(self) -> None:
        # `explicit_skill_invocation` knows every name and alias, and a named
        # skill is the one legitimate one-word message.
        from omh.routing.chat import DIRECT_ANSWER_REASON, route_chat_message

        for message, expected in (("wiki", "wiki"), ("/wiki", "wiki"), ("ask", "ask"), ("team", "ultrawork")):
            with self.subTest(message=message):
                route = route_chat_message(message, source="slack")
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], expected)
                self.assertNotEqual(route["reason"], DIRECT_ANSWER_REASON)

    def test_short_imperatives_and_real_requests_keep_routing(self) -> None:
        # An imperative does not end in a question mark; a spaced request has
        # content. Neither belongs to this guard.
        from omh.routing.chat import DIRECT_ANSWER_REASON, route_chat_message

        for message in ("리뷰해", "배포해줘", "상태 보여줘", "왜 빌드가 깨졌어", "이거 기억해둬", "omh doctor"):
            with self.subTest(message=message):
                route = route_chat_message(message, source="slack")
                self.assertNotEqual(route["reason"], DIRECT_ANSWER_REASON)

    def test_github_issue_filing_requires_context_for_generic_english(self) -> None:
        # Given: generic issue wording outside GitHub
        from omh.routing.chat import route_chat_message

        # When: landlord and payroll requests are routed
        for message in ("file an issue about my landlord", "open an issue for payroll"):
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                # Then: ordinary issue language never enters the GitHub filing lane
                self.assertNotEqual(route["selected_skill"], "github-issue-intake")

    def test_github_issue_filing_keeps_explicit_and_korean_requests(self) -> None:
        # Given: explicit workflow, filing, and Korean GitHub requests
        from omh.routing.chat import route_chat_message

        # When/Then: each identifies the bounded intake lane
        for message in (
            "github-issue-intake: setup crashes",
            "file this as an issue: setup crashes",
            "이 버그를 깃허브 이슈로 올려줘",
        ):
            with self.subTest(message=message):
                self.assertEqual(route_chat_message(message, source="discord")["selected_skill"], "github-issue-intake")

    def test_cjk_pack_phrases_reach_their_skill_one_tier_below_english(self) -> None:
        # Given: the corpus can now assert a tier, not only an action
        payload = build_routing_precision_demo(source="discord")
        interventions = {case["id"]: case for case in payload["intervention_cases"]}

        # When/Then: a pack phrase inside a ja or zh sentence keeps its skill as
        # a named candidate but reaches it at medium, where English dispatches
        # at high. This is the recorded #1607 decision, not an aspiration: the
        # cases pass today and a scoring change has to move them on purpose.
        for case_id in (
            "japanese-pack-phrase-in-sentence-clarifies",
            "chinese-pack-phrase-in-sentence-clarifies",
        ):
            with self.subTest(case_id=case_id):
                case = interventions[case_id]
                self.assertTrue(case["passed"])
                self.assertEqual(case["observed"]["route_action"], "clarify")
                self.assertEqual(case["observed"]["route_confidence"], "medium")
                self.assertEqual(case["observed"]["route_workflow"], "oh-my-hermes")
                self.assertEqual(case["expected"]["confidence"], "medium")
        english = interventions["keep-monitoring-opens-automation-blueprint"]["observed"]
        self.assertEqual(english["route_action"], "dispatch")
        self.assertEqual(english["route_confidence"], "high")
        self.assertEqual(english["route_workflow"], "automation-blueprint")

        # And: the same zh phrase crosses the tier on segmentation alone --
        # bare it dispatches, inside a question it clarifies.
        bare = interventions["chinese-bare-pack-phrase-dispatches"]["observed"]
        embedded = interventions["chinese-pack-phrase-in-question-clarifies"]["observed"]
        self.assertEqual((bare["route_action"], bare["route_confidence"]), ("dispatch", "high"))
        self.assertEqual(
            (embedded["route_action"], embedded["route_confidence"]), ("clarify", "medium")
        )
        self.assertEqual(embedded["route_workflow"], "oh-my-hermes")

        # And: the tier assertion can fail the thing it names. Without this the
        # pinned tier would be a payload field nothing checks, which is the
        # shape of guard this repository keeps finding.
        from omh.quality.routing_precision import (
            ROUTING_INTERVENTION_CASES,
            _evaluate_intervention_case,
        )

        pinned = next(
            case
            for case in ROUTING_INTERVENTION_CASES
            if case.id == "japanese-pack-phrase-in-sentence-clarifies"
        )
        mispinned = _evaluate_intervention_case(
            replace(pinned, expected_confidence="high"), source="discord"
        )
        self.assertFalse(mispinned["passed"])
        self.assertIn("expected confidence high, observed medium", mispinned["issues"])


if __name__ == "__main__":
    unittest.main()
