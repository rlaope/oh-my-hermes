"""Original market methodology must survive catalog and both host projections."""
from __future__ import annotations

import unittest

from omh.skills.catalog import installable_skill_definitions
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import (
    agent_skill_reference_templates,
    agent_skill_templates,
    builtin_skill_templates,
)


class MarketResearchSkillTests(unittest.TestCase):
    def test_opening_steps_live_once_in_the_compact_body(self) -> None:
        definition = next(item for item in installable_skill_definitions() if item.name == "market-research")
        body = next(item.content for item in builtin_skill_templates() if item.name == definition.name)
        contract = next(
            item.content for item in builtin_skill_reference_templates()
            if item.skill_name == definition.name and item.relative_path == "references/full-contract.md"
        )
        for step in definition.opening_steps:
            self.assertIn(step, body)
            self.assertNotIn(step, contract)
        self.assertLess(body.index("## First Steps"), body.index("## When to Use"))

    def test_market_procedure_passes_the_real_catalog_validator(self) -> None:
        from omh.skills.validation import validate_skill_definition_contract

        definition = next(item for item in installable_skill_definitions() if item.name == "market-research")
        self.assertEqual(validate_skill_definition_contract(definition), [])

    def test_business_brief_consumes_market_methods_without_owning_discovery(self) -> None:
        for templates, name in ((builtin_skill_templates(), "research-brief"), (agent_skill_templates(), "omh-research-brief")):
            body = next(item.content for item in templates if item.name == name)
            for clause in (
                "Use `omh-market-research` for scoped TAM/SAM/SOM",
                "decision implication, contrary evidence, confidence limit, and next verification owner",
                "observed, vendor-asserted, or inferred",
                "source cutoff, period/currency/base year, units and denominator",
                "not customer validation or an investment approval",
            ):
                self.assertIn(clause, body)

    def test_recurring_research_keeps_dated_market_snapshots_and_failed_coverage(self) -> None:
        body = next(item.content for item in builtin_skill_templates() if item.name == "research-department")
        for clause in (
            "dated competitor/pricing snapshot",
            "stable period, currency, units, source cutoff, and materiality threshold",
            "retain the failed source's previous cutoff",
            "observed, vendor-asserted, or inferred",
            "hand the bounded analysis to `omh-market-research`",
            "Outreach, paid sources, and schedule creation require separate explicit approval",
        ):
            self.assertIn(clause, body)

    def test_market_methods_and_templates_ship_to_both_hosts(self) -> None:
        definitions = {item.name: item for item in installable_skill_definitions()}
        self.assertIn("market-research", definitions)
        definition = definitions["market-research"]
        self.assertTrue(definition.progressive_disclosure)
        self.assertEqual(definition.category, "research")
        self.assertEqual(definition.hermes_role, "researcher")
        self.assertEqual(len(definition.procedure_steps), 6)
        self.assertEqual({q.required_input for q in definition.expert_questions}, set(definition.required_inputs))
        for bodies, references, name in (
            (builtin_skill_templates(), builtin_skill_reference_templates(), "market-research"),
            (agent_skill_templates(), agent_skill_reference_templates(), "omh-market-research"),
        ):
            with self.subTest(host=name):
                body = next(item.content for item in bodies if item.name == name)
                refs = {item.relative_path: item.content for item in references if item.skill_name == name}
                for path, terms in {
                    "references/market-sizing.md": ("TAM", "SAM", "SOM", "top-down", "bottom-up", "sensitivity", "currency", "denominator", "unknown", "tool"),
                    "references/customer-evidence.md": ("JTBD", "sample frame", "selection bias", "Q1", "consent", "contrary", "past behavior"),
                    "references/competitive-pricing.md": ("vendor-asserted", "observed", "inferred", "billing period", "tax", "not observed", "S1"),
                    "references/findings-template.md": ("decision", "source cutoff", "failed retrieval", "assumption", "confidence", "verification"),
                }.items():
                    self.assertIn(path, refs)
                    self.assertIn(path, body)
                    for term in terms:
                        self.assertIn(term, refs[path])
                # The Hermes body renders the safety rules once and the full
                # contract carries the boundaries the body does not; read both.
                contract = body + refs["references/full-contract.md"] if name == "market-research" else body
                for clause in (
                    "Never invent figures or quotes",
                    "Outreach, participant recruitment, payments, and scheduling each require separate explicit approval",
                    "product-discovery-validation",
                    "not customer validation",
                ):
                    self.assertIn(clause, contract)
                self.assertIn("references/procedure.md", refs)
                for sibling in ("omh-research-brief", "omh-product-discovery-validation"):
                    self.assertIn(f"`{sibling}`", refs["references/findings-template.md"])


if __name__ == "__main__":
    unittest.main()
