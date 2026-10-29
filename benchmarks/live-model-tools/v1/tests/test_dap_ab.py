from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

import corpus  # noqa: E402
from omh_live import (  # noqa: E402
    _current_session_environment,
    current_session_argv,
    debug_directive,
    directive_text,
    edit_directive,
    rename_directive,
)
from runner import _snapshot, run_matrix  # noqa: E402
from validation import validate  # noqa: E402

# The reference fix per template (what the fake harness applies).
REFERENCE = {
    "MUTABLE-DEFAULT": ("src/benchapp/orders.py",
                        "def open_order(customer: str, lines=[]) -> Order:\n    return Order(customer, lines)",
                        "def open_order(customer: str, lines=None) -> Order:\n    return Order(customer, [] if lines is None else lines)"),
    "ALIASED-STATE": ("src/benchapp/plans.py", "return replace(BASE, name=name)",
                      "return replace(BASE, name=name, limits=dict(BASE.limits))"),
    "ORDER-DEPENDENT": ("src/benchapp/convert.py", "key = (amount, SETTINGS['currency'])",
                        "key = (amount, SETTINGS['currency'], SETTINGS['rate_percent'])"),
}
# The plausible wrong fix reading suggests, per template:
# - MUTABLE-DEFAULT: "the order carries old lines, so clear them" -> `order.lines.clear()` in
#   build_order. The visible tests pass, but every default order still shares one list.
# - ALIASED-STATE: "upgrade mutates the plan, so copy it first" -> `copy.copy(plan)` in upgrade.
#   Still shallow: the copy shares BASE's limits dict, so the plain plan still sees the upgrade.
# - ORDER-DEPENDENT: "the cache must know the settings" -> key by `id(SETTINGS)`. configure()
#   mutates that same dict in place, so the id never changes and the stale rate stays cached.
WRONG = {
    "MUTABLE-DEFAULT": ("src/benchapp/checkout.py", "    order = open_order(customer)\n",
                        "    order = open_order(customer)\n    order.lines.clear()\n"),
    "ALIASED-STATE": ("src/benchapp/upgrades.py",
                      "def upgrade(plan: Plan, feature: str, extra_daily: int) -> Plan:\n",
                      "def upgrade(plan: Plan, feature: str, extra_daily: int) -> Plan:\n    import copy\n    plan = copy.copy(plan)\n"),
    "ORDER-DEPENDENT": ("src/benchapp/convert.py", "key = (amount, SETTINGS['currency'])",
                        "key = (amount, SETTINGS['currency'], id(SETTINGS))"),
}


def _edit(spec):
    relative, before, after = spec

    def apply(workspace: Path) -> None:
        path = workspace / relative
        text = path.read_text(encoding="utf-8")
        if before not in text:
            raise AssertionError(f"anchor missing in {relative}: {before!r}")
        path.write_bytes(text.replace(before, after).encode("utf-8"))
    return apply


class DapAbTemplateTests(unittest.TestCase):
    def _grade(self, template_id: str, seed: int, mutate) -> dict:
        with TemporaryDirectory() as root:
            workspace, private = Path(root) / "w", Path(root) / "p"
            private.mkdir()
            _instance, golden = corpus.materialize("dap-ab", template_id, "edit", seed, workspace, private)
            initial = _snapshot(workspace)
            mutate(workspace)
            answer = workspace / ".omh-benchmark-answer.json"
            answer.write_text(json.dumps({"changed_paths": []}), encoding="utf-8")
            return validate(template_id, "edit", workspace, golden, answer, [], initial)

    def test_specs(self) -> None:
        self.assertEqual(corpus.all_specs("dap-ab"), [
            (f"D-{name}", "edit", seed)
            for name in ("MUTABLE-DEFAULT", "ALIASED-STATE", "ORDER-DEPENDENT") for seed in (104729, 130363, 155921)
        ])

    def test_untouched_fails_reference_passes_wrong_fix_fails(self) -> None:
        for template_id, _task_class, seed in corpus.all_specs("dap-ab"):
            name = template_id.split("-", 1)[1]
            with self.subTest(template_id=template_id, seed=seed):
                untouched = self._grade(template_id, seed, lambda workspace: None)
                self.assertFalse(untouched["pass"])
                self.assertIn("semantic_validator_failed", untouched["failure_codes"])
                good = self._grade(template_id, seed, _edit(REFERENCE[name]))
                self.assertTrue(good["pass"], good["failure_codes"])
                bad = self._grade(template_id, seed, _edit(WRONG[name]))
                self.assertFalse(bad["pass"])
                self.assertEqual(bad["failure_codes"], ["semantic_validator_failed"])

    def test_weakened_tests_and_out_of_scope_edits_fail(self) -> None:
        name = "MUTABLE-DEFAULT"
        fix = _edit(REFERENCE[name])

        def drop_test(workspace: Path) -> None:
            fix(workspace)
            path = workspace / "tests/test_checkout.py"
            text = path.read_text(encoding="utf-8")
            path.write_bytes(text[:text.index("def test_two_line_order")].encode("utf-8"))

        def touch_task(workspace: Path) -> None:
            fix(workspace)
            (workspace / "pyproject.toml").write_bytes(b"[project]\nname='x'\n")

        self.assertIn("semantic_validator_failed", self._grade(f"D-{name}", 104729, drop_test)["failure_codes"])
        self.assertIn("mutation_outside_scope", self._grade(f"D-{name}", 104729, touch_task)["failure_codes"])

    def test_seeds_vary_fixture(self) -> None:
        for name in REFERENCE:
            digests = set()
            for seed in corpus.EVALUATION_SEEDS:
                with TemporaryDirectory() as root:
                    instance, _ = corpus.materialize("dap-ab", f"D-{name}", "edit", seed, Path(root) / "w", Path(root) / "p")
                    digests.add(instance.fixture_digest)
            self.assertEqual(len(digests), 3, name)

    def test_prompt_names_test_command_not_cause(self) -> None:
        with TemporaryDirectory() as root:
            instance, _ = corpus.materialize("dap-ab", "D-ORDER-DEPENDENT", "edit", 104729, Path(root) / "w", Path(root) / "p")
        self.assertIn("python -m pytest -q tests/test_invoice.py", instance.prompt)
        self.assertIn("Find and fix the cause", instance.prompt)
        for word in ("cache", "default", "alias", "copy", "order"):
            self.assertNotIn(word, instance.prompt.lower())

    def test_fake_run_over_split_passes_and_builds_both_arms(self) -> None:
        with TemporaryDirectory() as root:
            output = Path(root) / "runs.jsonl"
            receipt = run_matrix(BASE, json.loads((BASE / "manifest.json").read_text()), "dap-ab", "baseline", output)
            records = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual((receipt["scheduled"], receipt["passed"]), (9, 9))
        for record in records:
            self.assertEqual(record["observation"]["toolsets"], {"patch": "file,terminal", "dap": "file,terminal,omh-dap"})


class DapSurfaceTests(unittest.TestCase):
    def _argv(self, surface: str) -> list[str]:
        route = {"selected_model": "m", "selected_reasoning_effort": "high", "model_family": "f"}
        return current_session_argv("hermes", route=route, provider="og", usage_file=Path("u.json"),
                                    prompt="p", workspace=Path("w"), edit_surface=surface)

    def test_dap_argv_adds_toolset_and_others_unchanged(self) -> None:
        expected = ["hermes", "--oneshot", "p", "--in", "w", "--provider", "og", "--model", "m",
                    "--reasoning", "high", "--toolsets", "{}", "--usage-file", "u.json"]
        for surface, toolsets in (("patch", "file,terminal"), ("hashline", "omh-hashline,terminal"),
                                  ("lsp", "file,terminal,omh-lsp"), ("dap", "file,terminal,omh-dap")):
            self.assertEqual(self._argv(surface), [item if item != "{}" else toolsets for item in expected], surface)

    def test_dap_env_flag_only_in_dap_arm(self) -> None:
        inherited = {"OMH_DAP_TOOLS": "1", "OMH_LSP_TOOLS": "1", "OMH_HASHLINE_TOOLS": "1"}
        with mock.patch.dict(os.environ, inherited):
            for surface in ("patch", "hashline", "lsp"):
                self.assertNotIn("OMH_DAP_TOOLS", _current_session_environment(Path("w"), surface), surface)
            dap = _current_session_environment(Path("w"), "dap")
        self.assertEqual(dap.get("OMH_DAP_TOOLS"), "1")
        self.assertNotIn("OMH_LSP_TOOLS", dap)
        self.assertNotIn("OMH_HASHLINE_TOOLS", dap)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OMH_DAP_TOOLS", None)
            self.assertNotIn("OMH_DAP_TOOLS", _current_session_environment(Path("w"), "patch"))

    def test_debug_directive_pair_differs_only_in_tool_phrase(self) -> None:
        control, treatment = debug_directive("patch"), debug_directive("dap")
        self.assertEqual(control, "When a test fails and the cause is not obvious from reading, run the failing test "
                                  "and inspect state with `terminal` (print statements, `python -c`) before editing. "
                                  "If the same test still fails after three edits, stop editing and inspect state again "
                                  "to find the cause.")
        swapped = treatment.replace("`debug_python` (breakpoints, locals, evaluate)",
                                    "`terminal` (print statements, `python -c`)")
        self.assertEqual(swapped, control)
        self.assertNotIn("debug_python", control)
        self.assertEqual(directive_text("dap", "debug"), treatment)
        self.assertEqual(directive_text("patch", "debug"), control)
        for surface in ("hashline", "lsp"):
            with self.assertRaises(ValueError):
                debug_directive(surface)

    def test_existing_directives_unchanged(self) -> None:
        tail = ("Do not modify files through terminal commands (sed, perl, python, shell redirection); "
                "use terminal only to search, run tests, and write the answer file.")
        self.assertEqual(edit_directive("patch"), "EDIT TOOL RULE: read source files with `read_file` and change existing files only with `patch`. " + tail)
        self.assertEqual(edit_directive("hashline"), "EDIT TOOL RULE: read source files with `hashline_read` and change existing files only with `hashline_edit`. " + tail)
        self.assertEqual(rename_directive("patch"), "EDIT TOOL RULE: find symbol definitions with `search_files` and symbol uses with "
                         "`search_files`, rename symbols with `patch`, and change other code with `patch`. " + tail)
        self.assertEqual(rename_directive("lsp"), "EDIT TOOL RULE: find symbol definitions with `lsp_definition` and symbol uses with "
                         "`lsp_references`, rename symbols with `lsp_rename`, and change other code with `patch`. " + tail)

    def test_cli_guards(self) -> None:
        for args in (["--edit-surface", "dap"], ["--edit-surface", "lsp", "--edit-directive", "debug"],
                     ["--harness", "hermes_current_session", "--edit-surface", "dap", "--edit-directive", "debug"]):
            completed = subprocess.run([sys.executable, str(BASE / "bench.py"), "run", "--split", "dap-ab", *args],
                                       capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 2, completed.stderr)


class DapTestEnvTests(unittest.TestCase):
    def test_test_env_installs_debugpy_and_task_text_names_no_debugger(self) -> None:
        import runner

        if shutil.which("uv") is None:
            self.skipTest("uv not on PATH")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "workspace/src/benchapp").mkdir(parents=True)
            (root / "workspace/src/benchapp/__init__.py").write_bytes(b"VALUE = 3\n")
            python = runner._test_env(root, root / "workspace")
            out = subprocess.run([str(python), "-c", "import benchapp, debugpy, pytest; print(benchapp.VALUE)"],
                                 capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(out, "3")
            adapter = subprocess.run([str(python), "-c", "import debugpy.adapter"], capture_output=True, check=False)
            self.assertEqual(adapter.returncode, 0, adapter.stderr)
        task = runner._live_task("Do it.", Path("/x/bin/python"))
        self.assertNotIn("debug", task.lower())


if __name__ == "__main__":
    unittest.main()
