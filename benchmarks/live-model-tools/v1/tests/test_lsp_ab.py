from __future__ import annotations

import os
from unittest import mock
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

import corpus  # noqa: E402
from omh_live import (  # noqa: E402
    _current_session_environment,
    current_session_argv,
    directive_text,
    edit_directive,
    rename_directive,
)
from runner import _snapshot, execute_one, run_matrix  # noqa: E402
from validation import changed_paths, validate  # noqa: E402

REPO = BASE.parents[2]

# A correct semantic rename, written out per reference (what pyright's rename produces).
SEMANTIC = {
    "RENAME-ALIAS": {
        "src/benchapp/quota.py": [("def compute_quota(units", "def allocate_quota(units")],
        "src/benchapp/api.py": [("import compute_quota", "import allocate_quota"), ('["compute_quota"]', '["allocate_quota"]')],
        "src/benchapp/service.py": [("import compute_quota as", "import allocate_quota as")],
        "src/benchapp/report.py": [("quota.compute_quota(units)", "quota.allocate_quota(units)")],
        "tests/test_quota.py": [("api import compute_quota", "api import allocate_quota"), ("assert compute_quota(", "assert allocate_quota(")],
    },
    "RENAME-SHADOW": {
        "src/benchapp/limits.py": [("def parse_limit(", "def read_limit(")],
        "src/benchapp/cli.py": [("import parse_limit", "import read_limit"), ("return parse_limit(", "return read_limit(")],
        "src/benchapp/batch.py": [("limits.parse_limit)", "limits.read_limit)")],
        "tests/test_limits.py": [("limits import parse_limit", "limits import read_limit"), ("assert parse_limit(", "assert read_limit(")],
    },
}
NAIVE = {"RENAME-ALIAS": ("compute_quota", "allocate_quota"), "RENAME-SHADOW": ("parse_limit", "read_limit")}


class LspSurfaceTests(unittest.TestCase):
    def _argv(self, surface: str) -> list[str]:
        route = {"selected_model": "m", "selected_reasoning_effort": "high", "model_family": "f"}
        return current_session_argv("hermes", route=route, provider="og", usage_file=Path("u.json"),
                                    prompt="p", workspace=Path("w"), edit_surface=surface)

    def test_lsp_argv_adds_toolset_and_others_unchanged(self) -> None:
        patch, hashline, lsp = self._argv("patch"), self._argv("hashline"), self._argv("lsp")
        expected = ["hermes", "--oneshot", "p", "--in", "w", "--provider", "og", "--model", "m",
                    "--reasoning", "high", "--toolsets", "{}", "--usage-file", "u.json"]
        self.assertEqual(patch, [item if item != "{}" else "file,terminal" for item in expected])
        self.assertEqual(hashline, [item if item != "{}" else "omh-hashline,terminal" for item in expected])
        self.assertEqual(lsp, [item if item != "{}" else "file,terminal,omh-lsp" for item in expected])

    def test_lsp_env_flag(self) -> None:
        with mock.patch.dict(os.environ, {"OMH_LSP_TOOLS": "1", "OMH_HASHLINE_TOOLS": "1"}):
            self.assertNotIn("OMH_LSP_TOOLS", _current_session_environment(Path("w"), "patch"))
            self.assertNotIn("OMH_HASHLINE_TOOLS", _current_session_environment(Path("w"), "lsp"))
        self.assertEqual(_current_session_environment(Path("w"), "lsp").get("OMH_LSP_TOOLS"), "1")
        self.assertNotIn("OMH_LSP_TOOLS", _current_session_environment(Path("w"), "patch"))
        self.assertNotIn("OMH_LSP_TOOLS", _current_session_environment(Path("w"), "hashline"))

    def test_existing_directives_byte_identical(self) -> None:
        tail = ("Do not modify files through terminal commands (sed, perl, python, shell redirection); "
                "use terminal only to search, run tests, and write the answer file.")
        self.assertEqual(edit_directive("patch"), "EDIT TOOL RULE: read source files with `read_file` and change existing files only with `patch`. " + tail)
        self.assertEqual(edit_directive("hashline"), "EDIT TOOL RULE: read source files with `hashline_read` and change existing files only with `hashline_edit`. " + tail)
        self.assertEqual(directive_text("patch", True), edit_directive("patch"))
        self.assertIsNone(directive_text("lsp", False))

    def test_rename_directive_pair_differs_only_in_tool_names(self) -> None:
        control, treatment = rename_directive("patch"), rename_directive("lsp")
        self.assertIn("`lsp_rename`", treatment)
        self.assertNotIn("lsp_", control)
        swapped = (treatment.replace("lsp_definition", "search_files")
                   .replace("lsp_references", "search_files").replace("lsp_rename", "patch"))
        self.assertEqual(swapped, control)
        self.assertEqual(directive_text("lsp", "rename"), treatment)
        with self.assertRaises(ValueError):
            rename_directive("hashline")

    def test_cli_guards(self) -> None:
        for args in (["--edit-surface", "lsp"], ["--edit-surface", "hashline", "--edit-directive", "rename"]):
            completed = subprocess.run([sys.executable, str(BASE / "bench.py"), "smoke", *args],
                                       capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 2, completed.stderr)


class GitInitWorkspaceTests(unittest.TestCase):
    def _manifest(self) -> dict:
        return json.loads((BASE / "manifest.json").read_text())

    def test_git_init_creates_repo_and_is_ignored_by_changed_paths(self) -> None:
        import runner
        captured: dict = {}
        original = runner.validate

        def spy(template_id, task_class, workspace, *rest):
            captured["git"] = (workspace / ".git").is_dir()
            captured["initial_has_git"] = any(key.startswith(".git/") for key in rest[-1])
            captured["paths"] = changed_paths(workspace, rest[-1])
            return original(template_id, task_class, workspace, *rest)

        runner.validate = spy
        try:
            with TemporaryDirectory() as root:
                record = execute_one(BASE, self._manifest(), "development", "D-RENAME", "edit", 7919,
                                     "baseline", Path(root) / "runs.jsonl", git_init_workspace=True)
        finally:
            runner.validate = original
        self.assertTrue(captured["git"])
        self.assertFalse(captured["initial_has_git"])
        self.assertEqual(captured["paths"], ["src/benchapp/retries.py", "tests/test_retries.py"])
        self.assertTrue(record["grade"]["pass"])
        # Mirrors edit_directive: null outside the current-session harness.
        self.assertIn("git_init_workspace", record)
        self.assertIsNone(record["git_init_workspace"])

    def test_default_off_has_no_git_dir(self) -> None:
        import runner
        seen: dict = {}
        original = runner.validate

        def spy(template_id, task_class, workspace, *rest):
            seen["git"] = (workspace / ".git").exists()
            return original(template_id, task_class, workspace, *rest)

        runner.validate = spy
        try:
            with TemporaryDirectory() as root:
                record = execute_one(BASE, self._manifest(), "development", "D-RENAME", "edit", 7919,
                                     "baseline", Path(root) / "runs.jsonl")
        finally:
            runner.validate = original
        self.assertFalse(seen["git"])
        self.assertTrue(record["grade"]["pass"])

    def test_bare_git_init_satisfies_hermes_detection(self) -> None:
        # Hermes `find_git_worktree` only checks `(dir / ".git").exists()`.
        from runner import _git_init
        with TemporaryDirectory() as root:
            _git_init(Path(root))
            self.assertTrue((Path(root) / ".git").exists())


class LspAbTemplateTests(unittest.TestCase):
    def _grade(self, template_id: str, seed: int, mutate) -> dict:
        with TemporaryDirectory() as root:
            workspace, private = Path(root) / "w", Path(root) / "p"
            private.mkdir()
            _instance, golden = corpus.materialize("lsp-ab", template_id, "edit", seed, workspace, private)
            initial = _snapshot(workspace)
            mutate(workspace)
            answer = workspace / ".omh-benchmark-answer.json"
            answer.write_text(json.dumps({"changed_paths": []}), encoding="utf-8")
            return validate(template_id, "edit", workspace, golden, answer, [], initial)

    def test_specs(self) -> None:
        self.assertEqual(corpus.all_specs("lsp-ab"), [
            (f"L-{name}", "edit", seed) for name in ("RENAME-ALIAS", "RENAME-SHADOW") for seed in corpus.EVALUATION_SEEDS
        ])

    def test_untouched_fails_semantic_passes_naive_fails(self) -> None:
        for template_id, _task_class, seed in corpus.all_specs("lsp-ab"):
            name = template_id.split("-", 1)[1]

            def semantic(workspace: Path, name=name) -> None:
                for relative, edits in SEMANTIC[name].items():
                    path = workspace / relative
                    text = path.read_text(encoding="utf-8")
                    for before, after in edits:
                        self.assertIn(before, text)
                        text = text.replace(before, after)
                    path.write_text(text, encoding="utf-8")

            def naive(workspace: Path, name=name) -> None:
                old, new = NAIVE[name]
                for path in workspace.rglob("*.py"):
                    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

            with self.subTest(template_id=template_id, seed=seed):
                untouched = self._grade(template_id, seed, lambda workspace: None)
                self.assertFalse(untouched["pass"])
                self.assertIn("semantic_validator_failed", untouched["failure_codes"])
                good = self._grade(template_id, seed, semantic)
                self.assertTrue(good["pass"], good["failure_codes"])
                bad = self._grade(template_id, seed, naive)
                self.assertFalse(bad["pass"])
                self.assertEqual(bad["failure_codes"], ["semantic_validator_failed"])

    def test_seeds_vary_fixture(self) -> None:
        digests = set()
        for seed in corpus.EVALUATION_SEEDS:
            with TemporaryDirectory() as root:
                instance, _ = corpus.materialize("lsp-ab", "L-RENAME-ALIAS", "edit", seed, Path(root) / "w", Path(root) / "p")
                digests.add(instance.fixture_digest)
        self.assertEqual(len(digests), 3)

    def test_fake_run_over_split_passes(self) -> None:
        with TemporaryDirectory() as root:
            receipt = run_matrix(BASE, json.loads((BASE / "manifest.json").read_text()), "lsp-ab",
                                 "baseline", Path(root) / "runs.jsonl")
        self.assertEqual((receipt["scheduled"], receipt["passed"]), (6, 6))


class PinnedCorpusTests(unittest.TestCase):
    def test_evaluation_and_development_output_unchanged(self) -> None:
        with TemporaryDirectory() as root:
            receipt = corpus.generate_public(BASE, Path(root) / "corpus")
            self.assertEqual(receipt["counts"], {"development": 10, "evaluation": 30})
            self.assertEqual(receipt["corpus_digest"], "c4ea899a8e727fcc531776e56306ff0e83d129e2248fe4362614b3d186fa7b33")
            for split in ("development", "evaluation"):
                generated = json.loads((Path(root) / "corpus" / f"{split}.json").read_text())
                ids = [row["template_id"] for row in generated["instances"]]
                self.assertFalse(any(item.startswith("L-") for item in ids))
        # The checked-in generator plans stay byte-identical to origin/main.
        for name in ("corpus/evaluation.json", "corpus/development.json", "manifest.json"):
            shown = subprocess.run(["git", "show", f"origin/main:benchmarks/live-model-tools/v1/{name}"],
                                   cwd=REPO, capture_output=True, check=False)
            if shown.returncode:
                self.skipTest("origin/main not available")
            self.assertEqual(shown.stdout, (BASE / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()


class TestEnvTests(unittest.TestCase):
    def test_test_env_imports_workspace_package_and_pytest(self) -> None:
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        import runner

        if shutil.which("uv") is None:
            self.skipTest("uv not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace/src/benchapp").mkdir(parents=True)
            (root / "workspace/src/benchapp/__init__.py").write_text("VALUE = 7\n", encoding="utf-8")
            python = runner._test_env(root, root / "workspace")
            out = subprocess.run([str(python), "-c", "import benchapp, pytest; print(benchapp.VALUE)"],
                                 capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(out, "7")
            self.assertFalse((root / "workspace" / "testenv").exists())

    def test_live_task_names_interpreter_only_when_given(self) -> None:
        from pathlib import Path

        import runner

        plain = runner._live_task("Do it.")
        self.assertNotIn("pytest", plain)
        named = runner._live_task("Do it.", Path("/x/bin/python"))
        self.assertIn("/x/bin/python -m pytest -q", named)
        self.assertTrue(named.startswith("Do it.\n\n"))
        self.assertTrue(named.endswith(plain[len("Do it.\n\n"):]))
