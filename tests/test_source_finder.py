from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.source_finder import (
    SOURCE_ACQUISITION_STATUS_SCHEMA_VERSION,
    SOURCE_CANDIDATE_SET_SCHEMA_VERSION,
    SOURCE_FINDER_PLAN_SCHEMA_VERSION,
    build_source_acquisition_status,
    build_source_candidate,
    build_source_finder_plan,
    normalize_acquisition_state,
    normalize_source_kind,
    validate_source_acquisition_status,
    validate_source_candidate,
    validate_source_finder_plan,
)


class SourceFinderTests(unittest.TestCase):
    def test_builds_valid_source_finder_plan_without_observed_claims(self) -> None:
        candidate = build_source_candidate(
            title="Browser agent benchmark dataset",
            kind="dataset",
            summary="Candidate dataset for evaluating browser agents.",
            tags=("benchmark", "browser"),
        )
        plan = build_source_finder_plan(
            request="find papers, datasets, and repos for browser agent benchmarks",
            desired_kinds=("paper", "dataset", "github repo"),
            source_boundaries=("public sources only", "prefer maintained repos"),
            candidates=(candidate,),
        )

        self.assertEqual(plan["schema_version"], SOURCE_FINDER_PLAN_SCHEMA_VERSION)
        self.assertEqual(plan["source_candidate_set"]["schema_version"], SOURCE_CANDIDATE_SET_SCHEMA_VERSION)
        self.assertEqual(plan["source_candidate_set"]["candidates"][0]["kind"], "dataset")
        self.assertEqual(plan["source_candidate_set"]["candidates"][0]["acquisition_state"], "candidate_prepared")
        self.assertEqual(plan["source_candidate_set"]["candidates"][0]["observation_provenance"], "unknown")
        self.assertIn("download_execution", plan["not_evidence_until_observed"])
        self.assertEqual(validate_source_finder_plan(plan), [])

    def test_observed_state_requires_provenance(self) -> None:
        without_provenance = build_source_candidate(
            title="Observed looking source",
            kind="paper",
            acquisition_state="download_observed",
        )
        with_provenance = build_source_candidate(
            title="Observed paper",
            kind="paper",
            acquisition_state="download_observed",
            observation_provenance="wrapper",
            evidence_uri="file:///tmp/paper.pdf",
        )
        status = build_source_acquisition_status(with_provenance)

        self.assertEqual(without_provenance["acquisition_state"], "candidate_prepared")
        self.assertEqual(with_provenance["acquisition_state"], "download_observed")
        self.assertEqual(status["schema_version"], SOURCE_ACQUISITION_STATUS_SCHEMA_VERSION)
        self.assertIn("download_observed", status["observed_states"])
        self.assertEqual(validate_source_candidate(with_provenance), [])
        self.assertEqual(validate_source_acquisition_status(status), [])

    def test_recorded_and_checked_states_require_provenance(self) -> None:
        for acquisition_state in ("file_hash_recorded", "license_checked", "downstream_selected"):
            with self.subTest(acquisition_state=acquisition_state):
                candidate = build_source_candidate(
                    title="Evidence-looking source",
                    kind="dataset",
                    acquisition_state=acquisition_state,
                )

                self.assertEqual(candidate["acquisition_state"], "candidate_prepared")

    def test_status_does_not_infer_prior_observed_states(self) -> None:
        candidate = build_source_candidate(
            title="License-only source",
            kind="dataset",
            acquisition_state="license_checked",
            observation_provenance="wrapper",
            evidence_note="Wrapper recorded a license note only.",
        )
        status = build_source_acquisition_status(candidate)

        self.assertEqual(status["observed_states"], ["license_checked"])
        self.assertIn("download_observed", status["missing_states"])
        self.assertIn("file_hash_recorded", status["missing_states"])
        self.assertIn("text_extraction_observed", status["missing_states"])

    def test_normalizes_source_kind_and_acquisition_aliases(self) -> None:
        self.assertEqual(normalize_source_kind("GitHub repo"), "github_repo")
        self.assertEqual(normalize_source_kind("public slides"), "presentation")
        self.assertEqual(normalize_source_kind("RFC"), "docs_spec")
        self.assertEqual(normalize_acquisition_state("downloaded", provenance="user"), "download_observed")
        self.assertEqual(normalize_acquisition_state("downloaded"), "candidate_prepared")


if __name__ == "__main__":
    unittest.main()
