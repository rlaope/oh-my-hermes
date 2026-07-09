from __future__ import annotations

import json
from pathlib import Path
import unittest

from _cli_harness import run_cli
from omh.catalogs.awesome_hermes_agent import (
    AwesomeHermesItem,
    PLUGIN_SUBSECTION,
    SOURCE_REPO,
    awesome_hermes_coverage,
    awesome_hermes_coverage_payload,
    awesome_hermes_item,
    awesome_hermes_summary,
)
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


class AwesomeHermesAgentCatalogTests(unittest.TestCase):
    def test_catalog_locks_current_upstream_readme_inventory(self) -> None:
        summary = awesome_hermes_summary()

        self.assertEqual(summary["schema_version"], "awesome_hermes_agent_coverage/v1")
        self.assertEqual(summary["source_repo"], SOURCE_REPO)
        self.assertEqual(summary["source_commit"], "e1e6d7b42d54ffbddf3503e72cf25ff59451e2d1")
        self.assertEqual(summary["item_count"], 188)
        self.assertEqual(summary["plugin_count"], 26)
        self.assertEqual(summary["status_counts"], {"covered": 1, "partial": 187})

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

    def test_default_rule_ids_are_emitted_for_unmatched_skill_plugins(self) -> None:
        community_skill = coverage_for_item(
            _synthetic_item(
                item_id="synthetic-unmapped-community-skill",
                section="Skills & Plugins",
                subsection=PLUGIN_SUBSECTION,
                summary="Small helper for unclassified agent notes.",
            )
        )

        self.assertEqual(community_skill.status, "partial")
        self.assertEqual(community_skill.rule_set_version, "awesome_hermes_agent_rules/v1")
        self.assertEqual(community_skill.matched_rule_id, "default_skills_plugins")

    def test_unmatched_external_items_keep_missing_candidate_fallback(self) -> None:
        external = coverage_for_item(
            _synthetic_item(
                item_id="synthetic-unmapped-placeholder",
                summary="Placeholder entry without configured routing terms.",
            )
        )

        self.assertEqual(external.status, "missing_candidate")
        self.assertEqual(external.rule_set_version, "awesome_hermes_agent_rules/v1")
        self.assertEqual(external.matched_rule_id, "default_external_candidate")
        self.assertEqual(external.omh_surfaces, ("skill-scout", "toolbelt-readiness"))

    def test_generic_documentation_words_do_not_steal_external_fallback(self) -> None:
        external = coverage_for_item(
            _synthetic_item(
                item_id="synthetic-doc-notes",
                section="Guides & Documentation",
                subsection="Guides & Documentation",
                summary="Community maintained wiki and setup notes for an unrelated shell helper.",
            )
        )

        self.assertEqual(external.status, "missing_candidate")
        self.assertEqual(external.matched_rule_id, "default_external_candidate")

    def test_generic_setup_and_research_words_do_not_steal_external_fallback(self) -> None:
        external = coverage_for_item(
            _synthetic_item(
                item_id="synthetic-setup-research-notes",
                section="Guides & Documentation",
                subsection="Guides & Documentation",
                summary=(
                    "Setup guide, wiki notes, research plan, legal review, cash flow notes, "
                    "and dashboard ideas for an unrelated shell helper."
                ),
            )
        )

        self.assertEqual(external.status, "missing_candidate")
        self.assertEqual(external.matched_rule_id, "default_external_candidate")

    def test_rule_matching_uses_token_boundaries_for_ambiguous_plugin_terms(self) -> None:
        for item_id in ("hermes-weather-plugin", "hermes-wxtrain-plugin"):
            weather = awesome_hermes_item(item_id)

            self.assertEqual(weather.status, "partial")
            self.assertEqual(weather.matched_rule_id, "domain_connectors")
            self.assertIn("external-connector-readiness", weather.omh_surfaces)
            self.assertIn("connector-operator", weather.omh_surfaces)
            self.assertIn("live-info-operator", weather.omh_surfaces)
            self.assertNotIn("web-research", weather.omh_surfaces)
            self.assertNotIn("source-finder", weather.omh_surfaces)

        analytics = awesome_hermes_item("agent-analytics-hermes-plugin")

        self.assertEqual(analytics.status, "partial")
        self.assertEqual(analytics.matched_rule_id, "cost_analytics")
        self.assertIn("ops-observability-card", analytics.omh_surfaces)
        self.assertNotIn("voice-operator", analytics.omh_surfaces)

    def test_external_connector_candidates_have_readiness_surface(self) -> None:
        for item_id in ("hermes-nextcloud", "onequery-cli", "microsoft-workspace-skill", "chainlink-agent-skills"):
            candidate = awesome_hermes_item(item_id)

            self.assertEqual(candidate.status, "partial")
            self.assertIn("external-connector-readiness", candidate.omh_surfaces)
            self.assertIn("toolbelt-readiness", candidate.omh_surfaces)

        onequery = awesome_hermes_item("onequery-cli")

        self.assertEqual(onequery.matched_rule_id, "external_connector_readiness")
        self.assertIn("data-analysis", onequery.omh_surfaces)
        self.assertIn("security-safety-review", onequery.omh_surfaces)

    def test_ecosystem_bridge_candidates_have_connector_readiness_surface(self) -> None:
        for item_id in (
            "hermes-miniverse",
            "reina",
            "clawsocial-hermes-plugin",
            "agentchat-hermes",
            "windy-access",
            "agy-cli-bridge",
            "orahermes-agent",
        ):
            with self.subTest(item_id=item_id):
                candidate = awesome_hermes_item(item_id)

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, "ecosystem_identity_connector")
                self.assertIn("external-connector-readiness", candidate.omh_surfaces)
                self.assertIn("connector-operator", candidate.omh_surfaces)
                self.assertIn("security-safety-review", candidate.omh_surfaces)
                self.assertNotEqual(candidate.matched_rule_id, "default_external_candidate")

    def test_ecosystem_bridge_rule_does_not_steal_chainlink_connector_coverage(self) -> None:
        chainlink = awesome_hermes_item("chainlink-agent-skills")

        self.assertNotEqual(chainlink.matched_rule_id, "ecosystem_identity_connector")
        self.assertIn("external-connector-readiness", chainlink.omh_surfaces)

    def test_ecosystem_bridge_rule_does_not_steal_self_contained_agentchat_skill(self) -> None:
        skill = awesome_hermes_item("agentchat-universal-skill")

        self.assertNotEqual(skill.matched_rule_id, "ecosystem_identity_connector")
        self.assertNotIn("external-connector-readiness", skill.omh_surfaces)
        self.assertNotIn("connector-operator", skill.omh_surfaces)

    def test_slash_prompt_plugin_has_prompt_import_readiness_surface(self) -> None:
        slash_prompts = awesome_hermes_item("hermes-plugin-slash-prompts")

        self.assertEqual(slash_prompts.status, "partial")
        self.assertEqual(slash_prompts.matched_rule_id, "prompt_import_readiness")
        self.assertIn("prompt-import-readiness", slash_prompts.omh_surfaces)
        self.assertIn("skill-scout", slash_prompts.omh_surfaces)
        self.assertIn("security-safety-review", slash_prompts.omh_surfaces)
        self.assertNotEqual(slash_prompts.matched_rule_id, "default_skills_plugins")

    def test_physical_device_candidates_have_device_safety_readiness_surface(self) -> None:
        for item_id in ("snapmaker-u1-toolkit", "mycodo-hermes-skill", "hermes-embodied"):
            with self.subTest(item_id=item_id):
                device_candidate = awesome_hermes_item(item_id)

                self.assertEqual(device_candidate.status, "partial")
                self.assertEqual(device_candidate.matched_rule_id, "physical_device_readiness")
                self.assertIn("physical-device-readiness", device_candidate.omh_surfaces)
                self.assertIn("security-safety-review", device_candidate.omh_surfaces)
                self.assertNotEqual(device_candidate.matched_rule_id, "default_external_candidate")

    def test_tooling_and_documentation_candidates_map_to_operator_surfaces(self) -> None:
        expectations = {
            "lintlang": ("quality_config_migration", "workspace-audit", "security-safety-review"),
            "openclaw-to-hermes": ("quality_config_migration", "doctor", "workspace-audit"),
            "evey-setup": ("quality_config_migration", "doctor", "toolbelt-readiness"),
            "hermes-agent-docs": ("operator_documentation", "wiki", "content-operator"),
            "hermes-wsl-ubuntu": ("operator_documentation", "doctor", "wiki"),
            "hermeswiki": ("operator_documentation", "wiki", "workspace-audit"),
        }
        for item_id, (rule_id, primary_surface, secondary_surface) in expectations.items():
            with self.subTest(item_id=item_id):
                candidate = awesome_hermes_item(item_id)

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, rule_id)
                self.assertIn(primary_surface, candidate.omh_surfaces)
                self.assertIn(secondary_surface, candidate.omh_surfaces)

    def test_domain_research_and_safety_candidates_map_to_review_surfaces(self) -> None:
        expectations = {
            "hermes-genesis": ("domain_research_analysis", "research-department", "agent-evaluation"),
            "hermes-legal": ("domain_research_analysis", "security-safety-review", "data-analysis"),
            "mercury": ("domain_research_analysis", "data-analysis", "external-connector-readiness"),
            "hermes-research-agent": ("research_agent_readiness", "research-department", "source-finder"),
            "hermes-agent-camel": ("safety_training_derivatives", "security-safety-review", "verification-gate"),
            "hermes-skill-distillation": ("safety_training_derivatives", "agent-evaluation", "workflow-learning"),
        }
        for item_id, (rule_id, primary_surface, secondary_surface) in expectations.items():
            with self.subTest(item_id=item_id):
                candidate = awesome_hermes_item(item_id)

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, rule_id)
                self.assertIn(primary_surface, candidate.omh_surfaces)
                self.assertIn(secondary_surface, candidate.omh_surfaces)

    def test_terminal_visual_candidate_maps_to_visual_review_surfaces(self) -> None:
        candidate = awesome_hermes_item("hermes-neurovision")

        self.assertEqual(candidate.status, "partial")
        self.assertEqual(candidate.matched_rule_id, "terminal_visual_overlay")
        self.assertIn("visual-qa", candidate.omh_surfaces)
        self.assertIn("design-quality-gate", candidate.omh_surfaces)

    def test_popular_agent_skill_candidates_have_specific_readiness_surfaces(self) -> None:
        expectations = {
            "wondelai-skills": ("cross_platform_skill_ecosystem", "skill-scout", "prompt-import-readiness"),
            "anthropic-cybersecurity-skills": (
                "security_skill_library",
                "security-safety-review",
                "agent-evaluation",
            ),
            "pydantic-ai-skills": ("typed_skill_runtime", "verification-gate", "toolbelt-readiness"),
            "agentic-mcp-skill": ("mcp_skill_bridge", "external-connector-readiness", "toolbelt-readiness"),
            "skillsdotnet": ("mcp_skill_bridge", "external-connector-readiness", "toolbelt-readiness"),
            "longbridge": ("domain_connectors", "external-connector-readiness", "live-info-operator"),
            "dev-gtm-claude-skills": ("growth_content_skills", "content-operator", "research-department"),
        }
        for item_id, (rule_id, primary_surface, secondary_surface) in expectations.items():
            with self.subTest(item_id=item_id):
                candidate = awesome_hermes_item(item_id)

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, rule_id)
                self.assertIn(primary_surface, candidate.omh_surfaces)
                self.assertIn(secondary_surface, candidate.omh_surfaces)
                self.assertNotEqual(candidate.matched_rule_id, "default_skills_plugins")

    def test_remaining_popular_skill_candidates_gain_domain_surfaces(self) -> None:
        expectations = {
            "personal-api": ("knowledge_workspace_identity", "memory-curation-review", "wiki"),
            "humanizer-ru": ("copy_localization_quality", "content-operator", "verification-gate"),
            "cognify-skills": (
                "business_operations_skill_pack",
                "external-connector-readiness",
                "connector-operator",
            ),
            "bmad-module-skill-forge": ("skill_forge_generation", "skill-scout", "prompt-import-readiness"),
            "ripley-xmr-gateway": (
                "private_crypto_gateway",
                "external-connector-readiness",
                "security-safety-review",
            ),
            "colony-skill": (
                "community_matching_reputation",
                "gateway-intent-card",
                "security-safety-review",
            ),
            "hermes-edu-skills": ("education_skill_library", "research-department", "media-input-operator"),
            "hurmoz": ("localized_domain_skill_pack", "content-operator", "live-info-operator"),
            "pingpong": ("community_matching_reputation", "gateway-intent-card", "external-connector-readiness"),
            "wizards-of-the-ghosts": ("themed_dev_workflow_pack", "workflow-learning", "verification-gate"),
        }
        for item_id, (rule_id, primary_surface, secondary_surface) in expectations.items():
            with self.subTest(item_id=item_id):
                candidate = awesome_hermes_item(item_id)

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, rule_id)
                self.assertIn(primary_surface, candidate.omh_surfaces)
                self.assertIn(secondary_surface, candidate.omh_surfaces)
                self.assertNotEqual(candidate.matched_rule_id, "default_skills_plugins")

    def test_public_plugin_repo_items_have_specific_readiness_surfaces(self) -> None:
        expectations = {
            "hermes-plugins": (
                "public_agent_orchestration_plugin",
                "agent-board",
                "ops-observability-card",
            ),
            "evey-bridge-plugin": (
                "public_agent_orchestration_plugin",
                "external-connector-readiness",
                "agent-board",
            ),
            "hermes-curator-evolver": (
                "public_skill_governance_plugin",
                "skill-health",
                "verification-gate",
            ),
            "yantrikdb-hermes-plugin": (
                "public_memory_provider_plugin",
                "memory-curation-review",
                "external-connector-readiness",
            ),
        }
        for item_id, (rule_id, primary_surface, secondary_surface) in expectations.items():
            with self.subTest(item_id=item_id):
                candidate = awesome_hermes_item(item_id)

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, rule_id)
                self.assertIn(primary_surface, candidate.omh_surfaces)
                self.assertIn(secondary_surface, candidate.omh_surfaces)
                self.assertNotIn("voice-operator", candidate.omh_surfaces)

    def test_public_plugin_repo_synthetic_candidates_route_to_review_surfaces(self) -> None:
        expectations = {
            "hermes-example-plugins": (
                "Reference implementations and documentation companions for hermes-agent plugin authoring.",
                "official_plugin_reference_examples",
                "prompt-import-readiness",
                "verification-gate",
            ),
            "remnic": (
                "Remnic Hermes plugin provides scoped memory with provenance, retrieval quality, corrections, and boundaries.",
                "public_memory_provider_plugin",
                "memory-curation-review",
                "security-safety-review",
            ),
            "scope-recall-hermes": (
                "Scope-aware recall Hermes memory plugin/provider with SQLite truth and LanceDB semantic search.",
                "public_memory_provider_plugin",
                "memory-curation-review",
                "external-connector-readiness",
            ),
            "mem9-hermes-plugin": (
                "Mem9 Hermes memory plugin provider for reviewed recall and external backend readiness.",
                "public_memory_provider_plugin",
                "memory-curation-review",
                "external-connector-readiness",
            ),
            "hermes-brave-search-plugin": (
                "Brave Search plugin provider for Hermes Agent web search.",
                "public_search_provider_plugin",
                "web-research",
                "external-connector-readiness",
            ),
            "hermes-kagi-plugin": (
                "Kagi web search and extract provider for Hermes Agent.",
                "public_search_provider_plugin",
                "source-finder",
                "live-info-operator",
            ),
            "hermes-tweet": (
                "Native Hermes Agent plugin for X/Twitter automation through Xquik.",
                "public_social_automation_plugin",
                "gateway-intent-card",
                "connector-operator",
            ),
            "tokentelemetry-hermes-plugin": (
                "TokenTelemetry launcher tab inside Hermes Dashboard with local observability for Hermes Agent.",
                "public_observability_plugin",
                "ops-observability-card",
                "production-audit",
            ),
            "hermes-skill-view": (
                "Hermes Skill View plugin improves runtime skill recommendation and pre-message reasoning middleware.",
                "public_skill_governance_plugin",
                "skill-health",
                "agent-evaluation",
            ),
        }
        for item_id, (summary, rule_id, primary_surface, secondary_surface) in expectations.items():
            with self.subTest(item_id=item_id):
                candidate = coverage_for_item(
                    _synthetic_item(
                        item_id=item_id,
                        summary=summary,
                        section="Skills & Plugins",
                        subsection=PLUGIN_SUBSECTION,
                    )
                )

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, rule_id)
                self.assertIn(primary_surface, candidate.omh_surfaces)
                self.assertIn(secondary_surface, candidate.omh_surfaces)
                self.assertNotEqual(candidate.matched_rule_id, "default_skills_plugins")

    def test_official_plugin_examples_rule_does_not_steal_generic_reference_docs(self) -> None:
        generic_reference = coverage_for_item(
            _synthetic_item(
                item_id="python-sdk-examples",
                summary="Reference implementations for Python SDK examples and a generic plugin authoring guide.",
                section="Skills & Plugins",
                subsection=PLUGIN_SUBSECTION,
            )
        )

        self.assertNotEqual(generic_reference.matched_rule_id, "official_plugin_reference_examples")

    def test_meta_skill_and_registry_candidates_do_not_stay_generic(self) -> None:
        expectations = {
            "hermes-skill-factory": "skill_marketplace",
            "hermes-dojo": "skill_marketplace",
            "super-hermes": "meta_prompt_self_improvement",
            "maestro": "dynamic_orchestration",
            "execplan-skill": "dynamic_orchestration",
            "hermeshub": "skill_marketplace",
        }
        for item_id, rule_id in expectations.items():
            with self.subTest(item_id=item_id):
                candidate = awesome_hermes_item(item_id)

                self.assertEqual(candidate.status, "partial")
                self.assertEqual(candidate.matched_rule_id, rule_id)
                self.assertNotEqual(candidate.matched_rule_id, "default_skills_plugins")

    def test_current_awesome_hermes_inventory_has_no_unmapped_candidates(self) -> None:
        missing = [item.item.id for item in awesome_hermes_coverage(status="missing_candidate")]

        self.assertEqual(missing, [])

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
        self.assertEqual(statuses, {"covered", "partial"})

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
