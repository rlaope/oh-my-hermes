"""Native-Windows Codex handoffs (#2471): child environment, sandbox backend, shim resolution."""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout_environment import resolve_child_environment  # noqa: E402

_WINDOWS_PARENT = {
    "PATH": r"C:\Windows\System32",
    "SYSTEMDRIVE": "C:",
    "SYSTEMROOT": r"C:\Windows",
    "WINDIR": r"C:\Windows",
    "USERPROFILE": r"C:\Users\operator",
    "GITHUB_TOKEN": "must-not-leave-parent",
}


class CodexChildEnvironmentTests(unittest.TestCase):
    def test_a_codex_owner_child_keeps_systemdrive(self) -> None:
        # MXC refuses every shell call without it:
        # "MXC requires nonempty Unicode host SystemDrive".
        decision = resolve_child_environment(_WINDOWS_PARENT, owner="codex", purpose="owner")

        self.assertEqual(decision.environment["SYSTEMDRIVE"], "C:")
        self.assertIn("SYSTEMDRIVE", decision.receipt["passed"])
        self.assertNotIn("SYSTEMDRIVE", decision.receipt["removed"])
        self.assertNotIn("GITHUB_TOKEN", decision.environment)

    def test_a_verification_child_keeps_systemdrive_too(self) -> None:
        decision = resolve_child_environment(_WINDOWS_PARENT, owner="codex", purpose="verification")

        self.assertEqual(decision.environment["SYSTEMDRIVE"], "C:")


if __name__ == "__main__":
    unittest.main()
