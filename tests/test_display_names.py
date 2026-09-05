"""Contract for the `omh-` display form in messenger-visible wrapper bodies.

PR #657 made generated skill frontmatter render `name: omh-<skill>`, so the host
status line says `Reading skill omh-ultrawork` while wrapper bodies still said
`ultrawork`. This module locks the three contexts that split apart:

1. prose a user reads -> display form (`omh-<name>`, `omh-routing` for the router)
2. invocation syntax and machine-fed identifiers -> canonical, unchanged
3. echo-back of the display form -> routes to the same workflow as the canonical form
"""

from __future__ import annotations

import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import awareness as awareness_module
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.plugin_bundle.omh.degradation import DEGRADATION_CHAT_NOTE
from omh.routing.chat import route_chat_message
from omh.routing.display_names import canonical_display_mentions
from omh.skills.catalog import historical_skill_display_names, installable_skill_definitions, omh_skill_display_name
from omh.wrapper.contract import build_chat_interaction_payload
from omh.wrapper.route_hints import build_chat_route_hint_payload


class DisplayNamesInBodiesTests(unittest.TestCase):
    """Context 1: prose a user reads carries the `omh-` display form."""

    def test_skill_picker_body_lists_capability_families_with_display_names(self) -> None:
        body = build_chat_interaction_payload("./omh", source="discord")["chat_response"]["body"]

        self.assertTrue(body.strip())
        self.assertIn("Families:", body)
        # The QA observation: this line used to read "deep-interview, ralplan".
        # Both are workflow engines, so they render the `ulw-` label while the
        # domain skills beside them keep `omh-`.
        self.assertIn("- Plan and decide: ulw-interview, ulw-context, ulw-plan, omh-codebase-onboarding", body)
        self.assertIn("omh-visual-qa", body)

        # A family card also lists capability phrases that are not installable
        # skills. Those must not collect a prefix.
        self.assertIn("omh-idea-to-deploy", body)
        self.assertNotIn("omh-dynamic-workflow", body)
        self.assertNotIn("omh-coding runtime handoff", body)

    def test_catalog_question_picker_body_uses_display_names(self) -> None:
        body = build_chat_interaction_payload("what omh workflows are available?", source="discord")["chat_response"][
            "body"
        ]

        self.assertTrue(body.strip())
        self.assertIn("Capability families:", body)
        self.assertIn("omh-source-finder", body)
        self.assertIn("omh-doctor", body)

    def test_route_hint_body_and_headline_offer_the_display_name(self) -> None:
        response = build_chat_route_hint_payload("run visual qa on the login page", source="discord")["chat_response"]

        self.assertTrue(response["body"].strip())
        self.assertEqual(response["state"]["selected_workflow"], "visual-qa")
        self.assertEqual(response["headline"], "[omh] omh-visual-qa looks relevant.")
        self.assertIn("I can open `omh-visual-qa` first", response["body"])
        self.assertIn("omh-visual-qa", response["messenger_rendering"]["body_text"])

        labels = {str(action.get("label", "")) for action in response["actions"]}
        self.assertIn("Open omh-visual-qa", labels)

    def test_plan_headline_and_workflow_explanation_copy_use_display_names(self) -> None:
        response = build_chat_interaction_payload(
            "I want to safely add a feature to this repo", source="discord"
        )["chat_response"]
        explanation = response["state"]["workflow_explanation"]

        # This request routes to `ralplan`, a workflow engine, so the copy carries
        # the `ulw-` label. The contract is that prose uses the display form, not
        # that the display form is always `omh-`.
        self.assertTrue(response["headline"].strip())
        self.assertIn("`ulw-plan", response["headline"])
        self.assertIn("ulw-plan", explanation["recommended_reply"])
        self.assertEqual(str(explanation["primary_action_label"]), "Open ulw-plan")

    def test_router_skill_renders_as_omh_routing_rather_than_the_mechanical_prefix(self) -> None:
        self.assertEqual(omh_skill_display_name("oh-my-hermes"), "omh-routing")

        body = build_chat_interaction_payload("./omh", source="discord")["chat_response"]["body"]
        self.assertNotIn("omh-oh-my-hermes", body)


class CanonicalIdentifiersStayCanonicalTests(unittest.TestCase):
    """Context 2: invocation syntax and machine-fed identifiers never shift."""

    def test_route_hint_invocation_and_state_keep_canonical_names(self) -> None:
        payload = build_chat_route_hint_payload("run visual qa on the login page", source="discord")
        response = payload["chat_response"]

        submit_texts = {str(action.get("submit_text", "")) for action in response["actions"]}
        self.assertIn("./visual-qa", submit_texts)
        self.assertNotIn("./omh-visual-qa", submit_texts)

        self.assertEqual(response["state"]["selected_workflow"], "visual-qa")
        self.assertEqual(response["state"]["route_hint"]["primary_workflow"], "visual-qa")
        self.assertEqual(payload["route_hint"]["primary_workflow"], "visual-qa")

        commands = [str(entry.get("command", "")) for entry in payload["wrapper_contract"]["next_backend_commands"]]
        self.assertTrue(any("./visual-qa <message>" in command for command in commands))
        self.assertFalse(any("omh-visual-qa" in command for command in commands))

    def test_skill_picker_options_and_state_keep_canonical_identifiers(self) -> None:
        picker = build_chat_interaction_payload("./omh", source="discord")["chat_response"]["state"]["skill_picker"]

        options = {str(option["id"]): option for option in picker["options"]}
        self.assertIn("deep-interview", options)
        self.assertEqual(options["deep-interview"]["direct_invocation"], "./deep-interview <request>")
        self.assertEqual(options["deep-interview"]["payload"]["skill"], "deep-interview")
        for option in picker["options"]:
            self.assertFalse(str(option["id"]).startswith("omh-"), option["id"])

        for family in picker["capability_families"]:
            for workflow in family["primary_workflows"]:
                self.assertFalse(str(workflow).startswith("omh-"), workflow)

    def test_catalog_definitions_and_triggers_stay_canonical(self) -> None:
        for definition in installable_skill_definitions():
            self.assertFalse(definition.name.startswith("omh-"), definition.name)
            for trigger in definition.triggers:
                self.assertFalse(str(trigger).startswith("omh-"), (definition.name, trigger))


class DisplayNameEchoBackRoutingTests(unittest.TestCase):
    """Context 3: showing a name means accepting it back as routing input."""

    ECHO_BACK_CASES = (
        "use omh-visual-qa",
        "omh-visual-qa로 해줘",
        "use omh-ultrawork",
        "omh-ultrawork로 해줘",
        "use omh-deep-interview",
        "use omh-code-review",
    )

    def test_route_chat_message_resolves_display_names_like_canonical_names(self) -> None:
        for message in self.ECHO_BACK_CASES:
            with self.subTest(message=message):
                canonical_message = canonical_display_mentions(
                    message, {f"omh-{name}": name for name in ("visual-qa", "ultrawork", "deep-interview", "code-review")}
                )
                self.assertNotEqual(canonical_message, message)
                self.assertEqual(
                    route_chat_message(message)["selected_skill"],
                    route_chat_message(canonical_message)["selected_skill"],
                )

    def test_every_installable_skill_routes_the_same_from_either_form(self) -> None:
        for definition in installable_skill_definitions():
            display = omh_skill_display_name(definition.name)
            with self.subTest(skill=definition.name):
                self.assertEqual(
                    route_chat_message(f"use {display}")["selected_skill"],
                    route_chat_message(f"use {definition.name}")["selected_skill"],
                )

    def test_route_hint_accepts_the_display_name_it_just_rendered(self) -> None:
        # Without the display-prefix normalization this echo-back landed on
        # `workflow-learning`: the bare `omh` token reads as vocabulary talk.
        self.assertEqual(
            awareness_route_hint("run omh-visual-qa on login", max_hints=2)["primary_workflow"],
            awareness_route_hint("run visual-qa on login", max_hints=2)["primary_workflow"],
        )

        response = build_chat_route_hint_payload("run omh-visual-qa on login", source="discord")["chat_response"]
        self.assertEqual(response["state"]["selected_workflow"], "visual-qa")
        self.assertIn("I can open `omh-visual-qa` first", response["body"])

    def test_router_display_name_echo_back_resolves_to_the_router_skill(self) -> None:
        self.assertEqual(route_chat_message("omh-routing")["selected_skill"], "oh-my-hermes")
        self.assertEqual(
            awareness_route_hint("use omh-routing", max_hints=2)["primary_workflow"],
            awareness_route_hint("use oh-my-hermes", max_hints=2)["primary_workflow"],
        )

    def test_the_display_prefix_alone_never_invents_a_route(self) -> None:
        """Overroute guards: the prefix only counts in front of a real catalog name.

        An unresolved `omh-...` token falls back to the router skill (which
        renders the picker) or to `workflow-learning`; normalization must never
        turn one into a real workflow dispatch.
        """
        for message in ("omh-", "omh-nonexistent", "omh-xyz please help"):
            with self.subTest(message=message):
                self.assertEqual(awareness_route_hint(message, max_hints=2)["status"], "no_hint")
                self.assertEqual(route_chat_message(message)["selected_skill"], "oh-my-hermes")

        # The bare word reaches the router skill, not `workflow-learning`. It
        # used to reach the latter only because that skill's `omh` triggers are
        # all negative-usage phrases ("did not use OMH") that the bare word was
        # a substring of; the word itself is a real `oh-my-hermes` trigger.
        # Either way it opens the picker rather than dispatching real work,
        # which is what this guard is about.
        self.assertEqual(awareness_route_hint("omh", max_hints=2)["status"], "no_hint")
        self.assertEqual(route_chat_message("omh")["selected_skill"], "oh-my-hermes")
        self.assertEqual(route_chat_message("omh-not-a-real-workflow")["selected_skill"], "workflow-learning")

    def test_existing_canonical_triggers_are_unaffected(self) -> None:
        for message, expected in (
            ("use visual-qa", "visual-qa"),
            ("ultrawork", "ultrawork"),
            ("deep-interview", "deep-interview"),
            ("oh-my-hermes", "oh-my-hermes"),
            ("run visual qa on the login page", "visual-qa"),
        ):
            with self.subTest(message=message):
                self.assertEqual(route_chat_message(message)["selected_skill"], expected)

    def test_canonical_display_mentions_only_rewrites_known_display_names(self) -> None:
        mapping = {"omh-visual-qa": "visual-qa", "omh-routing": "oh-my-hermes"}

        self.assertEqual(canonical_display_mentions("use omh-visual-qa", mapping), "use visual-qa")
        self.assertEqual(canonical_display_mentions("use omh-routing", mapping), "use oh-my-hermes")
        # Longest-first, so a trailing word that is not part of the name stays put.
        self.assertEqual(canonical_display_mentions("omh-visual-qa-now", mapping), "visual-qa-now")

        for untouched in ("omh", "omh-", "omh-nonexistent", "run-omh-thing", "somh-visual-qa"):
            with self.subTest(value=untouched):
                self.assertEqual(canonical_display_mentions(untouched, mapping), untouched)

    def test_awareness_display_map_matches_the_catalog_display_rule(self) -> None:
        mapping = awareness_module._canonical_workflow_by_display_name()

        self.assertEqual(mapping["omh-routing"], "oh-my-hermes")
        for display, canonical in mapping.items():
            with self.subTest(display=display):
                allowed = (omh_skill_display_name(canonical), *historical_skill_display_names(canonical))
                self.assertIn(display, allowed)
        # The current label always wins its slot; historical aliases only ever
        # add entries, never replace one.
        for display, canonical in mapping.items():
            if display == omh_skill_display_name(canonical):
                continue
            with self.subTest(alias=display):
                self.assertIn(omh_skill_display_name(canonical), mapping)


class HistoricalLabelAliasTests(unittest.TestCase):
    """Renamed labels stay resolvable: stale agents echo the era they installed."""

    def test_historical_labels_resolve_to_the_same_workflow_as_current_ones(self) -> None:
        for old, canonical in (
            ("omh-ultragoal", "ultragoal"),
            ("omh-ultrawork", "ultrawork"),
            ("omh-ralplan", "ralplan"),
            ("ulw-ultrawork", "ultrawork"),
            ("omh-strategy-brief", "strategy-brief"),
        ):
            with self.subTest(old=old):
                route = route_chat_message(f"use {old} for this", source="discord")
                current = route_chat_message(f"use {omh_skill_display_name(canonical)} for this", source="discord")
                self.assertEqual(route["selected_skill"], current["selected_skill"], old)

    def test_awareness_map_carries_the_pre_ulw_labels(self) -> None:
        mapping = awareness_module._canonical_workflow_by_display_name()
        self.assertEqual(mapping.get("omh-ultragoal"), "ultragoal")
        self.assertEqual(mapping.get("ulw-ultrawork"), "ultrawork")
        self.assertEqual(mapping.get("ulw-goal"), "ultragoal")


class DisplayNamesLeaveDegradationRenderingAloneTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        awareness_module._awareness_context_matches_message_cached.cache_clear()
        awareness_module._awareness_route_hint_cached.cache_clear()

    def test_a_degraded_route_hint_still_carries_the_note_exactly_once(self) -> None:
        locale_failure = mock.patch.object(
            awareness_module,
            "_prepare_routing_text",
            mock.Mock(side_effect=RuntimeError("locale boom")),
        )
        with locale_failure:
            response = build_chat_route_hint_payload(
                "Users report a wrapper-surface checkout bug", source="discord"
            )["chat_response"]

        body = response["body"]
        self.assertTrue(body.strip())
        self.assertEqual(body.count(DEGRADATION_CHAT_NOTE), 1)
        self.assertTrue(body.endswith(DEGRADATION_CHAT_NOTE))
        self.assertEqual(response["messenger_rendering"]["body_text"].count(DEGRADATION_CHAT_NOTE), 1)
        self.assertIn("omh-feedback-triage", body)


if __name__ == "__main__":
    unittest.main()


class UltraperfDisplayNameTests(unittest.TestCase):
    """ultraperf renders as ulw-perf; canonical and historical labels keep routing."""

    def test_ultraperf_display_name_and_historical_labels(self) -> None:
        self.assertEqual(omh_skill_display_name("ultraperf"), "ulw-perf")
        historical = historical_skill_display_names("ultraperf")
        self.assertIn("omh-ultraperf", historical)
        self.assertIn("ulw-ultraperf", historical)

    def test_ultraperf_display_and_historical_labels_route_to_the_workflow(self) -> None:
        mapping = {label: "ultraperf" for label in ("ulw-perf", "omh-ultraperf", "ulw-ultraperf")}
        for label in mapping:
            with self.subTest(label=label):
                self.assertEqual(
                    canonical_display_mentions(f"run {label} on the api", mapping),
                    "run ultraperf on the api",
                )
        self.assertEqual(route_chat_message("run ulw-perf on the api and worker")["selected_skill"], "ultraperf")


class UlwBundleParityTests(unittest.TestCase):
    """The copied plugin bundle's ULW tables cannot drift from the catalog.

    `awareness.py` duplicates the engine set and lifecycle stages on purpose (a
    copied bundle has no catalog import); this lock is what makes the copy
    safe. `ulw_inventory_payload()` is the catalog side of both comparisons.
    """

    def test_bundle_ulw_engine_set_and_lifecycle_stages_match_the_catalog(self) -> None:
        from omh.skills.catalog import ulw_inventory_payload
        from omh.skills.catalog_types import ULW_ENGINE_SKILL_NAMES

        payload = ulw_inventory_payload()
        catalog_stages = {
            engine["canonical"]: engine["lifecycle_stage"]
            for engine in (
                *payload["canonical_engines"],
                *payload["alias_engines"],
                *payload["retired_engines"],
            )
        }

        self.assertEqual(set(awareness_module._ULW_ENGINE_WORKFLOWS), set(ULW_ENGINE_SKILL_NAMES))
        self.assertEqual(awareness_module._ULW_ENGINE_LIFECYCLE_STAGES, catalog_stages)
