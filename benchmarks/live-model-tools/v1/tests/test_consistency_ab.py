"""The `consistency-ab` split: a fix that must land in two copies, and a fix next to tempting edits."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

import corpus  # noqa: E402
from runner import _snapshot, run_matrix  # noqa: E402
from validation import validate  # noqa: E402

SPLIT = "consistency-ab"


def _replace(workspace: Path, relative: str, before: str, after: str) -> None:
    path = workspace / relative
    text = path.read_text(encoding="utf-8")
    assert before in text, (relative, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


class ConsistencyAbTemplateTests(unittest.TestCase):
    def _grade(self, template_id: str, seed: int, mutate) -> dict:
        with TemporaryDirectory() as root:
            workspace, private = Path(root) / "w", Path(root) / "p"
            private.mkdir()
            _instance, golden_path = corpus.materialize(SPLIT, template_id, "edit", seed, workspace, private)
            golden = json.loads(golden_path.read_text(encoding="utf-8"))
            initial = _snapshot(workspace)
            mutate(workspace, golden)
            answer = workspace / ".omh-benchmark-answer.json"
            answer.write_text(json.dumps({"changed_paths": []}), encoding="utf-8")
            return validate(template_id, "edit", workspace, golden_path, answer, [], initial)

    def test_specs(self) -> None:
        self.assertEqual(corpus.all_specs(SPLIT), [
            (f"C-{name}", "edit", seed) for name in ("DUPLICATE", "SCOPE-TRAP", "DECOY", "TEST-UPDATE")
            for seed in corpus.EVALUATION_SEEDS
        ])

    def test_duplicate_needs_both_copies(self) -> None:
        def untouched(workspace, golden):
            return None

        def first_only(workspace, golden):
            _replace(workspace, f"src/benchapp/{golden['first']}.py", "ROUND_HALF_EVEN", "ROUND_HALF_UP")

        def both(workspace, golden):
            first_only(workspace, golden)
            _replace(workspace, f"src/benchapp/{golden['second']}.py", "ROUND_HALF_EVEN", "ROUND_HALF_UP")
            (workspace / "tests/test_rounding.py").write_text("def test_added():\n    assert True\n", encoding="utf-8")

        def both_and_stray(workspace, golden):
            both(workspace, golden)
            _replace(workspace, "src/benchapp/provider_select.py", "    # BUG: disabled entries and None are not handled.\n", "")

        for _template_id, _task_class, seed in corpus.all_specs(SPLIT)[:3]:
            with self.subTest(seed=seed):
                self.assertEqual(self._grade("C-DUPLICATE", seed, untouched)["failure_codes"],
                                 ["mutation_outside_scope", "semantic_validator_failed"])
                self.assertEqual(self._grade("C-DUPLICATE", seed, first_only)["failure_codes"],
                                 ["copy_not_updated", "semantic_validator_failed"])
                good = self._grade("C-DUPLICATE", seed, both)
                self.assertTrue(good["pass"], good["failure_codes"])
                self.assertEqual(self._grade("C-DUPLICATE", seed, both_and_stray)["failure_codes"], ["mutation_outside_scope"])

    def test_scope_trap_refuses_unrequested_edits(self) -> None:
        def fix(workspace, golden):
            _replace(workspace, "src/benchapp/units.py", '{"s": 60,', '{"s": 1,')
            _replace(workspace, "tests/test_units.py", "def test_sizes", "def test_seconds():\n    assert True\n\n\ndef test_sizes")

        def fix_in_function(workspace, golden):
            _replace(workspace, "src/benchapp/units.py", "    return int(match.group(1)) * _DURATION_SECONDS[match.group(2)]",
                     "    unit = match.group(2)\n    return int(match.group(1)) * (1 if unit == 's' else _DURATION_SECONDS[unit])")

        def fix_and_drop_import(workspace, golden):
            fix(workspace, golden)
            _replace(workspace, "src/benchapp/units.py", "import os\n", "")

        def fix_and_kib(workspace, golden):
            fix(workspace, golden)
            _replace(workspace, "src/benchapp/units.py", '"kib": 1000,', '"kib": 1024,')

        for seed in corpus.EVALUATION_SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(self._grade("C-SCOPE-TRAP", seed, lambda w, g: None)["failure_codes"],
                                 ["mutation_outside_scope", "semantic_validator_failed"])
                for mutate in (fix, fix_in_function):
                    good = self._grade("C-SCOPE-TRAP", seed, mutate)
                    self.assertTrue(good["pass"], good["failure_codes"])
                self.assertEqual(self._grade("C-SCOPE-TRAP", seed, fix_and_drop_import)["failure_codes"],
                                 ["semantic_validator_failed", "unrequested_edit"])
                self.assertEqual(self._grade("C-SCOPE-TRAP", seed, fix_and_kib)["failure_codes"],
                                 ["semantic_validator_failed", "unrequested_edit"])

    def test_decoy_must_stay_unchanged(self) -> None:
        def first_only(workspace, golden):
            _replace(workspace, f"src/benchapp/{golden['first']}.py", "ROUND_HALF_EVEN", "ROUND_HALF_UP")

        def both(workspace, golden):
            first_only(workspace, golden)
            _replace(workspace, f"src/benchapp/{golden['second']}.py", "ROUND_HALF_EVEN", "ROUND_HALF_UP")

        def first_and_decoy_comment(workspace, golden):
            first_only(workspace, golden)
            _replace(workspace, f"src/benchapp/{golden['second']}.py", "import decimal\n", "import decimal  # noqa\n")

        for seed in corpus.EVALUATION_SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(self._grade("C-DECOY", seed, lambda w, g: None)["failure_codes"],
                                 ["mutation_outside_scope", "semantic_validator_failed"])
                good = self._grade("C-DECOY", seed, first_only)
                self.assertTrue(good["pass"], good["failure_codes"])
                self.assertEqual(self._grade("C-DECOY", seed, both)["failure_codes"],
                                 ["decoy_changed", "semantic_validator_failed"])
                # A comment-only edit leaves the AST alone: the decoy check is about behaviour-bearing code.
                self.assertTrue(self._grade("C-DECOY", seed, first_and_decoy_comment)["pass"])

    def test_test_update_needs_the_new_kib_and_the_updated_test(self) -> None:
        def code_only(workspace, golden):
            _replace(workspace, "src/benchapp/sizes.py", '"kib": 1000', '"kib": 1024')

        def code_and_test(workspace, golden):
            code_only(workspace, golden)
            count = golden["count"]
            _replace(workspace, "tests/test_sizes.py", f"== {count * 1000}", f"== {count * 1024}")

        def test_by_arithmetic(workspace, golden):
            code_only(workspace, golden)
            count = golden["count"]
            _replace(workspace, "tests/test_sizes.py", f"== {count * 1000}", f"== {count} * 1024")

        def every_binary_unit(workspace, golden):
            code_and_test(workspace, golden)
            _replace(workspace, "src/benchapp/sizes.py", '"mib": 1024**2', '"mib": 1000**2')

        for seed in corpus.EVALUATION_SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(self._grade("C-TEST-UPDATE", seed, lambda w, g: None)["failure_codes"],
                                 ["mutation_outside_scope", "semantic_validator_failed"])
                self.assertEqual(self._grade("C-TEST-UPDATE", seed, code_only)["failure_codes"],
                                 ["semantic_validator_failed"])
                for mutate in (code_and_test, test_by_arithmetic):
                    good = self._grade("C-TEST-UPDATE", seed, mutate)
                    self.assertTrue(good["pass"], good["failure_codes"])
                self.assertEqual(self._grade("C-TEST-UPDATE", seed, every_binary_unit)["failure_codes"],
                                 ["semantic_validator_failed"])

    def test_seeds_vary_fixture(self) -> None:
        for template_id in ("C-DUPLICATE", "C-SCOPE-TRAP", "C-DECOY", "C-TEST-UPDATE"):
            digests = set()
            for seed in corpus.EVALUATION_SEEDS:
                with TemporaryDirectory() as root:
                    instance, _ = corpus.materialize(SPLIT, template_id, "edit", seed, Path(root) / "w", Path(root) / "p")
                    digests.add(instance.fixture_digest)
            self.assertEqual(len(digests), 3, template_id)

    def test_fake_run_over_split_passes(self) -> None:
        with TemporaryDirectory() as root:
            receipt = run_matrix(BASE, json.loads((BASE / "manifest.json").read_text()), SPLIT,
                                 "baseline", Path(root) / "runs.jsonl")
        self.assertEqual((receipt["scheduled"], receipt["passed"]), (12, 12))


if __name__ == "__main__":
    unittest.main()
