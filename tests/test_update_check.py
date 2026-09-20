"""Contracts for the opt-in startup update-availability check.

`evaluate_update_check` is the core of `omh update-check`: zero network
attempts while `update_check.mode` is `off` (the shipped default), an
interval-respecting cache once opted in, a bounded timeout on every probe,
and a silent skip -- never a raised exception, a false claim, or a delayed
result -- on any network failure.

The probe spawns `curl` as a subprocess (never a Python-level network
client -- see `tests/test_handoff_safety_contract_enforcement.py` INVARIANT
2), so every test here fakes the `subprocess.run`-shaped `runner` callable;
none of them may spawn a real process or reach a real socket.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.local_store import FileLockTimeout, atomic_write_json, read_json_object
from omh.maintenance.update_check import (
    DEFAULT_UPDATE_CHECK_INTERVAL_HOURS,
    DEFAULT_UPDATE_CHECK_MODE,
    MAX_UPDATE_CHECK_INTERVAL_HOURS,
    MIN_UPDATE_CHECK_INTERVAL_HOURS,
    UPDATE_CHECK_MODES,
    acquire_auto_update_lock,
    evaluate_update_check,
    fetch_remote_main_identity,
    format_notice_line,
    local_installed_channel,
    local_installed_commit,
    read_update_check_cache,
    read_update_check_policy,
    record_remote_commit_for_install,
    refresh_cache_after_auto_update,
    update_check_cache_path,
    update_check_policy_recorded,
    write_update_check_policy,
)
from omh.maintenance.update_check_state import write_update_check_cache
from omh.paths import OmhPaths


def _paths(root: Path) -> OmhPaths:
    resolved = root.resolve()
    return OmhPaths(resolved / ".omh", resolved / ".hermes")


def _http_stdout(status: int, *, etag: str = "", sha: str | None = None) -> str:
    header_lines = [f"HTTP/2 {status}"]
    if etag:
        header_lines.append(f"etag: {etag}")
    body = json.dumps({"sha": sha}) if sha is not None else ""
    return "\n".join(header_lines) + "\n\n" + body


def _ok_runner(sha: str, *, etag: str = '"abc"', calls: list[object] | None = None):
    """Fake curl: a readable head, and a verified fast-forward compare.

    Since the issue #1282 contract, `behind` is emitted only for a verified
    `fast_forward`, so the compare read answers `status: ahead`; every other
    URL (the head/metadata probe) answers with the head payload.
    """

    def runner(argv, timeout=None):
        if calls is not None:
            calls.append(argv)
        if any("/compare/" in str(arg) for arg in argv):
            stdout = "HTTP/2 200\n\n" + json.dumps({"status": "ahead", "ahead_by": 1, "behind_by": 0})
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=_http_stdout(200, etag=etag, sha=sha), stderr="")

    return runner


def _not_modified_runner(etag: str = '"abc"'):
    def runner(argv, timeout=None):
        return subprocess.CompletedProcess(argv, 0, stdout=_http_stdout(304, etag=etag), stderr="")

    return runner


def _raising_runner(exc: BaseException):
    def runner(argv, timeout=None):
        raise exc

    return runner


def _refusing_runner():
    def runner(argv, timeout=None):  # pragma: no cover - fails the test if reached
        raise AssertionError("no subprocess spawn is allowed here")

    return runner


def _write_local_commit(paths: OmhPaths, sha: str) -> None:
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths.runtime_state_path, {"release_source_commit": sha})


class UpdateCheckPolicyTests(unittest.TestCase):
    def test_default_policy_is_off_with_the_24h_interval(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            policy = read_update_check_policy(paths)
            self.assertEqual(policy["mode"], DEFAULT_UPDATE_CHECK_MODE)
            self.assertEqual(policy["mode"], "off")
            self.assertEqual(policy["interval_hours"], DEFAULT_UPDATE_CHECK_INTERVAL_HOURS)

    def test_write_then_read_round_trips_and_preserves_other_profile_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.omh_home.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths.setup_profile_path, {"unrelated": "kept"})
            policy = write_update_check_policy(paths, mode="notify", interval_hours=6)
            self.assertEqual(policy["mode"], "notify")
            self.assertEqual(policy["interval_hours"], 6.0)
            self.assertEqual(read_update_check_policy(paths), policy)
            profile = read_json_object(paths.setup_profile_path)
            self.assertEqual(profile["unrelated"], "kept")

    def test_write_rejects_unknown_mode_and_non_positive_interval(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with self.assertRaises(ValueError):
                write_update_check_policy(paths, mode="sometimes")
            with self.assertRaises(ValueError):
                write_update_check_policy(paths, interval_hours=0)
            with self.assertRaises(ValueError):
                write_update_check_policy(paths, interval_hours=-4)

    def test_every_mode_is_a_recognized_choice(self) -> None:
        self.assertEqual(UPDATE_CHECK_MODES, ("off", "notify", "auto"))

    def test_recorded_separates_never_asked_from_answered_off(self) -> None:
        """The distinction `read_update_check_policy` cannot make.

        Both homes below resolve to mode `off`. Only the record says which of
        them was answered, which is what lets `omh setup` ask the question
        once instead of on every interactive run.
        """
        with TemporaryDirectory() as tmp:
            never_asked = _paths(Path(tmp) / "never")
            answered_off = _paths(Path(tmp) / "answered")
            write_update_check_policy(answered_off, mode="off")

            self.assertEqual(read_update_check_policy(never_asked)["mode"], "off")
            self.assertEqual(read_update_check_policy(answered_off)["mode"], "off")
            self.assertFalse(update_check_policy_recorded(never_asked))
            self.assertTrue(update_check_policy_recorded(answered_off))

    def test_recorded_is_true_for_every_mode_and_false_for_junk(self) -> None:
        for mode in UPDATE_CHECK_MODES:
            with self.subTest(mode=mode), TemporaryDirectory() as tmp:
                paths = _paths(Path(tmp))
                write_update_check_policy(paths, mode=mode)
                self.assertTrue(update_check_policy_recorded(paths))
        # A value nothing in OMH wrote reads as unanswered, which is what the
        # policy reader already does with it -- it resolves such a record to
        # the shipped default rather than honouring it.
        for junk in ("sometimes", "", None, [], {"interval_hours": 6}, {"mode": "OFF"}):
            with self.subTest(junk=junk), TemporaryDirectory() as tmp:
                paths = _paths(Path(tmp))
                paths.omh_home.mkdir(parents=True, exist_ok=True)
                atomic_write_json(paths.setup_profile_path, {"update_check": junk})
                self.assertFalse(update_check_policy_recorded(paths))
                self.assertEqual(read_update_check_policy(paths)["mode"], DEFAULT_UPDATE_CHECK_MODE)

    def test_recorded_is_false_when_no_profile_exists_at_all(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            self.assertFalse(paths.setup_profile_path.exists())
            self.assertFalse(update_check_policy_recorded(paths))


class FetchRemoteMainIdentityTests(unittest.TestCase):
    def test_success_returns_sha_and_etag(self) -> None:
        result = fetch_remote_main_identity(runner=_ok_runner("deadbeef" * 5))
        self.assertTrue(result.ok)
        self.assertEqual(result.sha, "deadbeef" * 5)
        self.assertEqual(result.etag, '"abc"')
        self.assertFalse(result.not_modified)

    def test_not_modified_304_is_ok_without_a_new_sha(self) -> None:
        result = fetch_remote_main_identity(etag='"abc"', runner=_not_modified_runner('"abc"'))
        self.assertTrue(result.ok)
        self.assertTrue(result.not_modified)
        self.assertIsNone(result.sha)

    def test_timeout_is_a_clean_failure_not_an_exception(self) -> None:
        result = fetch_remote_main_identity(
            runner=_raising_runner(subprocess.TimeoutExpired(cmd=["curl"], timeout=1.5))
        )
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)

    def test_curl_missing_is_a_clean_failure(self) -> None:
        result = fetch_remote_main_identity(runner=_raising_runner(FileNotFoundError("curl not found")))
        self.assertFalse(result.ok)

    def test_nonzero_exit_is_a_clean_failure(self) -> None:
        def runner(argv, timeout=None):
            return subprocess.CompletedProcess(argv, 6, stdout="", stderr="curl: (6) Could not resolve host")

        result = fetch_remote_main_identity(runner=runner)
        self.assertFalse(result.ok)
        self.assertIn("resolve host", result.error or "")

    def test_http_error_other_than_304_is_a_clean_failure(self) -> None:
        def runner(argv, timeout=None):
            return subprocess.CompletedProcess(argv, 0, stdout=_http_stdout(500), stderr="")

        result = fetch_remote_main_identity(runner=runner)
        self.assertFalse(result.ok)

    def test_malformed_json_body_is_a_clean_failure(self) -> None:
        def runner(argv, timeout=None):
            return subprocess.CompletedProcess(argv, 0, stdout="HTTP/2 200\n\nnot json", stderr="")

        result = fetch_remote_main_identity(runner=runner)
        self.assertFalse(result.ok)

    def test_missing_sha_field_is_a_clean_failure(self) -> None:
        def runner(argv, timeout=None):
            return subprocess.CompletedProcess(argv, 0, stdout="HTTP/2 200\n\n{}", stderr="")

        result = fetch_remote_main_identity(runner=runner)
        self.assertFalse(result.ok)

    def test_non_full_sha_is_a_clean_failure(self) -> None:
        for sha in ("deadbeef", "g" * 40, "\x1b]8;;file:///Users/alice/.ssh/id_rsa\x07"):
            with self.subTest(sha=sha):
                result = fetch_remote_main_identity(runner=_ok_runner(sha))
                self.assertFalse(result.ok)
                self.assertIsNone(result.sha)
                self.assertIn("invalid sha", result.error or "")

    def test_the_argv_invokes_curl_with_the_commits_endpoint(self) -> None:
        calls: list[object] = []
        fetch_remote_main_identity(runner=_ok_runner("a" * 40, calls=calls))
        self.assertEqual(len(calls), 1)
        argv = calls[0]
        self.assertEqual(argv[0], "curl")
        self.assertIn("https://api.github.com/repos/rlaope/oh-my-hermes/commits/main", argv)


class EvaluateUpdateCheckTests(unittest.TestCase):
    def test_cache_redacts_and_refuses_malformed_remote_commit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            path = update_check_cache_path(paths)
            path.parent.mkdir(parents=True)
            unsafe = "\x1b]8;;file:///Users/alice/.ssh/id_rsa\x07"
            atomic_write_json(
                path,
                {
                    "schema_version": "omh_update_check_cache/v2",
                    "remote_commit": unsafe,
                    "outcome": "behind",
                },
            )

            self.assertEqual(read_update_check_cache(paths)["remote_commit"], "")
            with self.assertRaisesRegex(ValueError, "40-character hexadecimal"):
                write_update_check_cache(paths, {"remote_commit": unsafe})

    def test_off_mode_makes_zero_network_attempts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            result = evaluate_update_check(paths, runner=_refusing_runner())
            self.assertEqual(result["mode"], "off")
            self.assertEqual(result["outcome"], "skipped_off")
            self.assertFalse(result["checked"])
            self.assertFalse(result["should_auto_update"])

    def test_no_local_identity_is_inconclusive_not_a_false_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify")
            result = evaluate_update_check(paths, runner=_ok_runner("a" * 40))
            self.assertEqual(result["outcome"], "inconclusive")
            self.assertEqual(format_notice_line(result), "OMH update check inconclusive -- run `omh update`.")

    def test_matching_identity_is_up_to_date(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify")
            _write_local_commit(paths, "a" * 40)
            result = evaluate_update_check(paths, runner=_ok_runner("a" * 40))
            self.assertEqual(result["outcome"], "up_to_date")
            self.assertEqual(format_notice_line(result), "")

    def test_differing_identity_is_behind_and_formats_a_short_notice(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify")
            _write_local_commit(paths, "a" * 40)
            result = evaluate_update_check(paths, runner=_ok_runner("b" * 40))
            self.assertEqual(result["outcome"], "behind")
            notice = format_notice_line(result)
            self.assertIn("OMH update available: aaaaaaa -> bbbbbbb", notice)
            self.assertIn("omh update", notice)

    def test_auto_mode_flags_should_auto_update_only_when_behind(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="auto")
            _write_local_commit(paths, "a" * 40)
            behind = evaluate_update_check(paths, runner=_ok_runner("b" * 40))
            self.assertTrue(behind["should_auto_update"])

            _write_local_commit(paths, "b" * 40)
            up_to_date = evaluate_update_check(paths, force=True, runner=_ok_runner("b" * 40))
            self.assertFalse(up_to_date["should_auto_update"])

    def test_cached_behind_within_the_interval_never_flags_a_repeat_auto_update(self) -> None:
        # Regression for the "auto mode re-updates every launch" defect: a
        # cached "behind" outcome served without a fresh probe (interval not
        # elapsed) must never set should_auto_update on its own -- only a
        # fresh probe in this same call may.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="auto", interval_hours=24)
            _write_local_commit(paths, "a" * 40)
            first = evaluate_update_check(paths, runner=_ok_runner("b" * 40))
            self.assertTrue(first["checked"])
            self.assertTrue(first["should_auto_update"])

            second = evaluate_update_check(paths, runner=_refusing_runner())
            self.assertFalse(second["checked"])
            self.assertEqual(second["outcome"], "behind")
            self.assertFalse(second["should_auto_update"])

            third = evaluate_update_check(paths, runner=_refusing_runner())
            self.assertFalse(third["checked"])
            self.assertFalse(third["should_auto_update"])

    def test_network_failure_is_a_silent_skip_that_keeps_the_previous_outcome(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify")
            _write_local_commit(paths, "a" * 40)
            first = evaluate_update_check(paths, runner=_ok_runner("b" * 40))
            self.assertEqual(first["outcome"], "behind")

            second = evaluate_update_check(
                paths, force=True, runner=_raising_runner(subprocess.TimeoutExpired(cmd=["curl"], timeout=1.5))
            )
            self.assertEqual(second["outcome"], "behind")
            self.assertTrue(second["checked"])
            cache = read_update_check_cache(paths)
            self.assertEqual(cache["outcome"], "behind")

    def test_interval_not_elapsed_serves_the_cache_without_a_network_attempt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify", interval_hours=24)
            _write_local_commit(paths, "a" * 40)
            first = evaluate_update_check(paths, runner=_ok_runner("b" * 40))
            self.assertTrue(first["checked"])

            second = evaluate_update_check(paths, runner=_refusing_runner())
            self.assertFalse(second["checked"])
            self.assertEqual(second["outcome"], "behind")

    def test_elapsed_interval_triggers_a_fresh_probe(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify", interval_hours=1)
            _write_local_commit(paths, "a" * 40)
            now = datetime.now(timezone.utc)
            evaluate_update_check(paths, now=now, runner=_ok_runner("b" * 40))
            later = now + timedelta(hours=2)
            result = evaluate_update_check(paths, now=later, runner=_ok_runner("c" * 40))
            self.assertTrue(result["checked"])
            self.assertEqual(result["remote_commit"], "c" * 40)

    def test_not_modified_reuses_the_cached_remote_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify", interval_hours=1)
            _write_local_commit(paths, "a" * 40)
            now = datetime.now(timezone.utc)
            evaluate_update_check(paths, now=now, runner=_ok_runner("b" * 40))

            later = now + timedelta(hours=2)
            result = evaluate_update_check(paths, now=later, runner=_not_modified_runner())
            self.assertEqual(result["remote_commit"], "b" * 40)
            self.assertEqual(result["outcome"], "behind")


class LocalInstalledCommitTests(unittest.TestCase):
    def test_absent_state_reads_as_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            self.assertEqual(local_installed_commit(paths), "")

    def test_record_remote_commit_for_install_is_best_effort(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            self.assertEqual(
                record_remote_commit_for_install(
                    paths, runner=_raising_runner(subprocess.TimeoutExpired(cmd=["curl"], timeout=1.5))
                ),
                "",
            )
            self.assertEqual(record_remote_commit_for_install(paths, runner=_ok_runner("c" * 40)), "c" * 40)


class AutoUpdateLockTests(unittest.TestCase):
    def test_lock_is_exclusive_and_non_blocking(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with acquire_auto_update_lock(paths):
                with self.assertRaises(FileLockTimeout):
                    with acquire_auto_update_lock(paths):
                        pass

    def test_lock_path_is_the_cache_sidecar(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            cache_path = update_check_cache_path(paths)
            with acquire_auto_update_lock(paths):
                sidecar = cache_path.with_name(f".{cache_path.name}.lock")
                self.assertTrue(sidecar.exists())


class LocalInstalledChannelTests(unittest.TestCase):
    def test_absent_state_reads_as_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            self.assertEqual(local_installed_channel(paths), "")

    def test_reads_the_recorded_channel(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(paths.runtime_state_path, {"release_channel": "stable"})
            self.assertEqual(local_installed_channel(paths), "stable")


class FormatNoticeLineChannelAwarenessTests(unittest.TestCase):
    def test_inconclusive_on_a_non_preview_channel_names_the_channel_instead_of_suggesting_update(self) -> None:
        notice = format_notice_line({"outcome": "inconclusive", "channel": "stable"})
        self.assertIn("stable", notice)
        self.assertNotIn("omh update", notice)

    def test_inconclusive_with_no_recorded_channel_keeps_the_actionable_wording(self) -> None:
        notice = format_notice_line({"outcome": "inconclusive", "channel": ""})
        self.assertEqual(notice, "OMH update check inconclusive -- run `omh update`.")

    def test_inconclusive_on_the_preview_channel_keeps_the_actionable_wording(self) -> None:
        notice = format_notice_line({"outcome": "inconclusive", "channel": "preview"})
        self.assertEqual(notice, "OMH update check inconclusive -- run `omh update`.")


class RefreshCacheAfterAutoUpdateTests(unittest.TestCase):
    def test_marks_up_to_date_when_local_commit_now_matches_the_cached_remote(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="auto")
            _write_local_commit(paths, "a" * 40)
            evaluate_update_check(paths, runner=_ok_runner("b" * 40))

            _write_local_commit(paths, "b" * 40)  # simulate the auto-update converging
            refreshed = refresh_cache_after_auto_update(paths)
            self.assertEqual(refreshed["outcome"], "up_to_date")
            self.assertEqual(read_update_check_cache(paths)["outcome"], "up_to_date")

    def test_marks_inconclusive_when_the_local_identity_still_does_not_match(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="auto")
            _write_local_commit(paths, "a" * 40)
            evaluate_update_check(paths, runner=_ok_runner("b" * 40))

            refreshed = refresh_cache_after_auto_update(paths)  # local commit unchanged
            self.assertEqual(refreshed["outcome"], "inconclusive")


class IntervalHoursBoundsTests(unittest.TestCase):
    def test_write_rejects_an_interval_below_the_minimum(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with self.assertRaises(ValueError):
                write_update_check_policy(paths, interval_hours=MIN_UPDATE_CHECK_INTERVAL_HOURS / 2)

    def test_write_rejects_an_interval_above_the_maximum(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with self.assertRaises(ValueError):
                write_update_check_policy(paths, interval_hours=MAX_UPDATE_CHECK_INTERVAL_HOURS * 2)

    def test_write_rejects_an_infinite_interval(self) -> None:
        # Regression: `timedelta(hours=...)` raises OverflowError on `inf`,
        # which would otherwise crash `_interval_elapsed` on every launch.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with self.assertRaises(ValueError):
                write_update_check_policy(paths, interval_hours=float("inf"))

    def test_read_ignores_a_stored_out_of_range_interval_and_falls_back_to_default(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.omh_home.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                paths.setup_profile_path,
                {"update_check": {"mode": "notify", "interval_hours": 1e18}},
            )
            policy = read_update_check_policy(paths)
            self.assertEqual(policy["interval_hours"], DEFAULT_UPDATE_CHECK_INTERVAL_HOURS)


class CorruptDiskStateNeverRaisesTests(unittest.TestCase):
    """Regression for the P0 launch traceback: a corrupt on-disk document must
    read the same as an absent one everywhere on the update-check path."""

    def test_corrupt_setup_profile_reads_as_the_default_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.omh_home.mkdir(parents=True, exist_ok=True)
            paths.setup_profile_path.write_text("{not json", encoding="utf-8")
            policy = read_update_check_policy(paths)
            self.assertEqual(policy["mode"], DEFAULT_UPDATE_CHECK_MODE)
            self.assertEqual(policy["interval_hours"], DEFAULT_UPDATE_CHECK_INTERVAL_HOURS)

    def test_corrupt_cache_reads_as_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            update_check_cache_path(paths).write_text("{not json", encoding="utf-8")
            self.assertEqual(read_update_check_cache(paths), {})

    def test_state_json_as_a_json_array_reads_as_no_local_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            paths.runtime_state_path.write_text("[]", encoding="utf-8")
            self.assertEqual(local_installed_commit(paths), "")
            self.assertEqual(local_installed_channel(paths), "")

    def test_evaluate_update_check_never_raises_on_a_corrupt_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_update_check_policy(paths, mode="notify")
            paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            update_check_cache_path(paths).write_text("not json at all", encoding="utf-8")
            result = evaluate_update_check(paths, runner=_ok_runner("b" * 40))
            self.assertIn(result["outcome"], ("behind", "up_to_date", "inconclusive"))


if __name__ == "__main__":
    unittest.main()
