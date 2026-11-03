"""Point-in-time snapshots age, restated facts yield to the newest, project facts say where they belong.

Three rules, each with the cases that must not move:

- A model capture whose summary states a dated or versioned snapshot ("As of
  2026-10-30 (v0.1.7), ...", "nanran v0.1.13 added ...") and names no
  retention class is kept `standard`, with the default 90-day review deadline,
  instead of `durable`. Dated decisions, bare "v1" and versions without "v"
  stay durable, and a class the captor chose is kept.
- Recall serves only the newest of admitted records that restate one fact:
  the same scope, no two different subjects, one topic (the project scope, or
  a shared topic tag), and wording at `SIMILAR_WORDING_JACCARD_PCT`. Two
  similar facts that can both be true are both served.
- A user-global capture made outside a repository that names a known project
  carries a `scope_hint`. The record is never moved.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from memory_recall_fixture import GLOBAL, PROJECT, included_ids, mapping, payload, reviewed, selection, text  # noqa: E402
from omh.plugin_bundle.omh.memory_recall_selector import effective_recall_configuration  # noqa: E402
from omh.plugin_bundle.omh.memory_records import read_record_store_snapshot, select_prefetch_records  # noqa: E402
from omh.plugin_bundle.omh.memory_recall_support import SIMILAR_WORDING_JACCARD_PCT, memory_summary_terms  # noqa: E402
from omh.plugin_bundle.omh.tools.memory_tool import omh_memory_handler, omh_remember_handler, point_in_time_cue  # noqa: E402
from project_identity_fixture import seed_project_identity  # noqa: E402
from test_memory_prefetch_canonical import SESSION, provider  # noqa: E402


# A session in a repository: its project scope beside the user-global one.
LENS = [PROJECT, GLOBAL]


def _wording_pct(first: str, second: str) -> int:
    a, b = memory_summary_terms(first), memory_summary_terms(second)
    return len(a & b) * 100 // len(a | b)


def _reasons(result: object) -> dict[str, dict[str, object]]:
    return {text(mapping(row)["record_id"]): mapping(row) for row in payload(result)["excluded_records"]}  # type: ignore[arg-type, union-attr]


class _StoreCase(unittest.TestCase):
    """A real temp home with a repository and a directory outside any repository."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        seed_project_identity(self.root)
        (self.root / ".hermes").mkdir()
        self.outside = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.store = self.root / ".omh"
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.store), "HERMES_HOME": str(self.root / ".hermes")}))
        provider(self.root)

    def capture(self, cwd: Path | None = None, **args: object) -> dict:
        return json.loads(omh_memory_handler({"action": "capture", **args}, cwd=str(cwd or self.outside), session_id=SESSION))

    def save(self, cwd: Path | None = None, **args: object) -> dict:
        return json.loads(omh_remember_handler(dict(args), cwd=str(cwd or self.outside), session_id=SESSION))

    def stored(self, record_id: str) -> dict:
        return json.loads((self.store / "memory" / "records" / f"{record_id}.json").read_text(encoding="utf-8"))


class PointInTimeCueTests(unittest.TestCase):
    def test_the_closed_set_matches_dated_and_versioned_snapshots(self) -> None:
        for summary, cue in (
            ("As of 2026-10-30 (v0.1.7), nanran has light and dark themes.", "as_of_date"),
            ("References live in ~/kami-refs as of 2026-10-28.", "as_of_date"),
            ("nanran v0.1.13 added an easy-explanation translation mode.", "version"),
            ("nanran v0.1.16: the summary button opens a wide chat.", "version"),
            ("Title-bar areas use a drag region since v0.1.12.", "version"),
        ):
            with self.subTest(summary=summary):
                self.assertEqual(point_in_time_cue(summary), cue)

    def test_dated_decisions_bare_generations_and_unprefixed_versions_are_not_snapshots(self) -> None:
        for summary in (
            "Decided 2026-10-27: OMH coexists with Hermes 0.22.5 delegation backends.",
            "v1 scope is only side-by-side English and Korean.",
            "The public API v1 endpoint is frozen.",
            "khope (2026-11-03): Kami decides timing on its own.",
            "Releases are tagged from the release branch.",
            "The schema is project_memory_record/v2.",
            "Assets live under dev.rlaope.nanran/papers.",
        ):
            with self.subTest(summary=summary):
                self.assertEqual(point_in_time_cue(summary), "")


class SnapshotRetentionTests(_StoreCase):
    def test_a_snapshot_capture_is_standard_with_the_90_day_review_deadline(self) -> None:
        result = self.capture(summary="As of 2026-10-30 (v0.1.7), nanran has light and dark themes driven by CSS variables.")
        self.assertEqual(result["status"], "remembered", result)
        self.assertEqual((result["retention_class"], result["point_in_time"]), ("standard", "as_of_date"))
        record = self.stored(result["record_id"])
        self.assertEqual(record["retention"]["class"], "standard")
        approved = datetime.fromisoformat(record["approved_at"].replace("Z", "+00:00"))
        due = datetime.fromisoformat(record["staleness"]["review_due_at"].replace("Z", "+00:00"))
        self.assertEqual(due - approved, timedelta(days=90))
        self.assertEqual(record["ttl"]["expires_at"], "", "standard keeps no expiry for a fact; it ages out of recall, not out of the store")
        snapshot = read_record_store_snapshot((self.store,))
        for days, served in ((89, True), (91, False)):
            with self.subTest(days=days):
                picked = select_prefetch_records(
                    snapshot, "nanran themes", allowed_scopes=[GLOBAL], required_scope_kinds=(), now=approved + timedelta(days=days),
                )
                self.assertEqual(result["record_id"] in [item["record_id"] for item in picked.pack["included_records"]], served)
                if not served:
                    self.assertEqual(picked.exclusion_reason_counts, {"stale_review_required": 1})

    def test_a_versioned_save_through_omh_remember_is_standard(self) -> None:
        result = self.save(summary="nanran v0.1.13 added an easy-explanation translation mode.")
        self.assertEqual(result["status"], "remembered", result)
        self.assertEqual((result["retention_class"], result["point_in_time"]), ("standard", "version"))
        self.assertEqual(self.stored(result["record_id"])["retention"]["class"], "standard")

    def test_a_lasting_fact_stays_durable_with_no_deadline_and_no_new_fields(self) -> None:
        for summary in (
            "Decided 2026-10-27: OMH coexists with Hermes 0.22.5 delegation backends.",
            "v1 scope is only side-by-side English and Korean.",
        ):
            with self.subTest(summary=summary):
                result = self.capture(summary=summary)
                self.assertEqual(result["status"], "remembered", result)
                self.assertNotIn("point_in_time", result)
                self.assertNotIn("retention_class", result)
                record = self.stored(result["record_id"])
                self.assertEqual(record["retention"]["class"], "durable")
                self.assertEqual(record["staleness"]["review_due_at"], "")

    def test_a_class_the_captor_chose_is_kept(self) -> None:
        result = self.capture(summary="As of 2026-10-30, the license is Apache-2.0.", retention_class="durable")
        self.assertEqual(result["status"], "remembered", result)
        self.assertNotIn("point_in_time", result)
        self.assertEqual(self.stored(result["record_id"])["retention"]["class"], "durable")

    def test_a_correction_that_restates_a_snapshot_ages_like_one(self) -> None:
        first = self.save(summary="nanran's sidebar lists every paper in one flat list.")
        self.assertEqual(self.stored(first["record_id"])["retention"]["class"], "durable")
        corrected = self.save(
            summary="As of 2026-11-01 (v0.1.15), nanran's sidebar groups papers into folders.", replaces=first["record_id"],
        )
        self.assertEqual(corrected["status"], "corrected", corrected)
        self.assertEqual(self.stored(corrected["record_id"])["retention"]["class"], "standard")

    def test_a_correction_without_a_snapshot_keeps_the_durable_class(self) -> None:
        first = self.save(summary="nanran's sidebar lists every paper in one flat list.")
        corrected = self.save(summary="nanran's sidebar groups papers into folders.", replaces=first["record_id"])
        self.assertEqual(corrected["status"], "corrected", corrected)
        self.assertEqual(self.stored(corrected["record_id"])["retention"]["class"], "durable")


class ScopeHintTests(_StoreCase):
    def checkout(self, name: str) -> Path:
        """A repository root on this machine, outside the session's directory."""
        root = Path(self.enterContext(TemporaryDirectory())).resolve() / name
        (root / ".git").mkdir(parents=True)
        return root

    def test_a_hosted_repository_named_outside_a_repository_gets_a_hint_and_stays_user_global(self) -> None:
        result = self.save(summary="Widget releases are published at github.com/acme/widget-api by the release bot.")
        self.assertEqual(result["status"], "remembered", result)
        hint = result["scope_hint"]
        self.assertEqual((hint["projects"], hint["saved_scope"], hint["reason"]), (["widget-api"], "user-global", "names_project_outside_repository"))
        self.assertIn("retire this record", hint["next_action"])
        self.assertEqual(self.stored(result["record_id"])["scope"], {"kind": "user-global", "ref": "default"}, "never moved")

    def test_a_project_known_from_a_held_record_is_named_by_word_or_subject(self) -> None:
        repo = self.checkout("nanran")
        first = self.save(summary=f"nanran is a standalone paper reader kept at {repo}.")
        self.assertEqual(first["scope_hint"]["projects"], ["nanran"], first)
        by_word = self.save(summary="nanran UI error messages are written in polite casual Korean.")
        self.assertEqual(by_word["scope_hint"]["projects"], ["nanran"], by_word)
        by_particle = self.save(summary="Nanran은 논문을 좌우로 나란히 보여 준다.")
        self.assertEqual(by_particle["scope_hint"]["projects"], ["nanran"], by_particle)
        by_subject = self.save(summary="Papers are grouped into folders saved in papers/folders.json.", subject="nanran-folders")
        self.assertEqual(by_subject["scope_hint"]["projects"], ["nanran"], by_subject)
        by_inner_path = self.save(summary=f"The paper styles live in {repo / 'src'}.")
        self.assertEqual(by_inner_path["scope_hint"]["projects"], ["nanran"], by_inner_path)

    def test_no_hint_where_nothing_names_a_known_project(self) -> None:
        repo = self.checkout("nanran")
        self.save(summary=f"nanran is a standalone paper reader kept at {repo}.")
        plain_dir = Path(self.enterContext(TemporaryDirectory())).resolve() / "kami-refs"
        plain_dir.mkdir()
        for summary in (
            "Prefers terse replies.",
            "nanranx is a different tool entirely.",
            "The pre-nanran reader was a browser extension.",
            f"Kami reference images live in {plain_dir}.",
        ):
            with self.subTest(summary=summary):
                result = self.save(summary=summary)
                self.assertEqual(result["status"], "remembered", result)
                self.assertNotIn("scope_hint", result)

    def test_no_hint_inside_a_repository_or_when_the_captor_chose_user_scope(self) -> None:
        repo = self.checkout("nanran")
        self.save(summary=f"nanran is a standalone paper reader kept at {repo}.")
        inside = self.capture(cwd=self.root, summary="nanran builds with the universal macOS target.")
        self.assertEqual(inside["status"], "remembered", inside)
        self.assertNotIn("scope_hint", inside)
        self.assertEqual(self.stored(inside["record_id"])["scope"]["kind"], "project")
        chosen = self.capture(summary="nanran releases are ad-hoc signed.", scope="user")
        self.assertEqual(chosen["status"], "remembered", chosen)
        self.assertNotIn("scope_hint", chosen)


class SimilarWordingCollapseTests(unittest.TestCase):
    OLD = "As of 2026-10-30 the nanran sidebar keeps papers in one flat list"
    NEW = "As of 2026-11-01 the nanran sidebar keeps papers in one folder list"

    def setUp(self) -> None:
        self.assertGreaterEqual(_wording_pct(self.OLD, self.NEW), SIMILAR_WORDING_JACCARD_PCT)

    def pair(
        self, old: dict | None = None, new: dict | None = None, *, scope: dict[str, str] = GLOBAL,
        summaries: tuple[str, str] | None = None,
    ) -> list:
        old_summary, new_summary = summaries or (self.OLD, self.NEW)
        return [
            reviewed("mem-old", scope=scope, summary=old_summary, approved_at="2026-10-30T00:00:00Z", **{"tags": ["nanran"], **(old or {})}),
            reviewed("mem-new", scope=scope, summary=new_summary, approved_at="2026-11-01T00:00:00Z", **{"tags": ["nanran"], **(new or {})}),
        ]

    def test_an_older_record_that_is_not_a_snapshot_is_never_dropped(self) -> None:
        cases = {
            "two facts differing in one word": ("Deploy notes alpha cover the nanran release checklist.",
                                                "Deploy notes bravo cover the nanran release checklist."),
            "a lasting fact before a newer snapshot": ("The nanran sidebar keeps papers in one flat list",
                                                       "As of 2026-11-01 the nanran sidebar keeps papers in one flat list"),
        }
        for name, summaries in cases.items():
            with self.subTest(name):
                self.assertGreaterEqual(_wording_pct(*summaries), SIMILAR_WORDING_JACCARD_PCT)
                for scope, lens in ((GLOBAL, LENS), (PROJECT, [PROJECT])):
                    result = selection(self.pair(scope=scope, summaries=summaries), "nanran sidebar papers deploy notes", allowed_scopes=lens)
                    self.assertEqual(sorted(included_ids(result)), ["mem-new", "mem-old"])

    def test_the_newest_restatement_is_served_and_the_older_names_it(self) -> None:
        result = selection(self.pair(), "nanran sidebar papers", allowed_scopes=LENS)
        self.assertEqual(included_ids(result), ["mem-new"])
        cut = _reasons(result)["mem-old"]
        self.assertEqual((cut["reason"], cut["superseded_by"]), ("superseded_by_wording", "mem-new"))
        self.assertEqual(result.exclusion_reason_counts, {"superseded_by_wording": 1})

    def test_a_project_scope_is_the_topic_without_tags(self) -> None:
        result = selection(self.pair({"tags": []}, {"tags": []}, scope=PROJECT), "nanran sidebar papers")
        self.assertEqual(included_ids(result), ["mem-new"])

    def test_one_side_declaring_a_subject_still_collapses(self) -> None:
        result = selection(self.pair(new={"subject": "nanran-sidebar"}), "nanran sidebar papers", allowed_scopes=LENS)
        self.assertEqual(included_ids(result), ["mem-new"])

    def test_two_similar_facts_that_can_both_be_true_are_both_served(self) -> None:
        cases = {
            "different subjects": self.pair({"subject": "nanran-sidebar"}, {"subject": "paprv-sidebar"}),
            "no shared topic tag": self.pair({"tags": ["nanran"]}, {"tags": ["paprv"]}),
            "only a provenance tag": self.pair({"tags": ["hermes-demotion"]}, {"tags": ["hermes-demotion"]}),
            "no tags in a shared scope": self.pair({"tags": []}, {"tags": []}),
        }
        for name, pairs in cases.items():
            with self.subTest(name):
                result = selection(pairs, "nanran sidebar papers", allowed_scopes=LENS)
                self.assertEqual(sorted(included_ids(result)), ["mem-new", "mem-old"])
                self.assertNotIn("superseded_by_wording", result.exclusion_reason_counts)

    def test_complementary_facts_on_one_topic_stay_below_the_threshold(self) -> None:
        first, second = "Staging deploys run canary batches before promotion", "Staging deploys wait for a green nightly run"
        self.assertLess(_wording_pct(first, second), SIMILAR_WORDING_JACCARD_PCT)
        pairs = [
            reviewed("mem-a", scope=GLOBAL, summary=first, tags=["staging"], approved_at="2026-10-30T00:00:00Z"),
            reviewed("mem-b", scope=GLOBAL, summary=second, tags=["staging"], approved_at="2026-11-01T00:00:00Z"),
        ]
        result = selection(pairs, "staging deploys", allowed_scopes=LENS)
        self.assertEqual(sorted(included_ids(result)), ["mem-a", "mem-b"])

    def test_different_scopes_never_collapse(self) -> None:
        pairs = [
            reviewed("mem-old", scope=GLOBAL, summary=self.OLD, tags=["nanran"], approved_at="2026-10-30T00:00:00Z"),
            reviewed("mem-new", scope=PROJECT, summary=self.NEW, tags=["nanran"], approved_at="2026-11-01T00:00:00Z"),
        ]
        result = selection(pairs, "nanran sidebar papers", allowed_scopes=LENS)
        self.assertEqual(sorted(included_ids(result)), ["mem-new", "mem-old"])

    def test_a_pinned_older_record_stays(self) -> None:
        result = selection(self.pair(), "nanran sidebar papers", allowed_scopes=LENS, pins={"mem-old"})
        self.assertEqual(sorted(included_ids(result)), ["mem-new", "mem-old"])

    def test_an_older_record_whose_restatement_the_query_missed_is_served_as_before(self) -> None:
        result = selection(self.pair(), "flat", allowed_scopes=LENS)
        self.assertEqual(included_ids(result), ["mem-old"])
        self.assertEqual(_reasons(result)["mem-new"]["reason"], "no_query_overlap")

    def test_the_rule_is_part_of_the_recall_configuration(self) -> None:
        rule = effective_recall_configuration()["similar_wording_collapse"]
        self.assertEqual(rule["jaccard_pct"], SIMILAR_WORDING_JACCARD_PCT)


if __name__ == "__main__":
    unittest.main()
