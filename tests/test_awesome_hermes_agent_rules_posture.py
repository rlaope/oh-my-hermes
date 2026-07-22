from __future__ import annotations

import unittest

from omh.catalogs.awesome_hermes_agent import AwesomeHermesItem, PLUGIN_SUBSECTION
from omh.catalogs.awesome_hermes_agent_rules import coverage_for_item


def _synthetic_item(
    *,
    item_id: str,
    summary: str,
    section: str = "Candidate Shelf",
    subsection: str = "Unmapped Shelf",
) -> AwesomeHermesItem:
    return AwesomeHermesItem(
        id=item_id,
        name=item_id.replace("-", " ").title(),
        url=f"https://example.invalid/{item_id}",
        author="Synthetic",
        author_url="https://example.invalid",
        maturity="experimental",
        section=section,
        subsection=subsection,
        summary=summary,
        readme_line=999,
    )


class DynamicOrchestrationRulePostureTests(unittest.TestCase):
    def test_dynamic_orchestration_summary_defers_to_native_kanban_and_delegate_task(self) -> None:
        coverage = coverage_for_item(
            _synthetic_item(
                item_id="hermes-dynamic-workflows-posture-check",
                summary="Dynamic workflow scripts for subagents, swarm, and multi-agent parallel long running task execution with progress tracking, checkpoints, and failure recovery.",
                section="Skills & Plugins",
                subsection=PLUGIN_SUBSECTION,
            )
        )

        self.assertEqual(coverage.matched_rule_id, "dynamic_orchestration")
        summary = coverage.notes[0]
        self.assertIn("Kanban", summary)
        self.assertIn("delegate_task", summary)
        self.assertNotIn("does not import external worker runtimes", summary)


if __name__ == "__main__":
    unittest.main()
