from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402
from omh.coding.model_contracts import (  # noqa: E402
    EFFORT_FLOOR_KIND,
    MODEL_CONTRACTS,
    MODEL_CONTRACT_CLAIM_BOUNDARY,
    contract_effort_floor,
    contract_model_id,
    dynamic_effort_guidance,
    model_contract,
    model_contract_projection,
)
from omh.coding.model_routing import (  # noqa: E402
    EFFORT_CHANGE_KINDS,
    EXECUTOR_MODEL_OPTIONS,
    REASONING_EFFORT_LADDER,
    model_family,
    resolve_model_route,
)
from omh.coding.unit_prompt_protocol import (  # noqa: E402
    HIGH_EFFORT_CALIBRATIONS,
    MAIN_AGENT_COMPOSITION_CALIBRATIONS,
    MODEL_COMPOSITION_CALIBRATIONS,
    MODEL_HIGH_EFFORT_CALIBRATIONS,
    calibration_for_route,
    composition_calibration_for_model,
)
from omh.plugin_bundle.omh.hermes_delegation import APPROX_PRICE_PER_MTOK  # noqa: E402

_ASTRA_FORMS = ("gpt-6-astra", "openai/gpt-6-astra", "openai-codex/gpt-6-astra", "GPT-6-Astra")
_ASTRA_VARIANTS = {
    "gpt-6-astra": ("standard", "standard", "exact"),
    "gpt-6-astra-fast": ("standard", "fast", "declared_inheritance"),
    "gpt-6-astra-flex": ("standard", "flex", "declared_inheritance"),
    "gpt-6-astra-pro": ("pro", "standard", "declared_inheritance"),
    "gpt-6-astra-pro-fast": ("pro", "fast", "declared_inheritance"),
    "gpt-6-astra-pro-flex": ("pro", "flex", "declared_inheritance"),
}
_MONITORING_WORDS = ("monitor", "watching you", "chain of thought", "chain-of-thought", "reasoning trace")


class AstraRecognitionTests(unittest.TestCase):
    """Step 1 of docs/MODEL-ONBOARDING.md: what the router sees."""

    def test_every_served_form_classifies_as_gpt(self) -> None:
        for form in _ASTRA_FORMS:
            self.assertEqual(model_family(form), "gpt", form)
            self.assertEqual(contract_model_id(form), "gpt-6-astra", form)

    def test_bare_chat_name_stays_unknown_and_siblings_carry_no_contract(self) -> None:
        # Decision recorded in MODEL_OPTI.md: no bare `astra` alias, matching
        # how `sol`/`terra`/`luna` are handled; and the contract is exact, so
        # a hypothetical sibling id keeps the family-only treatment.
        self.assertEqual(model_family("astra"), "unknown")
        self.assertIsNone(model_contract("astra"))
        self.assertIsNone(model_contract("gpt-6-terra"))
        self.assertIsNone(model_contract("gpt-5.6-sol"))
        self.assertIsNone(model_contract(""))


class ContractRecordTests(unittest.TestCase):
    def test_declared_astra_forms_resolve_a_bounded_projection(self) -> None:
        base = model_contract("gpt-6-astra")
        for model_id, (mode, tier, provenance) in _ASTRA_VARIANTS.items():
            requested = f"openai/{model_id}"
            projection = model_contract_projection(requested)
            assert projection is not None
            with self.subTest(model_id=model_id):
                self.assertEqual(projection["schema_version"], "model_contract_projection/v1")
                self.assertEqual(projection["requested_model"], requested)
                self.assertEqual(projection["canonical_model_id"], model_id)
                self.assertEqual(projection["contract_model_id"], "gpt-6-astra")
                self.assertEqual(projection["reasoning_mode"], mode)
                self.assertEqual(projection["service_tier"], tier)
                self.assertEqual(projection["provenance"], provenance)
                self.assertIs(model_contract(requested), base)

        for model_id in (
            "gpt-6-astra-turbo",
            "gpt-6-astra-fast-pro",
            "gpt-6-astra-pro-flex-fast",
            "gpt-6-astra-pro-pro",
        ):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))
                self.assertIsNone(model_contract(model_id))
                self.assertEqual(contract_model_id(model_id), model_id)

    def test_exact_child_contract_overrides_an_older_declared_projection(self) -> None:
        from unittest import mock

        exact_child = dict(MODEL_CONTRACTS["gpt-6-astra"])
        exact_child.update(
            {
                "model_id": "gpt-6-astra-pro",
                "reasoning_mode": "dedicated-pro",
                "service_tier": "dedicated",
            }
        )
        with mock.patch.dict(MODEL_CONTRACTS, {"gpt-6-astra-pro": exact_child}):
            projection = model_contract_projection("openai/gpt-6-astra-pro")
            assert projection is not None
            self.assertEqual(projection["provenance"], "exact")
            self.assertEqual(projection["contract_model_id"], "gpt-6-astra-pro")
            self.assertEqual(projection["reasoning_mode"], "dedicated-pro")
            self.assertEqual(projection["service_tier"], "dedicated")
            self.assertIs(model_contract("openai/gpt-6-astra-pro"), exact_child)

    def test_contract_is_documented_and_bounded(self) -> None:
        contract = model_contract("gpt-6-astra")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(contract["effort_floor"], "low")
        self.assertEqual(contract["effort_default"], "")
        self.assertEqual(contract["tool_calling"]["api"], "responses")
        self.assertEqual(contract["pricing_usd_per_mtok"]["input"], 10.0)
        self.assertEqual(contract["pricing_usd_per_mtok"]["output"], 50.0)
        self.assertEqual(contract["pricing_usd_per_mtok"]["cache_write"], 12.5)
        self.assertTrue(all(source.startswith("https://") for source in contract["sources"]))
        self.assertEqual(contract["claim_boundary"], MODEL_CONTRACT_CLAIM_BOUNDARY)
        self.assertEqual(contract["dynamic_effort"]["compatible_profiles"], ())
        self.assertEqual(contract["dynamic_effort"]["status"], "documented_not_observed")
        for value in contract["runtime_mechanisms"].values():
            self.assertEqual(value, "documented_not_observed")
        # No entitlement language anywhere in the record.
        self.assertNotIn("entitled", json.dumps(dict(contract)).casefold())

    def test_every_contract_ladder_is_canonical_vocabulary(self) -> None:
        for model_id, contract in MODEL_CONTRACTS.items():
            for effort in contract["reasoning_efforts"]:
                self.assertIn(effort, REASONING_EFFORT_LADDER, model_id)
            self.assertIn(contract["effort_floor"], contract["reasoning_efforts"], model_id)
            for effort in contract["unsupported_efforts"]:
                self.assertIn(effort, REASONING_EFFORT_LADDER, model_id)
                self.assertNotIn(effort, contract["reasoning_efforts"], model_id)

    def test_price_row_mirrors_the_contract_and_cites_its_source(self) -> None:
        contract = model_contract("gpt-6-astra")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6-astra"], (pricing["input"], pricing["output"]))

    def test_codex_catalog_row_mirrors_the_contract_ladder(self) -> None:
        row = next(option for option in EXECUTOR_MODEL_OPTIONS["codex"] if option["model_id"] == "gpt-6-astra")
        contract = model_contract("gpt-6-astra")
        assert contract is not None
        self.assertEqual(row["reasoning_efforts"], contract["reasoning_efforts"])


class EffortFloorTests(unittest.TestCase):
    def test_floor_kind_is_route_vocabulary(self) -> None:
        self.assertIn(EFFORT_FLOOR_KIND, EFFORT_CHANGE_KINDS)

    def test_helper_answers_only_for_documented_unsupported_rungs(self) -> None:
        self.assertEqual(contract_effort_floor("gpt-6-astra", "off")[0], "low")
        self.assertEqual(contract_effort_floor("openai/gpt-6-astra", "MINIMAL")[0], "low")
        self.assertIsNone(contract_effort_floor("gpt-6-astra", "low"))
        self.assertIsNone(contract_effort_floor("gpt-6-astra", "max"))
        self.assertIsNone(contract_effort_floor("gpt-6-astra", ""))
        self.assertIsNone(contract_effort_floor("gpt-6-astra", "turbo-9"))
        self.assertIsNone(contract_effort_floor("gpt-5.6-sol", "off"))

    def test_below_floor_requests_are_raised_on_record_for_every_profile(self) -> None:
        for profile in ("codex", "hermes", "claude-code", "generic"):
            for requested in ("off", "none", "minimal"):
                route = resolve_model_route(profile, requested_model="gpt-6-astra", requested_effort=requested)
                with self.subTest(profile=profile, requested=requested):
                    self.assertEqual(route["selected_model"], "gpt-6-astra")
                    self.assertEqual(route["model_family"], "gpt")
                    self.assertEqual(route["selected_reasoning_effort"], "low")
                    change = route["effort_change"]
                    self.assertEqual(change["kind"], EFFORT_FLOOR_KIND)
                    self.assertEqual(change["requested"], requested)
                    self.assertEqual(change["selected"], "low")
                    self.assertIn("documented floor", change["reason"])

    def test_declared_astra_forms_keep_requested_identity_and_contract_receipt(self) -> None:
        for model_id, (mode, tier, provenance) in _ASTRA_VARIANTS.items():
            requested = f"openai/{model_id}"
            route = resolve_model_route("hermes", requested_model=requested, requested_effort="none")
            with self.subTest(model_id=model_id):
                self.assertEqual(route["selected_model"], requested)
                self.assertEqual(route["selected_reasoning_effort"], "low")
                self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
                receipt = route["model_contract"]
                self.assertEqual(receipt["requested_model"], requested)
                self.assertEqual(receipt["canonical_model_id"], model_id)
                self.assertEqual(receipt["contract_model_id"], "gpt-6-astra")
                self.assertEqual(receipt["reasoning_mode"], mode)
                self.assertEqual(receipt["service_tier"], tier)
                self.assertEqual(receipt["provenance"], provenance)
                self.assertIn("not evidence", receipt["claim_boundary"])

    def test_supported_requests_pass_unchanged_and_provider_prefix_is_kept(self) -> None:
        for requested in ("low", "medium", "high", "xhigh", "max"):
            route = resolve_model_route("codex", requested_model="gpt-6-astra", requested_effort=requested)
            self.assertEqual(route["selected_reasoning_effort"], requested)
            self.assertEqual(route["effort_change"]["kind"], "unchanged")
        route = resolve_model_route("hermes", requested_model="openai/gpt-6-astra", requested_effort="off")
        self.assertEqual(route["selected_model"], "openai/gpt-6-astra")
        self.assertEqual(route["selected_reasoning_effort"], "low")
        self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)

    def test_hermes_recommendation_path_applies_the_same_floor(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="brain",
            requested_effort="off",
            requested_category="ultrabrain",
            active_models=("gpt-6-astra",),
        )
        self.assertEqual(route["selected_model"], "gpt-6-astra")
        self.assertEqual(route["selected_reasoning_effort"], "low")
        self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        # A model without a contract keeps the previous behavior byte for byte.
        route = resolve_model_route(
            "hermes",
            role="brain",
            requested_effort="off",
            requested_category="ultrabrain",
            active_models=("gpt-5.6-sol",),
        )
        self.assertEqual(route["selected_reasoning_effort"], "off")
        self.assertNotIn("effort_change", route)

    def test_a_model_the_catalog_has_not_met_is_never_labeled_supported(self) -> None:
        # The Astra catalog row adds `max` to the codex profile union; that
        # union is advisory, so an unknown model's in-vocabulary request is
        # still a no-authority passthrough, never "supported as requested".
        route = resolve_model_route("codex", requested_model="gpt-6-terra", requested_effort="xhigh")
        self.assertEqual(route["selected_reasoning_effort"], "xhigh")
        self.assertEqual(route["effort_change"]["kind"], "catalog_no_authority_passthrough")


class VersionAwareCalibrationTests(unittest.TestCase):
    def test_override_tables_share_one_key_set_and_name_contracted_models(self) -> None:
        self.assertEqual(set(MODEL_HIGH_EFFORT_CALIBRATIONS), set(MODEL_COMPOSITION_CALIBRATIONS))
        for model_id in MODEL_HIGH_EFFORT_CALIBRATIONS:
            self.assertIn(model_id, MODEL_CONTRACTS)
            self.assertTrue(MODEL_HIGH_EFFORT_CALIBRATIONS[model_id].startswith("High-effort calibration:"))
            self.assertTrue(MODEL_COMPOSITION_CALIBRATIONS[model_id].startswith("Composition calibration:"))

    def test_exact_model_resolves_before_family_and_family_stays_byte_stable(self) -> None:
        astra = {"selected_model": "openai/gpt-6-astra", "model_family": "gpt", "selected_reasoning_effort": "xhigh"}
        sol = {"selected_model": "gpt-5.6-sol", "model_family": "gpt", "selected_reasoning_effort": "xhigh"}
        self.assertEqual(calibration_for_route(astra), MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"])
        self.assertEqual(calibration_for_route(sol), HIGH_EFFORT_CALIBRATIONS["gpt"])
        self.assertNotEqual(calibration_for_route(astra), calibration_for_route(sol))
        # The measurement arm: the block Astra would inherit if the override
        # were removed, which is exactly Sol's block.
        self.assertEqual(calibration_for_route(astra, family_only=True), HIGH_EFFORT_CALIBRATIONS["gpt"])
        self.assertEqual(calibration_for_route(astra, family_only=True), calibration_for_route(sol))
        self.assertEqual(calibration_for_route({**astra, "selected_reasoning_effort": "low"}, family_only=True), "")
        self.assertEqual(
            composition_calibration_for_model("gpt-6-astra"), MODEL_COMPOSITION_CALIBRATIONS["gpt-6-astra"]
        )
        self.assertEqual(composition_calibration_for_model("gpt-5.6-sol"), MAIN_AGENT_COMPOSITION_CALIBRATIONS["gpt"])
        self.assertEqual(composition_calibration_for_model("gpt-6-terra"), MAIN_AGENT_COMPOSITION_CALIBRATIONS["gpt"])

    def test_declared_astra_forms_inherit_both_exact_model_calibrations(self) -> None:
        for model_id in _ASTRA_VARIANTS:
            route = {
                "selected_model": f"openai/{model_id}",
                "model_family": "gpt",
                "selected_reasoning_effort": "xhigh",
            }
            with self.subTest(model_id=model_id):
                self.assertEqual(
                    calibration_for_route(route),
                    MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"],
                )
                self.assertEqual(
                    composition_calibration_for_model(f"openai/{model_id}"),
                    MODEL_COMPOSITION_CALIBRATIONS["gpt-6-astra"],
                )

    def test_override_still_requires_the_high_tier(self) -> None:
        route = {"selected_model": "gpt-6-astra", "model_family": "gpt", "selected_reasoning_effort": "low"}
        self.assertEqual(calibration_for_route(route), "")

    def test_astra_counters_name_the_documented_traits_and_nothing_about_monitoring(self) -> None:
        subagent = MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"]
        composer = MODEL_COMPOSITION_CALIBRATIONS["gpt-6-astra"]
        self.assertIn("instructions outrank", subagent)
        self.assertIn("materially change the result", subagent)
        self.assertIn("Size tests to the change", subagent)
        self.assertIn("Delegate every unit that is independent", composer)
        self.assertIn("documented floor", composer)
        self.assertIn("next prepared unit", composer)
        for text in (subagent, composer):
            lowered = text.casefold()
            for word in _MONITORING_WORDS:
                self.assertNotIn(word, lowered, word)


class DynamicEffortGuidanceTests(unittest.TestCase):
    def test_no_prepared_profile_is_told_it_can_change_effort_mid_conversation(self) -> None:
        for profile in ("", "codex", "hermes", "claude-code", "generic"):
            policy = dynamic_effort_guidance("gpt-6-astra", profile)
            assert policy is not None
            with self.subTest(profile=profile):
                self.assertEqual(policy["mode"], "per_turn")
                self.assertEqual(policy["effort_floor"], "low")
                self.assertIn("no mid-conversation change is claimed", policy["note"])
                self.assertEqual(policy["status"], "documented_not_observed")
        self.assertIsNone(dynamic_effort_guidance("gpt-5.6-sol", "codex"))

    def test_a_contract_naming_a_compatible_profile_switches_the_mode(self) -> None:
        contract = dict(MODEL_CONTRACTS["gpt-6-astra"])
        contract["dynamic_effort"] = dict(contract["dynamic_effort"], compatible_profiles=("lab-runtime",))
        from unittest import mock

        with mock.patch.dict(MODEL_CONTRACTS, {"gpt-6-astra": contract}):
            policy = dynamic_effort_guidance("gpt-6-astra", "lab-runtime")
            assert policy is not None
            self.assertEqual(policy["mode"], "mid_conversation")
            self.assertEqual(policy["mechanism"], "configuration_update")
            self.assertIn("standard single-agent", policy["scope"])
            self.assertTrue(policy["constraints"])
            self.assertEqual(dynamic_effort_guidance("gpt-6-astra", "codex")["mode"], "per_turn")


class ModelOptiDocCoverageTests(unittest.TestCase):
    def test_every_exact_model_override_has_a_documented_section(self) -> None:
        from pathlib import Path

        doc = (Path(__file__).resolve().parents[1] / "MODEL_OPTI.md").read_text(encoding="utf-8")
        for model_id in MODEL_HIGH_EFFORT_CALIBRATIONS:
            self.assertIn(f"### `{model_id}`", doc, model_id)
        self.assertIn("MODEL_CONTRACTS", doc)
        self.assertIn("MODEL_HIGH_EFFORT_CALIBRATIONS", doc)
        self.assertIn("floor_raised", doc)


class ModelContractCliTests(unittest.TestCase):
    def test_model_contract_prints_the_record_and_the_per_turn_policy(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "model-contract", "--model", "openai/gpt-6-astra", "--json"])
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "model_contract_report/v1")
        self.assertEqual(payload["family"], "gpt")
        self.assertEqual(payload["contract"]["model_id"], "gpt-6-astra")
        self.assertEqual(payload["effort_policy"]["mode"], "per_turn")
        status, stdout, _stderr = run_cli(
            ["coding", "model-contract", "--model", "gpt-6-astra", "--executor", "codex"], output_json=False
        )
        self.assertEqual(status, 0)
        self.assertIn("floor `low`", stdout)
        self.assertIn("effort policy (per_turn)", stdout)
        self.assertIn(MODEL_CONTRACT_CLAIM_BOUNDARY, stdout)

    def test_declared_variant_report_exposes_projection_instead_of_base_mode(self) -> None:
        status, stdout, stderr = run_cli(
            [
                "coding",
                "model-contract",
                "--model",
                "openai/gpt-6-astra-pro-fast",
                "--json",
            ]
        )
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            payload["projection"],
            model_contract_projection("openai/gpt-6-astra-pro-fast"),
        )
        self.assertEqual(payload["projection"]["requested_model"], "openai/gpt-6-astra-pro-fast")
        self.assertEqual(payload["projection"]["contract_model_id"], "gpt-6-astra")
        self.assertEqual(payload["projection"]["reasoning_mode"], "pro")
        self.assertEqual(payload["projection"]["service_tier"], "fast")
        self.assertEqual(payload["projection"]["provenance"], "declared_inheritance")

    def test_declared_variant_plain_report_names_mode_tier_and_inheritance(self) -> None:
        status, stdout, stderr = run_cli(
            ["coding", "model-contract", "--model", "openai/gpt-6-astra-pro-fast"],
            output_json=False,
        )
        self.assertEqual(status, 0, stderr)
        self.assertIn("declared_inheritance", stdout)
        self.assertIn("reasoning mode `pro`", stdout)
        self.assertIn("service tier `fast`", stdout)

    def test_model_contract_refuses_a_model_without_a_record(self) -> None:
        status, _stdout, stderr = run_cli(["coding", "model-contract", "--model", "gpt-5.6-sol"], output_json=False)
        self.assertNotEqual(status, 0)
        self.assertIn("no documented contract", stderr)

    def test_composition_guide_carries_the_effort_policy_only_for_contracted_models(self) -> None:
        status, stdout, _stderr = run_cli(
            ["coding", "composition-guide", "--model", "gpt-6-astra", "--executor", "codex", "--json"]
        )
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["calibration"], MODEL_COMPOSITION_CALIBRATIONS["gpt-6-astra"])
        self.assertEqual(payload["effort_policy"]["mode"], "per_turn")
        status, stdout, _stderr = run_cli(["coding", "composition-guide", "--model", "gpt-5.6-sol", "--json"])
        self.assertEqual(status, 0)
        self.assertNotIn("effort_policy", json.loads(stdout))
        status, stdout, _stderr = run_cli(["coding", "composition-guide", "--json"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout)["model_calibrations"], MODEL_COMPOSITION_CALIBRATIONS)


if __name__ == "__main__":
    unittest.main()
