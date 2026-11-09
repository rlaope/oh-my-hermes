from __future__ import annotations

import json
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.model_recommendations import (  # noqa: E402
    MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
)
from omh.coding.model_routing import resolve_model_route  # noqa: E402
from omh.coding.model_discovery_adapters import RUNTIME_CONFIG_SOURCE


def _active(alias: str, provider: str, family: str) -> dict[str, object]:
    return {
        "model_alias": alias,
        "model_id": alias,
        "provider": provider,
        "provider_family": provider,
        "model_family": family,
        "compatible_owners": ["hermes"],
        "status": "confirmed_active",
    }


_KIMI = _active("kimi-k3.1-pro", "apitopia", "kimi")
_OPUS = _active("claude-opus-5-5", "ccapi", "claude")
_GROK = _active("grok-build-0.1", "xai", "grok")
_GEMINI = _active("gemini-4-argon", "google", "gemini")
# Shipped chain members (the superseded GLM 5.2 Ultrafast and Fable 5
# entries left the chains on 2026-09-11): the quick head, and the entries
# right behind Opus 5.5 in writing and visual-engineering. Opus 5.5 heads
# both since 2026-10-13, so each category is exercised on a model that only
# its own chain ranks above Kimi K3.1 Pro, the companion every chain ends on.
_GLM_FLASH = _active("glm-5.3-flash", "zai", "glm")
_FABLE = _active("claude-fable-5-1", "ccapi", "claude")
_SONNET = _active("claude-sonnet-5-5", "ccapi", "claude")


_CATEGORY_ACTIVE = {
    "quick": _GLM_FLASH,
    "writing": _SONNET,
    "artistry": _GEMINI,
    "visual-engineering": _FABLE,
}


class HermesRecommendationRoutingTests(unittest.TestCase):
    def test_every_closed_category_has_an_editable_nonempty_editorial_chain(self) -> None:
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS
        from omh.coding.model_routing import MODEL_CATEGORIES

        categories = SHIPPED_MODEL_RECOMMENDATIONS["categories"]
        self.assertEqual(set(categories), set(MODEL_CATEGORIES))
        for category in MODEL_CATEGORIES:
            with self.subTest(category=category):
                self.assertGreater(len(categories[category]), 0)

    def test_category_is_orthogonal_to_role_and_aliases_are_canonical(self) -> None:
        for requested, canonical in (
            ("quick", "quick"),
            ("ulw-writing", "writing"),
            ("ulw-visual", "visual-engineering"),
            ("ulw-artistry", "artistry"),
        ):
            with self.subTest(requested=requested):
                active = _CATEGORY_ACTIVE[canonical]
                route = resolve_model_route(
                    "hermes",
                    role="implementation",
                    requested_category=requested,
                    active_models=[active, _KIMI],
                )
                self.assertEqual(route["category"], canonical)
                self.assertEqual(route["role"], "implementation")
                self.assertEqual(route["selected_model"], f"{active['provider']}/{active['model_id']}")

    def test_non_category_text_does_not_trigger_a_category(self) -> None:
        from omh.coding.model_routing import category_from_text

        for message in (
            "the visual-engineering docs mention routing",
            "make this quick please",
            "the writer discussed artistry",
            "ulw-visual-engineering-ish is not a route",
        ):
            with self.subTest(message=message):
                self.assertEqual(category_from_text(message), "")

    def test_route_consumes_hermes_native_recommendation_projection(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            active_models=[_KIMI, _OPUS],
        )

        recommendation = route["recommendation"]
        projection = recommendation["projection"]
        self.assertEqual(recommendation["owner"], "hermes")
        self.assertEqual(projection["kind"], "hermes_native_binding")
        self.assertEqual(projection["binding"], route["selected_model"])
        self.assertNotEqual(projection["kind"], "maestro_ordered_chain")

    def test_missing_recommended_head_falls_through_confirmed_active_chain(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            active_models=[_OPUS],
        )

        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["provenance"], "recommendation_chain_head")
        self.assertEqual(route["selected_model"], "ccapi/claude-opus-5-5")
        self.assertEqual(
            [entry["model_id"] for entry in route["chain"]],
            ["ccapi/claude-opus-5-5"],
        )
        recommendation = route["recommendation"]
        # The default working chain heads on GPT-6.1 Sol since 2026-10-13.
        self.assertEqual(recommendation["inactive_candidates"][0], "gpt-6.1-sol")

    def test_dated_snapshot_counts_as_its_base_and_routes_as_served(self) -> None:
        from omh.coding.model_recommendations import resolve_model_recommendation

        # A provider that serves only `<base>-YYYY-MM-DD` ids (reported
        # 2026-09-11 for gpt-5.6-terra / gpt-5.6-luna): the snapshot satisfies
        # the chain entry naming its base, and the route carries the id as
        # served rather than the catalog spelling. Both 5.6 ids left the
        # shipped chains on 2026-09-23, so the rule is held on an id `deep`
        # names (second behind Opus 5.5 since 2026-10-13); the date is a
        # shape, not a published snapshot.
        dated = _active("gpt-6.1-sol-2026-09-29", "openai", "gpt")
        recommendation = resolve_model_recommendation(owner="hermes", active_models=[dated], category="deep")
        self.assertEqual(recommendation["status"], "resolved")
        self.assertEqual(recommendation["selected"]["model_alias"], "gpt-6.1-sol")
        self.assertEqual(recommendation["selected"]["model_id"], "gpt-6.1-sol-2026-09-29")
        qualified = _active("openai/gpt-6.1-sol-2026-09-29", "openai", "gpt")
        self.assertEqual(
            resolve_model_recommendation(owner="hermes", active_models=[qualified], category="deep")["status"],
            "resolved",
        )
        # An explicit request for the base is met by its confirmed snapshot;
        # a request pinned to a date is not met by an unpinned base.
        self.assertEqual(
            resolve_model_recommendation(owner="hermes", active_models=[dated], explicit_model="gpt-6.1-sol")["status"],
            "resolved",
        )
        self.assertEqual(
            resolve_model_recommendation(
                owner="hermes",
                active_models=[_active("gpt-6.1-sol", "openai", "gpt")],
                explicit_model="gpt-6.1-sol-2026-09-29",
            )["status"],
            "choice_required",
        )
        # A date on a base no chain names still resolves nothing.
        unknown = _active("gpt-7-nova-2026-07-09", "openai", "gpt")
        self.assertEqual(
            resolve_model_recommendation(owner="hermes", active_models=[unknown], category="deep")["status"],
            "owner_default",
        )

    def test_no_confirmed_candidate_uses_the_hermes_executor_default(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            active_models=[],
        )

        self.assertEqual(route["status"], "model_unrouted")
        self.assertEqual(route["provenance"], "executor_default")
        self.assertEqual(route["selected_model"], "")
        self.assertEqual(route["chain"], [])
        self.assertEqual(route["recommendation"]["status"], "owner_default")
        outcomes = {
            entry["stage"]: entry["outcome"]
            for entry in route["attempted"]
        }
        self.assertEqual(outcomes["recommendation_chain"], "owner_default")
        self.assertEqual(outcomes["executor_default"], "selected")

    def test_dead_category_chain_routes_hermes_through_the_shared_last_resort(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            requested_category="quick",
            active_models=[_OPUS],
        )

        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["provenance"], "recommendation_chain_head")
        self.assertEqual(route["selected_model"], "ccapi/claude-opus-5-5")
        self.assertEqual(route["recommendation"]["source"], "last_resort_chain")
        outcomes = {entry["stage"]: entry["outcome"] for entry in route["attempted"]}
        self.assertEqual(outcomes["recommendation_chain"], "last_resort")

    def test_domain_candidate_replaces_category_last_resort_and_projection(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            requested_category="quick",
            requested_domain="x_platform_data",
            active_models=[_OPUS, _GROK],
        )

        self.assertEqual(route["selected_model"], "xai/grok-build-0.1")
        self.assertEqual(route["recommendation"]["source"], "recommendation_chain")
        self.assertEqual(route["recommendation"]["projection"]["binding"], "xai/grok-build-0.1")
        outcomes = {entry["stage"]: entry["outcome"] for entry in route["attempted"]}
        self.assertEqual(outcomes["domain_affinity"], "reordered")
        self.assertEqual(outcomes["recommendation_chain"], "selected")

    def test_domain_last_resort_never_outranks_an_active_category_candidate(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            requested_category="quick",
            requested_domain="x_platform_data",
            active_models=[_GLM_FLASH, _OPUS],
        )

        self.assertEqual(route["selected_model"], "zai/glm-5.3-flash")
        self.assertEqual(
            route["recommendation"]["projection"]["binding"],
            "zai/glm-5.3-flash",
        )
        affinity = next(
            entry for entry in route["attempted"] if entry["stage"] == "domain_affinity"
        )
        self.assertEqual(affinity["outcome"], "last_resort_deferred")

    def test_x_platform_domain_stably_promotes_grok_kimi_gemini_without_removal(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            active_models=[_OPUS, _GEMINI, _KIMI, _GROK],
        )

        chain = [entry["model_id"] for entry in route["chain"]]
        self.assertEqual(
            chain,
            [
                "xai/grok-build-0.1",
                "apitopia/kimi-k3.1-pro",
                "google/gemini-4-argon",
                "ccapi/claude-opus-5-5",
            ],
        )
        self.assertEqual(route["selected_model"], "xai/grok-build-0.1")
        affinity = next(
            entry for entry in route["attempted"] if entry["stage"] == "domain_affinity"
        )
        self.assertEqual(affinity["outcome"], "reordered")
        self.assertIn("no entry removed", affinity["reason"])

    def test_missing_grok_falls_through_to_kimi_then_gemini(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            active_models=[_GEMINI, _KIMI],
        )

        self.assertEqual(route["selected_model"], "apitopia/kimi-k3.1-pro")
        self.assertEqual(
            [entry["model_id"] for entry in route["chain"]],
            ["apitopia/kimi-k3.1-pro", "google/gemini-4-argon"],
        )

    def test_explicit_active_model_wins_over_domain_and_explicit_missing_freezes(self) -> None:
        active = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            requested_model="gemini-4-argon",
            active_models=[_GROK, _KIMI, _GEMINI],
        )
        self.assertEqual(active["provenance"], "request_named_model")
        self.assertEqual(active["selected_model"], "google/gemini-4-argon")

        missing = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            requested_model="qwen3-coder",
            active_models=[_GROK, _KIMI, _GEMINI],
        )
        self.assertEqual(missing["status"], "choice_required")
        self.assertEqual(missing["provenance"], "request_named_model_unavailable")
        self.assertEqual(missing["selected_model"], "")
        self.assertEqual(missing["requested_model"], "qwen3-coder")
        self.assertEqual(missing["chain"], [])

    def test_editable_qwen_recommendation_routes_without_pi_family_catalog_relabeling(self) -> None:
        overrides = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {
                "deep": [
                    {
                        "model_alias": "qwen3-coder",
                        "model_family": "qwen",
                        "preferred_provider_families": ["qwen-oauth"],
                        "reasoning_effort": "high",
                        "reasoning": "Operator-selected deep coding route.",
                    }
                ]
            },
        }
        route = resolve_model_route(
            "hermes",
            role="brain",
            active_models=[_active("qwen3-coder", "qwen-oauth", "qwen")],
            recommendation_overrides=overrides,
            local_catalog={
                "schema_version": "local_model_catalog/v1",
                "executor_profile": "pi-family-runtime",
                "options": [{"model_id": "must/not-route"}],
            },
        )

        self.assertEqual(route["selected_model"], "qwen-oauth/qwen3-coder")
        self.assertEqual(route["catalog_kind"], "editorial_recommendations")
        self.assertNotIn("catalog_fingerprint", route)
        self.assertEqual(route["recommendation"]["source"], "recommendation_chain")

    def test_brain_steps_from_ultrabrain_to_deep_before_the_last_resort(self) -> None:
        # brain heads on ultrabrain; a set without an ultrabrain model steps to
        # deep, the next depth tier, and keeps deep's effort instead of the
        # last-resort one.
        astra = _active("gpt-6-astra", "openai-codex", "gpt")
        sol = _active("gpt-6.1-sol", "openai-codex", "gpt")
        for active, model, effort, category in (
            ([_OPUS], "ccapi/claude-opus-5-5", "high", "deep"),
            ([sol], "openai-codex/gpt-6.1-sol", "high", "deep"),
            ([_KIMI], "apitopia/kimi-k3.1-pro", "high", "deep"),
            ([astra, _OPUS], "openai-codex/gpt-6-astra", "xhigh", "ultrabrain"),
        ):
            with self.subTest(active=[entry["model_alias"] for entry in active]):
                route = resolve_model_route("hermes", role="brain", active_models=active)
                self.assertEqual(route["status"], "routed")
                self.assertEqual(route["selected_model"], model)
                self.assertEqual(route["selected_reasoning_effort"], effort)
                self.assertEqual(route["category"], category)
                self.assertEqual(route["recommendation"]["source"], "recommendation_chain")
                stepped = [entry for entry in route["attempted"] if entry["stage"] == "recommendation_category"]
                self.assertEqual(len(stepped), 0 if category == "ultrabrain" else 1)
                for entry in stepped:
                    self.assertEqual(entry["outcome"], "no_active_candidate")
                    self.assertIn("`ultrabrain`", entry["reason"])
                    self.assertIn("`deep` selected", entry["reason"])

    def test_research_deep_and_scale_large_step_to_deep_too(self) -> None:
        for kwargs in ({"role": "research", "requested_depth": "deep"}, {"role": "review", "requested_scale": "large"}):
            with self.subTest(**kwargs):
                route = resolve_model_route("hermes", active_models=[_KIMI], **kwargs)
                self.assertEqual(route["selected_model"], "apitopia/kimi-k3.1-pro")
                self.assertEqual(route["selected_reasoning_effort"], "high")
                self.assertEqual(route["category"], "deep")

    def test_a_non_generative_ultrabrain_candidate_does_not_stop_the_step(self) -> None:
        overrides = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {
                "ultrabrain": [
                    {
                        "model_alias": "jev-1.13.0",
                        "model_family": "jev",
                        "preferred_provider_families": ["typesafe"],
                        "reasoning_effort": "low",
                        "reasoning": "Operator-selected head.",
                    }
                ]
            },
        }
        jev = _active("jev-1.13.0", "typesafe", "jev")
        route = resolve_model_route(
            "hermes", role="brain", active_models=[jev, _OPUS], recommendation_overrides=overrides
        )
        self.assertEqual(route["selected_model"], "ccapi/claude-opus-5-5")
        self.assertEqual(route["selected_reasoning_effort"], "high")
        self.assertEqual(route["category"], "deep")

    def test_requested_category_is_never_widened(self) -> None:
        route = resolve_model_route(
            "hermes", role="brain", requested_category="ultrabrain", active_models=[_OPUS]
        )
        self.assertEqual(route["category"], "ultrabrain")
        self.assertEqual(route["selected_reasoning_effort"], "medium")
        self.assertEqual(route["recommendation"]["source"], "last_resort_chain")
        self.assertNotIn("recommendation_category", [entry["stage"] for entry in route["attempted"]])

        kimi = resolve_model_route(
            "hermes", role="brain", requested_category="ultrabrain", active_models=[_KIMI]
        )
        self.assertEqual(kimi["status"], "model_unrouted")
        self.assertEqual(kimi["provenance"], "executor_default")

    def test_without_a_deep_candidate_the_ultrabrain_resolution_stands(self) -> None:
        dead = [
            {
                "model_alias": "qwen3-coder",
                "model_family": "qwen",
                "preferred_provider_families": ["qwen-oauth"],
                "reasoning_effort": "high",
                "reasoning": "Inactive on purpose.",
            }
        ]
        overrides = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {"ultrabrain": dead, "deep": dead},
        }
        route = resolve_model_route(
            "hermes", role="brain", active_models=[_OPUS], recommendation_overrides=overrides
        )
        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["selected_model"], "ccapi/claude-opus-5-5")
        self.assertEqual(route["selected_reasoning_effort"], "medium")
        self.assertEqual(route["recommendation"]["source"], "last_resort_chain")
        self.assertEqual(route["category"], "ultrabrain")
        self.assertEqual(
            [entry["stage"] + ":" + entry["outcome"] for entry in route["attempted"]],
            ["requested_model:skipped", "recommendation_chain:last_resort"],
        )

    def test_the_step_never_reaches_a_role_that_does_not_head_on_ultrabrain(self) -> None:
        # Values as origin/main resolves them before the step existed.
        glm = resolve_model_route("hermes", role="implementation", active_models=[_active("glm-5.3", "zai", "glm")])
        self.assertEqual(glm["status"], "model_unrouted")
        self.assertEqual(glm["category"], "unspecified-high")
        self.assertEqual(
            [entry["stage"] + ":" + entry["outcome"] for entry in glm["attempted"]],
            ["requested_model:skipped", "recommendation_chain:owner_default", "executor_default:selected"],
        )
        haiku = _active("claude-haiku-5-5", "ccapi", "claude")
        research = resolve_model_route("hermes", role="research", active_models=[haiku, _OPUS])
        self.assertEqual(research["selected_model"], "ccapi/claude-opus-5-5")
        self.assertEqual(research["selected_reasoning_effort"], "medium")
        self.assertEqual(research["category"], "unspecified-low")
        self.assertEqual(research["recommendation"]["source"], "last_resort_chain")
        self.assertEqual(
            [entry["stage"] + ":" + entry["outcome"] for entry in research["attempted"]],
            ["requested_model:skipped", "recommendation_chain:last_resort"],
        )

    def test_a_deep_override_steers_brain_only_without_an_ultrabrain_candidate(self) -> None:
        overrides = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {
                "deep": [
                    {
                        "model_alias": "qwen3-coder",
                        "model_family": "qwen",
                        "preferred_provider_families": ["qwen-oauth"],
                        "reasoning_effort": "high",
                        "reasoning": "Operator-selected deep coding route.",
                    }
                ]
            },
        }
        qwen = _active("qwen3-coder", "qwen-oauth", "qwen")
        astra = _active("gpt-6-astra", "openai-codex", "gpt")
        alone = resolve_model_route("hermes", role="brain", active_models=[qwen], recommendation_overrides=overrides)
        self.assertEqual(alone["selected_model"], "qwen-oauth/qwen3-coder")
        beside = resolve_model_route(
            "hermes", role="brain", active_models=[qwen, astra], recommendation_overrides=overrides
        )
        self.assertEqual(beside["selected_model"], "openai-codex/gpt-6-astra")

    def test_cli_category_routes_independently_from_role(self) -> None:
        inventory = {
            "model_discovery": {
                "observations": [
                    {
                        "source": RUNTIME_CONFIG_SOURCE,
                        "provider": "zai",
                        "model_id": "glm-5.3-flash",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    }
                ]
            }
        }
        with mock.patch("omh.coding.model_inventory.local_model_inventory", return_value=inventory):
            code, stdout, stderr = run_cli(
                [
                    "coding", "model-route", "--executor", "hermes",
                    "--role", "implementation", "--category", "ulw-quick",
                    "--from-inventory", "--json",
                ]
            )
        self.assertEqual((code, stderr), (0, ""))
        route = json.loads(stdout)
        self.assertEqual(route["category"], "quick")
        self.assertEqual(route["role"], "implementation")
        self.assertEqual(route["selected_model"], "zai/glm-5.3-flash")

    def test_cli_routes_hermes_from_confirmed_discovery_and_freezes_missing_explicit(self) -> None:
        inventory = {
            "model_discovery": {
                "observations": [
                    {
                        "source": RUNTIME_CONFIG_SOURCE,
                        "provider": "xai",
                        "model_id": "grok-build-0.1",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    },
                    {
                        "source": RUNTIME_CONFIG_SOURCE,
                        "provider": "apitopia",
                        "model_id": "kimi-k3.1-pro",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    },
                    {
                        "source": RUNTIME_CONFIG_SOURCE,
                        "provider": "google",
                        "model_id": "gemini-4-argon",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    },
                ]
            }
        }
        with mock.patch("omh.coding.model_inventory.local_model_inventory", return_value=inventory):
            code, stdout, _stderr = run_cli(
                [
                    "coding",
                    "model-route",
                    "--executor",
                    "hermes",
                    "--role",
                    "implementation",
                    "--domain",
                    "x_platform_data",
                    "--from-inventory",
                    "--json",
                ]
            )
            missing_code, missing_stdout, _missing_stderr = run_cli(
                [
                    "coding",
                    "model-route",
                    "--executor",
                    "hermes",
                    "--role",
                    "implementation",
                    "--model",
                    "qwen3-coder",
                    "--from-inventory",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(missing_code, 0)
        self.assertEqual(json.loads(stdout)["selected_model"], "xai/grok-build-0.1")
        self.assertEqual(json.loads(missing_stdout)["status"], "choice_required")


if __name__ == "__main__":
    unittest.main()
