from __future__ import annotations

import re
import unittest

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.skills.catalog import builtin_definitions
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from omh.wrapper.contract import build_chat_interaction_payload

SKILL = "app-debugging"
NATIVE_SIBLING = "native-debugging"
BUILD_SIBLING = "build-failure-triage"
REPRODUCTION = "reproduction_record/v1"
FIX_HANDOFF = "fix_handoff/v1"
REFERENCE_PATH = "references/hypothesis-and-race-method.md"


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


def _route(message: str) -> dict[str, object]:
    return build_chat_interaction_payload(message, source="discord")["route"]


class AppDebuggingCatalogTests(unittest.TestCase):
    def test_no_fix_is_prepared_before_an_observed_reproduction(self) -> None:
        """#1709: the ordering is the contract, so it is stated where each reader looks."""

        mine = _definition(SKILL)
        blocked = [output for output in mine.expected_outputs if output.startswith(FIX_HANDOFF)]
        self.assertEqual(len(blocked), 1)
        self.assertIn(REPRODUCTION, blocked[0])
        self.assertIn("observed", blocked[0])
        self.assertTrue(any(rule.startswith("No fix before an observed reproduction") for rule in mine.safety_rules))
        self.assertTrue(any("not_observed" in step for step in mine.opening_steps))
        self.assertTrue(any(REPRODUCTION.split("/")[0] in line or "reproduction" in line for line in mine.final_checklist))

    def test_the_native_boundary_is_named_from_both_sides(self) -> None:
        mine = _definition(SKILL)
        for sibling in (NATIVE_SIBLING, BUILD_SIBLING):
            with self.subTest(sibling=sibling):
                statements = [text for text in mine.do_not_use_when if f"`{sibling}`" in text]
                self.assertEqual(len(statements), 1)
                back = [text for text in _definition(sibling).do_not_use_when if f"`{SKILL}`" in text]
                self.assertEqual(len(back), 1)

    def test_the_heavy_material_lives_in_the_reference(self) -> None:
        references = {
            template.relative_path: template.content
            for template in builtin_skill_reference_templates()
            if template.skill_name == SKILL
        }
        self.assertIn(REFERENCE_PATH, references)
        reference = references[REFERENCE_PATH]
        for heading in ("Hypotheses on distinct axes", "Flaky tests", "Races and lost updates"):
            with self.subTest(heading=heading):
                self.assertIn(heading, reference)
        body = next(template.content for template in builtin_skill_templates() if template.name == SKILL)
        self.assertIn(REFERENCE_PATH, body)
        self.assertNotIn("Races and lost updates", body)

    def test_three_failed_fixes_stop_for_an_architecture_review(self) -> None:
        """#2049: the count comes from executed runs of one command, and the next step is the user's."""

        body = next(template.content for template in builtin_skill_templates() if template.name == SKILL)
        rules = [line for line in body.splitlines() if "third failed fix" in line]
        self.assertEqual(len(rules), 1, "the escalation rule is one body line")
        for token in (
            "same reproduction command",
            "executed",
            "original symptom",
            "new symptom",
            "planned runs and other commands do not count",
            "no fourth",
            "architecture",
            "question",
        ):
            with self.subTest(body_token=token):
                self.assertIn(token, rules[0])
        pointers = [line for line in body.splitlines() if REFERENCE_PATH in line]
        self.assertEqual(len(pointers), 1, "the rule reuses the existing pointer instead of adding one")

        reference = next(
            template.content
            for template in builtin_skill_reference_templates()
            if template.skill_name == SKILL and template.relative_path == REFERENCE_PATH
        )
        heading = re.search(r"^## \d+\. After three failed fixes$", reference, re.MULTILINE)
        self.assertIsNotNone(heading, "the method reference keeps the escalation section")
        start = heading.start()
        section = reference[start : reference.index("\n## ", start + 1)]
        for token in (
            "never from the conversation",
            "same reproduction command",
            "planned but not executed",
            "only executed runs of the one reproduction move the count",
            "the original symptom is still there",
            "a new symptom shows up",
            "a fault that moved is a failed fix",
            "the root cause is open again",
            "observation that eliminated its hypothesis",
            "return to section 2",
            "Prepare no fourth fix",
            "shared assumptions",
            "as a question the user owns",
            "| One more fix will do it |",
        ):
            with self.subTest(reference_token=token):
                self.assertIn(token, section)
        leads = re.findall(r"^- (\*\*[^*]+\*\*)", section, re.MULTILINE)
        self.assertTrue(leads, "the section keeps its bolded bullet leads")
        for lead in leads:
            with self.subTest(section_lead_absent_from_body=lead):
                self.assertNotIn(lead, body)
        self.assertNotIn("| One more fix", body)
        self.assertIsNone(re.search(r"\b(19|20)\d{2}-\d{2}-\d{2}\b", section))


class AppDebuggingRoutingTests(unittest.TestCase):
    def test_the_issue_rows_dispatch_to_the_root_cause_lane(self) -> None:
        for message in (
            "a test fails one run in five in CI, how do I find out why",
            "the bug disappears when I add a print statement",
            "two workers write the same row, one update is lost",
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual(route["action"], "dispatch")
                self.assertEqual(route["selected_skill"], SKILL)
                self.assertFalse(route.get("explicit"))

    def test_the_same_phrases_outside_code_stay_away(self) -> None:
        for message in (
            "the root cause of my back pain is bad posture",
            "my phone update is lost after the reset",
            "the snow is flaky today",
            "the race condition at the marathon was muddy and slow",
            "competing hypotheses about the origin of the universe",
            "watch out for the race condition in this handler",
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertNotEqual(route.get("selected_skill"), SKILL)
                self.assertNotEqual(route["action"], "dispatch")

    def test_siblings_keep_their_lanes(self) -> None:
        self.assertEqual(_route("this binary segfaults on the third request, help me debug it")["selected_skill"], NATIVE_SIBLING)
        self.assertEqual(_route("the build is failing with a compile error")["selected_skill"], BUILD_SIBLING)

    def test_the_plugin_route_hint_names_the_lane(self) -> None:
        for message in (
            "a test fails one run in five in CI, how do I find out why",
            "the bug disappears when I add a print statement",
            "two workers write the same row, one update is lost",
        ):
            with self.subTest(message=message):
                self.assertEqual(awareness_route_hint(message).get("selected_workflow"), SKILL)
        self.assertNotEqual(awareness_route_hint("the snow is flaky today").get("selected_workflow"), SKILL)


if __name__ == "__main__":
    unittest.main()
