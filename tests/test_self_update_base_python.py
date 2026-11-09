"""A staged generation's venv is created from the installer's stable base interpreter (#2683)."""

from __future__ import annotations

from argparse import Namespace
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.install.self_update import run_installer_self_update, stable_base_python
from omh.install.self_update_base_python import base_python_candidates, creator_interpreter, read_pyvenv_cfg
from omh.install.self_update_platform import SelfUpdatePlatform

POSIX = SelfUpdatePlatform(is_windows=False)
WINDOWS = SelfUpdatePlatform(is_windows=True)


def _file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _venv(root: Path, *, home: Path, creator: Path, windows: bool = False) -> Path:
    """A venv whose `pyvenv.cfg` records `home` and `command` the way CPython writes them."""
    python = root / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")
    _file(python)
    (root / "pyvenv.cfg").write_text(
        f"home = {home}\ninclude-system-site-packages = false\nversion = 3.15.2\n"
        f"executable = {creator}\ncommand = {creator} -m venv {root}\n",
        encoding="utf-8",
    )
    return python


class FakeRunner:
    """Answers the version probe from a table and records every command; nothing is spawned."""

    def __init__(self, versions: dict[str, str] | None = None, *, default: str = "3.15", raises: dict[str, BaseException] | None = None, venv_returncode: int = 1) -> None:
        self.versions = versions or {}
        self.default = default
        self.raises = raises or {}
        self.venv_returncode = venv_returncode
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], /, *, text: bool, stdout: int | None, stderr: int | None, env: dict[str, str] | None, timeout: float | None) -> subprocess.CompletedProcess[str]:
        _ = text, stdout, stderr, env, timeout
        self.commands.append(list(command))
        if command[1:3] == ["-I", "-c"]:
            if command[0] in self.raises:
                raise self.raises[command[0]]
            return subprocess.CompletedProcess(command, 0, self.versions.get(command[0], self.default) + "\n", "")
        if command[1:3] == ["-m", "venv"]:
            return subprocess.CompletedProcess(command, self.venv_returncode, "", "venv stopped by the test")
        return subprocess.CompletedProcess(command, 1, "", "unexpected command")

    def probes(self) -> list[str]:
        return [command[0] for command in self.commands if command[1:3] == ["-I", "-c"]]


class HomebrewLayout:
    """`opt/python@3.15` names the stable link; `Cellar/python@3.15/3.15.0` the keg one upgrade removes."""

    def __init__(self, root: Path) -> None:
        self.stable_bin = root / "opt" / "python@3.15" / "bin"
        self.stable = _file(self.stable_bin / "python3.15")
        self.keg_bin = root / "Cellar" / "python@3.15" / "3.15.0" / "Frameworks" / "Python.framework" / "Versions" / "3.15" / "bin"
        self.keg = _file(self.keg_bin / "python3.15")
        self.bootstrap = root / "share" / "omh" / "venv"
        self.bootstrap_python = _venv(self.bootstrap, home=self.stable_bin, creator=self.stable)


class StableBasePythonTests(unittest.TestCase):
    def test_the_bootstrap_venv_stages_from_the_interpreter_the_installer_ran(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            runner = FakeRunner()
            chosen = stable_base_python(str(brew.bootstrap_python), runner=runner, platform=POSIX, version=(3, 15))
            self.assertEqual(chosen, str(brew.stable))
            self.assertNotIn("Cellar", chosen)

    def test_a_generation_an_older_omh_staged_leads_back_past_its_keg_home(self) -> None:
        # The reported generation: home is the keg, command is the bootstrap venv's python.
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            generation = Path(temporary) / "share" / "omh" / "generations" / "20261109002739162546-edfca25300" / "venv"
            generation_python = _venv(generation, home=brew.keg_bin, creator=brew.bootstrap_python)
            candidates = base_python_candidates(str(generation_python), version=(3, 15), is_windows=False)
            self.assertEqual(candidates[0], str(brew.stable))
            self.assertIn(str(brew.keg), candidates[1:], "the keg stays a last resort, never ahead of the stable base")
            chosen = stable_base_python(str(generation_python), runner=FakeRunner(), platform=POSIX, version=(3, 15))
            self.assertEqual(chosen, str(brew.stable))

    def test_an_interpreter_on_another_minor_release_is_never_picked(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            moved = _file(root / "usr" / "local" / "bin" / "python3")
            home = root / "usr" / "local" / "bin"
            _file(home / "python3.15")
            seed = _venv(root / "venv", home=home, creator=moved)
            runner = FakeRunner({str(moved): "3.16"})
            chosen = stable_base_python(str(seed), runner=runner, platform=POSIX, version=(3, 15))
            self.assertEqual(chosen, str(home / "python3.15"))
            self.assertEqual(runner.probes()[0], str(moved))
            everything_moved = FakeRunner(default="3.16")
            self.assertEqual(stable_base_python(str(seed), runner=everything_moved, platform=POSIX, version=(3, 15)), str(seed))

    def test_a_probe_that_cannot_run_skips_that_candidate(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            for failure in (PermissionError("not executable"), subprocess.TimeoutExpired("probe", 30.0)):
                with self.subTest(type(failure).__name__):
                    runner = FakeRunner(raises={str(brew.stable): failure})
                    chosen = stable_base_python(str(brew.bootstrap_python), runner=runner, platform=POSIX, version=(3, 15))
                    self.assertEqual(chosen, str(brew.bootstrap_python))

    def test_a_missing_or_unreadable_pyvenv_cfg_keeps_todays_interpreter(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            bare = _file(root / "plain" / "bin" / "python")
            runner = FakeRunner()
            self.assertEqual(stable_base_python(str(bare), runner=runner, platform=POSIX, version=(3, 15)), str(bare))
            garbled = _file(root / "garbled" / "bin" / "python")
            (root / "garbled" / "pyvenv.cfg").write_bytes(b"home = \xff\xfe\n")
            self.assertEqual(read_pyvenv_cfg(root / "garbled"), {})
            self.assertEqual(stable_base_python(str(garbled), runner=runner, platform=POSIX, version=(3, 15)), str(garbled))
            self.assertEqual(runner.probes(), [], "no evidence, no extra process")

    def test_a_base_interpreter_or_a_removed_one_is_left_alone(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            self.assertEqual(base_python_candidates(str(brew.stable), version=(3, 15), is_windows=False), [])
            brew.stable.unlink()
            self.assertNotIn(str(brew.stable), base_python_candidates(str(brew.bootstrap_python), version=(3, 15), is_windows=False))

    def test_the_windows_layout_reads_scripts_python_exe_and_its_home(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = root / "Programs" / "Python" / "Python315"
            base = _file(installed / "python.exe")
            seed = _venv(root / "omh" / "venv", home=installed, creator=base, windows=True)
            self.assertEqual(base_python_candidates(str(seed), version=(3, 15), is_windows=True), [str(base)])
            self.assertEqual(stable_base_python(str(seed), runner=FakeRunner(), platform=WINDOWS, version=(3, 15)), str(base))

    def test_the_creator_keeps_a_path_with_spaces_whole(self) -> None:
        command = r"C:\Program Files\Python315\python.exe -m venv C:\Users\me\AppData\Local\omh\venv"
        self.assertEqual(str(creator_interpreter({"command": command})), str(Path(r"C:\Program Files\Python315\python.exe")))
        self.assertIsNone(creator_interpreter({"command": "python3.15"}))
        self.assertIsNone(creator_interpreter({}))

    def test_the_update_hands_the_stable_interpreter_to_venv(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            root = brew.bootstrap.parent
            (root / "omh" / "skills").mkdir(parents=True)
            runner = FakeRunner(default=f"{sys.version_info.major}.{sys.version_info.minor}")
            args = Namespace(json=True, omh_home=str(root / "omh"), hermes_home=str(root / "hermes"), recover_known_good=False, scope=None)
            plan = {
                "method": "installer",
                "release": Namespace(package_url="test://candidate", version="1.0.7"),
                "python": str(brew.bootstrap_python),
                "venv_dir": str(brew.bootstrap),
            }
            with patch.dict(os.environ, {"OMH_VENV_DIR": str(brew.bootstrap), "OMH_BIN_DIR": str(root / "bin")}, clear=False):
                result = run_installer_self_update(args, plan, runner=runner, platform=POSIX)
            venv_commands = [command for command in runner.commands if command[1:3] == ["-m", "venv"]]
            self.assertEqual(len(venv_commands), 1)
            self.assertEqual(venv_commands[0][0], str(brew.stable))
            self.assertEqual(result["phase"], "staging")
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
