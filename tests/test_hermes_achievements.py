from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.paths import OmhPaths
from omh.workflows.hermes_achievements import (
    filter_badges,
    find_badge,
    observe_achievements,
    render_achievements_markdown,
)


class HermesAchievementsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.omh_home = root / "omh"
        self.hermes_home = root / "hermes"
        self.plugin_dir = self.hermes_home / "plugins" / "hermes-achievements"
        self.paths = OmhPaths(omh_home=self.omh_home, hermes_home=self.hermes_home)

    def _write_plugin_file(self, name: str, data: object) -> None:
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        (self.plugin_dir / name).write_text(json.dumps(data), encoding="utf-8")

    def _base_args(self) -> list[str]:
        return ["--omh-home", str(self.omh_home), "--hermes-home", str(self.hermes_home)]

    def _write_list_shaped_artifacts(self) -> None:
        self._write_plugin_file(
            "scan_snapshot.json",
            {
                "completed_at": "2026-07-01T10:00:00Z",
                "achievements": [
                    {
                        "id": "red-text",
                        "name": "Red Text Connoisseur",
                        "tier": "gold",
                        "category": "debugging",
                        "state": "unlocked",
                        "progress": 1.0,
                        "unlocked_at": "2026-06-30T09:00:00Z",
                    },
                    {
                        "id": "let-him-cook",
                        "name": "Let Him Cook",
                        "tier": "silver",
                        "category": "toolchain",
                        "state": "discovered",
                        "progress": {"current": 3, "target": 10},
                    },
                    {
                        "id": "night-owl",
                        "name": "Night Owl",
                        "category": "lifestyle",
                        "secret": True,
                    },
                ],
            },
        )
        self._write_plugin_file(
            "state.json",
            {
                "unlocked": {
                    "red-text": {"unlocked_at": "2026-06-30T09:00:00Z", "tier": "gold"},
                    "weekend-warrior": {
                        "name": "Weekend Warrior",
                        "tier": "copper",
                        "category": "lifestyle",
                        "unlocked_at": "2026-07-02T08:00:00Z",
                    },
                }
            },
        )


class ObserveAchievementsTests(HermesAchievementsTestCase):
    def test_missing_artifacts_report_not_observed(self) -> None:
        payload = observe_achievements(self.paths)

        self.assertEqual(payload["status"], "not_observed")
        self.assertFalse(payload["observed"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["badges"], [])
        self.assertEqual(payload["summary"]["unlocked_count"], 0)
        self.assertEqual(payload["summary"]["total_count"], 0)
        self.assertEqual(payload["privacy"], "metadata_only")

    def test_list_shaped_snapshot_merges_state_unlocks(self) -> None:
        self._write_list_shaped_artifacts()

        payload = observe_achievements(self.paths)

        self.assertEqual(payload["status"], "observed")
        self.assertEqual(payload["errors"], [])
        summary = payload["summary"]
        self.assertEqual(summary["total_count"], 4)
        self.assertEqual(summary["unlocked_count"], 2)
        self.assertEqual(summary["discovered_count"], 1)
        self.assertEqual(summary["secret_count"], 1)
        self.assertEqual(summary["top_tier"], "gold")
        self.assertEqual(summary["last_scan_at"], "2026-07-01T10:00:00Z")
        self.assertEqual(
            summary["categories"],
            [
                {"category": "debugging", "total": 1, "unlocked": 1},
                {"category": "lifestyle", "total": 2, "unlocked": 1},
                {"category": "toolchain", "total": 1, "unlocked": 0},
            ],
        )
        recent_ids = [badge["badge_id"] for badge in payload["recent_unlocks"]]
        self.assertEqual(recent_ids, ["weekend-warrior", "red-text"])
        in_progress = find_badge(payload["badges"], "let-him-cook")
        self.assertIsNotNone(in_progress)
        self.assertEqual(in_progress["progress_percent"], 30.0)

    def test_dict_shaped_snapshot_and_list_shaped_state(self) -> None:
        self._write_plugin_file(
            "scan_snapshot.json",
            {
                "badges": {
                    "toolchain-maxxer": {"title": "Toolchain Maxxer", "tier": "diamond", "group": "toolchain"},
                    "claude-confidant": {"title": "Claude Confidant", "group": "models", "unlocked": True},
                }
            },
        )
        self._write_plugin_file("state.json", {"unlocked": ["toolchain-maxxer"]})

        payload = observe_achievements(self.paths)

        self.assertEqual(payload["summary"]["total_count"], 2)
        self.assertEqual(payload["summary"]["unlocked_count"], 2)
        self.assertEqual(payload["summary"]["top_tier"], "diamond")
        badge = find_badge(payload["badges"], "toolchain-maxxer")
        self.assertEqual(badge["name"], "Toolchain Maxxer")
        self.assertEqual(badge["state"], "unlocked")

    def test_corrupt_snapshot_degrades_to_state_only_observation(self) -> None:
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        (self.plugin_dir / "scan_snapshot.json").write_text("{not json", encoding="utf-8")
        self._write_plugin_file("state.json", {"unlocked": {"red-text": {"tier": "gold"}}})

        payload = observe_achievements(self.paths)

        self.assertEqual(payload["status"], "observed")
        self.assertFalse(payload["source"]["snapshot_observed"])
        self.assertTrue(payload["source"]["state_observed"])
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("scan_snapshot.json", payload["errors"][0])
        self.assertEqual(payload["summary"]["unlocked_count"], 1)

    def test_unknown_shapes_degrade_without_raising(self) -> None:
        self._write_plugin_file("scan_snapshot.json", {"achievements": "not-a-collection", "extra": 5})
        self._write_plugin_file("state.json", {"unlocked": 7})

        payload = observe_achievements(self.paths)

        self.assertEqual(payload["status"], "observed")
        self.assertEqual(payload["badges"], [])
        self.assertEqual(payload["summary"]["unlocked_count"], 0)

    def test_filter_badges_by_category_state_and_limit(self) -> None:
        self._write_list_shaped_artifacts()
        badges = observe_achievements(self.paths)["badges"]

        lifestyle = filter_badges(badges, category="lifestyle")
        self.assertEqual({badge["badge_id"] for badge in lifestyle}, {"night-owl", "weekend-warrior"})
        unlocked = filter_badges(badges, state="unlocked")
        self.assertEqual({badge["badge_id"] for badge in unlocked}, {"red-text", "weekend-warrior"})
        self.assertEqual(len(filter_badges(badges, limit=2)), 2)

    def test_markdown_projection_is_deterministic_metadata_only(self) -> None:
        self._write_list_shaped_artifacts()
        payload = observe_achievements(self.paths)
        payload["generated_at"] = "2026-07-04T00:00:00Z"

        first = render_achievements_markdown(payload)
        second = render_achievements_markdown(payload)

        self.assertEqual(first, second)
        self.assertIn("# Hermes Achievements (OMH observation)", first)
        self.assertIn("- Unlocked: 2 / 4", first)
        self.assertIn("## debugging", first)
        self.assertIn("| Badge | Tier | State | Progress | Unlocked at |", first)
        self.assertIn("Red Text Connoisseur (`red-text`)", first)
        self.assertIn("Boundary:", first)


class AgentProfileTests(HermesAchievementsTestCase):
    def test_profile_derived_from_observed_badges(self) -> None:
        self._write_list_shaped_artifacts()

        profile = observe_achievements(self.paths)["agent_profile"]

        self.assertEqual(profile["schema_version"], "hermes_achievements_agent_profile/v1")
        self.assertTrue(profile["observed"])
        self.assertEqual(profile["derivation"], "derived_from_observed_badges")
        self.assertEqual(profile["strengths"], ["debugging", "lifestyle"])
        self.assertEqual(profile["gaps"], ["toolchain"])
        self.assertEqual(profile["top_tier"], "gold")
        self.assertFalse(profile["source"]["agent_summary_observed"])

    def test_upstream_agent_summary_takes_precedence(self) -> None:
        self._write_list_shaped_artifacts()
        self._write_plugin_file(
            "agent_summary.json",
            {
                "strengths": ["autonomous toolchains", "error recovery"],
                "gaps": ["skill usage", "model variety"],
                "top_tier": "diamond",
                "unlocked_count": 12,
                "total_count": 60,
            },
        )

        profile = observe_achievements(self.paths)["agent_profile"]

        self.assertEqual(profile["derivation"], "upstream_agent_summary")
        self.assertEqual(profile["strengths"], ["autonomous toolchains", "error recovery"])
        self.assertEqual(profile["gaps"], ["skill usage", "model variety"])
        self.assertEqual(profile["top_tier"], "diamond")
        self.assertEqual(profile["unlocked_count"], 12)
        self.assertEqual(profile["total_count"], 60)
        self.assertTrue(profile["source"]["agent_summary_observed"])

    def test_profile_without_artifacts_is_unobserved(self) -> None:
        profile = observe_achievements(self.paths)["agent_profile"]

        self.assertFalse(profile["observed"])
        self.assertEqual(profile["derivation"], "none")
        self.assertEqual(profile["strengths"], [])
        self.assertEqual(profile["gaps"], [])


class ContextBriefInjectionTests(HermesAchievementsTestCase):
    def test_context_brief_includes_profile_when_observed(self) -> None:
        self._write_list_shaped_artifacts()

        status, stdout, stderr = run_cli([*self._base_args(), "context", "brief", "--json"])

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        profile = payload["achievements_profile"]
        self.assertEqual(profile["derivation"], "derived_from_observed_badges")
        self.assertEqual(profile["gaps"], ["toolchain"])
        self.assertIn("advisory", profile["routing_rule"])

    def test_context_brief_omits_profile_without_artifacts(self) -> None:
        status, stdout, stderr = run_cli([*self._base_args(), "context", "brief", "--json"])

        self.assertEqual(status, 0, stderr)
        self.assertNotIn("achievements_profile", json.loads(stdout))


class AchievementsCapabilityTests(HermesAchievementsTestCase):
    def test_capability_section_lists_achievement_evidence(self) -> None:
        status, stdout, stderr = run_cli(["capabilities", "list", "--section", "achievement_evidence", "--json"])

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        sections = {section["section"]: section["ids"] for section in payload["sections"]}
        self.assertEqual(sections["achievement_evidence"], ["hermes_achievements_observation"])

    def test_capability_inspect_returns_contract(self) -> None:
        status, stdout, stderr = run_cli(
            ["capabilities", "inspect", "hermes_achievements_observation", "--section", "achievements", "--json"]
        )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        capability = payload["capability"]
        self.assertEqual(capability["schema_version"], "achievement_evidence_contract/v1")
        self.assertEqual(capability["claim_kind"], "observed_badge_metadata")
        self.assertIn("productivity", capability["not_evidence_for"])


class AchievementsRoutingTests(HermesAchievementsTestCase):
    def test_route_hint_matches_badge_questions(self) -> None:
        status, stdout, stderr = run_cli(["chat", "route-hint", "show my unlocked badges", "--json"])

        self.assertEqual(status, 0, stderr)
        self.assertIn('"workflow": "achievements"', stdout)


class AchievementsCliTests(HermesAchievementsTestCase):
    def test_summary_json_reports_not_observed_without_artifacts(self) -> None:
        status, stdout, stderr = run_cli([*self._base_args(), "achievements", "summary", "--json"])

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "hermes_achievements_observation/v1")
        self.assertEqual(payload["status"], "not_observed")

    def test_summary_text_prints_unlocks_and_boundary(self) -> None:
        self._write_list_shaped_artifacts()

        status, stdout, stderr = run_cli([*self._base_args(), "achievements", "summary"], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertIn("Unlocked: 2 / 4", stdout)
        self.assertIn("Top tier: gold", stdout)
        self.assertIn("Weekend Warrior", stdout)
        self.assertIn("Boundary:", stdout)

    def test_list_applies_filters(self) -> None:
        self._write_list_shaped_artifacts()

        status, stdout, stderr = run_cli(
            [*self._base_args(), "achievements", "list", "--state", "unlocked", "--json"]
        )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            {badge["badge_id"] for badge in payload["badges"]},
            {"red-text", "weekend-warrior"},
        )

    def test_show_returns_badge_and_fails_cleanly_when_missing(self) -> None:
        self._write_list_shaped_artifacts()

        status, stdout, stderr = run_cli([*self._base_args(), "achievements", "show", "red-text", "--json"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["badge"]["tier"], "gold")

        status, _, stderr = run_cli([*self._base_args(), "achievements", "show", "no-such-badge", "--json"])
        self.assertEqual(status, 2)
        self.assertIn("badge not found", stderr)

    def test_export_writes_markdown_file(self) -> None:
        self._write_list_shaped_artifacts()
        out_path = Path(self._tmp.name) / "achievements.md"

        status, stdout, stderr = run_cli(
            [*self._base_args(), "achievements", "export", "--format", "md", "--out", str(out_path), "--json"]
        )

        self.assertEqual(status, 0, stderr)
        receipt = json.loads(stdout)
        self.assertEqual(receipt["written_path"], str(out_path))
        content = out_path.read_text(encoding="utf-8")
        self.assertIn("# Hermes Achievements (OMH observation)", content)
        self.assertIn("Boundary:", content)

    def test_export_json_stdout_parses(self) -> None:
        self._write_list_shaped_artifacts()

        status, stdout, stderr = run_cli(
            [*self._base_args(), "achievements", "export", "--format", "json"], output_json=False
        )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["unlocked_count"], 2)


class AchievementsHudTests(HermesAchievementsTestCase):
    def test_full_preset_hud_includes_achievements_segment(self) -> None:
        self._write_list_shaped_artifacts()

        status, stdout, stderr = run_cli([*self._base_args(), "hud", "--preset", "full", "--json"])

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["achievements"]["observed"])
        self.assertEqual(payload["achievements"]["unlocked_count"], 2)
        self.assertEqual(payload["achievements"]["total_count"], 3)
        self.assertIn("ach:2/3", payload["display"]["segments"])

    def test_focused_preset_hud_omits_achievements_segment(self) -> None:
        self._write_list_shaped_artifacts()

        status, stdout, stderr = run_cli([*self._base_args(), "hud", "--json"])

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertNotIn("ach:2/3", payload["display"]["segments"])

    def test_hud_without_artifacts_reports_unobserved_achievements(self) -> None:
        status, stdout, stderr = run_cli([*self._base_args(), "hud", "--preset", "full", "--json"])

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertFalse(payload["achievements"]["observed"])
        self.assertNotIn("ach:", payload["display"]["line"])


if __name__ == "__main__":
    unittest.main()
