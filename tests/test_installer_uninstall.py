"""`install.sh --uninstall [--purge] [--dry-run]`: the one-liner removes OMH.

The installer only finds the installed `omh` command (PATH first, then where it
puts the command itself) and runs `omh uninstall`; `omh uninstall` owns every
removal rule. An uninstall run never downloads or installs anything, so the
stub `curl` and the stub interpreter log every call and the tests assert none.
Everything runs against a temporary HOME with stub commands on a private PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "install.sh"

SYSTEM_TOOLS = (
    "sh", "bash", "awk", "sed", "grep", "tr", "tail", "head", "dirname", "readlink",
    "ln", "mkdir", "cp", "chmod", "rm", "mktemp", "cat", "mv", "printf",
)

# Logs its arguments, prints a marker line, exits with FAKE_OMH_STATUS.
STUB_OMH = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/omh-argv"
printf 'stub omh %s: %s\\n' "$STUB_NAME" "$*"
exit "${FAKE_OMH_STATUS:-0}"
"""

STUB_CURL = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/curl"
exit 22
"""

# Any interpreter call means the installer went down its install path.
STUB_PYTHON = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/python"
case "$*" in
  *"import sys; print"*) echo "3.12"; exit 0 ;;
esac
case "$2" in
  venv) mkdir -p "$3/bin"; cp "$0" "$3/bin/python"; exit 0 ;;
esac
exit 0
"""


@unittest.skipIf(sys.platform == "win32", "install.sh is the POSIX installer; install.ps1 covers Windows")
class InstallerUninstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "log"
        self.log.mkdir()
        (self.root / "tmp").mkdir()
        tools = self.root / "tools"
        tools.mkdir()
        for name in SYSTEM_TOOLS:
            found = shutil.which(name, path="/usr/bin:/bin")
            if found is not None:
                (tools / name).symlink_to(found)
        self.tools = tools
        self._write(self.bin / "curl", STUB_CURL)
        self._write(self.bin / "python3", STUB_PYTHON)
        self._write(self.bin / "python3.12", STUB_PYTHON)

    @staticmethod
    def _write(path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _stub_omh(self, path: Path, name: str) -> Path:
        self._write(path, STUB_OMH.replace('"$STUB_NAME"', f"'{name}'"))
        return path

    def _run(self, *args: str, path_dirs: tuple[Path, ...] = (), **environment: str) -> subprocess.CompletedProcess[str]:
        path = ":".join([*(str(d) for d in path_dirs), str(self.bin), str(self.tools)])
        env = {
            "HOME": str(self.home),
            "PATH": path,
            "TMPDIR": str(self.root / "tmp"),
            "FAKE_LOG": str(self.log),
            "NO_COLOR": "1",
            **environment,
        }
        return subprocess.run(
            ["sh", str(INSTALLER), *args], env=env, capture_output=True, text=True, timeout=120, check=False,
        )

    def _calls(self, name: str) -> list[str]:
        path = self.log / name
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def _home_files(self) -> list[str]:
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))

    def _assert_nothing_installed(self) -> None:
        self.assertEqual(self._calls("curl"), [])
        self.assertEqual(self._calls("python"), [])

    # -- where the command is found -------------------------------------------------------------

    def test_the_command_on_path_runs_omh_uninstall(self) -> None:
        on_path = self.root / "pathbin"
        self._stub_omh(on_path / "omh", "path")
        result = self._run("--uninstall", path_dirs=(on_path,))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "stub omh path: uninstall\n")
        self.assertEqual(self._calls("omh-argv"), ["uninstall"])
        self._assert_nothing_installed()

    def test_the_command_only_in_the_installer_bin_dir_is_found_without_path(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        result = self._run("--uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "stub omh bin: uninstall\n")
        self._assert_nothing_installed()

    def test_omh_bin_dir_moves_the_place_it_looks(self) -> None:
        elsewhere = self.root / "elsewhere"
        self._stub_omh(elsewhere / "omh", "custom-bin")
        result = self._run("--uninstall", OMH_BIN_DIR=str(elsewhere))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stub omh custom-bin", result.stdout)

    def test_the_command_only_in_the_venv_is_found_without_path(self) -> None:
        self._stub_omh(self.home / ".local" / "share" / "omh" / "venv" / "bin" / "omh", "venv")
        result = self._run("--uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "stub omh venv: uninstall\n")
        self._assert_nothing_installed()

    def test_the_current_generation_venv_is_found_without_path(self) -> None:
        self._stub_omh(self.home / ".local" / "share" / "omh" / "current" / "venv" / "bin" / "omh", "current")
        result = self._run("--uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "stub omh current: uninstall\n")
        self._assert_nothing_installed()

    def test_xdg_data_home_moves_the_managed_root(self) -> None:
        xdg = self.root / "xdg"
        self._stub_omh(xdg / "omh" / "current" / "venv" / "bin" / "omh", "xdg")
        result = self._run("--uninstall", XDG_DATA_HOME=str(xdg))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stub omh xdg", result.stdout)

    # -- the arguments handed on ----------------------------------------------------------------

    def test_purge_maps_to_all(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        result = self._run("--uninstall", "--purge")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._calls("omh-argv"), ["uninstall --all"])

    def test_dry_run_passes_through_and_creates_nothing(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        before = self._home_files()
        result = self._run("--uninstall", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._calls("omh-argv"), ["uninstall --dry-run"])
        self.assertEqual(self._home_files(), before)
        self._assert_nothing_installed()

    def test_purge_and_dry_run_together_in_either_order(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        for args in (("--uninstall", "--purge", "--dry-run"), ("--dry-run", "--purge", "--uninstall")):
            (self.log / "omh-argv").unlink(missing_ok=True)
            result = self._run(*args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self._calls("omh-argv"), ["uninstall --all --dry-run"])

    def test_language_is_passed_only_when_it_was_set(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        self.assertEqual(self._run("--uninstall").returncode, 0)
        self.assertEqual(self._calls("omh-argv"), ["uninstall"])
        (self.log / "omh-argv").unlink()
        self.assertEqual(self._run("--uninstall", OMH_LANG="ko").returncode, 0)
        self.assertEqual(self._calls("omh-argv"), ["uninstall --language ko"])

    def test_force_is_never_passed(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        self._run("--uninstall", "--purge", "--dry-run", OMH_LANG="en")
        self.assertNotIn("--force", "".join(self._calls("omh-argv")))

    def test_the_stubs_nonzero_exit_is_the_scripts_exit(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        result = self._run("--uninstall", FAKE_OMH_STATUS="3")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "stub omh bin: uninstall\n")
        self._assert_nothing_installed()

    # -- nothing found --------------------------------------------------------------------------

    def test_not_found_is_nonzero_says_where_it_looked_and_downloads_nothing(self) -> None:
        before = self._home_files()
        result = self._run("--uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("no installed omh command was found", result.stderr)
        self.assertIn(str(self.home / ".local" / "bin" / "omh"), result.stderr)
        self.assertIn(str(self.home / ".local" / "share" / "omh" / "current" / "venv" / "bin" / "omh"), result.stderr)
        self.assertIn(str(self.home / ".local" / "share" / "omh" / "venv" / "bin" / "omh"), result.stderr)
        self.assertIn("OMH home", result.stderr)
        self.assertIn("Hermes registration", result.stderr)
        self.assertIn("docs/INSTALLATION.md#uninstall", result.stderr)
        self.assertEqual(self._home_files(), before)
        self._assert_nothing_installed()

    def test_not_found_with_purge_and_dry_run_still_installs_nothing(self) -> None:
        result = self._run("--uninstall", "--purge", "--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._home_files(), [])
        self._assert_nothing_installed()

    def test_not_found_is_localized(self) -> None:
        result = self._run("--uninstall", OMH_LANG="ko")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("omh 명령어를 찾지 못해", result.stderr)

    def test_a_non_executable_file_is_not_the_command(self) -> None:
        path = self.home / ".local" / "bin" / "omh"
        path.parent.mkdir(parents=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        result = self._run("--uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no installed omh command was found", result.stderr)

    # -- refused combinations -------------------------------------------------------------------

    def test_every_refused_combination_exits_2_and_writes_nothing(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        before = self._home_files()
        cases = (
            ("--purge",),
            ("--dry-run",),
            ("--purge", "--dry-run"),
            ("--uninstall", "omher@beta"),
            ("omher@beta", "--uninstall"),
            ("--uninstall", "--force"),
            ("--uninstall", "--all"),
            ("--uninstall", "extra"),
            ("--unknown",),
        )
        for args in cases:
            with self.subTest(args=args):
                result = self._run(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("omh installer:", result.stderr)
                self.assertIn("--uninstall [--purge] [--dry-run]", result.stderr)
                self.assertIn("omher@beta", result.stderr)
                self.assertEqual(self._calls("omh-argv"), [])
                self._assert_nothing_installed()
                self.assertEqual(self._home_files(), before)

    def test_the_unknown_argument_message_names_the_argument(self) -> None:
        result = self._run("--unknown")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument '--unknown'", result.stderr)

    # -- the install path is untouched ----------------------------------------------------------

    def test_no_argument_still_reaches_the_install_path(self) -> None:
        self._stub_omh(self.home / ".local" / "bin" / "omh", "bin")
        result = self._run(OMH_PACKAGE_URL=str(self.root / "pkg.whl"), OMH_LINK_COMMAND="0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OMH installer", result.stdout)
        self.assertTrue(self._calls("python"), "the install path never ran an interpreter")
        self.assertEqual(self._calls("omh-argv"), [])


if __name__ == "__main__":
    unittest.main()
