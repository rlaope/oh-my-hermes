"""Public contract tests for the canonical just-in-time learning workflow.

These tests assert structured catalog/card metadata, routing boundaries, and stable protocol
values rather than snapshotting generated prose.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest

from _standalone_bundle import _load_standalone_bundle_awareness
from omh.quality.chat_card_coverage import CHAT_CARD_COVERAGE_CASES, build_chat_card_coverage_demo
from omh.quality.native_skill_competition import (
    NATIVE_COMPETITION_CASES,
    build_native_skill_competition_report,
)
from omh.quality.routing_precision import ROUTING_INTERVENTION_CASES, build_routing_precision_demo
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
from omh.routing.localization import normalized_phrase, routing_tokens
from omh.routing.route_plan import public_workflow_identifier
from omh.routing.policy import (
    JIT_LEARN_CURRICULUM_EXCLUSION_PHRASES,
    jit_learn_guard_applies,
)
from omh.skills.catalog import (
    DEEP_INTERVIEW_MAX_ROUNDS,
    builtin_harnesses,
    installable_skill_definitions,
    omh_skill_display_name,
)
from omh.skills.render import builtin_skill_templates
from omh.wrapper.contract import build_chat_interaction_payload


JIT_LEARN_ROUTE_CASE_IDS = frozenset(
    {
        "jit-learn-korean-immediate-payoff",
        "jit-learn-current-blocker",
        "jit-learn-well-formed-still-confirms",
        "jit-learn-negative-workflow-learning",
        "jit-learn-negative-curriculum-design",
        "jit-learn-negative-korean-curriculum-learning-objective",
        "jit-learn-negative-paper-learning",
        "jit-learn-negative-source-finder",
        "jit-learn-negative-research",
        "jit-learn-negative-plan",
        "jit-learn-negative-incident-postmortem-rollback",
        "jit-learn-negative-postmortem-report-rollback",
    }
)
JIT_LEARN_POSITIVE_CASE_IDS = frozenset(
    {
        "jit-learn-korean-immediate-payoff",
        "jit-learn-current-blocker",
        "jit-learn-well-formed-still-confirms",
    }
)
JIT_LEARN_NEGATIVE_WORKFLOWS = {
    "jit-learn-negative-workflow-learning": "workflow-learning",
    "jit-learn-negative-curriculum-design": "curriculum-design",
    "jit-learn-negative-korean-curriculum-learning-objective": "curriculum-design",
    "jit-learn-negative-paper-learning": "paper-learning",
    "jit-learn-negative-source-finder": "source-finder",
    "jit-learn-negative-research": "web-research",
    "jit-learn-negative-plan": "plan",
    "jit-learn-negative-incident-postmortem-rollback": "reliability-review",
    "jit-learn-negative-postmortem-report-rollback": "reliability-review",
}
# Korean curriculum requests that also name a learning topic or objective. The
# noun phrases `학습 주제` and `학습 목표` are ordinary Korean for "learning
# topic" and "learning objective", so a course-design request uses them just as
# naturally as an immediate-learning request does. Only the fully specified one
# carries a deterministic incumbent; the underspecified ones must at minimum
# never reach `jit-learn`, which is what this corpus locks.
JIT_LEARN_KOREAN_CURRICULUM_NON_JIT_MESSAGES = (
    "학습 주제 커리큘럼 짜줘",
    "팀 온보딩 학습 주제로 교육과정을 설계해줘",
    "학습 목표 커리큘럼을 6주로 만들어줘",
)
# Messages that match an immediate-learning cue AND a curriculum cue at once.
# These are what make the exclusion's position load-bearing rather than
# decorative: narrowing the cues alone cannot save them, because the positive
# cue genuinely matches. Only evaluating the sibling boundary first does.
JIT_LEARN_CURRICULUM_OVER_POSITIVE_CUE_MESSAGES = (
    "What should I learn next? Design a six-week curriculum for it with weekly assessments.",
    "지금 뭘 배워야 할지 정해서 커리큘럼을 6주로 짜줘",
    "Design a six-week syllabus covering what I should learn next.",
    "지금 뭘 배워야 할지 강의계획으로 만들어줘",
)
JIT_LEARN_INCIDENT_INVESTIGATION_NON_JIT_MESSAGES = (
    "we need to study the incident report this week to decide on a rollback",
    "study the postmortem report this week before deciding whether to roll back",
    "review the incident postmortem this week to determine the rollback plan",
    "investigate the incident report this week and decide if rollback is needed",
    "learn from the incident postmortem this week before choosing the rollback path",
)
JIT_LEARN_INCIDENT_CONTEXT_POSITIVE_MESSAGES = (
    "What should I learn next to diagnose this incident before Friday?",
    "I need to study distributed tracing this week so I can diagnose the active incident.",
)
JIT_LEARN_KAFKA_WELL_FORMED_MESSAGE = (
    "I need to learn Kafka consumer-group rebalancing before Friday's incident review; I know the basics "
    "and need one book, podcast, creator, and course with links so I can diagnose our current lag spike."
)


def _jit_definition():
    return next(
        (definition for definition in installable_skill_definitions() if definition.name == "jit-learn"),
        None,
    )


def _jit_template():
    return next((template for template in builtin_skill_templates() if template.name == "jit-learn"), None)


def _jit_harness():
    return next((harness for harness in builtin_harnesses() if harness.name == "jit-learn"), None)


class JitLearnCatalogContractTests(unittest.TestCase):
    def test_canonical_definition_is_unique_and_installable(self) -> None:
        matches = [definition for definition in installable_skill_definitions() if definition.name == "jit-learn"]

        self.assertEqual(len(matches), 1, "canonical installable jit-learn definition is absent")
        self.assertEqual(omh_skill_display_name(matches[0].name), "omh-jit-learn")

    def test_catalog_metadata_names_readiness_inputs_and_source_gating(self) -> None:
        definition = _jit_definition()
        self.assertIsNotNone(definition, "jit-learn catalog metadata is absent")
        if definition is None:
            return

        self.assertEqual(definition.phase, "learning-target")
        self.assertEqual(definition.quality_tier, "source-gated")
        normalized_inputs = " ".join(value.casefold().replace("_", " ") for value in definition.required_inputs)
        for required in (
            "reviewed",
            "urgency",
            "current level",
            "application window",
            "time",
            "format constraints",
        ):
            with self.subTest(required_input=required):
                self.assertIn(required, normalized_inputs)

    def test_generated_frontmatter_uses_the_public_install_name(self) -> None:
        template = _jit_template()
        self.assertIsNotNone(template, "jit-learn rendered template is absent")
        if template is None:
            return

        frontmatter = template.content.split("---", 2)[1]
        self.assertIn('\nname: "omh-jit-learn"\n', frontmatter)
        self.assertIn("\n    phase: learning-target\n", frontmatter)
        self.assertIn("\n    quality_tier: source-gated\n", frontmatter)

    def test_harness_exposes_confirmation_first_evidence_ladder(self) -> None:
        harness = _jit_harness()
        self.assertIsNotNone(harness, "jit-learn harness is absent")
        if harness is None:
            return

        required_ladder = {
            "context_reviewed",
            "confirmation_asked",
            "target_confirmed",
            "research_scoped",
            "learning_brief_prepared",
        }
        self.assertTrue(required_ladder.issubset(harness.evidence_ladder), harness.evidence_ladder)
        self.assertTrue(any(str(DEEP_INTERVIEW_MAX_ROUNDS) in stop for stop in harness.stop_conditions))


class JitLearnRenderedProtocolTests(unittest.TestCase):
    def _body(self) -> str | None:
        template = _jit_template()
        self.assertIsNotNone(template, "jit-learn custom renderer is absent")
        return None if template is None else template.content

    def test_confirmation_is_mandatory_before_research_even_when_request_is_ready(self) -> None:
        body = self._body()
        if body is None:
            return
        normalized = " ".join(body.casefold().split())

        self.assertIn("## just-in-time learning protocol", normalized)
        for token in ("always", "confirmation", "before research"):
            with self.subTest(token=token):
                self.assertIn(token, normalized)

    def test_interview_asks_one_question_at_a_time_with_the_shared_budget(self) -> None:
        body = self._body()
        if body is None:
            return
        normalized = " ".join(body.casefold().split())

        self.assertIn(str(DEEP_INTERVIEW_MAX_ROUNDS), normalized)
        self.assertIn("one question", normalized)
        self.assertIn("one question per", normalized)
        for dimension in ("urgency", "current level", "application window"):
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, normalized)

    def test_target_confirmation_and_markdown_learning_brief_are_machine_checkable(self) -> None:
        body = self._body()
        if body is None:
            return
        normalized = " ".join(body.casefold().split())

        self.assertIn("## learning brief contract", normalized)
        self.assertIn("learn x now so i can do/decide y in context z by t", normalized)
        for heading in ("books", "podcasts", "creators", "courses"):
            with self.subTest(heading=heading):
                self.assertIn(heading, normalized)
        for field in (
            "title",
            "format",
            "creator/publisher",
            "link",
            "source class",
            "time to first value",
            "why it fits",
            "first application",
            "caveats",
            "currency",
        ):
            with self.subTest(field=field):
                self.assertIn(field, normalized)
        for section_token in (
            "competing learning targets",
            "filtered-out",
            "unresolved gaps",
            "starting action",
            "empty section",
        ):
            with self.subTest(section_token=section_token):
                self.assertIn(section_token, normalized)

    def test_ranking_rejects_popularity_and_preserves_the_evidence_boundary(self) -> None:
        body = self._body()
        if body is None:
            return
        normalized = " ".join(body.casefold().split())

        for token in (
            "fit",
            "authority",
            "currency",
            "time-to-first-value",
            "direct transfer",
            "bestseller",
            "ratings",
            "followers",
            "prepared",
            "learning_brief_prepared",
        ):
            with self.subTest(token=token):
                self.assertIn(token, normalized)


class JitLearnRoutingAndCardContractTests(unittest.TestCase):
    def test_quality_corpus_contains_positives_and_all_sibling_negatives(self) -> None:
        cases = {case.id: case for case in ROUTING_INTERVENTION_CASES}

        self.assertTrue(JIT_LEARN_ROUTE_CASE_IDS.issubset(cases), JIT_LEARN_ROUTE_CASE_IDS - cases.keys())
        for case_id in JIT_LEARN_POSITIVE_CASE_IDS:
            self.assertEqual(cases[case_id].expected_workflow, "jit-learn")
        for case_id, incumbent in JIT_LEARN_NEGATIVE_WORKFLOWS.items():
            # A case the dispatch-evidence gate re-pinned to clarify names its
            # incumbent as the expected candidate instead.
            case = cases[case_id]
            owner = case.expected_candidate if case.expected_route_action == "clarify" else case.expected_workflow
            self.assertEqual(owner, incumbent)

    def test_korean_curriculum_requests_never_reach_jit_learn(self) -> None:
        """A curriculum request keeps its sibling boundary even when it names a learning topic.

        The guard's sibling exclusion has to be evaluated before its positive
        cues; ordering it after them makes it unreachable, because the same
        message matches both.
        """
        for message in (
            *JIT_LEARN_KOREAN_CURRICULUM_NON_JIT_MESSAGES,
            *JIT_LEARN_CURRICULUM_OVER_POSITIVE_CUE_MESSAGES,
        ):
            with self.subTest(message=message):
                self.assertFalse(
                    jit_learn_guard_applies(normalized_phrase(message), routing_tokens(message)),
                    "jit-learn guard claimed a curriculum request",
                )

                interaction = build_chat_interaction_payload(message, source="discord")
                route = interaction.get("route", {})
                response = interaction.get("chat_response", {})

                self.assertNotEqual(route.get("selected_skill"), "jit-learn")
                self.assertNotEqual(response.get("kind"), "jit_learn")
                self.assertNotEqual(
                    (response.get("state") or {}).get("next_action"),
                    "prepare_learning_brief",
                )

                # The route hint is a second injection surface: it feeds
                # `selected=` and `next_action=` straight into the hook text,
                # so excluding the router alone still leaks the workflow.
                hint = awareness_route_hint(message)
                self.assertNotEqual(hint.get("selected_workflow"), "jit-learn")
                hinted = [row.get("workflow") for row in hint.get("hints", [])]
                self.assertNotIn("jit-learn", hinted)
                self.assertNotIn(
                    "prepare_learning_brief",
                    [row.get("next_action") for row in hint.get("hints", [])],
                )

    def test_standalone_awareness_fallback_matches_and_applies_router_boundary(self) -> None:
        """Exercise the literal fallback without making ``omh`` importable."""
        standalone_awareness = _load_standalone_bundle_awareness()

        self.assertEqual(
            standalone_awareness._JIT_LEARN_CURRICULUM_EXCLUSION_PHRASES,
            JIT_LEARN_CURRICULUM_EXCLUSION_PHRASES,
        )
        self.assertFalse(standalone_awareness.__name__.startswith("omh."))
        for phrase in ("curriculum", "syllabus", "커리큘럼", "교육과정", "강의계획"):
            self.assertIn(phrase, standalone_awareness._JIT_LEARN_CURRICULUM_EXCLUSION_PHRASES)
        # The router helpers resolve per call, so this host must still answer
        # with its own copies now that `omh` is importable again in this
        # process: a host that had no router at load does not grow one.
        self.assertIsNone(standalone_awareness._router_policy_module())
        # The workflow-intent classifier is not one of those copies: it lives
        # in the bundle, so this host runs the router's own implementation.
        bundle_package = standalone_awareness.__name__.rpartition(".")[0]
        self.assertEqual(
            type(standalone_awareness.classify_workflow_intent("plan the billing refactor")).__module__,
            f"{bundle_package}.workflow_intent",
        )

        positive = standalone_awareness.awareness_route_hint(
            "What should I learn next to solve my current blocker?"
        )
        self.assertEqual(positive.get("selected_workflow"), "jit-learn")
        well_formed = standalone_awareness.awareness_route_hint(JIT_LEARN_KAFKA_WELL_FORMED_MESSAGE)
        self.assertEqual(well_formed.get("selected_workflow"), "jit-learn")
        self.assertNotIn(
            "ultraprocess",
            [row.get("workflow") for row in well_formed.get("hints", [])],
        )
        curriculum = standalone_awareness.awareness_route_hint(
            "What should I learn next? Design a six-week curriculum for it."
        )
        self.assertNotEqual(curriculum.get("selected_workflow"), "jit-learn")
        self.assertNotIn(
            "jit-learn",
            [row.get("workflow") for row in curriculum.get("hints", [])],
        )

    def test_kafka_route_and_awareness_hook_align_without_reversing_priority(self) -> None:
        cases = (
            (
                JIT_LEARN_KAFKA_WELL_FORMED_MESSAGE,
                "jit-learn",
                "prepare_learning_brief",
                "prepare_learning_brief",
            ),
            (
                "Implement the accepted onboarding PRD and open a PR.",
                "ultrawork",
                "choose_executor",
                "prepare_one_cycle_delivery",
            ),
            (
                "Use Codex to implement this learning feature so I can apply it this week.",
                "ultrawork",
                "show_coding_handoff_status",
                "show_coding_handoff_status",
            ),
            (
                "review the incident postmortem this week to determine the rollback plan",
                "reliability-review",
                "prepare_reliability_review",
                "prepare_reliability_review",
            ),
        )
        for message, workflow, route_action, hint_action in cases:
            with self.subTest(workflow=workflow):
                interaction = build_chat_interaction_payload(message, source="discord")
                hint = awareness_route_hint(message)
                self.assertEqual(interaction.get("route", {}).get("selected_skill"), workflow)
                self.assertEqual(interaction.get("next_action"), route_action)
                # The hint emits the installed-skill identifier (#1249); the
                # interaction above keeps the catalog key.
                self.assertEqual(hint.get("selected_workflow"), public_workflow_identifier(workflow))
                self.assertEqual(hint.get("primary_next_action"), hint_action)

        with tempfile.TemporaryDirectory() as omh_home:
            hook = pre_llm_call(
                user_message=JIT_LEARN_KAFKA_WELL_FORMED_MESSAGE,
                is_first_turn=True,
                session_id="jit-learn-kafka-alignment",
                omh_home=omh_home,
            )
        self.assertIsNotNone(hook)
        context = str((hook or {}).get("context", ""))
        self.assertIn("selected=jit-learn", context)
        self.assertIn("next_action=prepare_learning_brief", context)
        self.assertNotIn("selected=ultraprocess", context)
        self.assertNotIn("next_action=prepare_one_cycle_delivery", context)

    def test_incident_investigation_does_not_become_jit_learning(self) -> None:
        for message in JIT_LEARN_INCIDENT_INVESTIGATION_NON_JIT_MESSAGES:
            with self.subTest(message=message):
                self.assertFalse(
                    jit_learn_guard_applies(normalized_phrase(message), routing_tokens(message))
                )
                interaction = build_chat_interaction_payload(message, source="discord")
                route = interaction.get("route", {})
                response = interaction.get("chat_response", {})
                self.assertNotEqual(route.get("selected_skill"), "jit-learn")
                self.assertNotEqual(response.get("kind"), "jit_learn")
                hint = awareness_route_hint(message)
                self.assertNotEqual(hint.get("selected_workflow"), "jit-learn")
                self.assertNotIn(
                    "jit-learn",
                    [row.get("workflow") for row in hint.get("hints", [])],
                )

    def test_incident_context_still_allows_immediate_learning(self) -> None:
        for message in JIT_LEARN_INCIDENT_CONTEXT_POSITIVE_MESSAGES:
            with self.subTest(message=message):
                self.assertTrue(
                    jit_learn_guard_applies(normalized_phrase(message), routing_tokens(message))
                )
                interaction = build_chat_interaction_payload(message, source="discord")
                self.assertEqual(interaction.get("route", {}).get("selected_skill"), "jit-learn")

    def test_positive_routes_select_jit_learn_and_negatives_keep_incumbents(self) -> None:
        payload = build_routing_precision_demo(source="discord")
        observed = {row["id"]: row for row in payload["intervention_cases"]}

        for case_id in JIT_LEARN_POSITIVE_CASE_IDS:
            with self.subTest(case_id=case_id):
                self.assertEqual(observed[case_id]["observed"]["route_workflow"], "jit-learn")
                self.assertEqual(observed[case_id]["observed"]["next_action"], "prepare_learning_brief")
                self.assertEqual(observed[case_id]["observed"]["response_kind"], "jit_learn")
        for case_id, incumbent in JIT_LEARN_NEGATIVE_WORKFLOWS.items():
            with self.subTest(case_id=case_id):
                row = observed[case_id]
                # A gate-made clarify keeps the incumbent as its candidate.
                owner = (
                    row["expected"]["candidate"]
                    if row["observed"]["route_action"] == "clarify"
                    else row["observed"]["route_workflow"]
                )
                self.assertEqual(owner, incumbent)
                self.assertTrue(row["passed"], row["issues"])

    def test_chat_card_names_skill_kind_phase_next_action_and_visible_actions(self) -> None:
        case = next((case for case in CHAT_CARD_COVERAGE_CASES if case.id == "jit-learn"), None)
        self.assertIsNotNone(case, "jit-learn chat-card coverage case is absent")
        if case is None:
            return
        self.assertEqual(case.expected_phase, "learning_target_confirmation")

        payload = build_chat_card_coverage_demo(source="discord")
        row = next(item for item in payload["cases"] if item["id"] == "jit-learn")
        self.assertTrue(row["passed"], row["issues"])
        self.assertEqual(row["observed"]["workflow"], "jit-learn")
        self.assertEqual(row["observed"]["kind"], "jit_learn")
        self.assertEqual(row["observed"]["phase"], "learning_target_confirmation")
        self.assertEqual(row["observed"]["next_action"], "prepare_learning_brief")
        self.assertGreaterEqual(row["observed"]["action_count"], 1)
        self.assertGreaterEqual(row["observed"]["primary_action_count"], 1)

    def test_native_recommendations_need_the_omh_policy_overlay(self) -> None:
        case = next((case for case in NATIVE_COMPETITION_CASES if case.case_id == "jit-learn-policy-overlay"), None)
        self.assertIsNotNone(case, "jit-learn native-competition case is absent")
        if case is None:
            return
        self.assertEqual(case.expected_winner, "omh")

        report = build_native_skill_competition_report()
        row = next(item for item in report["results"] if item["case_id"] == case.case_id)
        self.assertTrue(row["passed"], row)
        self.assertEqual(row["actual_winner"], "omh")


class RouterGuardImportOrderTests(unittest.TestCase):
    """The hint hook reaches the router's guards whichever omh module a process imports first."""

    def test_the_guards_resolve_when_routing_policy_is_imported_first(self) -> None:
        # `routing.policy` reaches awareness through `skills.render`, so a
        # module-level import of its guards ran against the half-initialised
        # module and bound None for the whole process; `/loop …` then ranked
        # workflow-learning first in every shard that imported policy before
        # awareness. Process state, so a fresh interpreter is the only probe.
        code = textwrap.dedent(
            """
            import json
            import omh.routing.policy  # the first router import of this process
            from omh.plugin_bundle.omh import awareness
            from omh.routing.localization import normalized_phrase

            # Each field is a value only the router's helper produces: the
            # bundle's jit-learn copy rejects a message that names the
            # workflow and its long-document copy knows page counts only. The
            # classifier is the one implementation the router re-exports from
            # the bundle, and with it `/loop …` ranks ulw-loop first.
            jit_message = "Current-blocker learning requests route to just-in-time learning"
            print(json.dumps({
                "jit_learn": awareness._jit_learn_route_hint_applies(jit_message, normalized_phrase(jit_message)),
                "long_document": awareness._long_document_request_signal("read this long contract end to end"),
                "classifier": type(awareness.classify_workflow_intent("plan the billing refactor")).__module__,
                "loop": awareness.awareness_route_hint("/loop fix the flaky site-two integration test")["primary_workflow"],
            }))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-P", "-c", code], capture_output=True, text=True, check=False, timeout=120
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "jit_learn": True,
                "long_document": True,
                "classifier": "omh.plugin_bundle.omh.workflow_intent",
                "loop": "ulw-loop",
            },
        )


if __name__ == "__main__":
    unittest.main()
