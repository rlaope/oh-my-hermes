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

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh.tools.memory_tool import omh_memory_handler, omh_remember_handler, point_in_time_cue  # noqa: E402
from project_identity_fixture import seed_project_identity  # noqa: E402
from test_memory_prefetch_canonical import SESSION, provider  # noqa: E402


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


class PointInTimeAdviceTests(unittest.TestCase):
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

    def test_a_snapshot_save_stays_durable_and_says_how_to_retire_it(self) -> None:
        result = self.save(summary="nanran v0.1.13 added folder export to the sidebar menu.")
        self.assertEqual(result["status"], "remembered", result)
        advice = result["point_in_time"]
        self.assertEqual(advice["record_id"], result["record_id"])
        self.assertIn(f"replaces='{result['record_id']}'", advice["next_action"])
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


if __name__ == "__main__":
    unittest.main()
