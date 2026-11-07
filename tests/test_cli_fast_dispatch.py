"""`omh <subcommand>` builds only that subcommand's parser, and reads argv exactly as the full parser does.

`omh.commands.fast_dispatch` maps each subcommand to the module that registers
it. These tests hold that map to `build_parser()`: the same names, each
building the same subparser, and the fast path landing on the same handler with
the same parsed values, so a new subcommand added to `build_parser()` without a
row here fails the first test rather than quietly taking the slow path.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import unittest

from _local_package import load_local_package

load_local_package()

from omh.commands.bare_launch import add_top_level_options  # noqa: E402
from omh.commands.fast_dispatch import SUBCOMMAND_REGISTRARS, build_fast_parser, registrar_for  # noqa: E402
from omh.commands.main import build_parser  # noqa: E402

# `status` is an alias `build_parser()` defines inline (it reuses `cmd_hud`); it
# has no registrar of its own and keeps taking the full parser.
INLINE_SUBCOMMANDS = frozenset({"status"})


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


def _shape(parser: argparse.ArgumentParser) -> list[object]:
    """What a parser accepts: every option's strings, dest, nargs, choices, default and help, recursively."""
    shape: list[object] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            shape.append(("sub", action.dest, {name: _shape(sub) for name, sub in action.choices.items()}))
        else:
            shape.append((tuple(action.option_strings), action.dest, action.nargs, action.choices, repr(action.default),
                          action.help, type(action).__name__))
    return shape


class FastDispatchTableTests(unittest.TestCase):
    def test_every_subcommand_has_a_registrar(self) -> None:
        full = set(_subparsers(build_parser()))
        self.assertEqual(full - set(SUBCOMMAND_REGISTRARS), set(INLINE_SUBCOMMANDS))
        self.assertEqual(set(SUBCOMMAND_REGISTRARS) - full, set())

    def test_each_registrar_builds_the_same_subparser(self) -> None:
        full = _subparsers(build_parser())
        for name in sorted(SUBCOMMAND_REGISTRARS):
            with self.subTest(subcommand=name):
                fast = _subparsers(build_fast_parser(registrar_for([name])))
                self.assertEqual(_shape(fast[name]), _shape(full[name]))

    def test_the_top_level_options_match(self) -> None:
        reference = argparse.ArgumentParser(prog="omh")
        add_top_level_options(reference)
        full = [a for a in _shape(build_parser()) if not (isinstance(a, tuple) and a[0] == "sub")]
        fast = [a for a in _shape(build_fast_parser(registrar_for(["hud"]))) if not (isinstance(a, tuple) and a[0] == "sub")]
        self.assertEqual(fast, full)
        self.assertEqual(fast, [a for a in _shape(reference)])

    def test_the_same_argv_parses_to_the_same_namespace(self) -> None:
        cases = [
            ["hud", "--limit", "5", "--preset", "full"],
            ["runtime", "status"],
            ["memory", "status"],
            ["hud", "--json"],
            ["chat", "route", "review this PR"],
            ["doctor"],
            ["update-check", "status"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                full = vars(build_parser().parse_args(argv))
                fast = vars(build_fast_parser(registrar_for(argv)).parse_args(argv))
                self.assertEqual(fast, full)

    def test_only_a_leading_exact_subcommand_takes_the_fast_path(self) -> None:
        for argv in ([], ["--help"], ["--version"], ["--pretty", "hud"], ["hu"], ["status"], ["nope"]):
            with self.subTest(argv=argv):
                self.assertIsNone(registrar_for(argv))
        self.assertIsNotNone(registrar_for(["hud"]))


class FastDispatchImportTests(unittest.TestCase):
    def test_a_subcommand_does_not_import_the_full_command_tree(self) -> None:
        probe = (
            "import sys, contextlib, io\nfrom omh.cli import main\nbuf = io.StringIO()\n"
            "with contextlib.redirect_stdout(buf):\n    try:\n        main(['update-check', '--help'])\n"
            "    except SystemExit as exit_:\n        code = exit_.code\n"
            "print('command tree imported:', 'omh.commands.main' in sys.modules); sys.exit(code)"
        )
        done = subprocess.run(
            [sys.executable, "-P", "-c", probe], capture_output=True, text=True, timeout=120,
            env={**os.environ, "OMH_HOME": os.devnull},
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("command tree imported: False", done.stdout)

    def test_help_and_errors_print_what_the_full_parser_prints(self) -> None:
        full = "import sys; from omh.commands.main import main; sys.exit(main(sys.argv[1:]))"
        fast = "import sys; from omh.cli import main; sys.exit(main(sys.argv[1:]))"
        env = {**os.environ, "COLUMNS": "100", "NO_COLOR": "1"}
        for argv in (["hud", "--help"], ["runtime", "--help"], ["runtime", "nope"], ["hud", "--limit", "x"]):
            with self.subTest(argv=argv):
                a = subprocess.run([sys.executable, "-c", full, *argv], capture_output=True, text=True, timeout=120, env=env)
                b = subprocess.run([sys.executable, "-c", fast, *argv], capture_output=True, text=True, timeout=120, env=env)
                self.assertEqual((b.returncode, b.stdout, b.stderr), (a.returncode, a.stdout, a.stderr))


if __name__ == "__main__":
    unittest.main()
