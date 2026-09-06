"""Contracts for `omh update-check` and its two integration points:

- `omh install`/`omh update` recording a comparable remote identity into
  `state.json` (`release_source_commit`) only when update-check is opted in.
- The `omh`/`hermes` launch path (`commands/main.py`) acting on the check:
  a notice line for `notify`, reusing `omh update`'s own code path for
  `auto`, and a non-blocking lock so two launches never auto-update at once.

The probe spawns `curl` as a subprocess (never a Python-level network client
-- see `tests/test_handoff_safety_contract_enforcement.py` INVARIANT 2), so
every test here patches `omh.maintenance.update_check_probe._run_curl` --
the transport seam the probe functions resolve when no `runner` is passed
explicitly -- rather than the global `subprocess.run`, so a legitimate
subprocess call elsewhere in `omh update` (e.g. command-package self-update)
is never accidentally intercepted. None of these tests may spawn a real
process or reach a real socket, and the `off`-mode tests assert that too by
making the fake raise if it is ever called.

Auto mode's `_run_auto_update` spawns `omh update --no-interactive` as a real
subprocess (so its own command-package-update re-entry sees a normal `omh
update` `sys.argv`, not the bare-launch argv this process actually started
with -- see the docstring on `_run_auto_update`). Tests here fake that
subprocess by patching `omh.commands.main.subprocess.run` directly, the same
pattern `tests/test_cli.py` already uses for the command-package self-update
re-entry, rather than letting a real child process spawn.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli

from omh.commands import main as main_module
from omh.local_store import atomic_write_json, read_json_object
from omh.maintenance.update_check import (
    acquire_auto_update_lock,
    read_update_check_cache,
    update_check_cache_path,
    write_update_check_policy,
)
from omh.paths import OmhPaths

_RUN_CURL_TARGET = "omh.maintenance.update_check_probe._run_curl"


def _base(root: Path) -> list[str]:
    return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]


def _paths(root: Path) -> OmhPaths:
    resolved = root.resolve()
    return OmhPaths(resolved / ".omh", resolved / ".hermes")


def _http_stdout(sha: str) -> str:
    return f'HTTP/2 200\netag: "fake"\n\n{json.dumps({"sha": sha})}'


def _fake_curl(sha: str):
    """Fake curl: a readable head, and a verified fast-forward compare.

    Since the issue #1282 contract, `behind` is emitted only for a verified
    `fast_forward`, so the compare read answers `status: ahead`.
    """

    def runner(argv, timeout=None):
        if any("/compare/" in str(arg) for arg in argv):
            stdout = 'HTTP/2 200\n\n' + json.dumps({"status": "ahead", "ahead_by": 1, "behind_by": 0})
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=_http_stdout(sha), stderr="")

    return runner


def _fake_curl_rewritten(sha: str, *, compare_status: int = 404):
    """Fake curl for rewritten history: head readable, cursor unreachable."""

    def runner(argv, timeout=None):
        if any("/compare/" in str(arg) for arg in argv):
            return subprocess.CompletedProcess(argv, 0, stdout=f"HTTP/2 {compare_status}\n\n", stderr="")
        if any("/tags" in str(arg) for arg in argv):
            return subprocess.CompletedProcess(argv, 0, stdout='HTTP/2 200\n\n[{"name": "v0.1.0"}]', stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=_http_stdout(sha), stderr="")

    return runner


def _refusing_curl():
    def runner(argv, timeout=None):  # pragma: no cover - fails the test if reached
        raise AssertionError("update-check must not spawn curl here")

    return runner


class UpdateCheckCliTests(unittest.TestCase):
    def test_status_reports_the_shipped_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(_base(root) + ["update-check", "status"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("Update-check mode: off", stdout)
            self.assertIn("Last checked: never", stdout)

    def test_set_writes_the_policy_and_status_reflects_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(
                _base(root) + ["update-check", "set", "--mode", "notify", "--interval-hours", "6"],
                output_json=False,
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("Update-check mode: notify", stdout)
            self.assertIn("Interval: every 6.0 hour(s)", stdout)

            status, stdout, _ = run_cli(_base(root) + ["update-check", "status"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("Update-check mode: notify", stdout)
            self.assertIn("Interval: every 6.0 hour(s)", stdout)

    def test_set_without_arguments_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, _, stderr = run_cli(_base(root) + ["update-check", "set"], output_json=False)
            self.assertEqual(status, 2)
            self.assertIn("--mode", stderr)

    def test_set_rejects_an_unknown_mode(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit) as raised:
                run_cli(_base(root) + ["update-check", "set", "--mode", "always"], output_json=False)
            self.assertEqual(raised.exception.code, 2)

    def test_status_json_reports_the_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(_base(root) + ["update-check", "status", "--json"])
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_update_check_status/v1")
            self.assertEqual(payload["policy"]["mode"], "off")


class InstallRecordsRemoteIdentityTests(unittest.TestCase):
    def _state(self, root: Path) -> dict[str, object]:
        return read_json_object(_paths(root).runtime_state_path) or {}

    def test_default_off_mode_never_touches_the_network_on_update(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch(_RUN_CURL_TARGET, _refusing_curl()):
                status, _, stderr = run_cli(_base(root) + ["update", "--yes", "--no-interactive"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            self.assertNotIn("release_source_commit", self._state(root))

    def test_notify_mode_records_the_remote_commit_on_the_preview_channel(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(_base(root) + ["update-check", "set", "--mode", "notify"], output_json=False)
            with patch(_RUN_CURL_TARGET, _fake_curl("c" * 40)):
                status, _, stderr = run_cli(_base(root) + ["update", "--yes", "--no-interactive"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(self._state(root)["release_source_commit"], "c" * 40)

    def test_local_channel_never_records_a_main_commit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_source = root / "local-skills"
            local_source.mkdir()
            run_cli(_base(root) + ["update-check", "set", "--mode", "auto"], output_json=False)
            with patch(_RUN_CURL_TARGET, _refusing_curl()):
                status, _, stderr = run_cli(
                    _base(root) + ["install", "--channel", "local", "--from-skills-dir", str(local_source)],
                    output_json=False,
                )
            self.assertEqual((status, stderr), (0, ""))
            self.assertNotIn("release_source_commit", self._state(root))

    def test_a_failed_probe_never_regresses_a_previously_recorded_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(_base(root) + ["update-check", "set", "--mode", "notify"], output_json=False)
            with patch(_RUN_CURL_TARGET, _fake_curl("d" * 40)):
                run_cli(_base(root) + ["update", "--yes", "--no-interactive"], output_json=False)
            self.assertEqual(self._state(root)["release_source_commit"], "d" * 40)

            def failing(argv, timeout=None):
                raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout or 1.5)

            with patch(_RUN_CURL_TARGET, failing):
                status, _, stderr = run_cli(_base(root) + ["update", "--yes", "--no-interactive"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(self._state(root)["release_source_commit"], "d" * 40)


class StartupCheckLaunchIntegrationTests(unittest.TestCase):
    def _args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(omh_home=str(root / ".omh"), hermes_home=str(root / ".hermes"), scope=None)

    def test_off_mode_prints_nothing_and_touches_no_network(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            buffer = io.StringIO()
            with patch(_RUN_CURL_TARGET, _refusing_curl()), contextlib.redirect_stdout(buffer):
                main_module._run_startup_update_check(args)
            self.assertEqual(buffer.getvalue(), "")

    def test_corrupt_setup_profile_with_the_shipped_off_mode_is_a_silent_launch(self) -> None:
        # Regression for the P0 defect: a corrupt `setup-profile.json` used to
        # raise inside `read_update_check_policy` (via `read_json_object`),
        # and `main.py`'s launch door only caught `OSError` -- a user who
        # never opted into this check got a launch traceback from a file this
        # check does not even own. Off mode must stay a silent launch.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            paths.omh_home.mkdir(parents=True, exist_ok=True)
            paths.setup_profile_path.write_text("{not valid json", encoding="utf-8")
            args = self._args(root)
            buffer = io.StringIO()
            with patch(_RUN_CURL_TARGET, _refusing_curl()), contextlib.redirect_stdout(buffer):
                main_module._run_startup_update_check(args)  # must not raise
            self.assertEqual(buffer.getvalue(), "")

    def test_state_json_as_a_json_array_with_notify_mode_is_a_silent_skip(self) -> None:
        # Regression for the same P0 shape one layer down: `state.json` that
        # is a JSON array (not an object) used to raise inside
        # `local_installed_commit`. It must read as "no comparable local
        # identity" -- inconclusive -- never a raised exception.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="notify")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            paths.runtime_state_path.write_text("[]", encoding="utf-8")
            args = self._args(root)
            buffer = io.StringIO()
            with patch(_RUN_CURL_TARGET, _fake_curl("b" * 40)), contextlib.redirect_stdout(buffer):
                main_module._run_startup_update_check(args)  # must not raise
            self.assertIn("inconclusive", buffer.getvalue())

    def test_notify_mode_prints_the_one_line_notice_when_behind(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="notify")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths.runtime_state_path, {"release_source_commit": "a" * 40})
            args = self._args(root)
            buffer = io.StringIO()
            with patch(_RUN_CURL_TARGET, _fake_curl("b" * 40)), contextlib.redirect_stdout(buffer):
                main_module._run_startup_update_check(args)
            output = buffer.getvalue()
            self.assertIn("OMH update available:", output)
            self.assertIn("omh update", output)
            # `notify` reports; only `auto` updates, and only `auto` says so.
            self.assertNotIn("Auto Update", output)

    def test_auto_mode_spawns_omh_update_no_interactive_as_a_real_subprocess(self) -> None:
        # Regression for the P1-b defect: `_run_auto_update` used to call
        # `cmd_update()` in-process, so the command-package self-update
        # re-entry (`commands/setup.py:_reentry_argv_with_command_package_
        # updated`) read the real process's `sys.argv[1:]` -- the bare `omh`
        # launch argv, empty -- instead of the synthesized `update ...` argv,
        # and exited 2 before the post-update half ever ran. Spawning a real
        # subprocess gives that re-entry a correct `sys.argv` of its own.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="auto")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                paths.runtime_state_path,
                {"release_source_commit": "a" * 40, "release_channel": "preview", "version": "9.9.8"},
            )
            args = self._args(root)
            buffer = io.StringIO()

            def fake_run(argv, timeout=None):
                # Simulate a successful `omh update` converging on the remote
                # identity the auto-update was triggered by, and recording the
                # version it installed the way `commands/setup.py` does.
                atomic_write_json(
                    paths.runtime_state_path,
                    {
                        "release_source_commit": "b" * 40,
                        "release_channel": "preview",
                        "version": "9.9.9",
                        "last_update": {"status": "ok"},
                    },
                )
                return subprocess.CompletedProcess(argv, 0)

            with (
                patch(_RUN_CURL_TARGET, _fake_curl("b" * 40)),
                patch.object(main_module.subprocess, "run", side_effect=fake_run) as run,
                contextlib.redirect_stdout(buffer),
            ):
                main_module._run_startup_update_check(args)

            run.assert_called_once()
            spawned_argv = run.call_args.args[0]
            self.assertEqual(spawned_argv[0], sys.executable)
            self.assertEqual(spawned_argv[1:3], ["-m", "omh.cli"])
            self.assertIn("update", spawned_argv)
            self.assertIn("--no-interactive", spawned_argv)
            # `--yes` would preset the branded-TUI identity choice
            # (`commands/setup.py:_preset_tui_identity_choice`) and rewrite a
            # user's own `display.interface`/skin choice on every auto-update.
            self.assertNotIn("--yes", spawned_argv)
            # The synthesized argv (after the interpreter/module prefix) must
            # be a valid CLI invocation, not just plausible-looking strings.
            main_module.build_parser().parse_args(spawned_argv[3:])

            state = read_json_object(paths.runtime_state_path) or {}
            self.assertIn("last_update", state)
            self.assertEqual(state["release_source_commit"], "b" * 40)
            # The cache is re-anchored on success so a launch later in the
            # same interval reads it as resolved, not still "behind".
            self.assertEqual(read_update_check_cache(paths)["outcome"], "up_to_date")

            # The launch is held for the whole update, so it says what it is
            # doing and what it landed on. The completion version is read
            # back from the record the update just rewrote -- this process is
            # still running the pre-update package -- and that same record is
            # what the TUI HUD footer renders.
            output = buffer.getvalue()
            self.assertIn("OMH Auto Update: aaaaaaa -> bbbbbbb (preview channel)", output)
            self.assertIn("OMH Auto Update complete: omh 9.9.9 is installed.", output)
            self.assertNotIn("9.9.8", output)

    def test_auto_mode_reports_a_failed_subprocess_without_crashing_the_launch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="auto")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths.runtime_state_path, {"release_source_commit": "a" * 40})
            args = self._args(root)
            out_buffer, err_buffer = io.StringIO(), io.StringIO()

            def failing_run(argv, timeout=None):
                return subprocess.CompletedProcess(argv, 2)

            with (
                patch(_RUN_CURL_TARGET, _fake_curl("b" * 40)),
                patch.object(main_module.subprocess, "run", side_effect=failing_run),
                contextlib.redirect_stdout(out_buffer),
                contextlib.redirect_stderr(err_buffer),
            ):
                main_module._run_startup_update_check(args)

            self.assertIn("update-check auto-update failed", err_buffer.getvalue())
            # The attempt is still announced -- the wait happened either way --
            # but a failed update never claims to have completed.
            self.assertIn("OMH Auto Update:", out_buffer.getvalue())
            self.assertNotIn("Auto Update complete", out_buffer.getvalue())
            cache = read_update_check_cache(paths)
            # A failed attempt never claims convergence.
            self.assertNotEqual(cache.get("outcome"), "up_to_date")

    def test_auto_mode_skips_silently_when_another_launch_holds_the_lock(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="auto")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths.runtime_state_path, {"release_source_commit": "a" * 40})
            args = self._args(root)
            buffer = io.StringIO()
            with acquire_auto_update_lock(paths):
                with patch(_RUN_CURL_TARGET, _fake_curl("b" * 40)), contextlib.redirect_stdout(buffer):
                    main_module._run_startup_update_check(args)
            state = read_json_object(paths.runtime_state_path) or {}
            self.assertNotIn("last_update", state)
            # Silent skip means silent: the launch that loses the race must
            # not announce an Auto Update it never ran.
            self.assertEqual(buffer.getvalue(), "")

    def test_notify_prints_the_rewrite_line_even_when_no_update_qualifies(self) -> None:
        # Issue #1282: an unreachable cursor must surface the classification
        # and the open gap -- silence never means complete coverage.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="notify")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths.runtime_state_path, {"release_source_commit": "a" * 40})
            args = self._args(root)
            buffer = io.StringIO()
            with patch(_RUN_CURL_TARGET, _fake_curl_rewritten("b" * 40)), contextlib.redirect_stdout(buffer):
                main_module._run_startup_update_check(args)
            output = buffer.getvalue()
            self.assertIn("history rewritten", output)
            self.assertIn("cursor_unreachable", output)
            self.assertIn("coverage gap", output)
            self.assertNotIn("OMH update available", output)

    def test_auto_mode_never_auto_updates_across_unverified_ancestry(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            write_update_check_policy(paths, mode="auto")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths.runtime_state_path, {"release_source_commit": "a" * 40})
            args = self._args(root)
            buffer = io.StringIO()
            with (
                patch(_RUN_CURL_TARGET, _fake_curl_rewritten("b" * 40)),
                patch.object(main_module.subprocess, "run") as run,
                contextlib.redirect_stdout(buffer),
            ):
                main_module._run_startup_update_check(args)
            run.assert_not_called()
            state = read_json_object(paths.runtime_state_path) or {}
            self.assertNotIn("last_update", state)
            self.assertEqual(state.get("release_source_commit"), "a" * 40)

    def test_cache_path_matches_the_documented_runtime_location(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            self.assertEqual(update_check_cache_path(paths), paths.omh_home / "runtime" / "update-check.json")


class WatchRecoveryCliTests(unittest.TestCase):
    """CLI surface for the issue #1282 rewritten-history recovery contract."""

    def _prime_open_gap(self, root: Path) -> None:
        paths = _paths(root)
        write_update_check_policy(paths, mode="notify")
        paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths.runtime_state_path, {"release_source_commit": "a" * 40})
        args = argparse.Namespace(omh_home=str(root / ".omh"), hermes_home=str(root / ".hermes"), scope=None)
        with patch(_RUN_CURL_TARGET, _fake_curl_rewritten("b" * 40)), contextlib.redirect_stdout(io.StringIO()):
            main_module._run_startup_update_check(args)

    def test_status_json_exposes_ancestry_generation_and_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prime_open_gap(root)
            status, stdout, stderr = run_cli(_base(root) + ["update-check", "status", "--json"])
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_update_check_status/v1")
            last_check = payload["last_check"]
            self.assertEqual(last_check["schema_version"], "omh_update_check_cache/v2")
            self.assertEqual(last_check["ancestry"], "cursor_unreachable")
            self.assertEqual(last_check["watched_branch"], "main")
            self.assertEqual(last_check["branch_generation"], 0)
            self.assertEqual(last_check["gap"]["status"], "open")
            self.assertTrue(last_check["gap"]["since"])
            self.assertTrue(last_check["recovery_attempts"])

    def test_status_human_output_names_the_open_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prime_open_gap(root)
            status, stdout, stderr = run_cli(_base(root) + ["update-check", "status"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("Ancestry: cursor_unreachable", stdout)
            self.assertIn("Coverage gap: open", stdout)
            self.assertIn("accept-gap", stdout)

    def test_status_never_prints_a_malformed_cached_commit_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            unsafe = "\x1b]8;;file:///Users/alice/.ssh/id_rsa\x07"
            update_check_cache_path(paths).parent.mkdir(parents=True)
            atomic_write_json(
                update_check_cache_path(paths),
                {
                    "schema_version": "omh_update_check_cache/v2",
                    "last_checked_at": "2026-09-03T00:00:00+00:00",
                    "outcome": "behind",
                    "remote_commit": unsafe,
                },
            )

            status, stdout, stderr = run_cli(_base(root) + ["update-check", "status"], output_json=False)

            self.assertEqual((status, stderr), (0, ""))
            self.assertNotIn("\x1b", stdout)
            self.assertNotIn("/Users/alice", stdout)
            self.assertNotIn("Remote main:", stdout)

    def test_accept_gap_marks_policy_acceptance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prime_open_gap(root)
            status, stdout, stderr = run_cli(_base(root) + ["update-check", "accept-gap"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("Coverage gap accepted", stdout)
            cache = read_update_check_cache(_paths(root))
            self.assertEqual(cache["gap"]["status"], "accepted")
            # Acceptance is recorded and idempotent.
            status, stdout, _ = run_cli(_base(root) + ["update-check", "accept-gap"], output_json=False)
            self.assertEqual(status, 0)
            self.assertIn("No open coverage gap", stdout)

    def test_accept_gap_json_reports_the_gap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._prime_open_gap(root)
            status, stdout, stderr = run_cli(_base(root) + ["update-check", "accept-gap", "--json"])
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_update_check_status/v1")
            self.assertTrue(payload["accepted"])
            self.assertEqual(payload["gap"]["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
