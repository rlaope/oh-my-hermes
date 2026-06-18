from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.menubar_status import build_menubar_status_payload, model_icon_descriptor, source_icon_descriptor
from omh.paths import resolve_paths
from omh.targets import record_target_observation


class MenubarStatusTests(unittest.TestCase):
    def test_menubar_status_keeps_hermes_agents_and_external_executors_separate(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)
            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "coding",
                    "delegate",
                    "--record",
                    "--executor",
                    "codex",
                    "--source",
                    "discord",
                    "--channel-ref",
                    "C123",
                    "Safely add feature without overclaiming.",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "menubar_status/v1")
            self.assertEqual(payload["display"]["menu_title"], "omh")
            self.assertEqual(payload["versions"]["omh"]["value"], "1.0.1")
            self.assertEqual(payload["versions"]["hermes"]["value"], "unknown")
            self.assertFalse(payload["versions"]["hermes"]["observed"])
            self.assertEqual(payload["settings"]["omh_connection"]["label"], "OMH connection: Ready")
            self.assertEqual(payload["settings"]["hermes_targets"]["label"], "Hermes targets: 1")
            self.assertEqual(payload["settings"]["coding_handoff"]["label"], "Coding handoff: Codex")
            self.assertEqual(payload["settings"]["send_mode"]["label"], "Send mode: Ask before opening Codex")
            menu_cards = payload["display"]["menu_cards"]
            self.assertEqual(
                [card["title"] for card in menu_cards],
                ["Connection", "Agent Status", "Coding Handoff", "Evidence"],
            )
            self.assertEqual(menu_cards[1]["columns"], ["Agent", "PID", "Status"])
            self.assertIn("PID is shown only after an observed runtime overlay.", menu_cards[1]["footer"])
            self.assertEqual(menu_cards[1]["rows"][0]["kind"], "agent_status")
            self.assertEqual(menu_cards[1]["rows"][0]["agent"], ".hermes")
            self.assertEqual(menu_cards[1]["rows"][0]["pid"], "not observed")
            self.assertEqual(menu_cards[1]["rows"][0]["status"], "Configured")
            self.assertNotIn("4312", json.dumps(menu_cards))
            self.assertEqual(menu_cards[2]["rows"][0]["label"], "Agent")
            self.assertEqual(menu_cards[2]["rows"][0]["value"], "Codex")

            hermes_agents = payload["hermes_agents"]
            self.assertEqual(len(hermes_agents), 1)
            self.assertEqual(hermes_agents[0]["kind"], "hermes_agent")
            self.assertTrue(hermes_agents[0]["is_hermes_agent"])
            self.assertEqual(hermes_agents[0]["status"], "configured")
            self.assertFalse(hermes_agents[0]["status_observed"])
            self.assertIsNone(hermes_agents[0]["pid"])
            self.assertFalse(hermes_agents[0]["pid_observed"])
            self.assertEqual(hermes_agents[0]["source"]["icon_id"], "source.local")
            self.assertEqual(hermes_agents[0]["model"]["icon_id"], "model.unknown")

            executors = payload["external_coding_executors"]
            self.assertEqual(len(executors), 1)
            self.assertEqual(executors[0]["kind"], "external_coding_executor")
            self.assertFalse(executors[0]["is_hermes_agent"])
            self.assertEqual(executors[0]["name"], "Codex")
            self.assertEqual(executors[0]["executor_profile"], "codex")
            self.assertEqual(executors[0]["status"], "prepared")
            self.assertFalse(executors[0]["status_observed"])
            self.assertIsNone(executors[0]["pid"])
            self.assertFalse(executors[0]["pid_observed"])
            self.assertEqual(executors[0]["source"]["icon_id"], "source.discord")
            self.assertEqual(executors[0]["source"]["tooltip"], "Discord: C123")
            self.assertEqual(executors[0]["model"]["icon_id"], "model.unknown")
            self.assertTrue(executors[0]["handoff"]["dispatchable"])
            self.assertEqual(executors[0]["handoff"]["dispatch_policy"], "ask_before_dispatch")
            self.assertEqual(executors[0]["evidence"]["state"], "prepared_not_observed")
            self.assertNotIn("Codex", [agent["name"] for agent in hermes_agents])
            current = payload["current_external_coding_executor"]
            self.assertTrue(current["selected"])
            self.assertEqual(current["selection_source"], "runtime_state.last_run_id")
            self.assertEqual(current["row_id"], executors[0]["id"])
            self.assertEqual(current["run_id"], executors[0]["evidence"]["run_id"])

    def test_process_overlay_applies_pid_status_and_model_only_when_fresh(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)
            self.assertEqual(
                run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "coding",
                        "delegate",
                        "--record",
                        "--executor",
                        "codex",
                        "--source",
                        "discord",
                        "--channel-ref",
                        "C123",
                        "Safely add feature without overclaiming.",
                    ]
                )[0],
                0,
            )
            base_status, base_stdout, _ = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status"]
            )
            self.assertEqual(base_status, 0)
            base = json.loads(base_stdout)
            run_id = base["external_coding_executors"][0]["evidence"]["run_id"]
            target_id = base["hermes_agents"][0]["id"]
            overlay_path = root / "overlay.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "schema_version": "menubar_process_overlay/v1",
                        "observed_at": "2026-06-18T00:00:00Z",
                        "ttl_seconds": 10,
                        "restart_window_seconds": 20,
                        "agents": [
                            {
                                "id": target_id,
                                "pid": 4312,
                                "status": "running",
                                "summary": "Hermes agent is serving Discord.",
                                "model": "gpt-5.5",
                            }
                        ],
                        "external_coding_executors": [
                            {
                                "executor_profile": "codex",
                                "run_id": run_id,
                                "pid": 9821,
                                "status": "restarting",
                                "summary": "Codex handoff window is reopening.",
                                "model": "gpt-5.5",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "menubar",
                    "status",
                    "--overlay",
                    str(overlay_path),
                    "--now",
                    "2026-06-18T00:00:05Z",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["process_overlay"]["status"], "applied")
            self.assertEqual(payload["process_overlay"]["applied_count"], 2)
            self.assertEqual(payload["hermes_agents"][0]["pid"], 4312)
            self.assertEqual(payload["hermes_agents"][0]["status"], "running")
            self.assertTrue(payload["hermes_agents"][0]["pid_observed"])
            self.assertTrue(payload["hermes_agents"][0]["status_observed"])
            self.assertEqual(payload["hermes_agents"][0]["model"]["icon_id"], "model.openai")
            self.assertEqual(payload["external_coding_executors"][0]["pid"], 9821)
            self.assertEqual(payload["external_coding_executors"][0]["status"], "restarting")
            self.assertTrue(payload["external_coding_executors"][0]["pid_observed"])
            self.assertTrue(payload["external_coding_executors"][0]["status_observed"])
            self.assertEqual(payload["external_coding_executors"][0]["model"]["tooltip"], "gpt-5.5")
            menu_cards = payload["display"]["menu_cards"]
            self.assertEqual(menu_cards[1]["rows"][0]["pid"], "4312")
            self.assertEqual(menu_cards[1]["rows"][0]["status"], "Running")
            self.assertEqual(menu_cards[2]["rows"][2]["label"], "PID")
            self.assertEqual(menu_cards[2]["rows"][2]["value"], "9821")

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "menubar",
                    "status",
                    "--overlay",
                    str(overlay_path),
                    "--now",
                    "2026-06-18T00:00:30Z",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            expired = json.loads(stdout)
            self.assertEqual(expired["process_overlay"]["status"], "expired")
            self.assertEqual(expired["process_overlay"]["applied_count"], 0)
            self.assertIsNone(expired["hermes_agents"][0]["pid"])
            self.assertEqual(expired["hermes_agents"][0]["status"], "configured")
            self.assertIsNone(expired["external_coding_executors"][0]["pid"])
            self.assertEqual(expired["external_coding_executors"][0]["status"], "prepared")

    def test_restart_overlay_expires_independently_inside_ttl(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")
            record_target_observation(paths, source="setup")
            target_id = build_menubar_status_payload(paths)["hermes_agents"][0]["id"]

            payload = build_menubar_status_payload(
                paths,
                process_overlay={
                    "schema_version": "menubar_process_overlay/v1",
                    "observed_at": "2026-06-18T00:00:00Z",
                    "ttl_seconds": 60,
                    "restart_window_seconds": 20,
                    "agents": [{"id": target_id, "pid": 4312, "status": "restarting"}],
                },
                now="2026-06-18T00:00:30Z",
            )

            self.assertEqual(payload["process_overlay"]["status"], "applied")
            self.assertEqual(payload["process_overlay"]["applied_count"], 0)
            self.assertEqual(payload["process_overlay"]["skipped_count"], 1)
            self.assertEqual(payload["process_overlay"]["skipped"][0]["reason"], "restart_window_expired")
            self.assertIsNone(payload["hermes_agents"][0]["pid"])
            self.assertEqual(payload["hermes_agents"][0]["status"], "configured")

    def test_invalid_overlay_now_is_reported_without_applying_process_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")
            record_target_observation(paths, source="setup")
            target_id = build_menubar_status_payload(paths)["hermes_agents"][0]["id"]

            payload = build_menubar_status_payload(
                paths,
                process_overlay={
                    "schema_version": "menubar_process_overlay/v1",
                    "observed_at": "2026-06-18T00:00:00Z",
                    "agents": [{"id": target_id, "pid": 4312, "status": "running"}],
                },
                now="not-a-time",
            )

            self.assertEqual(payload["process_overlay"]["status"], "invalid")
            self.assertIn("now must be an ISO timestamp", payload["process_overlay"]["errors"][0])
            self.assertIsNone(payload["hermes_agents"][0]["pid"])
            self.assertEqual(payload["hermes_agents"][0]["status"], "configured")

    def test_direct_overlay_schema_is_validated_before_applying_process_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")
            record_target_observation(paths, source="setup")
            target_id = build_menubar_status_payload(paths)["hermes_agents"][0]["id"]

            payload = build_menubar_status_payload(
                paths,
                process_overlay={
                    "schema_version": "wrong/v1",
                    "observed_at": "2026-06-18T00:00:00Z",
                    "agents": [{"id": target_id, "pid": 4312, "status": "running"}],
                },
                now="2026-06-18T00:00:05Z",
            )

            self.assertEqual(payload["process_overlay"]["status"], "invalid")
            self.assertIn("unsupported process overlay schema", payload["process_overlay"]["errors"][0])
            self.assertIsNone(payload["hermes_agents"][0]["pid"])
            self.assertEqual(payload["hermes_agents"][0]["status"], "configured")

    def test_external_executor_overlay_requires_run_identity_when_multiple_runs_exist(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)
            for message in ("First coding task.", "Second coding task."):
                self.assertEqual(
                    run_cli(
                        [
                            "--omh-home",
                            str(omh_home),
                            "--hermes-home",
                            str(hermes_home),
                            "coding",
                            "delegate",
                            "--record",
                            "--executor",
                            "codex",
                            "--source",
                            "discord",
                            "--channel-ref",
                            "C123",
                            message,
                        ]
                    )[0],
                    0,
                )
            paths = resolve_paths(omh_home, hermes_home)
            base = build_menubar_status_payload(paths, limit=5)
            self.assertEqual(len(base["external_coding_executors"]), 2)
            current = base["current_external_coding_executor"]
            self.assertTrue(current["selected"])
            self.assertEqual(current["selection_source"], "runtime_state.last_run_id")

            ambiguous = build_menubar_status_payload(
                paths,
                limit=5,
                process_overlay={
                    "schema_version": "menubar_process_overlay/v1",
                    "observed_at": "2026-06-18T00:00:00Z",
                    "external_coding_executors": [
                        {"executor_profile": "codex", "pid": 1111, "status": "running"}
                    ],
                },
                now="2026-06-18T00:00:05Z",
            )

            self.assertEqual(ambiguous["process_overlay"]["applied_count"], 0)
            self.assertEqual(ambiguous["process_overlay"]["skipped_count"], 1)
            self.assertEqual(ambiguous["process_overlay"]["skipped"][0]["reason"], "external_executor_run_id_required")
            self.assertTrue(all(row["pid"] is None for row in ambiguous["external_coding_executors"]))
            self.assertTrue(all(row["status"] == "prepared" for row in ambiguous["external_coding_executors"]))

            exact = build_menubar_status_payload(
                paths,
                limit=5,
                process_overlay={
                    "schema_version": "menubar_process_overlay/v1",
                    "observed_at": "2026-06-18T00:00:00Z",
                    "external_coding_executors": [
                        {
                            "executor_profile": "codex",
                            "run_id": current["run_id"],
                            "pid": 2222,
                            "status": "running",
                        }
                    ],
                },
                now="2026-06-18T00:00:05Z",
            )

            observed_rows = [row for row in exact["external_coding_executors"] if row["pid_observed"]]
            self.assertEqual(len(observed_rows), 1)
            self.assertEqual(observed_rows[0]["evidence"]["run_id"], current["run_id"])
            self.assertEqual(observed_rows[0]["pid"], 2222)
            self.assertEqual(exact["process_overlay"]["applied_count"], 1)

    def test_menubar_status_reports_multi_target_source_icons_without_process_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")
            record_target_observation(paths, source="setup")
            record_target_observation(
                paths,
                source="chat:slack",
                source_metadata={
                    "agent_ref": "agent-b",
                    "target_ref": "workspace-b",
                    "hermes_home": str(root / ".hermes-b"),
                    "agent_count": "2",
                },
            )

            payload = build_menubar_status_payload(paths)

            self.assertEqual(payload["settings"]["hermes_targets"]["value"], "multi:2")
            self.assertEqual(payload["settings"]["hermes_targets"]["label"], "Hermes targets: 2")
            self.assertEqual(len(payload["hermes_agents"]), 2)
            slack_rows = [row for row in payload["hermes_agents"] if row["source"]["icon_id"] == "source.slack"]
            self.assertEqual(len(slack_rows), 1)
            self.assertEqual(slack_rows[0]["source"]["tooltip"], "Slack: workspace-b")
            self.assertEqual(slack_rows[0]["status"], "configured")
            self.assertFalse(slack_rows[0]["status_observed"])
            self.assertIsNone(slack_rows[0]["pid"])
            self.assertFalse(slack_rows[0]["pid_observed"])

    def test_icon_descriptors_keep_logo_ids_and_tooltips_separate(self) -> None:
        self.assertEqual(source_icon_descriptor("chat:telegram", channel_ref="room-7")["icon_id"], "source.telegram")
        self.assertEqual(source_icon_descriptor("chat:telegram", channel_ref="room-7")["tooltip"], "Telegram: room-7")
        self.assertEqual(source_icon_descriptor("signal")["icon_id"], "source.signal")
        self.assertEqual(source_icon_descriptor("whatsapp")["icon_id"], "source.whatsapp")
        self.assertEqual(model_icon_descriptor("gpt-5.5")["icon_id"], "model.openai")
        self.assertEqual(model_icon_descriptor("claude-sonnet")["icon_id"], "model.anthropic")
        self.assertEqual(model_icon_descriptor("gemini-3")["icon_id"], "model.google")
        self.assertEqual(model_icon_descriptor("ollama/llama")["icon_id"], "model.local")


if __name__ == "__main__":
    unittest.main()
