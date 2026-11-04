from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))
sys.path.insert(0, str(BASE / "adapters"))

import corpus  # noqa: E402
from fake_harness import IMPACT_EDITS  # noqa: E402
from omh_live import _current_session_environment, current_session_argv, directive_text, edit_directive  # noqa: E402
from runner import _snapshot, run_matrix  # noqa: E402
from validation import validate  # noqa: E402

# The edit a model makes when it changes the definition (and the definition's own test) but no caller.
DEFINITION_ONLY = {
    "SIGNATURE": ("src/benchapp/pricing.py", "tests/test_pricing.py"),
    "RETURN-SHAPE": ("src/benchapp/quotes.py", "tests/test_quotes.py"),
    "KWARG": ("src/benchapp/http_client.py",),
}


def _apply(workspace: Path, edits: list[tuple[str, str, str]], only: tuple[str, ...] | None = None) -> None:
    for relative, pattern, replacement in edits:
        if only is not None and relative not in only:
            continue
        path = workspace / relative
        path.write_text(re.sub(pattern, replacement, path.read_text(encoding="utf-8")), encoding="utf-8")


class ImpactSplitTests(unittest.TestCase):
    def test_split_has_five_templates_three_seeds(self) -> None:
        specs = corpus.all_specs(corpus.IMPACT_AB_SPLIT)
        self.assertEqual(len(specs), 15)
        self.assertEqual(sorted({spec[0] for spec in specs}),
                         ["I-CONTROL", "I-DEFAULTED", "I-KWARG", "I-RETURN-SHAPE", "I-SIGNATURE"])
        self.assertIn(corpus.IMPACT_AB_SPLIT, corpus.SPLITS)

    def test_pinned_corpus_is_unchanged(self) -> None:
        with TemporaryDirectory() as root:
            receipt = corpus.generate_public(BASE, Path(root) / "corpus")
        self.assertEqual(receipt["counts"], {"development": 10, "evaluation": 30})

    def _grade(self, template: str, edit) -> dict:
        name = template.split("-", 1)[1]
        with TemporaryDirectory() as root:
            workspace, private = Path(root) / "w", Path(root) / "p"
            private.mkdir()
            seed = corpus.EVALUATION_SEEDS[0]
            _, golden = corpus.materialize(corpus.IMPACT_AB_SPLIT, template, "edit", seed, workspace, private)
            initial = _snapshot(workspace)
            edit(workspace, name)
            answer = workspace / ".omh-benchmark-answer.json"
            answer.write_text('{"changed_paths": []}', encoding="utf-8")
            return validate(template, "edit", workspace, golden, answer, [], initial)

    def test_reference_edit_passes_every_template(self) -> None:
        for template in ("I-SIGNATURE", "I-RETURN-SHAPE", "I-KWARG", "I-CONTROL", "I-DEFAULTED"):
            grade = self._grade(template, lambda workspace, name: _apply(workspace, IMPACT_EDITS[name]))
            self.assertTrue(grade["pass"], (template, grade["failure_codes"]))

    def test_definition_only_edit_fails(self) -> None:
        for name, only in DEFINITION_ONLY.items():
            grade = self._grade(f"I-{name}", lambda workspace, n, only=only: _apply(workspace, IMPACT_EDITS[n], only))
            self.assertIn("semantic_validator_failed", grade["failure_codes"], name)

    def test_kwarg_options_caller_alone_breaks(self) -> None:
        # Everything a type checker reports fixed, the `**options` caller left: still a fail.
        edits = [edit for edit in IMPACT_EDITS["KWARG"] if edit[0] != "src/benchapp/crawler.py"]
        grade = self._grade("I-KWARG", lambda workspace, name: _apply(workspace, edits))
        self.assertIn("semantic_validator_failed", grade["failure_codes"])

    def test_untouched_workspace_fails(self) -> None:
        for template in ("I-SIGNATURE", "I-RETURN-SHAPE", "I-KWARG", "I-CONTROL", "I-DEFAULTED"):
            grade = self._grade(template, lambda workspace, name: None)
            self.assertFalse(grade["pass"], template)

    def test_new_test_file_is_in_scope(self) -> None:
        def edit(workspace: Path, name: str) -> None:
            _apply(workspace, IMPACT_EDITS[name])
            (workspace / "tests/test_negative.py").write_text("def test_x():\n    pass\n", encoding="utf-8")

        grade = self._grade("I-CONTROL", edit)
        self.assertTrue(grade["pass"], grade["failure_codes"])

    def test_pytest_style_tests_do_not_fail_a_correct_edit(self) -> None:
        # Measured on the first live run: a correct edit whose new test imported pytest scored as a fail.
        def edit(workspace: Path, name: str) -> None:
            _apply(workspace, IMPACT_EDITS[name])
            (workspace / "tests/test_quotes.py").write_text(
                "import pytest\n\n\n@pytest.mark.parametrize('n', [1, 2])\ndef test_n(n):\n    assert n\n",
                encoding="utf-8")

        grade = self._grade("I-RETURN-SHAPE", edit)
        self.assertTrue(grade["pass"], grade["failure_codes"])

    def test_fake_matrix_passes(self) -> None:
        with TemporaryDirectory() as root:
            receipt = run_matrix(BASE, corpus_manifest(), corpus.IMPACT_AB_SPLIT, "baseline", Path(root) / "r.jsonl")
        self.assertEqual((receipt["scheduled"], receipt["passed"]), (15, 15))


def corpus_manifest() -> dict:
    import json

    return json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))


class ImpactSurfaceTests(unittest.TestCase):
    def test_argv_matches_lsp_toolsets(self) -> None:
        route = {"selected_model": "m", "selected_reasoning_effort": "high", "model_family": "f"}
        argv = {surface: current_session_argv("hermes", route=route, provider="p", usage_file=Path("u"), prompt="x",
                                              workspace=Path("w"), edit_surface=surface)
                for surface in ("patch", "lsp", "impact")}
        self.assertEqual(argv["impact"], argv["lsp"])
        self.assertIn("file,terminal", argv["patch"])

    def test_directive_is_the_patch_rule_byte_for_byte(self) -> None:
        self.assertEqual(edit_directive("impact"), edit_directive("patch"))
        self.assertEqual(directive_text("impact", True), directive_text("patch", True))

    def test_env_flags_reach_only_the_impact_arm(self) -> None:
        with mock.patch.dict(os.environ, {"OMH_IMPACT_CHECK": "1", "OMH_LSP_TOOLS": "1"}):
            patch_env = _current_session_environment(Path("w"), "patch")
            impact_env = _current_session_environment(Path("w"), "impact")
        self.assertNotIn("OMH_IMPACT_CHECK", patch_env)
        self.assertNotIn("OMH_LSP_TOOLS", patch_env)
        self.assertEqual((impact_env["OMH_IMPACT_CHECK"], impact_env["OMH_LSP_TOOLS"]), ("1", "1"))


if __name__ == "__main__":
    unittest.main()
