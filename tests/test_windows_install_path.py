"""Contract gates for the native Windows install path (issue #848).

The Windows installer can only be *executed* on the `windows-latest` CI job, so
these tests cover what is checkable from any host: that `install.ps1` exists,
that it stays byte-compatible with the encoding rule Windows PowerShell 5.1
imposes, and above all that it does not drift away from `install.sh`.

The drift gates derive the expected surface from `install.sh` source rather than
restating it, so adding an option to one installer and forgetting the other
fails here instead of on a user's machine.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

def _as_windows() -> object:
    """Force the Windows branches of omh.paths on any host.

    `os.name` itself cannot be patched: `pathlib` reads it to choose a flavour
    and raises `NotImplementedError` when the two disagree.
    """
    # The defining module, not the `omh.paths` re-export shim: the functions
    # under test resolve `_is_windows` in their own module globals.
    from omh.system import paths

    return patch.object(paths, "_is_windows", lambda: True)


def _as_posix() -> object:
    from omh.system import paths

    return patch.object(paths, "_is_windows", lambda: False)


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"

# The one option install.ps1 adds. POSIX shells conventionally already carry
# ~/.local/bin on PATH, so install.sh only prints a hint; Windows has no
# equivalent convention, so the installer has to offer to extend PATH.
WINDOWS_ONLY_ENV_VARS = {"OMH_ADD_TO_PATH"}


def _shell_env_contract(source: str) -> set[str]:
    """The OMH_* variables install.sh reads as input, from its own source.

    Matches `${OMH_X:-default}` and `${OMH_X+x}` only, which is exactly the
    read-an-input form; install.sh's internal `OMH_*` locals never appear that
    way, so they stay out of the contract.
    """
    return set(re.findall(r"\$\{(OMH_[A-Z0-9_]+)(?::-|\+x)", source))


class WindowsInstallerPresenceTests(unittest.TestCase):
    def test_native_windows_installer_exists_next_to_the_posix_one(self) -> None:
        self.assertTrue(INSTALL_PS1.is_file(), "install.ps1 is the native Windows install path for issue #848")

    def test_installer_is_pure_ascii_without_a_byte_order_mark(self) -> None:
        raw = INSTALL_PS1.read_bytes()

        # Windows PowerShell 5.1 decodes a BOM-less script as the system ANSI
        # code page, so any non-ASCII byte would render as mojibake on exactly
        # the hosts this file exists to serve. Adding a BOM instead would risk
        # the `irm | iex` path, which is the documented one. Staying ASCII
        # sidesteps both, and is why the installer labels are English.
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "a BOM would ride along into the irm | iex pipeline")
        raw.decode("ascii")  # raises UnicodeDecodeError and fails the test on any non-ASCII byte

    def test_installer_keeps_lf_line_endings_like_every_other_managed_file(self) -> None:
        self.assertNotIn(b"\r\n", INSTALL_PS1.read_bytes())


class WindowsInstallerRedirectResponseTests(unittest.TestCase):
    def test_redirect_headers_and_invocation_guard_are_capability_checked(self) -> None:
        powershell = INSTALL_PS1.read_text(encoding="utf-8")

        # PowerShell 7's HttpResponseHeaders has no indexer, while the other
        # supported response shapes do. The installer must hand both response
        # paths to one accessor that probes what the actual object supports.
        self.assertNotIn("$OmhLatestResponse.Headers['Location']", powershell)
        self.assertNotIn("$OmhLatestError.Headers['Location']", powershell)
        self.assertEqual(powershell.count("Get-OmhRedirectLocation $OmhLatest"), 2)
        self.assertIn("PSObject.Properties['Headers']", powershell)
        self.assertIn("PSObject.Properties['Location']", powershell)

        # `irm | iex` has no MyCommand.Path. StrictMode makes touching that
        # absent property a terminating error, so the exit guard must probe it.
        self.assertNotIn("$MyInvocation.MyCommand.Path", powershell)
        self.assertIn("PSObject.Properties['Path']", powershell)


class WindowsInstallerContractParityTests(unittest.TestCase):
    """install.ps1 must accept the same inputs install.sh does."""

    def setUp(self) -> None:
        self.shell = INSTALL_SH.read_text(encoding="utf-8")
        self.powershell = INSTALL_PS1.read_text(encoding="utf-8")

    def test_every_posix_installer_environment_variable_is_honored_on_windows(self) -> None:
        contract = _shell_env_contract(self.shell)
        self.assertGreater(len(contract), 20, "the extraction, not install.sh, is what broke if this trips")

        missing = sorted(name for name in contract if name not in self.powershell)
        self.assertEqual(
            missing,
            [],
            "install.sh reads these but install.ps1 does not; the two installers are one documented interface",
        )

    def test_windows_installer_adds_only_the_documented_extra_option(self) -> None:
        declared = set(re.findall(r"Get-OmhEnv '(OMH_[A-Z0-9_]+)'", self.powershell))
        declared |= set(re.findall(r"Test-OmhEnvSet '(OMH_[A-Z0-9_]+)'", self.powershell))

        extra = declared - _shell_env_contract(self.shell)
        self.assertEqual(
            extra,
            WINDOWS_ONLY_ENV_VARS,
            "a new install.ps1-only option needs a documented reason and an entry in WINDOWS_ONLY_ENV_VARS",
        )

    def test_setup_is_handed_the_same_flags_by_both_installers(self) -> None:
        # `omh setup` is the contract boundary between installer and product, so
        # a flag only one installer forwards is a silent behavior fork. Both
        # sides are sliced to their setup-argument block and compared as sets.
        shell_block = self.shell.split("set -- setup ", 1)[1].split('say_step "$(step_label "$OMH_SETUP_STEP")"', 1)[0]
        powershell_block = self.powershell.split("$OmhSetupArgv = @('setup'", 1)[1].split(
            "Write-OmhStep (Get-OmhStepLabel $OmhSetupStep)", 1
        )[0]

        shell_flags = set(re.findall(r"--[a-z][a-z-]*", shell_block))
        powershell_flags = set(re.findall(r"--[a-z][a-z-]*", powershell_block))

        self.assertGreater(len(shell_flags), 10, "the slice, not install.sh, is what broke if this trips")
        self.assertEqual(sorted(shell_flags - powershell_flags), [], "install.ps1 does not forward these setup flags")
        self.assertEqual(sorted(powershell_flags - shell_flags), [], "install.ps1 forwards setup flags install.sh does not")

    def test_package_source_resolution_matches(self) -> None:
        for fragment in (
            "/heads/main.zip",
            "/tags/",
            # Stable resolves the slim release wheel; the tag archive stays
            # only as the fallback for a tag that published no asset.
            "releases/download",
            "-py3-none-any.whl",
            "custom-url",
            "preview",
            "stable",
            "local",
        ):
            self.assertIn(fragment, self.powershell, f"channel resolution lost {fragment!r}")

    def test_windows_installer_uses_the_windows_virtualenv_layout(self) -> None:
        # A venv exposes Scripts\python.exe on Windows. Carrying install.sh's
        # bin/python across would produce an installer that always fails.
        self.assertIn(r"Scripts\python.exe", self.powershell)
        self.assertIn(r"Scripts\omh.exe", self.powershell)
        self.assertNotIn("/bin/python", self.powershell)
        self.assertNotIn("/bin/omh", self.powershell)

    def test_windows_installer_does_not_anchor_on_HOME(self) -> None:
        # ntpath.expanduser resolves ~ from USERPROFILE and ignores HOME, so an
        # installer that read HOME would write where `omh update` cannot look.
        self.assertNotIn("Get-OmhEnv 'HOME'", self.powershell)
        self.assertIn("Get-OmhEnv 'USERPROFILE'", self.powershell)

    def test_windows_installer_exposes_a_shim_rather_than_a_symlink(self) -> None:
        # Symlinking on Windows requires Developer Mode or elevation.
        self.assertIn("omh.cmd", self.powershell)
        self.assertNotIn("New-Item -ItemType SymbolicLink", self.powershell)


class WindowsInstallerDocumentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installation = (REPO_ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
        self.agents = (REPO_ROOT / "INSTALL_FOR_AGENTS.md").read_text(encoding="utf-8")
        self.readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    def test_windows_one_liner_is_documented_where_a_windows_user_will_look(self) -> None:
        one_liner = "irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex"
        for name, text in (("docs/INSTALLATION.md", self.installation), ("README.md", self.readme)):
            self.assertIn(one_liner, text, f"{name} does not show the native Windows install command")
        self.assertIn('$env:OMH_SOURCE_REF = $Ref', self.agents)
        self.assertIn(
            'irm "https://raw.githubusercontent.com/rlaope/oh-my-hermes/$Ref/install.ps1" | iex',
            self.agents,
        )
        self.assertNotIn(one_liner, self.agents)

    def test_hermes_home_resolution_on_windows_is_stated_not_implied(self) -> None:
        # The question issue #848 actually asked. `~` differs between native
        # Windows and WSL, and the two stores never merge.
        self.assertIn("%USERPROFILE%", self.installation)
        self.assertIn("WSL", self.installation)

    def test_posix_only_surfaces_are_named_in_the_docs(self) -> None:
        # "A note in the docs on which skills, if any, are POSIX-only" -- the
        # honest answer is that no skill is, but several storage/locking
        # surfaces fail closed, and a Windows user has to be told which.
        lowered = self.installation.lower()
        for surface in ("domain intelligence", "prompt compatibility audit", "o_nofollow", "fcntl"):
            self.assertIn(surface, lowered, f"the capability boundary table lost {surface!r}")


class ManagedCommandResolutionTests(unittest.TestCase):
    """`omh update` / `omh remove` must find what the installers wrote.

    The shim shape only exists on Windows, so these patch `os.name` rather than
    skipping: the branch would otherwise have zero coverage on the ubuntu job
    and be first exercised on a user's machine. What the caller does with a True
    here is delete the file, so every negative case below is load-bearing.
    """

    def _shim(self, directory: Path, target: Path) -> Path:
        shim = directory / "omh.cmd"
        shim.write_text(f'@echo off\r\n"{target}" %*\r\n', encoding="utf-8", newline="")
        return shim

    def test_managed_command_helpers_follow_the_host_convention(self) -> None:
        from omh.paths import managed_command_filenames, managed_command_venv_scripts_dir

        names = managed_command_filenames()
        if os.name == "nt":
            self.assertEqual(names, ("omh.cmd", "omh"))
            self.assertEqual(managed_command_venv_scripts_dir(Path("v")).name, "Scripts")
        else:
            self.assertEqual(names, ("omh",))
            self.assertEqual(managed_command_venv_scripts_dir(Path("v")).name, "bin")

    def test_a_cmd_shim_naming_the_venv_executable_is_recognized(self) -> None:
        from omh.paths import command_entry_belongs_to_venv, managed_command_venv_scripts_dir

        with TemporaryDirectory() as tmp, _as_windows():
            root = Path(tmp)
            venv_dir = root / "venv"
            scripts = managed_command_venv_scripts_dir(venv_dir)
            scripts.mkdir(parents=True)
            shim = self._shim(root, scripts / "omh.exe")

            self.assertTrue(command_entry_belongs_to_venv(shim, venv_dir))

    def test_a_wrapper_that_merely_mentions_the_venv_is_not_ours(self) -> None:
        # A user's own wrapper that puts the venv on PATH and then runs
        # something else names the directory without being installer-managed.
        # Substring-matching the directory would classify it as ours and
        # delete it.
        from omh.paths import command_entry_belongs_to_venv, managed_command_venv_scripts_dir

        with TemporaryDirectory() as tmp, _as_windows():
            root = Path(tmp)
            venv_dir = root / "venv"
            scripts = managed_command_venv_scripts_dir(venv_dir)
            scripts.mkdir(parents=True)
            wrapper = root / "omh.cmd"
            wrapper.write_text(
                f"@echo off\r\nset PATH={scripts};%PATH%\r\npython -m my_tool %*\r\n",
                encoding="utf-8",
                newline="",
            )

            self.assertFalse(command_entry_belongs_to_venv(wrapper, venv_dir))

    def test_a_sibling_venv_shim_is_not_ours(self) -> None:
        from omh.paths import command_entry_belongs_to_venv, managed_command_venv_scripts_dir

        with TemporaryDirectory() as tmp, _as_windows():
            root = Path(tmp)
            (root / "venv").mkdir()
            sibling = managed_command_venv_scripts_dir(root / "venv2")
            sibling.mkdir(parents=True)
            shim = self._shim(root, sibling / "omh.exe")

            self.assertFalse(command_entry_belongs_to_venv(shim, root / "venv"))

    def test_a_venv_whose_name_extends_ours_is_not_ours(self) -> None:
        # The prefix hazard a text match has and a path comparison does not:
        # `<root>/venv_backup` starts with `<root>/venv`, so substring-matching
        # the venv or its Scripts directory would delete a backup install's
        # shim. Component-wise containment cannot make that mistake.
        from omh.paths import command_entry_belongs_to_venv, managed_command_venv_scripts_dir

        with TemporaryDirectory() as tmp, _as_windows():
            root = Path(tmp)
            venv_dir = root / "venv"
            managed_command_venv_scripts_dir(venv_dir).mkdir(parents=True)
            other = managed_command_venv_scripts_dir(root / "venv_backup")
            other.mkdir(parents=True)
            shim = self._shim(root, other / "omh.exe")

            self.assertFalse(command_entry_belongs_to_venv(shim, venv_dir))

    def test_a_shim_under_a_redirected_store_is_still_ours(self) -> None:
        # The installer writes the spelling it was given while the reader
        # resolves; behind a junction or a symlinked profile the two strings
        # differ and a text match would strand the shim. Comparing resolved
        # paths is what keeps `omh remove` able to clean up after itself.
        from omh.paths import command_entry_belongs_to_venv, managed_command_venv_scripts_dir

        with TemporaryDirectory() as tmp, _as_windows():
            root = Path(tmp)
            real = root / "real_local"
            venv_dir = real / "omh" / "venv"
            scripts = managed_command_venv_scripts_dir(venv_dir)
            scripts.mkdir(parents=True)
            link = root / "Local"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("this host does not permit symlink creation")
            # The shim names the path through the link, as the installer would.
            shim = self._shim(root, managed_command_venv_scripts_dir(link / "omh" / "venv") / "omh.exe")

            self.assertTrue(command_entry_belongs_to_venv(shim, venv_dir))

    def test_an_unrelated_cmd_file_is_not_ours(self) -> None:
        from omh.paths import command_entry_belongs_to_venv

        with TemporaryDirectory() as tmp, _as_windows():
            root = Path(tmp)
            venv_dir = root / "venv"
            venv_dir.mkdir()
            foreign = self._shim(root, Path("C:/somewhere/else/omh.exe"))

            self.assertFalse(command_entry_belongs_to_venv(foreign, venv_dir))

    def test_a_plain_executable_is_not_ours(self) -> None:
        from omh.paths import command_entry_belongs_to_venv

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_dir = root / "venv"
            venv_dir.mkdir()
            plain = root / "omh"
            plain.write_text("#!/bin/sh\n", encoding="utf-8")

            self.assertFalse(command_entry_belongs_to_venv(plain, venv_dir))

    def test_the_shim_shape_is_refused_off_windows(self) -> None:
        # POSIX must keep exactly one delete path, the symlink one. Admitting
        # the shim shape there would widen deletion on a platform that never
        # produces it.
        from omh.paths import command_entry_belongs_to_venv, managed_command_venv_scripts_dir

        with TemporaryDirectory() as tmp, _as_posix():
            root = Path(tmp)
            venv_dir = root / "venv"
            scripts = managed_command_venv_scripts_dir(venv_dir)
            scripts.mkdir(parents=True)
            shim = self._shim(root, scripts / "omh.exe")

            self.assertFalse(command_entry_belongs_to_venv(shim, venv_dir))

    @unittest.skipIf(os.name == "nt", "POSIX venv interpreters are symlinks")
    def test_pointer_spelled_posix_generation_python_remains_installer_managed(self) -> None:
        from omh.commands import setup as setup_commands
        from omh.paths import managed_generation_for_executable, managed_workflow_pack_dir

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            generation = root / "generations" / "20260903-live"
            interpreter = generation / "venv" / "bin" / "python"
            interpreter.parent.mkdir(parents=True)
            try:
                interpreter.symlink_to(Path(sys.executable).resolve())
                current = root / "current"
                current.symlink_to(generation, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("this host does not permit symlink creation")

            pointer_interpreter = current / "venv" / "bin" / "python"
            expected_generation = generation.resolve()
            environment = {
                "OMH_VENV_DIR": str(root / "venv"),
                "OMH_SELF_UPDATE_GENERATION": "",
            }
            with (
                patch.dict(os.environ, environment, clear=False),
                patch.object(setup_commands.sys, "executable", str(pointer_interpreter)),
            ):
                self.assertEqual(managed_generation_for_executable(pointer_interpreter), expected_generation)
                self.assertEqual(managed_workflow_pack_dir(), expected_generation / "skills")
                self.assertTrue(setup_commands._managed_command_runtime()["managed"])

            for unrelated in (
                root / "generations-backup" / generation.name / "venv" / "bin" / "python",
                root / "external" / "venv" / "bin" / "python",
            ):
                unrelated.parent.mkdir(parents=True)
                unrelated.symlink_to(Path(sys.executable).resolve())
                with (
                    patch.dict(os.environ, environment, clear=False),
                    patch.object(setup_commands.sys, "executable", str(unrelated)),
                ):
                    self.assertIsNone(managed_generation_for_executable(unrelated), unrelated)
                    self.assertFalse(setup_commands._managed_command_runtime()["managed"])


class ManagedCommandLocationTests(unittest.TestCase):
    """The precedence `managed_command_venv_dir` walks, pinned.

    Untested before, and it broke twice while this branch was in review: once
    because a fixture patched HOME but not USERPROFILE, once because it cleared
    XDG_DATA_HOME but not LOCALAPPDATA. Both were silent -- the resolver simply
    answered with the real user's store.
    """

    def _resolve(self, env: dict[str, str], windows: bool) -> "Path | None":
        from omh.paths import managed_command_venv_dir

        cleared = dict.fromkeys(
            ("OMH_VENV_DIR", "XDG_DATA_HOME", "LOCALAPPDATA", "HOME", "USERPROFILE"), ""
        )
        cleared.update(env)
        flavour = _as_windows() if windows else _as_posix()
        with patch.dict(os.environ, cleared, clear=False), flavour:
            return managed_command_venv_dir()

    def test_an_explicit_venv_dir_outranks_everything(self) -> None:
        for windows in (True, False):
            resolved = self._resolve(
                {"OMH_VENV_DIR": "/explicit", "XDG_DATA_HOME": "/xdg", "LOCALAPPDATA": "/lad", "HOME": "/h"},
                windows,
            )
            self.assertEqual(resolved, Path("/explicit").resolve(), f"windows={windows}")

    def test_xdg_data_home_outranks_localappdata(self) -> None:
        # Honored on Windows too, because an operator who set it meant it.
        resolved = self._resolve({"XDG_DATA_HOME": "/xdg", "LOCALAPPDATA": "/lad"}, windows=True)
        self.assertEqual(resolved, (Path("/xdg") / "omh" / "venv").resolve())

    def test_localappdata_is_the_windows_default_and_is_ignored_off_windows(self) -> None:
        env = {"LOCALAPPDATA": "/lad", "HOME": "/h", "USERPROFILE": "/u"}
        self.assertEqual(self._resolve(env, windows=True), (Path("/lad") / "omh" / "venv").resolve())
        self.assertEqual(
            self._resolve(env, windows=False),
            (Path("/h") / ".local" / "share" / "omh" / "venv").resolve(),
        )

    def test_the_home_fallback_reads_userprofile_on_windows_and_home_elsewhere(self) -> None:
        env = {"HOME": "/h", "USERPROFILE": "/u"}
        self.assertEqual(
            self._resolve(env, windows=True),
            (Path("/u") / ".local" / "share" / "omh" / "venv").resolve(),
        )
        self.assertEqual(
            self._resolve(env, windows=False),
            (Path("/h") / ".local" / "share" / "omh" / "venv").resolve(),
        )

    def test_nothing_to_anchor_on_returns_none_rather_than_guessing(self) -> None:
        for windows in (True, False):
            self.assertIsNone(self._resolve({}, windows), f"windows={windows}")


class InstallerCommandHintTests(unittest.TestCase):
    def test_the_update_hint_names_an_installer_the_host_can_run(self) -> None:
        from omh.commands.setup import POSIX_INSTALLER_COMMAND, WINDOWS_INSTALLER_COMMAND, installer_command

        self.assertIn("install.sh", POSIX_INSTALLER_COMMAND)
        self.assertIn("install.ps1", WINDOWS_INSTALLER_COMMAND)
        expected = WINDOWS_INSTALLER_COMMAND if os.name == "nt" else POSIX_INSTALLER_COMMAND
        self.assertEqual(installer_command(), expected)

    def test_the_windows_hint_matches_the_command_the_docs_publish(self) -> None:
        from omh.commands.setup import WINDOWS_INSTALLER_COMMAND

        installation = (REPO_ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
        self.assertIn(WINDOWS_INSTALLER_COMMAND, installation)


if __name__ == "__main__":
    unittest.main()
