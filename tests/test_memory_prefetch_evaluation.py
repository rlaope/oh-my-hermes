"""The retained retrieval suite compares canonical selection with the live prefetch.

`omh memory recall-suite` used to ask one question: does the canonical
recall-pack builder return what the retained corpus expects? The live Hermes
prefetch now selects through the same canonical contract, so the suite asks a
second one per case: fed the same frozen corpus, the same explicit delivery
lens, the same clock and the same budgets, does the live provider adapter
select the same record ids in the same order, name the same exclusion reasons,
report the same truncation, and bind to the same configuration identity?

Every regression test here seeds a deliberate divergence in the live path --
through the real provider module's own seams or through the evaluator's
injectable live arms -- and proves the report names it under the right field
and fails. The suite is a gate on adapter drift, not a snapshot of it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import hashlib
import json
from typing import Any
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import memory_records
from omh.workflows.memory_evaluation import (
    PARITY_ARMS,
    PARITY_FIELDS,
    PARITY_SESSION_ID,
    RETRIEVAL_EVALUATOR_VERSION,
    compare_retrieval_reports,
    run_live_prefetch_arms,
    run_memory_retrieval_evaluation,
)
from omh.workflows.memory_retrieval_fixtures import FIXTURE_CLOCK_ISO, RETRIEVAL_CASES

# A case whose canonical delivery pack carries two records, so a reversal
# changes the order without changing the set.
_TWO_RECORD_CASE = "exact_and_partial_relevance"
# A case the record budget cuts, so the truncation flag is exercised.
_TRUNCATED_CASE = "record_limit_truncation_reports_over_budget"
_RETAINED_COUNTERS = (
    "unexpected_inclusions",
    "missing_inclusions",
    "exclusion_reason_drift",
    "sibling_hint_drift",
    "ineligible_evidence_drift",
    "budget_violations",
)


def _case_result(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(case for case in report["cases"] if case["case_id"] == case_id)


def _arm(case: dict[str, Any], name: str) -> dict[str, Any]:
    return next(arm for arm in case["parity"]["arms"] if arm["arm"] == name)


def _fields(arm: dict[str, Any]) -> list[str]:
    return [row["field"] for row in arm["divergences"]]


def _reversed_prepare(snapshot: memory_records.RecordStoreSnapshot, query: str = "", **kwargs: Any) -> memory_records.PreparedPrefetch:
    """The real adapter, then the selection reversed and re-rendered.

    The rendering is rebuilt from the reversed selection so the receipt stays
    internally consistent: the seeded fault is exactly "the live turn ranks
    the records differently", nothing else.
    """
    prepared = memory_records.prepare_prefetch_records(snapshot, query, **kwargs)
    pack = prepared.selection.pack
    reordered = replace(prepared.selection, pack={**pack, "included_records": list(reversed(pack["included_records"]))})
    section = memory_records.render_selected_memory_records(reordered, snapshot.records, budget_chars=prepared.section.budget_chars)
    return memory_records.PreparedPrefetch(reordered, section, prepared.clock)


def _resign(receipt: dict[str, Any]) -> None:
    """Recompute `receipt_id` over the body the way `build_prefetch_receipt` does.

    A seeded divergence must read as exactly the field it alters; an
    unsigned edit would also fail the receipt's integrity check and blur
    which field the evaluator caught.
    """
    body = {key: value for key, value in receipt.items() if key not in {"receipt_id", "state", "served_at"}}
    receipt["receipt_id"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _mutated_arms(arm: str, mutate: Callable[[dict[str, Any]], None], *, resign: bool = True) -> Callable[..., dict[str, dict[str, Any]]]:
    """The real live arms, with one receipt altered after the fact."""

    def _arms(paths: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
        receipts = run_live_prefetch_arms(paths, **kwargs)
        mutate(receipts[arm])
        if resign:
            _resign(receipts[arm])
        return receipts

    return _arms


class LiveProviderParityTests(unittest.TestCase):
    def test_a_reordering_live_provider_fails_its_retained_case(self) -> None:
        """A provider that serves the canonical records in another order must
        fail the case even though the canonical builder itself is untouched."""
        with patch("omh.plugin_bundle.omh.memory_provider.prepare_prefetch_records", side_effect=_reversed_prepare):
            report = run_memory_retrieval_evaluation()

        case = _case_result(report, _TWO_RECORD_CASE)
        self.assertFalse(case["passed"], json.dumps(case, sort_keys=True)[:2000])
        self.assertFalse(report["passed"])
        session = _arm(case, "provider_session")
        self.assertIn("included_order", _fields(session))
        self.assertEqual(session["live"]["included_order"], list(reversed(session["canonical"]["included_order"])))
        # The adapter arm calls the unpatched function and still agrees; the
        # retained counters stay clean, so the failure reads as adapter drift.
        self.assertTrue(_arm(case, "prefetch_adapter")["passed"])
        self.assertTrue(case["exact_order"])
        for counter in _RETAINED_COUNTERS:
            self.assertEqual(case[counter], [], counter)

    def test_a_provider_that_derives_another_lens_fails_only_its_own_arm(self) -> None:
        """The canonical arm states the handoff's allowlist itself, so a provider
        that resolves a different lens is caught rather than followed."""
        with patch("omh.plugin_bundle.omh.memory_provider.prefetch_scope_allowlist", return_value=[]):
            report = run_memory_retrieval_evaluation()

        case = _case_result(report, _TWO_RECORD_CASE)
        session = _arm(case, "provider_session")
        self.assertFalse(session["passed"])
        self.assertTrue(_arm(case, "prefetch_adapter")["passed"])
        self.assertEqual(
            {"scope_allowlist", "scope_status", "included_order", "exclusion_reason_counts", "recall_enabled", "configuration_id"} - set(_fields(session)),
            set(),
        )
        self.assertEqual(session["live"]["scope_status"], "unresolved")
        self.assertEqual(session["live"]["exclusion_reason_counts"], {"scope_unresolved": 1})
        self.assertEqual(session["canonical"]["scope_status"], "resolved")

    def test_each_divergent_receipt_field_is_named_and_fails_the_case(self) -> None:
        def _reverse(receipt: dict[str, Any]) -> None:
            receipt["selection"]["selected_record_ids"].reverse()

        def _drop_leader(receipt: dict[str, Any]) -> None:
            ids = receipt["selection"]["selected_record_ids"]
            if ids:
                del ids[0]

        def _miscount(receipt: dict[str, Any]) -> None:
            receipt["selection"]["exclusion_reason_counts"]["no_query_overlap"] = 99

        def _hide_exclusions(receipt: dict[str, Any]) -> None:
            receipt["selection"]["exclusion_reason_counts"] = {}

        def _flip_truncated(receipt: dict[str, Any]) -> None:
            receipt["selection"]["truncated"] = not receipt["selection"]["truncated"]

        def _rebind(receipt: dict[str, Any]) -> None:
            receipt["configuration_id"] = "0" * 64

        def _reclock(receipt: dict[str, Any]) -> None:
            receipt["selection"]["clock"] = "2030-01-01T00:00:00Z"

        def _relens(receipt: dict[str, Any]) -> None:
            receipt["lens"]["perspective"]["observed"] = "codex"

        seeded = (
            ("included_order", _TWO_RECORD_CASE, _reverse),
            ("included_order", _TWO_RECORD_CASE, _drop_leader),
            ("exclusion_reason_counts", _TWO_RECORD_CASE, _miscount),
            ("exclusion_reason_counts", _TWO_RECORD_CASE, _hide_exclusions),
            ("truncated", _TRUNCATED_CASE, _flip_truncated),
            ("configuration_id", _TWO_RECORD_CASE, _rebind),
            ("clock", _TWO_RECORD_CASE, _reclock),
            ("perspective", _TWO_RECORD_CASE, _relens),
        )
        for field, case_id, mutate in seeded:
            for arm_name in PARITY_ARMS:
                with self.subTest(field=field, arm=arm_name, mutation=mutate.__name__):
                    report = run_memory_retrieval_evaluation(live_arms=_mutated_arms(arm_name, mutate))
                    case = _case_result(report, case_id)
                    arm = _arm(case, arm_name)

                    self.assertFalse(report["passed"])
                    self.assertFalse(case["passed"])
                    self.assertFalse(arm["passed"])
                    self.assertIn(field, _fields(arm))
                    summary = report["summary"]
                    assert isinstance(summary, dict)
                    self.assertGreaterEqual(summary["parity_divergence_count"], 1)
                    self.assertGreaterEqual(summary["parity_failed_cases"], 1)
                    self.assertTrue(case["exact_order"])
                    for counter in _RETAINED_COUNTERS:
                        self.assertEqual(case[counter], [], counter)

    def test_a_truncating_adapter_cannot_hide_the_cut_behind_a_matching_prefix(self) -> None:
        """Same leading ids, one arm reports no cut: truncation and the cut
        record's reason both diverge, and the untouched arm still passes."""

        def _serve_everything(receipt: dict[str, Any]) -> None:
            receipt["selection"]["truncated"] = False
            receipt["selection"]["exclusion_reason_counts"] = {}

        report = run_memory_retrieval_evaluation(live_arms=_mutated_arms("prefetch_adapter", _serve_everything))
        case = _case_result(report, _TRUNCATED_CASE)
        adapter = _arm(case, "prefetch_adapter")

        self.assertEqual(sorted(_fields(adapter)), ["exclusion_reason_counts", "truncated"])
        self.assertTrue(adapter["canonical"]["truncated"])
        self.assertEqual(adapter["canonical"]["exclusion_reason_counts"], {"over_budget": 2})
        self.assertTrue(_arm(case, "provider_session")["passed"])

    def test_a_missing_or_malformed_receipt_is_a_divergence_not_a_skip(self) -> None:
        def _no_receipt(paths: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
            return {**run_live_prefetch_arms(paths, **kwargs), "provider_session": {}}

        def _foreign_receipt(paths: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
            receipts = run_live_prefetch_arms(paths, **kwargs)
            receipts["prefetch_adapter"]["schema_version"] = "omh_memory_prefetch_receipt/v0"
            receipts["prefetch_adapter"]["delivery_observed"] = True
            return receipts

        def _unsigned_reclock(receipt: dict[str, Any]) -> None:
            receipt["selection"]["clock"] = "2030-01-01T00:00:00Z"

        seeded = (
            ("missing", "provider_session", _no_receipt, None),
            ("foreign", "prefetch_adapter", _foreign_receipt, None),
            ("unsigned_edit", "prefetch_adapter", _mutated_arms("prefetch_adapter", _unsigned_reclock, resign=False), ["receipt_id"]),
        )
        for label, arm_name, arms, receipt_errors in seeded:
            with self.subTest(arm=arm_name, receipt=label):
                report = run_memory_retrieval_evaluation(live_arms=arms)
                case = _case_result(report, _TWO_RECORD_CASE)
                arm = _arm(case, arm_name)

                self.assertFalse(report["passed"])
                self.assertIn("receipt", _fields(arm))
                errors = next(row for row in arm["divergences"] if row["field"] == "receipt")["live"]
                self.assertTrue(errors)
                if receipt_errors is not None:
                    # A receipt edited without re-signing is caught by its own
                    # integrity check as well as by the field it changed.
                    self.assertEqual(errors, receipt_errors)
                    self.assertIn("clock", _fields(arm))

        report = run_memory_retrieval_evaluation(live_arms=_no_receipt)
        arm = _arm(_case_result(report, _TWO_RECORD_CASE), "provider_session")
        self.assertEqual(set(PARITY_FIELDS) - set(_fields(arm)), set())

    def test_a_renderer_that_reorders_or_skips_diverges_from_the_selected_prefix(self) -> None:
        def _swap_rendered(receipt: dict[str, Any]) -> None:
            receipt["rendering"]["rendered_records"].reverse()

        report = run_memory_retrieval_evaluation(live_arms=_mutated_arms("provider_session", _swap_rendered))
        arm = _arm(_case_result(report, _TWO_RECORD_CASE), "provider_session")

        self.assertIn("rendered_order", _fields(arm))
        self.assertNotIn("included_order", _fields(arm))

    def test_records_listed_in_the_index_line_are_set_aside_before_the_prefix_check(self) -> None:
        # Mutation: compare rendered ids with every selected id again; this case then diverges.
        def _index_first(receipt: dict[str, Any]) -> None:
            rendered = receipt["rendering"]["rendered_records"]
            if rendered:
                receipt["rendering"]["indexed_records"] = [rendered.pop(0)["record_id"]]

        report = run_memory_retrieval_evaluation(live_arms=_mutated_arms("provider_session", _index_first))
        arm = _arm(_case_result(report, _TWO_RECORD_CASE), "provider_session")
        self.assertNotIn("rendered_order", _fields(arm))

        def _skip_without_index(receipt: dict[str, Any]) -> None:
            rendered = receipt["rendering"]["rendered_records"]
            if rendered:
                rendered.pop(0)

        report = run_memory_retrieval_evaluation(live_arms=_mutated_arms("provider_session", _skip_without_index))
        arm = _arm(_case_result(report, _TWO_RECORD_CASE), "provider_session")
        self.assertIn("rendered_order", _fields(arm))


class LiveParityReportShapeTests(unittest.TestCase):
    def test_every_retained_case_holds_live_parity_on_both_arms(self) -> None:
        """The positive claim: the live adapter and the canonical selector agree
        on every retained case. A failure here names the arm and the field."""
        report = run_memory_retrieval_evaluation()

        cases = report["cases"]
        assert isinstance(cases, list)
        divergent = {
            case["case_id"]: {arm["arm"]: arm["divergences"] for arm in case["parity"]["arms"] if arm["divergences"]}
            for case in cases
            if not case["parity"]["passed"]
        }
        self.assertEqual(divergent, {}, json.dumps(divergent, sort_keys=True, indent=1))
        summary = report["summary"]
        assert isinstance(summary, dict)
        self.assertEqual(summary["parity_failed_cases"], 0)
        self.assertEqual(summary["parity_divergence_count"], 0)

    def test_both_arms_run_every_case_under_the_delivery_lens_clock_and_budget(self) -> None:
        report = run_memory_retrieval_evaluation()

        self.assertEqual(report["case_count"], len(RETRIEVAL_CASES))
        cases = report["cases"]
        assert isinstance(cases, list)
        for case, fixture in zip(cases, RETRIEVAL_CASES):
            with self.subTest(case=case["case_id"]):
                parity = case["parity"]
                self.assertEqual([arm["arm"] for arm in parity["arms"]], list(PARITY_ARMS))
                self.assertEqual(parity["clock"], FIXTURE_CLOCK_ISO)
                lens = parity["lens"]
                self.assertEqual(
                    lens["scope_allowlist"],
                    [
                        {"kind": "user-global", "ref": "default"},
                        {"kind": "project", "ref": next(spec["scope_ref"] for spec in fixture["records"] if spec["scope_kind"] == "project" and not spec["contamination_class"])},
                        {"kind": "thread", "ref": PARITY_SESSION_ID},
                    ],
                )
                self.assertEqual((lens["executor_target"], lens["inspection"], lens["include_stale"], lens["include_archived"]), ("hermes", False, False, False))
                adapter, session = parity["arms"]
                self.assertEqual(adapter["budget"], fixture["budget"])
                self.assertEqual(session["budget"], {"limit": memory_records.DEFAULT_RECORD_LIMIT, "max_chars": None})
                for arm in parity["arms"]:
                    self.assertEqual(set(PARITY_FIELDS) - set(arm["canonical"]), set())
                    self.assertEqual(set(PARITY_FIELDS) - set(arm["live"]), set())
                    self.assertEqual(arm["canonical"]["clock"], FIXTURE_CLOCK_ISO)
                    self.assertEqual(arm["live"]["clock"], FIXTURE_CLOCK_ISO)
                    self.assertEqual(arm["canonical"]["perspective"], {"observer": "", "observed": "hermes"})
                    self.assertEqual(arm["live"]["receipt_errors"], [])
                    self.assertEqual(arm["passed"], arm["divergences"] == [])

    def test_the_parity_block_carries_ids_reasons_and_identities_but_no_content(self) -> None:
        report = run_memory_retrieval_evaluation()

        cases = report["cases"]
        assert isinstance(cases, list)
        serialized = json.dumps([case["parity"] for case in cases], sort_keys=True)
        self.assertNotIn("summary", serialized)
        self.assertNotIn("rendered_text", serialized)
        for fixture in RETRIEVAL_CASES:
            self.assertNotIn(fixture["query"], serialized)
            records = fixture["records"]
            assert isinstance(records, list)
            for record in records:
                self.assertNotIn(record["summary"], serialized)

    def test_the_evaluator_version_moved_so_old_reports_refuse_comparison(self) -> None:
        report = run_memory_retrieval_evaluation(target_revision="rev-a")

        self.assertEqual(report["evaluator_version"], RETRIEVAL_EVALUATOR_VERSION)
        self.assertEqual(RETRIEVAL_EVALUATOR_VERSION, "omh-memory-retrieval-evaluator/v2")
        comparison = compare_retrieval_reports({**report, "evaluator_version": "omh-memory-retrieval-evaluator/v1"}, report)
        self.assertFalse(comparison["comparable"])
        self.assertEqual(comparison["mismatched_identity_fields"], ["evaluator_version"])
        self.assertIn("parity_boundary", report)


if __name__ == "__main__":
    unittest.main()
