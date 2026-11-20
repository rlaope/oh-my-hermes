"""`omh doctor`'s `omh_tui_support` check: can bare `omh` open the OMH TUI here?"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.maintenance.doctor import _omh_tui_check
from omh.paths import OmhPaths
from omh.system.hermes_install import installed_hermes_commit
from omh.tui.gateway_contract import DECLARED_AGAINST_HERMES

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")


def _git(install: Path, head: str, *, loose: dict[str, str] | None = None, packed: str = "") -> None:
    git_dir = install / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(head + "\n", encoding="utf-8")
    for name, commit in (loose or {}).items():
        (git_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (git_dir / name).write_text(commit + "\n", encoding="utf-8")
    if packed:
        (git_dir / "packed-refs").write_text(packed, encoding="utf-8")


def _hermes_install(root: Path, *, hook: bool = True, gateway: bool = True) -> None:
    install = root / "hermes" / "hermes-agent"
    (install / "hermes_cli").mkdir(parents=True)
    launcher = 'ext_dir = os.environ.get("HERMES_TUI_DIR")\n' if hook else "def _launch_tui(): pass\n"
    (install / "hermes_cli" / "main_tui_launch.py").write_text(launcher, encoding="utf-8")
    if gateway:
        (install / "tui_gateway").mkdir()
        (install / "tui_gateway" / "entry.py").write_text("", encoding="utf-8")


class OmhTuiDoctorTests(unittest.TestCase):
    def test_all_parts_present_reports_the_omh_tui_reachable(self) -> None:
        with TemporaryDirectory() as tmp, patch("omh.tui.launch.node_available", return_value=True):
            _hermes_install(Path(tmp))
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertTrue(check.ok)
        self.assertEqual(check.severity, "ok")
        self.assertIn("can open the OMH TUI", check.message)

    def test_a_hermes_without_the_launcher_hook_warns_and_names_the_fallback(self) -> None:
        with TemporaryDirectory() as tmp, patch("omh.tui.launch.node_available", return_value=True):
            _hermes_install(Path(tmp), hook=False)
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertTrue(check.ok)
        self.assertEqual(check.severity, "warning")
        self.assertIn("HERMES_TUI_DIR", check.message)
        self.assertIn("Hermes' own terminal", check.next_action)

    def test_a_hermes_without_the_gateway_warns(self) -> None:
        with TemporaryDirectory() as tmp, patch("omh.tui.launch.node_available", return_value=True):
            _hermes_install(Path(tmp), gateway=False)
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertEqual(check.severity, "warning")

    def test_no_node_warns(self) -> None:
        with TemporaryDirectory() as tmp, patch("omh.tui.launch.node_available", return_value=False):
            _hermes_install(Path(tmp))
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertEqual(check.severity, "warning")
        self.assertIn("Node", check.message)

    def test_a_missing_hermes_install_is_not_observed(self) -> None:
        with TemporaryDirectory() as tmp:
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertTrue(check.ok)
        self.assertFalse(check.observed)

    def test_the_message_names_the_installed_commit_next_to_the_declared_one(self) -> None:
        with TemporaryDirectory() as tmp, patch("omh.tui.launch.node_available", return_value=True):
            _hermes_install(Path(tmp))
            _git(Path(tmp) / "hermes" / "hermes-agent", "ref: refs/heads/main", loose={"refs/heads/main": COMMIT})
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertEqual(check.severity, "ok")
        self.assertIn(f"(Hermes commit 0123456789; the OMH TUI was declared against {DECLARED_AGAINST_HERMES})", check.message)

    def test_an_unreadable_commit_is_unknown_and_moves_nothing(self) -> None:
        for node in (True, False):
            with self.subTest(node=node), TemporaryDirectory() as tmp, patch("omh.tui.launch.node_available", return_value=node):
                _hermes_install(Path(tmp))
                check = _omh_tui_check(_paths(Path(tmp)))
            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "ok" if node else "warning")
            self.assertIn("Hermes commit unknown", check.message)

    def test_a_missing_shim_warns_before_anything_else(self) -> None:
        with TemporaryDirectory() as tmp, patch("omh.tui.launch.FRONTEND_ENTRY", Path(tmp) / "missing.js"):
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertEqual(check.severity, "warning")
        self.assertIn("shim", check.message)


class InstalledHermesCommitTests(unittest.TestCase):
    """The commit is read from the checkout's `.git` files; nothing runs git."""

    def commit(self, head: str | None, **refs: object) -> str:
        with TemporaryDirectory() as tmp:
            if head is not None:
                _git(Path(tmp), head, **refs)  # type: ignore[arg-type]
            return installed_hermes_commit(Path(tmp))

    def test_a_detached_head_names_the_commit(self) -> None:
        self.assertEqual(self.commit(COMMIT), COMMIT)

    def test_a_branch_reads_its_loose_ref_before_packed_refs(self) -> None:
        packed = f"# pack-refs with: peeled fully-peeled sorted \n{'f' * 40} refs/heads/main\n"
        self.assertEqual(self.commit("ref: refs/heads/main", loose={"refs/heads/main": COMMIT}, packed=packed), COMMIT)

    def test_a_branch_without_a_loose_ref_reads_packed_refs(self) -> None:
        packed = f"# pack-refs with: peeled fully-peeled sorted \n{'f' * 40} refs/heads/other\n{COMMIT} refs/heads/main\n"
        self.assertEqual(self.commit("ref: refs/heads/main", packed=packed), COMMIT)

    def test_anything_else_is_empty(self) -> None:
        cases = {
            "no .git": (None, {}),
            "a ref in neither place": ("ref: refs/heads/main", {}),
            # `.git/refs` exists, so the path resolves to the file beside `.git` unless the name is refused.
            "a ref that climbs out of refs": (
                "ref: refs/../../outside", {"loose": {"refs/heads/main": "f" * 40, "../outside": COMMIT}},
            ),
            "a short commit": (COMMIT[:12], {}),
            "garbage": ("not a ref", {}),
        }
        for label, (head, refs) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.commit(head, **refs), "")

    def test_a_git_file_pointing_elsewhere_is_not_followed(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
            self.assertEqual(installed_hermes_commit(Path(tmp)), "")


@unittest.skipUnless(os.name == "nt", "the Windows path is only reachable on Windows")
class OmhTuiDoctorWindowsTests(unittest.TestCase):
    def test_windows_reports_the_real_state_not_a_fixed_termios_line(self) -> None:
        # The OMH TUI runs on a Windows console with virtual terminal input (Windows Terminal), so the check walks
        # the same steps as on POSIX: here no Hermes install, so it says so.
        with TemporaryDirectory() as tmp:
            check = _omh_tui_check(_paths(Path(tmp)))
        self.assertTrue(check.ok)
        self.assertNotIn("termios", check.message)


if __name__ == "__main__":
    unittest.main()
