"""A query that matches nothing still serves the active tier; duplicates take one slot.

Recall is lexical, so a chat message sharing no token with any record used to
produce an empty pack every such turn while approved active memories sat in
the store. These cases pin when the active-tier fallback fires and, as
importantly, every way it must not -- including a query that met the store
only on words most records hold (`common_terms_only`); and that two records
with one normalized summary never both occupy the pack.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()
from memory_recall_fixture import Json, included_ids, mapping, payload, reviewed, selection, text  # noqa: E402
from omh.plugin_bundle.omh.memory_recall_support import normalized_summary_key  # noqa: E402
from project_identity_fixture import memory_paths  # noqa: E402
from omh.workflows import memory  # noqa: E402
from test_memory_prefetch_canonical import approve, provider, rendered_ids  # noqa: E402

_NO_MATCH = "quantum ledger reconciliation"
_FALLBACK = {"mode": "active_tier", "reason": "no_query_overlap", "readmitted_count": 2}


def _excluded(result: object) -> dict[str, dict[str, Json]]:
    rows = payload(result)["excluded_records"]  # type: ignore[arg-type]
    assert isinstance(rows, list)
    return {text(mapping(row)["record_id"]): mapping(row) for row in rows}


def _tier(tier: str) -> dict[str, Json]:
    return {"attention": {"tier": tier}}


class ActiveTierFallbackTests(unittest.TestCase):
    def test_no_overlap_readmits_every_active_record_and_says_so(self) -> None:
        pairs = [reviewed("mem-a", summary="Deploys wait for nightly"), reviewed("mem-b", summary="Parser owner is platform")]
        result = selection(pairs, _NO_MATCH)
        self.assertEqual(included_ids(result), ["mem-a", "mem-b"])
        self.assertEqual(payload(result)["query_fallback"], _FALLBACK)
        self.assertEqual(result.exclusion_reason_counts, {})
        self.assertEqual(memory.validate_project_memory_recall_pack(payload(result)), [])

    def test_a_record_that_never_set_a_tier_counts_as_active(self) -> None:
        record, review = reviewed("mem-untiered", summary="Deploys wait for nightly")
        self.assertNotIn("attention", record)
        result = selection([(record, review)], _NO_MATCH)
        self.assertEqual(included_ids(result), ["mem-untiered"])

    def test_reference_and_archive_stay_out_while_active_is_readmitted(self) -> None:
        pairs = [
            reviewed("mem-active", summary="Deploys wait for nightly"),
            reviewed("mem-reference", summary="Parser owner is platform", **_tier("reference")),
            reviewed("mem-archive", summary="Flags removed after two releases", **_tier("archive")),
        ]
        result = selection(pairs, _NO_MATCH)
        self.assertEqual(included_ids(result), ["mem-active"])
        self.assertEqual(payload(result)["query_fallback"], {**_FALLBACK, "readmitted_count": 1})
        excluded = _excluded(result)
        self.assertEqual(excluded["mem-reference"]["reason"], "no_query_overlap")
        self.assertEqual(excluded["mem-archive"]["reason"], "archived_tier")
        archived_query = selection(pairs, _NO_MATCH, include_archived=True)
        self.assertEqual(included_ids(archived_query), ["mem-active"], "archive stays explicit, never a fallback")
        self.assertEqual(_excluded(archived_query)["mem-archive"]["reason"], "no_query_overlap")

    def test_a_reference_only_store_stays_empty_and_named(self) -> None:
        pairs = [reviewed("mem-ref-1", summary="Deploys wait for nightly", **_tier("reference")),
                 reviewed("mem-ref-2", summary="Parser owner is platform", **_tier("reference"))]
        result = selection(pairs, _NO_MATCH)
        self.assertEqual(included_ids(result), [])
        self.assertNotIn("query_fallback", payload(result))
        self.assertEqual(result.exclusion_reason_counts, {"no_query_overlap": 2})

    def test_a_partial_match_never_falls_back(self) -> None:
        pairs = [reviewed("mem-match", summary="Deploys wait for nightly"), reviewed("mem-miss", summary="Parser owner is platform")]
        result = selection(pairs, "nightly quantum")
        self.assertEqual(included_ids(result), ["mem-match"])
        self.assertNotIn("query_fallback", payload(result))
        self.assertEqual(_excluded(result)["mem-miss"]["reason"], "no_query_overlap")

    def test_a_pin_is_a_match_and_blocks_the_fallback(self) -> None:
        pairs = [reviewed("mem-pinned", summary="Deploys wait for nightly"), reviewed("mem-other", summary="Parser owner is platform")]
        result = selection(pairs, _NO_MATCH, pins={"mem-pinned"})
        self.assertEqual(included_ids(result), ["mem-pinned"])
        self.assertNotIn("query_fallback", payload(result))
        self.assertEqual(_excluded(result)["mem-other"]["reason"], "no_query_overlap")

    def test_an_unqueried_pack_carries_no_fallback(self) -> None:
        result = selection([reviewed("mem-a", summary="Deploys wait for nightly")], "")
        self.assertEqual(included_ids(result), ["mem-a"])
        self.assertNotIn("query_fallback", payload(result))

    def test_overlap_only_on_store_common_words_does_not_fall_back(self) -> None:
        # "tally" is in four of six records, so it never matches alone; the
        # query met the store on it and nothing else, and that is not "matched
        # nothing": the pack stays empty and says why for each record.
        pairs = [
            reviewed("mem-t1", summary="Tally list view pages by fifty"),
            reviewed("mem-t2", summary="Tally keeps its data in sqlite"),
            reviewed("mem-t3", summary="Tally ships on fridays"),
            reviewed("mem-t4", summary="Tally exports go to the finance bucket"),
            reviewed("mem-o1", summary="Standups start at nine thirty"),
            reviewed("mem-o2", summary="Lunch is at noon"),
        ]
        result = selection(pairs, "tally quantum")
        self.assertEqual(included_ids(result), [])
        self.assertNotIn("query_fallback", payload(result))
        self.assertEqual(result.exclusion_reason_counts, {"common_terms_only": 4, "no_query_overlap": 2})
        self.assertEqual(_excluded(result)["mem-t1"]["reason"], "common_terms_only")
        self.assertEqual(memory.validate_project_memory_recall_pack(payload(result)), [])
        # The same store still falls back for a query that overlaps nothing.
        unmatched = selection(pairs, _NO_MATCH)
        self.assertEqual(len(included_ids(unmatched)), 6)
        self.assertEqual(payload(unmatched)["query_fallback"], {**_FALLBACK, "readmitted_count": 6})

    def test_a_replaced_subject_value_on_a_common_word_never_blocks_the_fallback(self) -> None:
        # The live records hold "team" only through a "teams" tag: they match
        # on it, but only by stemming, so nothing servable overlaps and the
        # query falls back. The one record that met the query on the common
        # word alone is a replaced subject value, and that never counts.
        pairs = [
            reviewed("mem-l1", summary="Squash merges for every pull request", tags=["teams"]),
            reviewed("mem-l2", summary="Lunch is on fridays", tags=["teams"]),
            reviewed("mem-l3", summary="Docs live in the wiki", tags=["teams"]),
            reviewed("mem-l4", summary="Billing service owners rotate", tags=["teams"]),
            reviewed("mem-old", summary="The team rotates on-call weekly", subject="on-call", approved_at="2026-08-01T00:00:00Z"),
            reviewed("mem-new", summary="On-call moved to pagerduty", subject="on-call", approved_at="2026-09-01T00:00:00Z"),
            reviewed("mem-o1", summary="Standups start at nine thirty"),
        ]
        result = selection(pairs, "team quantum")
        self.assertEqual(sorted(included_ids(result)), ["mem-l1", "mem-l2", "mem-l3", "mem-l4", "mem-new", "mem-o1"])
        self.assertEqual(payload(result)["query_fallback"], {**_FALLBACK, "readmitted_count": 6})
        self.assertEqual(_excluded(result)["mem-old"]["reason"], "superseded_by_subject")

    def test_the_fallback_still_honours_the_budget(self) -> None:
        pairs = [reviewed(f"mem-{index}", summary=f"Distinct fact number {index}") for index in range(3)]
        result = selection(pairs, _NO_MATCH, limit=2)
        self.assertEqual(len(included_ids(result)), 2)
        self.assertEqual(payload(result)["query_fallback"], {**_FALLBACK, "readmitted_count": 3})
        self.assertEqual(result.exclusion_reason_counts, {"over_budget": 1})
        self.assertTrue(payload(result)["truncated"])


class DuplicateSummaryCollapseTests(unittest.TestCase):
    def test_the_newest_approval_keeps_the_slot_and_the_other_names_it(self) -> None:
        pairs = [
            reviewed("mem-old", summary="Release checklist requires tests", approved_at="2026-08-01T00:00:00Z"),
            reviewed("mem-new", summary="  release CHECKLIST requires   tests ", approved_at="2026-09-01T00:00:00Z"),
        ]
        result = selection(pairs)
        self.assertEqual(included_ids(result), ["mem-new"])
        cut = _excluded(result)["mem-old"]
        self.assertEqual((cut["reason"], cut["duplicate_of"]), ("duplicate_record", "mem-new"))
        self.assertEqual(result.exclusion_reason_counts, {"duplicate_record": 1})
        self.assertEqual(memory.validate_project_memory_recall_pack(payload(result)), [])

    def test_an_approval_tie_keeps_the_smaller_record_id(self) -> None:
        same = "Release checklist requires tests"
        result = selection([reviewed("mem-b", summary=same), reviewed("mem-a", summary=same)])
        self.assertEqual(included_ids(result), ["mem-a"])
        self.assertEqual(_excluded(result)["mem-b"]["duplicate_of"], "mem-a")

    def test_a_pinned_duplicate_is_never_the_one_cut(self) -> None:
        same = "Release checklist requires tests"
        pairs = [
            reviewed("mem-old", summary=same, approved_at="2026-08-01T00:00:00Z"),
            reviewed("mem-new", summary=same, approved_at="2026-09-01T00:00:00Z"),
        ]
        result = selection(pairs, pins={"mem-old"})
        self.assertEqual(included_ids(result), ["mem-old"])
        self.assertEqual(_excluded(result)["mem-new"]["duplicate_of"], "mem-old")

    def test_summaries_that_only_look_alike_both_stay(self) -> None:
        pairs = [reviewed("mem-a", summary="Release checklist requires tests"), reviewed("mem-b", summary="Release checklist requires tests!")]
        result = selection(pairs)
        self.assertEqual(included_ids(result), ["mem-a", "mem-b"])
        self.assertEqual(result.exclusion_reason_counts, {})

    def test_the_bundle_normalizer_agrees_with_capture(self) -> None:
        for value in ("Release  Checklist\trequires tests", "  Ｃａｆｅ́ ", "", "배포는  금요일"):
            with self.subTest(value=value):
                self.assertEqual(normalized_summary_key(value), memory._normalized_summary_key(value))


class HermesOrderFallbackTests(unittest.TestCase):
    def test_a_greeting_serves_nothing_live_while_the_handoff_still_falls_back(self) -> None:
        # The live turn passes query_fallback=False (2026-11-03 audit: 89% of
        # live-served records shared no word with the turn); the handoff
        # facade keeps the selector's default.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            record = approve(root, "OMH uses deterministic token recall for memory packs")
            live = provider(root)
            live.on_turn_start(1, "hello there")
            pack = live.prefetch("hello there")
            self.assertEqual(rendered_ids(pack), [])
            self.assertIsNone(live.recall_status())
            receipt = live.latest_prefetch_receipt()
            assert isinstance(receipt, dict)
            self.assertIsNone(receipt["selection"]["query_fallback"])
            handoff = memory.build_project_memory_recall_pack(
                memory_paths(root / ".omh", root / ".hermes"), "hello there",
                scope_kind="project", scope_ref=record["scope"]["ref"], inspection=False,
            )
            self.assertEqual([item["record_id"] for item in handoff["included_records"]], [record["record_id"]])  # type: ignore[union-attr]
            self.assertEqual(handoff["query_fallback"], {**_FALLBACK, "readmitted_count": 1})


if __name__ == "__main__":
    unittest.main()
