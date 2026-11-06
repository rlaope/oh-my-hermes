"""Skills that describe a command's input file must name the keys the command's parser requires."""
from __future__ import annotations

from pathlib import Path
import unittest

from omh.runtime import run_efficiency
from omh.workflows import mcp_tool_name_compatibility as snapshot

ROOT = Path(__file__).resolve().parents[1]


def _body(skill: str) -> str:
    return (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")


class SkillInputShapeTests(unittest.TestCase):
    def test_run_efficiency_names_every_input_key_and_metric(self) -> None:
        body = _body("omh-run-efficiency")
        names = (
            run_efficiency._INPUT_KEYS | run_efficiency._OBSERVATION_KEYS | run_efficiency._METRICS
            | {run_efficiency.RUN_EFFICIENCY_INPUT_SCHEMA_VERSION, run_efficiency.RUN_CONTEXT_BUDGET_SCHEMA_VERSION}
        )
        for name in sorted(names):
            with self.subTest(name=name):
                self.assertIn(name, body)

    def test_run_efficiency_documented_input_parses(self) -> None:
        raw = {
            "schema_version": "run_efficiency_input/v1", "run_id": "r1",
            "context_budget": {"schema_version": run_efficiency.RUN_CONTEXT_BUDGET_SCHEMA_VERSION, "run_id": "r1",
                               "budget_bytes": 100, "emitted_bytes": 40, "remaining_bytes": 60,
                               "surfaces": {"hook": 2}},
            "observations": [{"metric": "tool_duration_ms", "value": 5, "source_ref": "tool-1"}],
        }
        self.assertEqual(run_efficiency.parse_run_efficiency_input(raw).run_id, "r1")

    def test_harness_inventory_names_every_snapshot_key(self) -> None:
        body = _body("omh-harness-session-inventory")
        for name in ("schema_version", "target_harness", "adapter", "required_tools", "advertised_tools",
                     "logical_name", "evidence_refs", "observation", "registered", "config_only",
                     snapshot.MCP_TOOL_NAME_SNAPSHOT_SCHEMA_VERSION):
            with self.subTest(name=name):
                self.assertIn(name, body)
        self.assertIn("`id` and `version`", body)

    def test_harness_documented_snapshot_is_accepted(self) -> None:
        raw = {
            "schema_version": snapshot.MCP_TOOL_NAME_SNAPSHOT_SCHEMA_VERSION, "target_harness": "codex",
            "adapter": {"id": "a", "version": "1"},
            "required_tools": [{"logical_name": "read", "evidence_refs": []}],
            "advertised_tools": [{"name": "read", "observation": "registered", "evidence_refs": []}],
        }
        snapshot._snapshot(raw)


class SkillHostClaimTests(unittest.TestCase):
    def test_cron_cancel_is_named_with_the_version_that_has_it(self) -> None:
        body = _body("omh-cancel")
        self.assertIn("`hermes cron cancel <job_id>`", body)
        self.assertIn("0.22.6 and later", body)
        self.assertIn("report the live run as still going", body)

    def test_gateway_card_states_what_a_refused_silence_marker_becomes(self) -> None:
        body = _body("omh-gateway-intent-card")
        self.assertIn("replaces the marker with a visible warning", body)
        self.assertIn("`origin` is only a cron job's `deliver` value", body)


if __name__ == "__main__":
    unittest.main()
