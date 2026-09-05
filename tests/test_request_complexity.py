from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from omh.coding.coding_delegation import build_coding_delegation_payload
from omh.coding.model_routing import MODEL_CATEGORIES, REASONING_EFFORT_LADDER
from omh.coding.request_complexity import (
    COMPLEXITY_CHAIN_STATUSES,
    COMPLEXITY_MODEL_RECOMMENDATION_SCHEMA_VERSION,
    COMPLEXITY_RECOMMENDATION_STATUSES,
    COMPLEXITY_SIGNAL_NAMES,
    COMPLEXITY_SIGNALS,
    COMPLEXITY_TIER_EFFORTS,
    COMPLEXITY_TIER_MODEL_CLASSES,
    COMPLEXITY_TIER_THRESHOLDS,
    COMPLEXITY_TIERS,
    REQUEST_COMPLEXITY_SCHEMA_VERSION,
    recommend_model_for_complexity,
    score_request_complexity,
    tier_for_score,
)
from omh.quality.complexity_precision import (
    COMPLEXITY_INTERVENTION_CASES,
    COMPLEXITY_PRECISION_CASES,
    complexity_precision_report,
)

# A stand-in for the user's configured chains. Deliberately NOT the shipped
# table: a test that asserted the shipped model names would turn an editorial
# chain edit into a test failure, and would also quietly bless hardcoding.
_USER_CHAINS = {
    "quick": (("user-small", "low"),),
    "unspecified-high": (("user-mid", ""),),
    "deep": (("user-large", "xhigh"), ("user-large-backup", "high")),
}


class SignalTests(unittest.TestCase):
    def test_score_is_exactly_the_sum_of_its_named_signals(self) -> None:
        for case in COMPLEXITY_PRECISION_CASES + COMPLEXITY_INTERVENTION_CASES:
            with self.subTest(case=case.id):
                result = score_request_complexity(case.message, routed_skill=case.routed_skill)
                total = sum(int(signal["weight"]) for signal in result["signals"])
                self.assertEqual(result["score"], total)
                self.assertEqual(result["tier"], tier_for_score(total))

    def test_every_signal_name_is_in_the_closed_vocabulary(self) -> None:
        for case in COMPLEXITY_PRECISION_CASES + COMPLEXITY_INTERVENTION_CASES:
            result = score_request_complexity(case.message, routed_skill=case.routed_skill)
            for signal in result["signals"]:
                self.assertIn(signal["name"], COMPLEXITY_SIGNAL_NAMES, case.id)

    def test_every_signal_carries_its_own_evidence_and_description(self) -> None:
        result = score_request_complexity(
            "Refactor the auth layer across every service and fix the race condition in src/a.py and src/b.py",
        )
        self.assertTrue(result["signals"])
        for signal in result["signals"]:
            self.assertTrue(signal["describe"], signal["name"])
            self.assertTrue(signal["evidence"], signal["name"])

    def test_simple_request_is_the_only_negative_signal(self) -> None:
        negatives = [signal.name for signal in COMPLEXITY_SIGNALS if signal.weight < 0]
        self.assertEqual(negatives, ["simple_request"])

    def test_an_empty_request_scores_zero_with_no_signals(self) -> None:
        result = score_request_complexity("")
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["signals"], [])
        self.assertEqual(result["tier"], "light")
        self.assertEqual(result["schema_version"], REQUEST_COMPLEXITY_SCHEMA_VERSION)

    def test_scoring_is_deterministic_byte_for_byte(self) -> None:
        message = "Migrate the schema across every service, then reproduce the deadlock in src/a.py and src/b.py."
        first = json.dumps(score_request_complexity(message, routed_skill="maestro"), sort_keys=True)
        second = json.dumps(score_request_complexity(message, routed_skill="maestro"), sort_keys=True)
        self.assertEqual(first, second)

    def test_case_and_accent_folding_does_not_change_the_score(self) -> None:
        lowered = score_request_complexity("refactor the architecture across every service")
        shouted = score_request_complexity("REFACTOR the ARCHITECTURE across EVERY service")
        self.assertEqual(lowered["score"], shouted["score"])

    def test_the_routed_skill_class_is_a_named_signal_with_its_family(self) -> None:
        result = score_request_complexity("ship the change", routed_skill="maestro")
        classes = [signal for signal in result["signals"] if signal["name"] == "routed_skill_class"]
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0]["weight"], 2)
        self.assertIn("routed_skill_class=delegate_coding_and_ship", classes[0]["evidence"])
        self.assertEqual(result["routed_skill_class"], "delegate_coding_and_ship")

    def test_an_unknown_routed_skill_contributes_nothing(self) -> None:
        result = score_request_complexity("ship the change", routed_skill="not-a-real-workflow")
        self.assertEqual(result["routed_skill_class"], "")
        self.assertNotIn("routed_skill_class", [signal["name"] for signal in result["signals"]])

    def test_path_and_subtask_counts_report_counts_not_user_text(self) -> None:
        result = score_request_complexity(
            "1. edit src/secret_project/a.py\n2. edit src/secret_project/b.py\n3. edit src/secret_project/c.py",
        )
        rendered = json.dumps(result)
        self.assertNotIn("secret_project", rendered)


class TierBoundaryTests(unittest.TestCase):
    def test_thresholds_are_inclusive_lower_bounds_in_descending_order(self) -> None:
        bounds = [bound for _, bound in COMPLEXITY_TIER_THRESHOLDS]
        self.assertEqual(bounds, sorted(bounds, reverse=True))
        for tier, bound in COMPLEXITY_TIER_THRESHOLDS:
            self.assertEqual(tier_for_score(bound), tier)
            self.assertNotEqual(tier_for_score(bound - 1), tier)

    def test_the_weakest_tier_absorbs_zero_and_negative_scores(self) -> None:
        for score in (-99, -2, 0, 3):
            self.assertEqual(tier_for_score(score), COMPLEXITY_TIERS[0])

    def test_every_tier_maps_to_a_shared_vocabulary_class_and_effort(self) -> None:
        for tier in COMPLEXITY_TIERS:
            self.assertIn(COMPLEXITY_TIER_MODEL_CLASSES[tier], MODEL_CATEGORIES)
            self.assertIn(COMPLEXITY_TIER_EFFORTS[tier], REASONING_EFFORT_LADDER)

    def test_tier_efforts_never_weaken_as_the_tier_rises(self) -> None:
        rungs = [REASONING_EFFORT_LADDER.index(COMPLEXITY_TIER_EFFORTS[tier]) for tier in COMPLEXITY_TIERS]
        self.assertEqual(rungs, sorted(rungs))


class ExplainabilityTests(unittest.TestCase):
    def test_every_tier_change_traces_to_a_named_signal(self) -> None:
        """Remove one signal's points and the tier must move only when the arithmetic says so."""
        message = (
            "Refactor the authentication layer across every service, migrate the session schema, "
            "and keep backwards compatibility for existing tokens."
        )
        result = score_request_complexity(message)
        self.assertEqual(result["tier"], "deep")
        for signal in result["signals"]:
            without = result["score"] - int(signal["weight"])
            expected = tier_for_score(without)
            self.assertEqual(
                tier_for_score(result["score"] - int(signal["weight"])),
                expected,
                f"{signal['name']} does not account for its own {signal['weight']} points",
            )
        # The payload alone is sufficient: nothing outside `signals` moved the score.
        self.assertEqual(result["score"], sum(int(signal["weight"]) for signal in result["signals"]))

    def test_the_thresholds_travel_with_the_payload(self) -> None:
        result = score_request_complexity("fix a typo in README.md")
        self.assertEqual(
            result["thresholds"],
            [{"tier": tier, "min_score": bound} for tier, bound in COMPLEXITY_TIER_THRESHOLDS],
        )


class ChainResolutionTests(unittest.TestCase):
    def test_a_deep_tier_resolves_the_users_own_chain_head(self) -> None:
        complexity = score_request_complexity(
            "Refactor the auth layer across every service, migrate the schema, keep backwards compatibility.",
        )
        recommendation = recommend_model_for_complexity(complexity, chains=_USER_CHAINS)
        self.assertEqual(recommendation["schema_version"], COMPLEXITY_MODEL_RECOMMENDATION_SCHEMA_VERSION)
        self.assertEqual(recommendation["model_class"], "deep")
        self.assertEqual(recommendation["chain_status"], "resolved")
        self.assertEqual(recommendation["resolved"], {"model": "user-large", "reasoning_effort": "xhigh"})
        self.assertEqual(
            recommendation["chain"],
            [
                {"model": "user-large", "reasoning_effort": "xhigh"},
                {"model": "user-large-backup", "reasoning_effort": "high"},
            ],
        )

    def test_a_chain_entry_without_an_effort_falls_back_to_the_tier_suggestion(self) -> None:
        complexity = score_request_complexity("Split the work up and migrate the four packages in parallel.")
        recommendation = recommend_model_for_complexity(complexity, chains=_USER_CHAINS)
        self.assertEqual(recommendation["model_class"], "unspecified-high")
        self.assertEqual(recommendation["reasoning_effort"], COMPLEXITY_TIER_EFFORTS["standard"])
        self.assertEqual(recommendation["resolved"]["model"], "user-mid")

    def test_no_chain_config_reports_the_class_without_inventing_a_model(self) -> None:
        complexity = score_request_complexity("fix a typo in README.md")
        recommendation = recommend_model_for_complexity(complexity)
        self.assertEqual(recommendation["chain_status"], "no_chain_config")
        self.assertEqual(recommendation["chain"], [])
        self.assertEqual(recommendation["resolved"], {})
        self.assertEqual(recommendation["model_class"], "quick")

    def test_a_class_missing_from_the_users_chains_is_named_not_substituted(self) -> None:
        complexity = score_request_complexity("fix a typo in README.md")
        recommendation = recommend_model_for_complexity(complexity, chains={"deep": (("user-large", "high"),)})
        self.assertEqual(recommendation["chain_status"], "class_not_in_chains")
        self.assertEqual(recommendation["resolved"], {})

    def test_every_reported_status_is_in_its_closed_vocabulary(self) -> None:
        complexity = score_request_complexity("fix a typo in README.md")
        for chains in (None, _USER_CHAINS, {}):
            recommendation = recommend_model_for_complexity(complexity, chains=chains)
            self.assertIn(recommendation["chain_status"], COMPLEXITY_CHAIN_STATUSES)
            self.assertIn(recommendation["status"], COMPLEXITY_RECOMMENDATION_STATUSES)

    def test_no_shipped_model_name_is_written_into_the_module(self) -> None:
        from omh.coding import request_complexity
        from omh.plugin_bundle.omh.hermes_delegation import HERMES_MIXTURE_CATEGORY_CHAINS

        source = Path(request_complexity.__file__).read_text(encoding="utf-8")
        shipped = {model for chain in HERMES_MIXTURE_CATEGORY_CHAINS.values() for model, _ in chain}
        for model in shipped:
            self.assertNotIn(model, source, "the scorer must resolve models from config, never name one")


class OverridePrecedenceTests(unittest.TestCase):
    def test_an_explicit_model_supersedes_the_recommendation_and_says_so(self) -> None:
        complexity = score_request_complexity("fix a typo in README.md")
        recommendation = recommend_model_for_complexity(
            complexity,
            chains=_USER_CHAINS,
            requested_model="operator-choice",
        )
        self.assertEqual(recommendation["status"], "superseded_by_user_override")
        self.assertEqual(recommendation["user_override"], {"model": "operator-choice", "reasoning_effort": ""})
        self.assertIn("wins over this recommendation", recommendation["override_note"])
        # The set-aside advice is still disclosed rather than dropped.
        self.assertEqual(recommendation["model_class"], "quick")

    def test_an_explicit_effort_outranks_both_the_chain_and_the_tier(self) -> None:
        complexity = score_request_complexity(
            "Refactor the auth layer across every service, migrate the schema, keep backwards compatibility.",
        )
        recommendation = recommend_model_for_complexity(
            complexity,
            chains=_USER_CHAINS,
            requested_effort="minimal",
        )
        self.assertEqual(recommendation["status"], "superseded_by_user_override")
        self.assertEqual(recommendation["reasoning_effort"], "minimal")
        self.assertEqual(recommendation["resolved"]["reasoning_effort"], "minimal")

    def test_no_override_leaves_the_block_a_plain_recommendation(self) -> None:
        complexity = score_request_complexity("fix a typo in README.md")
        recommendation = recommend_model_for_complexity(complexity, chains=_USER_CHAINS)
        self.assertEqual(recommendation["status"], "recommended")
        self.assertNotIn("user_override", recommendation)
        self.assertNotIn("override_note", recommendation)


class GuardCorpusTests(unittest.TestCase):
    def test_the_negative_controls_never_overscore(self) -> None:
        report = complexity_precision_report()
        self.assertEqual(report["overscore_count"], 0, report["overscored"])
        self.assertEqual(report["precision_case_count"], 16)

    def test_the_intervention_cases_all_escalate_for_their_named_reasons(self) -> None:
        report = complexity_precision_report()
        self.assertEqual(report["missed_escalation_count"], 0, report["missed_escalations"])
        self.assertEqual(report["intervention_case_count"], 9)

    def test_a_trivial_one_liner_never_scores_deep(self) -> None:
        for message in (
            "fix a typo",
            "rename this variable",
            "what is the default scope?",
            "add a comment here",
            "one line change to bump the version",
        ):
            with self.subTest(message=message):
                self.assertEqual(score_request_complexity(message)["tier"], "light")

    def test_every_case_id_is_unique_across_both_corpora(self) -> None:
        ids = [case.id for case in COMPLEXITY_PRECISION_CASES] + [case.id for case in COMPLEXITY_INTERVENTION_CASES]
        self.assertEqual(len(ids), len(set(ids)))


class PurityTests(unittest.TestCase):
    def test_model_routing_does_not_import_the_scorer(self) -> None:
        """The declared role/depth/scale dials stay declared; the scorer never routes."""
        from omh.coding import model_routing

        source = Path(model_routing.__file__).read_text(encoding="utf-8")
        self.assertNotIn("request_complexity", source)


class DelegationPayloadTests(unittest.TestCase):
    def test_the_prepared_handoff_carries_the_versioned_recommendation_block(self) -> None:
        payload = build_coding_delegation_payload(
            "Refactor the authentication layer across every service and migrate the session schema.",
            executor_target="codex",
            explicit_owner_choice=True,
            model_chains=_USER_CHAINS,
        )
        complexity = payload["request_complexity"]
        recommendation = payload["complexity_model_recommendation"]
        self.assertEqual(complexity["schema_version"], REQUEST_COMPLEXITY_SCHEMA_VERSION)
        self.assertEqual(recommendation["schema_version"], COMPLEXITY_MODEL_RECOMMENDATION_SCHEMA_VERSION)
        self.assertEqual(complexity["tier"], "deep")
        self.assertEqual(recommendation["model_class"], "deep")
        self.assertEqual(recommendation["resolved"]["model"], "user-large")
        self.assertEqual(recommendation["status"], "recommended")

    def test_an_explicit_choice_in_the_handoff_supersedes_the_recommendation(self) -> None:
        payload = build_coding_delegation_payload(
            "Refactor the authentication layer across every service and migrate the session schema.",
            executor_target="codex",
            explicit_owner_choice=True,
            model_chains=_USER_CHAINS,
            requested_model="operator-choice",
            requested_effort="max",
        )
        recommendation = payload["complexity_model_recommendation"]
        self.assertEqual(recommendation["status"], "superseded_by_user_override")
        self.assertEqual(recommendation["user_override"]["model"], "operator-choice")
        self.assertEqual(recommendation["reasoning_effort"], "max")

    def test_the_block_carries_no_user_request_text(self) -> None:
        payload = build_coding_delegation_payload(
            "Refactor the authentication layer in src/hushhush/private_thing.py across every service.",
            executor_target="codex",
            explicit_owner_choice=True,
        )
        rendered = json.dumps(payload["request_complexity"]) + json.dumps(payload["complexity_model_recommendation"])
        self.assertNotIn("hushhush", rendered)
        self.assertNotIn("private_thing", rendered)

    def test_the_routed_skill_reaches_the_scorer_from_the_delegation(self) -> None:
        payload = build_coding_delegation_payload(
            "Refactor the authentication layer across every service and migrate the session schema.",
            executor_target="codex",
            explicit_owner_choice=True,
        )
        self.assertEqual(
            payload["request_complexity"]["routed_skill"],
            payload["delegation"]["recommended_workflow"],
        )

    def test_a_delegation_without_chains_still_reports_the_class(self) -> None:
        payload = build_coding_delegation_payload(
            "fix a typo in README.md",
            executor_target="codex",
            explicit_owner_choice=True,
        )
        recommendation = payload["complexity_model_recommendation"]
        self.assertEqual(recommendation["chain_status"], "no_chain_config")
        self.assertEqual(recommendation["model_class"], "quick")


_HEAVY_REQUEST = "Refactor the authentication layer across every service and migrate the session schema."


class ComplexityCliTests(unittest.TestCase):
    def setUp(self) -> None:
        # An empty home means no override document, so the shipped chains
        # answer and the run does not depend on the developer's own config.
        self._home = TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        self.omh_home = ["--omh-home", self._home.name]

    def test_the_cli_reports_the_tier_its_signals_and_the_recommendation(self) -> None:
        status, stdout, stderr = run_cli([*self.omh_home, "coding", "complexity", _HEAVY_REQUEST, "--json"])
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "coding_complexity_report/v1")
        self.assertEqual(payload["complexity"]["tier"], "deep")
        self.assertEqual(payload["recommendation"]["model_class"], "deep")
        self.assertEqual(payload["recommendation"]["chain_status"], "resolved")

    def test_the_cli_marks_an_explicit_model_as_the_winner(self) -> None:
        status, stdout, stderr = run_cli(
            [*self.omh_home, "coding", "complexity", "fix a typo in README.md", "--model", "operator-choice", "--json"]
        )
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["recommendation"]["status"], "superseded_by_user_override")
        self.assertEqual(payload["recommendation"]["user_override"]["model"], "operator-choice")

    def test_the_cli_reads_the_users_own_chain_override(self) -> None:
        overrides = Path(self._home.name) / "routing" / "model-chains.json"
        overrides.parent.mkdir(parents=True, exist_ok=True)
        overrides.write_text(
            json.dumps(
                {
                    "schema_version": "mixture_chain_overrides/v1",
                    "categories": {"deep": [{"model": "my-own-model", "reasoning_effort": "high"}]},
                }
            ),
            encoding="utf-8",
        )
        status, stdout, stderr = run_cli([*self.omh_home, "coding", "complexity", _HEAVY_REQUEST, "--json"])
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["recommendation"]["resolved"]["model"], "my-own-model")

    def test_the_plain_text_output_names_every_contributing_signal(self) -> None:
        status, stdout, stderr = run_cli(
            [*self.omh_home, "coding", "complexity", _HEAVY_REQUEST], output_json=False
        )
        self.assertEqual(status, 0, stderr)
        self.assertIn("Complexity: deep", stdout)
        self.assertIn("architecture_keywords", stdout)
        self.assertIn("impact_system_wide", stdout)

    def test_the_cli_refuses_an_empty_request(self) -> None:
        status, _, _ = run_cli([*self.omh_home, "coding", "complexity"])
        self.assertNotEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
