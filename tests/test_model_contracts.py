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
    MODEL_CLASSES,
    NON_GENERATIVE_MODEL_CLASS,
    REASONING_EFFORT_LADDER,
    model_class,
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

    def test_a_declared_contract_class_is_canonical_vocabulary(self) -> None:
        # The key is optional and hand-written per contract, and both the
        # renderer and the ladder branch key on one exact spelling. A typo
        # would silently render and route as generative, which is the one
        # failure this class exists to prevent.
        for model_id, contract in MODEL_CONTRACTS.items():
            if "model_class" in contract:
                self.assertIn(contract["model_class"], MODEL_CLASSES, model_id)

    def test_every_contract_ladder_is_canonical_vocabulary(self) -> None:
        for model_id, contract in MODEL_CONTRACTS.items():
            for effort in contract["reasoning_efforts"]:
                # `none` is the vendor spelling of the canonical `off` rung.
                # A contract may record it verbatim (GPT-6 Luna documents it
                # as a rung), and the route then keeps that spelling.
                self.assertIn("off" if effort == "none" else effort, REASONING_EFFORT_LADDER, model_id)
            if contract.get("model_class") == NON_GENERATIVE_MODEL_CLASS:
                # A model that answers typed questions carries no effort
                # parameter at all: the request is a `state` plus a question
                # map. Empty is therefore the DOCUMENTED reading, not an
                # unread one, and it has to be empty on every rung at once --
                # no ladder, no floor, no default, and nothing declared
                # unsupported, because "unsupported" is a claim about a
                # ladder that does not exist. The generative assertion below
                # is not loosened to let this through.
                self.assertEqual(contract["reasoning_efforts"], (), model_id)
                self.assertEqual(contract["effort_floor"], "", model_id)
                self.assertEqual(contract["effort_default"], "", model_id)
                self.assertEqual(contract["unsupported_efforts"], {}, model_id)
                continue
            self.assertIn(contract["effort_floor"], contract["reasoning_efforts"], model_id)
            for effort in contract["unsupported_efforts"]:
                self.assertIn(effort, REASONING_EFFORT_LADDER, model_id)
                self.assertNotIn(effort, contract["reasoning_efforts"], model_id)

    def test_only_a_non_generative_contract_may_declare_an_empty_ladder(self) -> None:
        # The other half of the branch above, so neither direction drifts: a
        # generative contract that lost its ladder must fail rather than be
        # read as a typed-answer model, and the class the branch keys on is
        # the one the router refuses on.
        for model_id, contract in MODEL_CONTRACTS.items():
            with self.subTest(model=model_id):
                empty_ladder = contract["reasoning_efforts"] == ()
                non_generative = contract.get("model_class") == NON_GENERATIVE_MODEL_CLASS
                self.assertEqual(empty_ladder, non_generative)
                if non_generative:
                    self.assertEqual(model_class(model_id), NON_GENERATIVE_MODEL_CLASS)

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
        # (GPT-5.6 Sol and then Kimi K3, the earlier subjects here, left the
        # shipped chains on 2026-09-23 and 2026-10-24; GLM 5.3 Flash has no
        # contract and heads `quick`.)
        route = resolve_model_route(
            "hermes",
            role="brain",
            requested_effort="off",
            requested_category="quick",
            active_models=("glm-5.3-flash",),
        )
        self.assertEqual(route["selected_model"], "glm-5.3-flash")
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


_DEEPSEEK_FORMS = (
    "deepseek-v4.1-flash",
    "deepseek/deepseek-v4.1-flash",
    "openrouter/deepseek-v4.1-flash",
    "DeepSeek-V4.1-Flash",
)


class DeepSeekV41FlashTests(unittest.TestCase):
    """The second exact contract (2026-09-11): a vendor whose undocumented
    rungs map to a neighbour instead of erroring, and whose first-party id
    is a moving pointer declared with a read date."""

    def test_every_served_form_resolves_the_exact_contract(self) -> None:
        for form in _DEEPSEEK_FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "deepseek")
                self.assertEqual(contract_model_id(form), "deepseek-v4.1-flash")
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")
                self.assertEqual(projection["reasoning_mode"], "thinking")

    def test_first_party_pointer_is_a_declared_projection_not_a_second_contract(self) -> None:
        for form in ("deepseek-flash", "deepseek/deepseek-flash"):
            with self.subTest(form=form):
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["contract_model_id"], "deepseek-v4.1-flash")
                self.assertEqual(projection["provenance"], "declared_inheritance")
                self.assertEqual(projection["requested_model"], form)
        self.assertNotIn("deepseek-flash", MODEL_CONTRACTS)
        # The vendor routes `deepseek-v4-flash` to V4.1 Flash on its own API;
        # that is a wire concern, not an inheritance the catalog declares.
        # `deepseek-v4-pro` is a separately priced model and the others are
        # other generations or the bare vendor word: none projects.
        for form in ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v3.2", "deepseek"):
            with self.subTest(form=form):
                self.assertIsNone(model_contract_projection(form))

    def test_contract_records_the_three_rung_ladder_without_a_floor_to_raise_to(self) -> None:
        contract = model_contract("deepseek-flash")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("low", "high", "max"))
        self.assertEqual(contract["effort_default"], "high")
        self.assertEqual(contract["unsupported_efforts"], {})
        self.assertNotIn("dynamic_effort", contract)
        self.assertEqual(contract["max_output_tokens"], 384_000)
        self.assertTrue(all(source.startswith("https://") for source in contract["sources"]))
        self.assertNotIn("entitled", json.dumps(dict(contract)).casefold())
        # An undocumented rung passes through on record: the API maps it to
        # a neighbour it does not name, so OMH raises nothing and guesses
        # nothing.
        for effort in ("off", "minimal", "medium", "xhigh"):
            self.assertIsNone(contract_effort_floor("deepseek-v4.1-flash", effort), effort)
        route = resolve_model_route("hermes", requested_model="deepseek-flash", requested_effort="medium")
        self.assertEqual(route["selected_reasoning_effort"], "medium")
        self.assertNotEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        self.assertIsNone(dynamic_effort_guidance("deepseek-v4.1-flash", "hermes"))

    def test_price_row_mirrors_the_peak_list_rate_and_cache_ratio(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        contract = model_contract("deepseek-v4.1-flash")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["deepseek-v4.1-flash"], (pricing["input"], pricing["output"]))
        self.assertAlmostEqual(
            APPROX_CACHE_READ_RATIO["deepseek-v4.1-flash"] * pricing["input"], pricing["cached_input"]
        )
        self.assertNotIn("deepseek-flash", APPROX_PRICE_PER_MTOK)

    def test_override_resolves_before_the_family_and_older_generations_keep_the_family_block(self) -> None:
        flash = {"selected_model": "deepseek/deepseek-flash", "model_family": "deepseek", "selected_reasoning_effort": "high"}
        v32 = {"selected_model": "deepseek-v3.2", "model_family": "deepseek", "selected_reasoning_effort": "high"}
        self.assertEqual(calibration_for_route(flash), MODEL_HIGH_EFFORT_CALIBRATIONS["deepseek-v4.1-flash"])
        self.assertEqual(calibration_for_route(v32), HIGH_EFFORT_CALIBRATIONS["deepseek"])
        self.assertEqual(calibration_for_route(flash, family_only=True), HIGH_EFFORT_CALIBRATIONS["deepseek"])
        self.assertEqual(calibration_for_route({**flash, "selected_reasoning_effort": "low"}), "")
        self.assertEqual(
            composition_calibration_for_model("deepseek-flash"),
            MODEL_COMPOSITION_CALIBRATIONS["deepseek-v4.1-flash"],
        )
        self.assertEqual(
            composition_calibration_for_model("deepseek-v4-pro"),
            MAIN_AGENT_COMPOSITION_CALIBRATIONS["deepseek"],
        )

    def test_shipped_chains_name_the_served_pointer_not_the_versioned_id(self) -> None:
        # The first-party API rejects `deepseek-v4.1-flash` by name (HTTP
        # 400, observed in the Hermes DeepSeek profile 2026-09-11), so a
        # shipped chain names the pointer and reaches the contract through
        # the declared projection.
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS

        aliases = {
            str(candidate["model_alias"])
            for chain in SHIPPED_MODEL_RECOMMENDATIONS["categories"].values()
            for candidate in chain
        }
        self.assertIn("deepseek-flash", aliases)
        self.assertNotIn("deepseek-v4.1-flash", aliases)
        self.assertEqual(contract_model_id("deepseek-flash"), "deepseek-v4.1-flash")
        # The contract records which spelling each surface serves; the chain
        # alias is the first-party one and the gateway one is the exact id.
        contract = model_contract("deepseek-v4.1-flash")
        assert contract is not None
        self.assertEqual(contract["served_ids"]["first_party"], "deepseek-flash")
        self.assertEqual(contract["served_ids"]["openrouter"], "deepseek/deepseek-v4.1-flash")
        self.assertEqual(contract["limits_note"].split(";")[0], "1M context and 384K max output are documented literally")

    def test_counters_name_the_documented_traits_and_never_push(self) -> None:
        subagent = MODEL_HIGH_EFFORT_CALIBRATIONS["deepseek-v4.1-flash"]
        composer = MODEL_COMPOSITION_CALIBRATIONS["deepseek-v4.1-flash"]
        self.assertIn("thinking on by default", subagent)
        self.assertIn("never only in reasoning", subagent)
        self.assertIn("exact literal strings", subagent)
        self.assertIn("report the blocker", subagent)
        self.assertIn("low, high, or max", composer)
        self.assertIn("no synthetic thinking instructions", composer)
        for text in (subagent, composer):
            lowered = text.casefold()
            for word in _MONITORING_WORDS:
                self.assertNotIn(word, lowered, word)
            # The Astra round's lesson: a sentence that asks for completion
            # costs tokens on the tasks the model fails.
            for push in ("to completion", "keep going", "keep working", "instead of pausing"):
                self.assertNotIn(push, lowered, push)


class DatedSnapshotTests(unittest.TestCase):
    """A vendor's `<base>-YYYY-MM-DD` id is the base pinned to a date (a
    provider that serves only `gpt-5.6-terra-2026-07-09` was reported on
    2026-09-11). The rule is shape-only and projects only onto a base the
    tables already resolve; nothing else about suffix guessing changes."""

    def test_dated_snapshot_of_a_contracted_id_resolves_its_contract(self) -> None:
        from omh.coding.model_contracts import dated_snapshot_base

        base = model_contract("gpt-6-astra")
        for requested, canonical, mode in (
            ("gpt-6-astra-2026-08-01", "gpt-6-astra-2026-08-01", "standard"),
            ("openai/gpt-6-astra-2026-08-01", "gpt-6-astra-2026-08-01", "standard"),
            ("GPT-6-Astra-2026-08-01", "gpt-6-astra-2026-08-01", "standard"),
            # A snapshot of a declared row inherits that row's mode.
            ("gpt-6-astra-pro-2026-08-01", "gpt-6-astra-pro-2026-08-01", "pro"),
        ):
            with self.subTest(requested=requested):
                projection = model_contract_projection(requested)
                assert projection is not None
                self.assertEqual(projection["requested_model"], requested)
                self.assertEqual(projection["canonical_model_id"], canonical)
                self.assertEqual(projection["contract_model_id"], "gpt-6-astra")
                self.assertEqual(projection["reasoning_mode"], mode)
                self.assertEqual(projection["provenance"], "dated_snapshot")
                self.assertIs(model_contract(requested), base)
                self.assertEqual(contract_model_id(requested), "gpt-6-astra")
                self.assertEqual(dated_snapshot_base(requested), canonical.rsplit("-", 3)[0])
        # The pointer alias projects through to the exact contract as well.
        projection = model_contract_projection("deepseek/deepseek-flash-2026-09-01")
        assert projection is not None
        self.assertEqual(projection["contract_model_id"], "deepseek-v4.1-flash")
        self.assertEqual(projection["reasoning_mode"], "thinking")
        self.assertEqual(projection["provenance"], "dated_snapshot")

    def test_dated_snapshot_keeps_the_exact_model_calibration(self) -> None:
        base_route = {"selected_model": "gpt-6-astra", "selected_reasoning_effort": "xhigh", "model_family": "gpt"}
        dated_route = {**base_route, "selected_model": "openai/gpt-6-astra-2026-08-01"}
        self.assertEqual(calibration_for_route(dated_route), calibration_for_route(base_route))
        self.assertEqual(calibration_for_route(dated_route), MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"])

    def test_only_the_exact_trailing_shape_on_a_known_base_projects(self) -> None:
        from omh.coding.model_contracts import dated_snapshot_base

        for model_id in (
            "gpt-6-terra-2026-07-09",  # date on a base the tables never met
            "gpt-6-astra-turbo-2026-08-01",  # date on an undeclared variant
            "gpt-6-astra-2026-13-01",  # not a calendar month
            "gpt-6-astra-2026-08-32",  # not a calendar day
            "gpt-6-astra-20260801",  # a different vendor's compact shape
            "gpt-6-astra-2026-08",  # no day
            "gpt-6-astra-2026-08-01-fast",  # date is not trailing
            "gpt-6-astra-2026-08-01-2026-08-02",  # a snapshot of a snapshot
        ):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))
                self.assertIsNone(model_contract(model_id))
                self.assertEqual(contract_model_id(model_id), model_id)
        self.assertEqual(dated_snapshot_base("gpt-6-astra-20260801"), "")
        self.assertEqual(dated_snapshot_base("gpt-6-astra"), "")
        self.assertEqual(dated_snapshot_base(""), "")


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


class JevContractTests(unittest.TestCase):
    """The third exact contract (2026-09-21) and the first of a class that
    cannot be routed coding work: a model whose documented output is a typed
    answer, priced with a free output side and carrying no effort ladder."""

    def test_the_exact_id_resolves_and_both_aliases_are_declared_rows(self) -> None:
        for form in ("jev-1.13.0", "typesafe/jev-1.13.0", "JEV-1.13.0"):
            with self.subTest(form=form):
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")
                self.assertEqual(contract_model_id(form), "jev-1.13.0")
                self.assertEqual(projection["reasoning_mode"], "none")
        # Both aliases move on the next release, which is why each is a
        # declared row with a read date rather than a second contract.
        for form in ("jev-latest", "jev-preview"):
            with self.subTest(form=form):
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["contract_model_id"], "jev-1.13.0")
                self.assertEqual(projection["provenance"], "declared_inheritance")
        for form in ("jev-latest", "jev-preview"):
            self.assertNotIn(form, MODEL_CONTRACTS)
        # The bare word is recognized as a family but no vendor page
        # describes it, so it inherits no contract on a guess.
        self.assertEqual(model_family("jev"), "jev")
        self.assertIsNone(model_contract_projection("jev"))
        # A dated snapshot of the exact id projects onto its base, one way.
        snapshot = model_contract_projection("jev-1.13.0-2026-09-15")
        assert snapshot is not None
        self.assertEqual(snapshot["provenance"], "dated_snapshot")
        self.assertEqual(snapshot["contract_model_id"], "jev-1.13.0")
        self.assertIsNone(model_contract_projection("jev-2.0.0"))

    def test_the_record_documents_a_typed_answer_surface_instead_of_a_ladder(self) -> None:
        contract = model_contract("jev-latest")
        assert contract is not None
        self.assertEqual(contract["model_class"], NON_GENERATIVE_MODEL_CLASS)
        self.assertEqual(contract["question_types"], ("choice", "score", "noul"))
        self.assertEqual(contract["max_choice_options"], 255)
        self.assertEqual(contract["reasoning_efforts"], ())
        self.assertEqual(contract["effort_floor"], "")
        self.assertEqual(contract["effort_default"], "")
        self.assertEqual(contract["unsupported_efforts"], {})
        # The ladderless record must stay safe at the one call site that
        # reads a floor: nothing to raise to means nothing is raised.
        for effort in ("off", "minimal", "low", "high", "max", ""):
            self.assertIsNone(contract_effort_floor("jev-1.13.0", effort), effort)
        self.assertIsNone(dynamic_effort_guidance("jev-1.13.0", "hermes"))

    def test_limits_carry_the_zero_output_as_a_documented_int(self) -> None:
        contract = model_contract("jev-1.13.0")
        assert contract is not None
        self.assertEqual(contract["context_window_tokens"], 64_000)
        self.assertEqual(contract["max_input_tokens"], 32_000)
        # An int, not a string: `omh coding model-contract` formats this
        # field with a thousands separator, and a string breaks the one
        # command this contract exists to serve.
        self.assertIsInstance(contract["max_output_tokens"], int)
        self.assertEqual(contract["max_output_tokens"], 0)
        self.assertTrue(contract["limits_note"])
        self.assertEqual(contract["rate_limits"]["tokens_per_second"], 250_000)
        self.assertEqual(contract["rate_limits"]["requests_per_minute"], 1_200)
        self.assertTrue(all(source.startswith("https://docs.typesafe.ai/") for source in contract["sources"]))
        self.assertEqual(contract["sources_read"], "2026-09-21")
        # The vendor's model page publishes no release date for 1.13, so the
        # field is empty rather than carrying a figure the sources do not
        # support.
        self.assertEqual(contract["released"], "")
        self.assertNotIn("entitled", json.dumps(dict(contract)).casefold())

    def test_price_row_mirrors_the_contract_and_zero_output_is_the_published_rate(self) -> None:
        contract = model_contract("jev-1.13.0")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["jev-1.13.0"], (pricing["input"], pricing["output"]))
        self.assertEqual(pricing["output"], 0.0)
        # The table keys model ids, not aliases: an alias row would go stale
        # the moment the vendor moves it.
        for alias in ("jev", "jev-latest", "jev-preview"):
            self.assertNotIn(alias, APPROX_PRICE_PER_MTOK)

    def test_the_documented_traits_name_the_generation_limit_first(self) -> None:
        contract = model_contract("jev-1.13.0")
        assert contract is not None
        traits = contract["documented_traits"]
        self.assertTrue(traits)
        # The trait the whole refusal rests on is the one a reader must not
        # have to hunt for.
        self.assertIn("not trained to generate text", traits[0])

    def test_the_cli_prints_the_answer_surface_for_every_spelling(self) -> None:
        for model in ("jev-1.13.0", "jev-latest", "jev-preview"):
            status, stdout, stderr = run_cli(["coding", "model-contract", "--model", model], output_json=False)
            with self.subTest(model=model):
                self.assertEqual((status, stderr), (0, ""))
                self.assertIn("question types: choice, score, noul", stdout)
                self.assertIn("255 options", stdout)
                self.assertIn("250,000 tokens/s", stdout)
                self.assertIn("input $0.042; output $0.0", stdout)
                self.assertIn("not trained to generate text", stdout)
                self.assertIn("https://docs.typesafe.ai/models", stdout)
                # The ladder line belongs to the generative branch only.
                self.assertNotIn("reasoning efforts:", stdout)

    def test_a_generative_contract_renders_exactly_as_before(self) -> None:
        # The other half of the branch: the class gate must not have leaked
        # the new lines onto a model that has an effort ladder.
        status, stdout, _stderr = run_cli(
            ["coding", "model-contract", "--model", "gpt-6-astra"], output_json=False
        )
        self.assertEqual(status, 0)
        self.assertIn("reasoning efforts: low, medium, high, xhigh, max (floor `low`)", stdout)
        for absent in ("question types:", "rate limits:", "list price per Mtok:", "documented trait:"):
            self.assertNotIn(absent, stdout)


_LUNA_FORMS = ("gpt-6-luna", "openai/gpt-6-luna", "openai-codex/gpt-6-luna", "GPT-6-Luna")


class Gpt6LunaContractTests(unittest.TestCase):
    """The GPT-6 Luna exact contract (2026-09-23): the first contract whose
    documented ladder carries `none` as a rung rather than rejecting it."""

    def test_every_served_form_resolves_the_exact_contract(self) -> None:
        base = model_contract("gpt-6-luna")
        assert base is not None
        for form in _LUNA_FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "gpt")
                self.assertEqual(contract_model_id(form), "gpt-6-luna")
                self.assertIs(model_contract(form), base)
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")

    def test_bare_word_and_undocumented_variants_carry_no_contract(self) -> None:
        # `luna` stays unknown by the pinned decision; the vendor ships Fast,
        # Batch, and Flex as service tiers on the base id, not as separate
        # ids, so a gateway's `-pro` / `-fast` spelling inherits nothing.
        self.assertEqual(model_family("luna"), "unknown")
        for model_id in ("luna", "gpt-6-luna-pro", "gpt-6-luna-fast", "gpt-6-luna-mini"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract(model_id))
        # The previous generation keeps its family-only treatment.
        self.assertIsNone(model_contract("gpt-5.6-luna"))

    def test_contract_records_the_api_ladder_limits_and_price(self) -> None:
        contract = model_contract("gpt-6-luna")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("none", "low", "medium", "high", "xhigh", "max"))
        self.assertEqual(contract["effort_floor"], "none")
        self.assertEqual(contract["effort_default"], "medium")
        self.assertEqual(set(contract["unsupported_efforts"]), {"minimal"})
        self.assertEqual(
            (contract["context_window_tokens"], contract["max_input_tokens"], contract["max_output_tokens"]),
            (1_050_000, 922_000, 128_000),
        )
        self.assertEqual(contract["tool_calling"]["api"], "responses")
        self.assertIn("reasoning effort `none`", contract["tool_calling"]["note"])
        self.assertEqual(contract["unsupported_parameters"], ("temperature", "top_p", "top_logprobs"))
        self.assertIn("not `none`", contract["unsupported_parameters_note"])
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(
            (pricing["input"], pricing["cached_input"], pricing["cache_write"], pricing["output"]),
            (0.10, 0.01, 0.125, 0.50),
        )
        for key in ("long_context_over_272k_input", "batch_and_flex", "fast_mode"):
            self.assertIn(key, pricing)
        # Surfaces that differ from the API page are recorded beside it, not
        # folded into the ladder: Codex has no `none` and no `ultra`, and a
        # Hermes build before the named upstream commit clamps `max`.
        notes = contract["surface_notes"]
        self.assertIn("no `ultra`", notes["codex"])
        self.assertIn("272K", notes["codex"])
        self.assertIn("79ec1f2a34", notes["hermes"])
        self.assertEqual(contract["sources_read"], "2026-09-23")
        self.assertIn("https://developers.openai.com/api/docs/models/gpt-6-luna", contract["sources"])
        self.assertTrue(all(source.startswith("https://") for source in contract["sources"]))
        self.assertEqual(contract["data_handling"]["training_use"], "not_recorded")
        self.assertEqual(contract["claim_boundary"], MODEL_CONTRACT_CLAIM_BOUNDARY)
        # No mid-conversation effort mechanism is claimed for Luna: the guide
        # states it for the family, not for this model.
        self.assertNotIn("dynamic_effort", contract)
        self.assertIsNone(dynamic_effort_guidance("gpt-6-luna", "codex"))

    def test_price_row_mirrors_the_contract_and_the_retired_row_is_corrected(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        contract = model_contract("gpt-6-luna")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6-luna"], (pricing["input"], pricing["output"]))
        # Cached input is the default tenth, so no ratio row is needed.
        self.assertNotIn("gpt-6-luna", APPROX_CACHE_READ_RATIO)
        self.assertAlmostEqual(pricing["input"] / 10, pricing["cached_input"])
        # The retired generation stays priced, at its documented list rate
        # (developers.openai.com/api/docs/models/gpt-5.6-luna, 2026-09).
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-5.6-luna"], (0.20, 1.20))

    def test_none_keeps_its_spelling_on_every_profile(self) -> None:
        # Before this contract, `none` was normalized to `off`, a word the
        # Hermes effort parser does not read as "disabled".
        for profile in ("codex", "hermes", "claude-code", "generic"):
            for model in ("gpt-6-luna", "openai/gpt-6-luna", "gpt-6-luna-2026-09-22"):
                route = resolve_model_route(profile, requested_model=model, requested_effort="none")
                with self.subTest(profile=profile, model=model):
                    self.assertEqual(route["selected_model"], model)
                    self.assertEqual(route["selected_reasoning_effort"], "none")
                    change = route["effort_change"]
                    self.assertEqual(change["kind"], "unchanged")
                    self.assertEqual((change["requested"], change["selected"]), ("none", "none"))
                    self.assertIn("documented rung", change["reason"])

    def test_off_is_sent_as_none_on_every_profile(self) -> None:
        # `off` is OMH's own spelling for no reasoning; the Hermes effort
        # parser does not read it as "disabled", so Luna receives `none`.
        for profile in ("codex", "hermes", "claude-code", "generic"):
            for model in ("gpt-6-luna", "openai/gpt-6-luna", "gpt-6-luna-2026-09-22"):
                route = resolve_model_route(profile, requested_model=model, requested_effort="off")
                with self.subTest(profile=profile, model=model):
                    self.assertEqual(route["selected_reasoning_effort"], "none")
                    change = route["effort_change"]
                    self.assertEqual(change["kind"], "vendor_spelling")
                    self.assertEqual((change["requested"], change["selected"]), ("off", "none"))
        self.assertIn("vendor_spelling", EFFORT_CHANGE_KINDS)
        # A model without `none` on its ladder keeps `off` as before.
        route = resolve_model_route("hermes", requested_model="gpt-5.6-luna", requested_effort="off")
        self.assertEqual(route["selected_reasoning_effort"], "off")

    def test_the_codex_record_names_its_surface_ladder_without_none(self) -> None:
        # The effort is kept as requested; only the record names the
        # Codex client catalog's ladder, which lists no `none`.
        codex = resolve_model_route("codex", requested_model="gpt-6-luna", requested_effort="none")
        self.assertEqual(codex["selected_reasoning_effort"], "none")
        self.assertIn(
            "`codex` surface's recorded ladder (low, medium, high, xhigh, max) does not list `none`",
            codex["effort_change"]["reason"],
        )
        for profile in ("hermes", "claude-code", "generic"):
            route = resolve_model_route(profile, requested_model="gpt-6-luna", requested_effort="none")
            with self.subTest(profile=profile):
                self.assertNotIn("surface", route["effort_change"]["reason"])

    def test_astra_none_is_still_raised_and_uncontracted_ids_still_normalize(self) -> None:
        route = resolve_model_route("hermes", requested_model="gpt-6-astra", requested_effort="none")
        self.assertEqual(route["selected_reasoning_effort"], "low")
        self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        for model in ("gpt-5.6-luna", "luna", "gpt-6-terra-2026-09-22"):
            route = resolve_model_route("hermes", requested_model=model, requested_effort="none")
            with self.subTest(model=model):
                self.assertEqual(route["selected_reasoning_effort"], "off")
                self.assertEqual(route["effort_change"]["kind"], "legacy_alias_normalized")

    def test_hermes_recommendation_lane_keeps_none_for_the_named_model(self) -> None:
        route = resolve_model_route(
            "hermes",
            requested_model="gpt-6-luna",
            requested_effort="none",
            active_models=("gpt-6-luna",),
        )
        self.assertEqual(route["selected_model"], "gpt-6-luna")
        self.assertEqual(route["selected_reasoning_effort"], "none")
        route = resolve_model_route(
            "hermes", requested_model="gpt-6-luna", requested_effort="off", active_models=("gpt-6-luna",)
        )
        self.assertEqual(route["selected_reasoning_effort"], "none")
        self.assertEqual(route["effort_change"]["kind"], "vendor_spelling")
        # The named-model branch applies the contract as the chain-head
        # branch does: `minimal` is not a Luna rung.
        route = resolve_model_route(
            "hermes", requested_model="gpt-6-luna", requested_effort="minimal", active_models=("gpt-6-luna",)
        )
        self.assertEqual(route["selected_reasoning_effort"], "low")
        self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)

    def test_hermes_recommendation_chain_head_keeps_none(self) -> None:
        # No named model: Luna is reached as the chain head of the
        # categories that ship it.
        for category in ("simple-work", "quick"):
            for effort, kind in (("none", None), ("off", "vendor_spelling")):
                route = resolve_model_route(
                    "hermes",
                    requested_effort=effort,
                    requested_category=category,
                    active_models=("gpt-6-luna",),
                )
                with self.subTest(category=category, effort=effort):
                    self.assertEqual(route["provenance"], "recommendation_chain_head")
                    self.assertEqual(route["selected_model"], "gpt-6-luna")
                    self.assertEqual(route["selected_reasoning_effort"], "none")
                    change = route.get("effort_change")
                    self.assertEqual(change["kind"] if change else None, kind)

    def test_minimal_is_raised_to_low_never_lowered_to_none(self) -> None:
        # `none` turns reasoning off; a request for some reasoning is raised
        # to the lowest documented rung above it, never lowered to the floor.
        self.assertEqual(contract_effort_floor("gpt-6-luna", "minimal")[0], "low")
        route = resolve_model_route("codex", requested_model="gpt-6-luna", requested_effort="minimal")
        self.assertEqual(route["selected_reasoning_effort"], "low")
        self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        for effort in ("none", "low", "medium", "high", "xhigh", "max"):
            self.assertIsNone(contract_effort_floor("gpt-6-luna", effort), effort)

    def test_the_unsupported_parameters_note_says_rejected_not_dropped(self) -> None:
        note = model_contract("gpt-6-luna")["unsupported_parameters_note"]
        self.assertNotIn("drops", note)
        self.assertIn("`logprobs` is rejected", note)

    def test_the_cli_prints_the_condition_on_the_unsupported_parameters(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "model-contract", "--model", "gpt-6-luna"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("reasoning efforts: none, low, medium, high, xhigh, max (floor `none`)", stdout)
        self.assertIn("unsupported parameters: temperature, top_p, top_logprobs\n  rejected when", stdout)

    def test_dated_snapshot_resolves_to_the_contract_and_an_unknown_base_stays_unknown(self) -> None:
        projection = model_contract_projection("openai/gpt-6-luna-2026-09-22")
        assert projection is not None
        self.assertEqual(projection["contract_model_id"], "gpt-6-luna")
        self.assertEqual(projection["provenance"], "dated_snapshot")
        for model_id in ("gpt-6-lunar-2026-09-22", "luna-2026-09-22", "gpt-6-luna-pro-2026-09-22"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))


_SOL_FORMS = ("gpt-6-sol", "openai/gpt-6-sol", "openai-codex/gpt-6-sol", "GPT-6-Sol")


class Gpt6SolContractTests(unittest.TestCase):
    """The GPT-6 Sol exact contract (2026-09-23), the same shape as Luna's:
    `none` is a documented rung, `minimal` is not, and the Codex client's
    ladder is recorded beside the API ladder rather than folded into it."""

    def test_every_served_form_resolves_the_exact_contract(self) -> None:
        base = model_contract("gpt-6-sol")
        assert base is not None
        for form in _SOL_FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "gpt")
                self.assertEqual(contract_model_id(form), "gpt-6-sol")
                self.assertIs(model_contract(form), base)
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")

    def test_bare_word_and_undocumented_variants_carry_no_contract(self) -> None:
        # `sol` stays unknown by the pinned decision; Fast, Batch, and Flex
        # are service tiers on the base id, and `-900k` is a Hermes picker
        # alias, so none of these spellings inherits the contract.
        self.assertEqual(model_family("sol"), "unknown")
        for model_id in ("sol", "gpt-6-sol-pro", "gpt-6-sol-fast", "gpt-6-sol-900k", "gpt-6-terra"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract(model_id))
        # The superseded generation keeps its family-only treatment.
        self.assertIsNone(model_contract("gpt-5.6-sol"))
        self.assertIsNone(model_contract("gpt-5.6-terra"))

    def test_contract_records_the_api_ladder_limits_and_price(self) -> None:
        contract = model_contract("gpt-6-sol")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("none", "low", "medium", "high", "xhigh", "max"))
        self.assertEqual(contract["effort_floor"], "none")
        self.assertEqual(contract["effort_default"], "medium")
        self.assertEqual(set(contract["unsupported_efforts"]), {"minimal"})
        self.assertEqual(contract["released"], "2026-09-22")
        self.assertEqual(contract["knowledge_cutoff"], "2026-04-20")
        self.assertEqual(
            (contract["context_window_tokens"], contract["max_input_tokens"], contract["max_output_tokens"]),
            (1_050_000, 922_000, 128_000),
        )
        self.assertEqual(contract["tool_calling"]["api"], "responses")
        self.assertIn("reasoning effort `none`", contract["tool_calling"]["note"])
        self.assertEqual(contract["unsupported_parameters"], ("temperature", "top_p", "top_logprobs"))
        note = contract["unsupported_parameters_note"]
        self.assertIn("not `none`", note)
        self.assertIn("`logprobs` is rejected", note)
        self.assertNotIn("drops", note)
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(
            (pricing["input"], pricing["cached_input"], pricing["cache_write"], pricing["output"]),
            (2.0, 0.2, 2.5, 10.0),
        )
        for key in ("long_context_over_272k_input", "batch_and_flex", "fast_mode"):
            self.assertIn(key, pricing)
        notes = contract["surface_notes"]
        self.assertIn("272K", notes["codex"])
        self.assertIn("79ec1f2a34", notes["hermes"])
        self.assertIn("38c289c014", notes["hermes"])
        self.assertEqual(contract["sources_read"], "2026-09-23")
        self.assertIn("https://developers.openai.com/api/docs/models/gpt-6-sol", contract["sources"])
        # The rollout wording comes from the Codex changelog entry.
        self.assertIn("https://learn.chatgpt.com/docs/changelog", contract["sources"])
        self.assertTrue(all(source.startswith("https://") for source in contract["sources"]))
        self.assertEqual(contract["data_handling"]["training_use"], "not_recorded")
        self.assertEqual(contract["claim_boundary"], MODEL_CONTRACT_CLAIM_BOUNDARY)
        self.assertNotIn("dynamic_effort", contract)
        self.assertIsNone(dynamic_effort_guidance("gpt-6-sol", "codex"))

    def test_the_codex_ultra_rung_stays_out_of_every_recorded_ladder(self) -> None:
        # The Codex client lists a Codex-only `ultra` rung for Sol; the API
        # ladder does not document it, and no OMH ladder, chain, or option
        # row carries it (owner decision, 2026-09-23).
        contract = model_contract("gpt-6-sol")
        assert contract is not None
        self.assertEqual(contract["surface_efforts"], {"codex": ("low", "medium", "high", "xhigh", "max")})
        self.assertNotIn("ultra", contract["reasoning_efforts"])
        self.assertNotIn("ultra", REASONING_EFFORT_LADDER)
        for option in EXECUTOR_MODEL_OPTIONS["codex"]:
            self.assertNotIn("ultra", option["reasoning_efforts"])
        sol_rows = [option for option in EXECUTOR_MODEL_OPTIONS["codex"] if option["model_id"] == "gpt-6-sol"]
        self.assertEqual(len(sol_rows), 1)
        self.assertEqual(tuple(sol_rows[0]["reasoning_efforts"]), contract["surface_efforts"]["codex"])
        self.assertNotIn("default", sol_rows[0]["label"].casefold())

    def test_the_retired_gpt_5_6_rows_keep_adjudicating_an_explicit_override(self) -> None:
        # Both GPT-5.6 ids left every shipped chain, but their Codex option
        # rows stay: a row is the catalog's authority over the effort of an
        # explicit `--model` override. Their ladders are the pre-Sol ones.
        rows = {option["model_id"]: option for option in EXECUTOR_MODEL_OPTIONS["codex"]}
        for model_id in ("gpt-5.6-sol", "gpt-5.6-terra"):
            self.assertEqual(tuple(rows[model_id]["reasoning_efforts"]), ("low", "medium", "high", "xhigh"))
            self.assertNotIn("default", rows[model_id]["label"].casefold())
            route = resolve_model_route("codex", requested_model=model_id, requested_effort="minimal")
            self.assertNotEqual(route["effort_change"]["kind"], "catalog_no_authority_passthrough")

    def test_price_row_mirrors_the_contract_and_the_retired_rows_stay_priced(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        contract = model_contract("gpt-6-sol")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6-sol"], (pricing["input"], pricing["output"]))
        self.assertNotIn("gpt-6-sol", APPROX_CACHE_READ_RATIO)
        self.assertAlmostEqual(pricing["input"] / 10, pricing["cached_input"])
        # Both superseded ids stay priced at their documented list rates.
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-5.6-sol"], (4.0, 20.0))
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-5.6-terra"], (2.0, 12.0))

    def test_none_keeps_its_spelling_and_off_is_sent_as_none_on_every_profile(self) -> None:
        for profile in ("codex", "hermes", "claude-code", "generic"):
            for model in ("gpt-6-sol", "openai/gpt-6-sol", "gpt-6-sol-2026-09-22"):
                with self.subTest(profile=profile, model=model, effort="none"):
                    route = resolve_model_route(profile, requested_model=model, requested_effort="none")
                    self.assertEqual(route["selected_model"], model)
                    self.assertEqual(route["selected_reasoning_effort"], "none")
                    change = route["effort_change"]
                    self.assertEqual(change["kind"], "unchanged")
                    self.assertIn("documented rung", change["reason"])
                with self.subTest(profile=profile, model=model, effort="off"):
                    route = resolve_model_route(profile, requested_model=model, requested_effort="off")
                    self.assertEqual(route["selected_reasoning_effort"], "none")
                    change = route["effort_change"]
                    self.assertEqual(change["kind"], "vendor_spelling")
                    self.assertEqual((change["requested"], change["selected"]), ("off", "none"))
        # The superseded ids have no contract and keep `off`.
        for model in ("gpt-5.6-sol", "gpt-5.6-terra"):
            route = resolve_model_route("hermes", requested_model=model, requested_effort="off")
            self.assertEqual(route["selected_reasoning_effort"], "off")

    def test_the_codex_record_names_its_surface_ladder_without_none(self) -> None:
        codex = resolve_model_route("codex", requested_model="gpt-6-sol", requested_effort="none")
        self.assertEqual(codex["selected_reasoning_effort"], "none")
        self.assertIn(
            "`codex` surface's recorded ladder (low, medium, high, xhigh, max) does not list `none`",
            codex["effort_change"]["reason"],
        )

    def test_minimal_is_raised_to_low_never_lowered_to_none(self) -> None:
        self.assertEqual(contract_effort_floor("gpt-6-sol", "minimal")[0], "low")
        for profile in ("codex", "hermes"):
            route = resolve_model_route(profile, requested_model="gpt-6-sol", requested_effort="minimal")
            with self.subTest(profile=profile):
                self.assertEqual(route["selected_reasoning_effort"], "low")
                self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        for effort in ("none", "low", "medium", "high", "xhigh", "max"):
            self.assertIsNone(contract_effort_floor("gpt-6-sol", effort), effort)

    def test_hermes_named_model_branch_applies_the_contract(self) -> None:
        for effort, selected, kind in (
            ("none", "none", None),
            ("off", "none", "vendor_spelling"),
            ("minimal", "low", EFFORT_FLOOR_KIND),
        ):
            route = resolve_model_route(
                "hermes", requested_model="gpt-6-sol", requested_effort=effort, active_models=("gpt-6-sol",)
            )
            with self.subTest(effort=effort):
                self.assertEqual(route["selected_model"], "gpt-6-sol")
                self.assertEqual(route["selected_reasoning_effort"], selected)
                change = route.get("effort_change")
                if kind is not None:
                    self.assertEqual(change["kind"], kind)

    def test_the_retired_id_is_no_longer_a_chain_head(self) -> None:
        # GPT-6.1 Sol took every GPT-6 Sol slot (owner decision, 2026-10-01):
        # `deep` names the new id (second behind Opus 5.5 since 2026-10-13),
        # so a machine confirming only the old one is not reached through the
        # shipped chain.
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS

        for section in ("categories", "role_suggestions", "domain_affinities", "last_resort"):
            for slot, chain in SHIPPED_MODEL_RECOMMENDATIONS[section].items():
                aliases = [candidate["model_alias"] for candidate in chain]
                with self.subTest(section=section, slot=slot):
                    self.assertNotIn("gpt-6-sol", aliases)
        self.assertIn(
            "gpt-6.1-sol",
            [candidate["model_alias"] for candidate in SHIPPED_MODEL_RECOMMENDATIONS["categories"]["deep"]],
        )
        route = resolve_model_route(
            "hermes", requested_effort="high", requested_category="deep", active_models=("gpt-6-sol",)
        )
        self.assertNotEqual(route["selected_model"], "gpt-6-sol")

    def test_the_cli_prints_the_ladder_and_the_parameter_condition(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "model-contract", "--model", "gpt-6-sol"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("reasoning efforts: none, low, medium, high, xhigh, max (floor `none`)", stdout)
        self.assertIn("unsupported parameters: temperature, top_p, top_logprobs\n  rejected when", stdout)

    def test_no_exact_calibration_block_ships_for_sol(self) -> None:
        # The Luna precedent: an exact contract without an exact block until
        # a family-vs-optimized benchmark pair shows a difference.
        self.assertNotIn("gpt-6-sol", MODEL_HIGH_EFFORT_CALIBRATIONS)
        self.assertNotIn("gpt-6-sol", MODEL_COMPOSITION_CALIBRATIONS)
        route = {"selected_model": "gpt-6-sol", "model_family": "gpt", "selected_reasoning_effort": "high"}
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["gpt"])

    def test_dated_snapshot_resolves_to_the_contract_and_an_unknown_base_stays_unknown(self) -> None:
        projection = model_contract_projection("openai/gpt-6-sol-2026-09-22")
        assert projection is not None
        self.assertEqual(projection["contract_model_id"], "gpt-6-sol")
        self.assertEqual(projection["provenance"], "dated_snapshot")
        for model_id in ("gpt-6-sole-2026-09-22", "sol-2026-09-22", "gpt-6-sol-pro-2026-09-22"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))


_SOL_61_FORMS = ("gpt-6.1-sol", "openai/gpt-6.1-sol", "openai-codex/gpt-6.1-sol", "GPT-6.1-Sol")
_SOL_61_ALL_FORMS = _SOL_61_FORMS + ("gpt-6.1-sol-pro", "openai/gpt-6.1-sol-pro", "gpt-6.1-sol-2026-09-29")


class Gpt61SolContractTests(unittest.TestCase):
    """The GPT-6.1 Sol exact contract (2026-10-01): Astra's ladder shape (no
    `none`, `low` floor), a declared `-pro` projection, Astra's calibration
    wording, and every slot GPT-6 Sol held."""

    def test_every_served_form_resolves_the_exact_contract(self) -> None:
        base = model_contract("gpt-6.1-sol")
        assert base is not None
        for form in _SOL_61_FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "gpt")
                self.assertEqual(contract_model_id(form), "gpt-6.1-sol")
                self.assertIs(model_contract(form), base)
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")

    def test_pro_is_a_declared_projection_and_no_tier_variant_inherits(self) -> None:
        for form in ("gpt-6.1-sol-pro", "openai/gpt-6.1-sol-pro"):
            with self.subTest(form=form):
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["contract_model_id"], "gpt-6.1-sol")
                self.assertEqual(projection["reasoning_mode"], "pro")
                self.assertEqual(projection["service_tier"], "standard")
                self.assertEqual(projection["provenance"], "declared_inheritance")
        for model_id in ("gpt-6.1-sol-fast", "gpt-6.1-sol-flex", "gpt-6.1-sol-900k", "gpt-6.1-sole"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))

    def test_dated_snapshot_projects_with_its_provenance(self) -> None:
        for form in ("gpt-6.1-sol-2026-09-29", "openai/gpt-6.1-sol-2026-09-29"):
            with self.subTest(form=form):
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["contract_model_id"], "gpt-6.1-sol")
                self.assertEqual(projection["provenance"], "dated_snapshot")

    def test_contract_records_the_api_ladder_limits_and_price(self) -> None:
        contract = model_contract("gpt-6.1-sol")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(contract["effort_floor"], "low")
        self.assertEqual(contract["effort_default"], "medium")
        self.assertEqual(set(contract["unsupported_efforts"]), {"off", "minimal"})
        self.assertEqual(contract["generation"], "gpt-6.1")
        self.assertEqual(contract["released"], "2026-09-29")
        self.assertEqual(
            (contract["context_window_tokens"], contract["max_input_tokens"], contract["max_output_tokens"]),
            (1_050_000, 922_000, 128_000),
        )
        self.assertEqual(contract["surface_efforts"], {"codex": ("low", "medium", "high", "xhigh", "max")})
        self.assertNotIn("ultra", contract["reasoning_efforts"])
        self.assertIn("`low` default", contract["surface_notes"]["codex"])
        self.assertIn("NO_DISABLE_TIER_PREFIXES", contract["surface_notes"]["hermes"])
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(
            (pricing["input"], pricing["cached_input"], pricing["cache_write"], pricing["output"]),
            (2.0, 0.10, 2.5, 10.0),
        )
        self.assertEqual(contract["sources_read"], "2026-10-01")
        self.assertIn("https://developers.openai.com/api/docs/models/gpt-6.1-sol", contract["sources"])
        self.assertEqual(contract["claim_boundary"], MODEL_CONTRACT_CLAIM_BOUNDARY)

    def test_price_row_mirrors_the_contract_with_its_cache_ratio(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO, _approximate_cost_usd

        contract = model_contract("gpt-6.1-sol")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6.1-sol"], (pricing["input"], pricing["output"]))
        self.assertEqual(APPROX_CACHE_READ_RATIO["gpt-6.1-sol"], 0.05)
        self.assertAlmostEqual(pricing["input"] * APPROX_CACHE_READ_RATIO["gpt-6.1-sol"], pricing["cached_input"])
        # `-pro` and the dated snapshot inherit the base row; no row of their own.
        self.assertNotIn("gpt-6.1-sol-pro", APPROX_PRICE_PER_MTOK)
        for model in ("gpt-6.1-sol", "gpt-6.1-sol-pro", "openai/gpt-6.1-sol-2026-09-29"):
            with self.subTest(model=model):
                self.assertAlmostEqual(_approximate_cost_usd(model, 1e6, 1e6, 1e6), 2.0 + 10.0 + 0.10)
        # The retired GPT-6 Sol stays priced at its own list rate.
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6-sol"], (2.0, 10.0))

    def test_no_reasoning_and_minimal_are_raised_to_low_on_every_profile(self) -> None:
        for profile in ("codex", "hermes", "claude-code", "generic"):
            for model in _SOL_61_ALL_FORMS:
                for effort in ("off", "none", "minimal"):
                    with self.subTest(profile=profile, model=model, effort=effort):
                        route = resolve_model_route(profile, requested_model=model, requested_effort=effort)
                        self.assertEqual(route["selected_reasoning_effort"], "low")
                        change = route["effort_change"]
                        self.assertEqual(change["kind"], EFFORT_FLOOR_KIND)
                        self.assertEqual((change["requested"], change["selected"]), (effort, "low"))
        for effort in ("low", "medium", "high", "xhigh", "max"):
            self.assertIsNone(contract_effort_floor("gpt-6.1-sol", effort), effort)

    def test_the_codex_option_row_is_the_surface_ladder(self) -> None:
        contract = model_contract("gpt-6.1-sol")
        assert contract is not None
        rows = [option for option in EXECUTOR_MODEL_OPTIONS["codex"] if option["model_id"] == "gpt-6.1-sol"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(tuple(rows[0]["reasoning_efforts"]), contract["surface_efforts"]["codex"])
        self.assertNotIn("default", rows[0]["label"].casefold())
        # The retired GPT-6 Sol row stays to adjudicate an explicit override.
        self.assertEqual(
            [option["model_id"] for option in EXECUTOR_MODEL_OPTIONS["codex"]].count("gpt-6-sol"), 1
        )
        route = resolve_model_route("codex", requested_model="gpt-6.1-sol", requested_effort="max")
        self.assertEqual(route["effort_change"]["kind"], "unchanged")

    def test_hermes_recommendation_chain_head_applies_the_contract(self) -> None:
        # No named model: 6.1 Sol is the only active model, so it is the
        # first eligible entry of `deep` (second behind Opus 5.5 since
        # 2026-10-13) and the resolver reports it as the chain head.
        for effort, selected, kind in (
            ("none", "low", EFFORT_FLOOR_KIND),
            ("off", "low", EFFORT_FLOOR_KIND),
            ("minimal", "low", EFFORT_FLOOR_KIND),
            ("high", "high", None),
        ):
            route = resolve_model_route(
                "hermes",
                requested_effort=effort,
                requested_category="deep",
                active_models=("gpt-6.1-sol",),
            )
            with self.subTest(effort=effort):
                self.assertEqual(route["provenance"], "recommendation_chain_head")
                self.assertEqual(route["selected_model"], "gpt-6.1-sol")
                self.assertEqual(route["selected_reasoning_effort"], selected)
                change = route.get("effort_change")
                self.assertEqual(change["kind"] if change else None, kind)

    def test_exact_calibration_reuses_astra_wording_and_sol_keeps_the_family_block(self) -> None:
        # The vendor's Codex client gives 6.1 Sol Astra's base prompt, so the
        # override is Astra's measured text, byte for byte.
        self.assertEqual(MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6.1-sol"], MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"])
        self.assertEqual(MODEL_COMPOSITION_CALIBRATIONS["gpt-6.1-sol"], MODEL_COMPOSITION_CALIBRATIONS["gpt-6-astra"])
        for model in ("gpt-6.1-sol", "openai/gpt-6.1-sol-pro", "gpt-6.1-sol-2026-09-29"):
            route = {"selected_model": model, "model_family": "gpt", "selected_reasoning_effort": "high"}
            with self.subTest(model=model):
                self.assertEqual(calibration_for_route(route), MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6.1-sol"])
                self.assertEqual(
                    composition_calibration_for_model(model), MODEL_COMPOSITION_CALIBRATIONS["gpt-6.1-sol"]
                )
        old = {"selected_model": "gpt-6-sol", "model_family": "gpt", "selected_reasoning_effort": "high"}
        self.assertEqual(calibration_for_route(old), HIGH_EFFORT_CALIBRATIONS["gpt"])
        for text in (MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6.1-sol"], MODEL_COMPOSITION_CALIBRATIONS["gpt-6.1-sol"]):
            lowered = text.casefold()
            for phrase in ("persist until", "carry the user's intended task", "helpful enough",
                           "without ending the turn", "continue toward completing"):
                self.assertNotIn(phrase, lowered, phrase)

    def test_the_cli_prints_the_ladder(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "model-contract", "--model", "gpt-6.1-sol"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("reasoning efforts: low, medium, high, xhigh, max (floor `low`)", stdout)



_TERRA_61_FORMS = ("gpt-6.1-terra", "openai/gpt-6.1-terra", "openai-codex/gpt-6.1-terra", "GPT-6.1-Terra")
_TERRA_61_ALL_FORMS = _TERRA_61_FORMS + ("gpt-6.1-terra-pro", "openai/gpt-6.1-terra-pro", "gpt-6.1-terra-2026-10-26")


class Gpt61TerraContractTests(unittest.TestCase):
    """The GPT-6.1 Terra exact contract (2026-10-27): GPT-6 Luna's ladder
    shape (`none` is documented), a declared `-pro` projection, the `gpt`
    family calibration, and no shipped chain slot."""

    def test_every_served_form_resolves_the_exact_contract(self) -> None:
        base = model_contract("gpt-6.1-terra")
        assert base is not None
        for form in _TERRA_61_FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "gpt")
                self.assertEqual(contract_model_id(form), "gpt-6.1-terra")
                self.assertIs(model_contract(form), base)
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")
        # GPT-5.6 Terra is a different generation and stays uncontracted, and
        # the tier OpenAI never published stays unknown.
        for model_id in ("gpt-5.6-terra", "gpt-6-terra", "gpt-6.1-terra-fast", "gpt-6.1-terra-900k", "gpt-6.1-terran"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))

    def test_pro_and_the_dated_snapshot_project_with_their_provenance(self) -> None:
        for form, provenance, mode in (
            ("gpt-6.1-terra-pro", "declared_inheritance", "pro"),
            ("openai/gpt-6.1-terra-pro", "declared_inheritance", "pro"),
            ("gpt-6.1-terra-2026-10-26", "dated_snapshot", "standard"),
        ):
            with self.subTest(form=form):
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["contract_model_id"], "gpt-6.1-terra")
                self.assertEqual(projection["provenance"], provenance)
                self.assertEqual(projection["reasoning_mode"], mode)
                self.assertEqual(projection["service_tier"], "standard")

    def test_contract_records_the_api_ladder_limits_and_price(self) -> None:
        contract = model_contract("gpt-6.1-terra")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("none", "low", "medium", "high", "xhigh", "max"))
        self.assertEqual((contract["effort_floor"], contract["effort_default"]), ("none", "medium"))
        self.assertEqual(set(contract["unsupported_efforts"]), {"minimal"})
        self.assertEqual((contract["generation"], contract["released"]), ("gpt-6.1", "2026-10-26"))
        self.assertEqual(contract["knowledge_cutoff"], "2026-06-01")
        self.assertEqual(
            (contract["context_window_tokens"], contract["max_input_tokens"], contract["max_output_tokens"]),
            (1_050_000, 922_000, 128_000),
        )
        self.assertEqual(contract["surface_efforts"], {"codex": ("low", "medium", "high", "xhigh", "max")})
        self.assertIn("`low` default", contract["surface_notes"]["codex"])
        self.assertIn("clamps `max` to `xhigh`", contract["surface_notes"]["hermes"])
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(
            (pricing["input"], pricing["cached_input"], pricing["cache_write"], pricing["output"]),
            (1.0, 0.05, 1.25, 5.0),
        )
        self.assertEqual(contract["sources_read"], "2026-10-27")
        self.assertIn("https://developers.openai.com/api/docs/models/gpt-6.1-terra", contract["sources"])
        self.assertEqual(contract["claim_boundary"], MODEL_CONTRACT_CLAIM_BOUNDARY)

    def test_price_row_mirrors_the_contract_with_its_cache_ratio(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO, _approximate_cost_usd

        contract = model_contract("gpt-6.1-terra")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6.1-terra"], (pricing["input"], pricing["output"]))
        self.assertAlmostEqual(pricing["input"] * APPROX_CACHE_READ_RATIO["gpt-6.1-terra"], pricing["cached_input"])
        self.assertNotIn("gpt-6.1-terra-pro", APPROX_PRICE_PER_MTOK)
        for model in ("gpt-6.1-terra", "gpt-6.1-terra-pro", "openai/gpt-6.1-terra-2026-10-26"):
            with self.subTest(model=model):
                self.assertAlmostEqual(_approximate_cost_usd(model, 1e6, 1e6, 1e6), 1.0 + 5.0 + 0.05)
        # The predecessor keeps its own list rate for machine-level overrides.
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-5.6-terra"], (2.0, 12.0))

    def test_none_is_sent_and_only_minimal_is_raised(self) -> None:
        for profile in ("codex", "hermes", "generic"):
            for model in _TERRA_61_ALL_FORMS:
                with self.subTest(profile=profile, model=model):
                    route = resolve_model_route(profile, requested_model=model, requested_effort="none")
                    self.assertEqual(route["selected_reasoning_effort"], "none")
                    route = resolve_model_route(profile, requested_model=model, requested_effort="minimal")
                    self.assertEqual(route["selected_reasoning_effort"], "low")
                    self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        for effort in ("none", "low", "medium", "high", "xhigh", "max"):
            self.assertIsNone(contract_effort_floor("gpt-6.1-terra", effort), effort)

    def test_no_shipped_chain_names_it_and_it_keeps_the_family_block(self) -> None:
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS

        for section in ("categories", "role_suggestions", "domain_affinities", "last_resort"):
            for slot, chain in SHIPPED_MODEL_RECOMMENDATIONS[section].items():
                with self.subTest(section=section, slot=slot):
                    self.assertNotIn("gpt-6.1-terra", [candidate["model_alias"] for candidate in chain])
        self.assertNotIn("gpt-6.1-terra", MODEL_HIGH_EFFORT_CALIBRATIONS)
        self.assertNotIn("gpt-6.1-terra", MODEL_COMPOSITION_CALIBRATIONS)
        for model in ("gpt-6.1-terra", "openai/gpt-6.1-terra-pro"):
            route = {"selected_model": model, "model_family": "gpt", "selected_reasoning_effort": "high"}
            with self.subTest(model=model):
                self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["gpt"])

    def test_the_cli_prints_the_ladder(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "model-contract", "--model", "gpt-6.1-terra"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("reasoning efforts: none, low, medium, high, xhigh, max (floor `none`)", stdout)

_CYBER_FORMS = ("gpt-6-cyber", "openai/gpt-6-cyber", "openai-codex/gpt-6-cyber", "GPT-6-Cyber")
# Ids that put access-gated OpenAI models in front of a user who names them;
# none may appear in any shipped chain or in the Maestro tables.
_GATED_OPENAI_IDS = ("gpt-6-cyber", "gpt-5.6-cyber", "gpt-6-rosalind")


class Gpt6CyberContractTests(unittest.TestCase):
    """GPT-6 Cyber (released 2026-11-05): an access-gated Astra variant on the Mythos
    5.1 terms. Exact contract with Astra's inherited ladder, its own list
    price, Astra's exact calibration, and no shipped chain slot."""

    def test_every_served_form_resolves_the_exact_contract(self) -> None:
        base = model_contract("gpt-6-cyber")
        assert base is not None
        for form in _CYBER_FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "gpt")
                self.assertEqual(contract_model_id(form), "gpt-6-cyber")
                self.assertIs(model_contract(form), base)
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")
        projection = model_contract_projection("gpt-6-cyber-2026-11-05")
        assert projection is not None
        self.assertEqual((projection["contract_model_id"], projection["provenance"]), ("gpt-6-cyber", "dated_snapshot"))
        # The pricing page lists no mode or tier variant, so none is declared,
        # and the Astra contract is not reached through the Cyber id.
        for model_id in ("gpt-6-cyber-pro", "gpt-6-cyber-fast", "gpt-6-cyber-flex", "cyber", "gpt-6.1-cyber"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))
        self.assertIsNot(model_contract("gpt-6-cyber"), model_contract("gpt-6-astra"))
        # GPT-5.6 Cyber and GPT-6 Rosalind document no ladder: no contract.
        self.assertIsNone(model_contract("gpt-5.6-cyber"))
        self.assertIsNone(model_contract("gpt-6-rosalind"))

    def test_contract_records_the_gate_the_inherited_ladder_and_the_price(self) -> None:
        contract = model_contract("gpt-6-cyber")
        astra = model_contract("gpt-6-astra")
        assert contract is not None and astra is not None
        for key in ("reasoning_efforts", "effort_floor", "effort_default"):
            self.assertEqual(contract[key], astra[key], key)
        self.assertEqual(set(contract["unsupported_efforts"]), set(astra["unsupported_efforts"]))
        self.assertIn("inherited from GPT-6 Astra", contract["effort_ladder_source"])
        self.assertIn("Daybreak Red", contract["access"])
        self.assertIn("Critical in Cybersecurity", contract["access"])
        self.assertIn("HTTP 400", contract["rollout"])
        self.assertEqual((contract["generation"], contract["released"]), ("gpt-6", "2026-11-05"))
        self.assertEqual(
            (contract["context_window_tokens"], contract["max_input_tokens"], contract["max_output_tokens"]),
            (1_050_000, 922_000, 128_000),
        )
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(
            (pricing["input"], pricing["cached_input"], pricing["cache_write"], pricing["output"]),
            (20.0, 2.0, 25.0, 100.0),
        )
        self.assertEqual(pricing["cache_write_12h"], 50.0)
        self.assertEqual(pricing["long_context_over_272k_input"], "not published")
        self.assertEqual(contract["sources_read"], "2026-11-06")
        self.assertIn("https://deploymentsafety.openai.com/gpt-6-cyber", contract["sources"])
        self.assertEqual(contract["claim_boundary"], MODEL_CONTRACT_CLAIM_BOUNDARY)
        self.assertNotIn("entitled", json.dumps(dict(contract)).casefold())

    def test_price_rows_mirror_the_published_list_prices(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO, _approximate_cost_usd

        contract = model_contract("gpt-6-cyber")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6-cyber"], (pricing["input"], pricing["output"]))
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-5.6-cyber"], (12.5, 75.0))
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6-rosalind"], (15.0, 75.0))
        # Every cached rate is a tenth of input, so none needs a ratio row.
        for model in _GATED_OPENAI_IDS:
            self.assertNotIn(model, APPROX_CACHE_READ_RATIO)
        for model, (input_rate, output_rate) in (
            ("gpt-6-cyber", (20.0, 100.0)),
            ("openai/gpt-6-cyber-2026-11-05", (20.0, 100.0)),
            ("gpt-5.6-cyber", (12.5, 75.0)),
            ("gpt-6-rosalind", (15.0, 75.0)),
        ):
            with self.subTest(model=model):
                self.assertAlmostEqual(
                    _approximate_cost_usd(model, 1e6, 1e6, 1e6), input_rate + output_rate + input_rate / 10
                )
        # Astra keeps its own lower card; the Cyber id never borrows it.
        self.assertEqual(APPROX_PRICE_PER_MTOK["gpt-6-astra"], (10.0, 50.0))

    def test_no_reasoning_is_raised_to_the_inherited_floor_on_record(self) -> None:
        for profile in ("codex", "hermes", "generic"):
            for effort in ("off", "none", "minimal"):
                with self.subTest(profile=profile, effort=effort):
                    route = resolve_model_route(profile, requested_model="openai/gpt-6-cyber", requested_effort=effort)
                    self.assertEqual(route["selected_reasoning_effort"], "low")
                    self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
                    self.assertEqual(route["selected_model"], "openai/gpt-6-cyber")
        for effort in ("low", "medium", "high", "xhigh", "max"):
            self.assertIsNone(contract_effort_floor("gpt-6-cyber", effort), effort)

    def test_it_takes_astras_exact_calibration_byte_for_byte(self) -> None:
        self.assertEqual(MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-cyber"], MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"])
        self.assertEqual(MODEL_COMPOSITION_CALIBRATIONS["gpt-6-cyber"], MODEL_COMPOSITION_CALIBRATIONS["gpt-6-astra"])
        for model in _CYBER_FORMS:
            route = {"selected_model": model, "model_family": "gpt", "selected_reasoning_effort": "xhigh"}
            with self.subTest(model=model):
                self.assertEqual(calibration_for_route(route), MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-astra"])
                self.assertEqual(calibration_for_route(route, family_only=True), HIGH_EFFORT_CALIBRATIONS["gpt"])
        # The contract-less gated siblings keep the family block.
        for model in ("gpt-5.6-cyber", "gpt-6-rosalind"):
            route = {"selected_model": model, "model_family": "gpt", "selected_reasoning_effort": "xhigh"}
            with self.subTest(model=model):
                self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["gpt"])
                self.assertEqual(composition_calibration_for_model(model), MAIN_AGENT_COMPOSITION_CALIBRATIONS["gpt"])

    def test_no_shipped_chain_or_maestro_table_names_a_gated_model(self) -> None:
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS
        from omh.coding.model_routing import BUILTIN_CATEGORY_MODELS

        for section in ("categories", "role_suggestions", "domain_affinities", "last_resort"):
            for slot, chain in SHIPPED_MODEL_RECOMMENDATIONS[section].items():
                aliases = [candidate["model_alias"] for candidate in chain]
                for model_id in _GATED_OPENAI_IDS:
                    with self.subTest(section=section, slot=slot, model=model_id):
                        self.assertNotIn(model_id, aliases)
        flattened = json.dumps(BUILTIN_CATEGORY_MODELS) + json.dumps(EXECUTOR_MODEL_OPTIONS)
        for model_id in _GATED_OPENAI_IDS:
            self.assertNotIn(f'"{model_id}"', flattened, model_id)

    def test_every_gated_model_has_its_display_label_in_both_tables(self) -> None:
        from omh.catalogs.model_chain_table import MODEL_DISPLAY_LABELS
        from omh.plugin_bundle.omh.orchestration_say import model_label

        for model_id, label in (
            ("gpt-6-cyber", "GPT-6 Cyber"),
            ("gpt-5.6-cyber", "GPT-5.6 Cyber"),
            ("gpt-6-rosalind", "GPT-6 Rosalind"),
        ):
            with self.subTest(model_id=model_id):
                self.assertEqual(MODEL_DISPLAY_LABELS[model_id], label)
                self.assertEqual(model_label(model_id), label)

    def test_the_cli_prints_the_inherited_ladder(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "model-contract", "--model", "gpt-6-cyber"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("reasoning efforts: low, medium, high, xhigh, max (floor `low`)", stdout)


class DeepSeekV41Flash1017Tests(unittest.TestCase):
    """The 2026-10-17 upgrade the `deepseek-flash` pointer now serves, under
    the relay spelling DeepSeek itself does not accept."""

    def test_the_relay_spelling_inherits_the_flash_contract_price_and_calibration(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import _approximate_cost_usd

        base = model_contract("deepseek-v4.1-flash")
        for form in ("deepseek-v4.1-flash-1017", "deepseek/deepseek-v4.1-flash-1017"):
            with self.subTest(form=form):
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["contract_model_id"], "deepseek-v4.1-flash")
                self.assertEqual(projection["provenance"], "declared_inheritance")
                self.assertEqual(projection["reasoning_mode"], "thinking")
                self.assertIs(model_contract(form), base)
                self.assertAlmostEqual(
                    _approximate_cost_usd(form, 1e6, 1e6, 0), _approximate_cost_usd("deepseek-v4.1-flash", 1e6, 1e6, 0)
                )
                route = {"selected_model": form, "model_family": "deepseek", "selected_reasoning_effort": "max"}
                self.assertEqual(calibration_for_route(route), MODEL_HIGH_EFFORT_CALIBRATIONS["deepseek-v4.1-flash"])
        self.assertNotIn("deepseek-v4.1-flash-1017", APPROX_PRICE_PER_MTOK)
        self.assertIn("DeepSeek-V4.1-Flash-1017", base["rollout"])
        self.assertEqual(base["served_ids"]["openrouter_snapshot_1017"], "deepseek/deepseek-v4.1-flash-1017")
        # Only the declared spelling projects: another MMDD suffix stays
        # uncontracted until it gets its own row.
        for model_id in ("deepseek-v4.1-flash-1118", "deepseek-v4-pro-0813", "deepseek-flash-1017"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))


_OPUS_55_FORMS = ("claude-opus-5-5", "anthropic/claude-opus-5-5", "Claude-Opus-5-5")


class ClaudeOpus55ContractTests(unittest.TestCase):
    """The first Claude exact contract (2026-09-23): thinking is always on,
    so a no-thinking rung is raised to the documented floor on record."""

    def test_every_served_form_resolves_the_exact_contract(self) -> None:
        base = model_contract("claude-opus-5-5")
        assert base is not None
        for form in _OPUS_55_FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "claude")
                self.assertEqual(contract_model_id(form), "claude-opus-5-5")
                self.assertIs(model_contract(form), base)

    def test_other_claude_ids_keep_the_family_only_treatment(self) -> None:
        # No dated form (Anthropic publishes none for 5.5), no undeclared
        # regional Bedrock profile, and the tier alias `opus` and the
        # previous generation stay contract-free.
        for model_id in (
            "claude-opus-5",
            "opus",
            "claude-fable-5-1",
            "claude-opus-5-5-20260922",
            "us.anthropic.claude-opus-5-5",
            "anthropic.claude-opus-5",
        ):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract(model_id))

    def test_contract_records_the_always_thinking_ladder_and_wire_hazards(self) -> None:
        contract = model_contract("claude-opus-5-5")
        assert contract is not None
        self.assertEqual(contract["reasoning_mode"], "thinking")
        self.assertEqual(contract["reasoning_efforts"], ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(contract["effort_floor"], "low")
        self.assertEqual(contract["effort_default"], "medium")
        self.assertIn("off", contract["unsupported_efforts"])
        self.assertIn("400", contract["unsupported_efforts"]["off"])
        self.assertEqual(contract["tool_calling"]["api"], "messages")
        self.assertIn("`tool_choice`", contract["tool_calling"]["note"])
        self.assertIn("400", contract["tool_calling"]["note"])
        self.assertEqual((contract["context_window_tokens"], contract["max_output_tokens"]), (1_000_000, 128_000))
        self.assertIn("300K", contract["limits_note"])
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual((pricing["input"], pricing["output"]), (4.0, 20.0))
        # Cache reads are a twentieth of input on this model, not the tenth
        # the approximation table assumes by default.
        self.assertEqual(pricing["cached_input"], 0.20)
        self.assertEqual((pricing["cache_write_5m"], pricing["cache_write_1h"]), (5.0, 8.0))
        self.assertIn("Claude API", pricing["fast_mode"])
        self.assertIn("2027-09-22", contract["retirement"])
        self.assertEqual(contract["sources_read"], "2026-09-23")
        self.assertTrue(all(source.startswith("https://") for source in contract["sources"]))
        self.assertEqual(contract["claim_boundary"], MODEL_CONTRACT_CLAIM_BOUNDARY)

    def test_price_row_mirrors_the_contract_and_cache_ratio(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        contract = model_contract("claude-opus-5-5")
        assert contract is not None
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["claude-opus-5-5"], (pricing["input"], pricing["output"]))
        self.assertAlmostEqual(
            APPROX_CACHE_READ_RATIO["claude-opus-5-5"] * pricing["input"], pricing["cached_input"]
        )
        # The retired generation keeps its row for a machine-level override.
        self.assertEqual(APPROX_PRICE_PER_MTOK["claude-opus-5"], (5.0, 25.0))

    def test_declared_second_spellings_resolve_the_contract(self) -> None:
        # The contract's own Bedrock `served_ids` entry and the dotted gateway
        # spelling are declared rows, so core routing and the plugin's
        # always-thinking guard agree on them.
        contract = model_contract("claude-opus-5-5")
        assert contract is not None
        self.assertEqual(contract["served_ids"]["bedrock"], "anthropic.claude-opus-5-5")
        for form in (
            "anthropic.claude-opus-5-5",
            "claude-opus-5.5",
            "anthropic/claude-opus-5.5",
            "openrouter/anthropic/claude-opus-5.5",
        ):
            with self.subTest(form=form):
                self.assertIs(model_contract(form), contract)
                projection = model_contract_projection(form)
                self.assertEqual(projection["provenance"], "declared_inheritance")
                self.assertEqual((projection["reasoning_mode"], projection["service_tier"]), ("thinking", "standard"))
                route = resolve_model_route("hermes", requested_model=form, requested_effort="off")
                self.assertEqual(route["selected_reasoning_effort"], "low")
                self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)

    def test_hermes_named_model_lane_raises_no_thinking_on_record(self) -> None:
        # The confirmed-active named-model branch used to pass `off` through;
        # the contract documents a thinking-disabled request as HTTP 400.
        for requested in ("off", "none", "minimal"):
            route = resolve_model_route(
                "hermes",
                requested_model="claude-opus-5-5",
                requested_effort=requested,
                active_models=("claude-opus-5-5",),
            )
            with self.subTest(requested=requested):
                self.assertEqual(route["provenance"], "request_named_model")
                self.assertEqual(route["selected_reasoning_effort"], "low")
                change = route["effort_change"]
                self.assertEqual(change["kind"], EFFORT_FLOOR_KIND)
                self.assertEqual(change["requested"], requested)
        # Every exact contract's floor applies on this branch, not only Opus
        # 5.5's: GPT-6 Astra passed `off` / `none` / `minimal` through before.
        for requested in ("off", "none", "minimal"):
            route = resolve_model_route(
                "hermes", requested_model="gpt-6-astra", requested_effort=requested, active_models=("gpt-6-astra",)
            )
            with self.subTest(model="gpt-6-astra", requested=requested):
                self.assertEqual(route["selected_reasoning_effort"], "low")
                change = route["effort_change"]
                self.assertEqual(change["kind"], EFFORT_FLOOR_KIND)
                self.assertEqual(change["requested"], requested)
                self.assertIn(f"`{requested}`", change["reason"])
        # A supported rung is untouched and unrecorded, as before.
        route = resolve_model_route(
            "hermes", requested_model="claude-opus-5-5", requested_effort="high", active_models=("claude-opus-5-5",)
        )
        self.assertEqual(route["selected_reasoning_effort"], "high")
        self.assertIsNone(route.get("effort_change"))

    def test_no_thinking_rungs_are_raised_to_low_for_every_profile(self) -> None:
        for profile in ("codex", "hermes", "claude-code", "generic"):
            for requested in ("off", "none", "minimal"):
                route = resolve_model_route(profile, requested_model="claude-opus-5-5", requested_effort=requested)
                with self.subTest(profile=profile, requested=requested):
                    self.assertEqual(route["selected_reasoning_effort"], "low")
                    change = route["effort_change"]
                    self.assertEqual(change["kind"], EFFORT_FLOOR_KIND)
                    self.assertEqual(change["requested"], requested)
                    self.assertIn("documented floor", change["reason"])

    def test_opus_5_still_routes_off_as_before(self) -> None:
        for model in ("claude-opus-5", "opus"):
            route = resolve_model_route("hermes", requested_model=model, requested_effort="off")
            with self.subTest(model=model):
                self.assertEqual(route["selected_reasoning_effort"], "off")
                self.assertNotEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
                self.assertNotIn("model_contract", route)

    def test_family_calibration_stays_the_claude_block(self) -> None:
        route = {"selected_model": "claude-opus-5-5", "model_family": "claude", "selected_reasoning_effort": "high"}
        self.assertNotIn("claude-opus-5-5", MODEL_HIGH_EFFORT_CALIBRATIONS)
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["claude"])
        self.assertEqual(
            composition_calibration_for_model("claude-opus-5-5"), MAIN_AGENT_COMPOSITION_CALIBRATIONS["claude"]
        )


class ClaudeSonnet55ContractTests(unittest.TestCase):
    """Sonnet 5.5 (2026-10-01) takes the Opus 5.5 shape: a no-thinking rung is
    raised to `low` on record. It joined the shipped chains on 2026-10-13."""

    def test_every_served_and_declared_form_resolves_the_contract(self) -> None:
        contract = model_contract("claude-sonnet-5-5")
        assert contract is not None
        for form in (
            "claude-sonnet-5-5",
            "anthropic/claude-sonnet-5-5",
            "anthropic.claude-sonnet-5-5",
            "claude-sonnet-5.5",
            "openrouter/anthropic/claude-sonnet-5.5",
        ):
            with self.subTest(form=form):
                self.assertIs(model_contract(form), contract)
                route = resolve_model_route("hermes", requested_model=form, requested_effort="off")
                self.assertEqual(route["selected_reasoning_effort"], "low")
                self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        for model_id in ("claude-sonnet-5", "sonnet", "us.anthropic.claude-sonnet-5-5"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract(model_id))

    def test_contract_records_the_ladder_price_and_retirement(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        contract = model_contract("claude-sonnet-5-5")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual((contract["effort_floor"], contract["effort_default"]), ("low", "high"))
        self.assertIn("between_tools", contract["unsupported_efforts"]["off"])
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual(APPROX_PRICE_PER_MTOK["claude-sonnet-5-5"], (pricing["input"], pricing["output"]))
        # Anthropic lowered Sonnet 5.5 cache reads from $0.20 to $0.10 on
        # 2026-10-07 (the Haiku 5.5 launch post), which is 0.05x input, the
        # Opus 5.5 ratio; the approximation table carries the same ratio.
        self.assertEqual((pricing["input"], pricing["output"], pricing["cached_input"]), (2.0, 10.0, 0.10))
        self.assertAlmostEqual(APPROX_CACHE_READ_RATIO["claude-sonnet-5-5"] * pricing["input"], pricing["cached_input"])
        self.assertIn("2027-09-28", contract["retirement"])
        self.assertEqual(contract["sources_read"], "2026-10-01")

    def test_family_blocks_apply_since_the_override_was_removed(self) -> None:
        # The exact override (family block plus a stop-review clause) measured
        # no effect on 2026-10-02 (benchmarks/live-model-tools/v1/README.md)
        # and no shipped slot reached it, so it was removed on 2026-10-04.
        self.assertNotIn("claude-sonnet-5-5", MODEL_HIGH_EFFORT_CALIBRATIONS)
        self.assertNotIn("claude-sonnet-5-5", MODEL_COMPOSITION_CALIBRATIONS)
        for form in ("claude-sonnet-5-5", "anthropic/claude-sonnet-5-5", "claude-sonnet-5.5"):
            with self.subTest(form=form):
                route = resolve_model_route("hermes", requested_model=form, requested_effort="max")
                self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["claude"])
                self.assertEqual(
                    composition_calibration_for_model(form), MAIN_AGENT_COMPOSITION_CALIBRATIONS["claude"]
                )
        # Bedrock spellings, with and without a regional prefix, read the
        # `anthropic.` vendor segment and get the same claude family blocks.
        for form in (
            "anthropic.claude-sonnet-5-5",
            "us.anthropic.claude-sonnet-5-5",
            "anthropic.claude-opus-5-5",
            "global.anthropic.claude-opus-5-5",
        ):
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "claude")
                route = resolve_model_route("hermes", requested_model=form, requested_effort="max")
                self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["claude"])
                self.assertEqual(
                    composition_calibration_for_model(form), MAIN_AGENT_COMPOSITION_CALIBRATIONS["claude"]
                )
        # Only a vendor segment is stripped: a lookalike stays unclassified.
        for form in ("notanthropic.claude-x", "us-east.anthropic.claude-x", "anthropic."):
            with self.subTest(form=form):
                self.assertNotEqual(model_family(form), "claude")

    def test_sonnet_5_still_routes_off_as_before(self) -> None:
        for model in ("claude-sonnet-5", "sonnet"):
            route = resolve_model_route("hermes", requested_model=model, requested_effort="off")
            with self.subTest(model=model):
                self.assertEqual(route["selected_reasoning_effort"], "off")
                self.assertNotIn("model_contract", route)


class ClaudeHaiku55ContractTests(unittest.TestCase):
    """Haiku 5.5 (2026-10-07) is the first Haiku with an effort ladder. Unlike
    Opus 5.5 and Sonnet 5.5 it accepts a thinking disable at `high` or below,
    so `off` passes through on record instead of being raised."""

    def test_every_served_and_declared_form_resolves_the_contract(self) -> None:
        contract = model_contract("claude-haiku-5-5")
        assert contract is not None
        for form in (
            "claude-haiku-5-5",
            "anthropic/claude-haiku-5-5",
            "anthropic.claude-haiku-5-5",
            "claude-haiku-5.5",
            "openrouter/anthropic/claude-haiku-5.5",
        ):
            with self.subTest(form=form):
                self.assertIs(model_contract(form), contract)
                off = resolve_model_route("hermes", requested_model=form, requested_effort="off")
                self.assertEqual(off["selected_reasoning_effort"], "off")
                self.assertNotEqual(off["effort_change"]["kind"], EFFORT_FLOOR_KIND)
                minimal = resolve_model_route("hermes", requested_model=form, requested_effort="minimal")
                self.assertEqual(minimal["selected_reasoning_effort"], "low")
                self.assertEqual(minimal["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        # The superseded generation and the bare alias stay uncontracted.
        for model_id in ("claude-haiku-4-5", "haiku", "us.anthropic.claude-haiku-5-5"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract(model_id))

    def test_contract_records_the_ladder_both_price_cards_and_retirement(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        contract = model_contract("claude-haiku-5-5")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual((contract["effort_floor"], contract["effort_default"]), ("low", "medium"))
        self.assertNotIn("off", contract["unsupported_efforts"])
        self.assertEqual((contract["released"], contract["context_window_tokens"]), ("2026-10-07", 1_000_000))
        self.assertEqual(contract["max_output_tokens"], 128_000)
        pricing = contract["pricing_usd_per_mtok"]
        # The approximation table carries the up-to-100K card; the higher
        # card is recorded on the contract, not flattened into the table.
        self.assertEqual(APPROX_PRICE_PER_MTOK["claude-haiku-5-5"], (pricing["input"], pricing["output"]))
        self.assertEqual((pricing["input"], pricing["output"], pricing["cached_input"]), (0.10, 0.50, 0.01))
        self.assertEqual((pricing["cache_write_5m"], pricing["cache_write_1h"]), (0.125, 0.20))
        self.assertNotIn("claude-haiku-5-5", APPROX_CACHE_READ_RATIO)
        # The higher card, rate by rate and with its threshold: each number
        # is its own fragment, so one mistyped rate fails by name.
        higher = pricing["long_context_over_100k_prompt"]
        for fragment in (
            "input 0.50,",
            "cached input 0.05,",
            "cache write 0.625 (5m) and 1.00 (1h),",
            "output 2.50 ",
            "exceeds 100,000 tokens",
        ):
            with self.subTest(card="over_100k", fragment=fragment):
                self.assertIn(fragment, higher)
        self.assertTrue(higher.startswith("input 0.50,"), higher)
        # Batch halves both cards, and the same 100K threshold splits them.
        self.assertEqual(
            pricing["batch"], "input 0.05, output 0.25 up to 100K; input 0.25, output 1.25 above"
        )
        self.assertIn("a prompt over 100,000 tokens is billed on the higher price card", contract["limits_note"])
        self.assertIn("2027-10-07", contract["retirement"])
        # The superseded generation stays priced for an operator override.
        self.assertEqual(APPROX_PRICE_PER_MTOK["claude-haiku-4-5"], (1.0, 5.0))

    def test_family_blocks_apply(self) -> None:
        self.assertNotIn("claude-haiku-5-5", MODEL_HIGH_EFFORT_CALIBRATIONS)
        self.assertNotIn("claude-haiku-5-5", MODEL_COMPOSITION_CALIBRATIONS)
        route = resolve_model_route("hermes", requested_model="claude-haiku-5-5", requested_effort="max")
        self.assertEqual(route["model_family"], "claude")
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["claude"])


class KimiK31ProContractTests(unittest.TestCase):
    """Kimi K3.1 Pro (2026-10-23): the first Kimi exact contracts. A
    three-rung ladder the API enforces, so every other rung is raised on
    record, and a Highspeed tier with its own rate card."""

    _FORMS = ("kimi-k3.1-pro", "moonshotai/kimi-k3.1-pro", "openrouter/moonshotai/kimi-k3.1-pro")

    def test_both_ids_resolve_exact_contracts_and_older_kimi_ids_stay_uncontracted(self) -> None:
        for form in self._FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "kimi")
                self.assertEqual(contract_model_id(form), "kimi-k3.1-pro")
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")
        highspeed = model_contract_projection("moonshotai/kimi-k3.1-pro-highspeed")
        assert highspeed is not None
        self.assertEqual(highspeed["contract_model_id"], "kimi-k3.1-pro-highspeed")
        self.assertEqual(highspeed["service_tier"], "highspeed")
        self.assertEqual(highspeed["provenance"], "exact")
        # K3 and its gateway speed tier keep the family-only treatment, and the
        # Kimi Code plan's bare slugs are not aliased on a guess.
        for model_id in ("kimi-k3", "kimi-k3-ultrafast", "k3.1-pro", "kimi-k3.1", "kimi-k3.1-pro-turbo"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract(model_id))

    def test_off_ladder_rungs_are_raised_on_record_and_documented_rungs_pass(self) -> None:
        expected = {"off": "low", "none": "low", "minimal": "low", "medium": "high", "xhigh": "max"}
        for model in ("kimi-k3.1-pro", "kimi-k3.1-pro-highspeed"):
            for requested, selected in expected.items():
                route = resolve_model_route("hermes", requested_model=model, requested_effort=requested)
                with self.subTest(model=model, requested=requested):
                    self.assertEqual(route["selected_reasoning_effort"], selected)
                    self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
            for requested in ("low", "high", "max"):
                route = resolve_model_route("hermes", requested_model=model, requested_effort=requested)
                with self.subTest(model=model, requested=requested):
                    self.assertEqual(route["selected_reasoning_effort"], requested)
                    self.assertNotEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        # K3 itself is still uncontracted (retired from the chains, routable
        # by name): its route is unchanged.
        route = resolve_model_route("hermes", requested_model="kimi-k3", requested_effort="medium")
        self.assertEqual(route["selected_reasoning_effort"], "medium")
        self.assertEqual(route["effort_change"]["kind"], "catalog_no_authority_passthrough")

    def test_contract_records_the_ladder_limits_and_both_rate_cards(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        base = model_contract("kimi-k3.1-pro")
        fast = model_contract("kimi-k3.1-pro-highspeed")
        assert base is not None and fast is not None
        for contract in (base, fast):
            self.assertEqual(contract["reasoning_efforts"], ("low", "high", "max"))
            self.assertEqual((contract["effort_floor"], contract["effort_default"]), ("low", "max"))
            self.assertEqual(contract["context_window_tokens"], 1_048_576)
            self.assertEqual(contract["released"], "2026-10-23")
            self.assertEqual(contract["tool_calling"]["api"], "chat_completions")
            self.assertIn("thinking", contract["unsupported_parameters"])
            self.assertTrue(all(source.startswith("https://platform.kimi.ai/") for source in contract["sources"]))
            self.assertNotIn("dynamic_effort", contract)
            self.assertNotIn("entitled", json.dumps(dict(contract)).casefold())
            pricing = contract["pricing_usd_per_mtok"]
            self.assertEqual(APPROX_PRICE_PER_MTOK[contract["model_id"]], (pricing["input"], pricing["output"]))
            self.assertAlmostEqual(
                APPROX_CACHE_READ_RATIO.get(contract["model_id"], 0.1) * pricing["input"], pricing["cached_input"]
            )
        self.assertEqual((base["pricing_usd_per_mtok"]["input"], base["pricing_usd_per_mtok"]["output"]), (2.0, 10.0))
        self.assertEqual((fast["pricing_usd_per_mtok"]["input"], fast["pricing_usd_per_mtok"]["output"]), (4.0, 20.0))
        self.assertEqual(fast["pricing_usd_per_mtok"]["cached_input"], 0.20)
        self.assertEqual(fast["documented_traits"][1:], base["documented_traits"][1:])
        # K3's own row is unchanged.
        self.assertEqual(APPROX_PRICE_PER_MTOK["kimi-k3"], (3.0, 15.0))

    def test_the_kimi_family_blocks_apply_unchanged(self) -> None:
        for model in ("kimi-k3.1-pro", "kimi-k3.1-pro-highspeed"):
            with self.subTest(model=model):
                self.assertNotIn(model, MODEL_HIGH_EFFORT_CALIBRATIONS)
                self.assertNotIn(model, MODEL_COMPOSITION_CALIBRATIONS)
                route = resolve_model_route("hermes", requested_model=model, requested_effort="max")
                self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["kimi"])
                self.assertEqual(composition_calibration_for_model(model), MAIN_AGENT_COMPOSITION_CALIBRATIONS["kimi"])


class GeminiArgonContractTests(unittest.TestCase):
    """Gemini 4 Argon (GA 2026-10-13): the first Gemini exact contract. A
    `low`/`medium`/`high` ladder with no off switch, so the rungs below it are
    raised on record; the rungs above it have no documented rung to raise to
    and pass through. It took every Gemini 3.1 Pro slot on 2026-10-28."""

    _FORMS = ("gemini-4-argon", "google/gemini-4-argon", "openrouter/google/gemini-4-argon", "Gemini-4-Argon")

    def test_every_served_form_and_the_dated_snapshot_resolve_the_contract(self) -> None:
        contract = model_contract("gemini-4-argon")
        assert contract is not None
        for form in self._FORMS:
            with self.subTest(form=form):
                self.assertEqual(model_family(form), "gemini")
                self.assertIs(model_contract(form), contract)
                projection = model_contract_projection(form)
                assert projection is not None
                self.assertEqual(projection["provenance"], "exact")
        snapshot = model_contract_projection("google/gemini-4-argon-2026-10-13")
        assert snapshot is not None
        self.assertEqual(snapshot["contract_model_id"], "gemini-4-argon")
        self.assertEqual(snapshot["provenance"], "dated_snapshot")
        # The predecessor and spellings Google never published stay uncontracted.
        for model_id in ("gemini-3.1-pro", "gemini-4-argon-preview", "gemini-4", "gemini-4-argon-cyber-permissive"):
            with self.subTest(model_id=model_id):
                self.assertIsNone(model_contract_projection(model_id))

    def test_rungs_below_the_ladder_are_raised_and_rungs_above_pass_through(self) -> None:
        for model in ("gemini-4-argon", "google/gemini-4-argon-2026-10-13"):
            for requested in ("off", "none", "minimal"):
                route = resolve_model_route("hermes", requested_model=model, requested_effort=requested)
                with self.subTest(model=model, requested=requested):
                    self.assertEqual(route["selected_reasoning_effort"], "low")
                    self.assertEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
            # `xhigh` and `max` have no documented rung above them, so a raise
            # would land on the floor; the route keeps them, never lowers them.
            for requested in ("low", "medium", "high", "xhigh", "max"):
                route = resolve_model_route("hermes", requested_model=model, requested_effort=requested)
                with self.subTest(model=model, requested=requested):
                    self.assertEqual(route["selected_reasoning_effort"], requested)
                    self.assertNotEqual(route["effort_change"]["kind"], EFFORT_FLOOR_KIND)
        for effort in ("low", "medium", "high", "xhigh", "max", "ultra"):
            self.assertIsNone(contract_effort_floor("gemini-4-argon", effort), effort)

    def test_contract_records_the_ladder_limits_price_and_surfaces(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        contract = model_contract("gemini-4-argon")
        assert contract is not None
        self.assertEqual(contract["reasoning_efforts"], ("low", "medium", "high"))
        self.assertEqual((contract["effort_floor"], contract["effort_default"]), ("low", "medium"))
        self.assertEqual(set(contract["unsupported_efforts"]), {"off", "minimal"})
        self.assertEqual((contract["generation"], contract["released"]), ("gemini-4", "2026-10-13"))
        self.assertEqual(
            (contract["context_window_tokens"], contract["max_input_tokens"], contract["max_output_tokens"]),
            (1_048_576, 1_048_576, 65_536),
        )
        self.assertIn("32,768", contract["limits_note"])
        self.assertEqual(contract["unsupported_parameters"], ("temperature", "top_p", "top_k"))
        self.assertIn("observed in the Hermes source", contract["surface_notes"]["hermes"])
        self.assertIn("official-client", contract["surface_notes"]["gemini_cli"])
        self.assertTrue(contract["surface_notes"]["openrouter"].endswith("community"))
        pricing = contract["pricing_usd_per_mtok"]
        self.assertEqual((pricing["input"], pricing["cached_input"], pricing["output"]), (2.0, 0.10, 10.0))
        self.assertIn("input 4.00", pricing["from_2026_12_01"])
        self.assertEqual(APPROX_PRICE_PER_MTOK["gemini-4-argon"], (pricing["input"], pricing["output"]))
        self.assertAlmostEqual(pricing["input"] * APPROX_CACHE_READ_RATIO["gemini-4-argon"], pricing["cached_input"])
        self.assertTrue(all(source.startswith("https://ai.google.dev/") for source in contract["sources"]))
        self.assertEqual(contract["sources_read"], "2026-10-28")
        self.assertNotIn("entitled", json.dumps(dict(contract)).casefold())
        # The retired predecessor keeps its own list rate for overrides.
        self.assertEqual(APPROX_PRICE_PER_MTOK["gemini-3.1-pro"], (2.0, 12.0))

    def test_the_gemini_family_blocks_apply_unchanged(self) -> None:
        self.assertNotIn("gemini-4-argon", MODEL_HIGH_EFFORT_CALIBRATIONS)
        self.assertNotIn("gemini-4-argon", MODEL_COMPOSITION_CALIBRATIONS)
        route = resolve_model_route("hermes", requested_model="gemini-4-argon", requested_effort="high")
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["gemini"])
        self.assertEqual(
            composition_calibration_for_model("gemini-4-argon"), MAIN_AGENT_COMPOSITION_CALIBRATIONS["gemini"]
        )

    def test_the_cli_prints_the_ladder(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "model-contract", "--model", "gemini-4-argon"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("reasoning efforts: low, medium, high (floor `low`)", stdout)


class GrokBuildPriceTests(unittest.TestCase):
    """Grok Build 0.1 took the X-platform slot on 2026-10-01; xAI lists the
    retired Grok Code Fast ids as its aliases, so both spellings price alike."""

    def test_both_spellings_carry_the_build_rate_and_its_cache_ratio(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import APPROX_CACHE_READ_RATIO

        for model_id in ("grok-build-0.1", "grok-code-fast"):
            with self.subTest(model_id=model_id):
                self.assertEqual(APPROX_PRICE_PER_MTOK[model_id], (1.0, 2.0))
                # Cached input 0.20 on 1.00 input: a fifth, not the default tenth.
                self.assertAlmostEqual(APPROX_CACHE_READ_RATIO[model_id] * 1.0, 0.20)


if __name__ == "__main__":
    unittest.main()
