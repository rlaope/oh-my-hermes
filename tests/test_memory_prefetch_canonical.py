"""The live Hermes prefetch selects through the canonical recall contract.

Before this, `memory_records.rank_project_memory_records` was a second, reduced
ranking ladder: no scope allowlist, no perspective lens, no lifecycle, pins,
usage, attention or character budget. A record about another project or
another executor reached every Hermes turn, and the recall indicator counted
what the ranker selected rather than what the renderer actually emitted.

Every assertion here drives the real provider surface (`initialize`,
`queue_prefetch`, `prefetch`, `recall_status`, `latest_prefetch_receipt`) or the
adapter functions the provider itself calls. Nothing asserts host delivery or
model use: the receipt proves local preparation and return only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from _local_package import load_local_package
from _credential_fixtures import AWS_ACCESS_KEY_ID
from memory_recall_fixture import reviewed, selection

load_local_package()
from project_identity_fixture import PROJECT_IDENTITY, memory_paths as resolve_paths
from omh.plugin_bundle.omh import memory_prefetch_receipt as receipts
from omh.plugin_bundle.omh import memory_records
from omh.plugin_bundle.omh import memory_recall_selector as selector
from omh.plugin_bundle.omh.memory_blocks import approve_memory_block, build_memory_block, write_memory_block
from omh.plugin_bundle.omh.memory_dreaming import (
    DEFAULT_TURN_INTERVAL,
    consolidation_path,
    empty_dreaming_state,
    record_turn,
    write_dreaming_state,
)
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider, RecallStatus
from omh.workflows import memory

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)
CAPTURED_AT = "2026-09-01T00:00:00Z"
SESSION = "session-a"
GLOBAL = {"kind": "user-global", "ref": "default"}
PROJECT = {"kind": "project", "ref": PROJECT_IDENTITY}
THREAD = {"kind": "thread", "ref": SESSION}


def approve(root: Path, summary: str, *, home: str = ".omh", captured_at: str = CAPTURED_AT, **capture: Any) -> dict[str, Any]:
    paths = resolve_paths(root / home, root / ".hermes")
    with patch.object(memory, "utc_now", return_value=captured_at):
        candidate = memory.capture_project_memory_candidate(paths, summary, **capture)["candidate"]
        assert isinstance(candidate, dict)
        record = memory.approve_project_memory_candidate(paths, candidate["candidate_id"], approved_by="user")["record"]
        assert isinstance(record, dict)
        return record


def provider(root: Path, *, cwd: Path | None = None, session_id: str = SESSION, **kwargs: Any) -> OmhMemoryProvider:
    live = OmhMemoryProvider(root / ".omh")
    live.initialize(session_id, hermes_home=str(root / ".hermes"), agent_context="primary", cwd=str(cwd or root), **{"platform": "cli", **kwargs})
    return live


def serve(live: OmhMemoryProvider, query: str = "", *, now: datetime = NOW) -> str:
    live.queue_prefetch(query, now=now)
    return live.prefetch(query)


def rendered_ids(pack: str) -> list[str]:
    start = pack.find("<memory_records>")
    if start < 0:
        return []
    section = pack[start : pack.index("</memory_records>") + len("</memory_records>")]
    return [element.attrib["id"] for element in ElementTree.fromstring(section).findall("record")]


def included_ids(selection: selector.MemoryRecallSelection) -> list[str]:
    return [str(item["record_id"]) for item in selection.pack["included_records"]]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CanonicalPrefetchTests(unittest.TestCase):
    def test_canonical_renderer_does_not_skip_an_oversized_priority_record(self) -> None:
        # Given a pinned first record whose escaped text exceeds the render budget.
        pairs = [reviewed("mem_long", summary="&" * 500),
                 reviewed("mem_short", summary="Brief preference")]
        selected = selection(pairs, query="", pins={"mem_long"})
        self.assertEqual(included_ids(selected), ["mem_long", "mem_short"])
        # When
        section = memory_records.render_selected_memory_records(
            selected, tuple(record for record, _ in pairs))
        # Then: cutting a prefix cannot promote a later record over the pinned one.
        self.assertEqual(section.rendered, ())
        self.assertEqual(section.omissions["render_budget_exhausted"], 2)

    def test_foreign_scopes_and_perspectives_never_reach_the_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            approve(root, "current project release checklist")
            approve(root, "global reply preference is polite", scope_kind="user-global", scope_ref="default")
            approve(root, "thread note for this session", scope_kind="thread", scope_ref=SESSION)
            approve(root, "hermes actor note about itself", observed="hermes")
            foreign = [
                approve(root, "foreign project note elsewhere", scope_kind="project", scope_ref="elsewhere"),
                approve(root, "foreign thread note for another session", scope_kind="thread", scope_ref="session-b"),
                approve(root, "foreign actor note about codex", observed="codex"),
            ]
            live = provider(root)
            # A live turn serves what its query matches; this one names all four.
            pack = serve(live, "release checklist, reply preference, thread note, actor note")
            for expected in ("current project", "global reply", "thread note for this", "hermes actor note"):
                self.assertIn(expected, pack)
            for record in foreign:
                self.assertNotIn(record["summary"], pack, "a foreign scope or perspective leaked into the live prefetch")
                self.assertNotIn(record["record_id"], pack)
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            self.assertEqual(receipt["selection"]["exclusion_reason_counts"], {"perspective_mismatch": 1, "scope_mismatch": 2})
            self.assertEqual(len(receipt["selection"]["selected_record_ids"]), 4)
            for record in foreign:
                self.assertNotIn(record["record_id"], json.dumps(receipt))

    def test_the_allowlist_is_user_global_plus_current_project_and_thread(self) -> None:
        allowlist = memory_records.prefetch_scope_allowlist(project_identity="repo", session_id="s1")
        self.assertEqual(allowlist, [GLOBAL, {"kind": "project", "ref": "repo"}, {"kind": "thread", "ref": "s1"}])
        self.assertEqual(memory_records.prefetch_scope_allowlist(project_identity="repo"), [GLOBAL, {"kind": "project", "ref": "repo"}])
        # No project resolved (owner decision 2026-10-13): the project label
        # goes, the rest stays, and a shared surface still gets nothing.
        self.assertEqual(memory_records.prefetch_scope_allowlist(project_identity="", session_id="s1"), [GLOBAL, {"kind": "thread", "ref": "s1"}])
        self.assertEqual(memory_records.prefetch_scope_allowlist(project_identity="  ", session_id="s1"), [GLOBAL, {"kind": "thread", "ref": "s1"}])
        self.assertEqual(memory_records.prefetch_scope_allowlist(project_identity="", session_id="s1", include_legacy_personal=False), [])
        self.assertEqual(memory_records.prefetch_required_scope_kinds("repo"), ("project",))
        self.assertEqual(memory_records.prefetch_required_scope_kinds("  "), ())
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True)
            approve(root, "project record labelled for this repository", home="repo/.omh")
            approve(root, "global record from the user store", scope_kind="user-global", scope_ref="default")
            unlabelled = approve(root, "user store record still labelled project default", scope_ref="default")
            live = provider(root, cwd=repo)
            pack = serve(live, "record labelled, global user store")
            self.assertIn("labelled for this repository", pack)
            self.assertIn("global record from the user store", pack)
            self.assertNotIn(unlabelled["summary"], pack)
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            # The selector canonicalizes the allowlist: deduplicated, sorted by (kind, ref).
            self.assertEqual(receipt["lens"]["scope_allowlist"], [PROJECT, THREAD, GLOBAL])
            self.assertEqual(receipt["selection"]["exclusion_reason_counts"], {"scope_mismatch": 1})
            self.assertEqual(len(receipt["store"]["home_digests"]), 2)

    def test_selection_matches_the_canonical_selector_under_one_policy_clock_and_budget(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            strong = approve(root, "release tests run before the staging checklist", tags=["release", "tests"])
            used = approve(root, "release notes are edited after tagging", tags=["release"])
            unused = approve(root, "release branches are cut on friday", tags=["release"])
            old = approve(root, "release rollback uses the previous tag", captured_at="2026-08-01T00:00:00Z")
            reference = approve(root, "release tests archive their logs", tags=["release", "tests"])
            pinned = approve(root, "architecture overview lives in docs")
            approve(root, "menubar helper polls every thirty seconds", tags=["menubar"])
            memory.apply_memory_attention_change(paths, reference["record_id"], tier="reference", now=NOW)
            memory.set_memory_pin(paths, pinned["record_id"], pinned=True)
            for _ in range(10):
                memory.record_recall_usage(paths, [used["record_id"]], now="2026-09-05T00:00:00Z")
            self.assertEqual(memory_records.MEMORY_RECALL_USAGE_SCHEMA_VERSION, memory.MEMORY_RECALL_USAGE_SCHEMA_VERSION)
            self.assertEqual(memory_records.MEMORY_PINS_SCHEMA_VERSION, memory.MEMORY_PINS_SCHEMA_VERSION)

            live = provider(root)
            pack = serve(live, "release tests")
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            snapshot = memory_records.read_record_store_snapshot((root / ".omh",))
            allowlist = memory_records.prefetch_scope_allowlist(project_identity=PROJECT_IDENTITY, session_id=SESSION)
            expected = selector.select_memory_recall(
                list(snapshot.records), "release tests", allowed_scopes=allowlist, required_scope_kinds=("project",),
                inspection=False, review_resolver=snapshot.reviews, operation_states=snapshot.operation_states,
                usage=snapshot.usage, pins=set(snapshot.pins), executor_target="hermes", session_id=SESSION,
                limit=memory_records.DEFAULT_RECORD_LIMIT, now=NOW, query_fallback=False,
            )
            self.assertEqual(included_ids(expected)[:3], [pinned["record_id"], strong["record_id"], used["record_id"]])
            self.assertEqual(receipt["selection"]["selected_record_ids"], included_ids(expected))
            self.assertEqual(rendered_ids(pack), included_ids(expected))
            self.assertEqual(receipt["configuration_id"], expected.configuration_id)
            self.assertEqual(receipt["selection"]["exclusion_reason_counts"], expected.exclusion_reason_counts)
            # "release" is in 5 of the 7 candidates, so it is store-common and
            # matches only where it is a tag: the untagged rollback record met
            # "release tests" on that word alone and is named apart.
            self.assertEqual(receipt["selection"]["exclusion_reason_counts"], {"common_terms_only": 1, "no_query_overlap": 1})
            self.assertEqual(receipt["selection"]["truncated"], expected.pack["truncated"])
            self.assertIn(unused["record_id"], included_ids(expected))
            self.assertNotIn(old["record_id"], included_ids(expected))
            self.assertIn(
                {"record_id": old["record_id"], "reason": "common_terms_only"},
                [{"record_id": row["record_id"], "reason": row["reason"]} for row in expected.pack["excluded_records"]],
            )

            # Budget parity: record and character limits are the selector's cut.
            prepared = memory_records.prepare_prefetch_records(
                snapshot, "release tests", allowed_scopes=allowlist, session_id=SESSION, limit=2, max_chars=60, now=NOW,
            )
            same_budget = selector.select_memory_recall(
                list(snapshot.records), "release tests", allowed_scopes=allowlist, review_resolver=snapshot.reviews,
                operation_states=snapshot.operation_states, usage=snapshot.usage, pins=set(snapshot.pins),
                executor_target="hermes", session_id=SESSION, limit=2, max_chars=60, now=NOW,
            )
            self.assertEqual(included_ids(prepared.selection), included_ids(same_budget))
            self.assertTrue(prepared.selection.pack["truncated"])
            self.assertEqual(prepared.selection.configuration_id, same_budget.configuration_id)
            self.assertNotEqual(prepared.selection.configuration_id, expected.configuration_id)
            self.assertEqual(prepared.selection.exclusion_reason_counts, same_budget.exclusion_reason_counts)
            self.assertGreaterEqual(prepared.selection.exclusion_reason_counts["over_budget"], 1)

            # Clock parity: the same later clock stales the same records on both paths.
            later = NOW + timedelta(days=400)
            prepared_later = memory_records.prepare_prefetch_records(
                snapshot, "release tests", allowed_scopes=allowlist, session_id=SESSION, now=later,
            )
            selector_later = selector.select_memory_recall(
                list(snapshot.records), "release tests", allowed_scopes=allowlist, review_resolver=snapshot.reviews,
                operation_states=snapshot.operation_states, usage=snapshot.usage, pins=set(snapshot.pins),
                executor_target="hermes", session_id=SESSION, limit=memory_records.DEFAULT_RECORD_LIMIT, now=later,
            )
            self.assertEqual(included_ids(prepared_later.selection), [])
            self.assertEqual(prepared_later.selection.exclusion_reason_counts, selector_later.exclusion_reason_counts)
            # Staleness is checked before query overlap, so the non-overlapping record is stale too.
            self.assertEqual(prepared_later.selection.exclusion_reason_counts, {"stale_review_required": 7})
            self.assertEqual(prepared_later.section.text, "")

            # Policy parity: a disabled policy is the same empty pack on both paths.
            disabled: dict[str, object] = {"recall_enabled": False}
            prepared_off = memory_records.prepare_prefetch_records(
                snapshot, "release tests", allowed_scopes=allowlist, session_id=SESSION, now=NOW, policy=disabled,
            )
            selector_off = selector.select_memory_recall(
                list(snapshot.records), "release tests", allowed_scopes=allowlist, review_resolver=snapshot.reviews,
                executor_target="hermes", session_id=SESSION, now=NOW, policy=disabled,
            )
            self.assertFalse(prepared_off.selection.pack["enabled"])
            self.assertEqual(prepared_off.selection.exclusion_reason_counts, selector_off.exclusion_reason_counts)
            self.assertEqual(prepared_off.selection.exclusion_reason_counts, {"project_memory_disabled": 1})
            self.assertEqual(prepared_off.selection.configuration_id, selector_off.configuration_id)
            self.assertEqual(prepared_off.section.text, "")

    def test_rendering_reports_actual_rendered_records_not_the_selected_count(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(8):
                approve(root, f"release detail {index} " + ("checklist step repeated " * 19).strip())
            live = provider(root)
            pack = serve(live, "release detail checklist step")
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            selection, rendering = receipt["selection"], receipt["rendering"]
            self.assertEqual(selection["selected_count"], memory_records.DEFAULT_RECORD_LIMIT)
            self.assertEqual(len(selection["selected_record_ids"]), memory_records.DEFAULT_RECORD_LIMIT)
            self.assertLess(rendering["rendered_count"], selection["selected_count"])
            self.assertEqual([item["record_id"] for item in rendering["rendered_records"]], rendered_ids(pack))
            self.assertEqual(rendering["rendered_count"], len(rendered_ids(pack)))
            self.assertEqual(rendering["rendered_block_count"], 0)
            self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=rendering["rendered_count"]))
            not_rendered = selection["selected_record_ids"][rendering["rendered_count"] :]
            self.assertEqual(
                rendering["selected_not_rendered"],
                [{"record_id": record_id, "reason": "render_budget_exhausted"} for record_id in not_rendered],
            )
            self.assertEqual(
                rendering["omission_counts"],
                {"render_budget_exhausted": len(not_rendered), "over_budget": 2},
            )
            section = pack[pack.index("<memory_records>") :]
            omitted = {e.attrib["reason"]: int(e.attrib["count"]) for e in ElementTree.fromstring(section).findall("omitted")}
            self.assertEqual(omitted, rendering["omission_counts"])
            self.assertLessEqual(len(section), memory_records.DEFAULT_RECORD_RENDER_BUDGET_CHARS)

    def test_status_and_receipt_follow_the_current_rendering_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = approve(root, "first fact about the build")
            second = approve(root, "second fact about the tests")
            live = provider(root)
            query = "fact build tests"
            serve(live, query)
            self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=2))
            (root / ".omh" / "memory" / "records" / f"{first['record_id']}.json").unlink()
            # A compaction: the conversation no longer holds what was served, so
            # the next serve may carry the same records again.
            live.on_session_switch(SESSION, reset=False)
            live.queue_prefetch(query, now=NOW)
            self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=2), "queueing is not serving")
            stale = live.latest_prefetch_receipt()
            assert stale is not None
            self.assertIn(first["record_id"], stale["selection"]["selected_record_ids"])
            pack = live.prefetch(query)
            self.assertEqual(rendered_ids(pack), [second["record_id"]])
            self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))
            current = live.latest_prefetch_receipt()
            assert current is not None
            self.assertEqual(current["selection"]["selected_record_ids"], [second["record_id"]])
            self.assertEqual(current["rendering"]["rendered_count"], 1)
            self.assertNotIn(first["record_id"], json.dumps(current))
            self.assertNotEqual(current["receipt_id"], stale["receipt_id"])
            (root / ".omh" / "memory" / "records" / f"{second['record_id']}.json").unlink()
            self.assertEqual(serve(live, query), "")
            self.assertIsNone(live.recall_status())
            empty = live.latest_prefetch_receipt()
            assert empty is not None
            self.assertEqual((empty["selection"]["selected_count"], empty["rendering"]["rendered_count"]), (0, 0))
            self.assertEqual(empty["selection"]["exclusion_reason_counts"], {})
            live.shutdown()
            self.assertIsNone(live.recall_status())
            self.assertIsNone(live.latest_prefetch_receipt())

    def test_receipt_is_redacted_bounded_and_bound_to_its_identities(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = approve(root, "sentinel summary phrase quokka lantern")
            query = "quokka lantern question"
            live = provider(root)
            serve(live, query)
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            self.assertEqual(receipt["schema_version"], receipts.MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION)
            self.assertEqual(receipt["state"], "returned_to_host")
            self.assertEqual(receipt["session_id"], SESSION)
            self.assertRegex(receipt["receipt_id"], r"^[0-9a-f]{64}$")
            self.assertRegex(receipt["configuration_id"], r"^[0-9a-f]{64}$")
            self.assertEqual(receipt["lens"]["scope_allowlist"], [PROJECT, THREAD, GLOBAL])
            self.assertEqual(receipt["lens"]["scope_status"], "resolved")
            self.assertEqual(receipt["lens"]["perspective"], {"observer": "", "observed": "hermes"})
            self.assertEqual(receipt["lens"]["query_digest"], sha256(query))
            self.assertTrue(receipt["lens"]["query_supplied"])
            self.assertEqual(receipt["selection"]["clock"], "2026-09-11T00:00:00Z")
            self.assertEqual(receipt["prepared_at"], "2026-09-11T00:00:00Z")
            self.assertEqual(
                receipt["rendering"]["rendered_records"],
                [{"record_id": record["record_id"], "content_digest": sha256(record["summary"])}],
            )
            self.assertEqual(receipt["store"]["home_digests"], [sha256(str((root / ".omh").resolve()))])
            self.assertEqual(receipt["render_configuration"], {"budget_chars": 2400, "summary_limit_chars": 500})
            self.assertIsNone(receipt["delivery_observed"])
            self.assertIsNone(receipt["model_use_observed"])
            self.assertEqual(receipt["proves"], "local_provider_preparation_and_return")
            self.assertEqual(receipt["redaction_policy"], "metadata_only")
            serialized = json.dumps(receipt)
            for forbidden in ("quokka", "lantern", "sentinel summary", "included_records", "summary\""):
                self.assertNotIn(forbidden, serialized)
            self.assertEqual(receipts.validate_prefetch_receipt(receipt), [])
            on_disk = receipts.read_prefetch_receipt(root / ".omh")
            self.assertEqual(on_disk, receipt)
            self.assertEqual(receipts.prefetch_receipt_path(root / ".omh"), root / ".omh" / "memory" / "prefetch_receipt.json")

    def test_an_empty_or_unresolved_lens_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = approve(root, "record that must stay hidden under an unresolved lens")
            with patch("omh.plugin_bundle.omh.memory_provider.prefetch_scope_allowlist", return_value=[]):
                live = provider(root)
                pack = serve(live)
            self.assertEqual(pack, "")
            self.assertIsNone(live.recall_status())
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            self.assertEqual(receipt["lens"]["scope_status"], "unresolved")
            self.assertEqual(receipt["lens"]["scope_allowlist"], [])
            self.assertEqual(receipt["selection"]["exclusion_reason_counts"], {"scope_unresolved": 1})
            self.assertEqual(receipt["selection"]["selected_record_ids"], [])
            self.assertEqual(receipt["rendering"]["rendered_count"], 0)
            self.assertFalse(receipt["selection"]["recall_enabled"])
            self.assertNotIn(record["record_id"], json.dumps(receipt))
            snapshot = memory_records.read_record_store_snapshot((root / ".omh",))
            for scopes in ([], [GLOBAL], [{"kind": "project", "ref": ""}], [{"kind": "project", "ref": "   "}]):
                with self.subTest(scopes=scopes):
                    prepared = memory_records.prepare_prefetch_records(snapshot, "", allowed_scopes=scopes, session_id=SESSION, now=NOW)
                    self.assertEqual(prepared.selection.scope_status, "unresolved")
                    self.assertEqual(prepared.section.text, "")
                    self.assertEqual(prepared.section.rendered, ())

    def test_incompatible_input_is_refused_not_guessed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = approve(root, "compatible record")
            snapshot = memory_records.read_record_store_snapshot((root / ".omh",))
            allowlist = memory_records.prefetch_scope_allowlist(project_identity=PROJECT_IDENTITY, session_id=SESSION)
            prepared = memory_records.prepare_prefetch_records(snapshot, "", allowed_scopes=allowlist, session_id=SESSION, now=NOW)
            self.assertEqual([item["record_id"] for item in prepared.section.rendered], [record["record_id"]])
            foreign_pack = {**prepared.selection.pack, "schema_version": "project_memory_recall_pack/v0"}
            foreign_selection = selector.MemoryRecallSelection(
                foreign_pack, prepared.selection.scope_allowlist, prepared.selection.scope_status,
                prepared.selection.exclusion_reason_counts, prepared.selection.configuration, prepared.selection.configuration_id,
            )
            with self.assertRaises(ValueError):
                memory_records.render_selected_memory_records(foreign_selection, snapshot.records)
            with self.assertRaises(ValueError):
                memory_records.render_selected_memory_records(prepared.selection, ())
            stray = memory_records.RenderedRecordSection(
                text=prepared.section.text,
                rendered=({"record_id": "mem_0000000000000000", "content_digest": "0" * 64},),
                omissions=prepared.section.omissions,
            )
            with self.assertRaises(ValueError):
                receipts.build_prefetch_receipt(
                    memory_records.PreparedPrefetch(prepared.selection, stray, NOW),
                    session_id=SESSION, home_digests=snapshot.home_digests,
                )
            with self.assertRaises(ValueError):
                memory_records.prepare_prefetch_records(
                    snapshot, "", allowed_scopes=[{"kind": "project", "ref": AWS_ACCESS_KEY_ID}], session_id=SESSION, now=NOW,
                )
            path = receipts.prefetch_receipt_path(root / ".omh")
            path.parent.mkdir(parents=True, exist_ok=True)
            self.assertIsNone(receipts.read_prefetch_receipt(root / ".omh"))
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(receipts.read_prefetch_receipt(root / ".omh"))
            good = receipts.build_prefetch_receipt(prepared, session_id=SESSION, home_digests=snapshot.home_digests)
            path.write_text(json.dumps({**good, "schema_version": "omh_memory_prefetch_receipt/v0"}), encoding="utf-8")
            self.assertIsNone(receipts.read_prefetch_receipt(root / ".omh"))
            path.write_text(json.dumps({**good, "rendering": {**good["rendering"], "rendered_count": 5}}), encoding="utf-8")
            self.assertIsNone(receipts.read_prefetch_receipt(root / ".omh"), "a count that contradicts its records is not a receipt")
            path.write_text(json.dumps(good), encoding="utf-8")
            self.assertEqual(receipts.read_prefetch_receipt(root / ".omh"), good)
            self.assertEqual(good["state"], "prepared")
            self.assertEqual(good["served_at"], "")

    def test_blocks_and_consolidation_keep_their_behaviour_beside_record_receipts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_memory = root / ".hermes" / "memories" / "MEMORY.md"
            hermes_memory.parent.mkdir(parents=True)
            hermes_memory.write_text("one fact", encoding="utf-8")
            write_memory_block(root / ".omh", approve_memory_block(build_memory_block("facts", "OMH wraps Hermes.")))
            record = approve(root, "reviewed record beside a block")
            live = provider(root)
            live.on_turn_start(1, "hi")
            # A session-ending brief needs the turn interval's worth of turns.
            state = empty_dreaming_state()
            for _ in range(DEFAULT_TURN_INTERVAL):
                state = record_turn(state)
            write_dreaming_state(root / ".omh", root / ".hermes", state)
            live.on_session_end()
            pack = serve(live, "reviewed record beside a block")
            self.assertLess(pack.index("<memory_blocks>"), pack.index("<memory_records>"))
            self.assertLess(pack.index("<memory_records>"), pack.index("<memory_consolidation"))
            self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=2))
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            self.assertEqual(receipt["rendering"]["rendered_count"], 1)
            self.assertEqual(receipt["rendering"]["rendered_block_count"], 1)
            self.assertEqual([item["record_id"] for item in receipt["rendering"]["rendered_records"]], [record["record_id"]])
            self.assertNotIn("consolidation", json.dumps(receipt))
            self.assertNotIn("OMH wraps Hermes", json.dumps(receipt))
            # The brief alone is a request, not memory: no indicator, and the
            # record receipt reports zero rendered records rather than the brief.
            (root / ".omh" / "memory" / "records" / f"{record['record_id']}.json").unlink()
            for path in (root / ".omh" / "memory" / "blocks").rglob("*.json"):
                path.unlink()
            # The first brief was served once; a fresh one (new raised_at) is served again.
            brief_path = consolidation_path(root / ".omh", root / ".hermes")
            fresh = json.loads(brief_path.read_text(encoding="utf-8"))
            fresh["raised_at"] = "2099-01-01T00:00:00Z"
            brief_path.write_text(json.dumps(fresh), encoding="utf-8")
            pack = serve(live)
            self.assertIn("<memory_consolidation", pack)
            self.assertIsNone(live.recall_status())
            receipt = live.latest_prefetch_receipt()
            assert receipt is not None
            self.assertEqual((receipt["rendering"]["rendered_count"], receipt["rendering"]["rendered_block_count"]), (0, 0))

    def test_standalone_bundle_prefetch_path_never_imports_the_control_plane(self) -> None:
        bundle = Path(__file__).resolve().parents[1] / "src" / "plugin_bundle"
        code = """
import json, sys
sys.path.insert(0, sys.argv[1])
from datetime import datetime, timezone
from omh.memory_records import prepare_prefetch_records, prefetch_scope_allowlist, read_record_store_snapshot
from omh.memory_prefetch_receipt import build_prefetch_receipt, validate_prefetch_receipt
snapshot = read_record_store_snapshot((sys.argv[2],))
prepared = prepare_prefetch_records(snapshot, "release", allowed_scopes=prefetch_scope_allowlist(project_identity="qa"),
                                    session_id="s", now=datetime(2026, 9, 11, tzinfo=timezone.utc))
receipt = build_prefetch_receipt(prepared, session_id="s", home_digests=snapshot.home_digests)
assert validate_prefetch_receipt(receipt) == [], validate_prefetch_receipt(receipt)
assert receipt["selection"]["selected_count"] == 0 and receipt["rendering"]["rendered_count"] == 0
assert "omh.workflows" not in sys.modules
print("standalone canonical prefetch: OK")
"""
        with TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", code, str(bundle), str(Path(tmp) / ".omh")],
                capture_output=True, text=True, check=False, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("standalone canonical prefetch: OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
