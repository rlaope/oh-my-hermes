"""Unmatched live memory is withheld: no summary, no name, no line; tool recall still reads it."""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import unittest
from xml.etree import ElementTree

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import memory_records, memory_provider, memory_prefetch_receipt as receipts  # noqa: E402
from omh.plugin_bundle.omh.memory_principals import derive_channel_ref  # noqa: E402
from omh.workflows.memory_recall_incident_model import recall_delivery_stage, diagnosis  # noqa: E402
from memory_recall_fixture import NOW, PROJECT, reviewed, selection  # noqa: E402
from test_memory_prefetch_canonical import SESSION, approve, provider, serve, rendered_ids  # noqa: E402


class MemoryIndexFallbackTests(unittest.TestCase):
    def test_unmatched_messages_render_nothing_and_name_nothing(self) -> None:
        pairs = [
            reviewed("mem_one", summary="Release policy sentinel", subject="release-policy"),
            reviewed("mem_two", summary="Database backup sentinel", subject="database-backup"),
        ]
        for query in ("Astronomy telescope", "천문학 망원경", "天文学 望遠鏡"):
            with self.subTest(query=query):
                selected = selection(pairs, query=query)
                self.assertIn("query_fallback", selected.pack)
                section = memory_records.render_selected_memory_records(
                    selected, [record for record, _ in pairs], index_fallback=True,
                )
                self.assertEqual(section.text, "")
                self.assertEqual(section.rendered, ())
                self.assertEqual(section.indexed, tuple(item["record_id"] for item in selected.pack["included_records"]))
                self.assertEqual(section.omissions["render_budget_exhausted"], 0)

    def test_provider_keeps_current_origin_full_text_and_counts_only_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            unrelated = approve(root, "Unrelated stored policy sentinel")
            current = approve(root, "Current conversation decision sentinel", source_ref=f"hermes-session:{SESSION}")
            live = provider(root)
            pack = serve(live, "Astronomy telescope")
            # The one guard against the removed line coming back.
            self.assertNotIn("<record_index", pack)
            self.assertNotIn(unrelated["summary"], pack)
            self.assertNotIn(unrelated["record_id"], pack)
            self.assertIn(current["summary"], pack)
            self.assertEqual(rendered_ids(pack), [current["record_id"]])
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            self.assertEqual(receipt["rendering"]["indexed_records"], [unrelated["record_id"]])
            self.assertEqual(receipt["rendering"]["selected_not_rendered"], [])
            self.assertEqual(receipts.validate_prefetch_receipt(receipt), [])
            self.assertEqual(live.recall_status().count, 1)
            self.assertEqual(set(memory_records.read_served_counts(root / ".omh")), {current["record_id"]})

    def test_compaction_ancestor_origin_stays_full_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ancestor = approve(root, "Ancestor conversation sentinel", source_ref="hermes-session:before-compact")
            foreign = approve(root, "Foreign conversation sentinel", source_ref="hermes-session:forked-child")
            live = provider(root)
            with mock.patch.object(memory_provider.live_session, "compaction_ancestors", return_value={"status": "unverified", "ancestors": ["before-compact"]}) as lookup:
                pack = serve(live, "Astronomy telescope")
            # Compare resolved paths: Windows runners hand out 8.3 short temp names that resolve_homes expands.
            lookup.assert_called_once()
            (home_arg, session_arg), _ = lookup.call_args
            self.assertEqual(Path(home_arg).resolve(), (root / ".hermes").resolve())
            self.assertEqual(session_arg, SESSION)
            self.assertIn(ancestor["summary"], pack)
            self.assertNotIn(foreign["summary"], pack)
            self.assertEqual(rendered_ids(pack), [ancestor["record_id"]])
            self.assertEqual(live.latest_prefetch_receipt()["rendering"]["indexed_records"], [foreign["record_id"]])

    def test_lineage_failure_keeps_only_current_origin_and_reports_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = approve(root, "Current decision sentinel", source_ref=f"hermes-session:{SESSION}")
            ancestor = approve(root, "Ancestor decision sentinel", source_ref="hermes-session:older")
            live = provider(root)
            with mock.patch.object(memory_provider.live_session, "compaction_ancestors", side_effect=RuntimeError("private failure")):
                pack = serve(live, "Astronomy telescope")
            self.assertEqual(rendered_ids(pack), [current["record_id"]])
            self.assertNotIn(ancestor["summary"], pack)
            receipt = live.latest_prefetch_receipt()
            self.assertEqual(receipt["last_write_failure"], {"op": "compaction_ancestors", "error": "RuntimeError"})
            self.assertNotIn("private failure", str(receipt))
            live._hermes_home = None
            with mock.patch.object(memory_provider.live_session, "compaction_ancestors", side_effect=AssertionError("must not look up")):
                self.assertEqual(live._conversation_session_ids(), {SESSION})

    def test_console_and_channel_prefetch_withhold_unmatched_records(self) -> None:
        for surface in ("console", "channel"):
            with self.subTest(surface=surface), TemporaryDirectory() as tmp:
                root = Path(tmp)
                if surface == "console":
                    record = approve(root, "Console stored sentinel")
                    live = provider(root)
                else:
                    live = provider(root, platform="discord", chat_type="group", chat_id="1111111111111111111", user_id="987654321098765432", chat_name="team")
                    channel_ref = derive_channel_ref(root / ".omh", profile_ref="default", surface_ref="discord", channel_identity="1111111111111111111")
                    record = approve(root, "Channel stored sentinel", scope_kind="channel", scope_ref=channel_ref)
                pack = serve(live, "Astronomy telescope")
                self.assertEqual(pack, "")
                self.assertIsNone(live.recall_status())
                receipt = live.latest_prefetch_receipt()
                self.assertEqual(receipt["rendering"]["indexed_records"], [record["record_id"]])
                self.assertEqual(receipts.validate_prefetch_receipt(receipt), [])
                self.assertEqual(memory_records.read_served_counts(root / ".omh"), {})

    def test_matching_query_and_disabled_index_are_byte_identical(self) -> None:
        pairs = [reviewed("mem_one", summary="Release policy sentinel", subject="release-policy")]
        records = [record for record, _ in pairs]
        for query in ("Release", "Astronomy telescope", ""):
            selected = selection(pairs, query=query)
            legacy = memory_records.render_selected_memory_records(selected, records)
            explicit_off = memory_records.render_selected_memory_records(selected, records, index_fallback=False)
            self.assertEqual(legacy, explicit_off)
            if query != "Astronomy telescope":
                self.assertEqual(legacy, memory_records.render_selected_memory_records(selected, records, index_fallback=True))
        self.assertEqual(legacy.text, '<memory_records>\n  <record id="mem_one" type="fact" approved="2026-09-01">Release policy sentinel</record>\n</memory_records>')

    def test_withheld_records_cost_no_budget_and_leave_no_text_at_any_bound(self) -> None:
        pairs = [reviewed(f"mem_{index:02d}", summary=f"Stored sentinel {index}", subject=f"topic-{index}") for index in range(10)]
        selected = selection(pairs, query="Astronomy telescope", limit=12)
        records = [record for record, _ in pairs]
        for budget in (memory_records.DEFAULT_RECORD_RENDER_BUDGET_CHARS, 1, 0):
            with self.subTest(budget=budget):
                section = memory_records.render_selected_memory_records(selected, records, index_fallback=True, budget_chars=budget)
                self.assertEqual((section.text, section.rendered), ("", ()))
                self.assertEqual(len(section.indexed), 10)
                self.assertEqual(section.omissions["render_budget_exhausted"], 0)

    def test_origin_ids_use_exact_source_ref_and_preserve_full_text_selection_order(self) -> None:
        pairs = [reviewed(f"mem_{index}", summary=f"Stored sentinel {index}", source_ref=source) for index, source in enumerate(("hermes-session:current", "hermes-session:foreign", "hermes-session:ancestor", "hermes-session:current-extra"))]
        records = [record for record, _ in pairs]
        origin = memory_records.origin_record_ids(records, {"current", "ancestor", ""})
        self.assertEqual(origin, frozenset({"mem_0", "mem_2"}))
        selected = selection(pairs, query="Astronomy telescope")
        section = memory_records.render_selected_memory_records(selected, records, index_fallback=True, full_text_ids=origin)
        self.assertEqual([item["record_id"] for item in section.rendered], [item["record_id"] for item in selected.pack["included_records"] if item["record_id"] in origin])
        self.assertEqual([node.tag for node in ElementTree.fromstring(section.text)], ["record", "record"])
        self.assertNotIn("mem_1", section.text)
        self.assertNotIn("mem_3", section.text)

    def test_indexed_incident_stage_is_no_overlap_not_render_budget_failure(self) -> None:
        reason, last = recall_delivery_stage(rendered=False, indexed=True, delivery_observed=None, model_use_observed=None)
        self.assertEqual((reason, last), ("no_query_overlap", "selected"))
        self.assertEqual(diagnosis(reason, "live_prefetch_receipt")["stage"], "relevance_attention_or_budget_exclusion")
        self.assertEqual(recall_delivery_stage(rendered=False, delivery_observed=None, model_use_observed=None), ("selected_not_rendered", "selected"))

    def test_a_full_text_budget_cut_keeps_the_receipt_prefix(self) -> None:
        pairs = [reviewed(f"mem_{index}", summary=f"Stored sentinel {index}") for index in range(2)]
        selected = selection(pairs, query="Astronomy telescope")
        selected_ids = [item["record_id"] for item in selected.pack["included_records"]]
        section = memory_records.render_selected_memory_records(
            selected, [record for record, _ in pairs], index_fallback=True,
            full_text_ids={selected_ids[1]}, budget_chars=10,
        )
        self.assertEqual((section.text, section.rendered, section.indexed), ("", (), (selected_ids[0],)))
        receipt = receipts.build_prefetch_receipt(memory_records.PreparedPrefetch(selected, section, NOW), session_id=SESSION, home_digests=())
        self.assertEqual(receipts.validate_prefetch_receipt(receipt), [])
        self.assertEqual([item["record_id"] for item in receipt["rendering"]["selected_not_rendered"]], [selected_ids[1]])
        self.assertEqual(section.omissions["render_budget_exhausted"], 1)

    def test_a_plural_of_the_records_topic_word_is_shown_as_the_singular_is(self) -> None:
        pairs = [
            reviewed("mem_ticket", subject="ticket-tool-db-choice", summary=(
                "Team of 3 is building an internal ticket tool with about 50 writes per day. "
                "They are deciding between SQLite and Postgres.")),
            reviewed("mem_deploy", subject="deploy-schedule", summary="Deploys run nightly from the release branch"),
        ]
        records = tuple(record for record, _ in pairs)
        snapshot = memory_records.RecordStoreSnapshot(records, {review["review_id"]: review for _, review in pairs}, {}, {}, frozenset(), ())

        def prepared(query: str) -> memory_records.PreparedPrefetch:
            return memory_records.prepare_prefetch_records(snapshot, query, allowed_scopes=[PROJECT], now=NOW, index_fallback=True)

        singular = prepared("what about the ticket database?")
        self.assertNotIn("query_fallback", singular.selection.pack)
        plural = prepared("what about the tickets database?")
        # Only a suffix rule met the store, so the selection falls back; the
        # record whose subject the plural names is shown, the other withheld.
        self.assertIn("query_fallback", plural.selection.pack)
        for case in (singular, plural):
            self.assertEqual([item["record_id"] for item in case.section.rendered], ["mem_ticket"])
            self.assertIn("internal ticket tool", case.section.text)
            self.assertNotIn("mem_deploy", case.section.text)
        self.assertEqual(plural.section.indexed, ("mem_deploy",))
        self.assertEqual(receipts.validate_prefetch_receipt(receipts.build_prefetch_receipt(plural, session_id=SESSION, home_digests=())), [])
        # A stemmed hit only in the summary ("Write" on "50 writes per day")
        # is not the record's topic: it stays withheld.
        commit = prepared("Write a commit message for the staged change")
        self.assertIn("query_fallback", commit.selection.pack)
        self.assertGreater(next(item["score"] for item in commit.selection.pack["included_records"] if item["record_id"] == "mem_ticket"), 1)
        self.assertEqual((commit.section.text, commit.section.rendered), ("", ()))
        self.assertEqual(sorted(commit.section.indexed), ["mem_deploy", "mem_ticket"])

    def test_preparation_and_receipts_partition_selected_ids_and_validate_filtered_prefix(self) -> None:
        pairs = [reviewed(f"mem_{index}", summary=f"Stored sentinel {index}") for index in range(4)]
        records = tuple(record for record, _ in pairs)
        snapshot = memory_records.RecordStoreSnapshot(records, {review["review_id"]: review for _, review in pairs}, {}, {}, frozenset(), ())
        selected = selection(pairs, query="Astronomy telescope")
        selected_ids = [item["record_id"] for item in selected.pack["included_records"]]
        full_ids = set(selected_ids[1:])
        prepared = memory_records.prepare_prefetch_records(snapshot, "Astronomy telescope", allowed_scopes=[PROJECT], now=NOW, index_fallback=True, full_text_ids=full_ids)
        self.assertEqual(prepared.section.indexed, tuple(selected_ids[:1]))
        receipt = receipts.build_prefetch_receipt(prepared, session_id=SESSION, home_digests=())
        self.assertEqual(receipt["rendering"]["indexed_records"], selected_ids[:1])
        self.assertEqual(receipt["rendering"]["selected_not_rendered"], [])
        self.assertEqual(receipts.validate_prefetch_receipt(receipt), [])
        shortened = replace(prepared, section=replace(prepared.section, rendered=prepared.section.rendered[:1]))
        partial = receipts.build_prefetch_receipt(shortened, session_id=SESSION, home_digests=())
        self.assertEqual([item["record_id"] for item in partial["rendering"]["selected_not_rendered"]], selected_ids[2:])
        stray = replace(prepared, section=replace(prepared.section, rendered=prepared.section.rendered[1:]))
        with self.assertRaisesRegex(ValueError, "prefix"):
            receipts.build_prefetch_receipt(stray, session_id=SESSION, home_digests=())
        bad = copy.deepcopy(receipt)
        bad["rendering"]["rendered_records"] = bad["rendering"]["rendered_records"][1:]
        bad["rendering"]["rendered_count"] -= 1
        bad = receipts.mark_prefetch_receipt_returned(bad)
        self.assertIn("rendering.selected_prefix", receipts.validate_prefetch_receipt(bad))
        for invalid in (["unknown"], [selected_ids[0], selected_ids[0]], [selected_ids[2], selected_ids[0]], None):
            bad = copy.deepcopy(receipt)
            bad["rendering"]["indexed_records"] = invalid
            bad = receipts.mark_prefetch_receipt_returned(bad)
            self.assertIn("rendering.indexed_records", receipts.validate_prefetch_receipt(bad))
        legacy = receipts.build_prefetch_receipt(replace(prepared, section=memory_records.render_selected_memory_records(prepared.selection, records)), session_id=SESSION, home_digests=())
        self.assertEqual(legacy["rendering"].pop("indexed_records"), [])
        legacy = receipts.mark_prefetch_receipt_returned(legacy)
        self.assertEqual(receipts.validate_prefetch_receipt(legacy), [])


if __name__ == "__main__":
    unittest.main()
