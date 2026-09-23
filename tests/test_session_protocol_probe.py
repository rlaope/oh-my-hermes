"""A help page that outgrows the probe budget must not switch the lane off.

`negotiate_session_capability` reads a CLI's `--help` to see whether the
structured-session flags exist. The read was capped at the same 16 KiB every
other child capture uses, and a truncated read was treated as an unanswerable
probe -- so when `claude --help` grew past the cap (21,401 bytes observed
2026-09-11, with `--verbose` at byte 17,991), the negotiation returned no
protocol, the dispatch spawned without `--output-format stream-json`, and the
unit produced no token counts and no session id for the rest of its life. The
only trace was an empty token column, which reads like a unit that spent
nothing rather than like a capability that was never negotiated.

These pin the three parts of the repair: the budget is document-sized, a
truncated read still answers the question when every flag was found in what
WAS read, and an absent protocol states why.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()

from omh.coding.executor_readiness import negotiate_session_capability
from omh.coding.fanout_executor_sessions import (
    SESSION_HELP_PROBE_BYTES,
    bounded_session_probe,
)
from omh.coding._hermes_child_process import MAX_CAPTURE_BYTES


class HelpProbeBudgetTests(unittest.TestCase):
    def test_the_help_budget_clears_a_help_page_that_outgrew_the_shared_cap(self) -> None:
        # 21,401 bytes was the observed page; the budget is not set to clear it
        # by a hair, because the next release grows it again.
        self.assertGreater(SESSION_HELP_PROBE_BYTES, MAX_CAPTURE_BYTES)
        self.assertGreater(SESSION_HELP_PROBE_BYTES, 21_401 * 4)

    def test_a_larger_budget_reads_output_the_default_would_truncate(self) -> None:
        program = 'print("x" * 20000)'
        data, reason = bounded_session_probe([sys.executable, "-c", program])
        self.assertIsNone(data)
        self.assertEqual(reason, "probe_output_limited")
        data, reason = bounded_session_probe(
            [sys.executable, "-c", program], limit_bytes=SESSION_HELP_PROBE_BYTES
        )
        self.assertEqual(reason, "observed")
        # Count the payload, not the bytes: the child's own line ending is
        # platform-native, so a CRLF run is two bytes longer than the same
        # output on POSIX and an exact length would fail only on Windows.
        self.assertEqual((data or b"").count(b"x"), 20_000)

    def test_keep_partial_hands_back_what_was_read_without_calling_it_complete(self) -> None:
        # The reason still says the read was cut off: the caller decides what a
        # prefix can answer, the probe never upgrades it to `observed`.
        data, reason = bounded_session_probe(
            [sys.executable, "-c", 'print("y" * 20000)'], keep_partial=True
        )
        self.assertEqual(reason, "probe_output_limited")
        self.assertEqual(len(data or b""), MAX_CAPTURE_BYTES)

    def test_every_other_caller_still_gets_nothing_from_a_truncated_read(self) -> None:
        data, reason = bounded_session_probe([sys.executable, "-c", 'print("z" * 20000)'])
        self.assertIsNone(data)
        self.assertEqual(reason, "probe_output_limited")


def _fake_cli_wrapper(directory: Path, version: str, help_text: str) -> str:
    """An executable that answers `--version` and `--help` like a real CLI.

    The negotiation runs the path it is given as a program, so the fixture has
    to be one on both platforms: a POSIX shell script will not execute on
    Windows, and a `.cmd` will not on POSIX. Both wrappers call the same
    Python file, and the two answers live in their own files so no quoting
    rule of either shell can touch them.
    """
    (directory / "version.txt").write_text(version, encoding="utf-8")
    (directory / "help.txt").write_text(help_text, encoding="utf-8")
    program = directory / "fake_cli.py"
    program.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "here = Path(__file__).resolve().parent\n"
        "name = 'version.txt' if '--version' in sys.argv else 'help.txt'\n"
        "sys.stdout.write((here / name).read_text(encoding='utf-8'))\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = directory / "fake-cli.cmd"
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "{program}" %*\r\n', encoding="utf-8"
        )
        return str(wrapper)
    wrapper = directory / "fake-cli"
    wrapper.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{program}" "$@"\n', encoding="utf-8"
    )
    wrapper.chmod(0o755)
    return str(wrapper)


class NegotiationOutcomeTests(unittest.TestCase):
    def _negotiate(self, version: str, help_text: str):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        return negotiate_session_capability(
            "claude-code", _fake_cli_wrapper(directory, version, help_text), env=os.environ
        )

    def test_a_help_page_past_the_old_cap_still_negotiates_the_protocol(self) -> None:
        flags = "--output-format stream-json --resume"
        # `--verbose` past 16 KiB is the exact shape that switched the lane off.
        help_text = flags + "\n" + ("filler line\n" * 2_000) + "--verbose\n"
        self.assertGreater(help_text.find("--verbose"), MAX_CAPTURE_BYTES)
        capability = self._negotiate("2.1.268 (Claude Code)", help_text)
        self.assertEqual(capability.protocol, "claude_stream_json")
        self.assertEqual(capability.reason, "")

    def test_a_genuinely_absent_flag_refuses_and_names_itself(self) -> None:
        capability = self._negotiate(
            "2.1.268 (Claude Code)", "--output-format stream-json --resume\n"
        )
        self.assertIsNone(capability.protocol)
        self.assertIn("flags_absent", capability.reason)
        self.assertIn("--verbose", capability.reason)
        self.assertIn("help_complete", capability.reason)

    def test_an_unrecognized_version_refuses_and_says_so(self) -> None:
        capability = self._negotiate(
            "not-a-version", "--output-format stream-json --verbose --resume\n"
        )
        self.assertIsNone(capability.protocol)
        self.assertEqual(capability.reason, "version_output_unrecognized")

    def test_windows_launcher_closure_is_bounded_to_the_selected_package(self) -> None:
        from omh.coding.executor_readiness import _copy_windows_launcher_closure

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        selected = directory / "node_modules" / "@scope" / "tool"
        platform_package = directory / "node_modules" / "@scope" / "tool-win32-x64"
        unrelated = directory / "node_modules" / "unrelated"
        for package in (selected, platform_package, unrelated):
            package.mkdir(parents=True)
            (package / "payload").write_text(package.name, encoding="utf-8")
        launcher = directory / "tool.cmd"
        launcher.write_text(
            '@echo off\r\nnode "%~dp0\\node_modules\\@scope\\tool\\bin\\tool.js"\r\n',
            encoding="utf-8",
        )
        mirror = directory / "mirror"
        mirror.mkdir()

        _copy_windows_launcher_closure(launcher, mirror)

        self.assertTrue((mirror / "node_modules" / "@scope" / "tool" / "payload").is_file())
        self.assertTrue(
            (mirror / "node_modules" / "@scope" / "tool-win32-x64" / "payload").is_file()
        )
        self.assertFalse((mirror / "node_modules" / "unrelated").exists())

    @unittest.skipUnless(os.name == "nt", "Windows command-wrapper behavior")
    def test_pinned_command_wrapper_keeps_adjacent_support_files(self) -> None:
        from omh.coding.executor_readiness import observe_session_binary
        from omh.coding.fanout_dispatch import signal_safe_unit_runner

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        wrapper = _fake_cli_wrapper(directory, "2.1.268", "--help")
        identity = observe_session_binary(wrapper, env=os.environ)
        self.assertIsNotNone(identity)
        assert identity is not None

        completed = signal_safe_unit_runner(
            (wrapper, "--version"),
            env=os.environ,
            text=True,
            capture_output=True,
            expected_binary_identity=identity,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "2.1.268")

    @unittest.skipUnless(os.name == "nt", "Windows npm command-wrapper behavior")
    def test_pinned_npm_wrapper_keeps_adjacent_node_modules(self) -> None:
        from omh.coding.executor_readiness import observe_session_binary
        from omh.coding.fanout_dispatch import signal_safe_unit_runner

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        program = directory / "node_modules" / "package" / "bin" / "cli.py"
        program.parent.mkdir(parents=True)
        program.write_text("print('npm-layout')\n", encoding="utf-8")
        wrapper = directory / "fake-cli.cmd"
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "%~dp0\\node_modules\\package\\bin\\cli.py"\r\n',
            encoding="utf-8",
        )
        identity = observe_session_binary(str(wrapper), env=os.environ)
        self.assertIsNotNone(identity)
        assert identity is not None

        completed = signal_safe_unit_runner(
            (str(wrapper),),
            env=os.environ,
            text=True,
            capture_output=True,
            expected_binary_identity=identity,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "npm-layout")


if __name__ == "__main__":
    unittest.main()
