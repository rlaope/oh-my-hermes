from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli


class HermesReadinessCliTests(unittest.TestCase):
    def test_reports_native_surfaces_and_omh_reinforcement(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            _write_ready_fixture(omh_home, hermes_home)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hermes", "readiness"],
                output_json=False,
            )

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "hermes_agent_readiness/v1")
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["official_basis"]["source_repo"], "NousResearch/hermes-agent")
        self.assertIn("sessions/sessions.json", " ".join(payload["official_basis"]["stable_surfaces"]))
        surfaces = {surface["id"]: surface for surface in payload["native_surfaces"]}
        self.assertEqual(surfaces["hermes_config"]["status"], "available")
        self.assertEqual(surfaces["managed_omh_skills"]["status"], "available")
        self.assertEqual(surfaces["omh_skill_external_dir"]["status"], "available")
        self.assertEqual(surfaces["sessions_index"]["status"], "available")
        self.assertEqual(surfaces["state_db"]["status"], "available")
        self.assertEqual(surfaces["source_checkout"]["status"], "available")
        self.assertEqual(payload["summary"]["missing_required_surfaces"], 0)
        self.assertEqual(payload["summary"]["observed_native_state_surfaces"], 2)
        self.assertIn("not proof that Hermes loaded OMH", payload["claim_boundary"])

    def test_reinforcement_covers_memory_learning_loop_wiki_runtime_and_subagents(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            _write_ready_fixture(omh_home, hermes_home)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hermes", "readiness"],
                output_json=False,
            )

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        reinforcement = {item["id"]: item for item in payload["omh_reinforcement"]}
        self.assertTrue(
            {
                "memory_management",
                "self_improvement",
                "loop_control",
                "wiki_external_knowledge",
                "runtime_observation",
                "subagent_and_handoff",
            }
            <= set(reinforcement)
        )
        for item in reinforcement.values():
            self.assertEqual(item["mapping_state"], "mapped")
            self.assertNotIn("status", item)

    def test_handles_empty_target_home_as_setup_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hermes", "readiness"],
                output_json=False,
            )

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "hermes_agent_readiness/v1")
        self.assertEqual(payload["status"], "needs_setup")
        surfaces = {surface["id"]: surface for surface in payload["native_surfaces"]}
        self.assertEqual(surfaces["hermes_config"]["status"], "missing")
        self.assertEqual(surfaces["managed_omh_skills"]["status"], "missing")
        actions = {action["id"] for action in payload["next_actions"]}
        self.assertTrue({"run_hermes_setup", "run_omh_setup", "observe_hermes_runtime"} <= actions)
        self.assertGreater(payload["summary"]["missing_required_surfaces"], 0)


def _write_ready_fixture(omh_home: Path, hermes_home: Path) -> None:
    managed_skill = omh_home / "skills" / "oh-my-hermes" / "SKILL.md"
    managed_skill.parent.mkdir(parents=True)
    managed_skill.write_text("# oh-my-hermes\n", encoding="utf-8")
    (hermes_home / "skills").mkdir(parents=True)
    (hermes_home / "optional-skills").mkdir()
    (hermes_home / "plugins").mkdir()
    (hermes_home / "sessions").mkdir()
    (hermes_home / "sessions" / "sessions.json").write_text("{}", encoding="utf-8")
    (hermes_home / "state.db").write_text("", encoding="utf-8")
    (hermes_home / ".mcp.json").write_text("{}", encoding="utf-8")
    checkout = hermes_home / "hermes-agent"
    checkout.mkdir()
    (checkout / "README.md").write_text("# Hermes Agent\n", encoding="utf-8")
    (hermes_home / "config.yaml").write_text(
        f"skills:\n  external_dirs:\n    - {omh_home / 'skills'}\n",
        encoding="utf-8",
    )
