"""Native-Windows Codex handoffs (#2471): child environment, sandbox backend, shim resolution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.coding.codex_windows_sandbox import codex_windows_sandbox_signal  # noqa: E402
from omh.coding.fanout_dispatch import (  # noqa: E402
    build_dispatch_argv,
    dispatch_fanout,
    with_codex_fenced_sandbox,
    with_codex_windows_sandbox,
)
from omh.coding.fanout_output import FanoutOutput  # noqa: E402
from omh.coding.fanout_settings import (  # noqa: E402
    FANOUT_SETTINGS_SCHEMA_VERSION,
    fanout_settings_path,
    merged_environment_policy,
    read_fanout_settings,
    stored_codex_windows_sandbox,
)
from omh.coding.executor_readiness import _path_resolutions, _with_advisory_signals  # noqa: E402
from omh.coding.fanout_environment import resolve_child_environment  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402

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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CodexWindowsSandboxSignalTests(unittest.TestCase):
    def _signal(self, root: Path, *, platform_name: str = "nt", environ: dict[str, str] | None = None,
                project: bool = False) -> dict[str, object]:
        return codex_windows_sandbox_signal(
            platform_name=platform_name,
            environ=environ or {},
            home=root / "home",
            project_root=(root / "repo") if project else None,
        )

    def test_no_backend_configured_expects_a_read_only_session(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "home" / ".codex" / "config.toml", 'sandbox_mode = "workspace-write"\n')

            signal = self._signal(root)

            self.assertEqual(signal["status"], "not_configured")
            self.assertEqual(signal["write_capability"], "read_only_expected")

    def test_no_config_file_at_all_also_expects_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(self._signal(Path(tmp))["write_capability"], "read_only_expected")

    def test_a_configured_backend_is_reported_but_not_claimed_to_start(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "home" / ".codex" / "config.toml", '[windows]\nsandbox = "mxc"\n')

            signal = self._signal(root)

            self.assertEqual((signal["status"], signal["value"], signal["source"]),
                             ("configured", "mxc", "user_config"))
            self.assertEqual(signal["write_capability"], "not_observed")

    def test_codex_home_is_where_the_user_config_is_read(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "elsewhere" / "config.toml", '[windows]\nsandbox = "elevated"\n')

            signal = self._signal(root, environ={"CODEX_HOME": str(root / "elsewhere")})

            self.assertEqual(signal["value"], "elevated")

    def test_project_config_overrides_the_user_config(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "home" / ".codex" / "config.toml", '[windows]\nsandbox = "elevated"\n')
            _write(root / "repo" / ".codex" / "config.toml", '[windows]\nsandbox = "unelevated"\n')

            signal = self._signal(root, project=True)

            self.assertEqual((signal["value"], signal["source"]), ("unelevated", "project_config"))

    def test_an_unknown_value_is_unrecognized_without_echoing_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "home" / ".codex" / "config.toml", '[windows]\nsandbox = "C:/secret path!"\n')

            signal = self._signal(root)

            self.assertEqual(signal["status"], "unrecognized")
            self.assertNotIn("secret", str(signal))

    def test_a_broken_config_is_unreadable_not_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "home" / ".codex" / "config.toml", "[windows\n")

            signal = self._signal(root)

            self.assertEqual(signal["status"], "unreadable")
            self.assertEqual(signal["unreadable_sources"], ["user_config"])
            self.assertEqual(signal["write_capability"], "not_observed")

    def test_other_platforms_are_not_applicable(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(self._signal(Path(tmp), platform_name="posix")["status"], "not_applicable")


class CodexReadinessSurfaceTests(unittest.TestCase):
    def _surface(self, root: Path, profile: str, config: str | None) -> dict[str, object]:
        home = root / "home"
        if config is not None:
            _write(home / ".codex" / "config.toml", config)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        result = {"status": "ready", "available": True, "summary": "codex-cli 1.0", "next_action": "dispatch"}
        with mock.patch("omh.coding.executor_readiness._os_name", return_value="nt"), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("omh.coding.executor_readiness.Path.home", return_value=home), \
                mock.patch("omh.coding.executor_readiness.find_project_root", return_value=None):
            os.environ.pop("CODEX_HOME", None)
            return _with_advisory_signals(paths, profile, result)

    def test_ready_codex_without_a_backend_says_it_will_be_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self._surface(Path(tmp), "codex", 'sandbox_mode = "workspace-write"\n')

            self.assertEqual(result["windows_sandbox"]["write_capability"], "read_only_expected")
            self.assertIn("read-only", result["summary"])
            self.assertIn('[windows] sandbox = "mxc"', result["summary"])
            self.assertEqual(result["next_action"], "configure_codex_windows_sandbox")
            # Still the binary's own answer: the probe is not turned into a refusal.
            self.assertTrue(result["available"])

    def test_ready_codex_with_a_backend_keeps_its_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self._surface(Path(tmp), "codex", '[windows]\nsandbox = "mxc"\n')

            self.assertEqual(result["windows_sandbox"]["value"], "mxc")
            self.assertEqual(result["summary"], "codex-cli 1.0")
            self.assertEqual(result["next_action"], "dispatch")

    def test_a_backend_in_omh_fanout_settings_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            _settings(Path(tmp) / ".omh", {"codex": {"windows_sandbox": "elevated"}})
            result = self._surface(Path(tmp), "codex", None)

            self.assertEqual(result["windows_sandbox"]["source"], "omh_fanout_settings")
            self.assertEqual(result["windows_sandbox"]["value"], "elevated")
            self.assertEqual(result["next_action"], "dispatch")

    def test_other_profiles_carry_no_codex_sandbox_signal(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertNotIn("windows_sandbox", self._surface(Path(tmp), "claude-code", None))


class WindowsPathResolutionTests(unittest.TestCase):
    def test_the_extensionless_npm_shim_is_not_a_windows_resolution(self) -> None:
        # npm puts a POSIX `codex` shell shim beside `codex.cmd`. Spawning the
        # shim on Windows fails with WinError 193 before the probe falls back.
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "codex").write_text("#!/bin/sh\n", encoding="utf-8")
            (Path(tmp) / "codex.cmd").write_text("@echo off\n", encoding="utf-8")
            with mock.patch("omh.coding.executor_readiness._os_name", return_value="nt"), \
                    mock.patch.dict(os.environ, {"PATH": tmp, "PATHEXT": ".COM;.EXE;.BAT;.CMD"}), \
                    mock.patch("omh.coding.executor_readiness.os.access", return_value=True):
                found = [Path(path).name for path in _path_resolutions("codex")]

            self.assertEqual(found, ["codex.cmd"])

    def test_posix_still_resolves_the_bare_name(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "codex").write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch("omh.coding.executor_readiness._os_name", return_value="posix"), \
                    mock.patch.dict(os.environ, {"PATH": tmp}), \
                    mock.patch("omh.coding.executor_readiness.os.access", return_value=True):
                found = [Path(path).name for path in _path_resolutions("codex")]

            self.assertEqual(found, ["codex"])


def _settings(omh_home: Path, document: dict[str, object]) -> None:
    path = fanout_settings_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": FANOUT_SETTINGS_SCHEMA_VERSION, **document}), encoding="utf-8")


class FanoutSettingsTests(unittest.TestCase):
    def test_no_file_changes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(merged_environment_policy(Path(tmp), None))
            declared = {"owner_capabilities": {"codex": ["A"]}}
            self.assertIs(merged_environment_policy(Path(tmp), declared), declared)
            self.assertEqual(stored_codex_windows_sandbox(Path(tmp)), "")

    def test_stored_grants_join_the_command_grants(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _settings(home, {"environment_policy": {
                "owner_capabilities": {"codex": ["STORED"]}, "project_variables": ["CI"]}})

            merged = merged_environment_policy(home, {
                "owner_capabilities": {"codex": ["TYPED"], "claude-code": ["OTHER"]},
                "project_variables": [], "allow_broad_inheritance": False,
            })

            self.assertEqual(merged["owner_capabilities"],
                             {"claude-code": ["OTHER"], "codex": ["STORED", "TYPED"]})
            self.assertEqual(merged["project_variables"], ["CI"])
            self.assertIs(merged["allow_broad_inheritance"], False)

    def test_a_stored_grant_reaches_the_child(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _settings(home, {"environment_policy": {"owner_capabilities": {"codex": ["TRACKER_TOKEN"]}}})
            decision = resolve_child_environment(
                {"PATH": "/bin", "TRACKER_TOKEN": "granted"}, owner="codex", purpose="owner",
                declaration=merged_environment_policy(home, None),
            )
            self.assertEqual(decision.environment.get("TRACKER_TOKEN"), "granted")

    def test_the_file_cannot_turn_on_broad_inheritance(self) -> None:
        with TemporaryDirectory() as tmp:
            _settings(Path(tmp), {"environment_policy": {"allow_broad_inheritance": True}})
            with self.assertRaisesRegex(ValueError, "environment_policy accepts only"):
                read_fanout_settings(Path(tmp))

    def test_a_broken_file_fails_loudly(self) -> None:
        with TemporaryDirectory() as tmp:
            path = fanout_settings_path(Path(tmp))
            path.parent.mkdir(parents=True)
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "could not be read"):
                merged_environment_policy(Path(tmp), None)

    def test_an_unknown_backend_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            _settings(Path(tmp), {"codex": {"windows_sandbox": "none"}})
            with self.assertRaisesRegex(ValueError, "must be one of"):
                stored_codex_windows_sandbox(Path(tmp))


class CodexSandboxArgvTests(unittest.TestCase):
    def _argv(self, owner: str, route: dict[str, str] | None, backend: str) -> list[str] | None:
        return with_codex_windows_sandbox(build_dispatch_argv(owner, "do it", route), owner, backend)

    def test_a_stored_backend_becomes_a_config_override_before_the_prompt(self) -> None:
        self.assertEqual(self._argv("codex", None, "mxc"),
                         ["codex", "exec", "--config", "windows.sandbox=mxc", "do it"])

    def test_no_backend_keeps_the_template_byte_identical(self) -> None:
        self.assertEqual(self._argv("codex", None, ""), ["codex", "exec", "do it"])

    def test_it_follows_a_routed_model(self) -> None:
        self.assertEqual(self._argv("codex", {"selected_model": "m"}, "elevated"),
                         ["codex", "exec", "--model", "m", "--config", "windows.sandbox=elevated", "do it"])

    def test_other_owners_ignore_it(self) -> None:
        self.assertEqual(self._argv("claude-code", None, "mxc"), build_dispatch_argv("claude-code", "do it"))

    def test_an_unknown_backend_never_reaches_argv(self) -> None:
        with self.assertRaises(ValueError):
            self._argv("codex", None, "danger")

    def test_build_dispatch_argv_keeps_its_three_argument_shape(self) -> None:
        # Fixtures across the suite substitute it with a (owner, prompt, route)
        # function; a new keyword at the call sites broke every one of them.
        import inspect
        self.assertEqual(list(inspect.signature(build_dispatch_argv).parameters),
                         ["owner", "prompt", "model_route"])


def _fence(selected: str, enforced: bool = True) -> SimpleNamespace:
    return SimpleNamespace(selected=selected, receipt={"enforced": enforced})


class CodexFencedSandboxArgvTests(unittest.TestCase):
    # `codex exec` is read-only by default and `workspace-write` cannot start
    # Codex's own sandbox inside bwrap or sandbox-exec, so a fenced codex
    # unit could never write.
    _FULL = ["codex", "exec", "--sandbox", "danger-full-access", "do it"]

    def test_a_bwrap_fence_turns_off_the_codex_sandbox(self) -> None:
        argv = build_dispatch_argv("codex", "do it")
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", _fence("bwrap")), self._FULL)

    def test_a_sandbox_exec_fence_turns_off_the_codex_sandbox(self) -> None:
        argv = build_dispatch_argv("codex", "do it")
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", _fence("sandbox-exec")), self._FULL)

    def test_the_prompt_stays_last_after_session_and_model_options(self) -> None:
        argv = ["/usr/bin/codex", "exec", "--json", "--model", "m", "do it"]
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", _fence("bwrap")),
                         ["/usr/bin/codex", "exec", "--json", "--model", "m",
                          "--sandbox", "danger-full-access", "do it"])

    def test_no_fence_or_an_unenforced_fence_changes_nothing(self) -> None:
        argv = build_dispatch_argv("codex", "do it")
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", None), ["codex", "exec", "do it"])
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", _fence("bwrap", enforced=False)),
                         ["codex", "exec", "do it"])

    def test_other_backends_change_nothing(self) -> None:
        argv = build_dispatch_argv("codex", "do it")
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", _fence("windows")), ["codex", "exec", "do it"])

    def test_an_explicit_sandbox_choice_is_kept(self) -> None:
        for options in (["-s", "read-only"], ["--sandbox", "workspace-write"], ["--sandbox=read-only"],
                        ["-sread-only"], ["--full-auto"], ["--dangerously-bypass-approvals-and-sandbox"],
                        ["-c", "sandbox_mode=read-only"]):
            argv = ["codex", "exec", *options, "do it"]
            with self.subTest(options=options):
                self.assertEqual(with_codex_fenced_sandbox(argv, "codex", _fence("bwrap")), argv)

    def test_a_prompt_that_looks_like_a_flag_is_not_a_choice(self) -> None:
        argv = ["codex", "exec", "--sandbox"]
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", _fence("bwrap")),
                         ["codex", "exec", "--sandbox", "danger-full-access", "--sandbox"])

    def test_other_owners_are_unchanged(self) -> None:
        argv = build_dispatch_argv("claude-code", "do it")
        self.assertEqual(with_codex_fenced_sandbox(argv, "claude-code", _fence("bwrap")), argv)

    def test_the_windows_backend_override_is_unchanged(self) -> None:
        argv = with_codex_windows_sandbox(build_dispatch_argv("codex", "do it"), "codex", "mxc")
        self.assertEqual(with_codex_fenced_sandbox(argv, "codex", None),
                         ["codex", "exec", "--config", "windows.sandbox=mxc", "do it"])


@unittest.skipUnless(sys.platform == "darwin", "sandbox-exec confinement is exercised on macOS")
class CodexFencedSandboxDispatchTests(unittest.TestCase):
    """Through a real `dispatch_fanout` and a real sandbox-exec fence: the argv the fenced codex runs."""

    def _dispatch_through_the_fence(self, *, fail_first: bool = False, max_retries: int = 0) -> list[list[str]]:
        from test_fanout_dispatch import _GOAL, _UNITS, _make_repo, _ready
        from omh.coding.fanout import build_fanout_contract
        from omh.coding.fanout_artifacts import write_fanout_contract

        # Stands in for `codex`. It logs the unit's `exec` calls only, into the
        # worktree's gitignored fence scratch (`.omh/confinement-tmp`): writable
        # inside the fence, and a clean tree keeps a retry replay-safe. Readiness
        # probes (`--version`, `exec --help`) log nothing. With `fail_first`, the
        # first exec exits 1 with a retryable 503 so the dispatcher retries.
        script = (
            "import json, os, sys\n"
            "a = sys.argv[1:]\n"
            "if a[:1] == ['exec'] and a[1:2] != ['--help']:\n"
            "    log = os.path.join('.omh', 'confinement-tmp', 'codex-argv.jsonl')\n"
            "    first = not os.path.exists(log)\n"
            "    open(log, 'a').write(json.dumps(a) + '\\n')\n"
            f"    if first and {fail_first!r}:\n"
            "        print('stream error: status 503 service unavailable', file=sys.stderr)\n"
            "        sys.exit(1)\n"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "codex_stub.py").write_text(script, encoding="utf-8")
            stub = root / "codex-stub"
            stub.write_text(f'#!/bin/sh\nexec /usr/bin/python3 "{root / "codex_stub.py"}" "$@"\n', encoding="utf-8")
            stub.chmod(0o755)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            real_build = build_dispatch_argv

            def stub_argv(owner, prompt, model_route=None):
                argv = real_build(owner, prompt, model_route)
                return [str(stub), *argv[1:]] if argv else argv

            with mock.patch("omh.coding.fanout_dispatch.build_dispatch_argv", side_effect=stub_argv):
                summary = dispatch_fanout(paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                                          only_units=["core"], readiness=_ready, max_retries=max_retries,
                                          sleep=lambda _seconds: None)

            core = {entry["unit_id"]: entry for entry in summary["units"]}["core"]
            self.assertTrue(core["filesystem_confinement"]["enforced"])
            self.assertEqual(core["filesystem_confinement"]["backend"], "sandbox-exec")
            log = Path(core["worktree_path"]) / ".omh" / "confinement-tmp" / "codex-argv.jsonl"
            self.assertTrue(log.is_file(), "the stub never ran inside the unit worktree")
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def test_the_fenced_codex_process_receives_the_full_access_flag(self) -> None:
        exec_calls = self._dispatch_through_the_fence()
        self.assertEqual(len(exec_calls), 1, exec_calls)
        self.assertEqual(exec_calls[0][-3:-1], ["--sandbox", "danger-full-access"])

    def test_a_retried_attempt_rebuilds_the_argv_with_the_flag(self) -> None:
        # The first exec fails with a retryable 503, so the second runs from the
        # argv the retry branch rebuilds; the flag must be applied there too.
        exec_calls = self._dispatch_through_the_fence(fail_first=True, max_retries=1)
        self.assertEqual(len(exec_calls), 2, exec_calls)
        for argv in exec_calls:
            self.assertEqual(argv[-3:-1], ["--sandbox", "danger-full-access"])


class SandboxRefusalCaptureTests(unittest.TestCase):
    def _capture(self, *chunks: tuple[str, bytes]) -> FanoutOutput:
        capture = FanoutOutput()
        for stream, chunk in chunks:
            capture.feed(stream, chunk)
        capture.finish_pending(complete=True)
        return capture

    def test_codex_read_only_refusal_is_named(self) -> None:
        capture = self._capture(("stdout", b"patch rejected: writing is blocked by read-only sandbox; "
                                           b"rejected by user approval settings\n"))
        self.assertEqual(capture.sandbox_refusal(), "executor_sandbox_read_only")

    def test_mxc_start_failure_is_named_and_outranks_read_only(self) -> None:
        capture = self._capture(
            ("stdout", b"writing is blocked by read-only sandbox\n"),
            ("stderr", b'exec_command failed: CreateProcess { message: "MXC requires nonempty Unicode host '
                       b'SystemDrive" }\n'),
        )
        self.assertEqual(capture.sandbox_refusal(), "executor_sandbox_start_failed")

    def test_a_marker_split_across_chunks_is_still_found(self) -> None:
        capture = self._capture(("stderr", b"MXC requires nonempty Uni"), ("stderr", b"code host SystemDrive\n"))
        self.assertEqual(capture.sandbox_refusal(), "executor_sandbox_start_failed")

    def test_a_marker_far_before_the_error_window_is_still_found(self) -> None:
        capture = self._capture(("stdout", b"writing is blocked by read-only sandbox\n" + b"x" * 50_000 + b"\n"))
        self.assertEqual(capture.sandbox_refusal(), "executor_sandbox_read_only")

    def test_ordinary_output_names_nothing_and_the_phrase_is_not_retained(self) -> None:
        self.assertEqual(self._capture(("stderr", b"compiler failed\n")).sandbox_refusal(), "")
        capture = self._capture(("stdout", b"writing is blocked by read-only sandbox\n"))
        self.assertNotIn("read-only sandbox", json.dumps(capture.streams()))


class SandboxRefusalDispatchTests(unittest.TestCase):
    """End to end through `dispatch_fanout`: what a unit with no result is called."""

    def _run(self, stdout: str, returncode: int = 0, *, settings: dict[str, object] | None = None,
             env: dict[str, str] | None = None, spawned: list[tuple[list[str], dict[str, str]]] | None = None,
             ) -> dict[str, object]:
        from test_fanout_dispatch import _GOAL, _UNITS, _make_repo, _ready
        from omh.coding.fanout import build_fanout_contract
        from omh.coding.fanout_artifacts import write_fanout_contract

        class _Completed:
            def __init__(self) -> None:
                self.returncode, self.stdout, self.stderr = returncode, stdout, ""

        def runner(argv, **kwargs):
            if argv[0] == "git":
                return subprocess.run(argv, **kwargs)
            if spawned is not None:
                spawned.append((list(argv), dict(kwargs.get("env") or {})))
            return _Completed()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            if settings is not None:
                _settings(paths.omh_home, settings)
            repo, sha = _make_repo(root)
            contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, _UNITS))
            summary = dispatch_fanout(paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha,
                                      only_units=["core"], runner=runner, readiness=_ready, max_retries=0,
                                      env=env)
            return summary["units"][0].get("failure_diagnostic", {})

    def test_stored_settings_reach_the_spawned_codex(self) -> None:
        # The agent-driven path: no flag on the command, the grant and the
        # backend come from the operator's settings file alone.
        spawned: list[tuple[list[str], dict[str, str]]] = []
        parent = {**os.environ, "TRACKER_TOKEN": "granted", "UNGRANTED_TOKEN": "kept-out"}
        with mock.patch.dict(os.environ, parent, clear=True):
            self._run("done\n", settings={
                "environment_policy": {"owner_capabilities": {"codex": ["TRACKER_TOKEN"]}},
                "codex": {"windows_sandbox": "mxc"},
            }, env=parent, spawned=spawned)

        argv, child_env = spawned[0]
        self.assertIn("windows.sandbox=mxc", argv)
        self.assertEqual(child_env.get("TRACKER_TOKEN"), "granted")
        self.assertNotIn("UNGRANTED_TOKEN", child_env)

    def test_a_read_only_session_with_no_result_is_called_read_only(self) -> None:
        diagnostic = self._run("patch rejected: writing is blocked by read-only sandbox; rejected\n")
        self.assertEqual((diagnostic["phase"], diagnostic["reason"]), ("unit_result", "executor_sandbox_read_only"))

    def test_a_sandbox_that_never_started_is_called_that_on_a_nonzero_exit(self) -> None:
        diagnostic = self._run("MXC requires nonempty Unicode host SystemDrive\n", returncode=1)
        self.assertEqual((diagnostic["phase"], diagnostic["reason"]), ("worker", "executor_sandbox_start_failed"))

    def test_without_a_marker_it_stays_malformed_result(self) -> None:
        diagnostic = self._run("done\n")
        self.assertEqual(diagnostic["reason"], "malformed_result")


if __name__ == "__main__":
    unittest.main()
