from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.maintenance.advisory import build_model_routing_status  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.routing.owner_preference import (  # noqa: E402
    empty_owner_preference_state,
    record_accepted_explicit_choice,
    write_owner_preference,
)
from omh.coding.pi_family_interop import RUNTIME_CONFIG_FILES, RUNTIME_HOME


ROUTE_FAMILY = "ulw-coding-delivery"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ModelRoutingStatusTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[object, Path]:
        omh_home = root / ".omh-state"
        hermes_home = root / ".hermes"
        discovery_home = root / "local-home"
        paths = resolve_paths(omh_home, hermes_home)
        _write(
            discovery_home / RUNTIME_HOME / RUNTIME_CONFIG_FILES[0],
            json.dumps(
                {
                    "models": [
                        {"provider": "kimi-coding", "model": "kimi-k3.1-pro"},
                        {"provider": "zai", "model": "glm-5.2"},
                        {"provider": "xai", "model": "grok-code-fast"},
                    ]
                }
            ),
        )
        _write(
            discovery_home / ".codex" / "sessions" / "seen.jsonl",
            json.dumps({"payload": {"model_provider": "openai", "model": "gpt-6.1-sol"}}) + "\n",
        )
        _write(
            hermes_home / "config.yaml",
            "model:\n  aliases:\n    main: kimi-coding/kimi-k3.1-pro\n    cheap: zai/glm-5.2\n",
        )
        state = empty_owner_preference_state()
        for index in range(3):
            state = record_accepted_explicit_choice(
                state,
                route_family=ROUTE_FAMILY,
                selected_owner="pi-family-runtime",
                occurred_at=f"2026-08-13T00:00:0{index + 1}Z",
            )
        write_owner_preference(paths, state)
        return paths, discovery_home

    def test_status_separates_discovered_from_confirmed_and_explains_missing_heads(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, discovery_home = self._fixture(Path(tmp))
            payload = build_model_routing_status(paths, discovery_home=discovery_home)

        self.assertEqual(payload["schema_version"], "model_routing_status/v1")
        self.assertEqual(
            {entry["model_id"] for entry in payload["models"]["confirmed"]},
            {"kimi-k3.1-pro", "glm-5.2", "grok-code-fast"},
        )
        self.assertEqual(
            [entry["model_id"] for entry in payload["models"]["discovered_only"]],
            ["gpt-6.1-sol"],
        )
        # A discovered-only model is not confirmed. Since 2026-10-13 `deep`
        # ends on Kimi K3.1 Pro and resolves, so the owner-default case is
        # unspecified-low: it names gpt-6.1-sol and still falls through, and
        # unspecified-high reports gpt-6.1-sol as its missing head.
        low = payload["maestro"]["categories"]["unspecified-low"]
        self.assertEqual(low["status"], "owner_default")
        self.assertEqual(low["missing_head"], "glm-5.3")
        unspecified = payload["maestro"]["categories"]["unspecified-high"]
        self.assertEqual(unspecified["selected_model"], "kimi-k3.1-pro")
        self.assertEqual(unspecified["missing_head"], "gpt-6.1-sol")
        self.assertIn("metadata", payload["claim_boundary"])
        self.assertNotIn("execution confirmed", json.dumps(payload).lower())

    def test_status_reports_aliases_owner_learning_auth_boundary_and_exact_action(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, discovery_home = self._fixture(Path(tmp))
            payload = build_model_routing_status(paths, discovery_home=discovery_home)

        self.assertEqual(payload["hermes"]["status"], "configured")
        self.assertEqual(payload["hermes"]["aliases"]["main"], "kimi-coding/kimi-k3.1-pro")
        self.assertEqual(payload["hermes"]["auth"]["status"], "unobserved")
        # Mutation: report "learned" or a selected owner again; a stored choice selects no owner.
        stored = payload["owner_learning"]["routes"][ROUTE_FAMILY]
        self.assertEqual(stored["status"], "recorded")
        self.assertEqual(stored["recorded_owner"], "pi-family-runtime")
        self.assertIs(stored["selects_owner"], False)
        self.assertNotIn("selected_owner", stored)
        self.assertEqual(payload["owner_learning"]["status"], "recorded")
        self.assertNotIn("learned", json.dumps(payload["owner_learning"]))
        self.assertIsInstance(payload["next_action"], str)
        self.assertTrue(payload["next_action"])

    def test_missing_and_corrupt_inputs_are_explicit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            missing = build_model_routing_status(paths, discovery_home=root / "empty-home")
            self.assertEqual(missing["hermes"]["status"], "missing")
            self.assertEqual(missing["owner_learning"]["status"], "missing")
            _write(paths.hermes_config_path, "model:\n\taliases: broken\n")
            _write(paths.omh_home / "routing" / "owner-preference.json", "{broken")
            corrupt = build_model_routing_status(paths, discovery_home=root / "empty-home")
            self.assertEqual(corrupt["hermes"]["status"], "corrupt")
            self.assertEqual(corrupt["owner_learning"]["status"], "corrupt")
            self.assertIn("repair", corrupt["next_action"].lower())

    def test_cli_json_surface_is_compact_and_offline(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, discovery_home = self._fixture(root)
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(paths.omh_home),
                    "--hermes-home", str(paths.hermes_home),
                    "coding", "model-routing", "status",
                    "--discovery-home", str(discovery_home),
                    "--json",
                ]
            )
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["schema_version"], "model_routing_status/v1")
        self.assertEqual(len(stdout.splitlines()), 1)


    def test_cli_text_reports_stored_choices_as_selecting_no_owner(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, discovery_home = self._fixture(root)
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(paths.omh_home),
                    "--hermes-home", str(paths.hermes_home),
                    "coding", "model-routing", "status",
                    "--discovery-home", str(discovery_home),
                ],
                output_json=False,
            )
        self.assertEqual(status, 0, stderr)
        self.assertIn("Stored owner choices: 1 (history only; they select no owner)", stdout)
        self.assertNotIn("Owner learning", stdout)
        self.assertNotIn("learned", stdout)

class ModelRoutingResetTests(unittest.TestCase):
    def test_reset_changes_only_owner_preference_metadata_and_is_visible_in_status(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, discovery_home = ModelRoutingStatusTests()._fixture(root)
            hermes_before = paths.hermes_config_path.read_bytes()
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(paths.omh_home),
                    "--hermes-home", str(paths.hermes_home),
                    "coding", "model-routing", "reset",
                    "--route-family", ROUTE_FAMILY,
                    "--reason", "operator_reset",
                    "--json",
                ]
            )
            payload = json.loads(stdout)
            after = build_model_routing_status(paths, discovery_home=discovery_home)
            hermes_after = paths.hermes_config_path.read_bytes()
        self.assertEqual(status, 0, stderr)
        self.assertEqual(payload["status"], "reset")
        self.assertEqual(payload["reset_scope"], "owner_preference_metadata_only")
        self.assertEqual(after["owner_learning"]["routes"][ROUTE_FAMILY]["status"], "reset")
        self.assertEqual(hermes_before, hermes_after)

    def test_reset_from_missing_state_reports_that_it_created_only_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(root / ".omh"),
                    "--hermes-home", str(root / ".hermes"),
                    "coding", "model-routing", "reset",
                    "--route-family", ROUTE_FAMILY,
                    "--json",
                ]
            )
            payload = json.loads(stdout)
        self.assertEqual(status, 0, stderr)
        self.assertEqual(payload["previous_state"], "missing")
        self.assertEqual(payload["reset_scope"], "owner_preference_metadata_only")

    def test_reset_refuses_to_overwrite_corrupt_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".omh" / "routing" / "owner-preference.json"
            _write(path, "{broken")
            status, _stdout, stderr = run_cli(
                [
                    "--omh-home", str(root / ".omh"),
                    "--hermes-home", str(root / ".hermes"),
                    "coding", "model-routing", "reset",
                    "--route-family", ROUTE_FAMILY,
                ]
            )
            self.assertNotEqual(status, 0)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
            self.assertIn("corrupt", stderr.lower())


class ModelIdSummaryTests(unittest.TestCase):
    def test_each_model_is_named_once_with_its_observation_count(self) -> None:
        from omh.commands.coding import _model_id_summary

        entries = [{"model_id": "claude-opus-5-5"}] * 412 + [{"model_id": "claude-sonnet-5-5"}] * 61 + [{"model_id": "fast"}]
        self.assertEqual(_model_id_summary(entries), "claude-opus-5-5 (x412), claude-sonnet-5-5 (x61), fast")

    def test_no_entries_reads_none(self) -> None:
        from omh.commands.coding import _model_id_summary

        self.assertEqual(_model_id_summary([]), "none")


if __name__ == "__main__":
    unittest.main()
