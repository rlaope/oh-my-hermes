"""A failing check says whether the change caused it, and the gates act on the answer.

`verification-gate` and `build-failure-triage` used to treat every red check
the same way. A failure that was already on the base branch then either
blocked a change that never touched it, or was waved through on the
assumption that it predated the change. Neither is an observation.

The contract held here has four parts. A failure carries one of three
origins. The only origin that takes a failure off the change's account,
`pre_existing`, has a single admissible proof, and that proof may not move the
tree the user is working in. The two gates read the origin the same way,
because they state it from one string. And an origin moves the wording and the
remedy of a verdict, never its colour: PASS does not stand beside a red
required check.
"""

from __future__ import annotations

import unittest

from omh.evidence.observed_check_results import FAILURE_ORIGINS
from omh.skills.catalog import builtin_definitions, builtin_harnesses
from omh.skills.catalog_definitions import (
    FAILURE_ORIGIN_PRECEDENCE,
    FAILURE_ORIGIN_PROOF_NAMING,
    FAILURE_ORIGIN_PROOF_RULE,
)
from omh.skills.packaging import builtin_skill_templates
from omh.skills.render import agent_skill_templates

GATE = "verification-gate"
TRIAGE = "build-failure-triage"
TRIAGE_VERDICTS = ("FIX_READY", "NEEDS_MORE_LOGS", "BLOCKED_BY_ENVIRONMENT", "ROUTE_TO_VERIFICATION_GATE")


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


class FailureOriginProofRuleTests(unittest.TestCase):
    def test_the_rule_names_every_origin_and_no_other(self) -> None:
        for origin in FAILURE_ORIGINS:
            with self.subTest(origin=origin):
                self.assertIn(f"`{origin}`", FAILURE_ORIGIN_PROOF_RULE)
        self.assertEqual(FAILURE_ORIGIN_PROOF_RULE.count("`pre_existing`"), 1)

    def test_pre_existing_has_one_proof_and_it_runs_at_the_merge_base(self) -> None:
        """An observed run in a clean detached worktree, and nothing weaker.

        `only when` is the load-bearing part: `introduced` may be read off the
        diff, because mislabelling breakage as introduced only sends its owner
        to look. `pre_existing` lets a change through, so it takes a run.
        """
        self.assertIn("`pre_existing` only when an observed run of the same command", FAILURE_ORIGIN_PROOF_RULE)
        self.assertIn("fails the same way at the merge-base", FAILURE_ORIGIN_PROOF_RULE)
        self.assertIn("in a clean detached worktree", FAILURE_ORIGIN_PROOF_RULE)
        self.assertIn("`git worktree add --detach <dir> <merge-base>`", FAILURE_ORIGIN_PROOF_RULE)

    def test_the_proof_never_moves_the_users_tree(self) -> None:
        """Stashing or checking out the working tree is named only to forbid it.

        The baseline could be measured by stashing the change, running, and
        popping. That moves files the user did not ask to have moved and
        loses them when the pop conflicts, so the rule may mention a stash or
        a checkout only inside the prohibition.
        """
        self.assertIn(
            "never by stashing or checking out the tree the user is working in",
            FAILURE_ORIGIN_PROOF_RULE,
        )
        for command in ("git stash", "stash pop", "git checkout"):
            with self.subTest(command=command):
                self.assertNotIn(command, FAILURE_ORIGIN_PROOF_RULE)

    def test_both_gates_state_the_rule_from_one_string(self) -> None:
        for name in (GATE, TRIAGE):
            with self.subTest(skill=name):
                lines = [line for line in _definition(name).quality_bar if FAILURE_ORIGIN_PROOF_RULE in line]
                self.assertEqual(len(lines), 1, f"{name} no longer carries the shared origin rule exactly once")

    def test_an_observed_merge_base_failure_outranks_a_diff_line_reading(self) -> None:
        """When the two proofs disagree, the observed run decides.

        A test that is already red at the merge-base can fail on a line the
        diff edited. Read by the diff line it is `introduced`, and
        build-failure-triage would hand it to the change as FIX_READY. The run
        observed it failing without the change, so it is `pre_existing`.
        """
        self.assertTrue(FAILURE_ORIGIN_PRECEDENCE.startswith("An observed merge-base run outranks a diff-line reading"))
        self.assertIn("is `pre_existing` even when its failure points at a line the diff changed", FAILURE_ORIGIN_PRECEDENCE)
        for name in (GATE, TRIAGE):
            with self.subTest(skill=name):
                line = next(line for line in _definition(name).quality_bar if FAILURE_ORIGIN_PROOF_RULE in line)
                self.assertIn(f"{FAILURE_ORIGIN_PROOF_RULE}. {FAILURE_ORIGIN_PRECEDENCE}.", line)

    def test_the_row_names_which_proof_its_origin_rests_on(self) -> None:
        """`introduced` read off the diff is an inference, and the row says so.

        The origin sits inside an observed row. One of its two proofs for
        `introduced` is a run and the other is a reading of where the failure
        points, and a reader who cannot tell which was used takes the reading
        for a run.
        """
        self.assertIn("a merge-base run is an observation", FAILURE_ORIGIN_PROOF_NAMING)
        self.assertIn("a diff-line reading is an inference", FAILURE_ORIGIN_PROOF_NAMING)
        for name in (GATE, TRIAGE):
            with self.subTest(skill=name):
                line = next(line for line in _definition(name).quality_bar if FAILURE_ORIGIN_PROOF_RULE in line)
                self.assertIn(FAILURE_ORIGIN_PROOF_NAMING, line)

    def test_the_rule_reaches_both_shipped_bodies_of_each_gate(self) -> None:
        """It is git and nothing host-specific, so the portable body keeps it."""
        hermes = {template.name: template.content for template in builtin_skill_templates()}
        portable = {template.name: template.content for template in agent_skill_templates()}
        for name in (GATE, TRIAGE):
            with self.subTest(skill=name):
                self.assertIn(FAILURE_ORIGIN_PROOF_RULE, hermes[name])
                self.assertIn(FAILURE_ORIGIN_PROOF_RULE, portable[f"omh-{name}"])


class VerificationGateOriginTests(unittest.TestCase):
    def _pass_line(self) -> str:
        return next(line for line in _definition(GATE).quality_bar if line.startswith("Return PASS only when"))

    def test_pass_never_stands_beside_a_failing_required_check(self) -> None:
        """An origin changes what a HOLD says, never whether it is a HOLD.

        A verdict that reads PASS over a red required check is read as green
        by everything downstream that reads only the verdict. So the origin
        is carried in the wording, and the colour does not move.
        """
        line = self._pass_line()
        self.assertTrue(
            line.startswith("Return PASS only when required checks pass and stale or missing evidence is resolved")
        )
        self.assertIn("PASS never stands beside a failing required check, whatever its origin", line)
        self.assertNotIn("or its failure is proven", line)

    def test_a_pre_existing_failure_is_a_hold_that_names_its_proof(self) -> None:
        line = self._pass_line()
        self.assertIn("A required check that fails `pre_existing` is HOLD worded as not charged to the change", line)
        self.assertIn("naming the merge-base run that proves it", line)

    def test_not_charged_needs_a_run_that_still_covered_the_change(self) -> None:
        """A failure that stopped the check early says nothing about the change.

        A collection or import error that predates the change aborts the
        check before any of the change runs. The breakage is not the change's,
        and the change is also unverified by that check, so the row is missing
        evidence and not a failure taken off the change's account.
        """
        line = self._pass_line()
        self.assertIn("only when the failing run's scope still covered the change", line)
        self.assertIn("a collection or import error", line)
        self.assertIn("leaves that check as missing evidence", line)

    def test_an_unknown_origin_is_a_hold_naming_the_missing_run(self) -> None:
        self.assertIn("`unknown` is HOLD with the merge-base run named as the missing evidence", self._pass_line())

    def test_the_hold_rule_admits_no_exception(self) -> None:
        """The skill and its harness say one thing about a failing check.

        The harness line was never given an origin clause, so an exception in
        the skill alone would have the gate's own harness contradict it.
        """
        self.assertIn(
            "Failed or unavailable checks must produce HOLD/BLOCK with a rerun or remediation path.",
            _definition(GATE).safety_rules,
        )
        harness = next(harness for harness in builtin_harnesses() if harness.name == GATE)
        self.assertIn("If checks are missing, stale, or failing, return HOLD/BLOCK", harness.fallback)

    def test_the_verdict_artifact_carries_the_origin_of_each_failure(self) -> None:
        self.assertTrue(
            any(
                line.startswith("claim_verdict/v1") and line.endswith("each failed one with its origin")
                for line in _definition(GATE).artifact_expectations
            )
        )


class BuildFailureTriageOriginTests(unittest.TestCase):
    def test_fix_ready_is_for_introduced_clusters_only(self) -> None:
        line = next(line for line in _definition(TRIAGE).quality_bar if line.startswith("Return FIX_READY only"))
        self.assertTrue(line.startswith("Return FIX_READY only for `introduced` clusters;"))
        self.assertIn("a `pre_existing` cluster gets its own follow-up handoff outside this change's fix", line)

    def test_mixed_origins_still_yield_one_verdict_and_unknown_wins(self) -> None:
        """The verdict artifact holds one value, so a mixed run needs an order.

        FIX_READY beside an unattributed cluster would read as "every failure
        here has a fix", so one `unknown` cluster holds the whole run at
        NEEDS_MORE_LOGS even when others are plainly `introduced`.
        """
        line = next(line for line in _definition(TRIAGE).quality_bar if line.startswith("Return FIX_READY only"))
        order = [
            "NEEDS_MORE_LOGS while any cluster that can run locally is `unknown`",
            "otherwise FIX_READY when at least one is `introduced`",
            "otherwise, with every cluster `pre_existing`, ROUTE_TO_VERIFICATION_GATE",
        ]
        positions = [line.find(step) for step in order]
        self.assertNotIn(-1, positions, f"a step of the verdict order is missing: {positions}")
        self.assertEqual(positions, sorted(positions))
        self.assertIn("even beside `introduced` ones", line)

    def test_no_verdict_was_invented_to_carry_the_origin(self) -> None:
        """The four verdicts are the contract other surfaces read; origin routes within them."""
        expectation = next(
            line for line in _definition(TRIAGE).artifact_expectations if line.startswith("build_failure_triage_verdict/v1")
        )
        self.assertEqual(
            expectation,
            "build_failure_triage_verdict/v1 returns " + ", ".join(TRIAGE_VERDICTS[:-1]) + f", or {TRIAGE_VERDICTS[-1]}",
        )
        line = next(line for line in _definition(TRIAGE).quality_bar if line.startswith("Return FIX_READY only"))
        named = {token.strip("`.,;") for token in line.split() if token.strip("`.,;").isupper() and "_" in token}
        self.assertLessEqual(named, set(TRIAGE_VERDICTS), f"the origin rule names a verdict the contract does not have: {named}")

    def test_the_cluster_matrix_and_the_checklist_both_carry_the_origin(self) -> None:
        mine = _definition(TRIAGE)
        matrix = next(line for line in mine.artifact_expectations if line.startswith("failure_cluster_matrix/v1"))
        for origin in FAILURE_ORIGINS:
            with self.subTest(origin=origin):
                self.assertIn(origin, matrix)
        self.assertTrue(
            any(
                "Every cluster carries an origin" in line and "no FIX_READY handoff covers" in line
                for line in mine.final_checklist
            )
        )


if __name__ == "__main__":
    unittest.main()
