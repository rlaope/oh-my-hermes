from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, assert_never

from _cli_harness import run_cli

UnsafeProviderLabel = Literal["traversal", "absolute", "secret_like"]


class HermesRetainedContextCliTests(unittest.TestCase):
    def test_reports_hermes_and_omh_retained_context_channels(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            _write_retained_context_fixture(omh_home, hermes_home)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hermes", "retained-context"],
                output_json=False,
            )

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "hermes_retained_context/v1")
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["source_basis"]["source_repo"], "NousResearch/hermes-agent")
        self.assertEqual(payload["source_basis"]["readiness_basis_version"], "hermes_agent_source_basis/v1")
        self.assertIn("refresh_policy", payload["source_basis"])
        channels = {channel["id"]: channel for channel in payload["channels"]}
        self.assertEqual(channels["hermes_sessions_index"]["status"], "available")
        self.assertFalse(channels["hermes_sessions_index"]["metrics"]["content_inspected"])
        self.assertEqual(channels["hermes_state_db"]["status"], "available")
        self.assertEqual(channels["hermes_memory_provider"]["status"], "available")
        self.assertTrue(channels["hermes_memory_provider"]["metrics"]["provider_configured"])
        self.assertTrue(channels["hermes_memory_provider"]["metrics"]["provider_id_safe"])
        self.assertTrue(channels["hermes_memory_provider"]["metrics"]["plugin_marker_exists"])
        self.assertEqual(channels["omh_memory_store"]["status"], "available")
        self.assertFalse(channels["omh_memory_store"]["metrics"]["content_inspected"])
        self.assertEqual(channels["omh_learning_store"]["metrics"]["trace_count"], 1)
        self.assertFalse(channels["omh_runtime_journal"]["metrics"]["content_inspected"])
        self.assertEqual(channels["omh_loop_artifacts"]["status"], "available")
        self.assertEqual(channels["external_knowledge_store"]["status"], "available")
        self.assertEqual(payload["summary"]["available_channels"], 9)
        self.assertEqual(payload["summary"]["external_knowledge_channels"], 1)
        self.assertEqual(payload["summary"]["uncategorized_channels"], 0)
        self.assertEqual(
            payload["summary"]["total_channels"],
            payload["summary"]["hermes_native_channels"]
            + payload["summary"]["omh_retention_channels"]
            + payload["summary"]["external_knowledge_channels"]
            + payload["summary"]["uncategorized_channels"],
        )
        self.assertIn("opaque Hermes internal memory", payload["claim_boundary"])

    def test_empty_environment_reports_missing_setup_without_memory_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hermes", "retained-context"],
                output_json=False,
            )

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "hermes_retained_context/v1")
        self.assertEqual(payload["status"], "needs_setup")
        channels = {channel["id"]: channel for channel in payload["channels"]}
        self.assertEqual(channels["hermes_config"]["status"], "missing")
        self.assertEqual(channels["hermes_memory_provider"]["status"], "unknown")
        self.assertGreater(payload["summary"]["missing_required_channels"], 0)
        action_ids = {action["id"] for action in payload["next_actions"]}
        self.assertTrue({"run_hermes_setup", "configure_memory_provider"} <= action_ids)

    def test_accepts_quoted_commented_dotted_provider_id(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            _write_retained_context_fixture(
                omh_home,
                hermes_home,
                provider_id="custom.mem0",
                config_text='memory:\n  provider: "custom.mem0" # default provider\n',
            )

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hermes", "retained-context"],
                output_json=False,
            )

        self.assertEqual(stderr, "")
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        channels = {channel["id"]: channel for channel in payload["channels"]}
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(channels["hermes_memory_provider"]["status"], "available")
        self.assertTrue(channels["hermes_memory_provider"]["metrics"]["provider_id_safe"])

    def test_rejects_unsafe_provider_values_without_echoing_them(self) -> None:
        unsafe_labels: tuple[UnsafeProviderLabel, ...] = ("traversal", "absolute", "secret_like")
        for unsafe_label in unsafe_labels:
            with self.subTest(unsafe_label=unsafe_label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                omh_home = root / ".omh"
                hermes_home = root / ".hermes"
                outside_root = root / "outside"
                (outside_root / "plugin.yaml").parent.mkdir(parents=True)
                (outside_root / "plugin.yaml").write_text("name: unsafe\n", encoding="utf-8")
                unsafe_value = _unsafe_provider_value(unsafe_label, outside_root)
                _write_retained_context_fixture(
                    omh_home,
                    hermes_home,
                    provider_id="mem0",
                    config_text=f"memory:\n  provider: {unsafe_value}\n",
                )

                status, stdout, stderr = run_cli(
                    ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hermes", "retained-context"],
                    output_json=False,
                )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertNotIn(unsafe_value, stdout)
            payload = json.loads(stdout)
            channels = {channel["id"]: channel for channel in payload["channels"]}
            self.assertEqual(payload["status"], "needs_setup")
            self.assertEqual(channels["hermes_memory_provider"]["status"], "unknown")
            self.assertFalse(channels["hermes_memory_provider"]["metrics"]["provider_id_safe"])
            self.assertFalse(channels["hermes_memory_provider"]["metrics"]["plugin_marker_exists"])


def _unsafe_provider_value(label: UnsafeProviderLabel, outside_root: Path) -> str:
    match label:
        case "traversal":
            return "../mem0"
        case "absolute":
            return str(outside_root)
        case "secret_like":
            return "sk-secret-credential"
        case unreachable:
            assert_never(unreachable)


def _write_retained_context_fixture(
    omh_home: Path,
    hermes_home: Path,
    *,
    provider_id: str = "mem0",
    config_text: str | None = None,
) -> None:
    (hermes_home / "sessions").mkdir(parents=True)
    (hermes_home / "sessions" / "sessions.json").write_text(
        json.dumps(
            {
                "slack:T1:C1": {"session_id": "s1"},
                "discord:guild:channel": {"session_id": "s2"},
            }
        ),
        encoding="utf-8",
    )
    (hermes_home / "state.db").write_text("", encoding="utf-8")
    (hermes_home / "plugins" / "memory" / provider_id).mkdir(parents=True)
    (hermes_home / "plugins" / "memory" / provider_id / "plugin.yaml").write_text(
        f"name: {provider_id}\n",
        encoding="utf-8",
    )
    (hermes_home / "config.yaml").write_text(
        config_text if config_text is not None else f"memory:\n  provider: {provider_id}\n",
        encoding="utf-8",
    )

    (omh_home / "memory").mkdir(parents=True)
    (omh_home / "memory" / "index.json").write_text(json.dumps({"records": [{"id": "m1"}]}), encoding="utf-8")
    (omh_home / "learning" / "traces").mkdir(parents=True)
    (omh_home / "learning" / "traces" / "trace.json").write_text("{}", encoding="utf-8")
    (omh_home / "learning" / "candidates").mkdir(parents=True)
    (omh_home / "learning" / "candidates" / "candidate.json").write_text("{}", encoding="utf-8")
    (omh_home / "runtime" / "journal").mkdir(parents=True)
    (omh_home / "runtime" / "journal" / "events.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    (omh_home / "loops").mkdir(parents=True)
    (omh_home / "knowledge").mkdir(parents=True)
    (omh_home / "knowledge" / "index.json").write_text(
        json.dumps({"stores": [{"type": "markdown_folder"}]}),
        encoding="utf-8",
    )
