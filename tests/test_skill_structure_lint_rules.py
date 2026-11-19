"""Passing and isolated-rule coverage for the offline skill structure lint."""

from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from omh.skills.catalog import builtin_definitions
from omh.skills.validation import (
    SKILL_STRUCTURE_LINT_SCHEMA_VERSION,
    STRUCTURE_LINT_RULE_IDS,
    skill_structure_lint_payload,
)
from skill_structure_lint_test_support import blocked_sockets, violated_rules


class SkillStructureLintPassTests(unittest.TestCase):
    def test_tracked_tree_passes_with_zero_violations(self) -> None:
        with blocked_sockets():
            payload = skill_structure_lint_payload()

        self.assertEqual(payload["schema_version"], SKILL_STRUCTURE_LINT_SCHEMA_VERSION)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["violations"], [])

    def test_every_stable_rule_reports_a_pass_verdict_on_the_tracked_tree(self) -> None:
        """The passing fixture for every rule is the shipped tree itself.

        Listing the evaluated rules in the payload is what makes that claim
        checkable; otherwise a rule that silently stopped running would still
        look like a pass.
        """
        with blocked_sockets():
            payload = skill_structure_lint_payload()

        self.assertEqual(sorted(payload["rules"]), sorted(STRUCTURE_LINT_RULE_IDS))

    def test_two_runs_are_byte_identical(self) -> None:
        with blocked_sockets():
            first = skill_structure_lint_payload()
            second = skill_structure_lint_payload()

        self.assertEqual(first, second)

    def test_report_carries_no_score_grade_or_third_party_comparison(self) -> None:
        with blocked_sockets():
            payload = skill_structure_lint_payload()

        banned = {
            "score",
            "scores",
            "grade",
            "grades",
            "rank",
            "ranking",
            "rating",
            "badge",
            "badges",
            "third_party",
            "comparison",
        }
        self.assertEqual(banned & set(payload), set())

    def test_verdict_states_that_structure_is_not_host_loading_proof(self) -> None:
        """C012: passing structure never implies the host actually loaded a skill."""
        with blocked_sockets():
            payload = skill_structure_lint_payload()

        self.assertEqual(payload["checks"], "structure_only")
        self.assertEqual(payload["proves_host_loading"], False)


class SkillStructureLintRuleIsolationTests(unittest.TestCase):
    """One mutation per rule; exactly that rule must fail."""

    def _lint_with(self, definitions) -> dict[str, object]:
        with blocked_sockets():
            return skill_structure_lint_payload(definitions=definitions)

    def _mutated(self, name: str, **changes):
        definitions = list(builtin_definitions())
        for index, definition in enumerate(definitions):
            if definition.name == name:
                definitions[index] = dataclasses.replace(definition, **changes)
                return definitions
        raise AssertionError(f"missing catalog fixture skill: {name}")

    def assertOnlyRule(self, payload: dict[str, object], rule: str, skill: str) -> None:
        self.assertEqual(payload["ok"], False)
        self.assertEqual(violated_rules(payload), {rule})
        violations = payload["violations"]
        assert isinstance(violations, list)
        for violation in violations:
            self.assertEqual(violation["skill"], skill)
            self.assertTrue(str(violation["detail"]).strip())

    def test_catalog_contract_rule_fails_alone(self) -> None:
        payload = self._lint_with(self._mutated("skill-health", why_this_exists="  "))
        self.assertOnlyRule(payload, "SKILL_CATALOG_CONTRACT", "skill-health")

    def test_frontmatter_rule_fails_alone(self) -> None:
        """An alias that cannot survive unquoted YAML makes the description unrenderable."""
        payload = self._lint_with(self._mutated("skill-health", aliases=("bad/alias",)))
        self.assertOnlyRule(payload, "SKILL_FRONTMATTER_FIELDS", "skill-health")

    def test_harness_resolution_rule_fails_alone(self) -> None:
        from omh.skills import validation as validation_module

        harnesses = [
            harness
            for harness in validation_module.builtin_harnesses()
            if harness.name != "skill-health"
        ]
        with mock.patch.object(validation_module, "builtin_harnesses", return_value=harnesses):
            payload = self._lint_with(list(builtin_definitions()))

        self.assertOnlyRule(payload, "SKILL_HARNESS_RESOLVES", "skill-health")

    def test_generated_parity_rule_fails_alone(self) -> None:
        payload = self._lint_with(self._mutated("skill-health", phase="drifted-phase"))
        self.assertOnlyRule(payload, "SKILL_GENERATED_PARITY", "skill-health")

    def test_trigger_format_rule_fails_alone(self) -> None:
        """Sigil-only triggers are well-formed but never reach a non-router picker."""
        payload = self._lint_with(self._mutated("skill-health", triggers=("/omh", "./omh"), aliases=()))
        self.assertOnlyRule(payload, "SKILL_TRIGGER_FORMAT", "skill-health")

    def test_executable_consumer_rule_fails_alone(self) -> None:
        """Two consumers naming one skill must dispatch the same action.

        The mutation is applied to the routing policy rather than the catalog
        entry, because that is the shape of the real defect: the catalog looks
        fine while the wrapper card and the router disagree about what running
        the skill does.
        """
        from omh.routing import recommend as recommend_module

        policy = recommend_module._SKILL_POLICIES["skill-health"]
        drifted = dict(recommend_module._SKILL_POLICIES)
        drifted["skill-health"] = dataclasses.replace(policy, next_action="prepare_something_else")
        with mock.patch.object(recommend_module, "_SKILL_POLICIES", drifted):
            payload = self._lint_with(list(builtin_definitions()))

        self.assertOnlyRule(payload, "SKILL_EXECUTABLE_CONSUMER", "skill-health")

    def test_context_budget_rule_fails_alone(self) -> None:
        payload = self._lint_with(self._mutated("skill-health", use_when="x" * 200_000))
        self.assertOnlyRule(payload, "SKILL_CONTEXT_BUDGET", "skill-health")

    # A 70-character situation clause: Hermes' 60-character window cuts it.
    _LONG_SITUATION = "Quokka lemur tapir wombat clause that runs well past the index windows"

    def test_index_situation_visible_rule_fails_alone(self) -> None:
        self.assertEqual(len(self._LONG_SITUATION), 70)
        description = f"{self._LONG_SITUATION}: health overview."
        payload = self._lint_with(self._mutated("skill-health", description=description))
        self.assertOnlyRule(payload, "SKILL_INDEX_SITUATION_VISIBLE", "skill-health")
        (violation,) = payload["violations"]
        self.assertIn(self._LONG_SITUATION, violation["detail"])

    def test_index_situation_visible_rule_passes_a_clause_inside_the_window(self) -> None:
        description = "Quokka lemur tapir health check: " + "a long tail past the window " * 4
        payload = self._lint_with(self._mutated("skill-health", description=description))
        self.assertEqual(payload["violations"], [])


if __name__ == "__main__":
    unittest.main()
