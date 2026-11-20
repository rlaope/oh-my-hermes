"""Regression: a route write must not drop unrelated config keys (#2998).

`hermes config set` (the Hermes Agent CLI, outside OMH's lock) can add an
unrelated key between the route writer's validation snapshot and its rename.
The pre-fix writer replaced the file from the stale snapshot and silently
dropped the key: the observed case was `context_file_max_chars` reset to
unset, repeatedly. The fix re-reads the latest config and re-applies only
the delegation delta just before the rename, and skips byte-identical
writes, so the needless per-dispatch rewrite is gone too.

The race classes below pin the carry's review fixes: every check runs on
the one read the write is built from, drift in the routable keys is
refused, and the last stamp check sits right before the rename. An edit
landing after that check is still lost; nothing here promises otherwise.

Every test passes an explicit temporary home. Nothing here may read or
write the developer's own `~/.hermes` or `~/.omh`.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from omh.plugin_bundle.omh import delegation_route_restore, delegation_routing
from omh.plugin_bundle.omh.delegation_route_restore import (
    load_route_restore_record,
    restore_delegation_baseline,
    write_route_with_baseline,
)
from omh.plugin_bundle.omh.delegation_routing import (
    read_delegation_route,
    write_delegation_route,
)


class RouteWriteLostUpdateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "home"
        self.home.mkdir()
        self.config = self.home / "config.yaml"

    def _write_config(self, text: str) -> None:
        self.config.write_text(text, encoding="utf-8")

    def test_skip_byte_identical(self):
        text = (
            "context_file_max_chars: 60000\n"
            "delegation:\n"
            "  model: 'm1'\n"
            "  provider: 'p1'\n"
        )
        self._write_config(text)
        inode_before = self.config.stat().st_ino
        result = write_delegation_route(self.home, model="m1", provider="p1")
        self.assertEqual(result["status"], "routed")
        self.assertEqual(self.config.stat().st_ino, inode_before)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_concurrent_pin_preserved(self):
        no_pin = "delegation:\n  model: 'm1'\n  provider: 'p1'\n"
        self._write_config(no_pin)
        real_read = delegation_routing._read_config_snapshot
        calls = {"n": 0}

        def racing_read(path):
            calls["n"] += 1
            if calls["n"] == 2:
                # A concurrent `hermes config set` adds the pin after the
                # validation snapshot but before the write's fresh read.
                self._write_config("context_file_max_chars: 60000\n" + no_pin)
            return real_read(path)

        with mock.patch.object(
            delegation_routing, "_read_config_snapshot", racing_read
        ):
            result = write_delegation_route(self.home, model="m2", provider="p1")
        self.assertEqual(result["status"], "routed")
        final = self.config.read_text(encoding="utf-8")
        self.assertIn("context_file_max_chars: 60000", final)
        self.assertIn("model: 'm2'", final)

    def test_unrelated_bytes_preserved(self):
        text = (
            "# comment\n"
            "context_file_max_chars: 60000\n"
            "model:\n"
            "  default: 'main'\n"
            "delegation:\n"
            "  model: 'm1'\n"
            "  base_url: 'http://x'\n"
        )
        self._write_config(text)
        result = write_delegation_route(
            self.home, model="m2", provider="p2", reasoning_effort="high"
        )
        self.assertEqual(result["status"], "routed")
        final = self.config.read_text(encoding="utf-8")
        for needle in (
            "context_file_max_chars: 60000",
            "# comment",
            "default: 'main'",
            "model: 'm2'",
            "provider: 'p2'",
            "reasoning_effort: 'high'",
            "base_url: 'http://x'",
        ):
            self.assertIn(needle, final)

    def test_clear_removes_only_routable_keys(self):
        text = (
            "context_file_max_chars: 60000\n"
            "delegation:\n"
            "  model: 'm1'\n"
            "  provider: 'p1'\n"
        )
        self._write_config(text)
        result = write_delegation_route(self.home, clear=True)
        self.assertEqual(result["status"], "cleared")
        final = self.config.read_text(encoding="utf-8")
        self.assertIn("context_file_max_chars: 60000", final)
        self.assertNotIn("model: 'm1'", final)
        self.assertNotIn("provider: 'p1'", final)



ENDPOINT = "http://127.0.0.1:8000/v1"
PARENT = "model:\n  default: parent-model\n  provider: openrouter\n"
START = PARENT + "delegation:\n  model: 'start'\n  provider: 'og'\n"
PERSON_PIN = PARENT + "delegation:\n  model: 'person-pin'\n  provider: 'og'\n"


class RouteWriteRaceTestCase(unittest.TestCase):
    """Deterministic interleavings around the writer's reads and its rename.

    The competing edit stands in for `hermes config set`, which takes no
    OMH lock. Each test checks both what the writer reported and what is
    left in `config.yaml` (and in the restore record where one exists).
    """

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.home = root / "hermes"
        self.omh_home = root / "omh"
        managed = root / "managed"
        for directory in (self.home, self.omh_home, managed):
            directory.mkdir()
        self.config = self.home / "config.yaml"
        # An empty managed layer of the test's own, never /etc/hermes.
        environment = mock.patch.dict(os.environ, {"HERMES_MANAGED_DIR": str(managed)})
        environment.start()
        self.addCleanup(environment.stop)

    def write(self, text: str) -> None:
        self.config.write_text(text, encoding="utf-8")

    def text(self) -> str:
        return self.config.read_text(encoding="utf-8")

    def temp_files(self) -> list[str]:
        return sorted(p.name for p in self.home.iterdir() if p.name.startswith(".omh-delegation-route-"))

    @contextmanager
    def edit_after_first_check(self, text: str):
        """Rewrite the config right after the writer's first stamp check.

        That check follows the writer's validation read, so the edit lands
        exactly where the review placed it: after validation, before the
        write.
        """
        real = delegation_routing._file_signature
        done = False

        def signature_then_edit(path):
            nonlocal done
            result = real(path)
            if not done:
                done = True
                self.write(text)
            return result

        with mock.patch.object(delegation_routing, "_file_signature", signature_then_edit):
            yield

    @contextmanager
    def edit_after_read(self, call: int, text: str):
        """Rewrite the config right after the writer's `call`-th read returns."""
        real = delegation_routing._read_config_snapshot
        calls = 0

        def read_then_edit(path):
            nonlocal calls
            calls += 1
            result = real(path)
            if calls == call:
                self.write(text)
            return result

        with mock.patch.object(delegation_routing, "_read_config_snapshot", read_then_edit):
            yield


class ConditionalWriteTest(RouteWriteRaceTestCase):
    """Finding 1: `expected_previous` holds on every read the write uses."""

    def test_a_fallback_refuses_a_route_pinned_after_its_check(self) -> None:
        self.write(START)
        foreign = "context_file_max_chars: 60000\n" + PERSON_PIN
        with self.edit_after_first_check(foreign):
            result = write_delegation_route(
                self.home, model="next", provider="og",
                expected_previous={"model": "start", "provider": "og"},
            )
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(self.text(), foreign)
        self.assertEqual(self.temp_files(), [])

    def test_a_conditional_clear_refuses_a_route_pinned_after_its_check(self) -> None:
        self.write(START)
        with self.edit_after_first_check(PERSON_PIN):
            result = write_delegation_route(
                self.home, clear=True, expected_previous={"model": "start", "provider": "og"},
            )
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(self.text(), PERSON_PIN)

    def test_an_unrelated_edit_with_the_expected_route_unchanged_is_merged(self) -> None:
        self.write(START)
        with self.edit_after_first_check("context_file_max_chars: 60000\n" + START):
            result = write_delegation_route(
                self.home, model="next", provider="og",
                expected_previous={"model": "start", "provider": "og"},
            )
        self.assertEqual(result["status"], "routed", result)
        self.assertIn("context_file_max_chars: 60000\n", self.text())
        self.assertEqual(read_delegation_route(self.home), {"model": "next", "provider": "og"})

    def test_an_unconditional_set_refuses_a_route_pinned_after_its_check(self) -> None:
        # Drift in the routable keys is not merged: writing over it would
        # erase the pin and report a `previous` that was never replaced.
        self.write(START)
        with self.edit_after_first_check(PERSON_PIN):
            result = write_delegation_route(self.home, model="next", provider="og")
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(self.text(), PERSON_PIN)

    def test_a_restore_refuses_and_keeps_its_record_when_the_route_moved(self) -> None:
        self.write(PARENT + "delegation:\n  model: 'person-model'\n")
        routed = write_route_with_baseline(
            self.home, omh_home=self.omh_home, session_id="s1", task_id="t1",
            model="routed", provider="og",
        )
        self.assertEqual(routed["status"], "routed", routed)
        record = load_route_restore_record(self.omh_home)
        self.assertTrue(record)
        with self.edit_after_first_check(PERSON_PIN):
            restored = restore_delegation_baseline(
                self.home, omh_home=self.omh_home, trigger="session_end",
                require_writer_session="s1",
            )
        self.assertEqual(restored["status"], "error", restored)
        self.assertEqual(self.text(), PERSON_PIN)
        self.assertEqual(load_route_restore_record(self.omh_home), record)


class BaselineFromAcceptedReadTest(RouteWriteRaceTestCase):
    """Finding 2: the baseline is the route the write really replaced."""

    @contextmanager
    def pin_before_the_writer(self, text: str):
        real = delegation_route_restore.write_delegation_route

        def pin_then_write(*args, **kwargs):
            self.write(text)
            return real(*args, **kwargs)

        with mock.patch.object(delegation_route_restore, "write_delegation_route", pin_then_write):
            yield

    def route(self, model: str) -> dict:
        return write_route_with_baseline(
            self.home, omh_home=self.omh_home, session_id="s1", task_id="t1",
            model=model, provider="og",
        )

    def restore(self) -> dict:
        return restore_delegation_baseline(
            self.home, omh_home=self.omh_home, trigger="session_end", require_writer_session="s1",
        )

    def test_a_pin_made_before_the_write_is_what_turn_end_puts_back(self) -> None:
        self.write(START)
        with self.pin_before_the_writer(PERSON_PIN):
            routed = self.route("next")
        self.assertEqual(routed["status"], "routed", routed)
        self.assertEqual(load_route_restore_record(self.omh_home)["baseline"],
                         {"model": "person-pin", "provider": "og"})
        self.assertIn(self.restore()["status"], ("restored", "cleared"))
        self.assertEqual(read_delegation_route(self.home), {"model": "person-pin", "provider": "og"})

    def test_a_record_naming_only_the_stale_route_is_not_retained(self) -> None:
        self.write(PARENT)
        self.assertEqual(self.route("start")["status"], "routed")
        with self.pin_before_the_writer(PERSON_PIN):
            routed = self.route("next")
        self.assertEqual(routed["status"], "routed", routed)
        self.assertTrue(routed["route_restore"].startswith("baseline_recaptured"), routed)
        self.restore()
        self.assertEqual(read_delegation_route(self.home), {"model": "person-pin", "provider": "og"})


class GuardOnOneReadTest(RouteWriteRaceTestCase):
    """Finding 3: the endpoint guard judges one state of the file."""

    BEFORE = PARENT + f"delegation:\n  provider: 'og'\n  base_url: {ENDPOINT}\n"

    def test_a_provider_turned_native_after_the_check_is_refused(self) -> None:
        self.write(self.BEFORE)
        native = PARENT + f"delegation:\n  provider: 'bedrock'\n  base_url: {ENDPOINT}\n"
        with self.edit_after_first_check(native):
            result = write_delegation_route(self.home, model="local-llama", guard_route_endpoint=True)
        self.assertEqual(result.get("reason"), "native_provider_removed", result)
        self.assertEqual(self.text(), native)

    def test_an_unrelated_edit_with_a_non_native_provider_routes(self) -> None:
        self.write(self.BEFORE)
        edited = "context_file_max_chars: 60000\n" + self.BEFORE
        with self.edit_after_first_check(edited):
            result = write_delegation_route(self.home, model="local-llama", guard_route_endpoint=True)
        self.assertEqual(result["status"], "routed", result)
        self.assertIn("context_file_max_chars: 60000\n", self.text())
        self.assertEqual(read_delegation_route(self.home), {"model": "local-llama"})


class NoOpSuccessTest(RouteWriteRaceTestCase):
    """Finding 4: a write with nothing to change still confirms the file."""

    def test_a_change_after_the_candidate_read_is_not_reported_as_routed(self) -> None:
        self.write(START)
        inode = self.config.stat().st_ino
        # Read 1 validates, read 2 is the candidate; the pin lands after it.
        with self.edit_after_read(2, PERSON_PIN):
            result = write_delegation_route(self.home, model="start", provider="og")
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(self.text(), PERSON_PIN)
        self.assertEqual(self.config.stat().st_ino, inode)


class LastCheckBeforeReplaceTest(RouteWriteRaceTestCase):
    """Finding 5: mode handling comes before the final stamp check.

    An edit made after that final check and before `os.replace` is still
    lost (Hermes' CLI takes no OMH lock); nothing here promises otherwise.
    """

    def test_an_edit_during_the_temp_file_chmod_survives_a_retry(self) -> None:
        self.write(START)
        self.config.chmod(0o640)
        # Windows keeps only the read-only bit; compare with whatever mode the file really has.
        mode = self.config.stat().st_mode & 0o777
        real_chmod = os.chmod
        done = False

        def edit_then_chmod(path, mode, *args, **kwargs):
            nonlocal done
            if not done and str(path).startswith(str(self.home)):
                done = True
                self.write("context_file_max_chars: 60000\n" + START)
            return real_chmod(path, mode, *args, **kwargs)

        with mock.patch.object(delegation_routing.os, "chmod", edit_then_chmod):
            result = write_delegation_route(self.home, model="next", provider="og")
        self.assertTrue(done)
        self.assertEqual(result["status"], "routed", result)
        self.assertIn("context_file_max_chars: 60000\n", self.text())
        self.assertEqual(read_delegation_route(self.home), {"model": "next", "provider": "og"})
        self.assertEqual(self.config.stat().st_mode & 0o777, mode)
        self.assertEqual(self.temp_files(), [])

    def test_a_file_that_keeps_changing_is_refused_without_leftovers(self) -> None:
        self.write(START)
        real = delegation_routing._read_config_snapshot
        calls = 0

        def read_then_edit(path):
            nonlocal calls
            calls += 1
            result = real(path)
            if calls > 1:
                self.write(f"unrelated_{calls}: 1\n" + START)
            return result

        with mock.patch.object(delegation_routing, "_read_config_snapshot", read_then_edit):
            result = write_delegation_route(self.home, model="next", provider="og")
        self.assertEqual(result, {"status": "error", "error": "config kept changing during route update"})
        self.assertEqual(self.text(), f"unrelated_{calls}: 1\n" + START)
        self.assertEqual(self.temp_files(), [])

    def test_a_same_size_rewrite_within_the_timestamp_tick_is_still_seen(self) -> None:
        # Windows CI: NTFS kept the write time across an in-place same-size
        # rewrite, so a stamp-only check took the edited file for unchanged.
        self.write("unrelated: 0\n" + START)
        real = delegation_routing._read_config_snapshot
        calls = 0

        def read_then_edit_keeping_the_stamp(path):
            nonlocal calls
            calls += 1
            result = real(path)
            if calls > 1:
                stamp = self.config.stat()
                self.write(f"unrelated: {calls % 10}\n" + START)  # same size, same inode
                os.utime(self.config, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            return result

        with mock.patch.object(delegation_routing, "_read_config_snapshot", read_then_edit_keeping_the_stamp):
            result = write_delegation_route(self.home, model="next", provider="og")
        self.assertEqual(result, {"status": "error", "error": "config kept changing during route update"})
        self.assertNotIn("model: 'next'", self.text())
        self.assertEqual(self.temp_files(), [])

    def test_a_failed_rename_reports_an_error_and_leaves_no_temp_file(self) -> None:
        self.write(START)
        with mock.patch.object(delegation_routing.os, "replace", side_effect=PermissionError("denied")):
            result = write_delegation_route(self.home, model="next", provider="og")
        self.assertEqual(result, {"status": "error", "error": "config write failed: PermissionError"})
        self.assertEqual(self.text(), START)
        self.assertEqual(self.temp_files(), [])


if __name__ == "__main__":
    unittest.main()
