from __future__ import annotations

import json
import math
import unittest

from _local_package import load_local_package

load_local_package()

from omh.quality.agreement_stats import agreement_stats  # noqa: E402
from omh.quality.reported_rate import reported_rate_shape_errors  # noqa: E402


class AgreementStatsTests(unittest.TestCase):
    def test_perfect_agreement(self) -> None:
        stats = agreement_stats([(True, True)] * 3 + [(False, False)] * 2)
        self.assertEqual(stats["schema_version"], "agreement_stats/v1")
        self.assertEqual(
            stats["table"],
            {"both_include": 3, "both_exclude": 2, "a_only_include": 0, "b_only_include": 0, "n": 5},
        )
        self.assertEqual(stats["observed_agreement"]["percent"], 100.0)
        self.assertEqual(stats["cohen_kappa"], 1.0)
        self.assertEqual(stats["pabak"], 1.0)
        self.assertEqual(stats["kappa_undefined_reason"], "")
        self.assertEqual(stats["prevalence_note"], "")
        self.assertEqual(reported_rate_shape_errors(stats["observed_agreement"]), ())

    def test_total_disagreement(self) -> None:
        stats = agreement_stats([(True, False)] * 2 + [(False, True)] * 2)
        self.assertEqual(stats["table"]["a_only_include"], 2)
        self.assertEqual(stats["table"]["b_only_include"], 2)
        self.assertEqual(stats["observed_agreement"]["percent"], 0.0)
        self.assertEqual(stats["cohen_kappa"], -1.0)
        self.assertEqual(stats["pabak"], -1.0)

    def test_empty_input_is_unmeasured_never_zero(self) -> None:
        stats = agreement_stats([])
        self.assertEqual(stats["table"]["n"], 0)
        self.assertIsNone(stats["observed_agreement"]["percent"])
        self.assertEqual(stats["observed_agreement"]["basis"], "no_observations")
        self.assertIsNone(stats["cohen_kappa"])
        self.assertIsNone(stats["pabak"])
        self.assertEqual(stats["kappa_undefined_reason"], "no_observations")
        self.assertEqual(stats["prevalence_note"], "")
        self.assertEqual(reported_rate_shape_errors(stats["observed_agreement"]), ())

    def test_one_category_only_leaves_kappa_undefined(self) -> None:
        for pair in ((True, True), (False, False)):
            with self.subTest(pair=pair):
                stats = agreement_stats([pair] * 4)
                self.assertIsNone(stats["cohen_kappa"])
                self.assertEqual(stats["kappa_undefined_reason"], "expected_agreement_is_one")
                self.assertEqual(stats["pabak"], 1.0)
                self.assertEqual(stats["observed_agreement"]["percent"], 100.0)
                self.assertEqual(stats["prevalence_note"], "")

    def test_high_prevalence_makes_kappa_and_pabak_diverge(self) -> None:
        pairs = [(True, True)] * 85 + [(False, False)] * 5 + [(True, False)] * 5 + [(False, True)] * 5
        stats = agreement_stats(pairs)
        self.assertEqual(stats["observed_agreement"]["percent"], 90.0)
        self.assertEqual(stats["cohen_kappa"], 0.444)
        self.assertEqual(stats["pabak"], 0.8)
        self.assertEqual(stats["prevalence_note"], "kappa_and_pabak_diverge")

    def test_observed_agreement_is_a_reported_rate_naming_its_buckets(self) -> None:
        stats = agreement_stats([(True, True), (False, True), (False, False)])
        rate = stats["observed_agreement"]
        self.assertEqual(reported_rate_shape_errors(rate), ())
        self.assertEqual(rate["numerator_of"], ["both_include", "both_exclude"])
        self.assertEqual(rate["denominator_of"], "records both reviewers decided")
        self.assertEqual((rate["numerator"], rate["denominator"]), (2, 3))

    def test_excluded_observation_classes_are_named_with_their_counts(self) -> None:
        stats = agreement_stats([(True, True)], excluded={"records_with_unsure": 8, "pending_records": 1, "other": 0})
        rate = stats["observed_agreement"]
        self.assertEqual(reported_rate_shape_errors(rate), ())
        self.assertEqual(rate["excluded"], ["records_with_unsure", "pending_records"])
        self.assertEqual(stats["excluded_counts"], {"records_with_unsure": 8, "pending_records": 1, "other": 0})
        bare = agreement_stats([(True, True)])
        self.assertEqual((bare["observed_agreement"]["excluded"], bare["excluded_counts"]), ([], {}))

    def test_divergence_of_exactly_point_two_is_flagged(self) -> None:
        stats = agreement_stats([(True, False)] + [(False, True)] * 2)
        self.assertEqual((stats["cohen_kappa"], stats["pabak"]), (-0.8, -1.0))
        self.assertEqual(stats["prevalence_note"], "kappa_and_pabak_diverge")

    def test_kappa_is_never_negative_zero(self) -> None:
        stats = agreement_stats([(False, False)] + [(False, True)] * 2)
        self.assertEqual(json.dumps(stats["cohen_kappa"]), "0.0")
        self.assertEqual(math.copysign(1.0, stats["cohen_kappa"]), 1.0)

    def test_claim_boundary_is_not_accuracy(self) -> None:
        self.assertIn("not correctness", agreement_stats([])["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
