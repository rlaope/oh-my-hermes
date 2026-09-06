from __future__ import annotations

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.model_recommendations import (  # noqa: E402
    MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_STATUSES,
    SHIPPED_MODEL_RECOMMENDATIONS,
    load_recommendation_overrides,
    merge_recommendation_catalog,
    resolve_model_recommendation,
    serialize_recommendation_payload,
)
from omh.coding.model_routing import MODEL_CATEGORIES, MODEL_ROLES  # noqa: E402


def _active(
    model_alias: str,
    *,
    provider: str,
    model_id: str | None = None,
    family: str = "",
    owners: tuple[str, ...] = ("hermes", "maestro"),
    status: str = "confirmed_active",
) -> dict[str, object]:
    return {
        "model_alias": model_alias,
        "model_id": model_id or model_alias,
        "provider": provider,
        "provider_family": provider,
        "model_family": family,
        "compatible_owners": owners,
        "status": status,
    }


_ALL_ACTIVE = (
    _active("kimi-k3", provider="apitopia", family="kimi"),
    _active("claude-opus-5", provider="ccapi", family="claude"),
    _active("claude-fable-5", provider="ccapi", family="claude"),
    _active("gpt-5.6-sol", provider="openai-codex", family="gpt"),
    _active("gpt-5.6-terra", provider="openai-codex", family="gpt"),
    _active("glm-5.2", provider="zai", family="glm"),
    _active("glm-5.2-ultrafast", provider="zai", family="glm"),
    _active("grok-code-fast", provider="xai", family="grok"),
    _active("gemini-3.1-pro", provider="google", family="gemini"),
)


class RecommendationCatalogTests(unittest.TestCase):
    def test_public_readmes_and_site_cover_every_shipped_category_chain(self) -> None:
        docs = {
            "readme": Path("README.md").read_text(encoding="utf-8"),
            "ko": Path("README.ko.md").read_text(encoding="utf-8"),
            "ja": Path("README.ja.md").read_text(encoding="utf-8"),
            "zh": Path("README.zh.md").read_text(encoding="utf-8"),
            "site": Path("site/docs/model-routing/index.html").read_text(encoding="utf-8"),
            "home": Path("site/index.html").read_text(encoding="utf-8"),
        }
        # Both HTML surfaces put one category per source line and key the row
        # on a bare ``<span>{category}</span>``; the markdown READMEs use a
        # table row instead.
        html_surfaces = {"site", "home"}
        categories = SHIPPED_MODEL_RECOMMENDATIONS["categories"]
        assert isinstance(categories, dict)

        for name, chain in categories.items():
            assert isinstance(chain, list)
            aliases = [str(candidate["model_alias"]) for candidate in chain]
            for surface, text in docs.items():
                with self.subTest(category=name, surface=surface):
                    if surface in html_surfaces:
                        row = next(
                            line for line in text.splitlines() if f"<span>{name}</span>" in line
                        )
                    else:
                        row = next(
                            line for line in text.splitlines() if line.startswith(f"| `{name}` |")
                        )
                    normalized_text = re.sub(r"[^a-z0-9]", "", row.casefold())
                    position = -1
                    for alias in aliases:
                        normalized_alias = re.sub(r"[^a-z0-9]", "", alias.casefold())
                        next_position = normalized_text.find(normalized_alias, position + 1)
                        self.assertGreater(next_position, position)
                        position = next_position

    def test_agent_install_surfaces_link_to_the_canonical_protocol(self) -> None:
        protocol_url = (
            "https://raw.githubusercontent.com/rlaope/oh-my-hermes/"
            "{resolved-commit-sha}/INSTALL_FOR_AGENTS.md"
        )
        surfaces = {
            "agent_protocol": Path("INSTALL_FOR_AGENTS.md").read_text(encoding="utf-8"),
            "readme": Path("README.md").read_text(encoding="utf-8"),
            "ko": Path("README.ko.md").read_text(encoding="utf-8"),
            "ja": Path("README.ja.md").read_text(encoding="utf-8"),
            "zh": Path("README.zh.md").read_text(encoding="utf-8"),
            "site": Path("site/index.html").read_text(encoding="utf-8"),
            "routing_site": Path("site/docs/model-routing/index.html").read_text(
                encoding="utf-8"
            ),
        }

        for surface, text in surfaces.items():
            with self.subTest(surface=surface):
                self.assertIn(protocol_url, text)
        # Every copy of the pasteable request names the model-chain interview
        # step, so URL-driven agent installs enter the interview after setup
        # instead of stopping at doctor.
        for surface, text in surfaces.items():
            if "Install and fully configure Oh My Hermes" not in text:
                continue
            with self.subTest(surface=surface, contract="chain-interview-step"):
                self.assertIn("model-chain interview", text)
                self.assertNotIn("interactive model setup, and doctor steps", text)
        # The README model-routing section shows where the chains live: a cat
        # of the seeded file (matching its real key order and indentation) and
        # an edited example, so readers learn the file is the tuning surface.
        seeded_cat_block = (
            "$ cat ~/.omh/routing/model-chains.json\n"
            "{\n"
            '  "categories": {},\n'
            '  "schema_version": "mixture_chain_overrides/v1"\n'
            "}"
        )
        for surface in ("readme", "ko", "ja", "zh"):
            with self.subTest(surface=surface, contract="chains-file-example"):
                self.assertIn(seeded_cat_block, surfaces[surface])
                self.assertIn('"claude-fable-5-1", "reasoning_effort": "xhigh"', surfaces[surface])
                self.assertIn('"gpt-5.6-sol", "reasoning_effort": "xhigh"', surfaces[surface])
                self.assertIn('"kimi-k3-ultrafast", "reasoning_effort": "low"', surfaces[surface])
                self.assertIn("omh model-chains show", surfaces[surface])
        self.assertIn('data-i18n="route.state.owner_default"', surfaces["site"])
        translations = Path("site/i18n.js").read_text(encoding="utf-8")
        self.assertIn('"route.state.owner_default"', translations)
        self.assertNotIn('"route.state.unconfigured"', translations)
        self.assertIn('OMH_SOURCE_REF="$OMH_REF"', surfaces["agent_protocol"])
        self.assertNotIn(
            "raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh",
            surfaces["agent_protocol"],
        )
        for surface, text in surfaces.items():
            with self.subTest(surface=surface):
                self.assertNotIn(
                    "raw.githubusercontent.com/rlaope/oh-my-hermes/"
                    "main/INSTALL_FOR_AGENTS.md",
                    text,
                )
        self.assertIn('data-i18n="route.state.owner_default"', surfaces["site"])
        translations = Path("site/i18n.js").read_text(encoding="utf-8")
        self.assertIn('"route.state.owner_default"', translations)
        self.assertNotIn('"route.state.unconfigured"', translations)

    def test_catalog_is_schema_versioned_and_preserves_closed_vocabularies(self) -> None:
        catalog = SHIPPED_MODEL_RECOMMENDATIONS
        self.assertEqual(catalog["schema_version"], MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION)
        self.assertEqual(set(catalog["categories"]), set(MODEL_CATEGORIES))
        self.assertEqual(MODEL_CATEGORIES, (
            "ultrabrain", "deep", "architect", "unspecified-high", "unspecified-low",
            "quick", "writing", "visual-engineering", "artistry",
        ))
        self.assertEqual(MODEL_ROLES, (
            "brain", "implementation", "design_visual", "review", "docs", "research",
        ))
        self.assertNotIn("main", catalog["categories"])
        self.assertNotIn("x_platform_data", catalog["categories"])
        self.assertEqual(set(catalog["role_suggestions"]), {"main"})
        self.assertEqual(set(catalog["domain_affinities"]), {"x_platform_data"})

    def test_shipped_editorial_chains_are_pinned(self) -> None:
        catalog = SHIPPED_MODEL_RECOMMENDATIONS

        def aliases(section: str, name: str) -> list[str]:
            return [entry["model_alias"] for entry in catalog[section][name]]

        self.assertEqual(aliases("role_suggestions", "main"), [
            "kimi-k3", "claude-fable-5-1", "claude-opus-5", "claude-fable-5",
            "gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra",
        ])
        # A chain that would otherwise sit in one provider ecosystem ends on
        # a comparable-tier candidate from another (owner rule, 2026-08-19)
        # so one rejected ecosystem cannot exhaust the chain.
        self.assertEqual(
            aliases("categories", "unspecified-low"),
            ["glm-5.3", "glm-5.2", "glm-5.2-ultrafast", "deepseek-v3.2", "claude-opus-5"],
        )
        self.assertEqual(aliases("categories", "unspecified-high"), ["kimi-k3", "claude-opus-5"])
        # GPT-6 Astra heads the GPT frontier slots (2026-09-03) with Sol as
        # fall-through, the same generation rule as GLM 5.2 behind 5.3.
        self.assertEqual(aliases("categories", "ultrabrain"), ["gpt-6-astra", "gpt-5.6-sol"])
        # DeepSeek closes deep's single-ecosystem exposure with a
        # reasoning-capable budget fallback (owner request, 2026-08-21).
        self.assertEqual(aliases("categories", "deep"), ["gpt-5.6-terra", "deepseek-v3.2"])
        self.assertEqual(
            aliases("categories", "architect"),
            ["claude-fable-5-1", "claude-fable-5", "gpt-6-astra", "gpt-5.6-sol", "kimi-k3"],
        )
        self.assertEqual(
            aliases("categories", "quick"),
            [
                "glm-5.3-flash", "glm-5.2-ultrafast", "kimi-k3", "gpt-5.6-luna",
                "claude-fable-5-1", "claude-fable-5",
            ],
        )
        self.assertEqual(
            aliases("categories", "writing"),
            ["kimi-k3", "qwen3-coder", "gemini-3.1-pro"],
        )
        self.assertEqual(
            aliases("categories", "visual-engineering"),
            ["claude-fable-5-1", "claude-fable-5", "kimi-k3"],
        )
        self.assertEqual(
            aliases("categories", "artistry"),
            ["gemini-3.1-pro", "claude-fable-5-1", "claude-fable-5", "kimi-k3"],
        )
        self.assertEqual(
            aliases("categories", "visual-engineering"),
            ["claude-fable-5-1", "claude-fable-5", "kimi-k3"],
        )
        self.assertEqual(
            aliases("categories", "quick"),
            [
                "glm-5.3-flash", "glm-5.2-ultrafast", "kimi-k3", "gpt-5.6-luna",
                "claude-fable-5-1", "claude-fable-5",
            ],
        )
        self.assertEqual(aliases("categories", "writing"), ["kimi-k3", "qwen3-coder", "gemini-3.1-pro"])
        self.assertEqual(
            aliases("categories", "artistry"),
            ["gemini-3.1-pro", "claude-fable-5-1", "claude-fable-5", "kimi-k3"],
        )
        self.assertEqual(aliases("domain_affinities", "x_platform_data"), [
            "grok-code-fast", "kimi-k3", "gemini-3.1-pro",
        ])
        main = catalog["role_suggestions"]["main"]
        self.assertEqual([entry["reasoning_effort"] for entry in main[-3:]], ["xhigh", "medium", "high"])
        self.assertEqual(catalog["categories"]["ultrabrain"][0]["reasoning_effort"], "xhigh")
        self.assertEqual(catalog["categories"]["deep"][0]["reasoning_effort"], "high")
        for section in ("categories", "role_suggestions", "domain_affinities"):
            for chain in catalog[section].values():
                for candidate in chain:
                    self.assertTrue(candidate["model_family"])
                    self.assertTrue(candidate["preferred_provider_families"])
                    self.assertTrue(candidate["reasoning"])
                    self.assertEqual(candidate["recommendation_source"], "shipped_editorial")

    def test_override_loader_and_merge_are_deterministic_and_secret_free(self) -> None:
        override = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {
                "deep": [{
                    "model_alias": "qwen3-coder",
                    "model_family": "qwen",
                    "preferred_provider_families": ["qwen-oauth"],
                    "reasoning_effort": "high",
                    "reasoning": "Operator-selected deep coding route.",
                }],
            },
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "recommendations.json"
            path.write_text(json.dumps(override), encoding="utf-8")
            loaded = load_recommendation_overrides(path)
        self.assertEqual(loaded["categories"]["deep"][0]["recommendation_source"], "user_override")
        first = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, loaded)
        second = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, loaded)
        self.assertEqual(serialize_recommendation_payload(first), serialize_recommendation_payload(second))
        self.assertEqual(first["categories"]["deep"][0]["model_alias"], "qwen3-coder")
        self.assertEqual(first["categories"]["quick"], SHIPPED_MODEL_RECOMMENDATIONS["categories"]["quick"])
        serialized = serialize_recommendation_payload(first)
        self.assertNotIn("api_key", serialized.casefold())
        self.assertNotIn("token", serialized.casefold())

    def test_override_rejects_categories_role_slots_domains_and_secret_fields_at_wrong_surfaces(self) -> None:
        bad_payloads = (
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "categories": {"main": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "categories": {"x_platform_data": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "role_suggestions": {"brain": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "domain_affinities": {"main": []}},
            {
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "categories": {"deep": [{
                    "model_alias": "qwen3-coder", "model_family": "qwen",
                    "preferred_provider_families": ["qwen-oauth"],
                    "reasoning": "x", "api_key": "must-not-be-stored",
                }]},
            },
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    load_recommendation_overrides(payload)


class RecommendationResolverTests(unittest.TestCase):
    def test_recommended_head_and_missing_head_resolution_are_deterministic(self) -> None:
        all_active = resolve_model_recommendation(
            owner="maestro", category="unspecified-high", active_models=reversed(_ALL_ACTIVE)
        )
        self.assertEqual(all_active["status"], "resolved")
        self.assertEqual(all_active["selected"]["model_alias"], "kimi-k3")
        self.assertEqual(
            [entry["model_alias"] for entry in all_active["projection"]["chain"]],
            ["kimi-k3", "claude-opus-5"],
        )

        only_next = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            active_models=[_active("claude-opus-5", provider="ccapi", family="claude")],
        )
        self.assertEqual(only_next["selected"]["model_alias"], "claude-opus-5")
        self.assertEqual([entry["model_alias"] for entry in only_next["projection"]["chain"]], ["claude-opus-5"])
        self.assertEqual(only_next["inactive_candidates"], ["kimi-k3"])

    def test_explicit_unavailable_freezes_as_choice_required_without_substitution(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            explicit_model="grok-code-fast",
            active_models=_ALL_ACTIVE[:-2],
        )
        self.assertEqual(route["status"], "choice_required")
        self.assertEqual(route["requested_model"], "grok-code-fast")
        self.assertIsNone(route["selected"])
        self.assertIsNone(route["projection"])
        self.assertEqual(route["available_chain"], ["kimi-k3", "claude-opus-5"])

    def test_explicit_active_model_wins_over_editorial_chain(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            explicit_model="grok-code-fast",
            active_models=_ALL_ACTIVE,
        )
        self.assertEqual(route["status"], "resolved")
        self.assertEqual(route["selected"]["model_alias"], "grok-code-fast")
        self.assertEqual(route["source"], "explicit_model")
        self.assertEqual([entry["model_alias"] for entry in route["projection"]["chain"]], ["grok-code-fast"])

    def test_no_active_candidate_uses_each_owner_default_for_every_selector(self) -> None:
        selectors = (
            {"category": "deep"},
            {"role_slot": "main"},
            {"domain": "x_platform_data"},
        )

        for owner in ("hermes", "maestro"):
            for selector in selectors:
                with self.subTest(owner=owner, selector=selector):
                    route = resolve_model_recommendation(
                        owner=owner,
                        active_models=[],
                        **selector,
                    )
                    self.assertEqual(
                        route["schema_version"],
                        MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION,
                    )
                    self.assertEqual(route["status"], "owner_default")
                    self.assertEqual(route["source"], "owner_default")
                    self.assertIn(route["status"], MODEL_RECOMMENDATION_STATUSES)
                    self.assertIsNone(route["selected"])
                    self.assertIsNone(route["projection"])
                    self.assertTrue(route["setup_can_continue"])
                    self.assertTrue(route["inactive_candidates"])

    def test_only_confirmed_active_owner_compatible_models_are_eligible(self) -> None:
        models = (
            _active("gpt-5.6-terra", provider="openai-codex", status="observed_before"),
            _active("gpt-5.6-terra", provider="openai-codex", owners=("maestro",)),
        )
        route = resolve_model_recommendation(owner="hermes", category="deep", active_models=models)
        self.assertEqual(route["status"], "owner_default")

    def test_hermes_projection_is_one_native_binding_not_a_provider_registry(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes", role_slot="main", active_models=reversed(_ALL_ACTIVE)
        )
        projection = route["projection"]
        self.assertEqual(projection["kind"], "hermes_native_binding")
        self.assertEqual(projection["alias"], "main")
        self.assertEqual(projection["provider"], "apitopia")
        self.assertEqual(projection["model_id"], "kimi-k3")
        self.assertEqual(projection["binding"], "apitopia/kimi-k3")
        self.assertEqual(projection["apply_state"], "approval_required")
        self.assertNotIn("providers", projection)
        self.assertNotIn("credentials", serialize_recommendation_payload(route).casefold())

    def test_maestro_projection_keeps_ordered_external_chain_and_owner_compatibility(self) -> None:
        active = (
            _active("grok-code-fast", provider="xai", family="grok", owners=("hermes",)),
            _active("kimi-k3", provider="apitopia", family="kimi"),
            _active("gemini-3.1-pro", provider="google", family="gemini"),
        )
        route = resolve_model_recommendation(
            owner="maestro", domain="x_platform_data", active_models=active
        )
        self.assertEqual(route["selected"]["model_alias"], "kimi-k3")
        self.assertEqual(route["projection"]["kind"], "maestro_ordered_chain")
        self.assertEqual(
            [entry["model_alias"] for entry in route["projection"]["chain"]],
            ["kimi-k3", "gemini-3.1-pro"],
        )
        self.assertEqual(route["inactive_candidates"], ["grok-code-fast"])

    def test_selector_surfaces_are_mutually_exclusive_and_closed(self) -> None:
        invalid = (
            {"category": "main"},
            {"category": "x_platform_data"},
            {"role_slot": "brain"},
            {"domain": "main"},
            {"category": "deep", "domain": "x_platform_data"},
        )
        for selector in invalid:
            with self.subTest(selector=selector):
                with self.assertRaises(ValueError):
                    resolve_model_recommendation(owner="hermes", active_models=(), **selector)

    def test_user_override_drives_resolution_without_mutating_shipped_catalog(self) -> None:
        override = load_recommendation_overrides({
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {"deep": [{
                "model_alias": "qwen3-coder", "model_family": "qwen",
                "preferred_provider_families": ["qwen-oauth"],
                "reasoning_effort": "high", "reasoning": "User deep route.",
            }]},
        })
        route = resolve_model_recommendation(
            owner="hermes",
            category="deep",
            active_models=[_active("qwen3-coder", provider="qwen-oauth", family="qwen")],
            overrides=override,
        )
        self.assertEqual(route["selected"]["model_alias"], "qwen3-coder")
        self.assertEqual(route["selected"]["recommendation_source"], "user_override")
        self.assertEqual(SHIPPED_MODEL_RECOMMENDATIONS["categories"]["deep"][0]["model_alias"], "gpt-5.6-terra")

    def test_resolution_serialization_is_stable_across_active_input_order(self) -> None:
        first = resolve_model_recommendation(
            owner="maestro", role_slot="main", active_models=_ALL_ACTIVE
        )
        second = resolve_model_recommendation(
            owner="maestro", role_slot="main", active_models=reversed(_ALL_ACTIVE)
        )
        self.assertEqual(serialize_recommendation_payload(first), serialize_recommendation_payload(second))


class LastResortFallbackTests(unittest.TestCase):
    """The shared final attempt used only after a selected chain is exhausted."""

    _OPUS_ONLY = (_active("claude-opus-5", provider="ccapi", family="claude"),)
    _SOL_ONLY = (_active("gpt-5.6-sol", provider="openai-codex", family="gpt"),)

    def test_schema_versions_advance_and_legacy_override_remains_supported(self) -> None:
        self.assertEqual(MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION, "model_recommendation_catalog/v2")
        self.assertEqual(MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "model_recommendation_overrides/v2")
        self.assertEqual(MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION, "model_recommendation_resolution/v3")

        legacy = load_recommendation_overrides({
            "schema_version": "model_recommendation_overrides/v1",
            "categories": {"quick": [{
                "model_alias": "gemini-3.1-pro",
                "model_family": "gemini",
                "preferred_provider_families": ["google"],
                "reasoning": "Legacy category override.",
            }]},
        })
        self.assertEqual(legacy["schema_version"], "model_recommendation_overrides/v1")
        self.assertNotIn("last_resort", legacy)
        merged = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, legacy)
        self.assertEqual(merged["categories"]["quick"][0]["model_alias"], "gemini-3.1-pro")
        self.assertEqual(
            merged["last_resort"]["any"][0]["model_alias"],
            "claude-opus-5",
        )
        with self.assertRaises(ValueError):
            load_recommendation_overrides({
                "schema_version": "model_recommendation_overrides/v1",
                "last_resort": {"any": []},
            })

    def test_legacy_catalog_without_last_resort_keeps_owner_default_behavior(self) -> None:
        legacy_catalog = {
            "schema_version": "model_recommendation_catalog/v1",
            "categories": SHIPPED_MODEL_RECOMMENDATIONS["categories"],
            "role_suggestions": SHIPPED_MODEL_RECOMMENDATIONS["role_suggestions"],
            "domain_affinities": SHIPPED_MODEL_RECOMMENDATIONS["domain_affinities"],
        }
        untouched = merge_recommendation_catalog(legacy_catalog, None)
        self.assertNotIn("last_resort", untouched)
        self.assertEqual(
            merge_recommendation_catalog(untouched, None)["schema_version"],
            "model_recommendation_catalog/v1",
        )
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            active_models=self._OPUS_ONLY,
            catalog=legacy_catalog,
        )
        self.assertEqual(route["status"], "owner_default")
        self.assertEqual(route["source"], "owner_default")

        v2_category_only = merge_recommendation_catalog(
            legacy_catalog,
            load_recommendation_overrides({
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "categories": {"quick": [{
                    "model_alias": "gemini-3.1-pro",
                    "model_family": "gemini",
                    "preferred_provider_families": ["google"],
                    "reasoning": "Version 2 override using only a legacy-compatible section.",
                }]},
            }),
        )
        self.assertEqual(v2_category_only["schema_version"], "model_recommendation_catalog/v1")
        self.assertNotIn("last_resort", v2_category_only)
        self.assertEqual(v2_category_only["categories"]["quick"][0]["model_alias"], "gemini-3.1-pro")

        upgraded = merge_recommendation_catalog(
            legacy_catalog,
            load_recommendation_overrides({
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "last_resort": {"any": [{
                    "model_alias": "claude-opus-5",
                    "model_family": "claude",
                    "preferred_provider_families": ["ccapi"],
                    "reasoning": "Upgrade the legacy catalog with an explicit final chain.",
                }]},
            }),
        )
        self.assertEqual(upgraded["schema_version"], MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION)

    def test_dead_category_chain_falls_back_to_the_shared_subscription_chain(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes", category="quick", active_models=self._OPUS_ONLY
        )
        self.assertEqual(route["status"], "resolved")
        self.assertEqual(route["source"], "last_resort_chain")
        self.assertEqual(route["selected"]["model_alias"], "claude-opus-5")
        self.assertEqual(route["available_chain"], ["claude-opus-5"])
        self.assertEqual(
            route["inactive_candidates"],
            [
                "glm-5.3-flash",
                "glm-5.2-ultrafast",
                "kimi-k3",
                "gpt-5.6-luna",
                "claude-fable-5-1",
                "claude-fable-5",
                "gpt-5.6-sol",
            ],
        )
        self.assertEqual(route["projection"]["kind"], "hermes_native_binding")
        self.assertEqual(route["projection"]["apply_state"], "approval_required")

    def test_last_resort_never_outranks_an_eligible_selected_chain_candidate(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            active_models=(
                _active("glm-5.2-ultrafast", provider="zai", family="glm"),
                *self._OPUS_ONLY,
            ),
        )
        self.assertEqual(route["source"], "recommendation_chain")
        self.assertEqual(route["selected"]["model_alias"], "glm-5.2-ultrafast")

    def test_last_resort_also_serves_role_slot_and_domain_selectors(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes", domain="x_platform_data", active_models=self._SOL_ONLY
        )
        self.assertEqual(route["source"], "last_resort_chain")
        self.assertEqual(route["selected"]["model_alias"], "gpt-5.6-sol")
        self.assertEqual(
            route["inactive_candidates"],
            ["grok-code-fast", "kimi-k3", "gemini-3.1-pro", "claude-opus-5"],
        )

    def test_unavailable_explicit_model_stays_fail_closed_against_last_resort(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            explicit_model="glm-5.2-ultrafast",
            active_models=self._OPUS_ONLY,
        )
        self.assertEqual(route["status"], "choice_required")
        self.assertIsNone(route["selected"])

    def test_no_active_model_at_all_still_reaches_owner_default(self) -> None:
        route = resolve_model_recommendation(owner="hermes", category="quick", active_models=[])
        self.assertEqual(route["status"], "owner_default")
        self.assertEqual(
            route["inactive_candidates"],
            [
                "glm-5.3-flash",
                "glm-5.2-ultrafast",
                "kimi-k3",
                "gpt-5.6-luna",
                "claude-fable-5-1",
                "claude-fable-5",
                "claude-opus-5",
                "gpt-5.6-sol",
            ],
        )

    def test_maestro_projection_carries_the_whole_last_resort_order(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="quick",
            active_models=(*self._OPUS_ONLY, *self._SOL_ONLY),
        )
        self.assertEqual(
            [entry["model_alias"] for entry in route["projection"]["chain"]],
            ["claude-opus-5", "gpt-5.6-sol"],
        )

    def test_last_resort_chain_is_user_overridable_through_the_same_closed_surface(self) -> None:
        override = load_recommendation_overrides({
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "last_resort": {"any": [{
                "model_alias": "gemini-3.1-pro",
                "model_family": "gemini",
                "preferred_provider_families": ["google"],
                "reasoning": "Operator-selected final attempt.",
            }]},
        })
        route = resolve_model_recommendation(
            owner="hermes",
            category="quick",
            active_models=[_active("gemini-3.1-pro", provider="google", family="gemini")],
            overrides=override,
        )
        self.assertEqual(route["source"], "last_resort_chain")
        self.assertEqual(route["selected"]["model_alias"], "gemini-3.1-pro")
        self.assertEqual(route["selected"]["recommendation_source"], "user_override")
        self.assertEqual(
            SHIPPED_MODEL_RECOMMENDATIONS["last_resort"]["any"][0]["model_alias"],
            "claude-opus-5",
        )

    def test_override_rejects_unknown_last_resort_slots_and_secret_fields(self) -> None:
        bad_payloads = (
            {
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "last_resort": {"quick": []},
            },
            {
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "last_resort": {"any": [{
                    "model_alias": "gemini-3.1-pro", "model_family": "gemini",
                    "preferred_provider_families": ["google"],
                    "reasoning": "x", "api_key": "must-not-be-stored",
                }]},
            },
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    load_recommendation_overrides(payload)


if __name__ == "__main__":
    unittest.main()
