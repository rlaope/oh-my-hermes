"""The review false-alarm trap benchmark: corpus schema, verdict grading, and the table.

Nothing here calls a model or starts Hermes. The live harness is checked by the
argv it builds and the files it stages.
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Iterator
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "benchmarks" / "review-false-alarms"
LANE_LIB = LANE / "lib"
CORPUS = LANE / "corpus"
FIXTURE = LANE / "fixtures" / "recorded-verdicts.json"
LIB_NAMES = ("rfa_grading", "rfa_report", "rfa_harness")


@contextmanager
def _lane_import_scope() -> Iterator[None]:
    """Import the lane's modules by bare name, then restore sys.path and sys.modules."""

    saved = {name: sys.modules.get(name) for name in LIB_NAMES}
    original_path = list(sys.path)
    for name in LIB_NAMES:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(LANE_LIB))
    try:
        yield
    finally:
        sys.path[:] = original_path
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: a dataclass looks its own module up by name.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


with _lane_import_scope():
    grading = _load(LANE_LIB / "rfa_grading.py", "rfa_grading")
    report = _load(LANE_LIB / "rfa_report.py", "rfa_report")
    harness = _load(LANE_LIB / "rfa_harness.py", "rfa_harness")
    bench = _load(LANE / "bench.py", "rfa_bench")
    analyze = _load(LANE / "analyze.py", "rfa_analyze")
    sys.modules.pop("rfa_bench", None)
    sys.modules.pop("rfa_analyze", None)


def _run(module, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(argv)
    return code, out.getvalue(), err.getvalue()


def _control(line: int = 10, path: str = "app/x.py"):
    return grading.Case("c", "control", "python", "bug", "why", path, line, Path("c"))


TRAP = grading.Case("t", "trap", "python", "clean", "why", None, None, Path("t"))


class CorpusSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = grading.load_corpus(CORPUS)

    def test_corpus_has_the_minimum_traps_and_controls(self) -> None:
        kinds = [case.kind for case in self.cases.values()]
        self.assertGreaterEqual(kinds.count("trap"), 10)
        self.assertGreaterEqual(kinds.count("control"), 5)

    def test_every_case_directory_has_exactly_the_three_entries(self) -> None:
        for directory in sorted(path for path in CORPUS.iterdir() if path.is_dir()):
            with self.subTest(case=directory.name):
                self.assertEqual(
                    sorted(path.name for path in directory.iterdir()),
                    ["case.json", "context", "diff.patch"],
                )
                self.assertTrue(any((directory / "context").rglob("*")))

    def test_only_the_corpus_patches_skip_the_whitespace_gate(self) -> None:
        # A patch keeps the leading space of a blank context line, which the CI
        # `git diff --check` reads as trailing whitespace. Only the corpus
        # patches opt out; the harness code and the context files stay checked.
        patches = sorted(path.relative_to(ROOT).as_posix() for path in CORPUS.glob("*/diff.patch"))
        checked = [
            (LANE / "bench.py").relative_to(ROOT).as_posix(),
            (LANE_LIB / "rfa_harness.py").relative_to(ROOT).as_posix(),
            next(path for path in CORPUS.glob("*/context/**/*") if path.is_file()).relative_to(ROOT).as_posix(),
            "tests/test_review_false_alarms_benchmark.py",
        ]
        result = subprocess.run(
            ["git", "check-attr", "whitespace", "--", *patches, *checked],
            cwd=ROOT, capture_output=True, text=True, timeout=20, check=True,
        )
        values = dict(line.rsplit(": whitespace: ", 1) for line in result.stdout.splitlines())
        self.assertEqual({path: values[path] for path in patches}, {path: "unset" for path in patches})
        self.assertEqual({path: values[path] for path in checked}, {path: "unspecified" for path in checked})

    def test_every_case_expected_matches_its_kind(self) -> None:
        for case in self.cases.values():
            with self.subTest(case=case.id):
                self.assertEqual(case.expected, {"trap": "clean", "control": "bug"}[case.kind])
                self.assertTrue(case.id.startswith(f"{case.kind}-"))

    def test_bug_location_only_on_controls_and_points_into_context(self) -> None:
        for case in self.cases.values():
            with self.subTest(case=case.id):
                record = json.loads((case.directory / "case.json").read_text(encoding="utf-8"))
                if case.kind == "trap":
                    self.assertNotIn("bug_location", record)
                    continue
                target = case.directory / "context" / case.bug_path
                self.assertTrue(target.is_file())
                lines = target.read_text(encoding="utf-8").splitlines()
                self.assertLessEqual(case.bug_line, len(lines))
                self.assertTrue(lines[case.bug_line - 1].strip())

    def test_every_diff_touches_only_context_files_and_matches_them(self) -> None:
        """Each `+` line of a hunk is the post-change file's line at that number."""

        header = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
        for case in self.cases.values():
            with self.subTest(case=case.id):
                patch = (case.directory / "diff.patch").read_text(encoding="utf-8")
                paths = re.findall(r"^\+\+\+ b/(\S+)$", patch, flags=re.MULTILINE)
                self.assertTrue(paths)
                current: list[str] = []
                line_no = 0
                for raw in patch.splitlines():
                    if raw.startswith("+++ b/"):
                        current = (case.directory / "context" / raw[6:]).read_text(encoding="utf-8").splitlines()
                    elif raw.startswith("---"):
                        continue
                    elif match := header.match(raw):
                        line_no = int(match.group(1))
                    elif raw.startswith("+") or raw.startswith(" "):
                        self.assertEqual(current[line_no - 1], raw[1:], f"line {line_no}")
                        line_no += 1

    def test_control_bug_line_is_a_changed_line(self) -> None:
        """The bug is in the change itself, not somewhere the diff never touched."""

        header = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
        for case in self.cases.values():
            if case.kind != "control":
                continue
            with self.subTest(case=case.id):
                added: set[int] = set()
                path = None
                line_no = 0
                for raw in (case.directory / "diff.patch").read_text(encoding="utf-8").splitlines():
                    if raw.startswith("+++ b/"):
                        path = raw[6:]
                    elif raw.startswith("---"):
                        continue
                    elif match := header.match(raw):
                        line_no = int(match.group(1))
                    elif raw.startswith("+"):
                        if path == case.bug_path:
                            added.add(line_no)
                        line_no += 1
                    elif raw.startswith(" "):
                        line_no += 1
                self.assertIn(case.bug_line, added)

    def test_schema_rejects_each_broken_record(self) -> None:
        good = {
            "id": "control-x", "kind": "control", "language": "python", "expected": "bug",
            "bug_location": {"path": "a.py", "line": 3}, "why": "because",
        }
        directory = Path("control-x")
        grading.case_from_record(good, directory)
        broken = [
            {**good, "kind": "probe"},
            {**good, "expected": "clean"},
            {key: value for key, value in good.items() if key != "bug_location"},
            {**good, "bug_location": {"path": "a.py", "line": 0}},
            {**good, "bug_location": {"path": "a.py", "line": True}},
            {**good, "why": ""},
            {**good, "id": "control-y"},
            {**good, "extra": 1},
            {"id": "control-x", "kind": "trap", "language": "python", "expected": "clean",
             "why": "w", "bug_location": {"path": "a.py", "line": 3}},
        ]
        for record in broken:
            with self.subTest(record=record), self.assertRaises(grading.CorpusError):
                grading.case_from_record(record, directory)


class VerdictExtractionTests(unittest.TestCase):
    def test_clean_and_bug_forms(self) -> None:
        self.assertEqual(grading.extract_verdict("ok\n\nVERDICT: clean").kind, "clean")
        self.assertEqual(grading.extract_verdict("VERDICT: Clean  ").kind, "clean")
        verdict = grading.extract_verdict("bad\nVERDICT: bug app/x.py:12\n\n")
        self.assertEqual((verdict.kind, verdict.path, verdict.line), ("bug", "app/x.py", 12))

    def test_markdown_wrapping_and_path_prefixes_are_accepted(self) -> None:
        for text, path in (
            ("**VERDICT: bug `app/x.py:7`**", "app/x.py"),
            ("- VERDICT: bug context/app/x.py:7", "app/x.py"),
            ("`VERDICT: bug ./b/app/x.py:7`", "app/x.py"),
            ("VERDICT: bug app/x.py:7\n```", "app/x.py"),
        ):
            with self.subTest(text=text):
                verdict = grading.extract_verdict(text)
                self.assertEqual((verdict.kind, verdict.path, verdict.line), ("bug", path, 7))

    def test_missing_garbled_and_non_final_verdicts_are_no_verdict(self) -> None:
        cases = {
            "": "empty_output",
            None: "empty_output",
            "   \n\n": "empty_output",
            "Looks fine to me.": "no_verdict_line",
            "VERDICT: clean\n\nActually, line 4 is wrong.": "no_verdict_line",
            "VERDICT: maybe": "garbled_verdict",
            "VERDICT: bug app/x.py": "garbled_verdict",
            "VERDICT: bug app/x.py:0": "garbled_verdict",
            "VERDICT: bug app/x.py:12 and app/y.py:3": "garbled_verdict",
            "VERDICT: clean, mostly": "garbled_verdict",
        }
        for text, reason in cases.items():
            with self.subTest(text=text):
                verdict = grading.extract_verdict(text)
                self.assertEqual((verdict.kind, verdict.reason), ("none", reason))


class GradingTests(unittest.TestCase):
    def test_trap_outcomes(self) -> None:
        self.assertEqual(grading.grade(TRAP, grading.extract_verdict("VERDICT: clean")), "clean_ok")
        self.assertEqual(grading.grade(TRAP, grading.extract_verdict("VERDICT: bug a.py:1")), "false_alarm")
        self.assertEqual(grading.grade(TRAP, grading.extract_verdict("no line")), "no_verdict")

    def test_control_window_is_plus_minus_three_inclusive(self) -> None:
        case = _control(line=10)
        for line, outcome in ((7, "hit"), (10, "hit"), (13, "hit"), (6, "miss_location"), (14, "miss_location")):
            with self.subTest(line=line):
                verdict = grading.extract_verdict(f"VERDICT: bug app/x.py:{line}")
                self.assertEqual(grading.grade(case, verdict), outcome)

    def test_control_wrong_path_clean_and_missing(self) -> None:
        case = _control(line=10)
        self.assertEqual(grading.grade(case, grading.extract_verdict("VERDICT: bug app/y.py:10")), "miss_location")
        self.assertEqual(grading.grade(case, grading.extract_verdict("VERDICT: clean")), "miss_clean")
        self.assertEqual(grading.grade(case, grading.extract_verdict("VERDICT: bug")), "no_verdict")

    def test_no_verdict_is_never_counted_clean(self) -> None:
        graded = [
            {"arm": "omh-on", "case": "t", "kind": "trap", "run": 1, "outcome": "no_verdict"},
            {"arm": "omh-on", "case": "c", "kind": "control", "run": 1, "outcome": "no_verdict"},
        ]
        row = report.summarize(graded)["omh-on"]
        self.assertEqual((row["false_alarms"], row["trap_runs"]), (0, 1))
        self.assertEqual((row["hits"], row["control_runs"]), (0, 1))
        self.assertEqual((row["no_verdict_traps"], row["no_verdict_controls"]), (1, 1))

    def test_records_reject_duplicates_unknown_cases_and_arms(self) -> None:
        cases = {"t": TRAP}
        record = {"arm": "omh-on", "case": "t", "run": 1, "output": "VERDICT: clean"}
        with self.assertRaises(ValueError):
            grading.grade_records(cases, [record, dict(record)])
        with self.assertRaises(ValueError):
            grading.grade_records(cases, [{**record, "case": "nope"}])
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "r.json"
            path.write_text(json.dumps({"schema": grading.RECORDS_SCHEMA, "records": [{**record, "arm": "x"}]}))
            with self.assertRaises(ValueError):
                grading.load_records(path)


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        cases = grading.load_corpus(CORPUS)
        self.graded = grading.grade_records(cases, grading.load_records(FIXTURE))
        self.summary = report.summarize(self.graded)

    def test_fixture_covers_every_case_arm_and_run(self) -> None:
        cases = grading.load_corpus(CORPUS)
        keys = {(row["arm"], row["case"], row["run"]) for row in self.graded}
        self.assertEqual(keys, {(arm, case, run) for arm in grading.ARMS for case in cases for run in (1, 2, 3)})

    def test_fixture_exercises_every_outcome(self) -> None:
        outcomes = {(row["kind"], row["outcome"]) for row in self.graded}
        expected = {("trap", outcome) for outcome in grading.TRAP_OUTCOMES}
        expected |= {("control", outcome) for outcome in grading.CONTROL_OUTCOMES}
        self.assertEqual(outcomes, expected)

    def test_summary_numbers_on_the_fixture(self) -> None:
        on, off = self.summary["omh-on"], self.summary["omh-off"]
        self.assertEqual((on["false_alarms"], on["trap_runs"], on["hits"], on["control_runs"]), (1, 33, 17, 18))
        self.assertEqual((off["false_alarms"], off["trap_runs"], off["hits"], off["control_runs"]), (12, 33, 14, 18))
        self.assertEqual((on["no_verdict"], off["no_verdict"], off["miss_location"]), (2, 2, 2))
        self.assertEqual(off["flips"]["control-page-slice-drops-last"], 2)
        self.assertEqual(off["flips"]["trap-eval-on-literal-table"], 0)
        self.assertEqual((on["flip_total"], off["flip_total"]), (4, 11))

    def test_markdown_table_prints_both_rates_on_every_arm_row(self) -> None:
        table = report.markdown_table(self.summary)
        self.assertIn("| omh-on | 1/33 (3.0%) | 17/18 (94.4%) | 2 (traps 1, controls 1) | 0 | 3 | 4 |", table)
        self.assertIn("| omh-off | 12/33 (36.4%) | 14/18 (77.8%) | 2 (traps 1, controls 1) | 2 | 8 | 11 |", table)
        self.assertTrue(table.endswith("Win rule: omh-on wins: fewer false alarms, hit rate held"))

    def test_win_rule_is_two_sided(self) -> None:
        def arm(fa: int, hits: int, runs: int = 3) -> dict:
            return {"false_alarm_rate": fa / 10, "hit_rate": hits / 10, "min_runs_per_case": runs,
                    "runs_per_case": {"t": runs, "c": runs}}

        rule = report.verdict_on_win_rule
        self.assertEqual(rule({"omh-on": arm(1, 9), "omh-off": arm(3, 9)}), "omh-on wins: fewer false alarms, hit rate held")
        self.assertEqual(rule({"omh-on": arm(1, 8), "omh-off": arm(3, 9)}), "no win: fewer false alarms, but fewer controls hit")
        self.assertEqual(rule({"omh-on": arm(3, 9), "omh-off": arm(3, 9)}), "no win: false alarms not lower")
        self.assertEqual(rule({"omh-on": arm(4, 8), "omh-off": arm(3, 9)}), "no win: false alarms not lower, and fewer controls hit")
        self.assertTrue(rule({"omh-on": arm(1, 9, runs=1), "omh-off": arm(3, 9, runs=1)}).startswith("noise"))
        self.assertTrue(rule({"omh-on": arm(1, 9)}).startswith("not decided"))


    def _records(self, keep) -> list[dict]:
        records = grading.load_records(FIXTURE)
        return [record for record in records if keep(record)]

    def test_disjoint_coverage_is_not_comparable(self) -> None:
        cases = grading.load_corpus(CORPUS)
        names = sorted(cases)
        on_cases = set(names[::2])
        records = self._records(lambda r: (r["case"] in on_cases) == (r["arm"] == "omh-on"))
        summary = report.summarize(grading.grade_records(cases, records))
        self.assertEqual(summary["omh-on"]["min_runs_per_case"], 3)
        self.assertEqual(summary["omh-off"]["min_runs_per_case"], 3)
        rule = report.verdict_on_win_rule(summary)
        self.assertTrue(rule.startswith("not comparable: "), rule)
        self.assertNotIn("wins", rule)
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "records.json"
            path.write_text(json.dumps({"schema": grading.RECORDS_SCHEMA, "records": records}), encoding="utf-8")
            code, out, _ = _run(analyze, [str(path)])
            json_code, json_out, _ = _run(analyze, [str(path), "--json"])
        self.assertEqual((code, json_code), (0, 0))
        self.assertIn("Win rule: not comparable: ", out)
        self.assertNotIn("wins", out)
        self.assertTrue(json.loads(json_out)["win_rule"].startswith("not comparable: "))

    def test_unequal_runs_on_one_case_are_not_comparable(self) -> None:
        cases = grading.load_corpus(CORPUS)
        dropped = ("omh-off", "trap-eval-on-literal-table", 3)
        records = self._records(lambda r: (r["arm"], r["case"], r["run"]) != dropped)
        rule = report.verdict_on_win_rule(report.summarize(grading.grade_records(cases, records)))
        self.assertTrue(rule.startswith("not comparable: "), rule)
        self.assertIn("trap-eval-on-literal-table", rule)


class CommandLineTests(unittest.TestCase):
    def test_dry_run_prints_the_table(self) -> None:
        code, out, _ = _run(bench, ["--dry-run", "--fixture", str(FIXTURE)])
        self.assertEqual(code, 0)
        self.assertIn("no model called", out)
        self.assertIn("| arm | false-alarm rate (traps) | hit rate (controls) |", out)
        self.assertIn("| omh-on |", out)
        self.assertIn("| omh-off |", out)

    def test_analyze_matches_the_dry_run_table(self) -> None:
        _, dry, _ = _run(bench, ["--dry-run", "--fixture", str(FIXTURE)])
        code, out, _ = _run(analyze, [str(FIXTURE)])
        self.assertEqual(code, 0)
        self.assertIn(out.strip(), dry)

    def test_validate(self) -> None:
        code, out, _ = _run(bench, ["validate"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"^\d+ cases valid: \d+ traps, \d+ controls")

    def test_run_without_live_only_plans(self) -> None:
        code, out, _ = _run(bench, ["run", "--runs", "3"])
        self.assertEqual(code, 0)
        self.assertIn("Nothing was run", out)

    def test_live_run_refusals_happen_before_any_call(self) -> None:
        for argv in (
            ["run", "--live", "--provider", "og", "--profile-on", "a", "--profile-off", "b"],
            ["run", "--live", "--profile-on", "a"],
            ["run", "--live", "--profile-on", "a", "--profile-off", "a", "--output", "/nonexistent/x.json"],
            ["run", "--live", "--profile-on", "a", "--profile-off", "b"],
        ):
            with self.subTest(argv=argv):
                code, _, err = _run(bench, argv)
                self.assertEqual(code, 2)
                self.assertIn("refused", err)


class HarnessTests(unittest.TestCase):
    def test_prompt_is_neutral(self) -> None:
        prompt = harness.REVIEW_PROMPT.casefold()
        for word in ("careful", "false alarm", "false positive", "may be correct", "trap", "omh", "intended"):
            self.assertNotIn(word, prompt)
        self.assertIn("verdict: clean", prompt)
        self.assertIn("verdict: bug <path>:<line>", prompt)

    def test_argv_leaves_model_to_the_profile_unless_overridden(self) -> None:
        argv = harness.oneshot_argv(
            hermes_executable="hermes", profile="p", workspace=Path("w"), usage_file=Path("u"),
            provider=None, model=None, toolsets="file", ignore_rules=False,
        )
        self.assertEqual(argv[:4], ["hermes", "-p", "p", "-z"])
        self.assertNotIn("--provider", argv)
        self.assertNotIn("--model", argv)
        self.assertNotIn("--ignore-rules", argv)
        argv = harness.oneshot_argv(
            hermes_executable="hermes", profile=None, workspace=Path("w"), usage_file=Path("u"),
            provider="claude-proxy", model="m", toolsets="file", ignore_rules=True,
        )
        self.assertNotIn("-p", argv)
        self.assertEqual(argv[argv.index("--provider") + 1], "claude-proxy")
        self.assertIn("--ignore-rules", argv)

    def test_staged_workspace_never_holds_the_answer(self) -> None:
        case = grading.load_corpus(CORPUS)["control-sql-injection-search"]
        with TemporaryDirectory() as scratch:
            workspace = harness.stage_workspace(case, Path(scratch))
            names = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file())
        self.assertIn("diff.patch", names)
        self.assertIn("context/app/search.py", names)
        self.assertNotIn("case.json", names)


    def test_live_review_is_blind_to_the_case_label(self) -> None:
        case = grading.load_corpus(CORPUS)["trap-lock-held-by-caller"]
        seen = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = list(argv)
            seen["cwd"] = str(kwargs["cwd"])
            seen["env"] = dict(kwargs["env"])
            seen["files"] = sorted(
                path.relative_to(kwargs["cwd"]).as_posix() for path in Path(kwargs["cwd"]).rglob("*")
            )
            return subprocess.CompletedProcess(argv, 0, stdout="VERDICT: clean\n", stderr="")

        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=True), \
                mock.patch.object(harness.subprocess, "run", side_effect=fake_run):
            result = harness.review_once(
                case, hermes_executable="hermes", profile="p", provider=None, model=None,
                toolsets="file", ignore_rules=False, timeout=5,
            )
        self.assertEqual(result["exit_code"], 0)
        exposed = [seen["cwd"], *seen["argv"], *seen["files"], *seen["env"], *seen["env"].values()]
        slug_words = {"lock", "held", "caller"}
        for text in exposed:
            folded = text.casefold()
            with self.subTest(text=text[:80]):
                self.assertNotIn("trap", folded)
                self.assertNotIn("control", folded)
                self.assertNotIn(case.id, folded)
                if text != harness.REVIEW_PROMPT:
                    self.assertFalse(slug_words & set(re.split(r"[^a-z0-9]+", folded)))
        self.assertIn("diff.patch", seen["files"])
        self.assertNotIn("case.json", seen["files"])

    def test_each_staging_gets_a_fresh_neutral_name(self) -> None:
        case = grading.load_corpus(CORPUS)["control-sql-injection-search"]
        with TemporaryDirectory() as scratch:
            first = harness.stage_workspace(case, Path(scratch))
            second = harness.stage_workspace(case, Path(scratch))
        self.assertNotEqual(first.name, second.name)
        for name in (first.name, second.name):
            self.assertRegex(name, r"^[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main()
