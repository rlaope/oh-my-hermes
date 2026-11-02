"""The debugging records carry what the next reader needs to trust them.

A reproduction that matches a nearby failure instead of the reported one, a
large unminimised repro, probes left in the tree, a token quoted in a record,
and a regression test that was only ever seen green all look like progress and
are not. Each is held here at the field or line that names it, in the record
the user and the verification gate read, and in both shipped bodies where the
rule is git and host-neutral.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.skills.catalog import builtin_definitions
from omh.skills.catalog_definitions import FAILURE_ORIGIN_PROOF_RULE, REGRESSION_WITNESS_RULE
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates
from omh.skills.render import agent_skill_templates

APP = "app-debugging"
NATIVE = "native-debugging"
GATE = "verification-gate"
APP_METHOD = "references/hypothesis-and-race-method.md"
NATIVE_LOOP = "references/native-debug-loop.md"


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


def _reference(skill: str, path: str) -> str:
    return next(
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == skill and template.relative_path == path
    )


def _expectation(name: str, token: str) -> str:
    return next(line for line in _definition(name).artifact_expectations if line.startswith(token))


class ReproductionRecordTests(unittest.TestCase):
    def test_the_record_names_the_three_new_fields(self) -> None:
        line = _expectation(APP, "reproduction_record/v1")
        for field in ("`symptom_match`", "`loop_cost`", "`minimised`"):
            with self.subTest(field=field):
                self.assertIn(field, line)
        self.assertTrue(line.endswith("it reads observed or not_observed and nothing between"))

    def test_a_nearby_failure_does_not_reproduce_this_bug(self) -> None:
        bar = " ".join(_definition(APP).quality_bar)
        self.assertIn("a different failure near the same code is another bug, and this record stays not_observed", bar)
        table = _reference(APP, APP_METHOD)
        self.assertIn("| Symptom match |", table)
        self.assertIn("| Loop cost |", table)
        self.assertIn("| Minimised |", table)

    def test_minimise_comes_before_hypotheses_and_feeds_the_regression_test(self) -> None:
        bar = next(line for line in _definition(APP).quality_bar if line.startswith("`minimised` is filled before"))
        self.assertIn("`competing_hypotheses/v1`", bar)
        self.assertIn("the loop rerun without it still shows the symptom", bar)
        self.assertIn("`fix_handoff/v1` builds the regression test from what stayed", bar)
        method = _reference(APP, APP_METHOD)
        self.assertLess(method.index("**Then minimise.**"), method.index("## 2. Hypotheses on distinct axes"))

    def test_an_intermittent_fault_is_minimised_and_tightened_by_its_rate(self) -> None:
        """One green run proves nothing for a flaky fault, and pinning a cause away hides it."""
        bar = next(line for line in _definition(APP).quality_bar if line.startswith("`minimised` is filled before"))
        self.assertIn("for an intermittent fault, the same rate at the same N", bar)
        method = _reference(APP, APP_METHOD)
        self.assertIn('"still shows" means the same rate at the same N, never one red run', method)
        self.assertIn("rather than pin the variation away", method)
        self.assertIn("Pin what varies between runs and no standing hypothesis implicates", method)
        self.assertIn("**A pin that turns the loop green** is an observation about the cause", method)
        self.assertNotIn("pin whatever varies between runs", method)

    def test_the_loop_table_ends_in_a_capture_not_an_approval(self) -> None:
        method = _reference(APP, APP_METHOD)
        start = method.index("### When no test reaches the fault")
        table = method[start : method.index("\n## ", start)]
        self.assertIn("`bisect_plan/v1`", table)
        self.assertIn("the record takes them as user-observed", table)
        self.assertIn("nobody is asked to approve anything", table)
        self.assertIn("`competing_hypotheses/v1` waits for an observed record.", table)
        recovery = " ".join(_definition(APP).recovery_notes)
        self.assertIn("loop table", recovery)

    def test_secrets_never_reach_the_record(self) -> None:
        rule = next(rule for rule in _definition(APP).safety_rules if rule.startswith("Redact before recording"))
        self.assertIn("environment variables by name", rule)
        self.assertIn("`<redacted>`", rule)
        self.assertIn("never recorded unredacted", rule)

    def test_probes_are_tagged_and_their_removal_is_observed(self) -> None:
        checklist = " ".join(_definition(APP).final_checklist)
        self.assertIn("observed search for the session's probe tag returns nothing", checklist)
        self.assertIn("throwaway harness file is deleted or listed", checklist)
        self.assertIn("| The tree is free of probes |", _reference(APP, APP_METHOD))

    def test_the_confirmed_hypothesis_reaches_the_commit(self) -> None:
        line = _expectation(APP, "root_cause_record/v1")
        self.assertIn("commit or pull-request body states that confirmed hypothesis and the rivals it eliminated", line)

    def test_the_composition_mapping_records_the_same_fields(self) -> None:
        composition = _reference(APP, "references/debugging-skill-composition.md")
        row = next(line for line in composition.splitlines() if line.startswith("| Root cause investigation"))
        for field in ("`symptom_match`", "`loop_cost`", "`minimised`"):
            with self.subTest(field=field):
                self.assertIn(field, row)


class NativeFaultStatementTests(unittest.TestCase):
    def test_the_native_statement_shares_symptom_match_and_minimise(self) -> None:
        line = _expectation(NATIVE, "native_fault_statement/v1")
        self.assertIn("`symptom_match`", line)
        self.assertIn("`minimised`", line)
        loop = _reference(NATIVE, NATIVE_LOOP)
        self.assertIn("**Symptom match.**", loop)
        self.assertIn("**Minimised.**", loop)

    def test_a_print_fallback_is_tagged_and_removed(self) -> None:
        checklist = " ".join(_definition(NATIVE).final_checklist)
        self.assertIn("observed search for that tag returns nothing", checklist)


class RegressionWitnessTests(unittest.TestCase):
    def test_a_test_only_seen_green_is_a_hold_with_a_named_reason(self) -> None:
        self.assertIn("an observed red of that test, for the bug's reason, on the pre-fix tree", REGRESSION_WITNESS_RULE)
        self.assertIn("A fix test only ever observed green is HOLD with `regression_witness_missing`", REGRESSION_WITNESS_RULE)
        verdict = _expectation(GATE, "claim_verdict/v1")
        self.assertIn("`regression_witness_missing`", verdict)

    def test_the_pre_fix_tree_is_the_fixs_parent_and_a_collection_error_is_no_witness(self) -> None:
        self.assertIn(
            "the fix commit's parent, or the merge-base when the fix is the whole change", REGRESSION_WITNESS_RULE
        )
        self.assertIn("A collection or import error there is not a witness", REGRESSION_WITNESS_RULE)

    def test_any_observed_source_counts_when_it_is_recorded(self) -> None:
        """A worktree run is one source; CI and the debugging session's own pre-fix run are others."""
        for source in (
            "recorded with its source",
            "a run in a clean detached worktree at that tree",
            "a CI job on a commit that adds only the test",
            "the debugging session's run before the fix",
        ):
            with self.subTest(source=source):
                self.assertIn(source, REGRESSION_WITNESS_RULE)

    def test_rates_stand_in_for_one_run_where_one_run_proves_nothing(self) -> None:
        """An intermittent fault and a test-only fix both need a rate at a fixed N."""
        self.assertIn("the failure rate over N runs before beside 0/N at the same N after", REGRESSION_WITNESS_RULE)
        self.assertIn(
            "When the fix changes only test code, the witness is the old test's measured failure rate",
            REGRESSION_WITNESS_RULE,
        )

    def test_a_seam_the_fix_added_is_forced_red_by_reverting_behaviour_only(self) -> None:
        self.assertIn("reverting only the behavioural lines, keep the seam, and show that diff", REGRESSION_WITNESS_RULE)

    def test_the_witness_follows_the_origin_rule(self) -> None:
        bar = list(_definition(GATE).quality_bar)
        origin = next(index for index, line in enumerate(bar) if FAILURE_ORIGIN_PROOF_RULE in line)
        self.assertEqual(bar[origin + 1], REGRESSION_WITNESS_RULE)

    def test_the_rule_reaches_both_shipped_bodies(self) -> None:
        hermes = {template.name: template.content for template in builtin_skill_templates()}
        portable = {template.name: template.content for template in agent_skill_templates()}
        self.assertIn(REGRESSION_WITNESS_RULE, hermes[GATE])
        self.assertIn(REGRESSION_WITNESS_RULE, portable[f"omh-{GATE}"])


if __name__ == "__main__":
    unittest.main()
