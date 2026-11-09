"""A staged generation's venv is created from the installer's stable base interpreter (#2683)."""

from __future__ import annotations

from argparse import Namespace
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory, gettempdir
import unittest
from unittest.mock import patch

from omh.install.self_update import BASE_PYTHON_MARKER, BASE_PYTHON_PROBE_BUDGET_SECONDS, run_installer_self_update, stable_base_python
from omh.install.self_update_base_python import base_python_candidates, creator_interpreter, pinned_base_finding, read_pyvenv_cfg
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

    def __init__(self, versions: dict[str, str] | None = None, *, default: str = "3.15", raises: dict[str, BaseException] | None = None, venv_returncode: int = 1, noise: str = "") -> None:
        self.versions = versions or {}
        self.default = default
        self.raises = raises or {}
        self.venv_returncode = venv_returncode
        self.commands: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.noise = noise

    def __call__(self, command: list[str], /, *, text: bool, stdout: int | None, stderr: int | None, env: dict[str, str] | None, timeout: float | None) -> subprocess.CompletedProcess[str]:
        _ = text, stdout, stderr, env, timeout
        self.commands.append(list(command))
        if command[1:4] == ["-I", "-S", "-c"]:
            self.timeouts.append(timeout)
            if command[0] in self.raises:
                raise self.raises[command[0]]
            return subprocess.CompletedProcess(command, 0, self.noise + BASE_PYTHON_MARKER + self.versions.get(command[0], self.default) + "\n", "")
        if command[1:3] == ["-m", "venv"]:
            return subprocess.CompletedProcess(command, self.venv_returncode, "", "venv stopped by the test")
        return subprocess.CompletedProcess(command, 1, "", "unexpected command")

    def probes(self) -> list[str]:
        return [command[0] for command in self.commands if command[1:4] == ["-I", "-S", "-c"]]


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
            chosen = stable_base_python(str(brew.bootstrap_python), runner=runner, platform=POSIX, version=(3, 15), abiflags="")
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
            chosen = stable_base_python(str(generation_python), runner=FakeRunner(), platform=POSIX, version=(3, 15), abiflags="")
            self.assertEqual(chosen, str(brew.stable))

    def test_an_interpreter_on_another_minor_release_is_never_picked(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            moved = _file(root / "usr" / "local" / "bin" / "python3")
            home = root / "usr" / "local" / "bin"
            _file(home / "python3.15")
            seed = _venv(root / "venv", home=home, creator=moved)
            runner = FakeRunner({str(moved): "3.16"})
            chosen = stable_base_python(str(seed), runner=runner, platform=POSIX, version=(3, 15), abiflags="")
            self.assertEqual(chosen, str(home / "python3.15"))
            self.assertEqual(runner.probes()[0], str(moved))
            everything_moved = FakeRunner(default="3.16")
            self.assertEqual(stable_base_python(str(seed), runner=everything_moved, platform=POSIX, version=(3, 15), abiflags=""), str(seed))

    def test_a_probe_that_cannot_run_skips_that_candidate(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            for failure in (PermissionError("not executable"), subprocess.TimeoutExpired("probe", 30.0)):
                with self.subTest(type(failure).__name__):
                    runner = FakeRunner(raises={str(brew.stable): failure})
                    chosen = stable_base_python(str(brew.bootstrap_python), runner=runner, platform=POSIX, version=(3, 15), abiflags="")
                    self.assertEqual(chosen, str(brew.bootstrap_python))

    def test_a_missing_or_unreadable_pyvenv_cfg_keeps_todays_interpreter(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            bare = _file(root / "plain" / "bin" / "python")
            runner = FakeRunner()
            self.assertEqual(stable_base_python(str(bare), runner=runner, platform=POSIX, version=(3, 15), abiflags=""), str(bare))
            garbled = _file(root / "garbled" / "bin" / "python")
            (root / "garbled" / "pyvenv.cfg").write_bytes(b"home = \xff\xfe\n")
            self.assertEqual(read_pyvenv_cfg(root / "garbled"), {})
            self.assertEqual(stable_base_python(str(garbled), runner=runner, platform=POSIX, version=(3, 15), abiflags=""), str(garbled))
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
            self.assertEqual(stable_base_python(str(seed), runner=FakeRunner(), platform=WINDOWS, version=(3, 15), abiflags=""), str(base))

    def test_the_creator_keeps_a_path_with_spaces_whole(self) -> None:
        base = Path(gettempdir()).absolute() / "Program Files" / "Python315" / "python.exe"
        command = f"{base} -m venv {Path(gettempdir()).absolute() / 'omh' / 'venv'}"
        self.assertEqual(creator_interpreter({"command": command}, Path("venv")), base)
        self.assertIsNone(creator_interpreter({"command": "python3.15"}, Path("venv")))
        self.assertIsNone(creator_interpreter({}, Path("venv")))

    def test_the_update_hands_the_stable_interpreter_to_venv(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            root = brew.bootstrap.parent
            (root / "omh" / "skills").mkdir(parents=True)
            runner = FakeRunner(default=f"{sys.version_info.major}.{sys.version_info.minor}{getattr(sys, 'abiflags', '')}")
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

    def test_a_chain_cleanup_cut_still_reaches_the_installer_base_through_the_bootstrap(self) -> None:
        # Before the fix g2 was created by g1's python and g1 by the bootstrap's;
        # cleanup keeps active, previous and bootstrap, so g1 is gone and g2's
        # walk ends with only the keg `home`. The bootstrap anchor still names
        # the installer's base, and it must win over the keg.
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            generations = Path(temporary) / "share" / "omh" / "generations"
            g1_python = _venv(generations / "g1" / "venv", home=brew.keg_bin, creator=brew.bootstrap_python)
            g2_python = _venv(generations / "g2" / "venv", home=brew.keg_bin, creator=g1_python)
            shutil.rmtree(generations / "g1")
            alone = base_python_candidates(str(g2_python), version=(3, 15), is_windows=False)
            self.assertTrue(all("Cellar" in candidate for candidate in alone), alone)
            anchored = base_python_candidates(str(g2_python), version=(3, 15), is_windows=False, anchors=(str(brew.bootstrap_python),))
            self.assertEqual(anchored[0], str(brew.stable))
            self.assertLess(anchored.index(str(brew.stable_bin / "python3.15")), anchored.index(str(brew.keg)))
            chosen = stable_base_python(str(g2_python), runner=FakeRunner(), platform=POSIX, anchors=(str(brew.bootstrap_python),), version=(3, 15), abiflags="")
            self.assertEqual(chosen, str(brew.stable))

    def test_the_update_anchors_on_the_bootstrap_venv(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            root = brew.bootstrap.parent
            generation_python = _venv(root / "generations" / "g2" / "venv", home=brew.keg_bin, creator=root / "generations" / "g1" / "venv" / "bin" / "python")
            (root / "omh" / "skills").mkdir(parents=True)
            runner = FakeRunner(default=f"{sys.version_info.major}.{sys.version_info.minor}{getattr(sys, 'abiflags', '')}")
            args = Namespace(json=True, omh_home=str(root / "omh"), hermes_home=str(root / "hermes"), recover_known_good=False, scope=None)
            plan = {"method": "installer", "release": Namespace(package_url="test://candidate", version="1.0.7"), "python": str(generation_python), "venv_dir": str(brew.bootstrap)}
            with patch.dict(os.environ, {"OMH_VENV_DIR": str(brew.bootstrap), "OMH_BIN_DIR": str(root / "bin")}, clear=False):
                run_installer_self_update(args, plan, runner=runner, platform=POSIX)
            venv_commands = [command for command in runner.commands if command[1:3] == ["-m", "venv"]]
            self.assertEqual([command[0] for command in venv_commands], [str(brew.stable)])

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "POSIX folder permissions, not root")
    def test_a_folder_the_user_cannot_enter_falls_back_instead_of_raising(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            locked = root / "locked"
            hidden_base = _file(locked / "bin" / "python3.15")
            seed = _venv(root / "venv", home=locked / "bin", creator=locked / "inner" / "bin" / "python")
            _file(locked / "inner" / "pyvenv.cfg")
            locked.chmod(0)
            try:
                self.assertEqual(base_python_candidates(str(seed), version=(3, 15), is_windows=False), [])
                runner = FakeRunner()
                self.assertEqual(stable_base_python(str(seed), runner=runner, platform=POSIX, version=(3, 15), abiflags=""), str(seed))
                self.assertEqual(runner.probes(), [])
            finally:
                locked.chmod(0o700)
            self.assertTrue(hidden_base.is_file())

    def test_relative_cfg_paths_read_against_the_venv_folder_not_the_cwd(self) -> None:
        with TemporaryDirectory() as temporary, TemporaryDirectory() as elsewhere:
            root = Path(temporary)
            venv = root / "venv"
            _file(venv / "bin" / "python")
            _file(venv / "base" / "python3.15")
            _file(Path(elsewhere) / "python3")
            (venv / "pyvenv.cfg").write_text("home = base\ncommand = python3 -m venv x\n", encoding="utf-8")
            previous = os.getcwd()
            os.chdir(elsewhere)
            try:
                candidates = base_python_candidates(str(venv / "bin" / "python"), version=(3, 15), is_windows=False)
            finally:
                os.chdir(previous)
            self.assertEqual(candidates, [str(venv / "base" / "python3.15")])

    def test_a_free_threaded_build_keeps_its_own_build(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "usr" / "bin"
            threaded = _file(home / "python3.14t")
            default = _file(home / "python3.14")
            seed = _venv(root / "venv", home=home, creator=root / "gone" / "python3.14t")
            runner = FakeRunner({str(threaded): "3.14t", str(default): "3.14"})
            self.assertEqual(stable_base_python(str(seed), runner=runner, platform=POSIX, version=(3, 14), abiflags="t"), str(threaded))
            only_default = FakeRunner({str(threaded): "3.14", str(default): "3.14"})
            self.assertEqual(stable_base_python(str(seed), runner=only_default, platform=POSIX, version=(3, 14), abiflags="t"), str(seed))
            self.assertEqual(stable_base_python(str(seed), runner=FakeRunner({str(default): "3.14"}), platform=POSIX, version=(3, 14), abiflags=""), str(default))

    def test_startup_output_before_the_marker_line_is_ignored(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary))
            runner = FakeRunner(noise="sitecustomize says hello\n3.99\n")
            self.assertEqual(stable_base_python(str(brew.bootstrap_python), runner=runner, platform=POSIX, version=(3, 15), abiflags=""), str(brew.stable))

    def test_probing_stops_at_the_overall_budget(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "usr" / "bin"
            names = [_file(home / name) for name in ("python3.15", "python3", "python")]
            seed = _venv(root / "venv", home=home, creator=root / "gone" / "python3.15")
            hung = subprocess.TimeoutExpired("probe", 10.0)
            runner = FakeRunner(raises={str(path): hung for path in names})
            ticks = iter([0.0, 0.0, BASE_PYTHON_PROBE_BUDGET_SECONDS - 4.0, BASE_PYTHON_PROBE_BUDGET_SECONDS + 1.0])
            chosen = stable_base_python(str(seed), runner=runner, platform=POSIX, version=(3, 15), abiflags="", clock=lambda: next(ticks))
            self.assertEqual(chosen, str(seed))
            self.assertEqual(runner.probes(), [str(names[0]), str(names[1])])
            self.assertEqual(runner.timeouts, [10.0, 4.0], "the last probe gets only what is left of the budget")


class GenerationBasePythonDoctorTests(unittest.TestCase):
    """`omh doctor` names a generation venv bound to a pinned or removed base, with the repair."""

    def _layout(self, root: Path) -> tuple[HomebrewLayout, Path]:
        brew = HomebrewLayout(root)
        # The stable spelling is a link to the keg, as `opt/python@3.15` is.
        brew.stable.unlink()
        brew.stable.symlink_to(brew.keg)
        generation = brew.bootstrap.parent / "generations" / "g2"
        _venv(generation / "venv", home=brew.keg_bin, creator=generation.parent / "g1" / "venv" / "bin" / "python")
        return brew, generation

    def _doctor(self, root: Path, generation: Path, bootstrap: Path):
        from omh.maintenance import doctor

        state = root / "share" / "omh" / "self-update.json"
        state.write_text(json.dumps({"active": {"id": generation.name, "path": str(generation)}}), encoding="utf-8")
        with (
            patch.object(doctor, "managed_command_self_update_state_path", return_value=state),
            patch.object(doctor, "managed_command_venv_dir", return_value=bootstrap),
            patch.object(doctor.sys, "prefix", str(generation / "venv")),
        ):
            return doctor._generation_base_python_check()

    @unittest.skipIf(os.name == "nt", "POSIX symlinks")
    def test_a_pinned_base_with_a_stable_alias_warns_with_the_repair(self) -> None:
        with TemporaryDirectory() as temporary:
            brew, generation = self._layout(Path(temporary).resolve())
            finding = pinned_base_finding(generation / "venv", version=(3, 15), is_windows=False, anchors=(str(brew.bootstrap_python),))
            assert finding is not None
            self.assertEqual((finding["state"], finding["stable"], finding["home"]), ("pinned", str(brew.stable), str(brew.keg)))
            quoted = [shlex.quote(str(path)) for path in (generation / "venv" / "bin" / "python3.15", brew.stable, generation / "venv")]
            self.assertEqual(finding["repair"], f"rm -f {quoted[0]} && {quoted[1]} -m venv --upgrade {quoted[2]}")
            self.assertIsNone(pinned_base_finding(brew.bootstrap, version=(3, 15), is_windows=False), "a venv made from the stable spelling is fine")

    def test_a_removed_base_is_reported_gone_with_the_bootstrap_base_to_repair_from(self) -> None:
        with TemporaryDirectory() as temporary:
            brew = HomebrewLayout(Path(temporary).resolve())
            generation = brew.bootstrap.parent / "generations" / "g2"
            _venv(generation / "venv", home=brew.keg_bin, creator=generation.parent / "g1" / "venv" / "bin" / "python")
            brew.keg.unlink()
            finding = pinned_base_finding(generation / "venv", version=(3, 15), is_windows=False, anchors=(str(brew.bootstrap_python),))
            assert finding is not None
            self.assertEqual((finding["state"], finding["stable"]), ("gone", str(brew.stable)))
            windows = pinned_base_finding(generation / "venv", version=(3, 15), is_windows=True, anchors=())
            assert windows is not None
            self.assertEqual((windows["state"], windows["stable"], "repair" in windows), ("gone", "", False))

    @unittest.skipIf(os.name == "nt", "POSIX symlinks")
    def test_doctor_warns_on_the_active_generation(self) -> None:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            stable_bin = root / "opt" / "python" / "bin"
            keg_bin = root / "Cellar" / "python" / "9.9.9" / "bin"
            keg = _file(keg_bin / f"python{version}")
            stable_bin.mkdir(parents=True)
            (stable_bin / f"python{version}").symlink_to(keg)
            bootstrap = root / "share" / "omh" / "venv"
            _venv(bootstrap, home=stable_bin, creator=stable_bin / f"python{version}")
            generation = root / "share" / "omh" / "generations" / "g2"
            _venv(generation / "venv", home=keg_bin, creator=root / "gone" / "bin" / "python")
            check = self._doctor(root, generation, bootstrap)
            self.assertFalse(check.ok)
            self.assertEqual(check.severity, "warning")
            self.assertIn("version-pinned", check.message)
            self.assertIn(f"{shlex.quote(str(stable_bin / f'python{version}'))} -m venv --upgrade", check.next_action)
            self.assertIn(f"must run Python {version}", check.next_action)
            healthy = root / "share" / "omh" / "generations" / "g3"
            _venv(healthy / "venv", home=stable_bin, creator=stable_bin / f"python{version}")
            self.assertTrue(self._doctor(root, healthy, bootstrap).ok)

    @unittest.skipIf(os.name == "nt", "POSIX symlinks")
    def test_a_home_folder_that_is_itself_a_link_is_not_pinned(self) -> None:
        # uv's minor-version folder (`cpython-3.13-...`) links to the patch
        # folder and moves on `uv python upgrade`; a venv bound to it survives.
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            patch_bin = root / "uv" / "cpython-3.15.2" / "bin"
            real = _file(patch_bin / "python3.15")
            minor = root / "uv" / "cpython-3.15"
            minor.symlink_to(root / "uv" / "cpython-3.15.2", target_is_directory=True)
            user_bin = root / "local" / "bin"
            user_bin.mkdir(parents=True)
            (user_bin / "python3.15").symlink_to(real)
            bootstrap = root / "omh" / "venv"
            bootstrap_python = _venv(bootstrap, home=user_bin, creator=user_bin / "python3.15")
            generation = root / "omh" / "generations" / "g2" / "venv"
            _venv(generation, home=minor / "bin", creator=root / "omh" / "generations" / "g1" / "venv" / "bin" / "python")
            self.assertIsNone(pinned_base_finding(generation, version=(3, 15), is_windows=False, anchors=(str(bootstrap_python),)))
            pinned = root / "omh" / "generations" / "g3" / "venv"
            _venv(pinned, home=patch_bin, creator=root / "gone" / "bin" / "python")
            finding = pinned_base_finding(pinned, version=(3, 15), is_windows=False, anchors=(str(bootstrap_python),))
            assert finding is not None
            self.assertEqual((finding["state"], finding["stable"]), ("pinned", str(user_bin / "python3.15")), "a fully resolved patch folder still warns")

    def test_a_gone_base_prefers_a_candidate_named_for_the_same_minor(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            stable_bin = root / "usr" / "local" / "bin"
            _file(stable_bin / "python3")
            versioned = _file(stable_bin / "python3.15")
            bootstrap_python = _venv(root / "omh" / "venv", home=stable_bin, creator=stable_bin / "python3")
            generation = root / "omh" / "generations" / "g2" / "venv"
            _venv(generation, home=root / "Cellar" / "3.15.0" / "bin", creator=root / "gone" / "bin" / "python")
            finding = pinned_base_finding(generation, version=(3, 15), is_windows=False, anchors=(str(bootstrap_python),))
            assert finding is not None
            self.assertEqual((finding["state"], finding["stable"]), ("gone", str(versioned)))

    def test_a_state_file_that_vanishes_before_the_read_is_not_a_crash(self) -> None:
        from omh.maintenance import doctor

        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            state = root / "self-update.json"
            state.write_text("{}", encoding="utf-8")
            with (
                patch.object(doctor, "managed_command_self_update_state_path", return_value=state),
                patch.object(doctor, "read_json_object", return_value=None),
                patch.object(doctor.sys, "prefix", str(root / "generations" / "g1" / "venv")),
            ):
                check = doctor._generation_base_python_check()
        self.assertTrue(check.ok)
        self.assertFalse(check.observed)


if __name__ == "__main__":
    unittest.main()
