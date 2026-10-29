"""The `bigfile-ab` split: big module, work past line 3,000, graded by behaviour."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

import bigfile  # noqa: E402
import corpus  # noqa: E402
from runner import _snapshot, run_matrix  # noqa: E402
from validation import validate  # noqa: E402


class BigfileTemplateTests(unittest.TestCase):
    def _grade(self, template_id: str, seed: int, mutate) -> dict:
        with TemporaryDirectory() as root:
            workspace, private = Path(root) / "w", Path(root) / "p"
            private.mkdir()
            _instance, golden = corpus.materialize("bigfile-ab", template_id, "edit", seed, workspace, private)
            initial = _snapshot(workspace)
            mutate(workspace)
            answer = workspace / ".omh-benchmark-answer.json"
            answer.write_text(json.dumps({"changed_paths": []}), encoding="utf-8")
            return validate(template_id, "edit", workspace, golden, answer, [], initial)

    def test_specs(self) -> None:
        self.assertEqual(corpus.all_specs("bigfile-ab"), [
            (f"B-{name}", "edit", seed) for name in ("DEEP-BUG", "DEEP-RENAME") for seed in corpus.EVALUATION_SEEDS
        ])

    def test_module_is_big_and_the_work_is_deep(self) -> None:
        for seed in corpus.EVALUATION_SEEDS:
            text, starts = bigfile.module_text(seed)
            lines = text.count("\n")
            with self.subTest(seed=seed):
                self.assertGreaterEqual(lines, 4000)
                self.assertLessEqual(lines, 6000)
                # Past Hermes' 2,000-line read window either way.
                self.assertGreater(len(text), 100_000)
                self.assertGreater(starts["credit"], 3000)
                self.assertGreater(starts["estimator"], 3000)
                self.assertLess(starts["zone"], 2000)
                _files, golden = bigfile.bigfile_fixture("DEEP-BUG", seed)
                self.assertGreater(golden["bug_line"], 3000)

    def test_untouched_fails_reference_passes_wrong_edits_fail(self) -> None:
        for template_id, _task_class, seed in corpus.all_specs("bigfile-ab"):
            name = template_id.split("-", 1)[1]
            with self.subTest(template_id=template_id, seed=seed):
                untouched = self._grade(template_id, seed, lambda workspace: None)
                self.assertFalse(untouched["pass"])
                good = self._grade(template_id, seed, lambda workspace, name=name: bigfile.reference_edit(name, workspace))
                self.assertTrue(good["pass"], good["failure_codes"])
                if name == "DEEP-BUG":
                    # Editing the test to the buggy number does not pass: the cases are hidden.
                    def cheat(workspace: Path) -> None:
                        path = workspace / bigfile.TESTS
                        text = path.read_text(encoding="utf-8")
                        path.write_text(text.replace("== ", "!= ", 1), encoding="utf-8")
                    self.assertFalse(self._grade(template_id, seed, cheat)["pass"])
                else:
                    def naive(workspace: Path) -> None:
                        for path in workspace.rglob("*.py"):
                            path.write_text(path.read_text(encoding="utf-8").replace(bigfile.OLD_NAME, bigfile.NEW_NAME),
                                            encoding="utf-8")
                    bad = self._grade(template_id, seed, naive)
                    self.assertFalse(bad["pass"])
                    self.assertEqual(bad["failure_codes"], ["semantic_validator_failed"])

    def test_seeds_vary_fixture(self) -> None:
        digests = set()
        for seed in corpus.EVALUATION_SEEDS:
            with TemporaryDirectory() as root:
                instance, _ = corpus.materialize("bigfile-ab", "B-DEEP-BUG", "edit", seed, Path(root) / "w", Path(root) / "p")
                digests.add(instance.fixture_digest)
        self.assertEqual(len(digests), 3)

    def test_prompt_names_the_symptom_not_the_location(self) -> None:
        text = bigfile.prompt("DEEP-BUG", corpus.EVALUATION_SEEDS[0])
        self.assertIn("test_full_crate_quote", text)
        self.assertNotIn(bigfile.OLD_NAME, text)
        self.assertNotIn("CONSOLIDATION", text)
        self.assertNotIn("src/benchapp/tariffs.py", text)

    def test_fake_run_over_split_passes(self) -> None:
        with TemporaryDirectory() as root:
            receipt = run_matrix(BASE, json.loads((BASE / "manifest.json").read_text()), "bigfile-ab",
                                 "baseline", Path(root) / "runs.jsonl")
        self.assertEqual((receipt["scheduled"], receipt["passed"]), (6, 6))


if __name__ == "__main__":
    unittest.main()
