"""Contracts for `omh research eval litqa2 prepare|grade`.

`prepare` freezes a digest-pinned LitQA2 export into a seeded sample of task
files that carry no answer, plus an answer key and a manifest; `grade`
extracts each answer file's final ``ANSWER: <letter>`` line by a fixed rule and
reports per-arm rates as ``omh_reported_rate/v1``. The fixture is five made-up
questions (one with distractors as a string list literal); real LitQA2 data is
never in the repository.

The letters (a)-(k) name the node spec's required cases.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import tempfile
import unittest
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands.research import _litqa2_grade_exit_code  # noqa: E402
from omh.quality.reported_rate import REPORTED_RATE_SCHEMA_VERSION, reported_rate_shape_errors  # noqa: E402
from omh.workflows.research_eval_litqa2 import (  # noqa: E402
    ANSWER_INSTRUCTION,
    ARM_INSTRUCTIONS,
    GRADE_SCHEMA_VERSION,
    KEY_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    UNSURE_OPTION,
    LitQA2DigestError,
    LitQA2InputError,
    extract_answer,
    grade_litqa2,
    parse_rows,
    prepare_litqa2,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research_eval_litqa2"
DATA = FIXTURES / "questions.jsonl"
RECEIPT_CHECKS = FIXTURES / "receipt_checks"
DATA_SHA256 = "dadc028c69429026a36fccf4f90b875992fd518a42aa0f68d6313a814a89b5fa"
SEED = 7
CANARY = "SYNTHETIC-CANARY-7f3e"
_OPTION_RE = re.compile(r"^([A-Z])\. (.*)$")


def _fixture_rows() -> list[dict]:
    return [json.loads(line) for line in DATA.read_text(encoding="utf-8").splitlines() if line.strip()]


class _Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def prepare(self, name: str = "out", *, sample: int = 5, seed: int = SEED) -> Path:
        out = self.root / name
        prepare_litqa2(data_path=DATA, sha256=DATA_SHA256, sample=sample, seed=seed, out_dir=out)
        return out

    @staticmethod
    def key_of(out: Path) -> dict:
        return json.loads((out / "answer_key.json").read_text(encoding="utf-8"))

    def answer(self, answers: Path, arm: str, task_id: str, text: str) -> None:
        path = answers / arm / f"{task_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    @staticmethod
    def wrong_letter(task: dict) -> str:
        return next(letter for letter in "ABCDEFGHIJ"[: task["option_count"]]
                    if letter not in (task["correct"], task["unsure"]))


class PrepareTests(_Workspace):
    def test_a_same_seed_is_byte_identical_and_another_seed_differs(self) -> None:
        first, second = self.prepare("one"), self.prepare("two")
        for name in ("answer_key.json", "manifest.json"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)
        first_tasks = sorted(p.name for p in (first / "tasks").iterdir())
        self.assertEqual(first_tasks, ["q01.md", "q02.md", "q03.md", "q04.md", "q05.md"])
        for task in first_tasks:
            self.assertEqual((first / "tasks" / task).read_bytes(), (second / "tasks" / task).read_bytes(), task)
        other = self.prepare("three", seed=SEED + 1)
        key, other_key = self.key_of(first), self.key_of(other)
        self.assertNotEqual(
            [(t["dataset_id"], t["correct"]) for t in key["tasks"]],
            [(t["dataset_id"], t["correct"]) for t in other_key["tasks"]],
        )

    def test_a_sample_follows_the_specified_seeded_draw(self) -> None:
        out = self.prepare(sample=3)
        ids = sorted(row["id"] for row in _fixture_rows())
        expected = random.Random(f"{SEED}:sample").sample(ids, 3)
        self.assertEqual([t["dataset_id"] for t in self.key_of(out)["tasks"]], expected)
        self.assertEqual([t["task_id"] for t in self.key_of(out)["tasks"]], ["q01", "q02", "q03"])

    def test_b_task_files_leak_nothing_and_hold_exactly_the_options(self) -> None:
        out = self.prepare()
        rows = {row["id"]: row for row in _fixture_rows()}
        parsed = {row["id"]: row for row in parse_rows(DATA.read_text(encoding="utf-8"))}
        for task in self.key_of(out)["tasks"]:
            body = (out / "tasks" / f"{task['task_id']}.md").read_text(encoding="utf-8")
            raw = rows[task["dataset_id"]]
            for leak in (task["dataset_id"], CANARY, raw["canary"], raw["key-passage"], *raw["sources"]):
                self.assertNotIn(leak, body, task["task_id"])
            self.assertNotIn("correct", body.lower(), task["task_id"])
            options = {m.group(1): m.group(2) for m in map(_OPTION_RE.match, body.splitlines()) if m}
            row = parsed[task["dataset_id"]]
            self.assertEqual(sorted(options.values()), sorted([row["ideal"], *row["distractors"], UNSURE_OPTION]))
            self.assertEqual(options[task["correct"]], row["ideal"])
            self.assertEqual(options[task["unsure"]], UNSURE_OPTION)
            self.assertEqual(len(options), task["option_count"])
            self.assertIn(row["question"], body)
            self.assertEqual(body.splitlines()[-1], ANSWER_INSTRUCTION)
            self.assertNotIn("\r", body)

    def test_b_string_literal_distractors_parse(self) -> None:
        rows = {row["id"]: row for row in parse_rows(DATA.read_text(encoding="utf-8"))}
        self.assertIsInstance(_fixture_rows()[1]["distractors"], str)
        self.assertEqual(rows["syn-0002-beta"]["distractors"], ["magenta", "ochre"])

    def test_key_and_manifest_shape(self) -> None:
        out = self.prepare()
        key = self.key_of(out)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(key["schema_version"], KEY_SCHEMA_VERSION)
        self.assertEqual(manifest["schema_version"], MANIFEST_SCHEMA_VERSION)
        for doc in (key, manifest):
            self.assertEqual((doc["data_sha256"], doc["seed"], doc["sample"], doc["arms"]),
                             (DATA_SHA256, SEED, 5, ["baseline", "research"]))
        self.assertEqual(manifest["arm_instructions"], ARM_INSTRUCTIONS)
        self.assertIn("not paired-run signed receipts", manifest["claim_boundary"])
        for entry in manifest["task_files"]:
            self.assertEqual(hashlib.sha256((out / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])

    def test_c_wrong_digest_refuses_and_writes_nothing(self) -> None:
        out = self.root / "out"
        with self.assertRaises(LitQA2DigestError):
            prepare_litqa2(data_path=DATA, sha256="0" * 64, sample=2, seed=SEED, out_dir=out)
        self.assertFalse(out.exists())
        out.mkdir()
        status, _stdout, stderr = run_cli(["research", "eval", "litqa2", "prepare", "--data", str(DATA),
                                           "--sha256", "f" * 64, "--sample", "2", "--seed", "1", "--out", str(out)])
        self.assertEqual(status, 1)
        self.assertIn("sha256", stderr)
        self.assertEqual(list(out.iterdir()), [])

    def test_d_non_empty_output_dir_is_refused(self) -> None:
        out = self.root / "out"
        out.mkdir()
        (out / "keep.txt").write_text("user file", encoding="utf-8")
        with self.assertRaises(LitQA2InputError):
            prepare_litqa2(data_path=DATA, sha256=DATA_SHA256, sample=2, seed=SEED, out_dir=out)
        self.assertEqual([p.name for p in out.iterdir()], ["keep.txt"])

    def test_malformed_rows_name_the_row(self) -> None:
        cases = (
            ('{"id": "x", "question": "q?", "ideal": "a", "distractors": "[\'b\', 3]"}', "row 1: distractors"),
            ('{"id": "x", "question": "q?", "ideal": "a", "distractors": "not a list"}', "row 1: distractors"),
            ('{"id": "x", "question": "q?", "ideal": "a", "distractors": ["b", ""]}', "row 1: distractors"),
            ('\n{"question": "q?", "ideal": "a", "distractors": ["b"]}', "row 2: missing id"),
            ('{"id": "x", "ideal": "a", "distractors": ["b"]}', "row 1: missing question"),
            ('{"id": "x", "question": "q?", "distractors": ["b"]}', "row 1: missing ideal"),
            ('[1, 2]', "row 1: not a JSON object"),
        )
        for text, message in cases:
            with self.subTest(message=message), self.assertRaises(LitQA2InputError) as caught:
                parse_rows(text)
            self.assertIn(message, str(caught.exception))


class ExtractionTests(unittest.TestCase):
    def test_f_extraction_rule(self) -> None:
        cases = (
            ("Reasoning.\nANSWER: B", 4, "B"),
            ("ANSWER: A or C", 4, None),
            ("ANSWER: AC", 4, None),
            ("ANSWER:", 4, None),
            ("", 4, None),
            ("I think the answer is probably B.", 4, None),
            ("ANSWER: The second option, B", 4, None),
            ("ANSWER: A\nmore thought\nANSWER: C", 4, "C"),
            ("ANSWER: C\nANSWER: maybe", 4, None),
            ("**ANSWER:** (b).", 4, "B"),
            ("**ANSWER:** (e).", 4, None),
            ("  answer : d", 4, "D"),
            ("ANSWER: E", 5, "E"),
            ("ANSWER: E", 4, None),
        )
        for text, option_count, expected in cases:
            with self.subTest(text=text, option_count=option_count):
                self.assertEqual(extract_answer(text, option_count), expected)


class GradeTests(_Workspace):
    def build_mixed_tree(self, out: Path) -> Path:
        """baseline: correct, incorrect, unsure, unanswered (prose), missing; research: C, C, I, C, U."""
        answers = self.root / "answers"
        tasks = self.key_of(out)["tasks"]
        t1, t2, t3, t4, t5 = tasks
        self.answer(answers, "baseline", t1["task_id"], f"ANSWER: {t1['correct']}\n")
        self.answer(answers, "baseline", t2["task_id"], f"ANSWER: {self.wrong_letter(t2)}\n")
        self.answer(answers, "baseline", t3["task_id"], f"**ANSWER:** ({t3['unsure'].lower()}).\n")
        self.answer(answers, "baseline", t4["task_id"], "I am not able to decide between them.\n")
        self.answer(answers, "research", t1["task_id"], f"ANSWER: {t1['correct']}\n")
        self.answer(answers, "research", t2["task_id"], f"ANSWER: {self.wrong_letter(t2)}\nANSWER: {t2['correct']}\n")
        self.answer(answers, "research", t3["task_id"], f"ANSWER: {self.wrong_letter(t3)}\n")
        self.answer(answers, "research", t4["task_id"], f"ANSWER: {t4['correct']}\n")
        self.answer(answers, "research", t5["task_id"], f"ANSWER: {t5['unsure']}\n")
        return answers

    def test_e_hand_computed_grade(self) -> None:
        out = self.prepare()
        payload = grade_litqa2(key_path=out / "answer_key.json", answers_dir=self.build_mixed_tree(out))
        self.assertEqual(payload["schema_version"], GRADE_SCHEMA_VERSION)
        base, res = payload["arms"]["baseline"], payload["arms"]["research"]
        self.assertEqual(base["counts"], {"correct": 1, "incorrect": 1, "unsure": 1, "unanswered": 1, "missing": 1})
        self.assertEqual(res["counts"], {"correct": 3, "incorrect": 1, "unsure": 1, "unanswered": 0, "missing": 0})
        rates = lambda arm: {name: (arm[name]["numerator"], arm[name]["denominator"], arm[name]["percent"])  # noqa: E731
                             for name in ("accuracy", "precision", "unsure_rate", "unanswered_rate")}
        self.assertEqual(rates(base), {"accuracy": (1, 5, 20.0), "precision": (1, 2, 50.0),
                                       "unsure_rate": (1, 5, 20.0), "unanswered_rate": (2, 5, 40.0)})
        self.assertEqual(rates(res), {"accuracy": (3, 5, 60.0), "precision": (3, 4, 75.0),
                                      "unsure_rate": (1, 5, 20.0), "unanswered_rate": (0, 5, 0.0)})
        self.assertEqual(base["unanswered_rate"]["numerator_of"], ["unanswered", "missing"])
        self.assertEqual(base["precision"]["excluded"], ["unsure", "unanswered", "missing"])
        self.assertEqual(payload["paired"], {"both_correct": 1, "research_only": 2, "baseline_only": 0, "neither": 2})
        self.assertEqual(payload["missing_answers"], 1)
        self.assertFalse(payload["complete"])
        self.assertEqual(_litqa2_grade_exit_code(payload), 1)
        outcomes = {(row["task_id"], row["arm"]): (row["outcome"], row["extracted"]) for row in payload["outcomes"]}
        tasks = self.key_of(out)["tasks"]
        self.assertEqual(outcomes[("q03", "baseline")], ("unsure", tasks[2]["unsure"]))
        self.assertEqual(outcomes[("q04", "baseline")], ("unanswered", None))
        self.assertEqual(outcomes[("q05", "baseline")], ("missing", None))
        self.assertEqual(outcomes[("q02", "research")], ("correct", tasks[1]["correct"]))
        self.assertEqual(base["receipt_coverage"], {"status": "not_observed"})

    def test_g_no_sure_answer_makes_precision_unmeasured(self) -> None:
        out = self.prepare(sample=2)
        answers = self.root / "answers"
        for task in self.key_of(out)["tasks"]:
            self.answer(answers, "baseline", task["task_id"], f"ANSWER: {task['unsure']}\n")
            self.answer(answers, "research", task["task_id"], "ANSWER: A or B\n")
        payload = grade_litqa2(key_path=out / "answer_key.json", answers_dir=answers)
        for arm in ("baseline", "research"):
            precision = payload["arms"][arm]["precision"]
            self.assertEqual((precision["percent"], precision["basis"], precision["denominator"]),
                             (None, "no_observations", 0), arm)
            self.assertEqual(payload["arms"][arm]["accuracy"]["percent"], 0.0)
        self.assertTrue(payload["complete"])
        self.assertEqual(_litqa2_grade_exit_code(payload), 0)

    def test_h_every_rate_in_the_payload_is_well_formed(self) -> None:
        out = self.prepare(sample=3)
        payload = grade_litqa2(key_path=out / "answer_key.json", answers_dir=self.build_answers_for_receipts(out),
                               receipt_checks={"research": RECEIPT_CHECKS})
        found: list[dict] = []

        def walk(value: object) -> None:
            if isinstance(value, dict):
                if value.get("schema_version") == REPORTED_RATE_SCHEMA_VERSION:
                    found.append(value)
                    return
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(payload)
        self.assertEqual(len(found), 9)  # four per arm plus research's receipt coverage
        for rate in found:
            self.assertEqual(reported_rate_shape_errors(rate), (), rate)

    def build_answers_for_receipts(self, out: Path) -> Path:
        answers = self.root / "answers"
        for task in self.key_of(out)["tasks"]:
            for arm in ("baseline", "research"):
                self.answer(answers, arm, task["task_id"], f"ANSWER: {task['correct']}\n")
        return answers

    def test_i_receipt_coverage_sums_payload_counts_and_counts_absent_files(self) -> None:
        out = self.prepare(sample=3)
        answers = self.build_answers_for_receipts(out)
        payload = grade_litqa2(key_path=out / "answer_key.json", answers_dir=answers,
                               receipt_checks={"research": RECEIPT_CHECKS})
        coverage = payload["arms"]["research"]["receipt_coverage"]
        self.assertEqual((coverage["status"], coverage["tasks_checked"], coverage["no_receipt_check"]),
                         ("observed", 2, 1))
        rate = coverage["rate"]
        self.assertEqual((rate["numerator"], rate["denominator"], rate["percent"]), (3, 5, 60.0))
        self.assertEqual((rate["numerator_of"], rate["denominator_of"]), (["fetched"], "cited_sources"))
        self.assertIn("no_receipt_check", rate["excluded"])
        self.assertEqual(payload["arms"]["baseline"]["receipt_coverage"], {"status": "not_observed"})

        bad = self.root / "bad_receipts"
        bad.mkdir()
        (bad / "q01.json").write_text(json.dumps({"schema_version": "other/v1"}), encoding="utf-8")
        with self.assertRaises(LitQA2InputError):
            grade_litqa2(key_path=out / "answer_key.json", answers_dir=answers, receipt_checks={"research": bad})

    def test_j_payload_never_carries_answer_text(self) -> None:
        out = self.prepare()
        answers = self.root / "answers"
        sentinel = "SENTINEL-ANSWER-TEXT-91c2"
        for task in self.key_of(out)["tasks"]:
            for arm in ("baseline", "research"):
                self.answer(answers, arm, task["task_id"], f"{sentinel} reasoning\nANSWER: {sentinel}\n")
        payload = grade_litqa2(key_path=out / "answer_key.json", answers_dir=answers)
        self.assertNotIn(sentinel, json.dumps(payload))
        status, stdout, _stderr = run_cli(["research", "eval", "litqa2", "grade", "--key", str(out / "answer_key.json"),
                                           "--answers", str(answers)])
        self.assertEqual(status, 0)
        self.assertNotIn(sentinel, stdout)
        self.assertNotIn("SYNTHETIC", stdout)


class CliTests(_Workspace):
    def prepare_argv(self, out: Path, *extra: str, sha256: str = DATA_SHA256, sample: str = "3",
                     data: Path = DATA) -> list[str]:
        return ["research", "eval", "litqa2", "prepare", "--data", str(data), "--sha256", sha256,
                "--sample", sample, "--seed", str(SEED), "--out", str(out), *extra]

    def test_k_prepare_exit_codes(self) -> None:
        out = self.root / "out"
        status, stdout, stderr = run_cli(self.prepare_argv(out, "--json"))
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual((payload["task_count"], payload["data_sha256"], payload["out_dir"]), (3, DATA_SHA256, str(out)))
        status, stdout, _stderr = run_cli(self.prepare_argv(self.root / "text"), output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("prepared 3 task(s)", stdout)
        self.assertIn(DATA_SHA256, stdout)

        self.assertEqual(run_cli(self.prepare_argv(self.root / "wrong", sha256="0" * 64))[0], 1)
        self.assertFalse((self.root / "wrong").exists())
        status, _stdout, stderr = run_cli(self.prepare_argv(out))
        self.assertEqual(status, 2)
        self.assertIn("not empty", stderr)
        self.assertEqual(run_cli(self.prepare_argv(self.root / "big", sample="6"))[0], 2)
        bad = self.root / "bad.jsonl"
        bad.write_text('{"id": "x", "question": "q?", "ideal": "a", "distractors": "[1]"}\n', encoding="utf-8")
        status, _stdout, stderr = run_cli(self.prepare_argv(self.root / "badout", sample="1", data=bad,
                                                            sha256=hashlib.sha256(bad.read_bytes()).hexdigest()))
        self.assertEqual(status, 2)
        self.assertIn("row 1", stderr)
        self.assertEqual(run_cli(self.prepare_argv(self.root / "absent", data=self.root / "absent.jsonl"))[0], 2)

    def test_k_grade_exit_codes(self) -> None:
        out = self.root / "out"
        self.assertEqual(run_cli(self.prepare_argv(out))[0], 0)
        key = out / "answer_key.json"
        answers = self.root / "answers"
        for task in self.key_of(out)["tasks"]:
            self.answer(answers, "baseline", task["task_id"], f"ANSWER: {task['correct']}\n")
            self.answer(answers, "research", task["task_id"], f"ANSWER: {self.wrong_letter(task)}\n")
        grade = ["research", "eval", "litqa2", "grade", "--key", str(key), "--answers", str(answers)]
        status, stdout, stderr = run_cli([*grade, "--json"])
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["arms"]["baseline"]["accuracy"]["percent"], 100.0)
        status, stdout, _stderr = run_cli([*grade, "--receipt-checks", f"research={RECEIPT_CHECKS}"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("accuracy: 100.0% — 3/3 key_tasks (correct)", stdout)
        self.assertIn("receipt_coverage: 60.0% — 3/5 cited_sources (fetched)", stdout)

        (answers / "research" / "q02.md").unlink()
        self.assertEqual(run_cli(grade)[0], 1)

        wrong_key = self.root / "wrong_key.json"
        wrong_key.write_text(json.dumps({"schema_version": "other/v1"}), encoding="utf-8")
        for argv in (
            ["research", "eval", "litqa2", "grade", "--key", str(wrong_key), "--answers", str(answers)],
            ["research", "eval", "litqa2", "grade", "--key", str(self.root / "absent.json"), "--answers", str(answers)],
            ["research", "eval", "litqa2", "grade", "--key", str(key), "--answers", str(self.root / "absent")],
            [*grade, "--receipt-checks", f"nobody={RECEIPT_CHECKS}"],
            [*grade, "--receipt-checks", f"research={self.root / 'absent'}"],
        ):
            with self.subTest(argv=argv[-2:]):
                status, _stdout, stderr = run_cli(argv)
                self.assertEqual(status, 2)
                self.assertTrue(stderr.startswith("omh: "), stderr)
        big = answers / "baseline" / "q01.md"
        big.write_bytes(b"x" * (64 * 1024 + 1))
        self.assertEqual(run_cli(grade)[0], 2)


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
