from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.quality.evidence_records import (
    QUALITY_EVIDENCE_OBSERVATION_SCHEMA,
    assess_quality_evidence,
    build_quality_evidence_observation,
    build_quality_evidence_package,
    validate_quality_evidence_observation,
    validate_quality_evidence_package,
)


class QualityEvidenceRecordsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.omh_home = Path(self._tmp.name)
        self.package = build_quality_evidence_package(
            repository_id="local/omh",
            commit_sha="abc123",
            tree_sha="tree123",
            title="quality records",
            executor_target="generic-executor",
            scenarios=({"id": "scenario-pass", "risk": "high"},),
            review_requirements=({"id": "review-independent", "kind": "review"},),
            self_critique_questions=("What changed without direct evidence?",),
        )

    def _observation(self, **changes: object) -> dict[str, object]:
        observation = {
            "schema_version": QUALITY_EVIDENCE_OBSERVATION_SCHEMA,
            "evidence_id": "e1",
            "evidence_kind": "test",
            "result": "passed",
            "reference": "tests/test_quality_evidence_records.py",
            "observed_at": "2026-07-16T00:00:00+00:00",
            "reporter": "executor",
            "source": {"repository_id": "local/omh", "commit_sha": "abc123", "tree_sha": "tree123"},
            "provenance": "omh_observed_record",
            "record_ref": "runtime/observation-1",
            "scenario_ids": ["scenario-pass"],
            "review_requirement_ids": [],
            "claim_ids": [],
        }
        observation.update(changes)
        observation["record_ref"] = f"runtime/{observation['evidence_id']}.json"
        self._write_record(observation)
        return observation

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_record(self, observation: dict[str, object]) -> None:
        ref = str(observation.get("record_ref") or "")
        if not ref.startswith("runtime/"):
            return
        path = self.omh_home / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "record_type": "quality_evidence_observation",
            "source": observation["source"],
            "evidence_id": observation["evidence_id"],
            "evidence_kind": observation["evidence_kind"],
            "result": observation["result"],
            "reference": observation["reference"],
            "observed_at": observation["observed_at"],
            "reporter": observation["reporter"],
            "scenario_ids": observation.get("scenario_ids", []),
            "review_requirement_ids": observation.get("review_requirement_ids", []),
            "claim_ids": observation.get("claim_ids", []),
            **({"independence": observation["independence"]} if "independence" in observation else {}),
            "executor_target": self.package["subject"]["executor_target"],
            "observed": True,
            "provenance": "omh_observed_record",
        }), encoding="utf-8")

    def test_prepared_package_has_explicit_boundary_and_source_identity(self) -> None:
        self.assertEqual(self.package["status"], "prepared_not_observed")
        self.assertEqual(self.package["subject"]["source"]["tree_sha"], "tree123")
        self.assertIn("not observed", self.package["claim_boundary"])

    def test_invalid_prepared_package_returns_deterministic_errors(self) -> None:
        invalid = dict(self.package)
        invalid["status"] = "observed"
        invalid["subject"] = {"title": "missing source"}
        self.assertEqual(validate_quality_evidence_package(invalid), ["invalid_prepared_status", "invalid_subject", "invalid_source_identity"])

    def test_package_requires_exact_fields_boundary_and_string_questions(self) -> None:
        missing_boundary = dict(self.package)
        missing_boundary.pop("claim_boundary")
        self.assertIn("invalid_top_level_fields", validate_quality_evidence_package(missing_boundary))
        self.assertIn("missing_claim_boundary", validate_quality_evidence_package(missing_boundary))
        forged = dict(self.package)
        forged["extra"] = True
        forged["self_critique_questions"] = ["ok", 42]
        errors = validate_quality_evidence_package(forged)
        self.assertIn("invalid_top_level_fields", errors)
        self.assertIn("invalid_self_critique_questions", errors)
        with self.assertRaises(ValueError):
            assess_quality_evidence(forged)

    def test_observation_builder_binds_source_and_validates_ids(self) -> None:
        observation = build_quality_evidence_observation(
            self.package, evidence_id="built", evidence_kind="test", result="passed",
            reference="tests", observed_at="2026-07-16T00:00:00Z", reporter="executor",
            provenance="omh_observed_record", record_ref="runtime/built.json", scenario_ids=["scenario-pass"],
        )
        self.assertEqual(observation["source"], self.package["subject"]["source"])
        with self.assertRaises(ValueError):
            build_quality_evidence_observation(
                self.package, evidence_id="bad", evidence_kind="test", result="passed", reference="tests",
                observed_at="2026-07-16T00:00:00Z", reporter="executor", scenario_ids=["nope"],
            )

    def test_supplied_unverified_evidence_cannot_satisfy_scenario(self) -> None:
        supplied = self._observation(provenance="supplied_unverified", record_ref=None)
        self.assertEqual(validate_quality_evidence_observation(supplied, self.package), [])
        assessment = assess_quality_evidence(self.package, [supplied], omh_home=self.omh_home)
        self.assertEqual(assessment["dimensions"]["scenario_coverage"]["status"], "unknown")
        self.assertFalse(assessment["ready_for_completion"])
        self.assertIn("supplied_unverified_not_admissible", assessment["reasons"])

    def test_observed_record_must_resolve_inside_omh_and_match_source(self) -> None:
        observation = self._observation()
        observation["record_ref"] = "runtime/missing.json"
        assessment = assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)
        self.assertFalse(assessment["ready_for_completion"])
        self.assertIn("unresolved_observed_record", assessment["reasons"])
        self._write_record(observation)
        record = self.omh_home / str(observation["record_ref"])
        payload = json.loads(record.read_text(encoding="utf-8"))
        payload["source"]["tree_sha"] = "wrong-tree"
        record.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("unresolved_observed_record", assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)["reasons"])

    def test_observed_record_requires_explicit_observed_and_matching_executor(self) -> None:
        observation = self._observation()
        record = self.omh_home / str(observation["record_ref"])
        payload = json.loads(record.read_text(encoding="utf-8"))
        payload.pop("observed")
        record.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("unresolved_observed_record", assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)["reasons"])
        payload["observed"] = True
        payload["executor_target"] = "other-executor"
        record.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("unresolved_observed_record", assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)["reasons"])

    def test_observation_requires_nonblank_reporter_and_string_source(self) -> None:
        missing_reporter = self._observation(reporter=" ")
        self.assertIn("missing_reporter", validate_quality_evidence_observation(missing_reporter, self.package))
        nonstring_source = self._observation(source={"repository_id": 1, "commit_sha": "abc123", "tree_sha": "tree123"})
        self.assertIn("source_mismatch", validate_quality_evidence_observation(nonstring_source, self.package))

    def test_non_mapping_observation_fails_closed_without_raising(self) -> None:
        errors = validate_quality_evidence_observation("not-an-observation", self.package)
        assessment = assess_quality_evidence(self.package, ["not-an-observation"], omh_home=self.omh_home)

        self.assertEqual(errors, ["invalid_observation"])
        self.assertFalse(assessment["ready_for_completion"])
        self.assertIn("invalid_observation", assessment["reasons"])

    def test_package_rejects_extra_source_fields_and_malformed_lists(self) -> None:
        extra_source = dict(self.package)
        extra_source["subject"] = dict(self.package["subject"])
        extra_source["subject"]["source"] = {**self.package["subject"]["source"], "extra": "nope"}
        self.assertIn("invalid_source_identity", validate_quality_evidence_package(extra_source))
        malformed = dict(self.package)
        malformed["qa_scenarios"] = None
        malformed["review_requirements"] = 1
        malformed["claim_requirements"] = None
        errors = validate_quality_evidence_package(malformed)
        self.assertIn("invalid_qa_scenarios", errors)
        self.assertIn("invalid_review_requirements", errors)
        self.assertIn("invalid_claim_requirements", errors)

    def test_observed_record_requires_exact_provenance_executor_and_binding(self) -> None:
        observation = self._observation()
        record = self.omh_home / str(observation["record_ref"])
        payload = json.loads(record.read_text(encoding="utf-8"))
        payload.pop("provenance")
        record.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("unresolved_observed_record", assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)["reasons"])
        payload["provenance"] = "omh_observed_record"
        payload.pop("executor_target")
        record.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("unresolved_observed_record", assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)["reasons"])
        payload["executor_target"] = self.package["subject"]["executor_target"]
        payload["reporter"] = "different"
        record.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("unresolved_observed_record", assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)["reasons"])

    def test_self_review_only_is_not_admissible_for_any_dimension(self) -> None:
        observation = self._observation(independence="self_review_only", claim_ids=[])
        assessment = assess_quality_evidence(self.package, [observation], omh_home=self.omh_home)
        self.assertFalse(assessment["ready_for_completion"])
        self.assertIn("self_review_only_not_admissible", assessment["reasons"])

    def test_source_drift_fails_closed(self) -> None:
        drifted = self._observation(source={"repository_id": "local/omh", "commit_sha": "new", "tree_sha": "tree123"})
        self.assertIn("source_mismatch", validate_quality_evidence_observation(drifted, self.package))
        assessment = assess_quality_evidence(self.package, [drifted], omh_home=self.omh_home)
        self.assertEqual(assessment["dimensions"]["source_freshness"]["status"], "unsatisfied")
        self.assertFalse(assessment["ready_for_completion"])

    def test_self_review_does_not_satisfy_independent_review(self) -> None:
        review = self._observation(
            evidence_id="review-self",
            evidence_kind="review",
            independence="self_review_only",
            review_requirement_ids=["review-independent"],
            scenario_ids=[],
        )
        assessment = assess_quality_evidence(self.package, [review], omh_home=self.omh_home)
        self.assertEqual(assessment["dimensions"]["review_independence"]["status"], "unknown")
        self.assertFalse(assessment["ready_for_completion"])

    def test_independent_observed_review_and_test_are_separate_dimensions(self) -> None:
        test = self._observation()
        review = self._observation(
            evidence_id="review-independent",
            evidence_kind="review",
            independence="independent",
            review_requirement_ids=["review-independent"],
            scenario_ids=[],
        )
        assessment = assess_quality_evidence(self.package, [test, review], omh_home=self.omh_home)
        self.assertEqual(assessment["dimensions"]["scenario_coverage"]["status"], "satisfied")
        self.assertEqual(assessment["dimensions"]["review_independence"]["status"], "satisfied")
        self.assertNotIn("score", assessment)
        self.assertEqual(assessment["dimensions"]["scenario_coverage"]["evidence_ids"], ["e1"])

    def test_claim_coverage_is_meaningful_when_claims_are_declared(self) -> None:
        package = build_quality_evidence_package(
            repository_id="local/omh", commit_sha="abc123", tree_sha="tree123", title="claims", executor_target="generic-executor",
            claim_requirements=({"id": "claim-1"},),
        )
        observation = build_quality_evidence_observation(
            package, evidence_id="claim-evidence", evidence_kind="test", result="passed", reference="tests",
            observed_at="2026-07-16T00:00:00Z", reporter="executor", claim_ids=["claim-1"],
            provenance="omh_observed_record", record_ref="runtime/claim.json",
        )
        self._write_record(observation)
        assessment = assess_quality_evidence(package, [observation], omh_home=self.omh_home)
        self.assertEqual(assessment["dimensions"]["claim_coverage"]["status"], "satisfied")
        self.assertEqual(assessment["dimensions"]["claim_coverage"]["evidence_ids"], ["claim-evidence"])

    def test_builder_and_assessment_reject_invalid_packages(self) -> None:
        with self.assertRaises(ValueError):
            build_quality_evidence_package(
                repository_id="local/omh", commit_sha="abc123", tree_sha="tree123", title="", executor_target="executor"
            )
        invalid = dict(self.package)
        invalid["status"] = "observed"
        with self.assertRaises(ValueError):
            assess_quality_evidence(invalid)

    def test_mixed_ci_pass_and_fail_remains_unsatisfied(self) -> None:
        package = build_quality_evidence_package(
            repository_id="local/omh", commit_sha="abc123", tree_sha="tree123", title="ci", executor_target="generic-executor",
            review_requirements=({"id": "ci-required", "kind": "ci"},),
        )
        observations = [
            build_quality_evidence_observation(
                package, evidence_id="ci-pass", evidence_kind="ci", result="passed", reference="ci", observed_at="2026-07-16T00:00:00Z",
                reporter="ci", provenance="omh_observed_record", record_ref="runtime/ci-pass.json",
                review_requirement_ids=["ci-required"],
            ),
            build_quality_evidence_observation(
                package, evidence_id="ci-fail", evidence_kind="ci", result="failed", reference="ci", observed_at="2026-07-16T00:00:00Z",
                reporter="ci", provenance="omh_observed_record", record_ref="runtime/ci-fail.json",
                review_requirement_ids=["ci-required"],
            ),
        ]
        for item in observations:
            self._write_record(item)
        self.assertEqual(assess_quality_evidence(package, observations, omh_home=self.omh_home)["dimensions"]["ci_status"]["status"], "unsatisfied")

    def test_self_review_never_counts_with_independent_review(self) -> None:
        reviews = [
            self._observation(evidence_id="self", evidence_kind="review", independence="self_review_only", review_requirement_ids=["review-independent"], scenario_ids=[]),
            self._observation(evidence_id="independent", evidence_kind="review", independence="independent", review_requirement_ids=["review-independent"], scenario_ids=[]),
        ]
        assessment = assess_quality_evidence(self.package, reviews, omh_home=self.omh_home)
        self.assertEqual(assessment["dimensions"]["review_independence"]["status"], "satisfied")
        self.assertEqual(assessment["dimensions"]["review_independence"]["evidence_ids"], ["independent"])


if __name__ == "__main__":
    unittest.main()
