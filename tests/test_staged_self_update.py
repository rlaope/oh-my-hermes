import contextlib
from datetime import UTC, datetime
import io
import json
import os
from argparse import Namespace
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Callable, Literal, Protocol, TypeAlias, TypedDict
import unittest
from unittest.mock import patch

from _cli_harness import run_cli

from omh.commands import setup as setup_commands
from omh.config_adapter import external_dirs
from omh.core.errors import OmhError
from omh.install import installer as installer_commands
from omh.install import generation_hold, self_update, self_update_state
from omh.install.self_update import Runner, SelfUpdateResult, run_installer_self_update
from omh.install.self_update_platform import SelfUpdatePlatform, remove_directory_link
from omh.install.self_update_state import GarbageCollectionResult, STATE_SCHEMA_VERSION, collect_garbage, pointer_target, record_pointer, switch_current
from omh.system.local_store import atomic_write_json, file_lock
from omh.system.paths import OmhPaths


StrPath: TypeAlias = str | os.PathLike[str]
JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class InstallerPlan(TypedDict):
    method: str
    release: "FakeRelease"
    python: str
    venv_dir: str


class FakeRelease(Namespace):
    package_url: str
    version: str

    def __init__(self, *, package_url: str, version: str) -> None:
        super().__init__()
        self.package_url = package_url
        self.version = version


class SelfUpdateArgs(Namespace):
    json: bool
    omh_home: str
    hermes_home: str
    recover_known_good: bool

    def __init__(
        self,
        *,
        json: bool,
        omh_home: str,
        hermes_home: str,
        recover_known_good: bool,
    ) -> None:
        super().__init__()
        self.json = json
        self.omh_home = omh_home
        self.hermes_home = hermes_home
        self.recover_known_good = recover_known_good


class InstallerCommands(Protocol):
    def install_skill_pack(self, paths: OmhPaths) -> JsonValue: ...


def _bind_install_skill_pack(
    module: InstallerCommands,
) -> Callable[[OmhPaths], JsonValue]:
    return module.install_skill_pack


_decode_json: Callable[[str | bytes], JsonValue] = json.loads
_install_pack = _bind_install_skill_pack(installer_commands)


class ManagedWorkflowArgs(Namespace):
    omh_home: str
    hermes_home: str
    scope: str
    dry_run: bool
    force: bool
    memory_mode: str
    json: bool
    from_skills_dir: str | None
    source: str | None

    def __init__(
        self,
        *,
        omh_home: str,
        hermes_home: str,
        scope: str,
        dry_run: bool,
        force: bool,
        memory_mode: str,
        json: bool = False,
        from_skills_dir: str | None = None,
        source: str | None = None,
    ) -> None:
        super().__init__()
        self.omh_home = omh_home
        self.hermes_home = hermes_home
        self.scope = scope
        self.dry_run = dry_run
        self.force = force
        self.memory_mode = memory_mode
        self.json = json
        self.from_skills_dir = from_skills_dir
        self.source = source


def _read_json_object(path: Path) -> dict[str, JsonValue]:
    value = _decode_json(path.read_text())
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object in {path}")
    return value


def _install_skill_pack(paths: OmhPaths) -> dict[str, JsonValue]:
    value = _install_pack(paths)
    if not isinstance(value, dict):
        raise AssertionError("install result was not an object")
    return value


def _object(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise AssertionError(f"expected {label} to be an object")
    return value


def _array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise AssertionError(f"expected {label} to be an array")
    return value


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise AssertionError(f"expected {label} to be text")
    return value


def _runner_environment(environment: dict[str, str] | None) -> dict[str, str]:
    if environment is None:
        raise AssertionError("runner environment was not supplied")
    return environment


StateMutator: TypeAlias = Callable[[dict[str, JsonValue], Path, Path], None]


class JunctionInvocation(TypedDict):
    shell: Literal[False]
    cwd: str
    env: dict[str, str]
    text: Literal[True]
    stdout: int
    stderr: int
    timeout: float


def _junction_invocation(
    *,
    shell: Literal[False],
    cwd: str,
    env: dict[str, str],
    text: Literal[True],
    stdout: int,
    stderr: int,
    timeout: float,
) -> JunctionInvocation:
    return {
        "shell": shell,
        "cwd": cwd,
        "env": env,
        "text": text,
        "stdout": stdout,
        "stderr": stderr,
        "timeout": timeout,
    }


class StagedSelfUpdateTests(unittest.TestCase):
    @staticmethod
    def _platform() -> SelfUpdatePlatform:
        # Keep host pointer-swap semantics, but model the junction subprocess
        # with real links, as the dedicated Windows adapter tests do.
        def junction_runner(
            command: list[str],
            *,
            shell: bool,
            cwd: str,
            env: dict[str, str],
            text: Literal[True],
            stdout: int,
            stderr: int,
            timeout: float,
        ) -> subprocess.CompletedProcess[str]:
            _ = shell, text, stdout, stderr, timeout
            link = Path(env["OMH_JUNCTION_LINK"])
            target = Path(cwd) / env["OMH_JUNCTION_TARGET"]
            link.symlink_to(target, target_is_directory=True)
            return subprocess.CompletedProcess(command, 0, "", "")

        return SelfUpdatePlatform(is_windows=SelfUpdatePlatform.host().is_windows, runner=junction_runner)

    def _fixture(
        self, root: Path, *, pointer: bool = False, launcher: bool = True
    ) -> tuple[Path, SelfUpdateArgs, InstallerPlan]:
        legacy = root / "venv"
        (legacy / "bin").mkdir(parents=True)
        (legacy / "bin" / "python").touch()
        (legacy / "bin" / "omh").touch()
        (root / "omh" / "skills").mkdir(parents=True)
        if launcher:
            (root / "bin").mkdir()
            (root / "bin" / "omh").symlink_to(legacy / "bin" / "omh")
        args = SelfUpdateArgs(
            json=True,
            omh_home=str(root / "omh"),
            hermes_home=str(root / "hermes"),
            recover_known_good=False,
        )
        plan: InstallerPlan = {
            "method": "installer",
            "release": FakeRelease(package_url="test://candidate", version="1.0.7"),
            "python": str(legacy / "bin" / "python"),
            "venv_dir": str(legacy),
        }
        if pointer:
            _ = self._migrated(root, legacy, launcher=launcher)
        return legacy, args, plan

    def _migrated(self, root: Path, legacy: Path, *, launcher: bool = True) -> Path:
        bootstrap = root / "generations" / "bootstrap-legacy"
        bootstrap.mkdir(parents=True)
        (bootstrap / "venv").symlink_to(legacy, target_is_directory=True)
        (bootstrap / "skills").symlink_to(root / "omh" / "skills", target_is_directory=True)
        switch_current(root, bootstrap, platform=self._platform())
        if launcher:
            launcher_path = root / "bin" / "omh"
            launcher_path.unlink()
            launcher_path.symlink_to(root / "current" / "venv" / "bin" / "omh")
        (root / "hermes").mkdir()
        _ = (root / "hermes" / "config.yaml").write_text(
            f"skills:\n  external_dirs:\n  - {root / 'current' / 'skills'}\n"
        )
        atomic_write_json(
            root / "self-update.json",
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "active": self._entry(bootstrap, "bootstrap"),
                "previous_known_good": None,
                "pointer": {"path": str(root / "current"), "target": "generations/bootstrap-legacy"},
                "migration": {"status": "completed"},
                "activation_in_progress": None,
                "retained_generations": ["bootstrap-legacy"],
            },
            private=True,
        )
        return bootstrap

    @staticmethod
    def _entry(path: Path, kind: str = "generation") -> dict[str, JsonValue]:
        return {"id": path.name, "path": str(path), "kind": kind, "version": ""}

    def _runner(
        self,
        *,
        failure: str = "",
        version: str = "",
        restore_ok: bool = False,
    ) -> Runner:
        def run(
            command: list[str],
            *,
            text: bool,
            stdout: int | None,
            stderr: int | None,
            env: dict[str, str] | None,
            timeout: float | None,
        ) -> subprocess.CompletedProcess[str]:
            _ = text, stdout, stderr, timeout
            if command[1:3] == ["-m", "venv"]:
                if failure == "venv":
                    return subprocess.CompletedProcess(command, 1, "", "venv unavailable")
                candidate = Path(command[-1]).parent
                (candidate / "venv" / "bin").mkdir(parents=True, exist_ok=True)
                (candidate / "venv" / "bin" / "python").touch()
                return subprocess.CompletedProcess(command, 0, "", "")
            if command[1:4] == ["-m", "pip", "install"]:
                return subprocess.CompletedProcess(command, failure == "pip", "", "pip failed")
            if command[1:4] == ["-P", "-c", "import omh.cli"]:
                return subprocess.CompletedProcess(command, failure == "import", "", "import failed")
            if "--version" in command:
                return subprocess.CompletedProcess(command, 0, version or "1.0.7\n", "")
            if "update" in command:
                if failure == "pack":
                    return subprocess.CompletedProcess(command, 1, "", "pack failed")
                generation = Path(_runner_environment(env)["OMH_SELF_UPDATE_GENERATION"])
                (generation / "skills" / "core").mkdir(parents=True, exist_ok=True)
                _ = (generation / "skills" / "core" / "SKILL.md").write_text("candidate")
                return subprocess.CompletedProcess(command, 0, "", "")
            if restore_ok and _runner_environment(env).get(self_update.ROLLBACK_RESTORE_ENV) == "1":
                return subprocess.CompletedProcess(command, 0, "", "")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 1)
            return subprocess.CompletedProcess(command, failure == "post", "", "post failed")

        return run

    def _run(
        self,
        root: Path,
        args: SelfUpdateArgs,
        plan: InstallerPlan,
        runner: Runner,
    ) -> SelfUpdateResult:
        with patch.dict(
            os.environ,
            {"OMH_VENV_DIR": str(root / "venv"), "OMH_BIN_DIR": str(root / "bin")},
            clear=False,
        ):
            return run_installer_self_update(args, plan, runner=runner, platform=self._platform())

    def _assert_pair(self, root: Path, expected: Path | None = None) -> None:
        current = (root / "current").resolve()
        config = (root / "hermes" / "config.yaml").read_text()
        self.assertIn((root / "current" / "skills").as_posix(), config.replace("\\", "/"))
        launcher = root / "bin" / "omh"
        if launcher.exists() or launcher.is_symlink():
            self.assertIn(str(root / "current"), os.readlink(launcher))
        if expected is not None:
            self._assert_same_path(current, expected)

    def _assert_same_path(self, actual: Path | None, expected: Path) -> None:
        self.assertIsNotNone(actual)
        assert actual is not None
        self.assertTrue(os.path.samefile(actual, expected), f"{actual!s} does not identify {expected!s}")

    def test_fixture_uses_windows_pointer_strategy_without_starting_processes(self):
        with (
            TemporaryDirectory() as temporary,
            patch.object(SelfUpdatePlatform, "host", return_value=SelfUpdatePlatform(is_windows=True)),
            patch.object(subprocess, "Popen", side_effect=AssertionError("unexpected fixture subprocess")) as spawn,
        ):
            root = Path(temporary)
            legacy, args, plan = self._fixture(root, pointer=True)
            previous = root / "generations" / "bootstrap-legacy"
            self._assert_pair(root, previous)
            self._assert_same_path(root / "current" / "venv", legacy)
            self._assert_same_path(root / "current" / "skills", root / "omh" / "skills")

            result = self._run(root, args, plan, self._runner(failure="post"))

            self.assertEqual(result["activation"]["status"], "ok")
            self.assertEqual(result["phase"], "post_activation")
            self.assertTrue(result["rollback"]["performed"])
            self._assert_pair(root, previous)
            self.assertFalse(any(root.glob(".current.*")))
            spawn.assert_not_called()

    def test_venv_and_pip_failures_delete_candidates_without_moving_the_pair(self):
        for failure in ("venv", "pip"):
            with self.subTest(failure), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                before = (root / "current").resolve()
                result = self._run(root, args, plan, self._runner(failure=failure))
                self.assertFalse(result["ok"])
                self.assertEqual(result["phase"], "staging")
                self.assertEqual((root / "current").resolve(), before)
                self.assertFalse(Path(result["candidate"]["path"]).exists())
                self._assert_pair(root, before)

    def test_import_version_and_pack_smokes_never_touch_the_real_pair(self):
        for failure, version in (("import", ""), ("version", "1.0.6"), ("pack", "")):
            with self.subTest(failure), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                home_before = (root / "omh" / "skills").stat().st_mtime_ns
                config_before = (root / "hermes" / "config.yaml").read_bytes()
                result = self._run(root, args, plan, self._runner(failure=failure, version=version))
                self.assertFalse(result["ok"])
                self.assertEqual(result["phase"], "verification")
                self.assertFalse(Path(result["candidate"]["path"]).exists())
                self.assertEqual((root / "omh" / "skills").stat().st_mtime_ns, home_before)
                self.assertEqual((root / "hermes" / "config.yaml").read_bytes(), config_before)
                self._assert_pair(root)

    def test_migration_finds_the_legacy_skills_at_the_default_store_when_the_home_names_its_own(self) -> None:
        # The pre-pointer install registered and populated `<store>/skills` at
        # the store the resolver named then. A home that has since selected
        # its own store (`plugins.entries.omh.settings.omh_home`, read by the
        # standalone lane since #1679) resolves elsewhere now; the migration
        # must still link and strip the registration where it actually sits.
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            legacy = root / "legacy"
            (legacy / "bin").mkdir(parents=True)
            default_skills = root / ".omh" / "skills"
            default_skills.mkdir(parents=True)
            named_store = root / "named-store"
            hermes_home = root / "hermes"
            hermes_home.mkdir()
            (hermes_home / "config.yaml").write_text(
                f"skills:\n  external_dirs:\n    - {default_skills.as_posix()}\n"
                f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {named_store.as_posix()}\n",
                encoding="utf-8",
            )
            state: dict[str, JsonValue] = {"active": self._entry(legacy), "migration": {"status": "pending"}}
            paths = OmhPaths(omh_home=named_store, hermes_home=hermes_home)
            platform = SelfUpdatePlatform(is_windows=False)
            with patch.dict(os.environ, {"HOME": str(root), "USERPROFILE": str(root)}, clear=False):
                os.environ.pop("OMH_HOME", None)
                os.environ.pop("OMH_BIN_DIR", None)
                self_update_state.migrate_legacy(root, state, paths, platform)
            bootstrap = root / "generations" / "bootstrap-legacy"
            self.assertEqual((bootstrap / "skills").resolve(), default_skills.resolve())
            registered = external_dirs((hermes_home / "config.yaml").read_text(encoding="utf-8"))
            self.assertNotIn(default_skills.as_posix(), registered)
            self.assertIn((root / "current" / "skills").as_posix(), registered)
            self.assertFalse(named_store.exists())
            self.assertEqual(state["migration"]["status"], "completed")

    def test_migration_launcher_failure_keeps_old_pair_and_cleans_candidate(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy, args, plan = self._fixture(root)
            with patch("omh.install.self_update_state._retarget_launcher", side_effect=OSError("locked")):
                result = self._run(root, args, plan, self._runner())
            self.assertEqual(result["phase"], "migration")
            self.assertFalse(Path(result["candidate"]["path"]).exists())
            self.assertEqual((root / "bin" / "omh").resolve(), (legacy / "bin" / "omh").resolve())

    def test_activation_replace_failure_is_recoverable_without_rollback(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            previous = (root / "current").resolve()
            original = switch_current

            def reject_candidate(
                transaction_root: Path,
                target: Path,
                *,
                is_windows: bool | None = None,
                platform: SelfUpdatePlatform | None = None,
            ) -> None:
                if target.name != "bootstrap-legacy":
                    raise OmhError("replace failed")
                original(transaction_root, target, is_windows=is_windows, platform=platform)

            with patch("omh.install.self_update.switch_current", side_effect=reject_candidate):
                result = self._run(root, args, plan, self._runner())
            self.assertEqual(result["phase"], "activation")
            self.assertFalse(result["rollback"]["performed"])
            self.assertTrue(_read_json_object(root / "self-update.json")["activation_in_progress"])
            self._assert_pair(root, previous)

    def test_nonzero_and_timeout_post_activation_roll_back_and_reenter_previous(self):
        for failure, restore_ok in (("post", False), ("timeout", False), ("post", True), ("timeout", True)):
            with self.subTest(failure=failure, restore_ok=restore_ok), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                previous = (root / "current").resolve()
                calls: list[list[str]] = []
                runner = self._runner(failure=failure, restore_ok=restore_ok)

                def recording_runner(
                    command: list[str],
                    *,
                    text: Literal[True],
                    stdout: int | None,
                    stderr: int | None,
                    env: dict[str, str] | None,
                    timeout: float | None,
                ) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return runner(
                        command, text=text, stdout=stdout, stderr=stderr, env=env, timeout=timeout
                    )

                result = self._run(root, args, plan, recording_runner)
                self.assertFalse(result["ok"])
                self.assertEqual(result["phase"], "post_activation")
                self.assertTrue(result["rollback"]["performed"])
                # The re-entered update's stderr is the only place the cause
                # is written; it has to reach the result, not just the terminal.
                expected_reason = "post failed" if failure == "post" else "post-activation re-entry timed out"
                self.assertEqual(result["post_activation"].get("reason", ""), expected_reason)
                self.assertEqual(sum("--command-package-updated" in call and "update" not in call for call in calls), 2)
                self._assert_pair(root, previous)
                marker = _read_json_object(root / "self-update.json")["activation_in_progress"]
                if restore_ok:
                    # Only a successful restoring reentry may dispose the candidate.
                    self.assertFalse(Path(result["candidate"]["path"]).exists())
                    self.assertIsNone(marker)
                    self.assertEqual(result["rollback"]["restored"], previous.name)
                    self.assertNotEqual(result["recovery"]["status"], "required")
                else:
                    self.assertTrue(Path(result["candidate"]["path"]).is_dir())
                    pending = _object(marker, "pending rollback")
                    self.assertIs(pending["restore_required"], True)
                    self.assertEqual(pending["candidate"], result["candidate"]["path"])
                    self.assertEqual(Path(_text(pending["previous"], "previous generation")).resolve(), previous.resolve())
                    self.assertEqual(result["rollback"]["restored"], "")
                    self.assertEqual(result["rollback"]["status"], "failed")
                    self.assertEqual(result["rollback"]["reason"], expected_reason)
                    self.assertEqual(result["recovery"]["status"], "required")
                    self.assertEqual(result["recovery"]["action"], "restore_failed")

    def test_rollback_reentry_is_marked_so_its_summary_says_rollback(self):
        # The rollback re-entry re-renders the known-good pack and, unmarked,
        # printed the ordinary "Installed release ... OMH update complete."
        # card -- the owner read that as a downgrade. Only the restoring
        # re-entry carries the marker; the candidate's re-entry does not.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            reentries: list[dict[str, str]] = []
            runner = self._runner(failure="post")

            def recording_runner(
                command: list[str],
                *,
                text: Literal[True],
                stdout: int | None,
                stderr: int | None,
                env: dict[str, str] | None,
                timeout: float | None,
            ) -> subprocess.CompletedProcess[str]:
                if "--command-package-updated" in command and "update" not in command:
                    reentries.append(dict(_runner_environment(env)))
                return runner(
                    command, text=text, stdout=stdout, stderr=stderr, env=env, timeout=timeout
                )

            result = self._run(root, args, plan, recording_runner)
            self.assertTrue(result["rollback"]["performed"])
            self.assertEqual(len(reentries), 2)
            self.assertNotIn(self_update.ROLLBACK_RESTORE_ENV, reentries[0])
            self.assertEqual(reentries[1].get(self_update.ROLLBACK_RESTORE_ENV), "1")

        payload: dict[str, object] = {
            "skills": [],
            "source": "builtin",
            "command_package": {"updated": True},
            "release_update": {"previous": {"version": "2.0.2"}, "current": {"version": "2.0.2"}},
        }
        for restoring in (False, True):
            with self.subTest(restoring=restoring):
                env = {self_update.ROLLBACK_RESTORE_ENV: "1"} if restoring else {}
                output = io.StringIO()
                with (
                    patch.dict(os.environ, env, clear=False),
                    patch("omh.commands.setup._resolve_language", return_value="en"),
                    patch("omh.commands.setup._install_operation", return_value="update"),
                    patch("omh.commands.setup._install_result", return_value=payload),
                    patch("omh.commands.setup._use_color", return_value=False),
                    contextlib.redirect_stdout(output),
                ):
                    if not restoring:
                        _ = os.environ.pop(self_update.ROLLBACK_RESTORE_ENV, None)
                    status = setup_commands.cmd_install(Namespace(json=False))
                self.assertEqual(status, 0)
                printed = output.getvalue()
                if restoring:
                    self.assertIn("OMH rollback complete", printed)
                    self.assertIn("Oh-My-Hermes Rollback", printed)
                    self.assertIn("Restored release: 2.0.2", printed)
                    self.assertNotIn("update complete", printed.lower())
                    self.assertNotIn("Installed release", printed)
                else:
                    self.assertIn("OMH update complete.", printed)
                    self.assertIn("Installed release: 2.0.2", printed)
                    self.assertNotIn("Rollback", printed)

    def test_lock_is_nonblocking_and_does_not_mutate_the_pair(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            with file_lock(root / "self-update.json", timeout_seconds=1, private=True):
                with self.assertRaisesRegex(OmhError, "another omh update"):
                    _ = self._run(root, args, plan, self._runner())
            self._assert_pair(root)

    def test_interrupted_markers_reconcile_candidate_and_previous_deterministically(self):
        for at_candidate in (True, False):
            with self.subTest(at_candidate=at_candidate), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                previous = (root / "current").resolve()
                candidate = root / "generations" / "interrupted"
                (candidate / "venv" / "bin").mkdir(parents=True)
                (candidate / "skills").mkdir()
                if at_candidate:
                    switch_current(root, candidate, platform=self._platform())
                state = _read_json_object(root / "self-update.json")
                state["activation_in_progress"] = {
                    "candidate": str(candidate), "previous": str(previous), "phase": "pre_switch"
                }
                atomic_write_json(root / "self-update.json", state, private=True)
                result = self._run(root, args, plan, self._runner(failure="pip"))
                expected = "completed_interrupted_activation" if at_candidate else "discarded_unswitched_candidate"
                expected_phase = "recovery" if at_candidate else "staging"
                self.assertEqual(result["phase"], expected_phase)
                self.assertEqual(result["recovery"].get("action"), expected)
                self.assertEqual((root / "current").resolve(), (candidate if at_candidate else previous).resolve())
                self._assert_pair(root)

    def test_interrupted_rollback_reports_the_recovery_phase(self):
        for restore_ok in (False, True):
            with self.subTest(restore_ok=restore_ok), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                previous = root / "generations" / "bootstrap-legacy"
                candidate = root / "generations" / "interrupted"
                (candidate / "venv" / "bin").mkdir(parents=True)
                (candidate / "skills").mkdir()
                switch_current(root, candidate, platform=self._platform())
                state = _read_json_object(root / "self-update.json")
                state["activation_in_progress"] = {
                    "candidate": str(candidate),
                    "previous": str(previous),
                    "phase": "post_switch",
                }
                atomic_write_json(root / "self-update.json", state, private=True)
                result = self._run(root, args, plan, self._runner(failure="post", restore_ok=restore_ok))
                self.assertFalse(result["ok"])
                self.assertEqual(result["phase"], "recovery")
                self.assertTrue(result["rollback"]["performed"])
                self.assertEqual((root / "current").resolve(), previous.resolve())
                self._assert_pair(root, previous)
                marker = _read_json_object(root / "self-update.json")["activation_in_progress"]
                if restore_ok:
                    self.assertEqual(result["recovery"].get("action"), "rolled_back_interrupted_activation")
                    self.assertEqual(result["rollback"]["restored"], previous.name)
                    self.assertIsNone(marker)
                    self.assertFalse(candidate.exists())
                else:
                    self.assertEqual(result["recovery"]["status"], "required")
                    self.assertEqual(result["recovery"].get("action"), "restore_failed")
                    self.assertEqual(result["rollback"]["status"], "failed")
                    self.assertEqual(result["rollback"]["restored"], "")
                    self.assertEqual(result["rollback"]["reason"], "post failed")
                    self.assertTrue(candidate.is_dir())
                    pending = _object(marker, "pending interrupted rollback")
                    self.assertIs(pending["restore_required"], True)
                    self.assertEqual(pending["candidate"], str(candidate))
                    self.assertEqual(pending["previous"], str(previous))

    def test_corrupt_and_newer_state_refuse_without_overwriting(self):
        for contents in ("not json", json.dumps({"schema_version": "self_update_state/v99"})):
            with self.subTest(contents=contents), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                state_path = root / "self-update.json"
                _ = state_path.write_text(contents)
                with self.assertRaises(OmhError):
                    _ = self._run(root, args, plan, self._runner())
                self.assertEqual(state_path.read_text(), contents)
                self._assert_pair(root)

    def test_invalid_marker_candidates_never_delete_or_reconcile_outside_generations(self):
        for name, candidate in (
            ("traversal", "{root}/generations/../outside"),
            ("absolute", "{outside}"),
            ("symlink", "{link}"),
        ):
            with self.subTest(name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                previous = (root / "current").resolve()
                outside = root / "outside"
                outside.mkdir()
                sentinel = outside / "sentinel"
                _ = sentinel.write_text("do not delete")
                link = root / "generations" / "escaped"
                link.symlink_to(outside, target_is_directory=True)
                raw_candidate = candidate.format(root=root, outside=outside, link=link)
                state = _read_json_object(root / "self-update.json")
                state["activation_in_progress"] = {
                    "candidate": raw_candidate,
                    "previous": str(previous),
                    "phase": "pre_switch",
                }
                atomic_write_json(root / "self-update.json", state, private=True)
                error = None
                try:
                    _ = self._run(root, args, plan, self._runner(failure="pip"))
                except OmhError as exc:
                    error = exc
                self.assertTrue(sentinel.exists(), "invalid marker candidate deleted an external sentinel")
                self.assertIsInstance(error, OmhError, "invalid marker candidate was reconciled instead of refused")

    def test_interrupted_current_alias_is_confined_before_identity_comparison(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy, _args, _plan = self._fixture(root, pointer=True)
            previous = (root / "current").resolve()
            candidate = root / "generations" / "candidate"
            candidate.mkdir()
            outside_alias = root / "outside-alias"
            outside_alias.symlink_to(candidate, target_is_directory=True)
            (root / "current").unlink()
            (root / "current").symlink_to(outside_alias, target_is_directory=True)
            state = _read_json_object(root / "self-update.json")
            state["activation_in_progress"] = {
                "candidate": str(candidate),
                "previous": str(previous),
                "phase": "post_switch",
            }

            with self.assertRaisesRegex(OmhError, "current pointer target"):
                _ = self_update_state.interrupted_activation(root, state)

            self.assertTrue(candidate.is_dir())
            self.assertTrue(legacy.is_dir())

    def test_invalid_persisted_generation_entries_never_switch_or_reenter(self):
        mutations: tuple[tuple[str, StateMutator], ...] = (
            (
                "mismatched-id-path",
                lambda state, _outside, _link: _object(state["active"], "active").update(
                    id="wrong-id"
                ),
            ),
            (
                "mismatched-path",
                lambda state, outside, _link: _object(state["active"], "active").update(
                    path=str(outside.parent / "generations" / "other")
                ),
            ),
            ("external-active", lambda state, outside, _link: state.update(active=self._entry(outside))),
            (
                "external-previous",
                lambda state, outside, _link: state.update(
                    previous_known_good=self._entry(outside)
                ),
            ),
            ("symlink-active", lambda state, _outside, link: state.update(active=self._entry(link))),
            (
                "external-pointer",
                lambda state, _outside, _link: _object(state["pointer"], "pointer").update(
                    target="../../outside"
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                outside = root / "outside"
                (outside / "venv" / "bin").mkdir(parents=True)
                sentinel = outside / "venv" / "bin" / "sentinel"
                _ = sentinel.write_text("do not execute")
                link = root / "generations" / "escaped-active"
                link.symlink_to(outside, target_is_directory=True)
                state_path = root / "self-update.json"
                state = _read_json_object(state_path)
                state["previous_known_good"] = self._entry((root / "current").resolve())
                mutate(state, outside, link)
                atomic_write_json(state_path, state, private=True)
                args.recover_known_good = True
                calls: list[list[str]] = []
                runner = self._runner()

                def recording_runner(
                    command: list[str],
                    *,
                    text: Literal[True],
                    stdout: int | None,
                    stderr: int | None,
                    env: dict[str, str] | None,
                    timeout: float | None,
                ) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return runner(
                        command, text=text, stdout=stdout, stderr=stderr, env=env, timeout=timeout
                    )

                error = None
                try:
                    _ = self._run(root, args, plan, recording_runner)
                except OmhError as exc:
                    error = exc
                self.assertTrue(sentinel.exists(), "invalid persisted entry reached an external generation")
                self.assertEqual(calls, [], "invalid persisted generation entry was re-entered")
                self.assertIsInstance(error, OmhError, "invalid persisted generation entry was switched or re-entered")

    def test_malformed_marker_refuses_without_overwriting_state(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            state_path = root / "self-update.json"
            state = _read_json_object(state_path)
            state["activation_in_progress"] = {"candidate": str(root / "outside")}
            atomic_write_json(state_path, state, private=True)
            before = state_path.read_bytes()
            with self.assertRaises(OmhError):
                _ = self._run(root, args, plan, self._runner())
            self.assertEqual(state_path.read_bytes(), before)

    def test_gc_refuses_invalid_state_without_deleting_generation_entries(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            stale = root / "generations" / "stale"
            stale.mkdir(parents=True)
            state = {"active": self._entry(outside), "previous_known_good": None}
            result: GarbageCollectionResult = {"cleanup": {"collected": []}}
            with self.assertRaises(OmhError):
                collect_garbage(root, state, result, running_generation=None)
            self.assertTrue(stale.exists(), "GC deleted an in-root generation from invalid state")

    def test_known_good_recovery_is_reentered_idempotent_and_refuses_missing_target(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            self.assertTrue(self._run(root, args, plan, self._runner())["ok"])
            restored = _object(
                _read_json_object(root / "self-update.json")["previous_known_good"],
                "previous known good",
            )
            restored_path = _text(restored["path"], "previous known-good path")
            args.recover_known_good = True
            first = self._run(root, args, plan, self._runner())
            second = self._run(root, args, plan, self._runner())
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            assert "selected" in first["recovery"]
            assert "selected" in second["recovery"]
            self.assertEqual(first["recovery"]["selected"], second["recovery"]["selected"])
            self.assertEqual((root / "current").resolve(), Path(restored_path).resolve())
            import shutil
            shutil.rmtree(restored_path)
            with self.assertRaisesRegex(OmhError, "no retained previous"):
                _ = self._run(root, args, plan, self._runner())

    def test_gc_keeps_active_previous_bootstrap_and_running_generation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, _args, _plan = self._fixture(root, pointer=True)
            active = root / "generations" / "active"
            previous = root / "generations" / "previous"
            running = root / "generations" / "running"
            stale = root / "generations" / "stale"
            for generation in (active, previous, running, stale):
                generation.mkdir(parents=True, exist_ok=True)
            state = {"active": self._entry(active), "previous_known_good": self._entry(previous)}
            result: GarbageCollectionResult = {"cleanup": {"collected": []}}
            with patch.object(sys, "executable", str(running / "venv" / "bin" / "python")):
                collect_garbage(root, state, result, running_generation=running)
            self.assertTrue(active.exists())
            self.assertTrue(previous.exists())
            self.assertTrue(running.exists())
            self.assertFalse(stale.exists())

    def _gateway_gc(self, root: Path, gateway_starts: list[float]) -> dict[str, Path]:
        _legacy, _args, _plan = self._fixture(root, pointer=True)
        generations = {name: root / "generations" / name for name in ("g0", "g1", "g2", "g3")}
        for generation in generations.values():
            generation.mkdir(parents=True, exist_ok=True)
        activated = {"g0": "2026-10-29T12:00:00Z", "g1": "2026-10-30T13:06:00Z", "g2": "2026-10-30T13:13:00Z", "g3": "2026-10-30T14:00:00Z"}
        state: dict[str, JsonValue] = {
            "active": self._entry(generations["g3"]),
            "previous_known_good": self._entry(generations["g2"]),
            "activations": [{"id": name, "activated_at": stamp} for name, stamp in activated.items()],
        }
        result: GarbageCollectionResult = {"cleanup": {"collected": []}}
        collect_garbage(root, state, result, running_generation=None, gateway_starts=gateway_starts)
        return generations

    def test_gc_keeps_the_generation_current_at_a_recorded_gateway_start(self):
        # The gateway started between g0 and g1, so it still serves g0; g1 was
        # superseded after that start and nothing holds it.
        start = datetime.fromisoformat("2026-10-29T17:00:52+00:00").timestamp()
        with TemporaryDirectory() as temporary:
            generations = self._gateway_gc(Path(temporary), [start])
            self.assertTrue(generations["g0"].exists(), "GC deleted the generation a running gateway serves")
            self.assertFalse(generations["g1"].exists())
            self.assertTrue(generations["g2"].exists())
            self.assertTrue(generations["g3"].exists())

    def test_gc_without_a_recorded_gateway_start_keeps_only_active_and_previous(self):
        with TemporaryDirectory() as temporary:
            generations = self._gateway_gc(Path(temporary), [])
            self.assertFalse(generations["g0"].exists())
            self.assertFalse(generations["g1"].exists())
            self.assertTrue(generations["g2"].exists())
            self.assertTrue(generations["g3"].exists())

    def test_update_keeps_the_generation_a_gateway_started_on_until_it_restarts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            self.assertTrue(self._run(root, args, plan, self._runner())["ok"])
            state = _read_json_object(root / "self-update.json")
            held = root / "generations" / _text(_object(state["active"], "active")["id"], "active id")
            hermes_home = root / "hermes"
            _ = (hermes_home / "gateway.pid").write_text(json.dumps({"pid": 1, "hermes_home": str(hermes_home)}))
            _ = (hermes_home / "gateway-starts.log").write_text(f"{time.time()!r}\n")
            with patch.object(self_update_state, "now", return_value="2099-01-01T00:00:00Z"):
                for _ in range(2):
                    self.assertTrue(self._run(root, args, plan, self._runner())["ok"])
            self.assertTrue(held.exists(), "update deleted the generation the gateway started on")
            self.assertNotEqual((root / "current").resolve(), held.resolve())
            # A start recorded after the later activations releases it.
            _ = (hermes_home / "gateway-starts.log").write_text(f"{datetime(2099, 1, 2, tzinfo=UTC).timestamp()!r}\n")
            self.assertTrue(self._run(root, args, plan, self._runner())["ok"])
            self.assertFalse(held.exists())

    def test_gc_never_reads_an_unstamped_first_activation_as_covering_an_older_gateway(self):
        # The owner machine on 2026-11-02: the first update that kept a history
        # recorded the then-active generation with no time. A gateway started
        # on 10-30 still served the 10-27 generation; reading the unstamped row
        # as "before every start" held the 10-31 one and deleted 10-27.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, _args, _plan = self._fixture(root, pointer=True)
            names = {
                "served": "20261027024653159707-aaaaaaaaaa",
                "after_start": "20261030120000000000-cccccccccc",
                "unstamped": "20261031021314000000-bbbbbbbbbb",
                "active": "20261102020057175032-edfca25300",
            }
            generations = {key: root / "generations" / name for key, name in names.items()}
            for generation in generations.values():
                generation.mkdir(parents=True, exist_ok=True)
            state: dict[str, JsonValue] = {
                "active": self._entry(generations["active"]),
                "previous_known_good": self._entry(generations["unstamped"]),
                "activations": [
                    {"id": names["unstamped"], "activated_at": None},
                    {"id": names["active"], "activated_at": "2026-11-02T02:01:00Z"},
                ],
            }
            start = datetime.fromisoformat("2026-10-29T17:00:50+00:00").timestamp()
            result: GarbageCollectionResult = {"cleanup": {"collected": []}}
            collect_garbage(root, state, result, running_generation=None, gateway_starts=[start])
            self.assertTrue(generations["served"].exists(), "GC deleted the generation an older gateway serves")
            self.assertTrue(generations["unstamped"].exists())
            self.assertTrue(generations["active"].exists())
            # Created after that start, so provably not the one it serves.
            self.assertFalse(generations["after_start"].exists())
            self.assertIn("2026-10-29T17:00:50Z", result["cleanup"].get("reason", ""))
            self.assertIn("no recorded activation says which one that gateway serves", result["cleanup"].get("reason", ""))

    def test_gc_keeps_by_creation_time_only_for_a_start_the_history_cannot_name(self):
        # Before every stamped activation (g0 at 10-29 12:00): only generations
        # created after the start are provably not the one it serves. The
        # fixture's ids carry no creation stamp, so all of them stay.
        with TemporaryDirectory() as temporary:
            early = datetime.fromisoformat("2026-10-29T11:00:00+00:00").timestamp()
            generations = self._gateway_gc(Path(temporary), [early])
            self.assertTrue(all(generation.exists() for generation in generations.values()))

    def test_human_update_says_why_generations_were_kept(self):
        kept = {"ok": True, "phase": "cleanup", "cleanup": {"collected": [], "reason": "kept generations created before the Hermes gateway start recorded at 2026-10-29T17:00:50Z"}}
        output = io.StringIO()
        with (
            patch("omh.commands.setup._command_package_self_update_plan", return_value={"should_update": True, "method": "installer"}),
            patch("omh.install.self_update.run_installer_self_update", return_value=kept),
            contextlib.redirect_stdout(output),
        ):
            status = setup_commands.cmd_update(Namespace(json=False))
        self.assertEqual(status, 0)
        self.assertIn("  note: kept generations created before the Hermes gateway start recorded at 2026-10-29T17:00:50Z", output.getvalue())

    def test_gc_keeps_a_generation_an_open_omh_process_holds(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, _args, _plan = self._fixture(root, pointer=True)
            active = root / "generations" / "active"
            tui = root / "generations" / "tui"
            for generation in (active, tui):
                (generation / "venv").mkdir(parents=True, exist_ok=True)
            state: dict[str, JsonValue] = {"active": self._entry(active), "previous_known_good": None}
            with generation_hold.hold_running_generation(str(tui / "venv")) as held:
                self.assertEqual(held, "tui")
                result: GarbageCollectionResult = {"cleanup": {"collected": []}}
                collect_garbage(root, dict(state), result, running_generation=None)
                self.assertTrue(tui.exists(), "GC deleted the generation an open OMH TUI imports from")
            self.assertEqual(list((root / generation_hold.HOLDS_DIRNAME).iterdir()), [])
            result = {"cleanup": {"collected": []}}
            collect_garbage(root, dict(state), result, running_generation=None)
            self.assertFalse(tui.exists())

    def test_gc_keeps_by_the_latest_of_several_unmatched_starts(self):
        # Two gateways (two profiles) whose starts no stamped activation
        # precedes: a generation created between them may be the one the later
        # gateway serves, so the later start decides.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, _args, _plan = self._fixture(root, pointer=True)
            names = {
                "between": "20261029120000000000-aaaaaaaaaa",
                "after_both": "20261030120000000000-bbbbbbbbbb",
                "active": "20261102020057175032-edfca25300",
            }
            generations = {key: root / "generations" / name for key, name in names.items()}
            for generation in generations.values():
                generation.mkdir(parents=True, exist_ok=True)
            state: dict[str, JsonValue] = {
                "active": self._entry(generations["active"]),
                "previous_known_good": None,
                "activations": [{"id": names["active"], "activated_at": "2026-11-02T02:01:00Z"}],
            }
            starts = [
                datetime.fromisoformat("2026-10-29T00:00:00+00:00").timestamp(),
                datetime.fromisoformat("2026-10-29T18:00:00+00:00").timestamp(),
            ]
            result: GarbageCollectionResult = {"cleanup": {"collected": []}}
            collect_garbage(root, state, result, running_generation=None, gateway_starts=starts)
            self.assertTrue(generations["between"].exists(), "GC judged by the earlier start")
            self.assertFalse(generations["after_both"].exists())
            self.assertIn("2026-10-29T18:00:00Z", result["cleanup"].get("reason", ""))

    def _hold_fixture(self, root: Path) -> tuple[Path, Path]:
        generation = root / "generations" / "20261102020057175032-edfca25300"
        (generation / "venv").mkdir(parents=True)
        return generation, root / generation_hold.HOLDS_DIRNAME / f".{generation.name}.{os.getpid()}.lock"

    def test_a_hold_retries_past_a_gc_probe_that_has_its_file_locked(self):
        import threading

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            generation, sidecar = self._hold_fixture(root)
            locked = threading.Event()

            def gc_probe() -> None:
                # What `held_generations` does to every file it lists, briefly.
                with file_lock(sidecar.with_name(sidecar.name[1:-len(".lock")]), timeout_seconds=0.0):
                    locked.set()
                    time.sleep(0.2)

            probe = threading.Thread(target=gc_probe)
            probe.start()
            self.assertTrue(locked.wait(2))
            try:
                with generation_hold.hold_running_generation(str(generation / "venv")) as held:
                    self.assertEqual(held, generation.name)
                    self.assertEqual(generation_hold.held_generations(root), {generation.name})
            finally:
                probe.join()

    @unittest.skipIf(os.name == "nt", "Windows will not unlink a file a holder has open")
    def test_a_hold_on_a_file_a_gc_probe_unlinked_is_retaken(self):
        from omh.system import local_store

        real_acquire = local_store._acquire_os_file_lock
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            generation, sidecar = self._hold_fixture(root)
            calls = 0

            def unlink_first(handle, path, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    # A GC probe took and removed the file before this lock.
                    sidecar.unlink()
                return real_acquire(handle, path, **kwargs)

            with patch.object(local_store, "_acquire_os_file_lock", unlink_first), \
                    generation_hold.hold_running_generation(str(generation / "venv")) as held:
                self.assertEqual(held, generation.name)
                self.assertTrue(sidecar.exists(), "the hold locked a file nobody can see")
            self.assertEqual(calls, 2)

    def test_a_hold_that_cannot_be_taken_says_so(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            generation, _sidecar = self._hold_fixture(root)
            (root / generation_hold.HOLDS_DIRNAME).write_text("not a directory")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), \
                    generation_hold.hold_running_generation(str(generation / "venv")) as held:
                self.assertEqual(held, "")
            self.assertIn(f"could not hold generation {generation.name}", stderr.getvalue())

    def test_a_hold_left_by_a_process_that_died_holds_nothing(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            holds = root / generation_hold.HOLDS_DIRNAME
            holds.mkdir()
            stale = holds / ".20261027024653159707-aaaaaaaaaa.4242.lock"
            stale.touch()
            self.assertEqual(generation_hold.held_generations(root), set())
            self.assertFalse(stale.exists())

    def test_a_process_outside_a_generation_takes_no_hold(self):
        with TemporaryDirectory() as temporary, generation_hold.hold_running_generation(temporary) as held:
            self.assertEqual(held, "")
            self.assertFalse((Path(temporary) / generation_hold.HOLDS_DIRNAME).exists())

    def test_no_launcher_and_platform_link_failure_are_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True, launcher=False)
            result = self._run(root, args, plan, self._runner())
            self.assertTrue(result["ok"])
            self.assertEqual(result["activation"].get("launcher"), "absent_manual_instruction")
            self.assertIn(
                (root / "current" / "skills").as_posix(),
                (root / "hermes" / "config.yaml").read_text().replace("\\", "/"),
            )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "generations" / "candidate"
            target.mkdir(parents=True)
            with patch.object(os, "symlink", side_effect=OSError("no junction")):
                with self.assertRaisesRegex(OmhError, "cannot atomically"):
                    switch_current(root, target, platform=SelfUpdatePlatform.host(is_windows=False))
            self.assertFalse((root / "current").exists())

    def test_windows_contract_activates_a_pointer_and_rewrites_the_shim(self):
        """The named platform seam must work without changing ``os.name``."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = root / "generations" / "previous"
            candidate = root / "generations" / "candidate"
            previous.mkdir(parents=True)
            candidate.mkdir()
            calls: list[tuple[list[str], JunctionInvocation]] = []

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                calls.append((command, _junction_invocation(
                    shell=shell,
                    cwd=cwd,
                    env=env,
                    text=text,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                )))
                link = Path(env["OMH_JUNCTION_LINK"])
                target = Path(env["OMH_JUNCTION_TARGET"])
                self.assertTrue(target.is_absolute(), "PowerShell 7 rejects relative junction targets")
                link.symlink_to(target, target_is_directory=True)
                return subprocess.CompletedProcess(command, 0, "", "")

            platform = SelfUpdatePlatform.windows(junction_runner)
            switch_current(root, previous, platform=platform)
            self._assert_same_path(pointer_target(root, platform=platform), previous)
            bootstrap = root / "generations" / "bootstrap-legacy"
            bootstrap.mkdir()
            platform.create_directory_link(root, bootstrap / "venv", previous)
            platform.create_directory_link(root, bootstrap / "skills", previous)
            self.assertEqual((bootstrap / "venv").resolve(), previous.resolve())
            self.assertEqual((bootstrap / "skills").resolve(), previous.resolve())
            directory = root / "bin"
            directory.mkdir()
            shim = directory / "omh.cmd"
            _ = shim.write_text("old", newline="")
            migration_state: dict[str, JsonValue] = {
                "active": self._entry(previous),
                "migration": {"status": "pending"},
            }
            paths = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")
            with patch.dict(os.environ, {"OMH_BIN_DIR": str(directory)}, clear=False):
                self_update_state.migrate_legacy(root, migration_state, paths, platform)
            expected = str(root).replace("/", "\\") + "\\current\\venv\\Scripts\\omh.exe"
            self.assertIn(expected, shim.read_text())
            switch_current(root, candidate, platform=platform)
            switch_current(root, previous, platform=platform)
            self._assert_same_path(pointer_target(root, platform=platform), previous)
            self.assertTrue(all(call[0][:5] == ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"] for call in calls))
            self.assertTrue(all(call[1]["shell"] is False for call in calls))
            self.assertTrue(all(call[1]["timeout"] > 0 for call in calls))

    def test_pointer_state_uses_cross_platform_posix_relative_target(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "generations" / "candidate"
            state: dict[str, object] = {}

            with patch.object(os.path, "relpath", return_value=r"generations\candidate"):
                record_pointer(state, root, candidate)

            self.assertEqual(
                state["pointer"],
                {"path": str(root / "current"), "target": "generations/candidate"},
            )

    def test_windows_pointer_swap_never_replaces_an_existing_junction_in_place(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = root / "generations" / "previous"
            candidate = root / "generations" / "candidate"
            previous.mkdir(parents=True)
            candidate.mkdir()

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                _ = shell, cwd, text, stdout, stderr, timeout
                link = Path(env["OMH_JUNCTION_LINK"])
                target = link.parent / env["OMH_JUNCTION_TARGET"]
                link.symlink_to(target, target_is_directory=True)
                return subprocess.CompletedProcess(command, 0, "", "")

            real_rename = os.rename

            def windows_replace(source: StrPath, destination: StrPath) -> None:
                destination_path = Path(destination)
                if destination_path == root / "current" and (
                    destination_path.exists() or destination_path.is_symlink()
                ):
                    raise PermissionError("Windows cannot replace an existing junction in place")
                real_rename(source, destination)

            platform = SelfUpdatePlatform.windows(junction_runner)
            with patch("omh.install.self_update_platform.os.replace", side_effect=windows_replace):
                platform.replace_current(root, previous)
                platform.replace_current(root, candidate)

            self._assert_same_path(pointer_target(root, platform=platform), candidate)
            self.assertFalse(any(root.glob(".current.*")))

    def test_windows_pointer_swap_restores_previous_after_second_rename_failure(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = root / "generations" / "previous"
            candidate = root / "generations" / "candidate"
            previous.mkdir(parents=True)
            candidate.mkdir()

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                _ = shell, cwd, text, stdout, stderr, timeout
                link = Path(env["OMH_JUNCTION_LINK"])
                target = link.parent / env["OMH_JUNCTION_TARGET"]
                link.symlink_to(target, target_is_directory=True)
                return subprocess.CompletedProcess(command, 0, "", "")

            platform = SelfUpdatePlatform.windows(junction_runner)
            platform.replace_current(root, previous)
            real_replace = os.replace
            moves: list[tuple[Path, Path]] = []

            def fail_candidate_move(source: StrPath, destination: StrPath) -> None:
                source_path = Path(source)
                destination_path = Path(destination)
                moves.append((source_path, destination_path))
                if source_path.suffix == ".tmp" and destination_path == root / "current":
                    raise PermissionError("candidate rename failed")
                real_replace(source, destination)

            with (
                patch("omh.install.self_update_platform.os.replace", side_effect=fail_candidate_move),
                self.assertRaisesRegex(OmhError, "candidate rename failed"),
            ):
                platform.replace_current(root, candidate)

            self.assertTrue(any(destination.suffix == ".previous" for _source, destination in moves))
            self._assert_same_path(pointer_target(root, platform=platform), previous)
            self.assertFalse(any(root.glob(".current.*")))

    def test_windows_junction_creation_failure_keeps_the_previous_pointer(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = root / "generations" / "previous"
            candidate = root / "generations" / "candidate"
            previous.mkdir(parents=True)
            candidate.mkdir()

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                _ = shell, cwd, text, stdout, stderr, timeout
                target = Path(env["OMH_JUNCTION_TARGET"])
                if target.name == "candidate":
                    return subprocess.CompletedProcess(command, 1, "", "access denied")
                Path(env["OMH_JUNCTION_LINK"]).symlink_to(target, target_is_directory=True)
                return subprocess.CompletedProcess(command, 0, "", "")

            platform = SelfUpdatePlatform.windows(junction_runner)
            switch_current(root, previous, platform=platform)
            with self.assertRaisesRegex(OmhError, "directory junction"):
                switch_current(root, candidate, platform=platform)
            self._assert_same_path(pointer_target(root, platform=platform), previous)
            self.assertFalse(any(root.glob(".current.*.tmp")))

    def test_windows_junction_command_keeps_path_bytes_out_of_program_text(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "A&B%TEMP%^!()"
            link = root / ".current.A&B%TEMP%^!().tmp"
            target = root / "generations" / "A&B%TEMP%^!()"
            calls: list[tuple[list[str], JunctionInvocation]] = []

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                calls.append((command, _junction_invocation(
                    shell=shell,
                    cwd=cwd,
                    env=env,
                    text=text,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                )))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.dict(os.environ, {"PRESERVED": "yes"}, clear=True):
                SelfUpdatePlatform.windows(junction_runner).create_directory_link(root, link, target)

            command, kwargs = calls[0]
            program_text = subprocess.list2cmdline(command)
            self.assertNotIn("A&B%TEMP%^!()", "\n".join(command))
            self.assertNotIn("A&B%TEMP%^!()", program_text)
            self.assertEqual(kwargs["env"], {
                "PRESERVED": "yes",
                "OMH_JUNCTION_LINK": str(link),
                "OMH_JUNCTION_TARGET": str(target.absolute()),
            })
            self.assertEqual(command[0], "powershell.exe")
            self.assertEqual(command[1:4], ["-NoLogo", "-NoProfile", "-NonInteractive"])
            self.assertTrue(kwargs["shell"] is False)
            self.assertEqual(kwargs["cwd"], str(link.parent))
            self.assertGreater(kwargs["timeout"], 0)

    def test_windows_junction_absolutizes_relative_target_without_resolving_aliases(self):
        with TemporaryDirectory() as temporary:
            # The process cwd is already canonical (macOS reports /var/... as /private/var/...),
            # so anchor the fixture there; the alias under test is generation-alias below.
            root = Path(temporary).resolve()
            generations = root / "generations"
            generations.mkdir()
            (generations / "candidate").mkdir()
            alias = root / "generation-alias"
            alias.symlink_to(generations, target_is_directory=True)
            target = Path("generation-alias") / "candidate"
            targets: list[str] = []

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                targets.append(env["OMH_JUNCTION_TARGET"])
                return subprocess.CompletedProcess(command, 0, "", "")

            # A relative input is relative to the process, not the new link.
            # Keep cwd on the temporary drive even when Windows CI checks the
            # repository out on a different drive from its temporary directory.
            with contextlib.chdir(root):
                SelfUpdatePlatform.windows(junction_runner).create_directory_link(root, root / "link", target)

            self.assertEqual(targets, [str(alias / "candidate")])
            self.assertTrue(Path(targets[0]).is_absolute())

    def test_windows_junction_does_not_compute_a_cross_drive_relative_path(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls: list[str] = []

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                calls.append(env["OMH_JUNCTION_TARGET"])
                return subprocess.CompletedProcess(command, 0, "", "")

            # Windows relpath raises across drives; junctions permit that target.
            with patch.object(os.path, "relpath", side_effect=ValueError("path is on a different drive")):
                SelfUpdatePlatform.windows(junction_runner).create_directory_link(root, root / "link", root / "target")

            self.assertEqual(calls, [str(root / "target")])

    def test_posix_directory_link_keeps_the_relative_payload(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "generations" / "candidate"
            target.mkdir(parents=True)
            (target / "sentinel").write_text("candidate", encoding="utf-8")
            platform = SelfUpdatePlatform.host(is_windows=False)

            platform.create_directory_link(root, root / "current", target)

            self.assertEqual(os.readlink(root / "current").replace("\\", "/"), "generations/candidate")
            self.assertEqual((root / "current" / "sentinel").read_text(encoding="utf-8"), "candidate")

    def test_windows_broken_junction_is_removed_even_without_a_target(self):
        broken = Path("broken-junction")
        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(Path, "is_symlink", return_value=False),
            patch.object(Path, "is_junction", return_value=True, create=True),
            patch.object(Path, "rmdir") as remove,
            patch.object(Path, "unlink", side_effect=AssertionError("junctions must be removed with rmdir")),
        ):
            remove_directory_link(broken)
        remove.assert_called_once_with()

    def test_windows_post_activation_failure_restores_the_previous_pair(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy, args, plan = self._fixture(root, pointer=True)
            previous = pointer_target(root)
            assert previous is not None
            directory = root / "bin"
            (directory / "omh").unlink()
            shim = directory / "omh.cmd"
            _ = shim.write_text('"legacy" %*\r\n', newline="")
            junctions: list[tuple[list[str], JunctionInvocation]] = []

            def junction_runner(
                command: list[str],
                *,
                shell: Literal[False],
                cwd: str,
                env: dict[str, str],
                text: Literal[True],
                stdout: int,
                stderr: int,
                timeout: float,
            ) -> subprocess.CompletedProcess[str]:
                junctions.append((command, _junction_invocation(
                    shell=shell,
                    cwd=cwd,
                    env=env,
                    text=text,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=timeout,
                )))
                Path(env["OMH_JUNCTION_LINK"]).symlink_to(
                    env["OMH_JUNCTION_TARGET"], target_is_directory=True
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            platform = SelfUpdatePlatform.windows(junction_runner)
            with patch.dict(os.environ, {"OMH_VENV_DIR": str(legacy), "OMH_BIN_DIR": str(directory)}, clear=False):
                platform.rewrite_command_shim(shim, root)
                result = run_installer_self_update(
                    args, plan, runner=self._runner(failure="post"), platform=platform
                )
            self.assertEqual(result["activation"]["status"], "ok")
            self.assertTrue(result["rollback"]["performed"])
            self._assert_same_path(pointer_target(root, platform=platform), previous)
            self.assertIn("\\current\\venv\\Scripts\\omh.exe", shim.read_text())
            self.assertIn(
                (root / "current" / "skills").as_posix(),
                (root / "hermes" / "config.yaml").read_text().replace("\\", "/"),
            )
            self.assertEqual(len(junctions), 2)

    def test_json_and_human_results_never_claim_success_before_post_activation(self):
        for failure in ("venv", "pip", "import", "pack", "post", "timeout"):
            with self.subTest(failure), TemporaryDirectory() as temporary:
                root = Path(temporary)
                _legacy, args, plan = self._fixture(root, pointer=True)
                result = self._run(root, args, plan, self._runner(failure=failure))
                self.assertFalse(result["ok"])
                self.assertNotEqual(result["post_activation"]["status"], "ok")
        output = io.StringIO()
        failed = {
            "ok": False,
            "phase": "post_activation",
            "post_activation": {"status": "failed", "reason": "Traceback line\nerror: local modifications detected; rerun with --force"},
            "rollback": {"performed": True, "restored": "bootstrap-legacy"},
        }
        with (
            patch("omh.commands.setup._command_package_self_update_plan", return_value={"should_update": True, "method": "installer"}),
            patch("omh.install.self_update.run_installer_self_update", return_value=failed),
            contextlib.redirect_stdout(output),
        ):
            status = setup_commands.cmd_update(Namespace(json=False))
        self.assertEqual(status, 1)
        printed = output.getvalue()
        self.assertIn("stopped during post_activation", printed)
        # The phase alone sent people to the bug tracker; the line names the cause.
        self.assertIn("reason: error: local modifications detected; rerun with --force", printed)
        self.assertNotIn("Traceback line", printed)
        self.assertIn("rolled back to generation bootstrap-legacy", printed)
        self.assertIn("rerun `omh update`", printed)
        self.assertNotIn("update complete", printed.lower())
        bare = io.StringIO()
        with (
            patch("omh.commands.setup._command_package_self_update_plan", return_value={"should_update": True, "method": "installer"}),
            patch("omh.install.self_update.run_installer_self_update", return_value={"ok": False, "phase": "staging"}),
            contextlib.redirect_stdout(bare),
        ):
            bare_status = setup_commands.cmd_update(Namespace(json=False))
        self.assertEqual(bare_status, 1)
        self.assertIn("stopped during staging", bare.getvalue())
        self.assertNotIn("reason:", bare.getvalue())

    def test_reentry_judges_the_candidate_pack_by_its_own_manifest(self):
        # The home manifest describes the active generation's pack. Rendering
        # the candidate into a new generation and then judging it by that
        # manifest turned every catalog change since the last install into a
        # "local modification" and rolled the update back (reported on 2.0.1).
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")
            _ = _install_skill_pack(home)
            manifest_path = root / "omh" / "manifest.json"
            recorded = _read_json_object(manifest_path)
            self.assertEqual(recorded["skills_dir"], str(root / "omh" / "skills"))
            candidate = root / "generations" / "candidate" / "skills"
            smoke_home = OmhPaths(omh_home=root / "smoke-omh", hermes_home=root / "smoke-hermes", managed_skills_dir=candidate)
            _ = _install_skill_pack(smoke_home)
            # The active generation was installed from an older catalog.
            skills = _array(recorded["skills"], "manifest skills")
            first_skill = _object(skills[0], "first manifest skill")
            first_skill["sha256"] = "0" * 64
            _ = manifest_path.write_text(json.dumps(recorded))
            reentry = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes", managed_skills_dir=candidate)
            written = _install_skill_pack(reentry)
            self.assertEqual(written["skills_dir"], str(candidate))
            self.assertEqual(_read_json_object(manifest_path)["skills_dir"], str(candidate))
            # The same manifest still guards the directory it does describe.
            _ = (root / "omh" / "skills" / Path(_text(first_skill["path"], "first skill path"))).write_text("edited")
            _ = manifest_path.write_text(json.dumps(recorded))
            with self.assertRaisesRegex(OmhError, "local modifications detected"):
                _ = _install_skill_pack(home)
            # A bootstrap generation reaching the legacy pack through a link is
            # the same pack, so its edits are still seen.
            bootstrap = root / "generations" / "bootstrap-legacy"
            bootstrap.mkdir(parents=True)
            (bootstrap / "skills").symlink_to(root / "omh" / "skills", target_is_directory=True)
            linked = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes", managed_skills_dir=bootstrap / "skills")
            with self.assertRaisesRegex(OmhError, "local modifications detected"):
                _ = _install_skill_pack(linked)

    def _older_pack_home(self, root: Path) -> Path:
        """A real legacy pack whose manifest an older catalog wrote."""
        _ = _install_skill_pack(OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes"))
        manifest_path = root / "omh" / "manifest.json"
        recorded = _read_json_object(manifest_path)
        skills = _array(recorded["skills"], "manifest skills")
        first_skill = _object(skills[0], "first manifest skill")
        first_skill["sha256"] = "0" * 64
        _ = _ = manifest_path.write_text(json.dumps(recorded))
        return manifest_path

    def _live_update_runner(self, _root: Path) -> Runner:
        """Fake venv/pip/import/version; run the pack smoke and re-entry through the real CLI."""
        fake = self._runner()

        def run(
            command: list[str],
            *,
            text: Literal[True],
            stdout: int | None,
            stderr: int | None,
            env: dict[str, str] | None,
            timeout: float | None,
        ) -> subprocess.CompletedProcess[str]:
            if "update" not in command:
                return fake(
                    command, text=text, stdout=stdout, stderr=stderr, env=env, timeout=timeout
                )
            argv = command[command.index("omh.cli") + 1 :]
            with patch.dict(os.environ, dict(_runner_environment(env)), clear=True):
                status, cli_stdout, cli_stderr = run_cli(argv, output_json=False)
            return subprocess.CompletedProcess(command, status, cli_stdout, cli_stderr)

        return run

    def test_staged_transaction_completes_when_the_home_manifest_predates_the_candidate(self):
        # The reported 2.0.1 rollback, end to end: the smoke renders the candidate
        # pack into its generation, and the re-entered `omh update` against the
        # real home must accept that pack even though the home manifest still
        # carries the hashes of the pack the active generation was installed from.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            manifest_path = self._older_pack_home(root)
            argv = ["omh", "--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "update", "--no-interactive"]
            with patch.object(sys, "argv", argv):
                result = self._run(root, args, plan, self._live_update_runner(root))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["post_activation"]["status"], "ok")
            candidate = Path(result["candidate"]["path"])
            self.assertEqual(_read_json_object(manifest_path)["skills_dir"], str(candidate / "skills"))
            self._assert_pair(root, candidate)

    def test_every_generation_interpreter_call_ignores_the_working_directory(self):
        # The owner's 2.0.2 -> "2.0.1" update: `omh update` was run from inside
        # a source checkout, whose top-level `omh/` shim sat at `sys.path[0]`
        # for every `python -m omh.cli` the transaction spawned. The stale
        # checkout judged the fresh candidate, refused it, rolled back, and
        # stamped the manifest with its own version. `-P` keeps the smoke and
        # both re-entries on the generation's own package.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            commands: list[list[str]] = []
            fake = self._runner(version="1.0.7\n")

            def run(
                command: list[str],
                *,
                text: Literal[True],
                stdout: int | None,
                stderr: int | None,
                env: dict[str, str] | None,
                timeout: float | None,
            ) -> subprocess.CompletedProcess[str]:
                commands.append(list(command))
                return fake(
                    command, text=text, stdout=stdout, stderr=stderr, env=env, timeout=timeout
                )

            result = self._run(root, args, plan, run)
            self.assertTrue(result["ok"], result)
            omh_calls = [command for command in commands if "omh.cli" in " ".join(command)]
            self.assertEqual(len(omh_calls), 4, omh_calls)  # import, version, pack smoke, re-entry
            for command in omh_calls:
                self.assertEqual(command[1], "-P", command)
            self.assertEqual(omh_calls[0][1:4], ["-P", "-c", "import omh.cli"])
            self.assertEqual(omh_calls[-1][1:4], ["-P", "-m", "omh.cli"])
            self.assertIn("--command-package-updated", omh_calls[-1])

    def test_dash_p_is_what_keeps_a_checkout_shim_out_of_the_interpreter(self):
        # The mechanism itself, on the real interpreter: a directory holding an
        # `omh/cli.py` wins `python -m omh.cli` when it is the cwd, and loses
        # once `-P` drops the cwd from sys.path.
        with TemporaryDirectory() as temporary:
            shadow = Path(temporary) / "omh"
            shadow.mkdir()
            _ = (shadow / "__init__.py").write_text("")
            _ = (shadow / "cli.py").write_text("print('SHADOWED')\n")
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            env["PYTHONSAFEPATH"] = ""
            plain = subprocess.run(
                [sys.executable, "-m", "omh.cli"], cwd=temporary, env=env, text=True, capture_output=True, check=False
            )
            isolated = subprocess.run(
                [sys.executable, "-P", "-m", "omh.cli"], cwd=temporary, env=env, text=True, capture_output=True, check=False
            )
            self.assertEqual(plain.stdout.strip(), "SHADOWED")
            self.assertNotIn("SHADOWED", isolated.stdout)

    def test_staged_transaction_regression_guard_names_the_refusal_it_prevents(self):
        # Proves the guard above is load-bearing: judging the candidate by the
        # home manifest is exactly the refusal that rolled 2.0.1 updates back.
        # A candidate SKILL.md that already holds the incoming render is no
        # longer a local modification (#2300), so the candidate's copy here
        # differs from BOTH the home manifest's old record and the render.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _legacy, args, plan = self._fixture(root, pointer=True)
            manifest_path = self._older_pack_home(root)
            first_skill = _object(
                _array(_read_json_object(manifest_path)["skills"], "manifest skills")[0], "first manifest skill"
            )
            first_rel = _text(first_skill["path"], "first skill path")
            previous = (root / "current").resolve()
            argv = ["omh", "--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "update", "--no-interactive"]
            live = self._live_update_runner(root)
            diverged: list[Path] = []

            def run(
                command: list[str],
                *,
                text: Literal[True],
                stdout: int | None,
                stderr: int | None,
                env: dict[str, str] | None,
                timeout: float | None,
            ) -> subprocess.CompletedProcess[str]:
                completed = live(command, text=text, stdout=stdout, stderr=stderr, env=env, timeout=timeout)
                # The pack smoke runs against a throwaway home; only the
                # re-entry carries this transaction's `--omh-home`.
                smoke = "update" in command and "--omh-home" not in command
                if smoke and not diverged:
                    # After the pack smoke rendered the candidate: neither the
                    # old record ("0" * 64) nor the incoming render.
                    generation = _runner_environment(env)["OMH_SELF_UPDATE_GENERATION"]
                    skill_file = Path(generation) / "skills" / first_rel
                    _ = skill_file.write_text("diverged from both the old record and the render\n", encoding="utf-8")
                    diverged.append(skill_file)
                return completed

            with (
                patch.object(sys, "argv", argv),
                patch("omh.install.installer._manifest_describes", return_value=True),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = self._run(root, args, plan, run)
            self.assertEqual(len(diverged), 1)
            self.assertFalse(result["ok"])
            self.assertEqual(result["phase"], "post_activation")
            self.assertIn("local modifications detected", result["post_activation"].get("reason", ""))
            self.assertIn(first_rel, result["post_activation"].get("reason", ""))
            self.assertTrue(result["rollback"]["performed"])
            self._assert_pair(root, previous)


class ManagedWorkflowRegistrationTests(unittest.TestCase):
    @staticmethod
    def _args(root: Path) -> ManagedWorkflowArgs:
        return ManagedWorkflowArgs(
            omh_home=str(root / "omh"),
            hermes_home=str(root / "hermes"),
            scope="user",
            dry_run=False,
            force=False,
            memory_mode="review-first",
        )

    def test_pre_migration_apply_registers_the_existing_legacy_skills_dir(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy_skills = root / "omh" / "skills"
            legacy_skills.mkdir(parents=True)
            current_skills = root / "current" / "skills"
            args = self._args(root)

            with (
                patch.object(setup_commands, "managed_current_workflow_pack_dir", return_value=current_skills),
                patch.object(setup_commands, "_managed_command_runtime", return_value={"managed": True}),
            ):
                status = setup_commands.cmd_apply(args)

            self.assertEqual(status, 0)
            registered = external_dirs((root / "hermes" / "config.yaml").read_text())
            self.assertEqual(registered, [legacy_skills.resolve().as_posix()])
            state = _read_json_object(root / "omh" / "runtime" / "state.json")
            self.assertEqual(_text(state["last_applied_skills_dir"], "last applied skills directory"), str(legacy_skills.resolve()))
            self.assertNotIn(current_skills.as_posix(), registered)

    def test_migrated_profile_sync_recognizes_the_current_pointer_registration(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_skills = PureWindowsPath(r"C:\omh\current\skills")
            profile = root / "hermes" / "profiles" / "bot"
            (profile / "plugins" / "omh").mkdir(parents=True)
            _ = (profile / "config.yaml").write_text(
                f"skills:\n  external_dirs:\n  - {current_skills.as_posix()}\n"
            )
            args = self._args(root)

            applied: list[Namespace] = []
            captured_results: list[dict[str, object]] = []

            def apply_result(
                profile_args: Namespace, *, bind_omh_home: bool = True, theme_home: Path | None = None
            ) -> dict[str, object]:
                # This profile names no store, in its config or its `.env`,
                # so the sync asks for the primary's to be written (#1967);
                # the unset-only writer keeps a profile setting (#1679).
                self.assertTrue(bind_omh_home)
                applied.append(profile_args)
                # The keys the sync reads for the profile row; the real
                # `_apply_result` always returns them (#1857, #1973).
                return {
                    "registration": "unchanged",
                    "retired_external_dirs": [],
                    "registered_dir": current_skills.as_posix(),
                    "display_release": {},
                    "plugin_omh_home": {"reclaimed": ""},
                }

            def capture_results(
                results: list[dict[str, object]], *, language: str
            ) -> None:
                _ = language
                captured_results.extend(results)

            with (
                patch("omh.commands.setup._command_package_self_update_plan", return_value={"should_update": False}),
                patch.object(setup_commands, "cmd_install", return_value=0),
                patch("omh.commands.setup._bootstrap_tui_surface", return_value={}),
                patch("omh.commands.setup._refresh_installed_menubar_app", return_value=None),
                patch("omh.commands.setup._registered_workflow_dir", return_value=current_skills),
                patch.object(setup_commands, "install_plugin_bundle"),
                patch("omh.commands.setup._apply_result", side_effect=apply_result),
                patch("omh.commands.setup._print_hermes_profiles_line", side_effect=capture_results),
            ):
                status = setup_commands.cmd_update(args)

            self.assertEqual(status, 0)
            self.assertEqual(
                captured_results,
                [
                    {
                        "profile": "bot",
                        "status": "refreshed",
                        "registration": "unchanged",
                        "retired_external_dirs": [],
                        "registered_dir": current_skills.as_posix(),
                        "display_release": {},
                    }
                ],
            )
            self.assertEqual(len(applied), 1)

    def test_migrated_uninstall_removes_current_registration_from_primary_and_profiles(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_skills = root / "current" / "skills"
            current_skills.mkdir(parents=True)
            profile = root / "hermes" / "profiles" / "bot"
            profile.mkdir(parents=True)
            for home in (root / "hermes", profile):
                _ = (home / "config.yaml").write_text(
                    f"skills:\n  external_dirs:\n  - {current_skills}\n"
                )
            base = [
                "--omh-home",
                str(root / "omh"),
                "--hermes-home",
                str(root / "hermes"),
                "uninstall",
                "--registration-only",
            ]

            with (
                patch.object(setup_commands, "managed_current_workflow_pack_dir", return_value=current_skills),
                patch.object(setup_commands, "_managed_command_runtime", return_value={"managed": True}),
            ):
                status, _stdout, stderr = run_cli(base)

            self.assertEqual((status, stderr), (0, ""))
            for home in (root / "hermes", profile):
                self.assertNotIn(current_skills.as_posix(), external_dirs((home / "config.yaml").read_text()))
