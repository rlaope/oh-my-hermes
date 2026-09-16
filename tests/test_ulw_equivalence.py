"""ULW contract-equivalence gate for the `ulw-work` fold (issue #954, PR D).

Every counted obligation of the four retiring contracts (`team`,
`ultraprocess`, `ralph`, `ultragoal`) ships TWO mutants -- removal and
displacement -- introduced at the `SkillDefinition` level and re-rendered
through the real renderer (`workflow_skill_from_definition`), never by
monkeypatching or cache invalidation. The gate reads the byte-gated rendered
artifact, so a passing fixture is evidence about the file `docs workflows
--check` compares.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import unittest
from pathlib import Path

from omh.capabilities.families import capability_family_projection
from omh.quality.routing_precision import build_routing_precision_demo
from omh.quality.ulw_equivalence import (
    CONTRACT_EQUIVALENCE_CASES,
    CONTRACT_EQUIVALENCE_SCHEMA_VERSION,
    COORDINATED_SCOPE_TEARDOWN_TEXT,
    DISSOLVES_ADMISSIBLE_TARGETS,
    ULW_FOLD_CAPABILITIES,
    dissolves_on_fold_members,
    evaluate_contract_equivalence,
    external_cli_profile_leaks,
    parse_contract,
    rendered_target_contract,
    source_contract_digest,
    ulw_work_capability_projection,
)
from omh.skills.catalog import installable_skill_definitions, ulw_inventory_payload
from omh.skills.catalog_types import ULW_ENGINE_SKILL_NAMES
from omh.skills.packaging import builtin_skill_templates
from omh.skills.render import _definitions_by_name, workflow_skill, workflow_skill_from_definition

FIXTURES = Path(__file__).parent / "fixtures"
FOLDED_CONTRACTS = ("team", "ultraprocess", "ralph", "ultragoal")

# Settled by test_no_counted_obligation_is_pre_satisfied below: the plan's
# provisional denominators (team 6 / ultraprocess 11) survived the tie-break,
# and ralph / ultragoal were enumerated by the same procedure.
EXPECTED_COUNTED = {"team": 6, "ultraprocess": 11, "ralph": 6, "ultragoal": 12}
EXPECTED_EXCLUDED = {
    "team": (
        "team.lane_ownership",
        "team.worker_evidence_separation",
        "team.coding_harness_lanes",
        "team.engine_entry_confirmation",
        "team.ultrawork_boundary",
    ),
    "ultraprocess": (
        "ultraprocess.engine_entry_confirmation",
        "ultraprocess.coding_harness_staging",
    ),
    "ralph": ("ralph.engine_entry_confirmation",),
    "ultragoal": (
        "ultragoal.engine_entry_confirmation",
        "ultragoal.hidden_execution_boundary",
        "ultragoal.coding_harness_lanes",
    ),
}


def _pre_fold_fixture():
    raw = (FIXTURES / "ultrawork_main_contract.md").read_text(encoding="utf-8")
    return parse_contract(raw)


def _remove_carried(base, obligation):
    """Removal mutant: drop the obligation's carried entries from the definition."""
    changes = {}
    for entry in obligation.carried:
        current = changes.get(entry.definition_field, getattr(base, entry.definition_field))
        if entry.definition_field == "handoff_policy":
            if entry.text not in current:
                raise AssertionError(f"carried text missing from handoff_policy: {obligation.obligation_id}")
            changes[entry.definition_field] = current.replace(" " + entry.text, "").replace(entry.text, "")
        else:
            if entry.text not in current:
                raise AssertionError(
                    f"carried text missing from {entry.definition_field}: {obligation.obligation_id}"
                )
            changes[entry.definition_field] = tuple(item for item in current if item != entry.text)
    return dataclasses.replace(base, **changes)


def _displace_carried(base, obligation, capability):
    """Displacement mutant: keep the text but retag it into a different block."""
    other = next(name for name in ULW_FOLD_CAPABILITIES if name != capability)
    changes = {}
    for entry in obligation.carried:
        current = changes.get(entry.definition_field, getattr(base, entry.definition_field))
        displaced = entry.text.replace(f"[capability:{capability}]", f"[capability:{other}]")
        if displaced == entry.text:
            raise AssertionError(f"carried text has no capability tag: {obligation.obligation_id}")
        if entry.definition_field == "handoff_policy":
            changes[entry.definition_field] = current.replace(entry.text, displaced)
        else:
            changes[entry.definition_field] = tuple(
                displaced if item == entry.text else item for item in current
            )
    return dataclasses.replace(base, **changes)


class RendererEntryPointTests(unittest.TestCase):
    def test_workflow_skill_paths_are_byte_identical(self):
        definitions = _definitions_by_name()
        names = [
            definition.name
            for definition in installable_skill_definitions()
            if definition.name != "oh-my-hermes"
        ]
        self.assertGreater(len(names), 100)
        for name in names:
            with self.subTest(skill=name):
                self.assertEqual(
                    workflow_skill(name).content,
                    workflow_skill_from_definition(definitions[name], name).content,
                )

    def test_rendered_target_is_the_byte_gated_artifact(self):
        rendered = rendered_target_contract()
        template = next(t for t in builtin_skill_templates() if t.name == "ultrawork")
        self.assertEqual(rendered.raw, template.content)
        on_disk = (Path(__file__).parent.parent / "skills" / "ulw-work" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(rendered.raw, on_disk)

    def test_rendered_target_carries_all_four_capability_blocks(self):
        rendered = rendered_target_contract()
        for capability in ULW_FOLD_CAPABILITIES:
            with self.subTest(capability=capability):
                self.assertTrue(rendered.capability_blocks.get(capability))


class SourceBaselineTests(unittest.TestCase):
    def test_source_baseline_digests_are_pinned(self):
        for case in CONTRACT_EQUIVALENCE_CASES:
            with self.subTest(contract=case.contract_id):
                self.assertEqual(source_contract_digest(case.contract_id), case.baseline_digest)

    def test_case_table_covers_exactly_the_four_folding_contracts(self):
        self.assertEqual(tuple(case.contract_id for case in CONTRACT_EQUIVALENCE_CASES), FOLDED_CONTRACTS)
        self.assertEqual(
            tuple(case.target_capability for case in CONTRACT_EQUIVALENCE_CASES),
            ULW_FOLD_CAPABILITIES,
        )


class ContractEquivalenceTests(unittest.TestCase):
    def test_equivalence_passes_on_the_rendered_target(self):
        rendered = rendered_target_contract()
        for case in CONTRACT_EQUIVALENCE_CASES:
            with self.subTest(contract=case.contract_id):
                result = evaluate_contract_equivalence(case.contract_id, rendered)
                self.assertEqual(result["schema_version"], CONTRACT_EQUIVALENCE_SCHEMA_VERSION)
                self.assertTrue(result["ok"])
                self.assertEqual(result["failures"], [])
                self.assertEqual(tuple(result["excluded"]), EXPECTED_EXCLUDED[case.contract_id])

    def test_counted_denominators_are_settled(self):
        for case in CONTRACT_EQUIVALENCE_CASES:
            with self.subTest(contract=case.contract_id):
                self.assertEqual(len(case.counted_obligations()), EXPECTED_COUNTED[case.contract_id])

    def test_every_counted_obligation_fails_both_mutants(self):
        base = _definitions_by_name()["ultrawork"]
        mutators = ((_remove_carried, "removal"), (_displace_carried, "displacement"))
        for case in CONTRACT_EQUIVALENCE_CASES:
            for obligation in case.counted_obligations():
                for mutate, label in mutators:
                    with self.subTest(obligation=obligation.obligation_id, mutant=label):
                        if label == "removal":
                            mutant = mutate(base, obligation)
                        else:
                            mutant = mutate(base, obligation, case.target_capability)
                        rendered = parse_contract(
                            workflow_skill_from_definition(mutant, "ultrawork").content
                        )
                        result = evaluate_contract_equivalence(case.contract_id, rendered)
                        self.assertFalse(result["ok"])
                        if obligation.obligation_class == "unique":
                            self.assertEqual(result["failures"], [obligation.reason_code])
                        else:
                            self.assertEqual(
                                set(result["failures"]),
                                set(case.shared_failure_set(obligation)),
                            )

    def test_emptied_final_checklist_fails_with_multiple_reason_codes(self):
        """Guard on the renderer/gate wiring: a gate that still passes when the
        whole checklist is emptied is reading nothing (plan §8.2)."""
        base = _definitions_by_name()["ultrawork"]
        mutant = dataclasses.replace(base, final_checklist=("Checklist intentionally emptied.",))
        rendered = parse_contract(workflow_skill_from_definition(mutant, "ultrawork").content)
        failures: set[str] = set()
        for case in CONTRACT_EQUIVALENCE_CASES:
            failures.update(evaluate_contract_equivalence(case.contract_id, rendered)["failures"])
        self.assertGreater(len(failures), 1)
        result = evaluate_contract_equivalence("ultragoal", rendered)
        self.assertFalse(result["ok"])
        self.assertGreater(len(result["failures"]), 1)


class ObligationClassTests(unittest.TestCase):
    def test_no_counted_obligation_is_pre_satisfied(self):
        """The satisfaction-beats-uniqueness tie-break (plan §8.2.1), run
        against the pinned pre-fold contract from `main`. This converts the
        plan's provisional denominators into final ones."""
        fixture = _pre_fold_fixture()
        for case in CONTRACT_EQUIVALENCE_CASES:
            for obligation in case.counted_obligations():
                with self.subTest(obligation=obligation.obligation_id):
                    self.assertFalse(obligation.satisfied_without_capability_block(fixture))

    def test_pre_existing_exclusions_match_main(self):
        """Pinned exclusion list: the set of obligations satisfied by the
        pre-fold contract equals the declared `pre_existing_in_target` set --
        in both directions, so a relabeled counted obligation fails the pin."""
        fixture = _pre_fold_fixture()
        for case in CONTRACT_EQUIVALENCE_CASES:
            declared = {
                obligation.obligation_id
                for obligation in case.obligations
                if obligation.obligation_class == "pre_existing_in_target"
            }
            satisfied = {
                obligation.obligation_id
                for obligation in case.obligations
                if obligation.obligation_class != "dissolves_on_fold"
                and obligation.satisfied_without_capability_block(fixture)
            }
            with self.subTest(contract=case.contract_id):
                self.assertEqual(satisfied, declared)

    def test_relabeling_a_counted_obligation_fails_the_pin(self):
        """Mutant for the exclusion pin: declare a counted obligation
        `pre_existing_in_target` and the satisfied-on-main check rejects it."""
        fixture = _pre_fold_fixture()
        case = CONTRACT_EQUIVALENCE_CASES[0]
        obligation = case.counted_obligations()[0]
        relabeled = dataclasses.replace(obligation, obligation_class="pre_existing_in_target")
        self.assertFalse(relabeled.satisfied_without_capability_block(fixture))

    def test_dissolves_on_fold_members_are_admissible(self):
        members = dissolves_on_fold_members()
        self.assertEqual(
            tuple(member["member_id"] for member in members),
            ("team.ultrawork_boundary", "ultrawork.team_boundary"),
        )
        for member in members:
            with self.subTest(member=member["member_id"]):
                self.assertIn(member["named_target"], DISSOLVES_ADMISSIBLE_TARGETS)
        declared_dissolves = {
            obligation.obligation_id
            for case in CONTRACT_EQUIVALENCE_CASES
            for obligation in case.obligations
            if obligation.obligation_class == "dissolves_on_fold"
        }
        self.assertEqual(declared_dissolves, {"team.ultrawork_boundary"})

    def test_loop_boundary_is_inadmissible_for_dissolves(self):
        """Mutant for the admission rule: `loop` is retained, so declaring the
        ultraprocess -> loop boundary `dissolves_on_fold` must be rejected."""
        self.assertNotIn("loop", DISSOLVES_ADMISSIBLE_TARGETS)
        loop_boundary = next(
            obligation
            for case in CONTRACT_EQUIVALENCE_CASES
            for obligation in case.obligations
            if obligation.obligation_id == "ultraprocess.loop_routing_boundary"
        )
        self.assertEqual(loop_boundary.obligation_class, "unique")

    def test_dissolved_team_boundary_is_rewritten_not_dropped(self):
        """The reciprocal team boundary must be rewritten as a capability
        reference, not merely absent (plan §8.2.1)."""
        rendered = rendered_target_contract()
        do_not_use = rendered.sections.get("Do Not Use When", "")
        self.assertNotIn("use `team`", do_not_use)
        self.assertIn("`coordinated_scope` capability", do_not_use)
        # The retiring side stays untouched this PR: `team` still carries its
        # own boundary text; it dissolves when the contracts merge in PR G.
        team = _definitions_by_name()["team"]
        self.assertTrue(any("use `ultrawork`" in rule for rule in team.do_not_use_when))

    def test_teardown_is_a_new_requirement_not_equivalence(self):
        """`team` has no teardown rule (plan §4.2), so teardown is gated by
        presence on the target capability, never scored as carried equivalence."""
        rendered = rendered_target_contract()
        checklist_lines = rendered.section_lines.get("Completion Checklist", ())
        self.assertIn(COORDINATED_SCOPE_TEARDOWN_TEXT, [line.lstrip("- ") for line in checklist_lines])
        team_source = json.dumps(
            {
                "final_checklist": _definitions_by_name()["team"].final_checklist,
                "safety_rules": _definitions_by_name()["team"].safety_rules,
                "recovery_notes": _definitions_by_name()["team"].recovery_notes,
            }
        ).casefold()
        self.assertNotIn("teardown", team_source)


class CapabilityProjectionTests(unittest.TestCase):
    def test_ulw_work_is_not_maestro(self):
        for capability in ULW_FOLD_CAPABILITIES:
            with self.subTest(capability=capability):
                projection = ulw_work_capability_projection(capability)
                self.assertEqual(
                    external_cli_profile_leaks(projection),
                    [],
                    f"external CLI profile leaked into {capability}",
                )
                self.assertNotIn("selected_executor_profile", projection)
                self.assertTrue(projection["selection"]["capability_reason"].strip())
                self.assertIn("not", projection["selection"]["claim_boundary"])

    def test_unknown_capability_raises_key_error(self):
        with self.assertRaises(KeyError):
            ulw_work_capability_projection("maestro")

    def test_codex_injection_mutant_is_caught(self):
        """Inject an external CLI profile into one capability's projection and
        the leak check fails naming the capability's payload path."""
        projection = dict(ulw_work_capability_projection("delivery_boundary"))
        selection = dict(projection["selection"])
        selection["capability_reason"] = selection["capability_reason"] + " (default: codex)"
        projection["selection"] = selection
        leaks = external_cli_profile_leaks(projection)
        self.assertTrue(leaks)
        self.assertTrue(any("selection" in path and "capability_reason" in path for path in leaks))

    def test_projection_derives_from_the_case_table(self):
        for case in CONTRACT_EQUIVALENCE_CASES:
            projection = ulw_work_capability_projection(case.target_capability)
            self.assertEqual(projection["source_contract"], case.contract_id)
            self.assertEqual(
                projection["obligations"],
                tuple(obligation.obligation_id for obligation in case.counted_obligations()),
            )
            self.assertEqual(
                projection["reason_codes"],
                tuple(obligation.reason_code for obligation in case.counted_obligations()),
            )


class FamilyMoveTests(unittest.TestCase):
    def test_folded_contracts_left_the_family_projection_and_ultrawork_carries_it(self):
        """Projection assertion, not a diff assertion. After retirement
        (#954 stage 5) the four folded contracts lose their `capability`
        projection, so they leave the family map entirely; their family
        surface is `ultrawork`'s `delegate_coding_and_ship` membership."""
        mapping = capability_family_projection()["workflow_to_family"]
        self.assertEqual(mapping.get("ultrawork"), "delegate_coding_and_ship")
        for name in FOLDED_CONTRACTS:
            with self.subTest(workflow=name):
                self.assertIsNone(mapping.get(name))

    def test_no_folded_contract_sets_capability_family(self):
        definitions = _definitions_by_name()
        for name in FOLDED_CONTRACTS:
            with self.subTest(workflow=name):
                self.assertEqual(definitions[name].capability_family, "")

    def test_folded_contracts_left_every_family_roster(self):
        families = {
            family["id"]: family for family in capability_family_projection()["families"]
        }
        for family_id, family in families.items():
            for name in FOLDED_CONTRACTS:
                with self.subTest(family=family_id, workflow=name):
                    self.assertNotIn(name, family["primary_workflows"])
        self.assertIn("ultrawork", families["delegate_coding_and_ship"]["primary_workflows"])

    def test_no_dangling_adjacent_workflow_references(self):
        """All 23 `ultraprocess` + 2 `ultragoal` adjacency references were
        repointed (plus the duplicated catalog-picker hint in route_hints)."""
        from omh.plugin_bundle.omh.awareness import _ROUTE_HINT_RULES

        for rule in _ROUTE_HINT_RULES:
            adjacent = tuple(rule.get("adjacent_workflows", ()))
            with self.subTest(rule=rule.get("id")):
                self.assertNotIn("ultraprocess", adjacent)
                self.assertNotIn("ultragoal", adjacent)
                self.assertEqual(len(adjacent), len(set(adjacent)))


class RoutingInertnessTests(unittest.TestCase):
    def test_subset_digest_over_pre_existing_cases_is_byte_identical(self):
        """Regression pin over the pre-existing case ids. PR D's version
        forbade re-pinning; the retirement PR (#954 stage 5, window=0)
        deliberately rerouted the retiring engines' cues and edited their
        corpus rows, so the digest was re-pinned once in that PR and is a
        hard pin again from here on.

        Re-pinned a third time for the web-research split: the lookup half of
        `research`'s triggers became its own skill, so the four pinned cases
        whose messages are lookups move with them. A re-pin is only ever this
        -- a routing change the PR body names, with the moved rows enumerated
        in the fixture -- never a way to absorb an unexplained digest change.

        Re-pinned a fourth time for a reason the first three did not have: the
        row schema widened. `RoutingInterventionCase.expected_confidence`
        (#1607) put two more keys in every intervention row's `expected` block,
        so all of them serialize differently while nothing about their
        behaviour moved. That is why
        `test_observed_digest_is_inert_to_row_schema_changes` exists beside
        this one: this digest answers "did any pinned row change", the narrow
        one answers "did the router change", and only the second question can
        be answered without re-deriving it by hand every time a field is
        added."""
        fixture = json.loads(
            (FIXTURES / "routing_precision_subset_at_c.json").read_text(encoding="utf-8")
        )
        pinned_ids = set(fixture["case_ids"])
        self.assertEqual(len(pinned_ids), 237)
        demo = build_routing_precision_demo()
        subset = {
            "cases": sorted(
                [row for row in demo["cases"] if row["id"] in pinned_ids], key=lambda row: row["id"]
            ),
            "intervention_cases": sorted(
                [row for row in demo["intervention_cases"] if row["id"] in pinned_ids],
                key=lambda row: row["id"],
            ),
        }
        self.assertEqual(len(subset["cases"]) + len(subset["intervention_cases"]), 237)
        digest = hashlib.sha256(
            json.dumps(subset, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest, fixture["digest"])

    def test_observed_digest_is_inert_to_row_schema_changes(self):
        """The routing-inertness claim this class is named for.

        `digest` above covers the whole row, `expected` block included, which
        is what catches a pre-existing case whose assertion was quietly
        loosened. It also moves whenever a case dataclass gains a field, and
        those two causes are indistinguishable from the failure message -- the
        #1607 branch had to reproduce the old digest by stripping the new keys
        to show which one it was.

        This pin carries only what the router returned for each pinned
        message, so it moves when and only when a pinned message's verdict
        changes. Measured against all three ways `digest` can move:

        - a case dataclass gains a field: `digest` moves, this one does not;
        - a pinned case's message is reworded and still routes the same:
          `digest` moves (the row carries `message_sha256`), this one does not;
        - a pinned case's message reaches a different route: both move.

        So `digest` alone moving says no verdict changed and the row shape or
        an input did; both moving says routing did. Never re-pin this one to
        make a build green -- it moving is a behaviour change, and it belongs
        in the PR body with the rows named."""
        fixture = json.loads(
            (FIXTURES / "routing_precision_subset_at_c.json").read_text(encoding="utf-8")
        )
        pinned_ids = set(fixture["case_ids"])
        demo = build_routing_precision_demo()
        rows = sorted(
            [row for row in demo["cases"] if row["id"] in pinned_ids]
            + [row for row in demo["intervention_cases"] if row["id"] in pinned_ids],
            key=lambda row: row["id"],
        )
        self.assertEqual(len(rows), 237)
        observed = [{"id": row["id"], "observed": row["observed"]} for row in rows]
        digest = hashlib.sha256(
            json.dumps(observed, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest, fixture["observed_digest"])

    def test_the_pinned_case_ids_stay_in_sorted_order(self):
        """Sorted ids are what keeps a re-pin a readable diff.

        Both consumers turn `case_ids` into a set, so the order in the file
        cannot fail either of them: a re-pin that walks
        `build_routing_precision_demo()` in producer order rewrites all 237
        lines, buries whichever rows actually moved, and still passes. Producer
        order is corpus order, so it re-shuffles whenever a case is inserted
        above a pinned one. The fixture has been re-pinned four times and
        nothing told any of those authors which order to write."""
        fixture = json.loads(
            (FIXTURES / "routing_precision_subset_at_c.json").read_text(encoding="utf-8")
        )
        case_ids = fixture["case_ids"]
        self.assertEqual(
            case_ids,
            sorted(case_ids),
            "re-pin `case_ids` as sorted(...), not in build_routing_precision_demo() order",
        )

    def test_added_controls_are_outside_the_pinned_subset(self):
        fixture = json.loads(
            (FIXTURES / "routing_precision_subset_at_c.json").read_text(encoding="utf-8")
        )
        pinned_ids = set(fixture["case_ids"])
        added = {
            "one-owner-one-line-fix",
            "coordinated-workers-shared-task-list",
            "disjoint-lanes-reaches-existing-path",
        }
        self.assertFalse(added & pinned_ids)
        demo = build_routing_precision_demo()
        all_ids = {row["id"] for row in demo["cases"]} | {
            row["id"] for row in demo["intervention_cases"]
        }
        self.assertTrue(added <= all_ids)

    def test_ulw_engine_surface_reflects_the_retired_stage(self):
        """#954 stage 5 (window=0): the name set keeps all thirteen members --
        it drives `ulw-` display prefixing, which retired reference contracts
        keep -- while the canonical/retired split lives in `lifecycle_stage`
        and the inventory producer."""
        self.assertEqual(
            set(ULW_ENGINE_SKILL_NAMES),
            {
                "context",
                "deep-interview",
                "research",
                "ralplan",
                "ultrawork",
                "maestro",
                "loop",
                "ultraqa",
                "ultraperf",
                "team",
                "ultraprocess",
                "ralph",
                "ultragoal",
            },
        )
        payload = ulw_inventory_payload()
        self.assertEqual(len(payload["canonical_engines"]), 9)
        self.assertEqual(payload["alias_engines"], [])
        self.assertEqual(
            {engine["canonical"] for engine in payload["retired_engines"]},
            set(FOLDED_CONTRACTS),
        )
        for engine in payload["retired_engines"]:
            self.assertEqual(engine["lifecycle_stage"], "retired")


if __name__ == "__main__":
    unittest.main()
