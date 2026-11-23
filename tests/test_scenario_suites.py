"""The two scenario suites: corpus schema, held-out isolation, reporting, live gate.

Nothing here calls a model or starts Hermes. The live arm is checked by the
argv it builds, the refusals in front of it, and a run whose process call is
replaced by a stand-in that writes the decision file a child would.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.quality import automation_intent_grading as automation  # noqa: E402
from omh.quality import orchestration_grading as orchestration  # noqa: E402
from omh.quality import scenario_suite as shared  # noqa: E402
from omh.commands.hermes_child_observations import result_payload  # noqa: E402
from omh.quality.reported_rate import reported_rate_shape_errors  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    (automation, ROOT / "benchmarks" / "automation-intent" / "v1", automation.grade_automation_intent),
    (orchestration, ROOT / "benchmarks" / "orchestration" / "v1", orchestration.grade_orchestration),
)


def _load_bench(lane: Path, name: str):
    """Load a lane's thin `bench.py`; its shared runner is `module.runner`."""
    spec = importlib.util.spec_from_file_location(name, lane / "bench.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    original_path = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


def _run(module, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = module.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def _observations(suite_name: str, split: str, rows: list[dict], arm: str = "test-arm") -> dict:
    return {
        "schema_version": shared.OBSERVATIONS_SCHEMA_VERSION,
        "suite": suite_name,
        "split": split,
        "arm": arm,
        "observations": rows,
    }


def _all_rates(report: dict) -> list[dict]:
    rates = [report["headline"]["pass_rate"], report["totals"]["pass_rate"]]
    rates.extend(block["pass_rate"] for block in report.get("per_category", {}).values())
    return rates


def _child_stdout(status: str) -> str:
    """What `omh coding hermes-child dispatch --json` prints, built by its own producer."""
    from argparse import Namespace

    args = Namespace(provider="p", model="m", reasoning="r", parent_run_id="parent", run_id="parent-0001")
    return json.dumps(result_payload(args, status, {}))


class _FakePopen:
    """Stands in for `subprocess.Popen`: `behaviour(argv, prompt)` returns stdout or raises."""

    instances: list["_FakePopen"] = []

    def __init__(self, behaviour, argv, **kwargs):
        self.behaviour = behaviour
        self.argv = argv
        self.kwargs = kwargs
        self.signals: list[str] = []
        self.calls = 0

    def communicate(self, prompt=None, timeout=None):
        self.calls += 1
        if self.calls == 1:
            self.prompt = prompt
            return self.behaviour(self.argv, prompt), ""
        return "", ""

    def terminate(self):
        self.signals.append("terminate")

    def kill(self):
        self.signals.append("kill")


def _popen(behaviour, record: list | None = None):
    """A patch target for `bench.runner.subprocess.Popen` running `behaviour`."""

    def factory(argv, **kwargs):
        process = _FakePopen(behaviour, argv, **kwargs)
        if record is not None:
            record.append(process)
        return process

    return factory


class CorpusSchemaTests(unittest.TestCase):
    def test_both_splits_of_both_suites_are_well_formed(self) -> None:
        for module, lane, _grade in SUITES:
            for split in shared.SPLITS:
                corpus = shared.load_split(lane, split)
                with self.subTest(suite=module.SUITE, split=split):
                    self.assertEqual(shared.corpus_errors(
                        corpus,
                        suite=module.SUITE,
                        split=split,
                        categories=module.CATEGORIES,
                        id_prefix=module.ID_PREFIX,
                        scenario_errors=module.scenario_errors,
                    ), [])

    def test_every_category_has_a_positive_and_the_suites_carry_negatives(self) -> None:
        tuning = shared.load_split(SUITES[0][1], "tuning")["scenarios"] + shared.load_split(SUITES[0][1], "held_out")["scenarios"]
        outcomes = {row["expect"]["outcome"] for row in tuning}
        self.assertEqual(outcomes, set(automation.OUTCOMES))
        orchestration_rows = shared.load_split(SUITES[1][1], "tuning")["scenarios"] + shared.load_split(SUITES[1][1], "held_out")["scenarios"]
        expectations = {row["expect"]["handoff"] for row in orchestration_rows}
        self.assertEqual(expectations, {"required", "forbidden"})
        for module, lane, _grade in SUITES:
            rows = shared.load_split(lane, "tuning")["scenarios"] + shared.load_split(lane, "held_out")["scenarios"]
            for category in module.CATEGORIES:
                with self.subTest(suite=module.SUITE, category=category):
                    self.assertGreaterEqual(sum(1 for row in rows if row["category"] == category), 4)

    def test_malformed_automation_scenarios_are_refused(self) -> None:
        corpus = shared.load_split(SUITES[0][1], "tuning")
        base = next(row for row in corpus["scenarios"] if row["id"] == "ai-edit-move-standup-time")
        broken = []
        missing_expect = copy.deepcopy(base)
        del missing_expect["expect"]
        broken.append(missing_expect)
        wrong_job = copy.deepcopy(base)
        wrong_job["expect"]["automation"]["job_id"] = "job-that-does-not-exist"
        broken.append(wrong_job)
        no_schedule = copy.deepcopy(base)
        no_schedule["expect"]["automation"]["schedule"] = []
        broken.append(no_schedule)
        unknown_filter = copy.deepcopy(base)
        unknown_filter["expect"]["automation"]["filters"] = {"colour": ["red"]}
        broken.append(unknown_filter)
        ask_without_topic = copy.deepcopy(base)
        ask_without_topic["category"] = "ask"
        ask_without_topic["expect"] = {"outcome": "clarifying_question"}
        broken.append(ask_without_topic)
        for scenario in broken:
            with self.subTest(scenario.get("expect")):
                self.assertTrue(automation.scenario_errors(scenario))

    def test_malformed_orchestration_scenarios_are_refused(self) -> None:
        corpus = shared.load_split(SUITES[1][1], "tuning")
        base = next(row for row in corpus["scenarios"] if row["id"] == "orc-links-pr-but-no-ci-run")
        unobserved_citation = copy.deepcopy(base)
        unobserved_citation["expect"]["must_cite"] = ["https://github.com/rlaope/oh-my-hermes/actions/runs/1"]
        no_budget = copy.deepcopy(base)
        del no_budget["expect"]["word_budget"]
        required_without_owner = copy.deepcopy(base)
        required_without_owner["expect"] = {"handoff": "required", "word_budget": 10}
        unknown_repo = copy.deepcopy(base)
        unknown_repo["expect"] = {"handoff": "required", "owner": "codex", "repository": "acme/unknown", "word_budget": 10}
        for scenario in (unobserved_citation, no_budget, required_without_owner, unknown_repo):
            with self.subTest(scenario["expect"]):
                self.assertTrue(orchestration.scenario_errors(scenario))

    def test_corpus_level_errors(self) -> None:
        module, lane, _grade = SUITES[0]
        corpus = shared.load_split(lane, "tuning")
        duplicated = copy.deepcopy(corpus)
        duplicated["scenarios"].append(copy.deepcopy(corpus["scenarios"][0]))
        wrong_split = copy.deepcopy(corpus)
        wrong_split["split"] = "held_out"
        bad_category = copy.deepcopy(corpus)
        bad_category["scenarios"][0]["category"] = "cron"
        for document in (duplicated, wrong_split, bad_category):
            with self.subTest():
                self.assertTrue(shared.corpus_errors(
                    document, suite=module.SUITE, split="tuning", categories=module.CATEGORIES,
                    id_prefix=module.ID_PREFIX, scenario_errors=module.scenario_errors,
                ))

    def test_skill_files_named_by_the_manifests_exist(self) -> None:
        for module, lane, _grade in SUITES:
            manifest = json.loads((lane / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["suite"], module.SUITE)
            self.assertEqual(manifest["status"], "prepared_not_observed")
            self.assertIsNone(manifest["latest_measured"])
            self.assertTrue(manifest["arms"]["skill-text"]["skill_files"])
            self.assertEqual(manifest["arms"]["bare"]["skill_files"], [])
            for name in manifest["arms"]["skill-text"]["skill_files"]:
                with self.subTest(name):
                    self.assertTrue((ROOT / name).is_file())


class HeldOutIsolationTests(unittest.TestCase):
    def test_splits_are_separate_files_disjoint_and_sized(self) -> None:
        for module, lane, _grade in SUITES:
            tuning = shared.load_split(lane, "tuning")
            held_out = shared.load_split(lane, "held-out")
            self.assertNotEqual(shared.split_path(lane, "tuning"), shared.split_path(lane, "held_out"))
            with self.subTest(module.SUITE):
                self.assertEqual(shared.split_isolation_errors(tuning, held_out, categories=module.CATEGORIES), [])

    def test_isolation_check_catches_a_leak(self) -> None:
        module, lane, _grade = SUITES[1]
        tuning = shared.load_split(lane, "tuning")
        held_out = shared.load_split(lane, "held_out")
        leaked = copy.deepcopy(held_out)
        leaked["scenarios"][0]["request"] = "  " + tuning["scenarios"][0]["request"].upper() + " "
        errors = shared.split_isolation_errors(tuning, leaked, categories=module.CATEGORIES)
        self.assertTrue(any("repeated in tuning" in error for error in errors))
        same_id = copy.deepcopy(held_out)
        same_id["scenarios"][0]["id"] = tuning["scenarios"][0]["id"]
        self.assertTrue(any("ids in both" in error for error in shared.split_isolation_errors(tuning, same_id, categories=module.CATEGORIES)))

    def test_default_split_is_tuning_and_unknown_splits_are_refused(self) -> None:
        self.assertEqual(shared.DEFAULT_SPLIT, "tuning")
        self.assertEqual(shared.normalize_split("held-out"), "held_out")
        with self.assertRaises(shared.ScenarioSuiteError):
            shared.normalize_split("all")
        for _module, lane, _grade in SUITES:
            self.assertEqual(shared.load_split(lane)["split"], "tuning")

    def test_held_out_text_never_reaches_skill_text_or_routing_sources(self) -> None:
        held_text: list[str] = []
        for _module, lane, _grade in SUITES:
            for scenario in shared.load_split(lane, "held_out")["scenarios"]:
                held_text.extend([scenario["id"], scenario["request"]])
        roots = [ROOT / "skills", ROOT / "agent-skills", ROOT / "src" / "skills", ROOT / "src" / "routing", ROOT / "src" / "catalogs"]
        sources = [path for root in roots for path in root.rglob("*") if path.is_file() and path.suffix in {".md", ".py", ".json"}]
        sources.append(ROOT / "src" / "quality" / "routing_precision.py")
        self.assertGreater(len(sources), 100)
        for path in sources:
            text = path.read_text(encoding="utf-8", errors="replace")
            for needle in held_text:
                if needle in text:
                    self.fail(f"held-out text {needle!r} appears in {path.relative_to(ROOT)}")

    def test_a_held_out_file_padded_with_infrastructure_failures_is_refused(self) -> None:
        module, lane, grade = SUITES[0]
        corpus = shared.load_split(lane, "held_out")
        first = corpus["scenarios"][0]["id"]
        rows = [{"scenario_id": first, "status": "observed", "decision": {"outcome": "no_automation"}}]
        rows.extend(
            {"scenario_id": row["id"], "status": "infrastructure_failure", "infrastructure_failure": "timeout"}
            for row in corpus["scenarios"][1:]
        )
        with self.assertRaisesRegex(shared.ScenarioSuiteError, "graded"):
            shared.build_suite_report(
                suite=module.SUITE, corpus=corpus, observations=_observations(module.SUITE, "held_out", rows),
                grade=grade, categories=module.CATEGORIES, artifact="held.json",
            )

    def test_held_out_report_at_the_graded_floor_carries_totals_only(self) -> None:
        for module, lane, grade in SUITES:
            corpus = shared.load_split(lane, "held_out")
            ids = [row["id"] for row in corpus["scenarios"]]
            # The smallest graded count the floor allows: three quarters, rounded up.
            graded = -(-len(ids) * 3 // 4)
            rows = [{"scenario_id": item, "status": "observed", "decision": {}} for item in ids[:graded]]
            rows.extend(
                {"scenario_id": item, "status": "infrastructure_failure", "infrastructure_failure": "timeout"}
                for item in ids[graded:]
            )
            report = shared.build_suite_report(
                suite=module.SUITE, corpus=corpus, observations=_observations(module.SUITE, "held_out", rows),
                grade=grade, categories=module.CATEGORIES, artifact="held.json",
            )
            with self.subTest(module.SUITE):
                self.assertEqual(report["scenario_detail"], "withheld_for_held_out_split")
                for key in ("scenarios", "per_category", "per_group"):
                    self.assertNotIn(key, report)
                for item in ids:
                    self.assertNotIn(item, json.dumps(report))
                self.assertEqual(report["totals"]["graded"], graded)
            short = rows[: graded - 1] + [
                {"scenario_id": item, "status": "infrastructure_failure", "infrastructure_failure": "timeout"}
                for item in ids[graded - 1 : graded]
            ] + rows[graded:]
            with self.subTest(module.SUITE, below_floor=True), self.assertRaisesRegex(shared.ScenarioSuiteError, "graded"):
                shared.build_suite_report(
                    suite=module.SUITE, corpus=corpus, observations=_observations(module.SUITE, "held_out", short),
                    grade=grade, categories=module.CATEGORIES, artifact="held.json",
                )

    def test_a_partial_held_out_file_is_refused(self) -> None:
        module, lane, grade = SUITES[1]
        corpus = shared.load_split(lane, "held_out")
        rows = [{"scenario_id": corpus["scenarios"][0]["id"], "status": "observed", "decision": {}}]
        with self.assertRaisesRegex(shared.ScenarioSuiteError, "every one of its"):
            shared.build_suite_report(
                suite=module.SUITE, corpus=corpus, observations=_observations(module.SUITE, "held_out", rows),
                grade=grade, categories=module.CATEGORIES, artifact="x",
            )

    def test_a_file_from_one_split_is_never_graded_against_the_other(self) -> None:
        module, lane, grade = SUITES[0]
        tuning = shared.load_split(lane, "tuning")
        held_id = shared.load_split(lane, "held_out")["scenarios"][0]["id"]
        relabelled = _observations(module.SUITE, "tuning", [{"scenario_id": held_id, "status": "observed", "decision": {}}])
        with self.assertRaisesRegex(shared.ScenarioSuiteError, "does not hold"):
            shared.build_suite_report(suite=module.SUITE, corpus=tuning, observations=relabelled, grade=grade, categories=module.CATEGORIES, artifact="x")
        wrong_split = _observations(module.SUITE, "held_out", [])
        with self.assertRaisesRegex(shared.ScenarioSuiteError, "split must be tuning"):
            shared.build_suite_report(suite=module.SUITE, corpus=tuning, observations=wrong_split, grade=grade, categories=module.CATEGORIES, artifact="x")


class ReportShapeTests(unittest.TestCase):
    def report(self, rows: list[dict], *, suite_index: int = 0, split: str = "tuning") -> dict:
        module, lane, grade = SUITES[suite_index]
        return shared.build_suite_report(
            suite=module.SUITE, corpus=shared.load_split(lane, split),
            observations=_observations(module.SUITE, split, rows), grade=grade,
            categories=module.CATEGORIES, artifact="observations.json",
        )

    def test_empty_observations_report_null_never_zero(self) -> None:
        report = self.report([])
        self.assertEqual(report["headline"]["status"], "prepared_not_observed")
        for rate in _all_rates(report):
            self.assertEqual(reported_rate_shape_errors(rate["rate"]), ())
            self.assertIsNone(rate["rate"]["percent"])
            self.assertEqual(rate["rate"]["basis"], "no_observations")
            self.assertIsNone(rate["wilson_95"])
        self.assertEqual(report["headline"]["pass_rate"]["rate"]["excluded"], ["not_observed"])

    def test_infrastructure_failures_are_named_exclusions_not_failures(self) -> None:
        corpus = shared.load_split(SUITES[0][1], "tuning")
        ids = [row["id"] for row in corpus["scenarios"]]
        rows = [
            {"scenario_id": ids[0], "status": "infrastructure_failure", "infrastructure_failure": "timeout"},
            {"scenario_id": ids[1], "status": "infrastructure_failure", "infrastructure_failure": "transport_error"},
            {"scenario_id": ids[2], "status": "infrastructure_failure", "infrastructure_failure": "arm_did_not_run"},
        ]
        report = self.report(rows)
        totals = report["totals"]
        self.assertEqual((totals["graded"], totals["passed"], totals["failed"]), (0, 0, 0))
        self.assertEqual(totals["excluded_counts"], {"arm_did_not_run": 1, "timeout": 1, "transport_error": 1, "not_observed": len(ids) - 3})
        self.assertEqual(report["headline"]["pass_rate"]["rate"]["excluded"], list(shared.EXCLUDED_CLASSES))
        self.assertIsNone(report["headline"]["pass_rate"]["rate"]["percent"])

    def test_graded_rates_are_well_formed_with_named_numerator_and_interval(self) -> None:
        report = self.report(json.loads((SUITES[0][1] / "fixtures" / "recorded-observations.json").read_text(encoding="utf-8"))["observations"])
        for rate in _all_rates(report):
            self.assertEqual(reported_rate_shape_errors(rate["rate"]), ())
            self.assertEqual(rate["rate"]["numerator_of"], ["passed"])
        headline = report["headline"]
        self.assertEqual(headline["status"], "observed")
        for key in ("arm", "corpus", "split", "corpus_digest", "selection_rule", "artifact", "artifact_digest"):
            self.assertTrue(headline[key], key)
        self.assertEqual(headline["corpus_digest"], shared.canonical_digest(shared.load_split(SUITES[0][1], "tuning")))
        fixture_rows = json.loads((SUITES[0][1] / "fixtures" / "recorded-observations.json").read_text(encoding="utf-8"))["observations"]
        split_size = len(shared.load_split(SUITES[0][1], "tuning")["scenarios"])
        self.assertTrue(
            headline["selection_rule"].startswith(f"{len(fixture_rows)} of the {split_size} scenarios in the tuning split observed"),
            headline["selection_rule"],
        )
        interval = headline["pass_rate"]["wilson_95"]
        self.assertLessEqual(interval["low"], headline["pass_rate"]["rate"]["percent"])
        self.assertGreaterEqual(interval["high"], headline["pass_rate"]["rate"]["percent"])

    def test_tuning_report_separates_skill_rule_scenarios(self) -> None:
        for index, (module, lane, _grade) in enumerate(SUITES):
            corpus = shared.load_split(lane, "tuning")
            rows = [{"scenario_id": row["id"], "status": "observed", "decision": {}} for row in corpus["scenarios"]]
            report = self.report(rows, suite_index=index)
            groups = report["per_group"]
            ruled = sum(1 for row in corpus["scenarios"] if row.get("skill_rule"))
            with self.subTest(module.SUITE):
                self.assertEqual(set(groups), {"request_derivable", "skill_rule"})
                self.assertEqual(groups["skill_rule"]["scenarios"], ruled)
                self.assertGreater(ruled, 0)
                self.assertEqual(groups["request_derivable"]["scenarios"], len(corpus["scenarios"]) - ruled)
                for block in groups.values():
                    self.assertEqual(reported_rate_shape_errors(block["pass_rate"]["rate"]), ())
                rows_by_id = {row["scenario_id"]: row for row in report["scenarios"]}
                for row in corpus["scenarios"]:
                    expected = "skill_rule" if row.get("skill_rule") else "request_derivable"
                    self.assertEqual(rows_by_id[row["id"]]["group"], expected)

    def test_observations_file_errors_are_named(self) -> None:
        module = SUITES[0][0]
        bad = _observations(module.SUITE, "tuning", [
            {"scenario_id": "a", "status": "observed"},
            {"scenario_id": "a", "status": "infrastructure_failure", "infrastructure_failure": "oom", "decision": {}},
            {"scenario_id": "b", "status": "skipped"},
        ])
        errors = shared.observations_errors(bad, suite=module.SUITE, split="tuning")
        joined = "; ".join(errors)
        for fragment in ("decision must be an object", "observed twice", "infrastructure_failure must be one of", "must carry no decision", "status must be one of"):
            self.assertIn(fragment, joined)


class WilsonIntervalTests(unittest.TestCase):
    def test_known_values(self) -> None:
        self.assertIsNone(shared.wilson_interval(0, 0))
        self.assertEqual(shared.wilson_interval(0, 10), {"low": 0.0, "high": 27.8, "confidence": 0.95})
        self.assertEqual(shared.wilson_interval(10, 10), {"low": 72.2, "high": 100.0, "confidence": 0.95})
        self.assertEqual(shared.wilson_interval(5, 10), {"low": 23.7, "high": 76.3, "confidence": 0.95})
        with self.assertRaises(ValueError):
            shared.wilson_interval(3, 2)


class DispatchClassificationTests(unittest.TestCase):
    completed = _child_stdout("completed")
    failed = _child_stdout("failed")

    def classify(self, **kwargs) -> dict:
        values = {"launched": True, "timed_out": False, "stdout": self.completed, "decision": None, "decision_keys": ("reply",)}
        values.update(kwargs)
        return shared.observation_from_dispatch("s", **values)

    def test_classes(self) -> None:
        self.assertEqual(self.classify(launched=False)["infrastructure_failure"], "arm_did_not_run")
        self.assertEqual(self.classify(stdout="")["infrastructure_failure"], "arm_did_not_run")
        self.assertEqual(self.classify(timed_out=True, stdout="")["infrastructure_failure"], "timeout")
        self.assertEqual(self.classify(stdout=_child_stdout("timed_out"))["infrastructure_failure"], "timeout")
        self.assertEqual(
            self.classify(stdout=_child_stdout("timed_out"), decision={"reply": "late"})["infrastructure_failure"], "timeout"
        )
        self.assertEqual(self.classify(stdout=_child_stdout("cancelled"))["infrastructure_failure"], "transport_error")
        self.assertEqual(self.classify(stdout=self.failed)["infrastructure_failure"], "transport_error")

    def test_an_infrastructure_failure_keeps_a_short_reason(self) -> None:
        row = self.classify(stdout=self.failed, reason=".omh-scenario-decision.json was not written")
        self.assertEqual(row["infrastructure_failure"], "transport_error")
        self.assertEqual(row["reason"], "child status failed; .omh-scenario-decision.json was not written")
        long = self.classify(launched=False, reason="x" * 1000)
        self.assertLessEqual(len(long["reason"]), shared.MAX_REASON_CHARS)
        self.assertEqual(shared.observations_errors(
            _observations("s", "tuning", [long]), suite="s", split="tuning"), [])
        graded = self.classify(decision={"reply": "ok"}, reason="")
        self.assertNotIn("reason", graded)

    def test_non_terminal_or_refused_status_without_a_decision_did_not_run(self) -> None:
        for status in ("prepared", "running", "dispatched"):
            with self.subTest(status):
                self.assertEqual(self.classify(stdout=_child_stdout(status))["infrastructure_failure"], "arm_did_not_run")
        self.assertEqual(self.classify(stdout="omh: refused")["infrastructure_failure"], "arm_did_not_run")

    def test_completed_without_a_decision_is_graded_not_excluded(self) -> None:
        row = self.classify()
        self.assertEqual(row, {"scenario_id": "s", "status": "observed", "decision": {}})
        self.assertEqual(shared.child_status(_child_stdout("completed")), "completed")

    def test_decision_is_narrowed_and_evidence_comes_from_the_harness(self) -> None:
        row = self.classify(decision={"reply": "ok", "evidence_links": ["https://x"], "notes": "free text"}, evidence_links=["https://y"])
        self.assertEqual(row["decision"], {"reply": "ok"})
        self.assertEqual(row["evidence_links"], ["https://y"])
        failed_with_decision = self.classify(stdout=self.failed, decision={"reply": "ok"})
        self.assertEqual(failed_with_decision["status"], "observed")


class DecisionFileReasonTests(unittest.TestCase):
    def test_an_unreadable_decision_file_reason_names_no_path(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "private-user" / "ws"
            workspace.mkdir(parents=True)
            target = workspace / shared.DECISION_FILENAME
            for content in (b"{not json", b"[1, 2]", b"x" * (shared.MAX_DECISION_FILE_BYTES + 1)):
                target.write_bytes(content)
                decision, reason = shared.read_decision_file(workspace)
                with self.subTest(content[:8]):
                    self.assertIsNone(decision)
                    self.assertIn(shared.DECISION_FILENAME, reason)
                    self.assertNotIn(tmp, reason)
                    self.assertNotIn("private-user", reason)


class PromptAndArgvTests(unittest.TestCase):
    def test_prompt_shows_neither_the_answer_nor_the_label(self) -> None:
        for module, lane, _grade in SUITES:
            for split in shared.SPLITS:
                for scenario in shared.load_split(lane, split)["scenarios"]:
                    view = module.arm_view(scenario)
                    prompt = shared.scenario_prompt(
                        suite_instructions=module.SUITE_INSTRUCTIONS,
                        decision_contract=module.DECISION_CONTRACT,
                        view=view,
                    )
                    with self.subTest(scenario["id"]):
                        self.assertNotIn("expect", view)
                        self.assertNotIn("why", view)
                        self.assertNotIn(scenario["id"], prompt)
                        self.assertNotIn(scenario["why"], prompt)
                        self.assertIn(shared.DECISION_FILENAME, prompt)
                        self.assertIn(scenario["request"], prompt)

    def test_orchestration_arm_sees_its_word_budget_but_not_the_owner_record(self) -> None:
        for split in shared.SPLITS:
            for scenario in shared.load_split(SUITES[1][1], split)["scenarios"]:
                view = orchestration.arm_view(scenario)
                with self.subTest(scenario["id"]):
                    self.assertEqual(view["reply_word_budget"], scenario["expect"]["word_budget"])
                    self.assertNotIn("coding_owner_choice", view["prior_state"])
                    self.assertNotIn("coding_owner_choice", json.dumps(view))
        self.assertIn("Keep the reply within reply_word_budget words", orchestration.DECISION_CONTRACT)

    def test_skill_text_arm_inlines_the_named_files_and_bare_does_not(self) -> None:
        bench = _load_bench(SUITES[0][1], "scenario_bench_automation")
        texts = bench.runner.skill_texts(SUITES[0][1], "skill-text")
        self.assertEqual([name for name, _ in texts], json.loads((SUITES[0][1] / "manifest.json").read_text(encoding="utf-8"))["arms"]["skill-text"]["skill_files"])
        self.assertEqual(bench.runner.skill_texts(SUITES[0][1], "bare"), [])
        prompt = shared.scenario_prompt(suite_instructions="i", decision_contract="c", view={"request": "r"}, skill_texts=texts)
        self.assertIn("--- skills/omh-automation-blueprint/SKILL.md ---", prompt)
        self.assertNotEqual(shared.skill_texts_digest(texts), shared.skill_texts_digest([]))

    def test_oversized_prompt_is_refused(self) -> None:
        with self.assertRaises(shared.ScenarioSuiteError):
            shared.scenario_prompt(suite_instructions="i", decision_contract="c", view={"request": "x" * (shared.MAX_PROMPT_BYTES + 1)})

    def test_child_argv_is_the_confirmed_child_boundary_without_the_prompt(self) -> None:
        argv = shared.child_dispatch_argv(
            "omh", hermes_executable="hermes", workspace=Path("/tmp/w"), model="m", provider="p",
            reasoning="r", parent_run_id="parent", run_id="parent-0001", timeout=60,
        )
        self.assertEqual(argv[:5], ["omh", "coding", "hermes-child", "dispatch", "--confirm-dispatch"])
        self.assertNotIn("--prompt", " ".join(argv))
        self.assertEqual(argv[argv.index("--cwd") + 1], str(Path("/tmp/w")))


class BenchCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.benches = [
            (module, lane, _load_bench(lane, f"scenario_bench_{index}"))
            for index, (module, lane, _grade) in enumerate(SUITES)
        ]

    def test_validate_passes_and_pins_the_corpus(self) -> None:
        for module, _lane, bench in self.benches:
            code, out, _err = _run(bench, ["validate"])
            with self.subTest(module.SUITE):
                self.assertEqual(code, 0, out)
                self.assertTrue(json.loads(out)["valid"])

    def test_fixture_grades_to_its_pinned_counts(self) -> None:
        # The fixture measures nothing; these pins catch grader drift.
        expected = {automation.SUITE: (14, 5), orchestration.SUITE: (12, 5)}
        for module, lane, bench in self.benches:
            code, out, _err = _run(bench, ["grade", "--observations", str(lane / "fixtures" / "recorded-observations.json")])
            totals = json.loads(out)["totals"]
            with self.subTest(module.SUITE):
                self.assertEqual(code, 0)
                self.assertEqual((totals["graded"], totals["passed"]), expected[module.SUITE])

    def test_grading_a_tuning_file_as_held_out_is_refused(self) -> None:
        module, lane, bench = self.benches[0]
        code, _out, err = _run(bench, ["grade", "--split", "held-out", "--observations", str(lane / "fixtures" / "recorded-observations.json")])
        self.assertEqual(code, 2)
        self.assertIn("split must be held_out", err)

    def test_live_run_refuses_without_every_gate_and_spawns_nothing(self) -> None:
        _module, _lane, bench = self.benches[0]
        with TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "obs.json")
            common = ["run", "--arm", "a", "--arm-kind", "bare", "--model", "m", "--provider", "p", "--reasoning", "r", "--output", output, "--workspace", tmp]
            attempts = [
                common,
                [*common, "--allow-paid-live"],
                [*common, "--allow-paid-live", "--max-paid-calls", "100"],
                [*common, "--allow-paid-live", "--max-paid-calls", "2", "--confirm"],
            ]
            with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=AssertionError("spawned")) as spawn:
                for argv in attempts:
                    code, _out, err = _run(bench, argv)
                    with self.subTest(argv[len(common):]):
                        self.assertEqual(code, 2)
                        self.assertTrue(err)
                spawn.assert_not_called()
            self.assertFalse(Path(output).exists())
            held_id = shared.load_split(SUITES[0][1], "held_out")["scenarios"][0]["id"]
            held = [*common, "--split", "held-out", "--scenario", held_id, "--allow-paid-live", "--max-paid-calls", "1", "--confirm"]
            with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=AssertionError("spawned")) as spawn:
                code, _out, err = _run(bench, held)
                spawn.assert_not_called()
            self.assertEqual(code, 2)
            self.assertIn("held-out", err)

    def test_live_run_refuses_a_workspace_inside_the_checkout(self) -> None:
        _module, lane, bench = self.benches[1]
        with TemporaryDirectory() as tmp:
            argv = ["run", "--arm", "a", "--arm-kind", "bare", "--scenario", "orc-handoff-codex-named-in-request",
                    "--model", "m", "--provider", "p", "--reasoning", "r", "--workspace", str(lane / "artifacts" / "ws"),
                    "--output", str(Path(tmp) / "o.json"), "--allow-paid-live", "--max-paid-calls", "1", "--confirm"]
            with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=AssertionError("spawned")) as spawn:
                code, _out, err = _run(bench, argv)
                spawn.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("inside this checkout", err)
        self.assertFalse((lane / "artifacts" / "ws").exists())

    def test_a_dispatcher_that_ignores_sigterm_is_killed_after_the_grace(self) -> None:
        _module, _lane, bench = self.benches[0]

        class Stubborn(_FakePopen):
            def communicate(self, prompt=None, timeout=None):
                self.calls += 1
                if self.calls <= 2:
                    raise subprocess.TimeoutExpired(self.argv, timeout or 0)
                return "", ""

        processes: list = []

        def factory(argv, **kwargs):
            process = Stubborn(None, argv, **kwargs)
            processes.append(process)
            return process

        with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=factory):
            self.assertEqual(bench.runner._dispatch(["omh"], "prompt", 1), (True, True, ""))
        self.assertEqual(processes[0].signals, ["terminate", "kill"])

    def test_a_default_workspace_root_inside_the_checkout_is_refused(self) -> None:
        for _module, lane, bench in self.benches:
            inside = lane / "artifacts" / "tmp-root"
            with TemporaryDirectory() as tmp:
                argv = ["run", "--arm", "a", "--arm-kind", "bare", "--model", "m", "--provider", "p", "--reasoning", "r",
                        "--output", str(Path(tmp) / "o.json"), "--allow-paid-live", "--max-paid-calls", "100", "--confirm"]
                with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=AssertionError("spawned")) as spawn, \
                        mock.patch.object(bench.runner.tempfile, "mkdtemp", return_value=str(inside)):
                    code, _out, err = _run(bench, argv)
                    spawn.assert_not_called()
            with self.subTest(str(lane)):
                self.assertEqual(code, 2)
                self.assertIn("inside this checkout", err)
                self.assertFalse(inside.exists())

    def test_child_io_is_utf8_whatever_the_locale(self) -> None:
        _module, _lane, bench = self.benches[0]
        processes: list = []
        with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=_popen(lambda argv, prompt: "", processes)):
            bench.runner._dispatch(["omh"], "매일 아침 9시", 5)
        kwargs = processes[0].kwargs
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["env"]["PYTHONIOENCODING"], "utf-8")

    def test_both_lanes_run_through_one_shared_runner(self) -> None:
        runners = {id(bench.runner) for _module, _lane, bench in self.benches}
        self.assertEqual(len(runners), 1)
        for _module, lane, _bench in self.benches:
            source = (lane / "bench.py").read_text(encoding="utf-8")
            with self.subTest(str(lane)):
                self.assertNotIn("import subprocess", source)
                self.assertLess(len(source.splitlines()), 40)

    def test_report_artifact_path_is_repository_relative_or_a_bare_name(self) -> None:
        for _module, lane, bench in self.benches[:1]:
            fixture = lane / "fixtures" / "recorded-observations.json"
            _code, out, _err = _run(bench, ["grade", "--observations", str(fixture.resolve())])
            self.assertEqual(json.loads(out)["headline"]["artifact"], fixture.relative_to(ROOT).as_posix())
            with TemporaryDirectory() as tmp:
                outside = Path(tmp) / "private-name.json"
                outside.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
                _code, out, _err = _run(bench, ["grade", "--observations", str(outside)])
            artifact = json.loads(out)["headline"]["artifact"]
            self.assertEqual(artifact, "outside-repository:private-name.json")
            self.assertNotIn(tmp, artifact)

    def test_live_run_ids_are_unique_per_invocation(self) -> None:
        _module, _lane, bench = self.benches[0]
        run_ids: list[str] = []

        def fake_run(argv, prompt):
            run_ids.append(argv[argv.index("--run-id") + 1])
            return _child_stdout("completed")

        with TemporaryDirectory() as tmp:
            for attempt in ("a", "b"):
                argv = ["run", "--arm", "a", "--arm-kind", "bare", "--scenario", "ai-ask-daily-without-time",
                        "--model", "m", "--provider", "p", "--reasoning", "r", "--workspace", str(Path(tmp) / "ws"),
                        "--output", str(Path(tmp) / f"{attempt}.json"), "--allow-paid-live", "--max-paid-calls", "1", "--confirm"]
                with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=_popen(fake_run)):
                    code, _out, err = _run(bench, argv)
                self.assertEqual(code, 0, err)
        self.assertEqual(len(set(run_ids)), 2)

    def test_two_default_runs_succeed_with_workspaces_outside_the_checkout(self) -> None:
        _module, _lane, bench = self.benches[1]
        workspaces: list[Path] = []
        real_mkdtemp = bench.runner.tempfile.mkdtemp

        def fake_run(argv, prompt):
            workspaces.append(Path(argv[argv.index("--cwd") + 1]))
            return _child_stdout("completed")

        with TemporaryDirectory() as tmp:
            def mkdtemp(prefix: str = "") -> str:
                # The default is the system temp directory; root it in this test's own.
                return real_mkdtemp(prefix=prefix, dir=tmp)

            for attempt in ("first", "second"):
                argv = ["run", "--arm", "a", "--arm-kind", "bare", "--scenario", "orc-handoff-codex-named-in-request",
                        "--model", "m", "--provider", "p", "--reasoning", "r",
                        "--output", str(Path(tmp) / f"{attempt}.json"), "--allow-paid-live", "--max-paid-calls", "1", "--confirm"]
                with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=_popen(fake_run)), \
                        mock.patch.object(bench.runner.tempfile, "mkdtemp", side_effect=mkdtemp) as made:
                    code, _out, err = _run(bench, argv)
                self.assertEqual(code, 0, err)
                made.assert_called_once()
            self.assertEqual(len(workspaces), 2)
            self.assertEqual(len(set(workspaces)), 2)
            for workspace in workspaces:
                self.assertFalse(workspace.resolve().is_relative_to(ROOT.resolve()), workspace)

    def test_live_run_records_observations_through_the_child_command(self) -> None:
        module, lane, bench = self.benches[1]
        scenario_id = "orc-handoff-codex-named-in-request"
        calls: list[dict] = []

        def fake_run(argv, prompt):
            calls.append({"argv": argv, "input": prompt})
            workspace = Path(argv[argv.index("--cwd") + 1])
            decision = {
                "handoffs": [{"owner": "codex", "repository": "rlaope/oh-my-hermes"}],
                "parent_edits": [],
                "reply": "Handed to Codex.",
                "evidence_links": ["https://invented.example"],
            }
            (workspace / shared.DECISION_FILENAME).write_text(json.dumps(decision), encoding="utf-8")
            return _child_stdout("completed")

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "obs.json"
            argv = [
                "run", "--arm", "pilot", "--arm-kind", "skill-text", "--scenario", scenario_id,
                "--model", "m", "--provider", "p", "--reasoning", "r", "--workspace", str(Path(tmp) / "ws"),
                "--output", str(output), "--allow-paid-live", "--max-paid-calls", "1", "--confirm",
            ]
            processes: list = []
            with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=_popen(fake_run, processes)):
                code, _out, err = _run(bench, argv)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(calls), 1)
            self.assertEqual(processes[0].kwargs["stdin"], subprocess.PIPE)
            call = calls[0]
            self.assertEqual(call["argv"][:5], ["omh", "coding", "hermes-child", "dispatch", "--confirm-dispatch"])
            self.assertIn("skills/dag-ulw/SKILL.md", call["input"])
            self.assertNotIn(call["input"], " ".join(call["argv"]))
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["run"]["arm_kind"], "skill-text")
            self.assertEqual(len(document["run"]["skill_digest"]), 64)
            row = document["observations"][0]
            self.assertEqual(row["status"], "observed")
            self.assertNotIn("evidence_links", row["decision"])
            code, out, _err = _run(bench, ["grade", "--observations", str(output)])
            report = json.loads(out)
            self.assertEqual((report["totals"]["graded"], report["totals"]["passed"]), (1, 1))
            self.assertEqual(report["arm"], "pilot")

    def test_live_run_records_infrastructure_failures(self) -> None:
        _module, _lane, bench = self.benches[0]
        scenario_ids = ["ai-schedule-weekday-morning-status", "ai-schedule-every-two-hours-feed"]
        processes: list = []
        launches = iter(["timeout", "missing"])

        def timing_out(argv, prompt):
            raise subprocess.TimeoutExpired(argv, 1)

        def factory(argv, **kwargs):
            if next(launches) == "missing":
                raise FileNotFoundError("omh")
            process = _FakePopen(timing_out, argv, **kwargs)
            processes.append(process)
            return process

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "obs.json"
            argv = ["run", "--arm", "pilot", "--arm-kind", "bare", "--model", "m", "--provider", "p", "--reasoning", "r",
                    "--workspace", str(Path(tmp) / "ws"), "--output", str(output),
                    "--allow-paid-live", "--max-paid-calls", "2", "--confirm"]
            for scenario_id in scenario_ids:
                argv.extend(["--scenario", scenario_id])
            with mock.patch.object(bench.runner.subprocess, "Popen", side_effect=factory):
                code, _out, err = _run(bench, argv)
            self.assertEqual(code, 0, err)
            rows = json.loads(output.read_text(encoding="utf-8"))["observations"]
            self.assertEqual([row.get("infrastructure_failure") for row in rows], ["timeout", "arm_did_not_run"])
            # A timed-out dispatcher gets SIGTERM first, so it can stop its own Hermes child.
            self.assertEqual(processes[0].signals, ["terminate"])


if __name__ == "__main__":
    unittest.main()
