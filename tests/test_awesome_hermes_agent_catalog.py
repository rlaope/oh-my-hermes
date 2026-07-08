from __future__ import annotations

import json
from pathlib import Path
import unittest

from _cli_harness import run_cli
from omh.catalogs.awesome_hermes_agent import (
    PLUGIN_SUBSECTION,
    SOURCE_REPO,
    awesome_hermes_coverage,
    awesome_hermes_coverage_payload,
    awesome_hermes_item,
    awesome_hermes_summary,
)


class AwesomeHermesAgentCatalogTests(unittest.TestCase):
    def test_catalog_locks_current_upstream_readme_inventory(self) -> None:
        summary = awesome_hermes_summary()

        self.assertEqual(summary["schema_version"], "awesome_hermes_agent_coverage/v1")
        self.assertEqual(summary["source_repo"], SOURCE_REPO)
        self.assertEqual(summary["source_commit"], "e1e6d7b42d54ffbddf3503e72cf25ff59451e2d1")
        self.assertEqual(summary["item_count"], 188)
        self.assertEqual(summary["plugin_count"], 26)

        coverage = awesome_hermes_coverage()
        self.assertEqual(len({item.item.id for item in coverage}), 188)
        self.assertEqual(sum(1 for item in coverage if item.item.subsection == PLUGIN_SUBSECTION), 26)

    def test_plugin_coverage_maps_high_value_gaps_to_existing_omh_surfaces(self) -> None:
        web_search = awesome_hermes_item("hermes-web-search-plus")
        self.assertEqual(web_search.status, "partial")
        self.assertEqual(web_search.rule_set_version, "awesome_hermes_agent_rules/v1")
        self.assertEqual(web_search.matched_rule_id, "web_research")
        self.assertIn("web-research", web_search.omh_surfaces)
        self.assertIn("source-finder", web_search.omh_surfaces)

        live_discord = awesome_hermes_item("hermes-live-discord-agent-plugin")
        self.assertEqual(live_discord.status, "partial")
        self.assertEqual(live_discord.priority, "high")
        self.assertEqual(live_discord.matched_rule_id, "live_media_gateway")
        self.assertIn("voice-operator", live_discord.omh_surfaces)
        self.assertIn("media-input-operator", live_discord.omh_surfaces)
        self.assertIn("visual-qa", live_discord.omh_surfaces)

        dynamic = awesome_hermes_item("hermes-dynamic-workflows")
        self.assertEqual(dynamic.status, "partial")
        self.assertEqual(dynamic.matched_rule_id, "dynamic_orchestration")
        self.assertIn("team", dynamic.omh_surfaces)
        self.assertIn("ultragoal", dynamic.omh_surfaces)

        dangerous_patterns = awesome_hermes_item("custom-dangerous-patterns")
        self.assertEqual(dangerous_patterns.status, "partial")
        self.assertIn("security-safety-review", dangerous_patterns.omh_surfaces)
        self.assertIn("command-operator", dangerous_patterns.omh_surfaces)

    def test_default_rule_ids_are_emitted_for_unmatched_items(self) -> None:
        external = awesome_hermes_item("hermes-neurovision")

        self.assertEqual(external.status, "missing_candidate")
        self.assertEqual(external.rule_set_version, "awesome_hermes_agent_rules/v1")
        self.assertEqual(external.matched_rule_id, "default_external_candidate")

        community_skill = awesome_hermes_item("hermes-skill-factory")

        self.assertEqual(community_skill.status, "partial")
        self.assertEqual(community_skill.rule_set_version, "awesome_hermes_agent_rules/v1")
        self.assertEqual(community_skill.matched_rule_id, "default_skills_plugins")

    def test_rule_matching_uses_token_boundaries_for_ambiguous_plugin_terms(self) -> None:
        for item_id in ("hermes-weather-plugin", "hermes-wxtrain-plugin"):
            weather = awesome_hermes_item(item_id)

            self.assertEqual(weather.status, "missing_candidate")
            self.assertEqual(weather.matched_rule_id, "domain_connectors")
            self.assertIn("connector-operator", weather.omh_surfaces)
            self.assertIn("live-info-operator", weather.omh_surfaces)
            self.assertNotIn("web-research", weather.omh_surfaces)
            self.assertNotIn("source-finder", weather.omh_surfaces)

        analytics = awesome_hermes_item("agent-analytics-hermes-plugin")

        self.assertEqual(analytics.status, "partial")
        self.assertEqual(analytics.matched_rule_id, "cost_analytics")
        self.assertIn("ops-observability-card", analytics.omh_surfaces)
        self.assertNotIn("voice-operator", analytics.omh_surfaces)

    def test_plugin_filter_returns_only_plugin_section_coverage(self) -> None:
        payload = awesome_hermes_coverage_payload(subsection=PLUGIN_SUBSECTION)

        self.assertEqual(payload["schema_version"], "awesome_hermes_agent_coverage/v1")
        self.assertEqual(payload["item_count"], 26)
        items = payload["items"]
        self.assertIsInstance(items, list)
        self.assertTrue(items)
        for item in items:
            self.assertEqual(item["subsection"], PLUGIN_SUBSECTION)
            self.assertIn("coverage_status", item)
            self.assertIn("omh_surfaces", item)

    def test_skill_scout_contract_names_runtime_coverage_statuses(self) -> None:
        statuses = {item.status for item in awesome_hermes_coverage()}
        self.assertEqual(statuses, {"covered", "missing_candidate", "partial"})

        skill_scout = Path("skills/skill-scout/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("covered, partial, or missing_candidate coverage statuses", skill_scout)
        self.assertNotIn("missing-candidate", skill_scout)
        self.assertNotIn("external-reference", skill_scout)

    def test_ecosystem_cli_exposes_summary_list_and_inspect_surfaces(self) -> None:
        status, stdout, stderr = run_cli(["ecosystem", "awesome-hermes", "summary", "--json"])

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        summary = json.loads(stdout)
        self.assertEqual(summary["item_count"], 188)
        self.assertEqual(summary["plugin_count"], 26)

        status, stdout, stderr = run_cli(
            ["ecosystem", "awesome-hermes", "list", "--subsection", PLUGIN_SUBSECTION, "--json"]
        )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        listing = json.loads(stdout)
        self.assertEqual(listing["item_count"], 26)
        self.assertEqual(listing["summary"]["item_count"], 26)
        self.assertEqual(listing["catalog_summary"]["item_count"], 188)
        self.assertEqual(listing["items"][0]["subsection"], PLUGIN_SUBSECTION)
        self.assertIn("rule_set_version", listing["items"][0])
        self.assertIn("matched_rule_id", listing["items"][0])

        status, stdout, stderr = run_cli(
            ["ecosystem", "awesome-hermes", "inspect", "hermes-live-discord-agent-plugin", "--json"]
        )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        inspected = json.loads(stdout)
        self.assertEqual(inspected["schema_version"], "awesome_hermes_agent_item_coverage/v1")
        self.assertIn("voice-operator", inspected["item"]["omh_surfaces"])
        self.assertEqual(inspected["item"]["matched_rule_id"], "live_media_gateway")

    def test_ecosystem_cli_marks_truncated_human_surface_list(self) -> None:
        status, stdout, stderr = run_cli(
            [
                "ecosystem",
                "awesome-hermes",
                "list",
                "--subsection",
                PLUGIN_SUBSECTION,
                "--status",
                "partial",
                "--limit",
                "20",
            ],
            output_json=False,
        )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("+1 more", stdout)

    def test_ecosystem_cli_rejects_unknown_item_without_fallback_claim(self) -> None:
        status, stdout, stderr = run_cli(
            ["ecosystem", "awesome-hermes", "inspect", "definitely-not-a-real-item", "--json"]
        )

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("unknown awesome-hermes-agent item: definitely-not-a-real-item", stderr)

    def test_ecosystem_cli_rejects_negative_list_limit(self) -> None:
        status, stdout, stderr = run_cli(["ecosystem", "awesome-hermes", "list", "--limit", "-1"])

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("limit must be a positive integer", stderr)


if __name__ == "__main__":
    unittest.main()
