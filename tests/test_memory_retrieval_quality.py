"""Recall picks the right record more often, deterministically, with no model.

Three changes are pinned here:

- relevance is query-term coverage, then BM25F term frequency and length with
  no idf, over the eligible candidates (summary, tags, record type), with
  light English suffix stemming applied alike to the query and the records,
  CJK and accented text left as they were, and length counted in whole
  multiples of the average so near-average ties still go to recency;
- capture names a held record in the same confinement whose wording is
  similar (token Jaccard) or that already declares the same subject, and still
  saves the new fact -- a hint, never a refusal;
- a model-declared `subject` slug makes recall serve only the newest approved
  record per scope and subject, and names the others `superseded_by_subject`.

The reviews of #2091 added: query function words that never add coverage,
stemmed-only matches that cannot suppress the active-tier fallback, a record
type that needs a content hit, temporal relevance bands, a subject collapse over every
non-retired record, hints filtered through the session lens with a computed
recall status, and a `correct` that only supersedes into a record that can
stand in. Each has a test below that a mutation of it fails.

The store-common floor came after: a query term more than half of five or
more servable, distinct candidates hold never makes a record match alone,
unless the record carries it as a tag, and a query whose every term is common
keeps them.

The recall suite (`tests/test_memory_retrieval_suite.py`) runs the corpus cases
these changes were measured on; this file pins the parts underneath them.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import random
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _credential_fixtures import AWS_ACCESS_KEY_ID, AWS_TEMPORARY_ACCESS_KEY_ID
from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh.memory_session_lens import SURFACE_OPERATOR_CONSOLE  # noqa: E402
from omh.coding_delegation import build_coding_delegation_payload, coding_delegation_record_payload
from omh.paths import OmhPaths
from omh.plugin_bundle.omh import memory_admission
from omh.plugin_bundle.omh.memory_admission import (
    SIMILAR_WORDING_JACCARD_PCT,
    _records_in_confinement,
    capture_project_memory_candidate,
    project_memory_review_revision,
)
from omh.plugin_bundle.omh.memory_governance import contains_credential_like_material
from omh.plugin_bundle.omh.memory_prefetch_receipt import MAX_SUBJECT_SUPERSEDED, build_prefetch_receipt, validate_prefetch_receipt
from omh.plugin_bundle.omh.memory_records import prepare_prefetch_records, read_record_store_snapshot
from omh.plugin_bundle.omh import memory_recall_selector as selector_module
from omh.plugin_bundle.omh.memory_recall_support import (
    _QUERY_KOREAN_SUFFIXES,
    _attach_recall_ranking,
    _cut_cjk_function_words,
    _kept_listed_words,
    _korean_query_stem,
    _record_relevance_fields,
    _memory_index_terms,
    _memory_query_split,
    _memory_query_tokens,
    _memory_relevance,
    _memory_relevance_scores,
    _memory_token_list,
    _memory_tokens,
    _stem_memory_token,
    _term_contributions,
    memory_summary_terms,
    newest_record,
    normalize_memory_subject,
    record_subject,
)
from omh.plugin_bundle.omh.memory_store_io import validate_project_memory_record
from omh.plugin_bundle.omh.tools import memory_tool
from omh.runtime_artifacts import create_prepared_coding_delegation_run, validate_coding_delegation_record, write_coding_delegation
from omh.workflows.memory import build_project_memory_recall_pack, memory_recall_pack_for_handoff, validate_project_memory_recall_pack
from omh.workflows.memory_evaluation import PARITY_PROJECT_IDENTITY, _seed_retrieval_store
from omh.workflows.memory_retrieval_fixtures import (
    FIXTURE_CLOCK,
    FIXTURE_PROJECT_IDENTITY,
    RETRIEVAL_CASES,
    _case,
    _record as _spec,
    materialize_fixture_record,
)
from test_memory_lifecycle_tool import _Home, start

_YOUNG = "2030-12-20T00:00:00Z"
_AGING = "2030-10-01T00:00:00Z"
_PAST = "2030-11-15T00:00:00Z"


def _record(record_id: str, summary: str, *, tags: tuple[str, ...] = (), record_type: str = "fact") -> dict[str, object]:
    return {"record_id": record_id, "summary": summary, "tags": list(tags), "record_type": record_type}


def _scored(records: list[dict[str, object]], query: str) -> dict[str, int]:
    return dict(zip((str(record["record_id"]) for record in records), _memory_relevance_scores(records, query)))


class Bm25RelevanceTests(unittest.TestCase):
    # These two replaced tests that pinned idf. With idf inside a coverage
    # band, the review's blind probes ranked a stray word one record held
    # ("어케 해야 할지 모르면 ...") above every deploy record for "배포 어케 해":
    # both covered one term, and the stray word was the rarer.
    def test_rarity_carries_no_weight_within_one_coverage(self) -> None:
        records = [
            _record("a", "alpha one"),
            _record("b", "alpha two"),
            _record("c", "alpha three"),
            _record("d", "zeta four"),
        ]
        relevance = _memory_relevance(records, "alpha zeta")
        self.assertEqual(relevance.coverage, [2, 2, 2, 2])
        self.assertEqual(len(set(relevance.scores)), 1, relevance.scores)

    def test_how_many_records_hold_a_term_never_moves_its_weight(self) -> None:
        target = _record("t", "alpha kiwi")
        filler = [_record("x", "plum pear")]
        holders = [_record(f"h{index}", "alpha lime") for index in range(4)]
        weights = [
            _scored([target, *filler, *holders[:count]], "alpha")["t"]
            for count in range(len(holders) + 1)
        ]
        self.assertEqual(len(set(weights)), 1, weights)

    def test_a_tag_hit_outweighs_a_summary_hit_and_both_outweigh_either(self) -> None:
        records = [
            _record("summary_only", "deploy happens nightly", tags=("ops",)),
            _record("tag_only", "release happens nightly", tags=("deploy",)),
            _record("both", "deploy happens hourly", tags=("deploy",)),
            _record("neither", "lunch happens daily", tags=("food",)),
        ]
        scores = _scored(records, "deploy")
        self.assertGreater(scores["both"], scores["tag_only"])
        self.assertGreater(scores["tag_only"], scores["summary_only"])
        self.assertEqual(scores["neither"], 0)

    def test_stemming_is_the_same_for_the_query_and_the_record(self) -> None:
        for forms in (
            ("deploy", "deploys", "deployed", "deploying", "deployment", "deployments"),
            ("release", "releases", "released", "releasing"),
            ("migration", "migrations", "migrate", "migrated"),
            ("cache", "caches", "caching"),
            ("run", "runs", "running"),
            ("reply", "replies"),
            ("add", "added"),
        ):
            with self.subTest(forms=forms):
                self.assertEqual(len({_stem_memory_token(form) for form in forms}), 1)
        self.assertEqual(_memory_index_terms("Deploying deployments"), ["deploy", "deploy"])
        records = [_record("noun", "deployment runs nightly"), _record("verb", "deploys run nightly")]
        by_noun, by_verb = _scored(records, "deploying"), _scored(list(reversed(records)), "deploying")
        self.assertEqual(by_noun["noun"], by_verb["verb"])
        self.assertGreater(by_noun["noun"], 0)

    def test_short_and_unrelated_words_keep_their_shape(self) -> None:
        for word in ("string", "thing", "apply", "reply", "early", "only", "region", "status", "this", "used", "add"):
            with self.subTest(word=word):
                self.assertEqual(_stem_memory_token(word), word)

    def test_cjk_accented_numeric_and_compound_tokens_are_never_stemmed(self) -> None:
        for text in ("배포는 release 브랜치에서만", "部署流程需要", "デプロイ手順は", "préférence déploiement"):
            with self.subTest(text=text):
                non_ascii = [token for token in _memory_token_list(text) if not token.isascii()]
                self.assertTrue(non_ascii)
                self.assertEqual([_stem_memory_token(token) for token in non_ascii], non_ascii)
        for token in ("on-call", "src/plugins", "py312", "x86_64", "ci"):
            with self.subTest(token=token):
                self.assertEqual(_stem_memory_token(token), token)
        # The unstemmed token set is what it was before relevance changed.
        self.assertEqual(_memory_tokens("배포는"), {"배포는", "배포", "포는"})
        self.assertEqual(_memory_token_list("배포"), ["배포"])

    def test_cjk_queries_still_match_through_bigrams(self) -> None:
        records = [_record("branch", "배포는 release 브랜치에서만 한다"), _record("brand", "브랜드 색상은 파란색이다")]
        scores = _scored(records, "배포 브랜치가 뭐였지?")
        self.assertGreater(scores["branch"], scores["brand"])
        self.assertGreater(scores["brand"], 0)

    def test_ties_are_exact_and_independent_of_store_order(self) -> None:
        records = [
            _record("first", "Backups run every night", tags=("backup",)),
            _record("second", "Backups run each night", tags=("backup",)),
            _record("third", "Queue workers retry failed jobs twice", tags=("queue",)),
        ]
        baseline = _scored(records, "backups night")
        self.assertEqual(baseline["first"], baseline["second"])
        shuffled = list(records)
        random.Random(7).shuffle(shuffled)
        self.assertEqual(_scored(shuffled, "backups night"), baseline)

    def test_scores_do_not_depend_on_the_hash_seed(self) -> None:
        records = [_record(f"r{index}", f"alpha bravo charlie delta{index} echo{index % 3}", tags=("t",)) for index in range(6)]
        code = (
            "import json, sys\n"
            "from omh.plugin_bundle.omh.memory_recall_support import _memory_relevance_scores\n"
            "print(json.dumps(_memory_relevance_scores(json.loads(sys.argv[1]), sys.argv[2])))\n"
        )
        outputs = set()
        for seed in ("0", "1", "12345"):
            completed = subprocess.run(
                [sys.executable, "-P", "-c", code, json.dumps(records), "echo1 delta3 bravo charlie t"],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONHASHSEED": seed},
                check=True,
            )
            outputs.add(completed.stdout.strip())
        self.assertEqual(len(outputs), 1, outputs)

    def test_a_record_twice_the_average_length_is_discounted_and_near_average_records_tie(self) -> None:
        long_summary = "node " + " ".join(f"word{index}" for index in range(24))
        records = [
            _record("long", long_summary),
            _record("short", "node pinned in nvmrc"),
            _record("five", "prettier formats typescript files"),
            _record("six", "pull requests need review"),
        ]
        scores = _scored(records, "node")
        self.assertGreater(scores["short"], scores["long"])
        near = [_record("five_words", "queue workers retry failed jobs"), _record("six_words", "queue workers log every retry attempt")]
        near_scores = _scored(near, "queue workers retry")
        self.assertEqual(near_scores["five_words"], near_scores["six_words"])

    def test_no_query_and_unindexable_queries_score_every_record_one(self) -> None:
        records = [_record("a", "alpha"), _record("b", "bravo")]
        self.assertEqual(_memory_relevance_scores(records, ""), [1, 1])
        self.assertEqual(_memory_relevance_scores(records, "🙂 🙂"), [1, 1])
        self.assertEqual(_memory_relevance_scores(records, "zulu"), [0, 0])
        self.assertEqual(_memory_relevance_scores([], "alpha"), [])

    def test_any_match_scores_at_least_one(self) -> None:
        # One summary hit in a record about 9,000 times the average length
        # contributes 269 millionths, which rounds to 0 thousandths; only the
        # floor keeps it a match.
        records = [_record(f"r{index}", "zz") for index in range(9999)]
        records.append(_record("long", "common " + " ".join(["filler"] * 99999)))
        self.assertEqual(_memory_relevance(records, "common").scores[-1], 1)

    def test_per_term_contributions_are_integers_so_their_sum_ignores_term_order(self) -> None:
        records = [_record("a", "alpha bravo charlie delta", tags=("echo",)), _record("b", "alpha foxtrot", tags=("golf",))]
        documents = [_record_relevance_fields(record) for record in records]
        terms = ["alpha", "bravo", "echo", "foxtrot", "golf"]
        for document in documents:
            forward = _term_contributions(document, terms, norm=1.0)
            self.assertTrue(forward and all(isinstance(value, int) for value in forward))
            for seed in range(5):
                permuted = list(terms)
                random.Random(seed).shuffle(permuted)
                shuffled = _term_contributions(document, permuted, norm=1.0)
                self.assertEqual(sorted(shuffled), sorted(forward))
                self.assertEqual(sum(shuffled), sum(forward))


class SubjectShapeTests(unittest.TestCase):
    def test_the_closed_shape_is_accepted_and_nothing_else_is_rewritten(self) -> None:
        for value in ("deploy-branch", "reply-language", "a", "0", "x" * 48, "a-1-b"):
            with self.subTest(value=value):
                self.assertEqual(normalize_memory_subject(value), value)
        self.assertEqual(normalize_memory_subject(""), "")
        self.assertEqual(normalize_memory_subject(None), "")
        for value in ("Deploy-Branch", "deploy_branch", "-deploy", "deploy branch", " deploy", "x" * 49, "배포", 5, ["deploy"]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_memory_subject(value)

    def test_a_malformed_stored_subject_reads_as_none(self) -> None:
        self.assertEqual(record_subject({"subject": "deploy-branch"}), "deploy-branch")
        for value in ("Deploy", "", None, 7, "x" * 49):
            with self.subTest(value=value):
                self.assertEqual(record_subject({"subject": value}), "")


class SubjectSelectionTests(unittest.TestCase):
    def _case(self, case_id: str) -> dict[str, object]:
        return next(case for case in RETRIEVAL_CASES if case["case_id"] == case_id)

    def _prepare(self, case: dict[str, object], query: str | None = None):
        root = Path(self.enterContext(TemporaryDirectory()))
        paths = OmhPaths(root / ".omh", root / "hermes")
        _seed_retrieval_store(paths, case)
        snapshot = read_record_store_snapshot((paths.omh_home,))
        allowed = [{"kind": "project", "ref": FIXTURE_PROJECT_IDENTITY}, {"kind": "user-global", "ref": "default"}]
        prepared = prepare_prefetch_records(
            snapshot, str(case["query"]) if query is None else query, allowed_scopes=allowed, session_id="s", now=FIXTURE_CLOCK
        )
        return prepared, build_prefetch_receipt(prepared, session_id="s", home_digests=snapshot.home_digests)

    def test_only_the_newest_value_is_served_and_the_receipt_names_the_one_it_replaced(self) -> None:
        prepared, receipt = self._prepare(self._case("same_subject_serves_only_the_newest_value"))
        pack = prepared.selection.pack
        self.assertEqual([item["record_id"] for item in pack["included_records"]], ["mem_u02_main"])
        self.assertEqual(pack["included_records"][0]["subject"], "deploy-branch")
        [exclusion] = [item for item in pack["excluded_records"] if item["reason"] == "superseded_by_subject"]
        self.assertEqual(
            (exclusion["record_id"], exclusion["superseded_by"], exclusion["subject"]),
            ("mem_u01_release", "mem_u02_main", "deploy-branch"),
        )
        self.assertEqual(receipt["selection"]["subject_superseded"], [{"record_id": "mem_u01_release", "superseded_by": "mem_u02_main"}])
        self.assertEqual(receipt["selection"]["exclusion_reason_counts"].get("superseded_by_subject"), 1)
        self.assertEqual(validate_prefetch_receipt(receipt), [])

    def test_the_old_wording_never_brings_the_old_value_back(self) -> None:
        prepared, _ = self._prepare(self._case("same_subject_old_wording_never_brings_the_old_value_back"))
        pack = prepared.selection.pack
        self.assertEqual([item["record_id"] for item in pack["included_records"]], ["mem_u05_concise", "mem_u04_english"])
        # The current value shares no query word, so it took no score from the old one.
        self.assertEqual(pack["included_records"][1]["score"], 1)
        self.assertEqual(pack["query_fallback"]["reason"], "no_query_overlap")

    def test_without_a_query_the_old_value_still_stays_out(self) -> None:
        prepared, _ = self._prepare(self._case("same_subject_serves_only_the_newest_value"), query="")
        self.assertEqual([item["record_id"] for item in prepared.selection.pack["included_records"]], ["mem_u02_main"])

    def test_different_scopes_and_different_subjects_never_collapse(self) -> None:
        for case_id, expected in (
            ("same_subject_in_different_scopes_stays_separate", ["mem_w02_global", "mem_w01_repo"]),
            ("different_subjects_never_collapse", ["mem_v01_branch", "mem_v02_window"]),
        ):
            with self.subTest(case_id=case_id):
                prepared, receipt = self._prepare(self._case(case_id))
                self.assertEqual([item["record_id"] for item in prepared.selection.pack["included_records"]], expected)
                self.assertEqual(receipt["selection"]["subject_superseded"], [])

    def test_a_receipt_with_a_malformed_subject_list_is_refused(self) -> None:
        _, receipt = self._prepare(self._case("same_subject_serves_only_the_newest_value"))
        receipt["selection"]["subject_superseded"] = [{"record_id": "mem_u01_release"}]
        self.assertIn("selection.subject_superseded", validate_prefetch_receipt(receipt))


class CaptureHintTests(_Home):
    """Admission's two hints, read from the same confinement the duplicate check reads."""

    def _admit(self, summary: str, **capture) -> dict:
        defaults = {"scope_kind": "project", "scope_ref": self.identity, "source": "hermes_model", "retention_class": "durable", "on_duplicate": "skip"}
        return capture_project_memory_candidate(self.store, summary, **{**defaults, **capture})

    def test_similar_wording_at_the_threshold_is_named_and_the_capture_still_goes_through(self) -> None:
        self.assertEqual(SIMILAR_WORDING_JACCARD_PCT, 60)
        held = self._admit("kiwi plum pear lime")["record"]["record_id"]
        at_threshold = self._admit("kiwi plum pear sage")  # 3 shared of 5 distinct terms: 60%
        self.assertTrue(at_threshold["auto_approved"], at_threshold)
        self.assertEqual(at_threshold["similar_record_id"], held)
        self.assertEqual(at_threshold["similar_wording_pct"], 60)
        self.assertEqual(at_threshold["similar_summary"], "kiwi plum pear lime")

    def test_wording_just_under_the_threshold_is_not_named(self) -> None:
        self._admit("fig kiwi plum pear lime")
        below = self._admit("fig kiwi plum pear sage mint")  # 4 shared of 7 distinct terms: 57%
        self.assertTrue(below["auto_approved"], below)
        self.assertNotIn("similar_record_id", below)

    def test_the_threshold_comment_quotes_measured_ratios(self) -> None:
        def jaccard_pct(left: str, right: str) -> int:
            a, b = memory_summary_terms(left), memory_summary_terms(right)
            return len(a & b) * 100 // len(a | b)

        self.assertEqual(jaccard_pct("The staging database runs postgres 16", "The staging database runs postgres 17"), 71)
        self.assertEqual(
            jaccard_pct("Staging deploys run canary batches before promotion", "Staging deploys wait for a green nightly run"), 27
        )

    def test_a_changed_value_in_a_repeated_sentence_is_named(self) -> None:
        held = self._admit("The staging database runs postgres 16")["record"]["record_id"]
        newer = self._admit("The staging database runs postgres 17")
        self.assertEqual(newer["similar_record_id"], held)

    def test_similar_wording_in_another_scope_is_never_named(self) -> None:
        self._admit("kiwi plum pear lime", scope_kind="user-global", scope_ref="default")
        elsewhere = self._admit("kiwi plum pear sage")
        self.assertNotIn("similar_record_id", elsewhere)

    def test_the_record_a_correction_replaces_is_never_named(self) -> None:
        held = self._admit("kiwi plum pear lime", subject="fruit-list")["record"]
        correction = self._admit(
            "kiwi plum pear sage",
            subject="fruit-list",
            derived_from=[held["record_id"]],
            correction_of=held["record_id"],
            correction_revision=held["revision"],
        )
        self.assertEqual(correction["supersession"]["state"], "superseded", correction)
        self.assertNotIn("similar_record_id", correction)
        self.assertNotIn("subject_held_by", correction)

    def test_an_exact_duplicate_is_already_remembered_not_a_hint(self) -> None:
        held = self._admit("kiwi plum pear lime")["record"]["record_id"]
        again = self._admit("Kiwi plum  pear lime")
        self.assertFalse(again["captured"])
        self.assertEqual(again["duplicate_of"], held)
        self.assertNotIn("similar_record_id", again)

    def test_same_subject_names_the_holder_and_both_records_stay(self) -> None:
        held = self._admit("Deploys go from the release branch", subject="deploy-branch")["record"]["record_id"]
        newer = self._admit("Deploys go from main now", subject="deploy-branch")
        self.assertTrue(newer["auto_approved"], newer)
        self.assertEqual(newer["subject_held_by"], held)
        self.assertEqual(newer["record"]["subject"], "deploy-branch")
        self.assertEqual(newer["candidate"]["subject"], "deploy-branch")
        # A hint, not a supersession: the older record is still in records/.
        self.assertTrue(self.record_path(held).is_file())
        self.assertNotIn("superseded_by", self.read_record(held))

    def test_same_subject_in_another_scope_is_not_a_holder(self) -> None:
        self._admit("Reply in English", subject="reply-language", scope_kind="user-global", scope_ref="default")
        project = self._admit("Reply in Korean in this repository", subject="reply-language")
        self.assertNotIn("subject_held_by", project)

    def test_the_review_card_shows_and_binds_the_subject(self) -> None:
        pending = self._admit("Deploys go from main now", subject="deploy-branch", force_review=True)
        candidate = pending["candidate"]
        self.assertNotEqual(project_memory_review_revision(candidate), project_memory_review_revision({**candidate, "subject": "deploy-window"}))

    def test_a_malformed_subject_is_refused_before_anything_is_written(self) -> None:
        before = self.store_bytes()
        with self.assertRaises(ValueError):
            self._admit("Deploys go from main now", subject="Deploy Branch")
        self.assertEqual(self.store_bytes(), before)


class ToolSubjectAndHintTests(_Home):
    def test_capture_refuses_a_malformed_subject_and_writes_nothing(self) -> None:
        before = self.store_bytes()
        for value in ("Deploy-Branch", "deploy_branch", "x" * 49, 3):
            with self.subTest(value=value):
                result = self.call("capture", summary="Deploys go from main", subject=value)
                self.assertEqual((result["status"], result["reason"]), ("refused", "invalid_subject"), result)
        self.assertEqual(self.store_bytes(), before)

    def test_same_subject_capture_hints_correct_and_recall_serves_only_the_newest(self) -> None:
        old = self.capture("Deploys go from the release branch", subject="deploy-branch")
        # Approval stamps whole seconds; an older stamp makes "newest" a fact
        # rather than a record-id tie-break between two captures in one second.
        self.edit_record(old, approved_at="2026-01-01T00:00:00Z")
        result = self.call("capture", summary="Deploys go from main now", subject="deploy-branch")
        self.assertEqual(result["status"], "remembered", result)
        self.assertEqual(result["subject_held_by"], old)
        self.assertIn(f"action='correct' with record_id='{old}'", result["next_action"])
        recall = self.call("recall", query="which branch do deploys go from")
        self.assertEqual([row["record_id"] for row in recall["records"]], [result["record_id"]])
        self.assertEqual(recall["records"][0]["subject"], "deploy-branch")

    def test_the_suggested_correct_moves_the_old_record_to_history(self) -> None:
        old = self.capture("The staging database runs postgres 16")
        result = self.call("capture", summary="The staging database runs postgres 17")
        self.assertEqual((result["status"], result["similar_record_id"]), ("remembered", old), result)
        self.assertIn("similar wording", result["next_action"])
        new = result["record_id"]
        corrected = self.call("correct", record_id=old, summary="The staging database runs postgres 17")
        self.assertEqual(
            (corrected["status"], corrected["record_id"], corrected["superseded_record_id"], corrected["replacement"]),
            ("corrected", new, old, "already_held"),
            corrected,
        )
        self.assertFalse(self.record_path(old).exists())
        history = json.loads((self.memory / "history" / f"{old}.r1.json").read_text(encoding="utf-8"))
        self.assertEqual(history["superseded_by"]["id"], new)
        self.assertEqual(self.recalled("staging database postgres"), [new])

    def test_correct_keeps_the_old_subject_unless_a_new_one_is_given(self) -> None:
        old = self.capture("Deploys go from the release branch", subject="deploy-branch")
        kept = self.call("correct", record_id=old, summary="Deploys go from main")
        self.assertEqual(kept["status"], "corrected", kept)
        self.assertEqual(self.read_record(kept["record_id"])["subject"], "deploy-branch")
        renamed = self.call("correct", record_id=kept["record_id"], summary="Deploys go from main only", subject="deploy-source")
        self.assertEqual(self.read_record(renamed["record_id"])["subject"], "deploy-source")
        refused = self.call("correct", record_id=renamed["record_id"], summary="Deploys go from trunk", subject="Deploy Source")
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "invalid_subject"))


def _pack(
    test: unittest.TestCase,
    *specs: dict[str, object],
    query: str,
    pins: tuple[str, ...] = (),
    include_stale: bool = False,
    observed: str | None = None,
) -> dict:
    """The handoff recall pack for a store seeded with exactly these record specs."""
    root = Path(test.enterContext(TemporaryDirectory()))
    paths = OmhPaths(root / ".omh", root / "hermes")
    _seed_retrieval_store(paths, _case("probe", "probe", records=tuple(specs), query=query, pins=pins))
    return build_project_memory_recall_pack(paths, query, now=FIXTURE_CLOCK, include_stale=include_stale, observed=observed)


def _ids(pack: dict) -> list[str]:
    return [str(item["record_id"]) for item in pack["included_records"]]


def _reasons(pack: dict) -> dict[str, str]:
    return {str(item["record_id"]): str(item["reason"]) for item in pack["excluded_records"]}


class QueryFunctionWordTests(unittest.TestCase):
    def test_question_words_neither_score_nor_count_as_overlap(self) -> None:
        self.assertEqual(_memory_query_tokens("how do we deploy?"), ["deploy"])
        self.assertNotIn("누가", _memory_query_tokens("배포 승인은 누가 해?"))
        self.assertEqual(_memory_query_tokens("배포는 어떻게 해?"), ["배포"])
        records = [_record("deploy", "Deploy through the release pipeline", tags=("deploy",)), _record("how", "How expenses are filed is documented")]
        relevance = _memory_relevance(records, "how do we deploy?")
        self.assertGreater(relevance.scores[0], 0)
        self.assertEqual((relevance.scores[1], relevance.unstemmed[1], relevance.coverage[1]), (0, False, 0))

    def test_a_query_of_only_listed_words_is_scored_on_them(self) -> None:
        self.assertEqual(_memory_query_tokens("what is it?"), ["what"])
        records = [_record("a", "What the staging password policy is remains unknown"), _record("b", "Budget reviews happen monthly")]
        relevance = _memory_relevance(records, "what is it?")
        self.assertGreater(relevance.scores[0], 0)
        self.assertEqual(relevance.scores[1], 0)

    def test_records_keep_their_function_words_and_may_stays_a_word(self) -> None:
        self.assertIn("how", _memory_token_list("How expenses are filed"))
        self.assertIn("remind", _memory_token_list("We remind new hires to enable 2FA"))
        self.assertIn("may", _memory_query_tokens("deploy freeze in may"))

    def test_chat_fillers_are_dropped_from_the_query(self) -> None:
        self.assertEqual(_memory_query_tokens("can you remind me how we deploy?"), ["deploy"])
        self.assertEqual(_memory_query_tokens("quick question: do we deploy on fridays?"), ["deploy", "fridays"])
        self.assertEqual(_memory_query_tokens("does anyone know how we deploy, just wondering"), ["deploy"])

    def test_korean_interrogative_prefixes_drop_the_whole_run(self) -> None:
        self.assertEqual(_memory_query_tokens("배포 언제쯤이야?"), ["배포"])
        self.assertEqual(_memory_query_tokens("배포 승인 누가요?"), ["배포", "승인"])
        for run in ("어떻게든", "누구야", "어디서", "뭐였더라", "무슨", "몇시에", "왜요"):
            with self.subTest(run=run):
                self.assertEqual(_memory_query_tokens(f"배포 {run}"), ["배포"])
        # Records are never filtered.
        self.assertIn("언제", _memory_token_list("언제 회의할지는 팀장이 정한다"))

    def test_bare_korean_endings_are_dropped_as_whole_runs(self) -> None:
        for ending in ("알려줘", "했지", "해요", "있나요", "인가요"):
            with self.subTest(ending=ending):
                self.assertEqual(_memory_query_tokens(f"배포 {ending}"), ["배포"])
        # A longer run that merely contains a listed ending is a word: it loses
        # only the suffix it ends in, never the whole run.
        tokens = _memory_query_tokens("배포했지만 실패")
        self.assertIn("배포했지", tokens)
        self.assertIn("실패", tokens)

    def test_japanese_and_chinese_interrogatives_are_cut_out_before_bigrams(self) -> None:
        self.assertEqual(_memory_query_tokens("怎么部署？"), ["部署"])
        self.assertEqual(_memory_query_tokens("为什么部署失败"), ["部署失败", "部署", "署失", "失败"])
        japanese = _memory_query_tokens("デプロイはどうやるの？")
        self.assertNotIn("どう", japanese)
        self.assertNotIn("はど", japanese)
        self.assertIn("デプ", japanese)
        self.assertEqual(_cut_cjk_function_words("誰がデプロイする"), ["がデプロイする"])

    def test_listed_words_never_add_coverage_but_order_records_within_one(self) -> None:
        self.assertEqual(_memory_query_split("is there a quick start?"), (["there", "start"], ["quick"]))
        records = [
            _record("standups", "Standups start at 9:30 in the main room", tags=("meeting",)),
            _record("guide", "Quick start guide is docs/quickstart.md", tags=("docs",)),
            _record("links", "Quick links are pinned in the channel", tags=("docs",)),
        ]
        relevance = _memory_relevance(records, "is there a quick start?")
        self.assertEqual(relevance.coverage, [2, 2, 0])
        self.assertGreater(relevance.scores[1], relevance.scores[0])
        self.assertEqual(relevance.scores[2], 0)

    def test_listed_words_score_when_no_content_word_past_two_latin_letters_is_left(self) -> None:
        self.assertEqual(_memory_query_split("where do thanks go?"), (["where", "thanks", "go"], []))
        self.assertEqual(_memory_query_split("CI?"), (["ci"], []))
        # A two-character CJK token is a word, not a fragment.
        self.assertEqual(_memory_query_split("部署一下怎么弄")[0], ["部署"])

    def test_japanese_and_chinese_request_fillers_add_no_coverage(self) -> None:
        japanese = _memory_query_tokens("デプロイってどうすればいいですか")
        self.assertIn("デプ", japanese)
        for bigram in ("すれ", "れば", "いい", "です", "すか"):
            with self.subTest(bigram=bigram):
                self.assertNotIn(bigram, japanese)
        self.assertNotIn("教え", _memory_query_tokens("デプロイのやり方を教えて"))
        self.assertEqual(_memory_query_tokens("请问部署"), ["部署"])
        self.assertEqual(_memory_query_tokens("搞部署"), ["部署"])

    def test_korean_colloquial_fillers_are_dropped(self) -> None:
        for query in ("배포 어케 해", "혹시 배포", "배포 어떡해", "배포 알려주세요", "가르쳐줘 배포"):
            with self.subTest(query=query):
                self.assertEqual(_memory_query_tokens(query), ["배포"])

    def test_capitals_keep_a_listed_word_that_names_something(self) -> None:
        self.assertEqual(_memory_query_tokens("WHO?"), ["who"])
        self.assertEqual(_memory_query_tokens("what does WHO say about travel"), ["who", "say", "travel"])
        self.assertEqual(_memory_query_tokens("ask Will"), ["will"])
        self.assertEqual(_memory_query_tokens("CAN logger"), ["can", "logger"])
        # Capitalized at the start of a sentence is ordinary sentence case.
        self.assertEqual(_memory_query_tokens("Can you remind me how we deploy? How?"), ["deploy"])
        self.assertEqual(_kept_listed_words("Notes from Will: Who knows"), frozenset({"will"}))


class ColloquialQueryTests(unittest.TestCase):
    """Particles, endings and chat fillers in a colloquial query only order records.

    Each list below is written out rather than read from the module, so a
    removed entry fails its own case.
    """

    _KOREAN_SUFFIXES = (
        "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로", "와", "과", "랑", "요", "좀",
        "으로", "에서", "에게", "한테", "까지", "부터", "처럼", "보다", "이랑", "이나", "마다", "밖에",
        "이면", "이라", "인데", "는데", "은데", "인지", "는지", "은지",
        "해", "해줘", "해주세요", "주세요", "해봐", "해야", "하면", "해서", "하고", "했어", "했는데",
        "하는데", "하자", "할래", "할게", "돼", "됐어", "됨",
    )

    def test_every_listed_korean_suffix_comes_off_a_noun_and_off_a_latin_word(self) -> None:
        self.assertEqual(set(self._KOREAN_SUFFIXES), set(_QUERY_KOREAN_SUFFIXES))
        for suffix in self._KOREAN_SUFFIXES:
            with self.subTest(suffix=suffix):
                # Glued to a Korean noun the suffix comes off; glued to a Latin
                # word ("main에서") the run is the suffix whole and leaves nothing.
                self.assertEqual(_memory_query_split(f"배포{suffix}")[0], ["배포"])
                self.assertEqual(_memory_query_split(f"deploy{suffix}")[0], ["deploy"])

    def test_stripping_keeps_the_stem_matching_and_moves_the_suffix_out_of_coverage(self) -> None:
        self.assertEqual(_memory_query_split("자동으로"), (["자동"], ["자동으로", "동으", "으로"]))
        self.assertEqual(_memory_query_tokens("메모리에서는 확인해주세요"), ["메모리", "메모", "모리", "확인"])
        records = [
            _record("memory", "메모리 기록은 자동 승인되고 나중에 리뷰할 수 있다", tags=("memory",)),
            _record("deploy", "배포는 main 머지 후 자동으로 나간다", tags=("deploy",)),
        ]
        # 자동으로 used to add 자동으로, 동으 and 으로, and the deploy record tied at 8.
        self.assertEqual(_memory_relevance(records, "메모리 자동으로 저장돼?").coverage, [8, 2])

    def test_a_run_that_is_wholly_a_listed_ending_leaves_nothing(self) -> None:
        self.assertEqual(_korean_query_stem("해주세요"), "")
        self.assertEqual(_memory_query_tokens("확인좀 해주세요 PR"), ["pr", "확인"])
        records = [_record("bot", "해주세요 봇은 일정 알림을 보낸다", tags=("bot",)), _record("pr", "PR 리뷰는 코드오너 한 명 승인으로 머지한다")]
        self.assertEqual(_memory_relevance(records, "확인좀 해주세요 PR").coverage, [0, 2])

    def test_a_two_syllable_noun_that_ends_like_a_particle_stays(self) -> None:
        # 경로 and 평가 end in particle-like syllables and are nouns: the floor
        # keeps them, whether bare or under a particle.
        self.assertEqual(_memory_query_split("배포 경로"), (["배포", "경로"], []))
        self.assertEqual(_memory_query_split("배포 평가"), (["배포", "평가"], []))
        self.assertEqual(_memory_query_tokens("경로로 평가는"), ["경로", "평가"])
        self.assertEqual(_korean_query_stem("메모리"), "메모리")
        # The floor does not save a two-syllable run that is a listed suffix
        # whole: 인지 (cognition) reads as the ending 인지.
        self.assertEqual(_memory_query_tokens("인지 부하"), ["부하"])

    def test_the_suffix_strip_cuts_a_longer_noun_that_ends_in_a_listed_syllable(self) -> None:
        # The cost the docstring names: spelled suffixes, not parsed ones.
        self.assertEqual(_korean_query_stem("재시도"), "재시")
        self.assertEqual(_korean_query_stem("게이트웨이"), "게이트웨")
        self.assertEqual(_memory_query_split("응답속도"), (["응답속", "응답", "답속"], ["응답속도", "속도"]))
        # A stem that is itself a listed suffix leaves nothing, like 해야돼.
        self.assertEqual(_korean_query_stem("인지도"), "")
        self.assertEqual(_korean_query_stem("해야돼"), "")

    def test_a_capitalized_two_letter_name_keeps_the_fallback_off(self) -> None:
        # Stripping can leave only an acronym as content. Written in capitals
        # it is a name, so the interrogatives and endings stay listed.
        for query, content in (
            ("PR 어떻게 해야돼", ["pr"]),
            ("PR 어떻게 하면 돼", ["pr"]),
            ("PR 이거 어떻게 해", ["pr"]),
            ("CI 그냥 어떻게 해", ["ci"]),
            ("honestly what about CI", ["ci"]),
        ):
            with self.subTest(query=query):
                self.assertEqual(_memory_query_split(query)[0], content)
        # Lowercase, a two-letter word is not known to be a name; the strip
        # still never causes the fallback, so the unstripped content serves,
        # as it did before the strip, with 어떻게 still listed.
        self.assertEqual(_memory_query_split("pr 어떻게 해야돼")[0], ["pr", "해야돼", "해야", "야돼"])
        self.assertEqual(_memory_query_split("ci 어떻게 하면 돼")[0], ["ci", "하면"])
        # An all-caps interjection is not a name, and a query with nothing
        # longer than two letters still falls back to every word.
        self.assertEqual(_memory_query_split("OK where do thanks go")[0], ["where", "thanks", "ok", "go"])
        self.assertEqual(_memory_query_split("where do thanks go?"), (["where", "thanks", "go"], []))

    def test_a_filler_left_after_stripping_is_dropped_too(self) -> None:
        for query in ("진짜로 배포", "그냥요 배포", "근데요 배포"):
            with self.subTest(query=query):
                self.assertEqual(_memory_query_tokens(query), ["배포"])

    def test_stripped_tokens_still_order_records_within_one_coverage(self) -> None:
        records = [
            _record("stem", "메모리는 자동 승인된다", tags=("memory",)),
            _record("inflected", "메모리는 자동으로 저장된다", tags=("memory",)),
        ]
        relevance = _memory_relevance(records, "메모리 자동으로")
        self.assertEqual(relevance.coverage[0], relevance.coverage[1])
        self.assertGreater(relevance.scores[1], relevance.scores[0])

    def test_a_query_of_only_fillers_and_endings_scores_its_unstripped_endings(self) -> None:
        # The strip never causes the fallback: with nothing left after it, the
        # unstripped content serves, so 해주세요, 해주, 주세 and 세요 count
        # again as they did before any stripping, and the fillers stay listed.
        query = "진짜 그냥 해주세요"
        self.assertEqual(_memory_query_split(query), (["해주세요", "해주", "주세", "세요"], ["진짜", "그냥"]))
        records = [_record("bot", "해주세요 봇은 일정 알림을 보낸다"), _record("lunch", "점심은 12시")]
        self.assertEqual(_memory_relevance(records, query).coverage, [8, 0])

    def test_records_keep_their_particles_and_endings(self) -> None:
        tokens = _memory_token_list("배포는 main 머지 후 자동으로 나간다")
        for token in ("배포는", "자동으로", "으로"):
            with self.subTest(token=token):
                self.assertIn(token, tokens)

    def test_korean_fillers_are_dropped(self) -> None:
        for filler in (
            "그냥", "근데", "그런데", "그래서", "일단", "아니", "뭔가",
            "진짜", "정말", "완전", "너무", "약간", "솔직히", "아마",
            "그거", "이거", "저거", "그게", "이게", "저게",
        ):
            with self.subTest(filler=filler):
                self.assertEqual(_memory_query_tokens(f"{filler} 배포"), ["배포"])

    def test_english_hedges_and_intensifiers_are_dropped(self) -> None:
        for filler in ("honestly", "literally", "basically", "actually", "kinda", "sorta", "really", "totally", "anyway", "anyways"):
            with self.subTest(filler=filler):
                self.assertEqual(_memory_query_tokens(f"{filler} flaky tests"), ["flaky", "tests"])
        # Mid-sentence capitals still keep a listed word that names something.
        self.assertEqual(_memory_query_tokens("ask Really about flaky tests"), ["really", "flaky", "tests"])

    def test_japanese_and_chinese_wrappers_are_cut_out(self) -> None:
        for wrapper in ("って", "なってる", "なっている", "なってます"):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(_memory_query_tokens(f"保存{wrapper}"), ["保存"])
        for wrapper in ("什么时候", "一般", "通常", "平时"):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(_memory_query_tokens(f"发布{wrapper}"), ["发布"])
        self.assertEqual(_memory_query_tokens("メモリの保存ってどうなってる？"), ["メモリの保存", "メモ", "モリ", "リの", "の保", "保存"])
        self.assertEqual(_memory_query_tokens("发布一般什么时候？"), ["发布"])


class StemmedOnlyOverlapTests(unittest.TestCase):
    def test_a_stemmed_only_match_falls_back_and_leads_the_fallback_pack(self) -> None:
        pack = _pack(
            self,
            _spec("mem_a1_state", "State is kept in a Redux store", approved_at=_YOUNG, tags=("frontend",)),
            _spec("mem_a2_grafana", "Grafana dashboards hold the latency metrics", approved_at=_YOUNG, tags=("observability",)),
            _spec("mem_a3_release", "Releases ship on fridays", approved_at=_YOUNG, tags=("release",)),
            query="stats location?",
        )
        self.assertEqual(_ids(pack), ["mem_a1_state", "mem_a2_grafana", "mem_a3_release"])
        self.assertEqual(pack["query_fallback"]["readmitted_count"], 3)
        self.assertGreater(pack["included_records"][0]["score"], 1)

    def test_a_stemmed_match_counts_when_another_record_matches_unstemmed(self) -> None:
        pack = _pack(
            self,
            _spec("mem_s17_hires", "New hires get a laptop", approved_at=_YOUNG, tags=("onboarding",)),
            _spec("mem_s18_news", "Release news is posted in announce", approved_at=_YOUNG, tags=("release",)),
            query="new hire onboarding",
        )
        self.assertEqual(_ids(pack), ["mem_s17_hires", "mem_s18_news"])
        self.assertNotIn("query_fallback", pack)

    def test_relevance_reports_which_matches_are_unstemmed(self) -> None:
        records = [_record("state", "State is kept in Redux"), _record("stats", "Stats are exported nightly")]
        relevance = _memory_relevance(records, "stats")
        self.assertTrue(all(score > 0 for score in relevance.scores))
        self.assertEqual(relevance.unstemmed, [False, True])


class CoverageGuardTests(unittest.TestCase):
    """One stray query word, however rare, never outranks a topic word with its tag."""

    def test_coverage_counts_two_per_term_and_one_per_tag(self) -> None:
        records = [
            _record("both", "deploy from main", tags=("deploy", "main")),
            _record("summary", "deploy from main", tags=("ops",)),
            _record("one", "deploy nightly", tags=("ops",)),
            _record("none", "lunch at noon"),
        ]
        self.assertEqual(_memory_relevance(records, "deploy main").coverage, [6, 4, 2, 0])

    def test_a_rare_unlisted_word_never_outranks_a_topic_match_at_scale(self) -> None:
        # Like a real store, the topic word is common: every 13th note (154) mentions a deploy.
        filler = [
            _record(f"f{index:04d}", f"note number {index} about the build" + (" before a deploy" if index % 13 == 0 else ""), tags=("misc",))
            for index in range(1990)
        ]
        topic = [_record(f"d{index}", "Deploy through the release pipeline", tags=("deploy",)) for index in range(9)]
        stray = _record("stray", "Kindly ping the platform team before lunch", tags=("social",))
        records = [*filler, *topic, stray]
        relevance = _memory_relevance(records, "kindly deploy")
        by_id = {record["record_id"]: index for index, record in enumerate(records)}
        self.assertGreater(relevance.coverage[by_id["d0"]], relevance.coverage[by_id["stray"]])
        items = [
            {"record_id": record["record_id"], "score": relevance.scores[by_id[record["record_id"]]], "approved_at": _YOUNG}
            for record in (stray, topic[0])
        ]
        _attach_recall_ranking(items, {}, now=FIXTURE_CLOCK, coverage={record["record_id"]: relevance.coverage[by_id[record["record_id"]]] for record in (stray, topic[0])})
        ranks = {item["record_id"]: item["ranking"]["relevance_rank"] for item in items}
        self.assertEqual((ranks["d0"], ranks["stray"]), (1, 2))
        self.assertEqual(items[1]["ranking"]["coverage"], 3)

    def test_the_selector_ranks_on_coverage_before_the_score(self) -> None:
        pack = _pack(
            self,
            _spec("mem_e1", "Deploy through the release pipeline after CI is green", approved_at=_YOUNG, tags=("deploy",)),
            _spec("mem_e2", "Deploy approvals need two reviewers", approved_at=_YOUNG, tags=("deploy",)),
            _spec("mem_e3", "Deploy freezes start on december 20", approved_at=_YOUNG, tags=("deploy",)),
            _spec("mem_e4", "How we nudge new hires about 2FA", approved_at=_YOUNG, tags=("security",)),
            query="nudge me about how we deploy",
        )
        self.assertEqual(_ids(pack), ["mem_e1", "mem_e2", "mem_e3", "mem_e4"])
        # "how" and "about" raise mem_e4's score past every deploy record, but
        # listed words only order records of one coverage.
        scores = {item["record_id"]: item["score"] for item in pack["included_records"]}
        self.assertGreater(scores["mem_e4"], scores["mem_e1"])

    def test_two_records_covering_one_term_each_tie_and_recency_decides(self) -> None:
        # The blind probes' shape: one topic word, one stray word no list names,
        # and the topic word is the commoner of the two in the store.
        pack = _pack(
            self,
            _spec("mem_a_stray", "Kindly ping the platform team before lunch", approved_at=_AGING, tags=("social",)),
            _spec("mem_b_one", "Deploy from main", approved_at=_YOUNG, tags=("ops",)),
            _spec("mem_c_two", "Deploy windows close on fridays", approved_at=_AGING, tags=("ops",)),
            _spec("mem_d_three", "Deploy approvals need two reviewers", approved_at=_AGING, tags=("ops",)),
            query="kindly deploy",
        )
        ranks = {item["record_id"]: item["ranking"]["relevance_rank"] for item in pack["included_records"]}
        self.assertEqual(set(ranks.values()), {1}, ranks)
        self.assertEqual(_ids(pack)[0], "mem_b_one")


# "tally" is in four of these six records: a project store, where the
# project's name is in most records and says nothing about the topic.
_TALLY_IMPORT = _record("t", "Tally import needs a dry run first")
_TALLY_LIST = _record("a", "Tally list view pages by fifty")
_TALLY_SQLITE = _record("b", "Tally keeps its data in sqlite")
_TALLY_FRIDAYS = _record("c", "Tally ships on fridays")
_STANDUPS = _record("s", "Standups start at nine thirty")
_LUNCH = _record("l", "Lunch is at noon")
_COFFEE = _record("k", "The coffee machine is on floor two")


class StoreCommonTermTests(unittest.TestCase):
    """A query term most candidates hold never makes a record match on its own."""

    def test_a_term_most_candidates_hold_never_matches_alone(self) -> None:
        records = [_TALLY_IMPORT, _TALLY_LIST, _TALLY_SQLITE, _TALLY_FRIDAYS, _STANDUPS, _LUNCH]
        relevance = _memory_relevance(records, "tally import")
        self.assertEqual(relevance.coverage, [2, 0, 0, 0, 0, 0])
        self.assertEqual(relevance.scores[1:], [0, 0, 0, 0, 0])
        self.assertEqual(relevance.common_only, [False, True, True, True, False, False])
        # Scored like a listed word: it still orders the record it appears in.
        self.assertGreater(relevance.scores[0], _memory_relevance(records, "import").scores[0])

    def test_a_query_whose_every_term_is_common_keeps_them(self) -> None:
        records = [_TALLY_IMPORT, _TALLY_LIST, _TALLY_SQLITE, _TALLY_FRIDAYS, _STANDUPS, _LUNCH]
        relevance = _memory_relevance(records, "tally")
        self.assertEqual(relevance.coverage, [2, 2, 2, 2, 0, 0])
        self.assertEqual(relevance.common_only, [False] * 6)

    def test_below_five_candidates_the_rule_is_off(self) -> None:
        # Three of four hold "tally", yet four candidates are too few to say.
        four = [_TALLY_IMPORT, _TALLY_LIST, _TALLY_SQLITE, _STANDUPS]
        self.assertEqual(_memory_relevance(four, "tally import").coverage, [4, 2, 2, 0])
        self.assertEqual(_memory_relevance(four, "tally import").common_only, [False] * 4)
        five = [*four, _LUNCH]
        self.assertEqual(_memory_relevance(five, "tally import").coverage, [2, 0, 0, 0, 0])

    def test_a_term_exactly_half_the_candidates_hold_is_not_common(self) -> None:
        six = [_TALLY_IMPORT, _TALLY_LIST, _TALLY_SQLITE, _STANDUPS, _LUNCH, _COFFEE]
        self.assertEqual(_memory_relevance(six, "tally import").coverage, [4, 2, 2, 0, 0, 0])
        seven = [*six, _TALLY_FRIDAYS]
        self.assertEqual(_memory_relevance(seven, "tally import").coverage, [2, 0, 0, 0, 0, 0, 0])

    def test_a_tag_hit_on_a_common_term_still_matches(self) -> None:
        tagged = _record("a", "Tally list view pages by fifty", tags=("tally",))
        records = [_TALLY_IMPORT, tagged, _TALLY_SQLITE, _TALLY_FRIDAYS, _STANDUPS, _LUNCH]
        relevance = _memory_relevance(records, "tally import")
        self.assertEqual(relevance.coverage, [2, 3, 0, 0, 0, 0])
        self.assertEqual(relevance.common_only, [False, False, True, True, False, False])

    def test_the_selector_names_a_record_that_met_the_query_only_on_a_common_term(self) -> None:
        pack = _pack(
            self,
            _spec("mem_t_import", "Tally import needs a dry run first", approved_at=_AGING, tags=("import",)),
            _spec("mem_t_list", "Tally list view pages by fifty", approved_at=_YOUNG, tags=("ui",)),
            _spec("mem_t_sqlite", "Tally keeps its data in sqlite", approved_at=_YOUNG, tags=("storage",)),
            _spec("mem_t_fridays", "Tally ships on fridays", approved_at=_YOUNG, tags=("release",)),
            _spec("mem_standups", "Standups start at nine thirty", approved_at=_YOUNG, tags=("meeting",)),
            query="tally import",
        )
        self.assertEqual(_ids(pack), ["mem_t_import"])
        self.assertEqual(
            _reasons(pack),
            {
                "mem_t_list": "common_terms_only",
                "mem_t_sqlite": "common_terms_only",
                "mem_t_fridays": "common_terms_only",
                "mem_standups": "no_query_overlap",
            },
        )
        self.assertNotIn("query_fallback", pack)
        self.assertEqual(validate_project_memory_recall_pack(pack), [])

    def test_a_record_held_back_on_a_common_word_still_anchors_a_stemmed_match(self) -> None:
        # "backup" meets "Backups" only through stemming, and "team" is the
        # query's one unstemmed hit. The team records cannot match on it, but
        # they still share it, so the stemmed match counts and leads alone.
        team = [
            _spec("mem_team1", "The team meets on mondays", approved_at=_YOUNG),
            _spec("mem_team2", "The team uses squash merges", approved_at=_YOUNG),
            _spec("mem_team3", "Team lunch is on fridays", approved_at=_YOUNG),
            _spec("mem_team4", "The team owns the billing service", approved_at=_YOUNG),
        ]
        backup = _spec("mem_backup", "Backups rotate weekly", approved_at=_AGING)
        records = [_record(str(spec["record_id"]), str(spec["summary"])) for spec in (*team, backup)]
        relevance = _memory_relevance(records, "team backup")
        self.assertEqual(relevance.common_only, [True, True, True, True, False])
        self.assertEqual(relevance.unstemmed, [True, True, True, True, False])
        self.assertEqual(relevance.scores[:4], [0, 0, 0, 0])
        pack = _pack(self, *team, backup, query="team backup")
        self.assertEqual(_ids(pack), ["mem_backup"])
        self.assertNotIn("query_fallback", pack)
        self.assertEqual(set(_reasons(pack).values()), {"common_terms_only"})

    def test_with_no_unstemmed_holder_a_common_word_does_not_block_the_fallback(self) -> None:
        # "teams" meets "team" only through stemming, so no record shares an
        # unstemmed query word: the stemmed-only rule makes this a query that
        # matched nothing, and it falls back with the team records still out.
        team = [
            _spec("mem_team1", "The team meets on mondays", approved_at=_YOUNG),
            _spec("mem_team2", "The team uses squash merges", approved_at=_YOUNG),
            _spec("mem_team3", "Team lunch is on fridays", approved_at=_YOUNG),
            _spec("mem_team4", "The team owns the billing service", approved_at=_YOUNG),
        ]
        pack = _pack(self, *team, _spec("mem_backup", "Backups rotate weekly", approved_at=_AGING), query="teams backup")
        self.assertEqual(_ids(pack), ["mem_backup"])
        self.assertEqual(pack["query_fallback"]["readmitted_count"], 1)
        self.assertEqual(set(_reasons(pack).values()), {"common_terms_only"})

    def test_a_holder_with_the_term_only_as_a_tag_counts_toward_common(self) -> None:
        # Three summaries and one tag hold "tally": four of six, a majority.
        tag_only = _record("g", "Release notes go out on fridays", tags=("tally",))
        records = [_TALLY_IMPORT, _TALLY_LIST, _TALLY_SQLITE, tag_only, _STANDUPS, _LUNCH]
        relevance = _memory_relevance(records, "tally import")
        self.assertEqual(relevance.coverage, [2, 0, 0, 3, 0, 0])
        self.assertEqual(relevance.common_only, [False, True, True, False, False, False])

    def test_copies_of_one_record_count_once(self) -> None:
        # Four copies of one summary are one pack slot, so "backup" is held by
        # two of five distinct records, not five of eight.
        copies = [_record(f"x{index}", "Backup questions go to the external portal", tags=("backup",)) for index in range(4)]
        rotate = _record("v", "Rotate the backup encryption key monthly")
        records = [rotate, _STANDUPS, _LUNCH, _COFFEE, *copies]
        relevance = _memory_relevance(records, "backup restore steps")
        self.assertEqual(relevance.common_only, [False] * 8)
        self.assertEqual(relevance.coverage[0], 2)

    def test_only_records_marked_live_count_toward_common(self) -> None:
        records = [_TALLY_IMPORT, _TALLY_LIST, _TALLY_SQLITE, _TALLY_FRIDAYS, _STANDUPS, _LUNCH]
        self.assertEqual(_memory_relevance(records, "tally import").common_only, [False, True, True, True, False, False])
        # Two of the tally records are not servable (a replaced subject value,
        # an inspection-only stale record): two of four live is not a majority
        # and four live records are too few anyway, so every holder matches.
        live = [True, True, False, False, True, True]
        relevance = _memory_relevance(records, "tally import", live)
        self.assertEqual(relevance.common_only, [False] * 6)
        self.assertEqual(relevance.coverage, [4, 2, 2, 2, 0, 0])

    def test_an_inspection_only_stale_record_never_makes_a_word_common(self) -> None:
        stale = [
            _spec(f"mem_stale{index}", f"Tally release {index} notes are archived", approved_at=_AGING, review_due_at=_PAST)
            for index in range(4)
        ]
        live = [
            _spec("mem_t_import", "Tally import needs a dry run first", approved_at=_YOUNG),
            _spec("mem_t_list", "Tally list view pages by fifty", approved_at=_YOUNG),
            _spec("mem_standups", "Standups start at nine thirty", approved_at=_YOUNG),
            _spec("mem_lunch", "Lunch is at noon", approved_at=_YOUNG),
            _spec("mem_coffee", "The coffee machine is on floor two", approved_at=_YOUNG),
        ]
        # Two of the five servable records hold "tally"; the four stale ones
        # --include-stale shows would make it six of nine.
        pack = _pack(self, *live, *stale, query="tally import", include_stale=True)
        self.assertIn("mem_t_list", _ids(pack))
        self.assertNotIn("common_terms_only", set(_reasons(pack).values()))

    def test_a_current_value_that_met_the_query_on_a_common_word_takes_the_older_match(self) -> None:
        # "Tally" is in four of the five servable records. The current storage
        # record meets "tally sqlite locking error" only on it; the value it
        # replaced said "sqlite", so the current one takes that match.
        pack = _pack(
            self,
            _spec("mem_t_list", "Tally list view pages by fifty", approved_at=_YOUNG),
            _spec("mem_t_fridays", "Tally ships on fridays", approved_at=_YOUNG),
            _spec("mem_t_import", "Tally import needs a dry run", approved_at=_YOUNG),
            _spec("mem_old", "Tally keeps its data in sqlite", approved_at=_AGING, subject="storage-backend"),
            _spec("mem_new", "Tally moved storage to postgres", approved_at=_YOUNG, subject="storage-backend"),
            _spec("mem_standups", "Standups start at nine thirty", approved_at=_YOUNG),
            query="tally sqlite locking error",
        )
        self.assertEqual(_ids(pack), ["mem_new"])
        reasons = _reasons(pack)
        self.assertEqual(reasons["mem_old"], "superseded_by_subject")
        self.assertEqual({reasons[record_id] for record_id in ("mem_t_list", "mem_t_fridays", "mem_t_import")}, {"common_terms_only"})

    def test_a_current_value_whose_group_met_the_query_only_on_common_words_stays_held_back(self) -> None:
        # "Tally" is in four of the five servable records, and neither value of
        # the host subject says "quantum": the group has no match to give, so
        # the current value stays `common_terms_only`.
        pack = _pack(
            self,
            _spec("mem_t_list", "Tally list view pages by fifty", approved_at=_YOUNG),
            _spec("mem_t_fridays", "Tally ships on fridays", approved_at=_YOUNG),
            _spec("mem_t_import", "Tally import needs a dry run", approved_at=_YOUNG),
            _spec("mem_old", "Tally ran on a laptop", approved_at=_AGING, subject="tally-host"),
            _spec("mem_new", "Tally runs on a server now", approved_at=_YOUNG, subject="tally-host"),
            _spec("mem_standups", "Standups start at nine thirty", approved_at=_YOUNG),
            query="tally quantum",
        )
        self.assertEqual(_ids(pack), [])
        self.assertEqual(_reasons(pack)["mem_new"], "common_terms_only")

    def test_the_all_common_guard_reads_the_closed_lists(self) -> None:
        # 탈리 is in four of the six records. 알려줘 is a listed request word, so
        # in "탈리 알려줘" every content term is common and the guard keeps them;
        # 대해 is not listed, so in "탈리에 대해" 탈리 is common beside it.
        records = [
            _record("k1", "탈리 목록은 50개씩 페이지를 나눈다"),
            _record("k2", "탈리는 금요일마다 배포한다"),
            _record("k3", "탈리 가져오기는 dry run이 먼저 필요하다"),
            _record("k4", "탈리 데이터는 sqlite에 저장된다"),
            _record("k5", "스탠드업은 9시 30분에 시작한다"),
            _record("k6", "점심은 정오에 먹는다"),
        ]
        kept = _memory_relevance(records, "탈리 알려줘")
        self.assertEqual(kept.coverage, [2, 2, 2, 2, 0, 0])
        self.assertEqual(kept.common_only, [False] * 6)
        held = _memory_relevance(records, "탈리에 대해")
        self.assertEqual(held.coverage, [0] * 6)
        self.assertEqual(held.common_only, [True, True, True, True, False, False])

    def test_a_current_value_that_took_an_older_match_is_readmitted_by_the_fallback(self) -> None:
        # "teams" meets "team" only through stemming and the replaced value
        # does not count, so nothing servable overlaps and the query falls
        # back. The current value took the replaced value's "databases" match,
        # so it is no longer common-only: it is readmitted and leads.
        pack = _pack(
            self,
            _spec("mem_team1", "The team meets on mondays", approved_at=_YOUNG),
            _spec("mem_team2", "The team uses squash merges", approved_at=_YOUNG),
            _spec("mem_team3", "Team lunch is on fridays", approved_at=_YOUNG),
            _spec("mem_old", "Data lived in sqlite databases", approved_at=_AGING, subject="storage-backend"),
            _spec("mem_new", "The team moved storage to postgres", approved_at=_YOUNG, subject="storage-backend"),
            _spec("mem_coffee", "The coffee machine is on floor two", approved_at=_YOUNG),
            query="teams databases",
        )
        self.assertEqual(_ids(pack), ["mem_new", "mem_coffee"])
        self.assertEqual(pack["query_fallback"]["readmitted_count"], 2)
        self.assertEqual({_reasons(pack)[f"mem_team{index}"] for index in (1, 2, 3)}, {"common_terms_only"})


class RecordTypeFieldTests(unittest.TestCase):
    def test_a_record_type_alone_never_matches(self) -> None:
        records = [_record("decision", "Use uv for packaging", record_type="decision"), _record("fact", "Python 3.12 is the minimum")]
        self.assertEqual(_memory_relevance_scores(records, "decisions"), [0, 0])
        self.assertEqual(_memory_relevance_scores(records, "decision"), [0, 0])

    def test_a_record_type_boosts_a_record_that_has_a_content_hit(self) -> None:
        records = [
            _record("decision", "deploy from main", record_type="decision"),
            _record("fact", "deploy from tags", record_type="fact"),
        ]
        scores = _scored(records, "deploy decision")
        self.assertGreater(scores["decision"], scores["fact"])


class TemporalBandTests(unittest.TestCase):
    def _items(self) -> list[dict[str, object]]:
        return [
            {"record_id": "mem_old", "score": 491, "approved_at": "2030-06-01T00:00:00Z", "admission_mode": "approved_manual"},
            {"record_id": "mem_new", "score": 469, "approved_at": "2030-12-30T00:00:00Z", "admission_mode": "approved_manual"},
        ]

    def test_a_temporal_query_shares_a_relevance_rank_within_a_band(self) -> None:
        items = self._items()
        _attach_recall_ranking(items, {}, now=FIXTURE_CLOCK, recency_weight=2.0, temporal=True)
        self.assertEqual([item["ranking"]["relevance_rank"] for item in items], [1, 1])
        self.assertGreater(items[1]["ranking"]["rrf_score_micro"], items[0]["ranking"]["rrf_score_micro"])

    def test_a_default_query_ranks_on_raw_scores(self) -> None:
        items = self._items()
        _attach_recall_ranking(items, {}, now=FIXTURE_CLOCK)
        self.assertEqual([item["ranking"]["relevance_rank"] for item in items], [1, 2])

    def test_a_temporal_band_is_measured_within_one_coverage(self) -> None:
        items = [
            {"record_id": "mem_wide", "score": 1000, "approved_at": "2030-01-01T00:00:00Z"},
            {"record_id": "mem_older", "score": 300, "approved_at": "2030-06-01T00:00:00Z"},
            {"record_id": "mem_newer", "score": 230, "approved_at": "2030-12-30T00:00:00Z"},
        ]
        coverage = {"mem_wide": 4, "mem_older": 2, "mem_newer": 2}
        _attach_recall_ranking(items, {}, now=FIXTURE_CLOCK, recency_weight=2.0, temporal=True, coverage=coverage)
        ranks = {item["record_id"]: item["ranking"]["relevance_rank"] for item in items}
        # 230 is within a quarter of 300, the best of its own coverage, though not of 1000.
        self.assertEqual(ranks, {"mem_wide": 1, "mem_older": 2, "mem_newer": 2})

    def test_a_score_outside_the_band_keeps_its_own_rank(self) -> None:
        items = self._items()
        items[1]["score"] = 300
        _attach_recall_ranking(items, {}, now=FIXTURE_CLOCK, recency_weight=2.0, temporal=True)
        self.assertEqual([item["ranking"]["relevance_rank"] for item in items], [1, 2])


class SubjectPoolTests(unittest.TestCase):
    def test_a_stale_newest_value_still_holds_the_subject(self) -> None:
        specs = (
            _spec("mem_old", "Deploys go from the release branch", approved_at=_AGING, tags=("deploy",), subject="deploy-branch"),
            _spec("mem_new", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch", review_due_at=_PAST),
        )
        default = _pack(self, *specs, query="deploy branch")
        self.assertEqual(_ids(default), [])
        self.assertEqual(_reasons(default), {"mem_old": "superseded_by_subject", "mem_new": "stale_review_required"})
        inspected = _pack(self, *specs, query="deploy branch", include_stale=True)
        self.assertEqual(_ids(inspected), ["mem_new"])
        self.assertEqual(_reasons(inspected), {"mem_old": "superseded_by_subject"})

    def test_an_inspection_only_older_value_is_still_superseded(self) -> None:
        specs = (
            _spec("mem_old", "Deploys go from the release branch", approved_at=_AGING, tags=("deploy",), subject="deploy-branch", review_due_at=_PAST),
            _spec("mem_new", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch"),
        )
        pack = _pack(self, *specs, query="deploy branch", include_stale=True)
        self.assertEqual(_ids(pack), ["mem_new"])
        self.assertEqual(_reasons(pack), {"mem_old": "superseded_by_subject"})

    def test_a_pin_does_not_hold_an_older_value(self) -> None:
        pack = _pack(
            self,
            _spec("mem_old", "Deploys go from the release branch", approved_at=_AGING, tags=("deploy",), subject="deploy-branch"),
            _spec("mem_new", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch"),
            query="deploy branch",
            pins=("mem_old",),
        )
        self.assertEqual(_ids(pack), ["mem_new"])
        self.assertEqual(_reasons(pack)["mem_old"], "superseded_by_subject")

    def test_a_record_another_perspective_holds_never_supersedes_this_one(self) -> None:
        pack = _pack(
            self,
            _spec("mem_mine", "Run tests with make check", approved_at=_AGING, tags=("tests",), subject="test-command", observer="hermes", observed="claude-code"),
            _spec("mem_theirs", "Run tests with pytest -x", approved_at=_YOUNG, tags=("tests",), subject="test-command", observer="hermes", observed="codex"),
            query="tests",
            observed="claude-code",
        )
        self.assertEqual(_ids(pack), ["mem_mine"])
        self.assertNotIn("mem_theirs", json.dumps(pack["excluded_records"]))

    def test_a_record_the_principal_gate_refuses_never_supersedes_or_appears(self) -> None:
        real = selector_module.principal_recall_decision

        def refuse_new(record, principal, *, shared_surface=False, channel_scopes=()):
            if record.get("record_id") == "mem_new":
                return {"allowed": False, "reason_code": "principal_mismatch"}
            return real(record, principal, shared_surface=shared_surface, channel_scopes=channel_scopes)

        with patch.object(selector_module, "principal_recall_decision", refuse_new):
            pack = _pack(
                self,
                _spec("mem_old", "Deploys go from the release branch", approved_at=_AGING, tags=("deploy",), subject="deploy-branch"),
                _spec("mem_new", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch"),
                query="deploy branch",
            )
        self.assertEqual(_ids(pack), ["mem_old"])
        self.assertNotIn("mem_new", json.dumps(pack))

    def test_an_equal_stamp_goes_to_the_smaller_record_id_in_selection_and_capture(self) -> None:
        pack = _pack(
            self,
            _spec("mem_b", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch"),
            _spec("mem_a", "Deploys go from trunk", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch"),
            query="deploy",
        )
        self.assertEqual(_ids(pack), ["mem_a"])
        self.assertEqual(_reasons(pack)["mem_b"], "superseded_by_subject")
        self.assertEqual(newest_record([{"record_id": "mem_b", "approved_at": _YOUNG}, {"record_id": "mem_a", "approved_at": _YOUNG}])["record_id"], "mem_a")
        self.assertEqual(memory_admission._subject_holder(
            [{"record_id": "mem_b", "approved_at": _YOUNG, "subject": "s"}, {"record_id": "mem_a", "approved_at": _YOUNG, "subject": "s"}], "s", skip=set()
        ), "mem_a")

    def test_a_current_value_sharing_a_query_word_takes_the_groups_best_score(self) -> None:
        specs = (
            _spec("mem_old", "Reply language for this user is Korean", approved_at=_AGING, tags=("style",), subject="reply-language"),
            _spec("mem_new", "Reply in English", approved_at=_YOUNG, tags=("style",), subject="reply-language"),
            _spec("mem_other", "Language packs ship with the installer", approved_at=_YOUNG, tags=("i18n",)),
        )
        pack = _pack(self, *specs, query="reply language korean")
        records = [materialize_fixture_record(spec)[0] for spec in specs]
        alone = dict(zip(("mem_old", "mem_new", "mem_other"), _memory_relevance_scores(records, "reply language korean")))
        self.assertGreater(alone["mem_old"], alone["mem_new"])
        scores = {item["record_id"]: item["score"] for item in pack["included_records"]}
        self.assertEqual(scores["mem_new"], alone["mem_old"])
        self.assertEqual(_ids(pack)[0], "mem_new")
        # The coverage moves with the score, not the score alone.
        covered = dict(zip(("mem_old", "mem_new", "mem_other"), _memory_relevance(records, "reply language korean").coverage))
        self.assertGreater(covered["mem_old"], covered["mem_new"])
        ranking = {item["record_id"]: item["ranking"]["coverage"] for item in pack["included_records"]}
        self.assertEqual(ranking["mem_new"], covered["mem_old"])
        self.assertEqual(_reasons(pack)["mem_old"], "superseded_by_subject")

    def test_a_current_value_sharing_no_query_word_takes_no_score(self) -> None:
        pack = _pack(
            self,
            _spec("mem_m1_provider", "CI runs on Buildkite", approved_at=_AGING, tags=("ci",), subject="ci"),
            _spec("mem_m2_cache", "Cache keys include the lockfile hash", approved_at=_YOUNG, tags=("cache",), subject="ci"),
            query="which CI provider do we use?",
        )
        self.assertEqual(_reasons(pack), {"mem_m1_provider": "superseded_by_subject"})
        self.assertEqual([(item["record_id"], item["score"]) for item in pack["included_records"]], [("mem_m2_cache", 1)])
        self.assertIn("query_fallback", pack)

    def test_the_receipt_names_at_most_sixteen_replaced_records(self) -> None:
        specs = [
            _spec(f"mem_v{index:02d}", f"Deploy value number {index}", approved_at=f"2030-12-{index + 1:02d}T00:00:00Z", tags=("deploy",), subject="deploy-branch")
            for index in range(20)
        ]
        root = Path(self.enterContext(TemporaryDirectory()))
        paths = OmhPaths(root / ".omh", root / "hermes")
        _seed_retrieval_store(paths, _case("probe", "probe", records=tuple(specs), query="deploy"))
        snapshot = read_record_store_snapshot((paths.omh_home,))
        prepared = prepare_prefetch_records(snapshot, "deploy", allowed_scopes=[{"kind": "project", "ref": FIXTURE_PROJECT_IDENTITY}], session_id="s", now=FIXTURE_CLOCK)
        receipt = build_prefetch_receipt(prepared, session_id="s", home_digests=snapshot.home_digests)
        self.assertEqual(len(receipt["selection"]["subject_superseded"]), MAX_SUBJECT_SUPERSEDED)
        self.assertEqual(receipt["selection"]["exclusion_reason_counts"]["superseded_by_subject"], 19)
        self.assertEqual(validate_prefetch_receipt(receipt), [])
        receipt["selection"]["subject_superseded"] *= 2
        self.assertIn("selection.subject_superseded", validate_prefetch_receipt(receipt))


class StoredSubjectShapeTests(unittest.TestCase):
    def test_the_store_refuses_a_record_whose_subject_is_out_of_shape(self) -> None:
        record, _ = materialize_fixture_record(_spec("mem_x", "Deploys go from main", approved_at=_YOUNG, subject="deploy-branch"))
        self.assertEqual(validate_project_memory_record(record), [])
        for value in ("Deploy Branch", "", 7):
            with self.subTest(value=value):
                errors = validate_project_memory_record({**record, "subject": value})
                self.assertTrue(any("subject" in error for error in errors), errors)

    def test_a_recall_pack_validates_subject_and_superseded_by_shapes(self) -> None:
        pack = _pack(
            self,
            _spec("mem_old", "Deploys go from the release branch", approved_at=_AGING, tags=("deploy",), subject="deploy-branch"),
            _spec("mem_new", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch"),
            query="deploy branch",
        )
        self.assertEqual(validate_project_memory_recall_pack(pack), [])
        pack["included_records"][0]["subject"] = "Deploy Branch"
        pack["excluded_records"][0]["superseded_by"] = "not a record id"
        errors = validate_project_memory_recall_pack(pack)
        self.assertTrue(any(".subject must match" in error for error in errors), errors)
        self.assertTrue(any(".superseded_by must be a record id" in error for error in errors), errors)


class DelegationRecordTests(unittest.TestCase):
    def test_a_subject_pack_attaches_to_a_delegation_and_records_as_a_handoff(self) -> None:
        specs = (
            _spec("mem_old", "Deploys go from the release branch", approved_at=_AGING, tags=("deploy",), subject="deploy-branch"),
            _spec("mem_new", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",), subject="deploy-branch"),
        )
        root = Path(self.enterContext(TemporaryDirectory()))
        # The suite's repository anchor, so the handoff resolves the fixture project.
        project_root = root / PARITY_PROJECT_IDENTITY
        (project_root / ".git").mkdir(parents=True)
        (project_root / ".git" / "config").write_text('[remote "origin"]\n url = https://example.invalid/memory-fixture.git\n', encoding="utf-8")
        paths = OmhPaths(project_root / ".omh", root / "hermes")
        _seed_retrieval_store(paths, _case("probe", "probe", records=specs, query="deploy branch"))
        pack = memory_recall_pack_for_handoff(paths, "fix the broken login flow in the deploy branch script", executor_target="codex", surface_class=SURFACE_OPERATOR_CONSOLE)
        assert pack is not None
        self.assertEqual([item["record_id"] for item in pack["included_records"]], ["mem_new"])
        message = "fix the broken login flow in src/auth.py and add a regression test"
        payload = build_coding_delegation_payload(message, executor_target="codex", memory_recall_pack=pack)
        attached = payload["executor_handoff"]["memory_recall_pack"]
        self.assertEqual(attached["included_records"][0]["subject"], "deploy-branch")
        run = create_prepared_coding_delegation_run(paths, {"skill": "ai-slop-cleaner", "harness": "coding-handling"})
        record = write_coding_delegation(paths.runtime_runs_dir / run["run_id"], coding_delegation_record_payload(payload, message))
        self.assertEqual(validate_coding_delegation_record(record), [])
        recorded = record["executor_handoff"]["memory_recall_pack"]
        self.assertEqual(recorded["included_records"][0]["subject"], "deploy-branch")
        [replaced] = [item for item in recorded["excluded_records"] if item["reason"] == "superseded_by_subject"]
        self.assertEqual((replaced["superseded_by"], replaced["subject"]), ("mem_new", "deploy-branch"))


class OpaqueLookingStorePathTests(unittest.TestCase):
    def test_a_store_under_an_opaque_looking_path_still_attaches_to_a_handoff(self) -> None:
        # Four random alphanumeric directory names, which the opaque-value
        # check still reads as one value split at "/". Before the pack dropped
        # `store_dir`, the attach scan refused such a store as a split
        # credential. (The CI shard temp root this case first used is no
        # longer flagged: tempfile names are generated names now.)
        root = Path(self.enterContext(TemporaryDirectory()))
        project_root = root / "k2j3h4g5" / "q1w2e3r4" / "z9x8c7v6" / "m5n4b3v2" / PARITY_PROJECT_IDENTITY
        (project_root / ".git").mkdir(parents=True)
        (project_root / ".git" / "config").write_text('[remote "origin"]\n url = https://example.invalid/memory-fixture.git\n', encoding="utf-8")
        paths = OmhPaths(project_root / ".omh", root / "hermes")
        self.assertTrue(contains_credential_like_material(str(paths.memory_dir)))
        _seed_retrieval_store(paths, _case("probe", "probe", records=(_spec("mem_one", "Deploys go from main", approved_at=_YOUNG, tags=("deploy",)),), query="deploy"))
        pack = memory_recall_pack_for_handoff(paths, "deploy from main", executor_target="codex", surface_class=SURFACE_OPERATOR_CONSOLE)
        assert pack is not None
        self.assertNotIn("store_dir", pack["policy"])
        self.assertEqual(validate_project_memory_recall_pack(pack), [])
        payload = build_coding_delegation_payload("fix the broken login flow in src/auth.py", executor_target="codex", memory_recall_pack=pack)
        self.assertEqual(payload["executor_handoff"]["memory_recall_pack"]["included_records"][0]["record_id"], "mem_one")


class ConfinementTests(unittest.TestCase):
    def _confined(self, candidate: dict, records: list[dict]) -> list[str]:
        with patch.object(memory_admission, "read_project_memory_records", return_value=records):
            return [str(record["record_id"]) for record in _records_in_confinement(Path("/unused"), candidate, now=FIXTURE_CLOCK)]

    def test_confinement_compares_scope_principal_and_audience(self) -> None:
        scope = {"kind": "project", "ref": "prj"}

        def identity(subject: str | None, refs: list[str]) -> dict:
            return {"subject_principal": subject, "audience": {"kind": "explicit_principals" if refs else "subject_only", "principal_refs": refs}}

        candidate = {"scope": scope, "identity": identity(None, ["p1", "p2"])}
        records = [
            {"record_id": "same", "scope": scope, "identity": identity(None, ["p2", "p1"])},
            {"record_id": "other_audience", "scope": scope, "identity": identity(None, ["p1"])},
            {"record_id": "other_principal", "scope": scope, "identity": identity("p9", ["p9"])},
            {"record_id": "unbound", "scope": scope},
            {"record_id": "other_scope", "scope": {"kind": "project", "ref": "other"}, "identity": identity(None, ["p1", "p2"])},
        ]
        self.assertEqual(self._confined(candidate, records), ["same"])
        self.assertEqual(self._confined({"scope": scope}, records), ["unbound"])
        # Same audience, another subject principal: only the principal tells them apart.
        mine = {"scope": scope, "identity": identity("p1", ["p1"])}
        theirs = [{"record_id": "mine", "scope": scope, "identity": identity("p1", ["p1"])}, {"record_id": "theirs", "scope": scope, "identity": identity("p2", ["p1"])}]
        self.assertEqual(self._confined(mine, theirs), ["mine"])

    def test_a_fully_redacted_summary_never_matches(self) -> None:
        self.assertEqual(memory_admission._duplicate_in([{"record_id": "held", "summary": "[redacted]"}], {"summary": "[redacted]"}), "")
        self.assertEqual(memory_admission._similar_wording([{"record_id": "held", "summary": "[redacted]"}], "[redacted]", skip=set()), ("", "", 0))


class RedactedCaptureTests(_Home):
    def test_two_different_secrets_are_not_one_duplicate(self) -> None:
        defaults = {"scope_kind": "project", "scope_ref": self.identity, "source": "hermes_model", "retention_class": "durable", "on_duplicate": "skip"}
        first = capture_project_memory_candidate(self.store, f"The deploy key is {AWS_ACCESS_KEY_ID}", **defaults)
        second = capture_project_memory_candidate(self.store, f"The deploy key is {AWS_TEMPORARY_ACCESS_KEY_ID}", **defaults)
        self.assertTrue(first["captured"], first)
        self.assertTrue(second["captured"], second)
        self.assertNotIn("duplicate_of", second.get("candidate", {}))
        self.assertNotIn("similar_record_id", second)


class HintLensTests(_Home):
    def test_a_shared_surface_never_sees_a_record_its_lens_refuses(self) -> None:
        owner = self.capture("The owner has a therapist appointment on tuesdays at 17:00")
        start(self.store, self.root, "discord-session", platform="discord")
        recall = self.call("recall", session_id="discord-session", query="therapist appointment")
        self.assertNotIn(owner, [row["record_id"] for row in recall.get("records", [])])
        result = self.call("capture", session_id="discord-session", summary="The owner has a therapist appointment on thursdays at 17:00")
        # A shared surface does not capture (#2092); the refusal carries no hint either.
        self.assertEqual((result["status"], result["reason"]), ("refused", "shared_surface_writes_refused"), result)
        for key in ("similar_record_id", "similar_summary", "similar_wording_pct", "subject_held_by", "recalls_now"):
            self.assertNotIn(key, result)
        self.assertNotIn(owner, json.dumps(result))
        self.assertNotIn("tuesdays", json.dumps(result))

    def test_hints_ride_a_pending_review_capture_too(self) -> None:
        held = self.capture("kiwi plum pear lime")
        result = self.call("capture", summary="kiwi plum pear lime yesterday")
        self.assertEqual(result["status"], "pending_review", result)
        self.assertEqual(result["similar_record_id"], held)
        self.assertIn("absolute date", result["next_action"])
        self.assertNotIn("omh memory review", result["next_action"])

    def test_the_subject_sentence_reports_who_recall_actually_serves(self) -> None:
        held = self.capture("Deploys go from the release branch", subject="deploy-branch")
        # A held stamp newer than the capture: the new record loses the subject.
        self.edit_record(held, approved_at="2099-01-01T00:00:00Z")
        result = self.call("capture", summary="Deploys go from main now", subject="deploy-branch")
        new = result["record_id"]
        self.assertEqual(result["recalls_now"], [held])
        self.assertIn(f"{new} does not recall, {held} recalls.", result["next_action"])

    def test_the_similar_sentence_says_a_stale_record_does_not_recall(self) -> None:
        held = self.capture("The staging database runs postgres 16")
        self.edit_record(held, revalidation={"deadline": "2020-01-01T00:00:00Z"}, staleness={"review_due_at": "2020-01-01T00:00:00Z", "stale_after": "2020-01-01T00:00:00Z"})
        result = self.call("capture", summary="The staging database runs postgres 17")
        self.assertEqual(result["similar_record_id"], held)
        self.assertEqual(result["recalls_now"], [result["record_id"]])
        self.assertIn(f"{held} does not recall", result["next_action"])


class CorrectToHeldTests(_Home):
    def _pair(self, **held_capture) -> tuple[str, str]:
        old = self.capture("Deploys go from the release branch on fridays")
        held = self.capture("Deploys go from main", **held_capture)
        self.recalled("deploys release branch fridays main")
        return old, held

    def test_an_archived_held_record_is_not_a_replacement(self) -> None:
        old, held = self._pair()
        self.edit_record(held, attention={"tier": "archive"})
        result = self.call("correct", record_id=old, summary="Deploys go from main")
        self.assertEqual((result["status"], result["supersede_skipped"]), ("already_remembered", "held_not_recallable"), result)
        self.assertTrue(self.record_path(old).is_file())

    def test_a_shorter_lived_held_record_is_not_a_replacement(self) -> None:
        old = self.capture("Deploys go from the release branch on fridays", retention_class="durable")
        held = self.capture("Deploys go from main", retention_class="volatile")
        result = self.call("correct", record_id=old, summary="Deploys go from main")
        self.assertEqual((result["status"], result["supersede_skipped"]), ("already_remembered", "held_retention_shorter"), result)
        self.assertTrue(self.record_path(old).is_file())
        self.assertTrue(self.record_path(held).is_file())

    def test_a_held_record_of_the_same_class_that_expires_sooner_is_not_a_replacement(self) -> None:
        old, held = self._pair()
        self.edit_record(old, retention={"expires_at": "2099-06-01T00:00:00Z"}, ttl={"expires_at": "2099-06-01T00:00:00Z"})
        self.edit_record(held, retention={"expires_at": "2099-01-01T00:00:00Z"}, ttl={"expires_at": "2099-01-01T00:00:00Z"})
        self.assertEqual(self.read_record(old)["retention"]["class"], self.read_record(held)["retention"]["class"])
        result = self.call("correct", record_id=old, summary="Deploys go from main")
        self.assertEqual((result["status"], result["supersede_skipped"]), ("already_remembered", "held_expires_sooner"), result)
        self.assertTrue(self.record_path(old).is_file())

    def test_a_held_record_that_outlives_the_old_one_is_a_replacement(self) -> None:
        old, held = self._pair()
        self.edit_record(old, retention={"expires_at": "2099-01-01T00:00:00Z"}, ttl={"expires_at": "2099-01-01T00:00:00Z"})
        self.edit_record(held, retention={"expires_at": "2099-06-01T00:00:00Z"}, ttl={"expires_at": "2099-06-01T00:00:00Z"})
        result = self.call("correct", record_id=old, summary="Deploys go from main")
        self.assertEqual((result["status"], result["replacement"]), ("corrected", "already_held"), result)

    def test_a_held_record_with_another_subject_is_not_a_replacement(self) -> None:
        old = self.capture("Deploys go from the release branch on fridays", subject="deploy-branch")
        self.capture("Deploys go from main", subject="deploy-source")
        result = self.call("correct", record_id=old, summary="Deploys go from main")
        self.assertEqual(result["supersede_skipped"], "subject_conflict", result)

    def test_the_correction_subject_is_carried_onto_the_held_record(self) -> None:
        old = self.capture("Deploys go from the release branch on fridays", subject="deploy-branch")
        held = self.capture("Deploys go from main")
        result = self.call("correct", record_id=old, summary="Deploys go from main")
        self.assertEqual((result["status"], result["replacement"]), ("corrected", "already_held"), result)
        self.assertEqual(self.read_record(held)["subject"], "deploy-branch")

    def test_the_supersession_is_pinned_locked_and_indexed(self) -> None:
        old, held = self._pair()
        record = self.read_record(old)
        lens = memory_tool._session_lens({"session_id": "session-a"})
        moved = memory_tool._correct_to_held(self.store, {**record, "revision": 7}, held, "Deploys go from main", lens)
        self.assertEqual((moved["status"], moved["supersede_skipped"]), ("already_remembered", "revision_moved"), moved)
        self.assertTrue(self.record_path(old).is_file())
        locked: list[Path] = []
        real_lock = memory_tool.memory_store_lock

        @contextmanager
        def recording_lock(path: Path):
            locked.append(Path(path))
            with real_lock(path):
                yield

        with patch.object(memory_tool, "memory_store_lock", recording_lock):
            done = memory_tool._correct_to_held(self.store, record, held, "Deploys go from main", lens)
        self.assertEqual(done["status"], "corrected", done)
        self.assertIn(self.memory / "index.json", locked)
        index = json.loads((self.memory / "index.json").read_text(encoding="utf-8"))
        self.assertNotIn(f"records/{old}.json", index["record_files"])
        self.assertIn(f"records/{held}.json", index["record_files"])

    def test_a_held_record_that_vanishes_before_the_lock_changes_nothing(self) -> None:
        old, held = self._pair()
        record = self.read_record(old)
        lens = memory_tool._session_lens({"session_id": "session-a"})

        def vanish(*_args, **_kwargs) -> str:
            self.record_path(held).unlink()
            return ""

        with patch.object(memory_tool, "_held_replacement_refusal", vanish):
            result = memory_tool._correct_to_held(self.store, record, held, "Deploys go from main", lens)
        self.assertEqual((result["status"], result["supersede_skipped"]), ("already_remembered", "record_absent"), result)
        self.assertTrue(self.record_path(old).is_file())


if __name__ == "__main__":
    unittest.main()
