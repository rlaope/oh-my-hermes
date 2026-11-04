"""A saved point-in-time snapshot stays lasting, and the result says how to retire it later.

"As of 2026-10-30 (v0.1.7), nanran has ..." and "nanran v0.1.13 added ..."
describe a state the next release moves on from. The owner's store held eight
such records side by side, none ever replaced. The capture is unchanged (durable,
no review deadline, nothing hidden). The `remembered` result only carries
`point_in_time`, which tells the model to pass this record's id as `replaces`
when it saves the new state. The cue is a closed set, and versions stated as
constraints or conventions never match.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import memory_records  # noqa: E402
from omh.plugin_bundle.omh.memory_records import SNAPSHOT_RULE, render_memory_records  # noqa: E402
from omh.plugin_bundle.omh.tools.memory_tool import omh_memory_handler, omh_remember_handler, point_in_time_cue  # noqa: E402
from memory_recall_fixture import reviewed, selection  # noqa: E402
from project_identity_fixture import seed_project_identity  # noqa: E402
from test_memory_prefetch_canonical import SESSION, provider, serve  # noqa: E402

SNAPSHOT = "As of 2026-10-30 (v0.1.7), nanran has light and dark themes."
RELEASE_NOTE = "nanran v0.1.13 added folder export to the sidebar menu."
LASTING = "OMH requires Hermes v0.22.5 or newer for delegation backends."


class PointInTimeCueTests(unittest.TestCase):
    def test_snapshot_phrasings_match(self) -> None:
        for summary, record_type in (
            ("As of 2026-10-30 (v0.1.7), nanran has light and dark themes driven by CSS variables.", "fact"),
            ("As of 2026-11-01 (v0.1.15), nanran's sidebar groups papers into folders.", "decision"),
            ("as of 2026-01-01 the team uses Linear for tickets", "fact"),
            ("As of v0.1.7 the reader has two themes.", "fact"),
            ("Folder export is available in v0.1.14.", "episode"),
            ("nanran v0.1.13 added folder export", "fact"),
            ("nanran v0.1.16: the summary button opens a wide chat.", "fact"),
            ("As of 2026-10-30 releases ship from main.", "decision"),
        ):
            with self.subTest(summary=summary):
                self.assertTrue(point_in_time_cue(summary, record_type))

    def test_versions_stated_as_constraints_or_conventions_do_not_match(self) -> None:
        for summary, record_type in (
            ("OMH requires Hermes v0.22.5 or newer", "fact"),
            ("Pin Node v20.11 in CI because v22 breaks the native addon", "fact"),
            ("The deploy pipeline uses Terraform v1.6 and must not be upgraded without a plan", "fact"),
            ("Stay on React v18.3 until the design system migrates", "fact"),
            ("Our public API contract is v1.0 and is frozen; breaking changes need v2", "fact"),
            ("사용자는 Python v3.12 를 선호한다", "fact"),
            ("Semantic versioning: tags look like v1.2.3", "fact"),
            ("The project requires Python 3.11 or newer", "fact"),
            ("Pin Node 20 for the frontend build", "fact"),
            ("Use the v2 API for billing calls", "fact"),
            ("Hermes 0.22.5 is the minimum supported host", "fact"),
            ("Postgres 16 is the production database", "fact"),
            ("The SDK is pinned at openai==1.40.0", "fact"),
            ("Use HTTP/2 for the gateway", "fact"),
            ("Decided 2026-10-27: keep the monorepo", "decision"),
            ("Since v0.1.12 nanran stores settings in TOML", "fact"),
            ("Title-bar areas use a drag region since v0.1.12.", "fact"),
            ("v1 scope is only side-by-side English and Korean.", "fact"),
            ("2026-10-30 기준 nanran은 영어/한국어 병렬 보기만 지원한다", "fact"),
            # A snapshot phrasing that states a constraint: only the constraint words keep these out.
            ("As of 2026-10-30 every service must run Node v20.", "fact"),
            ("As of v4.0 the gateway requires TLS 1.3.", "fact"),
            ("Python v3.10 support was removed in v4.0.5; v3.11 is the minimum.", "fact"),
            ("As of 2026-10-30 deploys stay on the frozen branch.", "decision"),
        ):
            with self.subTest(summary=summary):
                self.assertFalse(point_in_time_cue(summary, record_type))

    def test_a_lesson_or_procedure_never_matches(self) -> None:
        for record_type in ("lesson", "procedure"):
            with self.subTest(record_type=record_type):
                self.assertFalse(point_in_time_cue("As of 2026-10-30 (v0.1.7), nanran has two themes.", record_type))
        self.assertFalse(point_in_time_cue("Release tags are written as v<major>.<minor>.<patch>, e.g. v4.0.5", "procedure"))


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        seed_project_identity(self.root)
        (self.root / ".hermes").mkdir()
        self.store = self.root / ".omh"
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.store), "HERMES_HOME": str(self.root / ".hermes")}))
        provider(self.root)

    def save(self, **args: object) -> dict:
        return json.loads(omh_remember_handler(dict(args), cwd=str(self.root), session_id=SESSION))

    def stored(self, record_id: str) -> dict:
        return json.loads((self.store / "memory" / "records" / f"{record_id}.json").read_text(encoding="utf-8"))


class PointInTimeAdviceTests(_StoreCase):
    def test_a_snapshot_save_stays_durable_and_says_how_to_retire_it(self) -> None:
        result = self.save(summary="nanran v0.1.13 added folder export to the sidebar menu.")
        self.assertEqual(result["status"], "remembered", result)
        advice = result["point_in_time"]
        self.assertEqual(advice["record_id"], result["record_id"])
        self.assertIn(f"replaces='{result['record_id']}'", advice["next_action"])
        # An additive release note must not be replaced by the next one ("v0.1.14
        # added folder import"): replaces is limited to the same thing changing.
        self.assertIn("when that same thing changes", advice["next_action"])
        self.assertIn("Something newly added", advice["next_action"])
        self.assertIn("is its own record: save it without replaces", advice["next_action"])
        record = self.stored(result["record_id"])
        self.assertEqual(record["retention"]["class"], "durable", "nothing ages")
        self.assertEqual(record["staleness"]["review_due_at"], "")

    def test_following_the_advice_leaves_only_the_new_state_in_recall(self) -> None:
        first = self.save(summary="As of 2026-10-30 (v0.1.7), nanran's sidebar lists papers in one flat list.")
        second = self.save(
            summary="As of 2026-11-01 (v0.1.15), nanran's sidebar groups papers into folders.", replaces=first["point_in_time"]["record_id"],
        )
        self.assertEqual((second["status"], second["superseded_record_id"]), ("corrected", first["record_id"]), second)
        recalled = self.save(action="recall", query="nanran sidebar papers")
        self.assertEqual([row["record_id"] for row in recalled["records"]], [second["record_id"]])
        # The corrected snapshot carries the advice for its own id, so the chain continues.
        self.assertEqual(second["point_in_time"]["record_id"], second["record_id"])
        self.assertIn(f"replaces='{second['record_id']}'", second["point_in_time"]["next_action"])

    def test_a_correction_that_is_not_a_snapshot_carries_no_advice(self) -> None:
        first = self.save(summary="As of 2026-10-30 (v0.1.7), nanran's sidebar lists papers in one flat list.")
        settled = self.save(summary="nanran's sidebar groups papers into folders.", replaces=first["record_id"])
        self.assertEqual(settled["status"], "corrected", settled)
        self.assertNotIn("point_in_time", settled)

    def test_the_full_capture_tool_carries_the_same_advice(self) -> None:
        result = json.loads(omh_memory_handler(
            {"action": "capture", "summary": "As of 2026-10-30 the team uses Linear for tickets."}, cwd=str(self.root), session_id=SESSION,
        ))
        self.assertEqual(result["status"], "remembered", result)
        self.assertEqual(result["point_in_time"]["record_id"], result["record_id"])

    def test_no_advice_for_a_lasting_fact_or_a_save_that_wrote_nothing(self) -> None:
        lasting = self.save(summary="OMH requires Hermes v0.22.5 or newer for delegation backends.")
        self.assertEqual(lasting["status"], "remembered", lasting)
        self.assertNotIn("point_in_time", lasting)
        procedure = self.save(summary="As of 2026-10-30, cut releases from the release branch.", record_type="procedure")
        self.assertEqual(procedure["status"], "remembered", procedure)
        self.assertNotIn("point_in_time", procedure)
        snapshot = "nanran v0.1.16: the summary button opens a wide chat."
        self.assertIn("point_in_time", self.save(summary=snapshot))
        again = self.save(summary=snapshot)
        self.assertEqual(again["status"], "already_remembered", again)
        self.assertNotIn("point_in_time", again)


def _record(record_id: str, summary: str, record_type: str = "fact") -> dict:
    return {"record_id": record_id, "record_type": record_type, "summary": summary, "approved_at": "2026-10-30T00:00:00Z"}


def _marked(text: str) -> dict[str, bool]:
    return {element.attrib["id"]: element.attrib.get("snapshot") == "as-of" for element in ElementTree.fromstring(text).iter("record")}


class SnapshotRecallMarkerTests(unittest.TestCase):
    """A later session sees a recalled snapshot marked, with the rule said once per section."""

    def test_snapshot_records_are_marked_and_the_rule_is_said_once(self) -> None:
        text, count = render_memory_records([_record("mem_a", SNAPSHOT), _record("mem_b", LASTING), _record("mem_c", RELEASE_NOTE, "decision")])
        self.assertEqual(count, 3)
        self.assertEqual(_marked(text), {"mem_a": True, "mem_b": False, "mem_c": True})
        rules = ElementTree.fromstring(text).findall("snapshots")
        self.assertEqual(len(rules), 1, text)
        self.assertEqual(rules[0].text, SNAPSHOT_RULE)
        # #2538's limit travels with the mark: only the same thing changing is a replacement.
        self.assertIn("still hold until it changes", SNAPSHOT_RULE)
        self.assertIn("When that same thing changes", SNAPSHOT_RULE)
        self.assertIn("something newly added is its own record, saved without replaces", SNAPSHOT_RULE)

    def test_constraint_episode_lesson_and_procedure_records_render_as_before(self) -> None:
        records = [
            _record("mem_a", "As of v4.0 the gateway requires TLS 1.3."),
            # An event never changes: capture still advises on it, recall does not mark it.
            _record("mem_e", "Bug fixed in v1.2.3 of libfoo.", "episode"),
            _record("mem_b", SNAPSHOT, "procedure"),
            _record("mem_c", SNAPSHOT, "lesson"),
            _record("mem_d", LASTING),
        ]
        self.assertTrue(point_in_time_cue("Bug fixed in v1.2.3 of libfoo.", "episode"))
        text, count = render_memory_records(records)
        self.assertEqual(count, 5)
        self.assertNotIn("snapshot", text)
        self.assertEqual(
            text.splitlines()[1],
            '  <record id="mem_a" type="fact" approved="2026-10-30">As of v4.0 the gateway requires TLS 1.3.</record>',
        )

    def test_the_mark_never_changes_which_records_render(self) -> None:
        records = [_record("mem_a", LASTING), _record("mem_b", SNAPSHOT), _record("mem_c", "Postgres 16 is the production database.")]
        full, _count = render_memory_records(records)
        for budget in range(len(full) + 1):
            text, count = render_memory_records(records, budget_chars=budget)
            with patch.object(memory_records, "snapshot_marked", return_value=False):
                plain, plain_count = render_memory_records(records, budget_chars=budget)
            with self.subTest(budget=budget):
                # The same records as with no mark at all; the mark is added only when it fits.
                self.assertEqual(count, plain_count)
                self.assertLessEqual(len(text), budget)
                if text != plain:
                    self.assertEqual(text.replace(f"\n  <snapshots>{SNAPSHOT_RULE}</snapshots>", "").replace(' snapshot="as-of">', ">"), plain)
                if text:
                    self.assertEqual(text.count("<snapshots>"), int(any(_marked(text).values())))
        lone = [_record("mem_b", SNAPSHOT)]
        marked, _count = render_memory_records(lone)
        with patch.object(memory_records, "snapshot_marked", return_value=False):
            plain, _count = render_memory_records(lone)
        self.assertIn("<snapshots>", marked)
        for budget in (len(plain), len(marked) - 1):
            with self.subTest(lone_budget=budget):
                self.assertEqual(render_memory_records(lone, budget_chars=budget), (plain, 1))
        self.assertEqual(render_memory_records(lone, budget_chars=len(marked)), (marked, 1))
        self.assertEqual(render_memory_records(lone, budget_chars=len(plain) - 1)[1], 0)

    def test_a_snapshot_never_costs_a_record_at_the_live_budget(self) -> None:
        # The provider renders at the default bound with the prefix rule; six
        # records that fit unmarked must all render, as on main.
        records = [_record("mem_0", (SNAPSHOT + " " + "x" * 280)[:330])]
        records += [_record(f"mem_{index}", f"Lasting fact {index} " + "y" * 280) for index in range(1, 6)]

        def render() -> tuple[str, list]:
            return memory_records._render_bounded(
                records, budget_chars=memory_records.DEFAULT_RECORD_RENDER_BUDGET_CHARS, limit=None,
                omissions={"render_budget_exhausted": 0, "over_budget": 0}, preserve_prefix=True,
            )

        text, rendered = render()
        with patch.object(memory_records, "snapshot_marked", return_value=False):
            plain, plain_rendered = render()
        self.assertEqual(len(plain_rendered), 6)
        self.assertEqual(rendered, plain_rendered)
        self.assertEqual(text, plain, "the mark does not fit here, so the section is main's bytes")

    def test_the_record_index_line_carries_no_mark(self) -> None:
        pairs = [reviewed("mem_one", summary=SNAPSHOT), reviewed("mem_two", summary=RELEASE_NOTE, subject="folder-export")]
        selected = selection(pairs, query="Astronomy telescope")
        records = [record for record, _ in pairs]
        section = memory_records.render_selected_memory_records(selected, records, index_fallback=True)
        self.assertEqual(sorted(section.indexed), ["mem_one", "mem_two"])
        self.assertNotIn("snapshot", section.text)
        # A snapshot captured in this conversation is shown in full, and marked.
        shown = memory_records.render_selected_memory_records(selected, records, index_fallback=True, full_text_ids={"mem_one"})
        self.assertEqual(_marked(shown.text), {"mem_one": True})
        self.assertEqual(shown.text.count("<snapshots>"), 1)
        index_line = next(line for line in shown.text.splitlines() if "<record_index" in line)
        self.assertNotIn("snapshot", index_line)
        # Short of room for the mark, the indexed section keeps the same records and index, unmarked.
        with patch.object(memory_records, "snapshot_marked", return_value=False):
            plain = memory_records.render_selected_memory_records(selected, records, index_fallback=True, full_text_ids={"mem_one"})
        tight = memory_records.render_selected_memory_records(
            selected, records, index_fallback=True, full_text_ids={"mem_one"}, budget_chars=len(shown.text) - 1,
        )
        self.assertEqual((tight.text, tight.rendered, tight.indexed), (plain.text, plain.rendered, plain.indexed))
        self.assertEqual(tight.indexed, shown.indexed)


class SnapshotRecallMarkerReachTests(_StoreCase):
    """The mark reaches the live pack of another session and the tool's own recall."""

    def test_tool_recall_marks_snapshot_rows_and_says_the_rule_once(self) -> None:
        snapshot = self.save(summary="As of 2026-10-30 (v0.1.7), nanran's sidebar lists papers in one flat list.")
        lasting = self.save(summary="nanran's sidebar papers are sorted by the date they were added.")
        recalled = self.save(action="recall", query="nanran sidebar papers")
        rows = {row["record_id"]: row for row in recalled["records"]}
        self.assertEqual(set(rows), {snapshot["record_id"], lasting["record_id"]}, recalled)
        self.assertEqual(rows[snapshot["record_id"]]["snapshot"], "as-of")
        self.assertNotIn("snapshot", rows[lasting["record_id"]])
        self.assertEqual(recalled["next_action"].count(SNAPSHOT_RULE), 1)
        plain = self.save(action="recall", query="sorted date added")
        self.assertEqual([row["record_id"] for row in plain["records"]], [lasting["record_id"]], plain)
        self.assertNotIn(SNAPSHOT_RULE, plain["next_action"])

    def test_a_later_session_sees_the_snapshot_marked_in_its_pack(self) -> None:
        saved = self.save(summary="As of 2026-10-30 (v0.1.7), nanran's sidebar lists papers in one flat list.")
        pack = serve(provider(self.root, session_id="session-later"), "nanran sidebar papers")
        self.assertIn(f'<record id="{saved["record_id"]}"', pack)
        self.assertEqual(pack.count(' snapshot="as-of">'), 1, pack)
        self.assertEqual(pack.count(f"<snapshots>{SNAPSHOT_RULE}</snapshots>"), 1, pack)


if __name__ == "__main__":
    unittest.main()
