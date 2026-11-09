"""Live recall shows what the turn asked for, once per conversation.

Measured on the owner's stores (2026-11-03 audit): 89% of the records a live
turn received shared no word with the person's message, 84% repeated a record
the same session had already received, and 55 of 126 messenger recall lines
fell on host notices nobody wrote. Three causes, each pinned here with the
cases that must not change:

- the selector's active-tier fallback served the whole store in full for a
  query that matched nothing, and an unqueried selection for an empty one;
  the live provider now withholds both and names neither (pins and
  same-conversation captures stay in full), and tool
  recall passes ``query_fallback=False``, while the handoff facade keeps the
  fallback in full;
- the provider re-served the same records every turn although Hermes replays
  each turn's injected block until compaction; it now skips a record the
  conversation already holds at the same ``recall_revision``, a record it
  withheld stays held for later unanswered turns, and both are forgotten at any session
  switch, so a compaction lets a record come back once;
- a turn that was only a host notice was served the store; it now considers
  no record at all, not even pins or an index.
"""
from __future__ import annotations

from contextlib import chdir
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from memory_recall_fixture import included_ids, payload, reviewed, selection  # noqa: E402
from project_identity_fixture import memory_paths as resolve_paths, seed_project_identity  # noqa: E402
from omh.plugin_bundle.omh import memory_prefetch_receipt as receipts  # noqa: E402
from omh.plugin_bundle.omh.memory_blocks import approve_memory_block, build_memory_block, write_memory_block  # noqa: E402
from omh.plugin_bundle.omh.memory_provider import RecallStatus  # noqa: E402
from omh.plugin_bundle.omh.memory_query_sanitizer import sanitize_memory_query  # noqa: E402
from omh.plugin_bundle.omh.memory_recall_selector import recall_revision  # noqa: E402
from omh.plugin_bundle.omh.tools.memory_tool import omh_memory_handler  # noqa: E402
from omh.workflows import memory, memory_recall_incident as incident, memory_recall_incident_model as incident_model  # noqa: E402
from test_memory_prefetch_canonical import SESSION, approve, provider, rendered_ids  # noqa: E402
from test_memory_provider_hermes_order import hermes_turn  # noqa: E402

_NO_MATCH = "quantum ledger reconciliation"
# Hermes' own shape (`tools/process_registry_notifications.py`): one bracketed block.
_NOTICE = "[IMPORTANT: Background process proc_1a2b completed (exit code 0).\nCommand: pytest -q\nOutput:\n12 passed]"
_BATCH = "[ASYNC DELEGATION BATCH COMPLETE batch_7: 3/3 tasks done]\nresults follow"
_DEPLOY = "Deploys wait for the nightly build"
_PARSER = "Parser ownership moved to the platform team"


def _reasons(result: object) -> dict[str, str]:
    return {str(row["record_id"]): str(row["reason"]) for row in payload(result)["excluded_records"]}  # type: ignore[arg-type, index]


class SelectorQueryFallbackSwitchTests(unittest.TestCase):
    def test_a_query_that_matches_nothing_serves_nothing_without_the_fallback(self) -> None:
        pairs = [reviewed("mem-a", summary=_DEPLOY), reviewed("mem-b", summary=_PARSER)]
        result = selection(pairs, _NO_MATCH, query_fallback=False)
        self.assertEqual(included_ids(result), [])
        self.assertNotIn("query_fallback", payload(result))
        self.assertEqual(result.exclusion_reason_counts, {"no_query_overlap": 2})
        self.assertEqual(result.configuration["query_fallback"], "off")
        self.assertEqual(memory.validate_project_memory_recall_pack(payload(result)), [])

    def test_the_default_keeps_the_fallback_and_its_configuration_identity(self) -> None:
        pairs = [reviewed("mem-a", summary=_DEPLOY), reviewed("mem-b", summary=_PARSER)]
        default = selection(pairs, _NO_MATCH)
        explicit = selection(pairs, _NO_MATCH, query_fallback=True)
        self.assertEqual(included_ids(default), ["mem-a", "mem-b"])
        self.assertEqual(payload(default)["query_fallback"]["mode"], "active_tier")  # type: ignore[index]
        self.assertEqual(default.configuration["query_fallback"], "active_tier_unless_unstemmed_common_terms_only/v2")
        self.assertEqual(default.configuration_id, explicit.configuration_id)
        self.assertNotEqual(default.configuration_id, selection(pairs, _NO_MATCH, query_fallback=False).configuration_id)

    def test_an_unqueried_selection_serves_pins_only_without_the_fallback(self) -> None:
        pairs = [reviewed("mem-pin", summary=_DEPLOY), reviewed("mem-b", summary=_PARSER)]
        for query in ("", "!!", "?"):
            with self.subTest(query=query):
                result = selection(pairs, query, pins={"mem-pin"}, query_fallback=False)
                self.assertEqual(included_ids(result), ["mem-pin"])
                self.assertEqual(_reasons(result), {"mem-b": "no_query_overlap"})
                self.assertEqual(included_ids(selection(pairs, query, query_fallback=False)), [])
        self.assertEqual(included_ids(selection(pairs, "", pins={"mem-pin"})), ["mem-pin", "mem-b"], "the default still serves the store unqueried")

    def test_a_matching_query_serves_the_same_records_either_way(self) -> None:
        pairs = [reviewed("mem-a", summary=_DEPLOY), reviewed("mem-b", summary=_PARSER)]
        self.assertEqual(included_ids(selection(pairs, "nightly deploys", query_fallback=False)), ["mem-a"])
        self.assertEqual(included_ids(selection(pairs, "nightly deploys")), ["mem-a"])


class SelectorSessionServedTests(unittest.TestCase):
    def test_a_held_record_is_skipped_and_its_slot_goes_to_the_next(self) -> None:
        first, second = reviewed("mem-a", summary="Deploys wait for nightly"), reviewed("mem-b", summary="Deploys need a green canary")
        served = {"mem-a": recall_revision(first[0])}
        result = selection([first, second], "deploys", limit=1, session_served=served)
        self.assertEqual(included_ids(result), ["mem-b"])
        self.assertEqual(_reasons(result), {"mem-a": "served_this_session"})
        self.assertFalse(payload(result)["truncated"])

    def test_a_record_at_another_revision_is_served_again(self) -> None:
        record, review = reviewed("mem-a", summary="Deploys wait for nightly")
        revised = {**record, "summary": "Deploys wait for the morning build"}
        for stale in ({**record, "revision": 0}, revised):
            with self.subTest(stale=stale["summary"]):
                result = selection([(record, review)], "deploys", session_served={"mem-a": recall_revision(stale)})
                self.assertEqual(included_ids(result), ["mem-a"])
        self.assertEqual(recall_revision(record), recall_revision({**record, "updated_at": "2026-10-01T00:00:00Z"}), "a confirm is not a revision")

    def test_a_held_record_never_turns_the_query_into_a_fallback(self) -> None:
        matching, other = reviewed("mem-a", summary="Deploys wait for nightly"), reviewed("mem-b", summary=_PARSER)
        result = selection([matching, other], "deploys", session_served={"mem-a": recall_revision(matching[0])})
        self.assertEqual(included_ids(result), [], "the query matched; the match is already held, so nothing unrelated replaces it")
        self.assertNotIn("query_fallback", payload(result))


class SelectorListedTests(unittest.TestCase):
    def test_a_listed_record_leaves_an_unanswered_pack_without_pulling_in_another(self) -> None:
        pairs = [reviewed(f"mem-{index}", summary=f"Distinct fact number {index}") for index in range(3)]
        listed = {f"mem-{index}": f"listed:{recall_revision(pairs[index][0])}" for index in range(2)}
        for query in (_NO_MATCH, ""):
            with self.subTest(query=query):
                result = selection(pairs, query, limit=2, session_served=listed)
                self.assertEqual(included_ids(result), [], "the cut kept the two listed records; the third stays over budget")
                self.assertEqual(result.exclusion_reason_counts, {"listed_this_session": 2, "over_budget": 1})

    def test_a_query_that_matches_a_listed_record_gets_it_in_full(self) -> None:
        record, review = reviewed("mem-a", summary="Deploys wait for nightly")
        result = selection([(record, review)], "deploys", session_served={"mem-a": f"listed:{recall_revision(record)}"})
        self.assertEqual(included_ids(result), ["mem-a"])


class SanitizedHostOnlyTests(unittest.TestCase):
    def test_a_turn_of_only_host_notices_is_host_only(self) -> None:
        for raw in (_NOTICE, _BATCH):
            with self.subTest(raw=raw[:30]):
                cleaned = sanitize_memory_query(raw)
                self.assertEqual((cleaned.clean, cleaned.host_only), ("", True))

    def test_words_before_a_notice_or_a_blank_turn_are_not_host_only(self) -> None:
        self.assertFalse(sanitize_memory_query(f"how do deploys work?\n{_NOTICE}").host_only)
        # A pasted notice followed by the person's own question: the words
        # after the closing bracket are theirs.
        for after in ("이거 왜 실패했어?", "why did it fail?"):
            with self.subTest(after=after):
                self.assertFalse(sanitize_memory_query(f"{_NOTICE}\n{after}").host_only)
        self.assertFalse(sanitize_memory_query("").host_only)
        self.assertFalse(sanitize_memory_query("   ").host_only)
        self.assertFalse(sanitize_memory_query("ok").host_only)


class ProviderLiveRecallTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".hermes").mkdir()
        self.paths = resolve_paths(self.root / ".omh", self.root / ".hermes")

    def test_a_host_notice_turn_serves_no_records_not_even_a_pin_and_posts_no_line(self) -> None:
        pinned = approve(self.root, _DEPLOY)
        approve(self.root, _PARSER)
        memory.set_memory_pin(self.paths, pinned["record_id"], pinned=True)
        live = provider(self.root)
        for turn, notice in enumerate((_NOTICE, _BATCH), start=1):
            with self.subTest(notice=notice[:30]):
                self.assertEqual(rendered_ids(hermes_turn(live, turn, notice)), [])
                self.assertIsNone(live.recall_status())
                receipt = live.latest_prefetch_receipt()
                assert receipt is not None
                self.assertEqual(receipt["selection"]["selected_record_ids"], [])
                self.assertEqual(receipt["lens"]["query_method"], "empty")
        # The pin is still served on the person's next turn.
        self.assertEqual(rendered_ids(hermes_turn(live, 3, "ok")), [pinned["record_id"]])

    def test_an_empty_turn_shows_pins_and_lists_the_rest(self) -> None:
        pinned = approve(self.root, _DEPLOY)
        parser = approve(self.root, _PARSER)
        memory.set_memory_pin(self.paths, pinned["record_id"], pinned=True)
        live = provider(self.root)
        for turn, message in enumerate(("", "   ", "야"), start=1):
            with self.subTest(message=message):
                pack = hermes_turn(live, turn, message)
                receipt = live.latest_prefetch_receipt()
                assert receipt is not None
                if turn == 1:
                    self.assertEqual(rendered_ids(pack), [pinned["record_id"]])
                    self.assertNotIn(_PARSER, pack)
                    self.assertEqual(receipt["rendering"]["indexed_records"], [parser["record_id"]])
                    self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))
                else:
                    # The pin is held and the index is unchanged: nothing new, no line.
                    self.assertNotIn("<memory_records>", pack)
                    self.assertIsNone(live.recall_status())
                    self.assertEqual(
                        receipt["selection"]["exclusion_reason_counts"], {"listed_this_session": 1, "served_this_session": 1},
                    )

    def test_a_turn_that_matches_nothing_serves_nothing(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        parser = approve(self.root, _PARSER)
        live = provider(self.root)
        self.assertEqual(hermes_turn(live, 1, "hello there"), "")
        self.assertIsNone(live.recall_status())
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(sorted(receipt["rendering"]["indexed_records"]), sorted([deploy["record_id"], parser["record_id"]]))
        for turn, message in enumerate((_NO_MATCH, "야"), start=2):
            with self.subTest(message=message):
                self.assertEqual(hermes_turn(live, turn, message), "")
                self.assertIsNone(live.recall_status())
        # A message that does match a withheld record gets it in full.
        self.assertEqual(rendered_ids(hermes_turn(live, 4, "when do deploys run?")), [deploy["record_id"]])
        self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))

    def test_a_record_pinned_after_it_was_withheld_is_shown_in_full(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        approve(self.root, _PARSER)
        live = provider(self.root)
        self.assertEqual(hermes_turn(live, 1, ""), "")
        memory.set_memory_pin(self.paths, deploy["record_id"], pinned=True)
        # Withheld before, but a pin is always in context: it is shown in full.
        self.assertEqual(rendered_ids(hermes_turn(live, 2, "")), [deploy["record_id"]])

    def test_a_new_conversation_after_a_withholding_turn_withholds_again(self) -> None:
        # The old conversation was shown nothing; its next turn renders with
        # every record withheld, and `/new` arrives after that render.
        deploy = approve(self.root, _DEPLOY)
        parser = approve(self.root, _PARSER)
        live = provider(self.root)
        self.assertEqual(hermes_turn(live, 1, "hello there"), "")
        live.on_turn_start(1, "hello there")
        pack = live.prefetch("hello there", session_id="session-new")
        self.assertEqual(pack, "")
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(sorted(receipt["rendering"]["indexed_records"]), sorted([deploy["record_id"], parser["record_id"]]))

    def test_an_index_names_only_records_the_conversation_does_not_hold(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        parser = approve(self.root, _PARSER)
        live = provider(self.root)
        hermes_turn(live, 1, "when do deploys run?")
        hermes_turn(live, 2, "hello there")
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(receipt["rendering"]["indexed_records"], [parser["record_id"]])
        self.assertIn(deploy["record_id"], receipt["selection"]["served_this_session"])

    def test_a_matching_turn_serves_once_and_the_repeat_posts_no_line(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        parser = approve(self.root, _PARSER)
        live = provider(self.root)
        self.assertEqual(rendered_ids(hermes_turn(live, 1, "when do deploys run?")), [deploy["record_id"]])
        self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))
        live.queue_prefetch("when do deploys run?")
        self.assertEqual(rendered_ids(hermes_turn(live, 2, "when do deploys run?")), [])
        self.assertIsNone(live.recall_status())
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(receipt["selection"]["exclusion_reason_counts"].get("served_this_session"), 1)
        # Only what is new counts: the deploy record stays held.
        self.assertEqual(rendered_ids(hermes_turn(live, 3, "deploys and parser ownership")), [parser["record_id"]])
        self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))

    def test_a_queued_render_that_is_never_served_holds_nothing_back(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        live = provider(self.root)
        live.queue_prefetch("when do deploys run?")
        self.assertEqual(rendered_ids(hermes_turn(live, 1, "when do deploys run?")), [deploy["record_id"]])

    def test_a_compaction_lets_each_record_come_back_once(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        live = provider(self.root)
        hermes_turn(live, 1, "when do deploys run?")
        self.assertEqual(rendered_ids(hermes_turn(live, 2, "when do deploys run?")), [])
        # In place (Hermes' default) the id stays; rotated, it moves. Both are
        # reported with reset false, and the summary dropped the old blocks.
        for turn, new_id in ((3, SESSION), (5, "session-compressed")):
            with self.subTest(new_id=new_id):
                live.on_session_switch(new_id, parent_session_id=SESSION, reset=False, reason="compression")
                self.assertEqual(rendered_ids(hermes_turn(live, turn, "when do deploys run?")), [deploy["record_id"]])
                self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))
                self.assertEqual(rendered_ids(hermes_turn(live, turn + 1, "when do deploys run?")), [])
                self.assertIsNone(live.recall_status())

    def test_a_new_conversation_reported_after_the_turn_render_still_serves(self) -> None:
        # Hermes often reports `/new` after the next turn's on_turn_start has
        # rendered under the old conversation; prefetch then sees the new id.
        deploy = approve(self.root, _DEPLOY)
        live = provider(self.root)
        hermes_turn(live, 1, "when do deploys run?")
        live.on_turn_start(1, "when do deploys run?")
        pack = live.prefetch("when do deploys run?", session_id="session-new")
        self.assertEqual(rendered_ids(pack), [deploy["record_id"]])
        self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(receipt["session_id"], "session-new")
        # The late report starts nothing over: the new conversation holds it now.
        live.on_session_switch("session-new", parent_session_id=SESSION, reset=True)
        self.assertEqual(rendered_ids(hermes_turn(live, 2, "when do deploys run?", session_id="session-new")), [])
        self.assertIsNone(live.recall_status())

    def test_a_new_conversation_reported_before_the_turn_serves(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        live = provider(self.root)
        hermes_turn(live, 1, "when do deploys run?")
        live.on_session_switch("session-new", parent_session_id=SESSION, reset=True)
        self.assertEqual(rendered_ids(hermes_turn(live, 1, "when do deploys run?", session_id="session-new")), [deploy["record_id"]])
        self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))

    def test_a_held_record_is_named_in_the_receipt_and_the_incident(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        live = provider(self.root)
        hermes_turn(live, 1, "when do deploys run?")
        hermes_turn(live, 2, "when do deploys run?")
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(receipt["selection"]["served_this_session"], [deploy["record_id"]])
        self.assertEqual(receipts.validate_prefetch_receipt(receipt), [])
        self.assertIn("selection.served_this_session", receipts.validate_prefetch_receipt(
            {**receipt, "selection": {**receipt["selection"], "served_this_session": [""]}}))
        self.assertEqual(incident._receipt_stage(receipt, deploy["record_id"], "unused"), ("served_this_session", "selected"))
        diagnosed = incident_model.diagnosis("served_this_session", "live_prefetch_receipt")
        self.assertEqual((diagnosed["stage"], diagnosed["reason_code"]), ("unresolved", "served_this_session"))
        self.assertFalse(diagnosed["omh_correction_proposed"])

    def test_a_new_conversation_and_a_new_provider_serve_again(self) -> None:
        deploy = approve(self.root, _DEPLOY)
        live = provider(self.root)
        hermes_turn(live, 1, "when do deploys run?")
        live.on_session_switch("session-new", reset=True)
        self.assertEqual(rendered_ids(hermes_turn(live, 1, "when do deploys run?")), [deploy["record_id"]])
        live.shutdown()
        again = provider(self.root, session_id="session-new")
        self.assertEqual(rendered_ids(hermes_turn(again, 1, "when do deploys run?")), [deploy["record_id"]])

    def test_blocks_count_for_the_line_only_when_they_change(self) -> None:
        write_memory_block(self.root / ".omh", approve_memory_block(build_memory_block("facts", "OMH wraps Hermes.")))
        live = provider(self.root)
        pack = hermes_turn(live, 1, "hello")
        self.assertIn("<memory_blocks>", pack)
        self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))
        pack = hermes_turn(live, 2, "hello again")
        self.assertIn("<memory_blocks>", pack, "the operator's blocks still ride every console turn")
        self.assertIsNone(live.recall_status(), "unchanged blocks are not news")
        live.on_session_switch(SESSION, reset=False, reason="compression")
        hermes_turn(live, 3, "hello")
        self.assertEqual(live.recall_status(), RecallStatus(provider_label="OMH", count=1))


class ToolRecallRelevanceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        seed_project_identity(self.root)
        (self.root / ".hermes").mkdir()
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.root / ".omh"), "HERMES_HOME": str(self.root / ".hermes")}))
        self.enterContext(chdir(self.root))
        self.live = provider(self.root)

    def recall(self, query: str) -> dict:
        return json.loads(self.live.handle_tool_call("omh_remember", {"action": "recall", "query": query}))

    def test_an_earlier_conversation_record_the_turn_does_not_touch_adds_no_memory_block(self) -> None:
        # Measured 2026-11-08 (live Hermes, persona with no reply language, a
        # Korean-writing user): an English line naming one unrelated stored
        # record, inside Hermes' "should inform all responses" fence, took
        # Korean replies from 14/20 to 5/20, and no turn read the record.
        summary = (
            "Team of 3 is building an internal ticket tool with about 50 writes per day. "
            "They are deciding between SQLite and Postgres; lowest operational burden is the top priority."
        )
        saved = json.loads(self.live.handle_tool_call(
            "omh_remember", {"summary": summary, "record_type": "fact", "subject": "ticket-tool-db-choice"}))
        self.assertEqual(saved["status"], "remembered", saved)
        self.live = provider(self.root, session_id="session-later")
        for turn, message in enumerate((
            "이 폴더의 calc.py에 버그가 있는지 리뷰해 주세요.",
            "Review calc.py in this folder for bugs.",
        ), start=1):
            with self.subTest(message=message):
                pack = hermes_turn(self.live, turn, message)
                self.assertEqual(pack, "", "no record matched, so Hermes must get nothing to fence")
                self.assertIsNone(self.live.recall_status())
                receipt = self.live.latest_prefetch_receipt()
                assert receipt is not None
                self.assertEqual(receipt["rendering"]["rendered_records"], [])
        # The model still reaches it on purpose, by subject or by its words.
        for query in ("ticket-tool-db-choice", "SQLite Postgres"):
            with self.subTest(query=query):
                found = self.recall(query)
                self.assertEqual((found["status"], [row["record_id"] for row in found["records"]]), ("found", [saved["record_id"]]))
        # And a turn that does touch it is served the record in full.
        pack = hermes_turn(self.live, 3, "Should the ticket tool use SQLite or Postgres?")
        self.assertEqual(rendered_ids(pack), [saved["record_id"]])
        self.assertIn(summary, pack)

    def test_a_query_that_matches_nothing_is_nothing_found(self) -> None:
        saved = json.loads(self.live.handle_tool_call("omh_remember", {"summary": _DEPLOY, "record_type": "decision"}))
        found = self.recall("nightly deploys")
        self.assertEqual((found["status"], [row["record_id"] for row in found["records"]]), ("found", [saved["record_id"]]))
        missing = self.recall(_NO_MATCH)
        self.assertEqual((missing["status"], missing["records"]), ("nothing_found", []))
        self.assertIn("matches words, not meaning", missing["next_action"])
        self.assertIn("tags hold its topic words", missing["next_action"])

    def test_a_subject_that_is_also_a_topic_word_still_searches_the_words(self) -> None:
        subject = json.loads(self.live.handle_tool_call(
            "omh_remember", {"summary": "Deploy windows close at 18:00", "record_type": "decision", "subject": "deploy"}))["record_id"]
        other = json.loads(self.live.handle_tool_call(
            "omh_remember", {"summary": "Deploy logs go to the ops bucket", "record_type": "fact"}))["record_id"]
        for query in ("deploy", "fact deploy"):
            with self.subTest(query=query):
                found = [row["record_id"] for row in self.recall(query)["records"]]
                self.assertEqual(found[0], subject, "the subject's own record leads")
                self.assertIn(other, found, "the word still searches every record")

    def test_an_index_label_reads_the_record(self) -> None:
        saved = json.loads(self.live.handle_tool_call(
            "omh_remember", {"summary": _DEPLOY, "record_type": "decision", "subject": "deploy-window"}))["record_id"]
        for query in ("deploy-window", f"decision {saved}", saved):
            with self.subTest(query=query):
                found = self.recall(query)
                self.assertEqual((found["status"], [row["record_id"] for row in found["records"]]), ("found", [saved]))
        self.assertEqual(self.recall("deploy-windows")["status"], "nothing_found")

    def confirm(self, record_id: str) -> dict:
        return json.loads(omh_memory_handler({"action": "confirm", "record_id": record_id}, cwd=str(self.root), session_id=SESSION))

    def test_confirming_an_open_record_serves_it_once_more(self) -> None:
        record = approve(self.root, "Which license should the SDK carry", unresolved=True)
        self.assertEqual(rendered_ids(hermes_turn(self.live, 1, "sdk license?")), [record["record_id"]])
        self.assertEqual(rendered_ids(hermes_turn(self.live, 2, "sdk license?")), [])
        self.assertEqual(self.confirm(record["record_id"])["status"], "confirmed")
        # Settled now: the open/settled state is part of what was served.
        self.assertEqual(rendered_ids(hermes_turn(self.live, 3, "sdk license?")), [record["record_id"]])
        self.assertEqual(rendered_ids(hermes_turn(self.live, 4, "sdk license?")), [])

    def test_a_record_shown_at_an_older_revision_is_withheld_on_unanswered_turns(self) -> None:
        record = approve(self.root, "Which license should the SDK carry", unresolved=True)
        hermes_turn(self.live, 1, "sdk license?")
        self.assertEqual(self.confirm(record["record_id"])["status"], "confirmed")
        # Unanswered turns: the revised record is withheld, then held as withheld.
        for turn in (2, 3):
            self.assertEqual(hermes_turn(self.live, turn, "hello there"), "")
            self.assertIsNone(self.live.recall_status())
        receipt = self.live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(receipt["selection"]["exclusion_reason_counts"].get("listed_this_session"), 1)
        # Asked again, the revised record comes back in full.
        self.assertEqual(rendered_ids(hermes_turn(self.live, 4, "sdk license?")), [record["record_id"]])

    def test_a_query_naming_record_ids_still_finds_them(self) -> None:
        first = json.loads(self.live.handle_tool_call("omh_remember", {"summary": _DEPLOY, "record_type": "decision"}))["record_id"]
        second = json.loads(self.live.handle_tool_call("omh_remember", {"summary": _PARSER, "record_type": "fact"}))["record_id"]
        found = self.recall(first)
        self.assertEqual((found["status"], [row["record_id"] for row in found["records"]]), ("found", [first]))
        both = self.recall(f"{second} {first}")
        self.assertEqual(sorted(row["record_id"] for row in both["records"]), sorted([first, second]))
        self.assertEqual(self.recall("mem_0000000000000000")["status"], "nothing_found")


if __name__ == "__main__":
    unittest.main()
