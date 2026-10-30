from __future__ import annotations

from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

import corpus  # noqa: E402
from runner import _snapshot  # noqa: E402
from validation import validate  # noqa: E402

TEMPLATE = "W-WIDE-RENAME"


class SearchSplitTests(unittest.TestCase):
    def test_split_has_one_control_template_three_seeds(self) -> None:
        specs = corpus.all_specs(corpus.SEARCH_AB_SPLIT)
        self.assertEqual([spec[0] for spec in specs], [TEMPLATE] * 3)
        self.assertIn(corpus.SEARCH_AB_SPLIT, corpus.SPLITS)

    def _grade(self, seed: int, edit) -> tuple[dict, Path]:
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        workspace, private = Path(root.name) / "w", Path(root.name) / "p"
        private.mkdir()
        _, golden = corpus.materialize(corpus.SEARCH_AB_SPLIT, TEMPLATE, "edit", seed, workspace, private)
        initial = _snapshot(workspace)
        edit(workspace)
        answer = workspace / ".omh-benchmark-answer.json"
        answer.write_text('{"changed_paths": []}', encoding="utf-8")
        return validate(TEMPLATE, "edit", workspace, golden, answer, [], initial), workspace

    def test_the_control_search_is_past_the_context_bound(self) -> None:
        # The pass enriches at most 20 hits in 8 files; the control's natural search must exceed both.
        for seed in corpus.EVALUATION_SEEDS:
            _, workspace = self._grade(seed, lambda workspace: None)
            hits = {path: path.read_text(encoding="utf-8").count("BASE_RATE_BP")
                    for path in workspace.rglob("*.py")}
            hit_files = [path for path, count in hits.items() if count]
            self.assertGreater(sum(hits.values()), 20, seed)
            self.assertGreater(len(hit_files), 8, seed)

    def test_a_complete_rename_passes_and_a_partial_one_fails(self) -> None:
        def rename(workspace: Path, skip: str = "") -> None:
            for path in workspace.rglob("*.py"):
                if skip and path.name == skip:
                    continue
                path.write_text(re.sub(r"\bBASE_RATE_BP\b", "DEFAULT_RATE_BP", path.read_text(encoding="utf-8")),
                                encoding="utf-8")

        for seed in corpus.EVALUATION_SEEDS:
            grade, _ = self._grade(seed, rename)
            self.assertTrue(grade["pass"], (seed, grade["failure_codes"]))
            grade, _ = self._grade(seed, lambda workspace: rename(workspace, skip="refunds.py"))
            self.assertIn("semantic_validator_failed", grade["failure_codes"])
            grade, _ = self._grade(seed, lambda workspace: None)
            self.assertFalse(grade["pass"])


if __name__ == "__main__":
    unittest.main()
