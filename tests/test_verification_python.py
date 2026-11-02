"""Fanout capped-field fixtures must not depend on the checkout path length."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

import _verification_python  # noqa: E402
from _verification_python import SHORT_INTERPRETER_CHARS, verification_python_path  # noqa: E402

from omh.coding.fanout_contracts import MAX_UNIT_VERIFICATION_COMMAND_CHARS  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_LONG_EXECUTABLE = "/" + "a-very-long-checkout-directory/" * 8 + ".venv/bin/python3"


def _can_symlink(directory: str) -> bool:
    if os.name != "posix":
        return False
    probe = Path(directory) / "probe"
    try:
        probe.symlink_to(sys.executable)
    except OSError:
        return False
    return True


class VerificationPythonTests(unittest.TestCase):
    def test_long_checkout_path_gets_a_short_interpreter_where_one_can_exist(self) -> None:
        self.assertGreater(len(_LONG_EXECUTABLE), MAX_UNIT_VERIFICATION_COMMAND_CHARS)
        parent = "/tmp" if os.name == "posix" and os.path.isdir("/tmp") else None
        with TemporaryDirectory(dir=parent) as root:
            can_link = parent is not None and _can_symlink(root)
            with (
                mock.patch.object(sys, "executable", _LONG_EXECUTABLE),
                mock.patch.object(sys, "_base_executable", "", create=True),
                mock.patch.object(_verification_python, "_LINK_ROOT", root),
            ):
                path = verification_python_path()
            if can_link:
                self.assertLessEqual(len(path), SHORT_INTERPRETER_CHARS)
                self.assertTrue(path.startswith(root))
            else:
                # No short spelling exists here (Windows has no unprivileged symlink): the real path.
                self.assertEqual(path, _LONG_EXECUTABLE)

    def test_short_interpreter_still_runs_python(self) -> None:
        result = subprocess.run(
            [verification_python_path(), "-c", "import sys; sys.exit(0)"], check=False
        )
        self.assertEqual(result.returncode, 0)

    def test_widest_fixture_body_fits_the_cap_with_the_short_interpreter(self) -> None:
        widest_body = " -c 'import os,sys; sys.exit(0 if os.environ.get(\"VERIFY_TOKEN\") and not os.environ.get(\"CODEX_TOKEN\") else 1)'"
        self.assertLess(SHORT_INTERPRETER_CHARS + 2 + len(widest_body), MAX_UNIT_VERIFICATION_COMMAND_CHARS)


class CappedFieldFixtureGateTests(unittest.TestCase):
    """A test that builds fanout units must not spell the checkout-dependent interpreter into a capped field."""

    _BUILDS_UNITS = re.compile(r"build_fanout_contract|verification_commands|reproduction_command|task_linked_test_runner")
    _SPELLS_EXECUTABLE = re.compile(r"shlex\.quote\(sys\.executable\)")

    def test_no_fanout_fixture_quotes_sys_executable(self) -> None:
        offenders = []
        for path in sorted(_TESTS.glob("test_*.py")):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            if self._BUILDS_UNITS.search(text) and self._SPELLS_EXECUTABLE.search(text):
                offenders.append(path.name)
        self.assertEqual(
            offenders, [],
            "use _verification_python.verification_python() in fanout fixtures: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
