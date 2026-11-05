"""Contracts for `omh research screening freeze|prepare|merge`.

Driven through the real CLI entry (`omh.cli.main`) over small synthetic
fixtures. These pin:

* freeze is write-once and refuses malformed codes;
* prepare refuses an existing ``tasks/``; each task file holds the criteria
  verbatim, the ordered codes and the answer grammar, and nothing of the
  other reviewer; A and B orders differ, and a seed reproduces them;
* merge decides each record by the fixed rules: agree include, agree exclude
  with the earliest protocol code (plus ``code_disagreements``), conflict,
  UNSURE -> conflict, and pending -- never a silent exclude -- for a missing
  line, contradictory lines or an unknown code;
* adjudication resolves conflicts only; a line for another record is exit 2;
* exit codes: 0 only when nothing is left, 1 when conflicts or pending
  remain, 2 for an input error;
* reviewer independence: ``not_observed`` by default, ``same_model`` with a
  ``broken_independence`` warning;
* the merge payload carries ids and codes, never abstract text.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands.research_screening import _screening_merge_exit_code  # noqa: E402
from omh.quality.reported_rate import reported_rate_shape_errors  # noqa: E402
from omh.workflows.systematic_review import (  # noqa: E402
    CLAIM_BOUNDARY,
    MANIFEST_SCHEMA_VERSION,
    MERGE_SCHEMA_VERSION,
    PROTOCOL_SCHEMA_VERSION,
    reviewer_order,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "systematic_review"
CRITERIA = FIXTURES / "criteria.md"
CODES = FIXTURES / "codes.json"
RECORDS = FIXTURES / "records.jsonl"
RECORD_IDS = [f"r{i:02d}" for i in range(1, 9)]
ABSTRACT_SENTINEL = "SYNTHETIC-ABSTRACT-SENTINEL"


class _ScreeningDir(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.dir = self.root / "screen"

    def cli(self, *args: str) -> tuple[int, Any, str]:
        status, stdout, stderr = run_cli(["research", "screening", *args], output_json=True)
        try:
            return status, json.loads(stdout), stderr
        except json.JSONDecodeError:
            return status, stdout, stderr

    def freeze(self) -> Any:
        status, payload, stderr = self.cli(
            "freeze", "--criteria", str(CRITERIA), "--codes", str(CODES), "--out", str(self.dir)
        )
        self.assertEqual(status, 0, stderr)
        return payload

    def prepare(self, *, seed: int = 7, directory: Path | None = None, batch_size: int = 3) -> Any:
        status, payload, stderr = self.cli(
            "prepare",
            "--dir", str(directory or self.dir),
            "--records", str(RECORDS),
            "--seed", str(seed),
            "--batch-size", str(batch_size),
        )
        self.assertEqual(status, 0, stderr)
        return payload

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def merge(self, answers_a: Path, answers_b: Path, *extra: str) -> tuple[int, Any, str]:
        return self.cli(
            "merge", "--dir", str(self.dir), "--answers-a", str(answers_a), "--answers-b", str(answers_b), *extra
        )


class FreezeTests(_ScreeningDir):
    def test_freeze_writes_the_protocol_once(self) -> None:
        summary = self.freeze()
        protocol = json.loads((self.dir / "protocol.json").read_text(encoding="utf-8"))
        self.assertEqual(protocol["schema_version"], PROTOCOL_SCHEMA_VERSION)
        self.assertEqual(protocol["criteria"], CRITERIA.read_text(encoding="utf-8"))
        self.assertEqual([code["code"] for code in protocol["codes"]], ["E1", "E2", "E3"])
        self.assertEqual(summary["protocol_sha256"], protocol["protocol_sha256"])
        before = (self.dir / "protocol.json").read_bytes()

        status, _payload, stderr = self.cli(
            "freeze", "--criteria", str(CRITERIA), "--codes", str(CODES), "--out", str(self.dir)
        )
        self.assertEqual(status, 2)
        self.assertIn("write-once", stderr)
        self.assertEqual((self.dir / "protocol.json").read_bytes(), before)

    def test_freeze_refuses_repeated_or_empty_codes(self) -> None:
        for name, codes in (
            ("repeated", [{"code": "E1", "label": "a"}, {"code": "E1", "label": "b"}]),
            ("empty", []),
            ("extra key", [{"code": "E1", "label": "a", "note": "x"}]),
        ):
            with self.subTest(case=name):
                path = self.write("codes.json", json.dumps(codes))
                status, _payload, _stderr = self.cli(
                    "freeze", "--criteria", str(CRITERIA), "--codes", str(path), "--out", str(self.root / name)
                )
                self.assertEqual(status, 2)
                self.assertFalse((self.root / name / "protocol.json").exists())


class PrepareTests(_ScreeningDir):
    def test_task_files_hold_criteria_codes_grammar_and_only_their_own_reviewer(self) -> None:
        self.freeze()
        summary = self.prepare()
        manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest["record_ids"], RECORD_IDS)
        self.assertEqual(summary["task_files"], [batch["path"] for batch in manifest["batches"]])
        criteria = CRITERIA.read_text(encoding="utf-8").rstrip("\n")
        for batch in manifest["batches"]:
            text = (self.dir / batch["path"]).read_text(encoding="utf-8")
            with self.subTest(path=batch["path"]):
                self.assertIn(criteria, text)
                self.assertIn("1. E1: Wrong population\n2. E2: Wrong study design\n3. E3: No HbA1c outcome", text)
                for form in ("RECORD <id>: INCLUDE", "RECORD <id>: EXCLUDE <code>", "RECORD <id>: UNSURE"):
                    self.assertIn(form, text)
                other = "B" if batch["reviewer"] == "A" else "A"
                self.assertIn(f"reviewer {batch['reviewer']},", text)
                self.assertNotIn(f"reviewer {other}", text)
                self.assertNotIn("answers", text.lower())
                self.assertEqual(
                    [line.split()[-1] for line in text.splitlines() if line.startswith("### RECORD ")],
                    batch["record_ids"],
                )
        for reviewer in ("A", "B"):
            ids = [rid for batch in manifest["batches"] if batch["reviewer"] == reviewer for rid in batch["record_ids"]]
            self.assertEqual(sorted(ids), RECORD_IDS)

    def test_reviewer_orders_differ_and_a_seed_reproduces_them(self) -> None:
        self.freeze()
        first = json.loads(json.dumps(self.prepare(seed=11)))
        order = {
            reviewer: [rid for batch in json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))["batches"]
                       if batch["reviewer"] == reviewer for rid in batch["record_ids"]]
            for reviewer in ("A", "B")
        }
        self.assertNotEqual(order["A"], order["B"])

        again = self.root / "again"
        again.mkdir()
        shutil.copy(self.dir / "protocol.json", again / "protocol.json")
        self.prepare(seed=11, directory=again)
        manifest_again = json.loads((again / "manifest.json").read_text(encoding="utf-8"))
        manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest_again["batches"], manifest["batches"])
        self.assertEqual(first["records_sha256"], manifest_again["records_sha256"])
        self.assertNotEqual(reviewer_order(RECORD_IDS, seed=12, reviewer="A"), order["A"])

    def test_prepare_refuses_an_existing_tasks_dir(self) -> None:
        self.freeze()
        (self.dir / "tasks").mkdir()
        status, _payload, stderr = self.cli(
            "prepare", "--dir", str(self.dir), "--records", str(RECORDS), "--seed", "1"
        )
        self.assertEqual(status, 2)
        self.assertIn("already exists", stderr)
        self.assertFalse((self.dir / "manifest.json").exists())

    def test_prepare_refuses_a_protocol_edited_after_freeze(self) -> None:
        self.freeze()
        protocol = json.loads((self.dir / "protocol.json").read_text(encoding="utf-8"))
        protocol["criteria"] += "Also include children.\n"
        (self.dir / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
        status, _payload, stderr = self.cli(
            "prepare", "--dir", str(self.dir), "--records", str(RECORDS), "--seed", "1"
        )
        self.assertEqual(status, 2)
        self.assertIn("edited after freeze", stderr)

    def test_records_split_on_newline_only_so_unicode_separators_stay_in_the_abstract(self) -> None:
        self.freeze()
        records = self.write(
            "separators.jsonl",
            '{"id": "r1", "title": "t", "abstract": "line one\u2028line two"}\r\n'
            '{"id": "r2", "title": "t", "abstract": "a\u0085b\u2029c"}\n',
        )
        status, payload, stderr = self.cli("prepare", "--dir", str(self.dir), "--records", str(records), "--seed", "1")
        self.assertEqual(status, 0, stderr)
        self.assertEqual(payload["record_count"], 2)
        text = "".join((self.dir / path).read_text(encoding="utf-8") for path in payload["task_files"])
        self.assertIn("line one\u2028line two", text)


class MergeTests(_ScreeningDir):
    def setUp(self) -> None:
        super().setUp()
        self.freeze()
        self.prepare()

    def fixture_merge(self, *extra: str) -> tuple[int, Any, str]:
        return self.merge(FIXTURES / "answers_a.md", FIXTURES / "answers_b", *extra)

    def test_decision_rules_on_the_fixture_answers(self) -> None:
        status, payload, _stderr = self.fixture_merge()
        self.assertEqual(status, 1)
        self.assertEqual(payload["schema_version"], MERGE_SCHEMA_VERSION)
        decisions = {row["id"]: (row["decision"], row["code"]) for row in payload["records"]}
        self.assertEqual(decisions["r01"], ("include", ""))  # agree include (a repeated identical line is one answer)
        self.assertEqual(decisions["r02"], ("exclude", "E1"))  # E2 vs E1: earliest in protocol order
        self.assertEqual(decisions["r03"], ("exclude", "E3"))
        self.assertEqual(decisions["r04"], ("conflict", ""))  # INCLUDE vs EXCLUDE
        self.assertEqual(decisions["r05"], ("conflict", ""))  # UNSURE vs INCLUDE
        self.assertEqual(payload["code_disagreements"], ["r02"])
        self.assertEqual(payload["conflict_ids"], ["r04", "r05"])
        pending = {row["id"]: row["reviewers"] for row in payload["pending"]}
        self.assertEqual(
            pending,
            {
                "r06": {"A": "missing"},  # malformed line is not an answer
                "r07": {"A": "contradictory_lines"},
                "r08": {"A": "unknown_code"},
            },
        )
        for record_id in pending:
            self.assertEqual(decisions[record_id], ("pending", ""))
        self.assertEqual(
            payload["counts"],
            {
                "records": 8,
                "included": 1,
                "excluded": 2,
                "excluded_by_code": {"E1": 1, "E2": 0, "E3": 1},
                "conflicts": 2,
                "adjudicated": 0,
                "pending": 3,
            },
        )
        self.assertEqual(payload["answer_lines"]["A"]["unknown_record_lines"], 1)
        agreement = payload["agreement"]
        self.assertEqual(agreement["schema_version"], "agreement_stats/v1")
        self.assertEqual(
            agreement["table"], {"both_include": 1, "both_exclude": 2, "a_only_include": 1, "b_only_include": 0, "n": 4}
        )
        self.assertFalse(reported_rate_shape_errors(agreement["observed_agreement"]))
        self.assertEqual(payload["claim_boundary"], CLAIM_BOUNDARY)

    def test_missing_answers_are_pending_never_excluded(self) -> None:
        empty = self.write("empty.md", "no answers here\n")
        status, payload, _stderr = self.merge(empty, FIXTURES / "answers_b")
        self.assertEqual(status, 1)
        self.assertEqual(payload["counts"]["pending"], 8)
        self.assertEqual(payload["counts"]["excluded"], 0)
        self.assertTrue(all(row["reviewers"] == {"A": "missing"} for row in payload["pending"]))
        self.assertEqual(payload["agreement"]["kappa_undefined_reason"], "no_observations")
        self.assertIsNone(payload["agreement"]["observed_agreement"]["percent"])

    def test_adjudication_resolves_conflicts_and_exit_zero_when_nothing_remains(self) -> None:
        lines_a = "\n".join(f"RECORD {rid}: INCLUDE" for rid in RECORD_IDS[:4])
        lines_a += "\n" + "\n".join(f"RECORD {rid}: EXCLUDE E2" for rid in RECORD_IDS[4:7]) + "\nRECORD r08: UNSURE\n"
        lines_b = "\n".join(f"RECORD {rid}: INCLUDE" for rid in RECORD_IDS[:3]) + "\nRECORD r04: EXCLUDE E3\n"
        lines_b += "\n".join(f"RECORD {rid}: EXCLUDE E2" for rid in RECORD_IDS[4:8]) + "\n"
        answers_a = self.write("a.md", lines_a)
        answers_b = self.write("b.md", lines_b)

        status, payload, _stderr = self.merge(answers_a, answers_b)
        self.assertEqual(status, 1)
        self.assertEqual(payload["conflict_ids"], ["r04", "r08"])
        self.assertEqual(payload["counts"]["pending"], 0)

        adjudication = self.write("adj.md", "RECORD r04: INCLUDE\nrecord r08: exclude E3\n")
        status, payload, _stderr = self.merge(answers_a, answers_b, "--adjudication", str(adjudication))
        self.assertEqual(status, 0)
        self.assertEqual(payload["conflict_ids"], [])
        self.assertEqual(payload["adjudicated_ids"], ["r04", "r08"])
        counts = payload["counts"]
        self.assertEqual((counts["included"], counts["excluded"], counts["adjudicated"]), (4, 4, 2))
        self.assertEqual(counts["excluded_by_code"], {"E1": 0, "E2": 3, "E3": 1})

    def test_adjudication_rejects_non_conflict_records_and_unsure(self) -> None:
        for name, text in (
            ("non-conflict", "RECORD r04: INCLUDE\nRECORD r01: EXCLUDE E1\n"),
            ("unsure", "RECORD r04: UNSURE\n"),
            ("unknown code", "RECORD r04: EXCLUDE E9\n"),
        ):
            with self.subTest(case=name):
                adjudication = self.write("adj.md", text)
                status, payload, stderr = self.fixture_merge("--adjudication", str(adjudication))
                self.assertEqual(status, 2)
                self.assertEqual(payload, "")
                self.assertTrue(stderr.startswith("omh: "))

    def test_input_errors_exit_two(self) -> None:
        status, _payload, _stderr = self.merge(self.root / "absent.md", FIXTURES / "answers_b")
        self.assertEqual(status, 2)
        status, _payload, _stderr = self.fixture_merge("--reviewer-models", "A=x")
        self.assertEqual(status, 2)

    def test_reviewer_independence_labels(self) -> None:
        _status, payload, _stderr = self.fixture_merge()
        self.assertEqual(payload["reviewer_independence"], "not_observed")
        self.assertEqual(payload["warnings"], [])

        _status, payload, _stderr = self.fixture_merge("--reviewer-models", "A=claude-opus,B=claude-opus")
        self.assertEqual(payload["reviewer_independence"], "same_model")
        self.assertIn("broken_independence", payload["warnings"])

        _status, payload, _stderr = self.fixture_merge("--reviewer-models", "A=claude-opus,B=gpt-5")
        self.assertEqual(payload["reviewer_independence"], "different_models")
        self.assertEqual(payload["warnings"], [])

    def test_observed_agreement_names_unsure_and_pending_records_it_left_out(self) -> None:
        answers_a = self.write("a.md", "".join(f"RECORD {rid}: INCLUDE\n" for rid in RECORD_IDS))
        answers_b = self.write(
            "b.md", "RECORD r01: INCLUDE\n" + "".join(f"RECORD {rid}: UNSURE\n" for rid in RECORD_IDS[1:7])
        )
        status, payload, _stderr = self.merge(answers_a, answers_b)
        self.assertEqual(status, 1)
        agreement = payload["agreement"]
        self.assertEqual(agreement["table"]["n"], 1)
        self.assertEqual(agreement["observed_agreement"]["excluded"], ["records_with_unsure", "pending_records"])
        self.assertEqual(agreement["excluded_counts"], {"records_with_unsure": 6, "pending_records": 1})
        self.assertFalse(reported_rate_shape_errors(agreement["observed_agreement"]))
        status, text, _stderr = run_cli(
            ["research", "screening", "merge", "--dir", str(self.dir), "--answers-a", str(answers_a),
             "--answers-b", str(answers_b)],
            output_json=False,
        )
        self.assertIn("excluded: records_with_unsure, pending_records", text)

    def test_same_answers_file_for_both_reviewers_is_warned(self) -> None:
        _status, payload, _stderr = self.merge(FIXTURES / "answers_a.md", FIXTURES / "answers_a.md")
        self.assertIn("same_answers_file", payload["warnings"])
        copy = self.write("copy.md", (FIXTURES / "answers_a.md").read_text(encoding="utf-8"))
        _status, payload, _stderr = self.merge(FIXTURES / "answers_a.md", copy)
        self.assertIn("same_answers_file", payload["warnings"])
        # A copy that only crossed platforms (CRLF from git autocrlf, an editor's BOM) is still the same answers.
        text = (FIXTURES / "answers_a.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        crossed = self.root / "crossed.md"
        crossed.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
        _status, payload, _stderr = self.merge(FIXTURES / "answers_a.md", crossed)
        self.assertIn("same_answers_file", payload["warnings"])
        _status, payload, _stderr = self.fixture_merge()
        self.assertNotIn("same_answers_file", payload["warnings"])

    def test_answers_directory_without_md_files_is_an_input_error(self) -> None:
        directory = self.root / "answers_txt"
        directory.mkdir()
        (directory / "answers.txt").write_text("RECORD r01: INCLUDE\n", encoding="utf-8")
        status, payload, stderr = self.merge(directory, FIXTURES / "answers_b")
        self.assertEqual(status, 2)
        self.assertEqual(payload, "")
        self.assertIn("*.md", stderr)

    def test_merge_refuses_a_manifest_changed_after_prepare(self) -> None:
        manifest_path = self.dir / "manifest.json"
        original = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(original)
        stale = dict(manifest, record_ids=manifest["record_ids"][:-1])
        rehashed = {key: value for key, value in stale.items() if key != "manifest_sha256"}
        rehashed["manifest_sha256"] = hashlib.sha256(
            json.dumps(rehashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for name, edited, message in (
            ("record id dropped, hash stale", stale, "manifest_sha256"),
            ("record id dropped, hash recomputed", rehashed, "record_ids"),
        ):
            with self.subTest(case=name):
                manifest_path.write_text(json.dumps(edited), encoding="utf-8")
                status, payload, stderr = self.fixture_merge()
                self.assertEqual(status, 2, stderr)
                self.assertEqual(payload, "")
                self.assertIn(message, stderr)
        manifest_path.write_text(original, encoding="utf-8")
        self.assertEqual(self.fixture_merge()[0], 1)

    def test_payload_and_text_carry_no_abstract_or_title_text(self) -> None:
        status, stdout, _stderr = run_cli(
            [
                "research", "screening", "merge", "--dir", str(self.dir),
                "--answers-a", str(FIXTURES / "answers_a.md"), "--answers-b", str(FIXTURES / "answers_b"),
            ],
            output_json=True,
        )
        self.assertEqual(status, 1)
        self.assertNotIn(ABSTRACT_SENTINEL, stdout)
        self.assertNotIn("Synthetic record", stdout)
        status, text, _stderr = run_cli(
            [
                "research", "screening", "merge", "--dir", str(self.dir),
                "--answers-a", str(FIXTURES / "answers_a.md"), "--answers-b", str(FIXTURES / "answers_b"),
            ],
            output_json=False,
        )
        self.assertEqual(status, 1)
        self.assertNotIn(ABSTRACT_SENTINEL, text)
        self.assertIn("screening incomplete", text)
        self.assertIn("pending r06: A missing", text)


class ExitCodeMapperTests(unittest.TestCase):
    def test_mapper_grades_remaining_work_as_one(self) -> None:
        def payload(conflicts: int, pending: int) -> dict:
            return {"schema_version": MERGE_SCHEMA_VERSION, "counts": {"conflicts": conflicts, "pending": pending}}

        self.assertEqual(_screening_merge_exit_code(payload(0, 0)), 0)
        self.assertEqual(_screening_merge_exit_code(payload(1, 0)), 1)
        self.assertEqual(_screening_merge_exit_code(payload(0, 1)), 1)
        self.assertEqual(_screening_merge_exit_code({"schema_version": MERGE_SCHEMA_VERSION}), 1)


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
