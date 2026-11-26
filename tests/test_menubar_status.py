from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.cli import build_parser
from omh.menubar_status import build_menubar_status_payload, model_icon_descriptor, source_icon_descriptor
from omh.paths import resolve_paths
from omh.surfaces.hermes_model_settings import HERMES_AUX_ALIASES
from omh.surfaces.hermes_sessions import hermes_state_watch_paths
from omh.surfaces.menubar_status import _display, _models_card, _sessions_card, menubar_watch_paths
from omh.targets import record_target_observation


class MenubarStatusTests(unittest.TestCase):
    def test_menu_bar_title_is_count_only_when_processes_and_sessions_are_observed(self) -> None:
        display = _display(
            {"omh_connection": {"value": "ready"}},
            {"observed": True, "agent_count": 2, "process_count": 3},
            {"observed": True, "live": 1, "total": 4},
            {},
            {},
        )

        self.assertEqual(display["menu_bar_title"], "2·1")
        self.assertNotIn("omh ✓", display["menu_bar_title"])

    def test_menu_bar_title_uses_only_attention_mark_when_connection_is_not_ready(self) -> None:
        display = _display(
            {"omh_connection": {"value": "stale"}},
            {"observed": True, "agent_count": 2, "process_count": 3},
            {"observed": True, "live": 1, "total": 4},
            {},
            {},
        )

        self.assertEqual(display["menu_bar_title"], "!")
        self.assertNotIn("omh ✓", display["menu_bar_title"])

    def test_ready_menu_bar_title_is_empty_until_both_observations_exist(self) -> None:
        for processes_observed, sessions_observed in ((False, False), (True, False), (False, True)):
            with self.subTest(
                processes_observed=processes_observed,
                sessions_observed=sessions_observed,
            ):
                display = _display(
                    {"omh_connection": {"value": "ready"}},
                    {"observed": processes_observed, "agent_count": 2, "process_count": 3},
                    {"observed": sessions_observed, "live": 1, "total": 4},
                    {},
                    {},
                )

                self.assertEqual(display["menu_bar_title"], "")
                self.assertNotIn("omh ✓", display["menu_bar_title"])

    def test_menubar_status_help_advertises_current_payload_schema(self) -> None:
        stdout = io.StringIO()

        with patch("sys.stdout", stdout), self.assertRaises(SystemExit) as exit_context:
            build_parser().parse_args(["menubar", "status", "--help"])

        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("Print the full menubar_status/v2 payload.", " ".join(stdout.getvalue().split()))
        self.assertNotIn("menubar_status/v1", stdout.getvalue())

    def test_long_model_is_bounded_in_human_output_but_preserved_in_payload(self) -> None:
        long_model = "provider/" + "model-segment-" * 6
        expected_display = long_model[:45] + "..."
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)
            self._seed_hermes_observers(hermes_home)
            connection = sqlite3.connect(hermes_home / "state.db")
            connection.execute(
                "update sessions set model = ?, model_config = '{}' where ended_at is null",
                (long_model,),
            )
            connection.commit()
            connection.close()

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status"],
                output_json=False,
            )

            self.assertEqual((status, stderr), (0, ""))
            current_line = next(line for line in stdout.splitlines() if line.startswith("  current"))
            self.assertEqual(current_line, f"  {'current'.ljust(20)} {expected_display}")
            self.assertEqual(len(current_line.rsplit(" ", 1)[-1]), 48)
            self.assertNotIn(long_model, stdout)
            self.assertTrue(
                stdout.endswith(
                    "Observation\n"
                    "  Process overlay: not supplied\n"
                    "  Boundary: configured targets are not PID evidence unless observed by the helper.\n\n"
                    "For machine-readable output, rerun with `--json`.\n"
                )
            )

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status", "--json"],
                output_json=False,
            )

            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            current_row = next(row for row in payload["display"]["menu_cards"][1]["rows"] if row["left"] == "current")
            self.assertEqual(current_row["right"], long_model)

    def test_sessions_card_shows_idle_open_rows_apart_from_live(self) -> None:
        # The owner's menu bar read "live 53" for two days: 53 rows Hermes
        # never closed, none touched since. Idle rows get their own line and
        # never inflate `live`; the footer says what live means.
        card = _sessions_card({"observed": True, "live": 1, "open": 54, "stale": 53, "total": 642, "live_window_seconds": 900})
        self.assertEqual(
            [(row["left"], row["right"], row["tone"]) for row in card["rows"]],
            [("live", "1", "ok"), ("open, idle", "53", "neutral"), ("total", "642", "ok")],
        )
        self.assertEqual(card["footer"], "live = activity within 15 min · Hermes state.db (read-only)")
        quiet = _sessions_card({"observed": True, "live": 0, "open": 0, "stale": 0, "total": 2, "live_window_seconds": 900})
        self.assertEqual([row["left"] for row in quiet["rows"]], ["live", "total"])

    def test_summary_line_pluralizes_agents_and_processes(self) -> None:
        one = _display(
            {"omh_connection": {"value": "ready"}},
            {"observed": True, "agent_count": 1, "process_count": 1},
            {"observed": True, "live": 0, "total": 4},
            {},
            {},
        )
        self.assertEqual(one["summary_line"], "1 agent · 1 process · sessions live 0 / total 4")
        many = _display(
            {"omh_connection": {"value": "ready"}},
            {"observed": True, "agent_count": 2, "process_count": 3},
            {"observed": True, "live": 1, "total": 4},
            {},
            {},
        )
        self.assertEqual(many["summary_line"], "2 agents · 3 processes · sessions live 1 / total 4")

    def test_models_card_lists_the_delegation_model_after_main(self) -> None:
        card = _models_card(
            {"current_model": {"observed": False}},
            {
                "aliases": [{"alias": "main", "configured": True, "label": "gpt-5.6-sol:medium"}],
                "delegation": {"alias": "delegation", "configured": True, "label": "gpt-6-astra:high"},
            },
        )
        self.assertEqual(
            [(row["left"], row["right"]) for row in card["rows"]],
            [("main", "gpt-5.6-sol:medium"), ("delegation", "gpt-6-astra:high")],
        )
        self.assertEqual(card["footer"], "current = live session · main/delegation/aux = config.yaml")

    def test_models_card_reserves_final_row_for_inherited_auxiliary_summary(self) -> None:
        card = _models_card(
            {"current_model": {"observed": True, "label": "current-model"}},
            {
                "aliases": [
                    {"alias": "main", "configured": True, "label": "main-model"},
                    {"alias": "vision", "configured": True, "label": "vision-model"},
                    {"alias": "compression", "configured": True, "label": "compression-model"},
                    {"alias": "monitor", "configured": True, "label": "monitor-model"},
                    *[
                        {"alias": alias, "configured": False, "label": "inherit"}
                        for alias in (
                            "skills_hub",
                            "approval",
                            "mcp",
                            "title_generation",
                            "memory_query_rewrite",
                            "tts_audio_tags",
                            "triage_specifier",
                            "kanban_decomposer",
                            "profile_describer",
                            "goal_judge",
                            "curator",
                        )
                    ],
                ],
                "inherit_count": 11,
            },
        )

        self.assertEqual(
            [(row["left"], row["right"]) for row in card["rows"]],
            [
                ("current", "current-model"),
                ("main", "main-model"),
                ("vision", "vision-model"),
                ("compression", "compression-model"),
                ("+11 aliases", "inherit default"),
            ],
        )

    def test_models_card_excludes_separately_rendered_main_from_inherited_auxiliary_count(self) -> None:
        card = _models_card(
            {"current_model": {"observed": True, "label": "current-model"}},
            {
                "aliases": [
                    {"alias": "main", "configured": False, "label": "inherit"},
                    *[
                        {"alias": alias, "configured": False, "label": "inherit"}
                        for alias in HERMES_AUX_ALIASES
                    ],
                ],
                "inherit_count": len(HERMES_AUX_ALIASES) + 1,
            },
        )

        self.assertEqual(
            [(row["left"], row["right"]) for row in card["rows"]],
            [
                ("current", "current-model"),
                ("main", "inherit"),
                (f"+{len(HERMES_AUX_ALIASES)} aliases", "inherit default"),
            ],
        )

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
                    "implement safe status feature in src/omh/runtime/status.py without overclaiming",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)

            self._seed_hermes_observers(hermes_home)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "menubar_status/v2")
            self.assertEqual(payload["display"]["menu_title"], "omh")
            from omh.version import __version__ as omh_version

            self.assertEqual(payload["versions"]["omh"]["value"], omh_version)
            self.assertEqual(payload["versions"]["hermes"]["value"], "unknown")
            self.assertFalse(payload["versions"]["hermes"]["observed"])
            self.assertEqual(payload["settings"]["omh_connection"]["label"], "OMH connection: Ready")
            self.assertEqual(payload["settings"]["hermes_targets"]["label"], "Hermes targets: 1")
            self.assertEqual(payload["settings"]["coding_handoff"]["label"], "Coding agent: Codex")
            self.assertEqual(payload["settings"]["send_mode"]["label"], "Open mode: Ask before opening Codex")
            menu_cards = payload["display"]["menu_cards"]
            self.assertEqual(
                [card["title"] for card in menu_cards],
                ["Sessions", "Models", ""],
            )
            self.assertEqual(menu_cards[0]["columns"], ["Hermes session", "Count"])
            self.assertEqual(
                menu_cards[0]["rows"],
                [
                    {"kind": "table_row", "left": "live", "right": "1", "tone": "ok"},
                    {"kind": "table_row", "left": "total", "right": "2", "tone": "ok"},
                ],
            )
            self.assertNotIn("tui", [row["left"] for row in menu_cards[0]["rows"]])
            self.assertEqual(menu_cards[1]["columns"], ["Alias", "Model"])
            self.assertEqual(
                [(row["left"], row["right"]) for row in menu_cards[1]["rows"]],
                [
                    ("current", "gpt-5.6-sol:medium"),
                    ("main", "anthropic/claude-opus-4.6:medium"),
                    ("vision", "google/gemini-2.5-pro"),
                    ("approval", "google/gemini-2.5-flash"),
                    (f"+{len(HERMES_AUX_ALIASES) - 2} aliases", "inherit default"),
                ],
            )
            self.assertEqual(
                menu_cards[2]["rows"],
                [{"label": "coding", "value": "Codex", "detail": "metadata only"}],
            )
            self.assertFalse(any(row.get("kind") == "agent_status" for card in menu_cards for row in card["rows"]))
            self.assertEqual(payload["hermes_processes"]["reason"], "not_requested")
            self.assertTrue(payload["hermes_sessions"]["observed"])
            self.assertTrue(payload["model_settings"]["observed"])
            self.assertTrue(
                {
                    "hermes_agents", "external_coding_executors", "current_external_coding_executor",
                    "settings", "versions", "process_overlay", "icon_contract", "privacy",
                }.issubset(payload)
            )

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
            self.assertEqual(executors[0]["evidence"]["next_action"], "dispatch_to_executor")
            self.assertEqual(
                executors[0]["evidence"]["next_action_label"],
                "dispatching to the selected coding agent",
            )
            self.assertNotIn("Codex", [agent["name"] for agent in hermes_agents])
            current = payload["current_external_coding_executor"]
            self.assertTrue(current["selected"])
            self.assertEqual(current["selection_source"], "runtime_state.last_run_id")
            self.assertEqual(current["row_id"], executors[0]["id"])
            self.assertEqual(current["run_id"], executors[0]["evidence"]["run_id"])

    def test_menubar_status_no_run_state_is_executor_neutral(self) -> None:
        # Safety-first setup deliberately records "choose" (no upfront
        # coding-owner question). The no-run status must be led by Hermes/OMH
        # readiness and the next request route, not by an idle coding agent
        # named "choose"/"ask". See docs/INSTALLATION.md "Status model:
        # no-run, prepared-handoff, observed-run".
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["settings"]["coding_handoff"]["label"], "Coding agent: Not selected")
            self.assertEqual(payload["settings"]["coding_handoff"]["source"], "none")
            self.assertFalse(payload["current_external_coding_executor"]["selected"])
            self.assertEqual(payload["display"]["summary_line"], "sessions not observed")
            footer = payload["display"]["menu_cards"][2]
            self.assertEqual(footer["rows"], [{"label": "coding", "value": "Not selected", "detail": "metadata only"}])

    def test_menubar_status_shows_recorded_preference_without_a_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(
                run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--default-executor",
                        "codex",
                    ]
                )[0],
                0,
            )

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["settings"]["coding_handoff"]["label"], "Coding agent: Codex")
            self.assertEqual(payload["settings"]["coding_handoff"]["source"], "user_preference")
            self.assertFalse(payload["current_external_coding_executor"]["selected"])
            footer = payload["display"]["menu_cards"][2]
            self.assertEqual(footer["rows"], [{"label": "coding", "value": "Codex", "detail": "metadata only"}])

    def test_menubar_status_defaults_to_human_readable_output(self) -> None:
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
                        "implement safe status feature without overclaiming",
                    ]
                )[0],
                0,
            )
            self._seed_hermes_observers(hermes_home)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status"],
                output_json=False,
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertTrue(stdout.startswith("OMH menu bar status\n"))
            self.assertIn("Summary\n", stdout)
            self.assertIn("  Sessions: live 1 / total 2\n", stdout)
            self.assertIn("  Processes: not observed\n", stdout)
            self.assertIn("Sessions\n  Hermes session       Count\n  live                 1\n  total                2\n", stdout)
            self.assertIn(
                "Models\n"
                "  Alias                Model\n"
                "  current              gpt-5.6-sol:medium\n"
                "  main                 anthropic/claude-opus-4.6:medium\n",
                stdout,
            )
            self.assertNotIn("Agent Status", stdout)
            self.assertIn("Coding agent: Codex", stdout)
            self.assertIn("For machine-readable output, rerun with `--json`.", stdout)
            with self.assertRaises(json.JSONDecodeError):
                json.loads(stdout)

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "menubar", "status", "--json"],
                output_json=False,
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "menubar_status/v2")
            self.assertEqual(payload["settings"]["coding_handoff"]["label"], "Coding agent: Codex")

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
                        "implement safe status feature in src/omh/runtime/status.py without overclaiming",
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
            self.assertEqual([card["title"] for card in payload["display"]["menu_cards"]], ["Sessions", "Models", ""])

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
            for message in (
                "implement first coding task in src/omh/runtime/first.py",
                "implement second coding task in src/omh/runtime/second.py",
            ):
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

    def test_local_process_observation_applies_real_hermes_pid_without_false_path_matches(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")
            record_target_observation(paths, source="setup")

            ps_output = "\n".join(
                [
                    " 101 1 /Applications/Codex.app/Contents/MacOS/Codex /Users/demo/code/hermes-agent",
                    " 22064 1 /Users/demo/.hermes/hermes-agent/venv/bin/python /Users/demo/.hermes/hermes-agent/hermes",
                    " 22065 22064 /opt/homebrew/bin/node --expose-gc /Users/demo/.hermes/hermes-agent/ui-tui/dist/entry.js",
                ]
            )

            with patch(
                "omh.surfaces.hermes_processes.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["ps"],
                    returncode=0,
                    stdout=ps_output,
                    stderr="",
                ),
            ) as run:
                payload = build_menubar_status_payload(
                    paths,
                    observe_local_processes=True,
                    now="2026-06-18T00:00:05Z",
                )

            self.assertEqual(payload["process_overlay"]["status"], "applied")
            self.assertEqual(payload["process_overlay"]["applied_count"], 1)
            self.assertEqual(payload["hermes_agents"][0]["pid"], 22064)
            self.assertEqual(payload["hermes_agents"][0]["status"], "running")
            self.assertTrue(payload["hermes_agents"][0]["pid_observed"])
            self.assertEqual(payload["hermes_processes"]["agent_count"], 1)
            self.assertEqual(payload["hermes_processes"]["process_count"], 2)
            run.assert_called_once()

    def test_empty_hermes_home_degrades_and_plain_status_never_scans_processes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            paths.hermes_home.mkdir()
            with patch("omh.surfaces.hermes_processes.subprocess.run") as run:
                payload = build_menubar_status_payload(paths)
            run.assert_not_called()
            self.assertEqual(payload["hermes_processes"]["reason"], "not_requested")
            self.assertFalse(payload["hermes_sessions"]["observed"])
            sessions_card = payload["display"]["menu_cards"][0]
            self.assertEqual(sessions_card["columns"], ["Hermes session", "Count"])
            self.assertEqual(sessions_card["rows"], [{"kind": "table_row", "left": "sessions", "right": "not observed"}])
            self.assertEqual(sessions_card["footer"], "state_db_missing")
            self.assertFalse(any(row.get("kind") == "agent_status" for card in payload["display"]["menu_cards"] for row in card["rows"]))

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

    def test_watch_paths_name_the_wal_sidecar_not_only_the_database(self) -> None:
        # Hermes runs state.db in WAL mode, so an ordinary session write
        # lands in the sidecar and leaves the database's own mtime where it
        # was until a checkpoint. A poller that stats only the database is
        # blind for exactly the window it exists to cover.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            paths.hermes_home.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(paths.hermes_home / "state.db")
            connection.execute("pragma journal_mode=wal")
            connection.execute("create table probe (value integer)")
            connection.commit()
            database = paths.hermes_home / "state.db"
            before = database.stat().st_mtime_ns
            connection.execute("insert into probe values (1)")
            connection.commit()
            after = database.stat().st_mtime_ns
            connection.close()

            payload = build_menubar_status_payload(paths)

        watch_paths = payload["watch_paths"]
        self.assertEqual(before, after, "this test is pointless if a WAL write does move the database mtime")
        self.assertEqual(
            watch_paths,
            [str(database), str(database) + "-wal"],
        )
        for candidate in watch_paths:
            self.assertTrue(Path(candidate).is_absolute())

    def test_watch_paths_are_derived_from_the_reader_that_opens_them(self) -> None:
        # Not a hand-kept list: the producer and the session reader call the
        # same expression, so renaming the store cannot leave a watcher
        # pointing at a path nothing reads.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")

            derived = menubar_watch_paths(paths)
            from_reader = [str(path) for path in hermes_state_watch_paths(paths)]
            payload = build_menubar_status_payload(paths)

        self.assertEqual(derived, from_reader)
        self.assertEqual(payload["watch_paths"], from_reader)
        self.assertIn(str(paths.hermes_home), from_reader[0])

    def test_icon_descriptors_keep_logo_ids_and_tooltips_separate(self) -> None:
        self.assertEqual(source_icon_descriptor("chat:telegram", channel_ref="room-7")["icon_id"], "source.telegram")
        self.assertEqual(source_icon_descriptor("chat:telegram", channel_ref="room-7")["tooltip"], "Telegram: room-7")
        self.assertEqual(source_icon_descriptor("signal")["icon_id"], "source.signal")
        self.assertEqual(source_icon_descriptor("whatsapp")["icon_id"], "source.whatsapp")
        self.assertEqual(model_icon_descriptor("gpt-5.5")["icon_id"], "model.openai")
        self.assertEqual(model_icon_descriptor("claude-sonnet")["icon_id"], "model.anthropic")
        self.assertEqual(model_icon_descriptor("gemini-3")["icon_id"], "model.google")
        self.assertEqual(model_icon_descriptor("ollama/llama")["icon_id"], "model.local")

    @staticmethod
    def _seed_hermes_observers(hermes_home: Path) -> None:
        hermes_home.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(hermes_home / "state.db")
        connection.execute(
            """create table sessions (
                source text, model text, model_config text, ended_at text,
                archived integer not null, hidden integer not null,
                started_at text, last_activity_at text
            )"""
        )
        current_config = json.dumps({"provider": "openai-codex", "reasoning_config": {"effort": "medium"}})
        # Hermes stores REAL epoch seconds; the open row was touched just now
        # so it counts as live under the real clock the CLI path runs on.
        now = time.time()
        connection.executemany(
            "insert into sessions values (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("tui", "gpt-5.6-sol", current_config, None, 0, 0, now - 600, now - 30),
                ("api", "older", "{}", now - 86_400, 0, 0, now - 90_000, now - 86_400),
            ],
        )
        connection.commit()
        connection.close()
        (hermes_home / "config.yaml").write_text(
            """model:
  default: anthropic/claude-opus-4.6
  provider: auto
agent:
  reasoning_effort: medium
auxiliary:
  approval:
    model: google/gemini-2.5-flash
  vision:
    model: google/gemini-2.5-pro
""",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
