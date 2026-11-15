"""`omh_gather_evidence` runs only bounded probes inside the host working directory.

The model chooses `project_root` and the command suffix, so both are bounded:
the root must be the host working directory or inside it, `-m unittest` takes
only reporting flags and a selection of test*.py modules inside workdir that
default discovery would also run, `git diff` refuses options that write a file, run a
configured program, or read outside the repository, and no `uv run` prefix is
shipped. Every path a probe opens because the suffix named it -- a compileall or
git diff argument, or the value of an omh option -- must stay inside workdir.
"""
from __future__ import annotations

import argparse
import compileall
import contextlib
import io
import itertools
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from omh.commands.main import build_parser
from omh.plugin_bundle.omh import runtime_paths
from omh.plugin_bundle.omh.tools import evidence_tool

_REAL_RUN = subprocess.run


class _ParserCaptured(Exception):
    pass


def _compileall_parser() -> argparse.ArgumentParser:
    """The parser `python -m compileall` builds on this interpreter."""
    captured: list[argparse.ArgumentParser] = []

    def capture(parser, *_args, **_kwargs):
        captured.append(parser)
        raise _ParserCaptured

    with patch.object(sys, "argv", ["compileall"]), patch.object(argparse.ArgumentParser, "parse_args", capture):
        with contextlib.suppress(_ParserCaptured):
            compileall.main()
    return captured[0]


def _parse(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace | None:
    """What argparse makes of `argv`, or None when it refuses it."""
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            return parser.parse_args(argv)
        except SystemExit:
            return None


def _subcommand(parser: argparse.ArgumentParser, names: tuple[str, ...]) -> argparse.ArgumentParser:
    for name in names:
        action = next(item for item in parser._actions if isinstance(item, argparse._SubParsersAction))
        parser = action.choices[name]
    return parser


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {option for action in parser._actions for option in action.option_strings} - {"-h", "--help"}


class EvidenceProbeBoundsTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.host_cwd = base / "project"
        self.host_cwd.mkdir()
        self.outside = base / "elsewhere"
        self.outside.mkdir()
        cwd_patch = patch.object(runtime_paths, "runtime_cwd", return_value=self.host_cwd)
        cwd_patch.start()
        self.addCleanup(cwd_patch.stop)
        run_patch = patch.object(evidence_tool.subprocess, "run",
                                 return_value=types.SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.child = run_patch.start()
        self.addCleanup(run_patch.stop)

    def gather(self, commands: list[str], **args: str) -> dict:
        return json.loads(evidence_tool.omh_evidence_handler({"commands": commands, **args}))

    def assert_refused(self, command: str, reason: str) -> None:
        with self.subTest(command=command):
            self.child.reset_mock()
            result = self.gather([command])
            self.assertFalse(result["all_pass"])
            self.assertEqual(result["results"][0]["evidence_type"], "rejected")
            self.assertIn(reason, result["results"][0]["output_tail"])
            self.child.assert_not_called()

    def test_project_root_defaults_to_the_host_working_directory(self) -> None:
        result = self.gather(["python -m unittest"])
        self.assertTrue(result["all_pass"])
        self.assertEqual(result["project_root"], str(self.host_cwd))
        self.assertEqual(self.child.call_args.kwargs["cwd"], str(self.host_cwd))

    def test_project_root_inside_the_host_working_directory_runs(self) -> None:
        inner = self.host_cwd / "pkg"
        inner.mkdir()
        result = self.gather(["python -m unittest -v"], project_root=str(inner))
        self.assertTrue(result["all_pass"])
        self.assertEqual(self.child.call_args.kwargs["cwd"], str(inner))

    def test_project_root_outside_the_host_working_directory_is_refused(self) -> None:
        for root in (self.outside, self.host_cwd.parent, Path(os.sep)):
            with self.subTest(root=str(root)):
                result = self.gather(["python -m unittest"], project_root=str(root))
                self.assertEqual(result["error"], "project_root must be the host working directory or inside it")
        self.child.assert_not_called()

    def test_a_symlink_inside_the_working_directory_cannot_leave_it(self) -> None:
        link = self.host_cwd / "escape"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        result = self.gather(["python -m unittest"], project_root=str(link))
        self.assertEqual(result["error"], "project_root must be the host working directory or inside it")
        result = self.gather(["python -m unittest"], workdir=str(link))
        self.assertEqual(result["error"], "workdir must stay within project_root")
        self.child.assert_not_called()

    def test_unittest_takes_only_reporting_flags(self) -> None:
        for command in (
            "python -m unittest discover",
            "python -m unittest discover -s /tmp",
            "python3 -m unittest -s tests",
            "python -m unittest -t .",
            "python -m unittest -p '*.py'",
            "python -m unittest tests.test_x",
            "python -m unittest -v evil_module",
            "python3 -m unittest /tmp/payload.py",
        ):
            self.assert_refused(command, "unittest argument not allowed")

    def make_test_tree(self) -> None:
        """tests/test_a.py (a class with test methods) in a regular package, and look-alikes."""
        tests = self.host_cwd / "tests"
        (tests / "nested").mkdir(parents=True)
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (tests / "nested" / "__init__.py").write_text("", encoding="utf-8")
        body = ("import os\nimport unittest\n\n\ndef helper():\n    pass\n\n\n"
                "class CaseA(unittest.TestCase):\n    def test_one(self):\n        pass\n\n"
                "    def setUp(self):\n        pass\n")
        (tests / "test_a.py").write_text(body, encoding="utf-8")
        (tests / "nested" / "test_deep.py").write_text(body, encoding="utf-8")
        (tests / "helpers.py").write_text("x = 1\n", encoding="utf-8")
        (self.host_cwd / "test_top.py").write_text(body, encoding="utf-8")
        (self.host_cwd / "nopkg").mkdir()
        (self.host_cwd / "nopkg" / "test_n.py").write_text(body, encoding="utf-8")
        (self.host_cwd / "test").mkdir()
        (self.host_cwd / "test" / "__init__.py").write_text("", encoding="utf-8")
        (self.host_cwd / "test" / "test_shadow.py").write_text(body, encoding="utf-8")
        # Named like a standard-library package the interpreter may already hold.
        (self.host_cwd / "email").mkdir()
        (self.host_cwd / "email" / "__init__.py").write_text("", encoding="utf-8")
        (self.host_cwd / "email" / "test_e.py").write_text(body, encoding="utf-8")

    def test_unittest_may_name_a_test_module_inside_workdir(self) -> None:
        """The task's own test can be named, so a red unrelated suite does not hide its result."""
        self.make_test_tree()
        for command in (
            "python3 -m unittest tests.test_a",
            "python3 -m unittest tests.test_a.CaseA",
            "python3 -m unittest tests.test_a.CaseA.test_one",
            "python3 -m unittest -v tests.test_a tests.nested.test_deep",
            "python3 -m unittest tests/test_a.py",
            "python3 -m unittest tests/nested/test_deep.py -f",
            "python3 -m unittest test_top",
            "python3 -m unittest test_top.py",
            "python -m unittest -k one tests.test_a",
            # `sys.stdlib_module_names` leaves out CPython's own `test` package,
            # so a workdir `test/` package is admitted like discovery runs it.
            "python3 -m unittest test.test_shadow",
        ):
            argv = self.assert_admitted(command)
            self.assertEqual(argv, shlex.split(command))

    def test_unittest_refuses_a_selection_discovery_would_not_run(self) -> None:
        self.make_test_tree()
        for command, reason in (
            ("python3 -m unittest tests.helpers", "names no test*.py module inside workdir"),
            ("python3 -m unittest tests", "names no test*.py module inside workdir"),
            ("python3 -m unittest tests.test_missing", "names no test*.py module inside workdir"),
            ("python3 -m unittest nopkg.test_n", "names no test*.py module inside workdir"),
            ("python3 -m unittest nopkg/test_n.py", "names no test*.py module inside workdir"),
            ("python3 -m unittest tests/helpers.py", "names no test*.py module inside workdir"),
            ("python3 -m unittest tests/test_missing.py", "names no test*.py module inside workdir"),
            # A dotted name past the module is called by unittest when it is not a TestCase.
            ("python3 -m unittest tests.test_a.helper", "names no class defined in the test module"),
            ("python3 -m unittest tests.test_a.os", "names no class defined in the test module"),
            ("python3 -m unittest tests.test_a.unittest.main", "names no class defined in the test module"),
            ("python3 -m unittest tests.test_a.os.getcwd", "names no class defined in the test module"),
            ("python3 -m unittest tests.test_a.CaseA.setUp", "names a method that is not test*"),
            ("python3 -m unittest tests.test_a.CaseA.test_one.x", "names more than a test class and method"),
            # Standard-library and installed modules, wherever they would resolve.
            ("python3 -m unittest unittest", "names a standard-library module"),
            ("python3 -m unittest os.system", "names a standard-library module"),
            ("python3 -m unittest json.tool", "names a standard-library module"),
            ("python3 -m unittest email.test_e", "names a standard-library module"),
            ("python3 -m unittest email/test_e.py", "names a standard-library module"),
            ("python3 -m unittest omh.cli", "names no test*.py module inside workdir"),
            # Paths and shapes the name grammar never admits.
            ("python3 -m unittest /tmp/test_x.py", "absolute or home-relative"),
            ("python3 -m unittest ../test_x.py", "'..' component"),
            ("python3 -m unittest ~/test_x.py", "absolute or home-relative"),
            ("python3 -m unittest tests/test-a.py", "not a test file path"),
            ("python3 -m unittest tests/te.st_a.py", "not a test file path"),
            ("python3 -m unittest tests.test_a.", "not a dotted test name"),
            ("python3 -m unittest tests..test_a", "not a dotted test name"),
            ("python3 -m unittest 'tests.test_a CaseA'", "not a dotted test name"),
            ("python3 -m unittest DISCOVER", "discover is not allowed"),
            # Options still follow the reporting-flag rule, wherever they sit.
            ("python3 -m unittest tests.test_a -s /tmp", "unittest argument not allowed: -s"),
            ("python3 -m unittest tests.test_a --start-directory=/tmp", "unittest argument not allowed: --start"),
            ("python3 -m unittest tests.test_a -c print", "unittest argument not allowed: print"),
        ):
            self.assert_refused(command, reason)

    def test_unittest_refuses_a_selection_that_leaves_workdir_through_a_symlink(self) -> None:
        self.make_test_tree()
        outside_pkg = self.outside / "pkg"
        outside_pkg.mkdir()
        (outside_pkg / "__init__.py").write_text("", encoding="utf-8")
        (outside_pkg / "test_out.py").write_text("x = 1\n", encoding="utf-8")
        try:
            (self.host_cwd / "linked").symlink_to(outside_pkg, target_is_directory=True)
            (self.host_cwd / "tests" / "test_link.py").symlink_to(outside_pkg / "test_out.py")
            mixed = self.host_cwd / "mixed"
            mixed.mkdir()
            (mixed / "__init__.py").symlink_to(outside_pkg / "__init__.py")
            (mixed / "test_m.py").write_text("x = 1\n", encoding="utf-8")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        for command in ("python3 -m unittest linked.test_out", "python3 -m unittest tests.test_link",
                        "python3 -m unittest linked/test_out.py", "python3 -m unittest mixed.test_m"):
            self.assert_refused(command, "resolves outside workdir")

    def test_an_operator_entry_naming_a_module_still_takes_no_other_selection(self) -> None:
        self.make_test_tree()
        with patch.object(evidence_tool, "_allowlist", return_value=("python -m unittest tests.test_a",)):
            self.assert_refused("python -m unittest tests.test_a tests.nested.test_deep", "unittest argument not allowed")

    def test_unittest_reporting_flags_are_allowed(self) -> None:
        for command in ("python -m unittest", "python3 -m unittest -v -f --locals",
                        "python -m unittest -q -b -c", "python -m unittest -k test_name"):
            with self.subTest(command=command):
                self.child.reset_mock()
                self.assertTrue(self.gather([command])["all_pass"])
                self.child.assert_called_once()

    def test_an_operator_entry_naming_a_module_permits_only_that_module(self) -> None:
        with patch.object(evidence_tool, "_allowlist", return_value=("python -m unittest tests.test_a",)):
            self.assertTrue(self.gather(["python -m unittest tests.test_a -v"])["all_pass"])
            self.assert_refused("python -m unittest tests.test_a tests.test_b", "unittest argument not allowed")

    def test_no_uv_run_prefix_is_shipped(self) -> None:
        for entry in evidence_tool._allowlist() + evidence_tool._DEFAULT_ALLOWLIST:
            with self.subTest(entry=entry):
                self.assertNotEqual(entry.split()[:2], ["uv", "run"])
        self.assert_refused("uv run python -m unittest", "command not in allowlist")

    def test_an_operator_added_uv_run_prefix_is_still_bounded(self) -> None:
        with patch.object(evidence_tool, "_allowlist", return_value=("uv run python -m unittest",)):
            self.assert_refused("uv run python -m unittest discover -s /tmp", "unittest argument not allowed")

    def test_git_diff_refuses_file_writes_external_programs_and_outside_reads(self) -> None:
        with patch.object(evidence_tool, "_allowlist", return_value=("git diff --check", "git diff")):
            for command in ("git diff --check --output=/tmp/x", "git diff --output /tmp/x",
                            "git diff --ext-diff", "git diff --textconv", "git diff --no-index /etc/hosts a"):
                self.assert_refused(command, "git diff option not allowed")
            self.assertTrue(self.gather(["git diff --check", "git diff HEAD~1.. -- tests"])["all_pass"])

    def escape_link(self, *, required: bool = True) -> str:
        """`escape` inside the working directory, a symlink to a directory outside it."""
        try:
            (self.host_cwd / "escape").symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            if required:
                self.skipTest("symlinks unavailable")
        return "escape"

    def assert_admitted(self, command: str) -> list[str]:
        with self.subTest(command=command):
            self.child.reset_mock()
            result = self.gather([command])
            self.assertTrue(result["all_pass"], result["results"][0]["output_tail"])
            self.child.assert_called_once()
            return self.child.call_args.args[0]

    def test_compileall_paths_must_stay_inside_workdir(self) -> None:
        outside = shlex.quote(str(self.outside))
        for command, reason in (
            (f"python3 -m compileall {outside}", "compileall path not allowed: absolute or home-relative"),
            ("python3 -m compileall -q ~/project", "compileall path not allowed: absolute or home-relative"),
            ("python -m compileall ../elsewhere", "compileall path not allowed: '..' component"),
            ("python -m compileall src/../../elsewhere", "compileall path not allowed: '..' component"),
            ("python -m compileall -- ../elsewhere", "compileall path not allowed: '..' component"),
            (f"python -m compileall -e {outside} .", "compileall path not allowed: absolute or home-relative"),
            ("python -m compileall -e../elsewhere .", "compileall path not allowed: '..' component"),
            ("python -m compileall -e '' .", "compileall path not allowed: empty"),
            # After `--` every token is a path to argparse, even one that looks
            # like an option.
            (f"python -m compileall . -- -x {outside}", "compileall path not allowed: absolute or home-relative"),
            (f"python -m compileall . -- -e {outside}", "compileall path not allowed: absolute or home-relative"),
        ):
            self.assert_refused(command, reason)

    def test_a_symlink_out_of_workdir_is_refused_without_naming_its_target(self) -> None:
        link = self.escape_link()
        for command in (f"python -m compileall {link}", f"python3 -m compileall -q {link}/leak.py",
                        f"python -m compileall -e {link} .", f"git diff --check {link}/a {link}/b"):
            self.assert_refused(command, "path not allowed: resolves outside workdir")
            self.assertNotIn(str(self.outside), json.dumps(self.gather([command])))

    def test_compileall_options_outside_the_grammar_are_refused(self) -> None:
        for command, reason in (
            ("python -m compileall -i files.txt", "compileall option not allowed: -i (reads more paths"),
            ("python -m compileall -i - .", "compileall option not allowed: -i"),
            (f"python3 -m compileall -fqi{shlex.quote(str(self.outside))} .", "compileall option not allowed: -i"),
            ("python -m compileall -b .", "compileall option not allowed: -b (writes .pyc beside the sources"),
            ("python -m compileall -lb .", "compileall option not allowed: -b"),
            ("python -m compileall -d /x .", "compileall option not allowed: -d"),
            ("python -m compileall -s /x .", "compileall option not allowed: -s"),
            ("python -m compileall -p / .", "compileall option not allowed: -p"),
            ("python -m compileall -e=../x .", "compileall option not allowed: -e with '='"),
            ("python -m compileall --inv timestamp .", "compileall option not allowed: --inv"),
            ("python -m compileall -h", "compileall option not allowed: -h"),
            ("python -m compileall . -r", "compileall option needs a value: -r"),
        ):
            self.assert_refused(command, reason)
            self.assertNotIn(str(self.outside), self.gather([command])["results"][0]["output_tail"])

    def test_compileall_without_a_path_is_refused(self) -> None:
        # With no path compileall compiles every directory on sys.path.
        for command in ("python -m compileall", "python3 -m compileall -q -f", "python -m compileall -x tests --"):
            self.assert_refused(command, "compileall needs a path inside workdir")

    def test_compileall_flags_and_paths_inside_workdir_run(self) -> None:
        (self.host_cwd / "src").mkdir()
        try:
            (self.host_cwd / "inner").symlink_to(self.host_cwd / "src", target_is_directory=True)
            inner = ["python -m compileall -q inner"]
        except (OSError, NotImplementedError):
            inner = []
        for command in (
            "python3 -m compileall -q .",
            "python -m compileall -q -f src",
            "python -m compileall -l -r 2 -x tests src",
            "python -m compileall -qq -o 1 -o 2 --hardlink-dupes src",
            "python -m compileall -e src src",
            "python -m compileall -j 2 --invalidation-mode checked-hash src",
            "python -m compileall -r2 -fq -- src",
            "python3 -m compileall src/missing.py",
            *inner,
        ):
            argv = self.assert_admitted(command)
            tokens = shlex.split(command)
            self.assertEqual(argv, [*tokens[:3], "-e", ".", *tokens[3:]])
            self.assertEqual(self.child.call_args.kwargs["env"]["PYTHONSAFEPATH"], "1")
            self.assertIs(self.child.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_unittest_keeps_the_working_directory_importable_and_reads_no_stdin(self) -> None:
        self.assertTrue(self.gather(["python -m unittest -v"])["all_pass"])
        self.assertNotIn("PYTHONSAFEPATH", self.child.call_args.kwargs["env"])
        self.assertIs(self.child.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def gather_returning(self, command: str, returncode: int, stderr: str) -> dict:
        """Gather one admitted command whose (faked) child exits `returncode` printing `stderr`."""
        self.child.return_value = types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
        return self.gather([command])

    def test_a_run_that_ran_no_test_is_not_a_pass(self) -> None:
        """`Ran 0 tests ... OK` (exit 0 before Python 3.12) and exit 5 prove nothing ran."""
        ran_none = "\n----------------------------------------------------------------------\nRan 0 tests in 0.000s\n\nOK\n"
        for command, returncode, stderr in (
            ("python3 -m unittest", 0, ran_none),
            ("python3 -m unittest -q", 0, ran_none),
            ("python3 -m unittest", 5, ran_none.replace("OK", "NO TESTS RAN")),
            # A test that prints its own summary-looking line does not decide it; the runner's last one does.
            ("python3 -m unittest -v", 0, "Ran 3 tests in 0.1s\n" + ran_none),
        ):
            with self.subTest(command=command, returncode=returncode):
                result = self.gather_returning(command, returncode, stderr)
                self.assertFalse(result["all_pass"])
                self.assertFalse(result["results"][0]["passed"])
                self.assertEqual(result["results"][0]["reason"], "no tests ran")
                self.assertEqual(result["results"][0]["evidence_type"], "observed_local_command")
                self.assertEqual(result["summary"], "0/1 passed")

    def test_a_run_that_ran_tests_still_passes_and_other_exit_fives_are_untouched(self) -> None:
        ran = "\n----------------------------------------------------------------------\nRan {n} tests in 0.001s\n\nOK\n"
        for command, returncode, stderr, passed in (
            ("python3 -m unittest", 0, ran.format(n=3), True),
            ("python3 -m unittest -v", 0, "Ran 0 tests in 0.0s\n" + ran.format(n=1), True),
            ("python3 -m unittest", 0, "Ran 10 tests in 0.1s\n\nOK\n", True),
            # Output whose tail was cut still reads the runner's line from the full output.
            ("python3 -m unittest", 0, ran.format(n=2) + "\n" + "y" * 5_000, True),
            ("python3 -m unittest", 1, ran.format(n=2).replace("OK", "FAILED (failures=1)"), False),
            # Exit 5 means "no tests" only for a test runner.
            ("python3 -m compileall -q .", 5, "", False),
            ("git diff --check", 0, "Ran 0 tests in 0.0s\n", True),
        ):
            with self.subTest(command=command, returncode=returncode, passed=passed):
                result = self.gather_returning(command, returncode, stderr)
                self.assertIs(result["results"][0]["passed"], passed)
                self.assertNotIn("reason", result["results"][0])

    def test_an_operator_added_pytest_prefix_reports_no_tests_ran(self) -> None:
        """pytest exits 5 when it collected nothing; an operator's pytest entry gets the same verdict."""
        with patch.object(evidence_tool, "_allowlist", return_value=("python3 -m pytest", "pytest")):
            for command in ("python3 -m pytest tests", "pytest -q"):
                with self.subTest(command=command):
                    result = self.gather_returning(command, 5, "no tests ran in 0.01s\n")
                    self.assertFalse(result["results"][0]["passed"])
                    self.assertEqual(result["results"][0]["reason"], "no tests ran")
                    result = self.gather_returning(command, 0, "1 passed in 0.01s\n")
                    self.assertTrue(result["results"][0]["passed"])
                    self.assertNotIn("reason", result["results"][0])

    def test_a_named_test_module_passes_in_one_call_while_the_full_suite_is_red(self) -> None:
        """The measured shape: the task's module is fixed, another module still fails."""
        python3 = shutil.which("python3")
        if python3 is None:
            self.skipTest("python3 unavailable")
        tests = self.host_cwd / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("", encoding="utf-8")
        (tests / "test_fixed.py").write_text(
            "import unittest\n\n\nclass Fixed(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
            encoding="utf-8")
        (tests / "test_other.py").write_text(
            "import unittest\n\n\nclass Other(unittest.TestCase):\n    def test_bug(self):\n        self.fail('unrelated')\n",
            encoding="utf-8")
        (self.host_cwd / "empty").mkdir()
        with patch.object(evidence_tool.subprocess, "run", _REAL_RUN):
            whole = self.gather(["python3 -m unittest"])
            named = self.gather(["python3 -m unittest tests.test_fixed", "python3 -m unittest tests/test_fixed.py"])
            nothing = self.gather(["python3 -m unittest"], workdir=str(self.host_cwd / "empty"))
        self.assertFalse(whole["all_pass"])
        self.assertTrue(named["all_pass"], named["results"])
        self.assertEqual(named["summary"], "2/2 passed")
        self.assertIn("Ran 1 test", named["results"][0]["output_tail"])
        self.assertFalse(nothing["all_pass"])
        self.assertEqual(nothing["results"][0]["reason"], "no tests ran")

    def test_a_compileall_module_in_workdir_does_not_run(self) -> None:
        python3 = shutil.which("python3")
        if python3 is None:
            self.skipTest("python3 unavailable")
        version = _REAL_RUN([python3, "-c", "import sys; print(sys.version_info >= (3, 11))"],
                            capture_output=True, text=True, check=False)
        if version.stdout.strip() != "True":
            self.skipTest("PYTHONSAFEPATH needs python3 >= 3.11")
        (self.host_cwd / "compileall.py").write_text('print("SHADOW compileall ran")\n', encoding="utf-8")
        with patch.object(evidence_tool.subprocess, "run", _REAL_RUN):
            result = self.gather(["python3 -m compileall -q ."])
        self.assertTrue(result["all_pass"], result["results"][0]["output_tail"])
        self.assertNotIn("SHADOW", result["results"][0]["output_tail"])

    def test_a_symlinked_file_below_a_compiled_directory_is_skipped(self) -> None:
        if shutil.which("python3") is None:
            self.skipTest("python3 unavailable")
        source = self.host_cwd / "src"
        source.mkdir()
        (source / "ok.py").write_text("x = 1\n", encoding="utf-8")
        (self.outside / "leak.py").write_text("def leaked(:\n", encoding="utf-8")
        try:
            (source / "leak.py").symlink_to(self.outside / "leak.py")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with patch.object(evidence_tool.subprocess, "run", _REAL_RUN):
            result = self.gather(["python3 -m compileall -q src"])
        self.assertTrue(result["all_pass"], result["results"][0]["output_tail"])
        self.assertNotIn("leaked", result["results"][0]["output_tail"])

    def test_compileall_corpus_suffixes_the_guard_admits_parse_inside_workdir(self) -> None:
        """Every suffix of up to three corpus tokens, and of four from a small
        `--` corpus, that the guard admits is read by this interpreter's
        compileall parser as paths inside workdir, with the `-e .` the tool
        adds; and the grammar decides every option that parser defines."""
        self.escape_link(required=False)
        parser = _compileall_parser()
        grammar = evidence_tool._COMPILEALL_GRAMMAR
        self.assertEqual(_options(parser),
                         grammar.flags | grammar.values | grammar.paths | {option for option, _ in grammar.refused})
        alphabet = ("-e", "-e=../x", "-fe../x", "-qe=..", "../x", "/abs", "-i", "-", "--", "-q", "-x", "-b",
                    "-r", "2", "src", ".", "-fq", "-fqe", "escape", "-e.", "--inv", "--invalidation-mode",
                    "timestamp", "-fi-", "-1", "- /../x", "-x -i", "-d", "-p", "-ri", "-xi", "")
        corpora = (
            (alphabet, (1, 2, 3)),
            # A path, `--`, then an option-looking token and a path: four tokens.
            ((".", "--", "-x", "-e", "/abs"), (4,)),
        )
        admitted = 0
        for tokens, sizes in corpora:
            for suffix in (list(item) for size in sizes for item in itertools.product(tokens, repeat=size)):
                if evidence_tool._suffix_rejection(["python", "-m", "compileall"], suffix, self.host_cwd):
                    continue
                admitted += 1
                parsed = _parse(parser, ["-e", ".", *suffix])
                if parsed is None:
                    continue
                with self.subTest(suffix=suffix):
                    self.assertIsNone(parsed.flist)
                    self.assertFalse(parsed.legacy)
                    self.assertEqual((parsed.ddir, parsed.stripdir, parsed.prependdir), (None, None, None))
                    self.assertTrue(parsed.compile_dest)
                    for path in (*parsed.compile_dest, parsed.limit_sl_dest):
                        self.assertTrue(path)
                        self.assertTrue(Path(os.path.realpath(self.host_cwd / path)).is_relative_to(self.host_cwd))
        self.assertGreater(admitted, 100)

    def test_git_diff_paths_must_stay_inside_workdir(self) -> None:
        outside = shlex.quote(str(self.outside))
        with patch.object(evidence_tool, "_allowlist", return_value=("git diff --check", "git diff")):
            for command, reason in (
                # Two paths with one outside the repository make git diff
                # switch to --no-index and print both files.
                (f"git diff {outside}/a {outside}/b", "git diff path not allowed: absolute or home-relative"),
                (f"git diff --check {outside}/a {outside}/b", "git diff path not allowed: absolute"),
                ("git diff ../elsewhere/a ../elsewhere/b", "git diff path not allowed: '..' component"),
                ("git diff HEAD -- ../elsewhere", "git diff path not allowed: '..' component"),
                ("git diff -- ~/a b", "git diff path not allowed: absolute or home-relative"),
                # After `--` a token that starts with `-` is a path, not an option.
                ("git diff --check -- -a/../../elsewhere", "git diff path not allowed: '..' component"),
                (f"git diff -O{outside}/order", "git diff option not allowed: -O (reads an order file)"),
                ("git diff -pO order.txt", "git diff option not allowed: -O"),
                ("git diff --stat -O order.txt HEAD", "git diff option not allowed: -O"),
            ):
                self.assert_refused(command, reason)
            for command in ("git diff --check", "git diff HEAD~1.. -- tests", "git diff main...HEAD -- src",
                            "git diff --stat HEAD", "git diff -- src/a.py src/b.py", "git diff --check -U0 HEAD^.."):
                self.assertEqual(self.assert_admitted(command), shlex.split(command))

    def test_omh_options_that_open_an_outside_path_are_refused(self) -> None:
        outside = shlex.quote(str(self.outside))
        for command, reason in (
            ("omh doctor --profile-isolation a b", "omh doctor option not allowed: --profile-isolation (reads two"),
            ("omh doctor --prof a b", "omh doctor option not allowed: --prof"),
            (f"omh docs workflows --check --output {outside}/W.md", "omh docs workflows path not allowed: absolute"),
            ("omh docs workflows --check --output=../W.md", "omh docs workflows path not allowed: '..' component"),
            ("omh docs workflows --check --output ~/W.md", "omh docs workflows path not allowed: absolute or home"),
            ("omh docs workflows --check --out docs/W.md", "omh docs workflows option not allowed: --out"),
            ("omh release evidence-bundle --write", "option not allowed: --write (writes the bundle into the OMH home)"),
            ("omh release evidence-bundle --verify b.json", "omh release evidence-bundle argument not allowed"),
            ("omh release evidence-bundle --verify=b.json", "omh release evidence-bundle option not allowed: --verify"),
            (f"omh release evidence-bundle --repo-root {outside}", "evidence-bundle path not allowed: absolute"),
            ("omh release evidence-bundle --artifact ../x.whl", "evidence-bundle path not allowed: '..' component"),
            ("omh release evidence-bundle --notes-file ~/n.md", "evidence-bundle path not allowed: absolute or home"),
            ("omh release evidence-bundle --rep .", "omh release evidence-bundle option not allowed: --rep"),
        ):
            self.assert_refused(command, reason)
        for command in (
            "omh doctor --json", "omh doctor --language ko",
            "omh docs workflows --check", "omh docs workflows --check --output docs/WORKFLOWS.md",
            "omh release evidence-bundle --json --verify",
            "omh release evidence-bundle --version 1.0.0 --repo-root . --artifact dist/a.whl --notes-file n.md --json",
            "omh probe --json", "omh harness validate", "omh release checklist --version 1.0.0 --json",
        ):
            self.assertEqual(self.assert_admitted(command), shlex.split(command))

    def test_omh_corpus_suffixes_the_guard_admits_parse_inside_workdir(self) -> None:
        """Every suffix of up to three corpus tokens that the guard admits after a
        bounded omh prefix is read by the real omh parser with no outside path,
        no profile isolation, no `--write`, and no `--verify` PATH."""
        self.escape_link(required=False)
        parser = build_parser()
        alphabet = ("--json", "--language", "ko", "--profile-isolation", "a", "--prof", "--output", "--out",
                    "docs/W.md", "/abs", "../x", "~/x", "escape", "--check", "--installed", "--write", "--verify",
                    "--verify=x", "--repo-root", "--rep", ".", "--artifact", "--notes-file", "--output=../x", "-",
                    "--", "--version", "1.0.0")
        admitted = 0
        for command, _grammar in evidence_tool._OMH_GRAMMARS:
            for size in (1, 2, 3):
                for suffix in map(list, itertools.product(alphabet, repeat=size)):
                    if evidence_tool._suffix_rejection(list(command), suffix, self.host_cwd):
                        continue
                    admitted += 1
                    parsed = _parse(parser, [*command[1:], *suffix])
                    if parsed is None:
                        continue
                    with self.subTest(command=command, suffix=suffix):
                        self.assertFalse(getattr(parsed, "profile_isolation", None))
                        self.assertFalse(getattr(parsed, "write", False))
                        self.assertIn(getattr(parsed, "verify", None), (None, ""))
                        for field in ("output", "repo_root", "artifact", "notes_file"):
                            value = getattr(parsed, field, None)
                            if value is not None:
                                resolved = Path(os.path.realpath(self.host_cwd / Path(value).expanduser()))
                                self.assertTrue(resolved.is_relative_to(self.host_cwd))
        self.assertGreater(admitted, 100)

    def test_every_shipped_prefix_has_a_reviewed_suffix_verdict(self) -> None:
        """A prefix keeps a free suffix only when none of its options opens a path."""
        unbounded = {
            ("omh", "--help"): None,
            ("omh", "probe"): {"--parity", "--roadmap", "--json"},
            ("omh", "harness", "validate"): set(),
            ("omh", "release", "checklist"): {"--version", "--omh-command", "--json"},
            ("omh", "release", "product-readiness"): {"--version", "--omh-command", "--json"},
        }
        bounded = {command for command, _grammar in evidence_tool._OMH_GRAMMARS}
        parser = build_parser()
        for entry in evidence_tool._allowlist() + evidence_tool._DEFAULT_ALLOWLIST:
            tokens = entry.split()
            with self.subTest(entry=entry):
                if tokens[1:3] in (["-m", "unittest"], ["-m", "compileall"]) or tokens[:2] == ["git", "diff"]:
                    continue
                if any(tuple(tokens[: len(command)]) == command for command in bounded):
                    continue
                key = next((command for command in unbounded if tuple(tokens[: len(command)]) == command), None)
                self.assertIsNotNone(key, f"{entry!r} has no suffix verdict in evidence_tool")
                if unbounded[key] is not None:
                    self.assertEqual(_options(_subcommand(parser, key[1:])), unbounded[key],
                                     f"`{' '.join(key)}` gained an option: if it opens a path, give the prefix "
                                     "an _OptionGrammar in evidence_tool before shipping it")


if __name__ == "__main__":
    unittest.main()
