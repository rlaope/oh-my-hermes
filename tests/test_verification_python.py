"""Fanout verification fixtures must not depend on the checkout path length."""

from __future__ import annotations

import subprocess
import sys
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _verification_python import SHORT_INTERPRETER_CHARS, verification_python  # noqa: E402

from omh.coding.fanout_contracts import MAX_UNIT_VERIFICATION_COMMAND_CHARS  # noqa: E402


class VerificationPythonTests(unittest.TestCase):
    def test_interpreter_is_short_when_the_checkout_path_is_long(self) -> None:
        long_executable = "/" + "a-very-long-checkout-directory/" * 8 + ".venv/bin/python3"
        self.assertGreater(len(long_executable), MAX_UNIT_VERIFICATION_COMMAND_CHARS)
        with mock.patch.object(sys, "executable", long_executable):
            interpreter = verification_python()
        self.assertLessEqual(len(interpreter), SHORT_INTERPRETER_CHARS + 2)

    def test_short_interpreter_still_runs_python(self) -> None:
        result = subprocess.run(
            f"{verification_python()} -c 'import sys; sys.exit(0)'", shell=True, check=False
        )
        self.assertEqual(result.returncode, 0)

    def test_widest_fixture_body_fits_the_cap_with_the_short_interpreter(self) -> None:
        widest_body = " -c 'import os,sys; sys.exit(0 if os.environ.get(\"VERIFY_TOKEN\") and not os.environ.get(\"CODEX_TOKEN\") else 1)'"
        self.assertLess(SHORT_INTERPRETER_CHARS + 2 + len(widest_body), MAX_UNIT_VERIFICATION_COMMAND_CHARS)


if __name__ == "__main__":
    unittest.main()
