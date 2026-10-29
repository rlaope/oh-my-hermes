from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

import corpus  # noqa: E402
from runner import _snapshot, run_matrix  # noqa: E402
from validation import validate  # noqa: E402


class ShellAbTemplateTests(unittest.TestCase):
    """S-GENERATED: every write the task needs is a new file under build/, made by shell redirection."""

    def _grade(self, seed: int, act) -> dict:
        with TemporaryDirectory() as root:
            workspace, private = Path(root) / "w", Path(root) / "p"
            private.mkdir()
            _instance, golden = corpus.materialize("shell-ab", "S-GENERATED", "edit", seed, workspace, private)
            facts = json.loads(golden.read_text(encoding="utf-8"))
            initial = _snapshot(workspace)
            act(workspace, facts)
            answer = workspace / ".omh-benchmark-answer.json"
            return validate("S-GENERATED", "edit", workspace, golden, answer, [], initial)

    @staticmethod
    def _shell_first(workspace: Path, facts: dict) -> None:
        generated = workspace / "build/generated/constants.py"
        generated.parent.mkdir(parents=True)
        generated.write_text(
            subprocess.check_output([sys.executable, "tools/gen_constants.py"], cwd=workspace, text=True), encoding="utf-8"
        )
        (workspace / "build/test-report.txt").write_text("1 passed\n", encoding="utf-8")
        check = subprocess.run(["git", "apply", "--check", "patches/retry_doc.diff"], cwd=workspace, capture_output=True)
        answer = {
            "generated_lines": len(generated.read_text(encoding="utf-8").splitlines()),
            "patch_applies": check.returncode == 0,
            "retry_line": "DEFAULT_RETRY_LIMIT = 2",
        }
        (workspace / ".omh-benchmark-answer.json").write_text(json.dumps(answer), encoding="utf-8")

    def test_specs(self) -> None:
        self.assertEqual(
            corpus.all_specs("shell-ab"), [("S-GENERATED", "edit", seed) for seed in corpus.EVALUATION_SEEDS]
        )

    def test_shell_first_passes_and_patch_answer_varies(self) -> None:
        applies = set()
        for seed in corpus.EVALUATION_SEEDS:
            with self.subTest(seed=seed):
                grade = self._grade(seed, self._shell_first)
                self.assertTrue(grade["pass"], grade["failure_codes"])
            with TemporaryDirectory() as root:
                _instance, golden = corpus.materialize("shell-ab", "S-GENERATED", "edit", seed, Path(root) / "w", Path(root) / "p")
                applies.add(json.loads(golden.read_text(encoding="utf-8"))["patch_applies"])
        self.assertEqual(applies, {True, False})

    def test_untouched_fails(self) -> None:
        grade = self._grade(corpus.EVALUATION_SEEDS[0], lambda workspace, facts: None)
        self.assertFalse(grade["pass"])

    def test_applying_the_patch_fails_as_out_of_scope(self) -> None:
        seed = next(
            seed for seed in corpus.EVALUATION_SEEDS
            if self._grade(seed, self._shell_first)["pass"] and self._applies(seed)
        )

        def apply_it(workspace: Path, facts: dict) -> None:
            self._shell_first(workspace, facts)
            subprocess.run(["git", "apply", "patches/retry_doc.diff"], cwd=workspace, check=True, capture_output=True)

        grade = self._grade(seed, apply_it)
        self.assertIn("mutation_outside_scope", grade["failure_codes"])

    @staticmethod
    def _applies(seed: int) -> bool:
        with TemporaryDirectory() as root:
            _instance, golden = corpus.materialize("shell-ab", "S-GENERATED", "edit", seed, Path(root) / "w", Path(root) / "p")
            return json.loads(golden.read_text(encoding="utf-8"))["patch_applies"]

    def test_fake_run_over_split_passes(self) -> None:
        with TemporaryDirectory() as root:
            receipt = run_matrix(BASE, json.loads((BASE / "manifest.json").read_text()), "shell-ab",
                                 "baseline", Path(root) / "runs.jsonl")
        self.assertEqual((receipt["scheduled"], receipt["passed"]), (3, 3))


if __name__ == "__main__":
    unittest.main()
