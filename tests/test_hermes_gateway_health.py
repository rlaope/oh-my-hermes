"""Hermes' gateway needs a restart: the lines the OMH TUI's launch and `omh doctor` show, from its files alone.

Two findings. `gateway_state.json`'s `session_store.status` is Hermes' one
aggregate over every store the gateway holds; `"unavailable"` means it
refuses state.db writes (often a profile deleted while it was served). And a
gateway whose last recorded start precedes the OMH plugin bundle's
`installed_at` still runs the old plugin code. Both are said as Hermes', with
the restart command, and neither is acted on. A third state is a restart
under way: `gateway_state` "draining", when Hermes waits for running turns
and refuses new messages; the time left is read from the restart-wait line
Hermes logs every 30 s, only while that line is fresh. The record shape is
the owner machine's on 2026-11-02 (Hermes 0.22.5), trimmed.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from omh.maintenance.doctor import _hermes_gateway_checks
from omh.maintenance.hermes_gateway import (
    DRAIN_LOG_FRESH_SECONDS,
    GATEWAY_STATE_BYTES,
    NOTICE_DRAINING,
    NOTICE_STALE_BUNDLE,
    NOTICE_STORE_UNAVAILABLE,
    gateway_drain,
    gateway_notice_home,
    gateway_notices,
    gateway_session_store_status,
)
from omh.paths import OmhPaths

INSTALLED_AT = "2026-11-02T02:01:18Z"
INSTALLED_EPOCH = datetime(2026, 11, 2, 2, 1, 18, tzinfo=UTC).timestamp()
PID = 99981
NOW = datetime(2026, 11, 2, 3, 54, 11, tzinfo=UTC).timestamp()
# One chat unit as Hermes' `_describe_active_work` records it while draining.
UNIT = {"kind": "chat", "session": "agent:kami:discord:thread:1", "pid": PID, "elapsed_s": 1823.3}


def drain_log(home: Path, *lines: tuple[float, str]) -> None:
    """Hermes' gateway.log lines, each stamped as Python logging's asctime in local time."""
    log = home / "logs" / "gateway.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(
        f"{datetime.fromtimestamp(at).strftime('%Y-%m-%d %H:%M:%S')},495 INFO gateway.run: {text}\n" for at, text in lines
    ), encoding="utf-8")


def wait_line(seconds: int, units: int = 1) -> str:
    return (f"Restart deferred: waiting on {units} active work unit(s) (0 wedged and excluded, 0 restart-safe and "
            f"excluded; {seconds}s remaining before force drain): [{UNIT!r}]")


def pid_record(home: Path, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "pid": PID, "kind": "hermes-gateway",
        "argv": ["hermes_cli/main.py", "gateway", "run", "--external-supervisor"],
        "start_time": 179329325070, "hermes_home": str(home),
    }
    record.update(overrides)
    return record


def state_record(home: Path, status: object = "ok", **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        **pid_record(home), "gateway_state": "running", "exit_reason": None, "restart_requested": False,
        "active_agents": 2, "platforms": {}, "session_store": {"status": status},
        "updated_at": "2026-11-02T03:18:26.525775+00:00", "code_version": "0.22.5",
        "served_profiles": ["default", "kami"],
    }
    record.update(overrides)
    return record


def write_home(
    home: Path,
    *,
    state: dict[str, object] | str | bytes | None = None,
    pid: dict[str, object] | None | bool = True,
    starts: list[float] | None = None,
    installed_at: str | None = None,
) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    if pid is True:
        pid = pid_record(home)
    if isinstance(pid, dict):
        (home / "gateway.pid").write_text(json.dumps(pid), encoding="utf-8")
    if isinstance(state, bytes):
        (home / "gateway_state.json").write_bytes(state)
    elif isinstance(state, str):
        (home / "gateway_state.json").write_text(state, encoding="utf-8")
    elif state is not None:
        (home / "gateway_state.json").write_text(json.dumps(state), encoding="utf-8")
    if starts is not None:
        (home / "gateway-starts.log").write_text("".join(f"{value!r}\n" for value in starts), encoding="utf-8")
    if installed_at is not None:
        plugin = home / "plugins" / "omh"
        plugin.mkdir(parents=True, exist_ok=True)
        (plugin / ".omh-plugin-manifest.json").write_text(
            json.dumps({"schema_version": 1, "installed_at": installed_at, "files": []}), encoding="utf-8"
        )
    return home


def kinds(home: Path) -> list[str]:
    _home, label, command = gateway_notice_home(home)
    return [notice.kind for notice in gateway_notices(home, label=label, restart_command=command)]


class SessionStoreStatusTests(unittest.TestCase):
    def test_ok_and_unavailable_are_read_from_the_running_gateways_record(self) -> None:
        with TemporaryDirectory() as tmp:
            ok = write_home(Path(tmp) / "ok", state=state_record(Path(tmp) / "ok"))
            self.assertEqual(gateway_session_store_status(ok), "ok")
            self.assertEqual(kinds(ok), [])
            down = write_home(Path(tmp) / "down", state=state_record(Path(tmp) / "down", "unavailable"))
            self.assertEqual(gateway_session_store_status(down), "unavailable")
            self.assertEqual(kinds(down), [NOTICE_STORE_UNAVAILABLE])

    def test_the_unavailable_line_is_hermes_own_and_names_the_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"))
            [notice] = gateway_notices(home, label="Hermes' gateway", restart_command="hermes gateway restart")
        self.assertEqual(
            notice.text,
            "Hermes' gateway cannot write its session store (Hermes reports it unavailable, often over a deleted "
            "profile it still holds); your saved sessions on disk are fine. Restart it with "
            "`hermes gateway restart`.",
        )
        self.assertEqual(notice.restart_command, "hermes gateway restart")
        self.assertNotIn("OMH", notice.text)

    def test_missing_files_say_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            no_state = write_home(Path(tmp) / "no-state")
            self.assertIsNone(gateway_session_store_status(no_state))
            # A clean stop unlinks gateway.pid; the state file it leaves is not a running gateway.
            stopped = write_home(Path(tmp) / "no-pid", state=state_record(Path(tmp) / "no-pid", "unavailable"), pid=None)
            self.assertIsNone(gateway_session_store_status(stopped))
            self.assertIsNone(gateway_session_store_status(Path(tmp) / "absent"))

    def test_missing_keys_and_odd_shapes_say_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases: dict[str, object] = {
                "no-store-key": {"pid": PID, "gateway_state": "running"},
                "store-not-object": state_record(root, session_store="unavailable"),
                "status-not-text": state_record(root, session_store={"status": ["unavailable"]}),
                "status-empty": state_record(root, session_store={"status": ""}),
                "no-status": state_record(root, session_store={}),
                "list": "[1, 2, 3]",
                "garbage": "{not json",
                "number": "42",
                "not-utf8": b"\xff\xfe\x00{",
                "deep": "[" * 100_000,
            }
            for label, state in cases.items():
                with self.subTest(label):
                    home = root / label
                    if isinstance(state, dict) and "hermes_home" in state:
                        state = {**state, "hermes_home": str(home)}
                    write_home(home, state=state)  # type: ignore[arg-type]
                    self.assertIsNone(gateway_session_store_status(home))
                    self.assertEqual(kinds(home), [])

    def test_an_oversized_record_is_not_one_hermes_wrote(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            record = state_record(home, "unavailable", padding="x" * GATEWAY_STATE_BYTES)
            write_home(home, state=record)
            self.assertIsNone(gateway_session_store_status(home))

    def test_a_record_of_another_home_another_pid_or_a_stopped_gateway_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            elsewhere = write_home(root / "a", state=state_record(root / "other", "unavailable"))
            self.assertIsNone(gateway_session_store_status(elsewhere))
            other_pid = write_home(root / "b", state=state_record(root / "b", "unavailable", pid=PID + 1))
            self.assertIsNone(gateway_session_store_status(other_pid))
            for gone in ("stopped", "startup_failed"):
                with self.subTest(gone):
                    home = write_home(root / gone, state=state_record(root / gone, "unavailable", gateway_state=gone))
                    self.assertIsNone(gateway_session_store_status(home))
            # A pid record of another home is that home's gateway, as Hermes reads it.
            foreign = write_home(root / "c", state=state_record(root / "c", "unavailable"),
                                 pid=pid_record(root / "elsewhere"))
            self.assertIsNone(gateway_session_store_status(foreign))

    def test_a_record_without_a_home_or_pid_is_read_as_this_homes(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            record = state_record(home, "unavailable")
            del record["hermes_home"], record["pid"]
            write_home(home, state=record)
            self.assertEqual(gateway_session_store_status(home), "unavailable")


class StaleBundleTests(unittest.TestCase):
    def test_a_gateway_started_before_the_bundle_install_needs_a_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp)), starts=[INSTALLED_EPOCH - 3 * 86400],
                              installed_at=INSTALLED_AT)
            [notice] = gateway_notices(home, label="Hermes' gateway", restart_command="hermes gateway restart")
        self.assertEqual(notice.kind, NOTICE_STALE_BUNDLE)
        self.assertEqual(
            notice.text,
            "Hermes' gateway started before OMH was updated (last start 2026-10-30T02:01:18Z, OMH plugin installed "
            "2026-11-02T02:01:18Z), so it still runs the old OMH plugin code; restart it with "
            "`hermes gateway restart` to load the new code.",
        )

    def test_a_gateway_started_after_the_install_or_without_evidence_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = write_home(root / "fresh", starts=[INSTALLED_EPOCH + 60], installed_at=INSTALLED_AT)
            self.assertEqual(kinds(fresh), [])
            no_ledger = write_home(root / "no-ledger", installed_at=INSTALLED_AT)
            self.assertEqual(kinds(no_ledger), [])
            no_bundle = write_home(root / "no-bundle", starts=[INSTALLED_EPOCH - 60])
            self.assertEqual(kinds(no_bundle), [])
            no_pid = write_home(root / "no-pid", pid=None, starts=[INSTALLED_EPOCH - 60], installed_at=INSTALLED_AT)
            self.assertEqual(kinds(no_pid), [])
            bad_stamp = write_home(root / "bad-stamp", starts=[INSTALLED_EPOCH - 60], installed_at="yesterday")
            self.assertEqual(kinds(bad_stamp), [])

    def test_both_findings_are_said_store_first(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"),
                              starts=[INSTALLED_EPOCH - 60], installed_at=INSTALLED_AT)
            self.assertEqual(kinds(home), [NOTICE_STORE_UNAVAILABLE, NOTICE_STALE_BUNDLE])

    def test_a_profile_home_names_its_own_restart(self) -> None:
        self.assertEqual(
            gateway_notice_home(Path("/h/profiles/kami"), "kami"),
            (Path("/h/profiles/kami"), "Hermes' gateway for profile kami", "hermes --profile kami gateway restart"),
        )


class DrainingTests(unittest.TestCase):
    def draining(self, home: Path, **overrides: object) -> Path:
        state = state_record(home, "unavailable", gateway_state="draining", restart_requested=True,
                             active_agents=1, active_work=[UNIT])
        state.update(overrides)
        return write_home(home, state=state, starts=[INSTALLED_EPOCH - 60], installed_at=INSTALLED_AT)

    def test_a_restart_wait_names_the_turns_the_time_left_and_the_knob_and_nothing_else(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp))
            drain_log(home, (NOW - 40, wait_line(719)), (NOW - 10, wait_line(689)), (NOW - 5, "unrelated line"))
            [notice] = gateway_notices(home, label="Hermes' gateway", restart_command="hermes gateway restart",
                                       now=NOW)
        self.assertEqual(notice.kind, NOTICE_DRAINING)
        self.assertEqual(notice.restart_command, "")
        self.assertEqual(
            notice.text,
            "Hermes' gateway is restarting: it waits for 1 running turn to finish first (about 679s left before "
            "it stops them anyway), and refuses new messages until it is done; bots answer them with "
            "`runtime_draining`. Hermes caps the wait with `agent.restart_after_turn_timeout` in its config.",
        )
        self.assertNotIn("OMH", notice.text)

    def test_without_a_fresh_log_line_the_time_left_is_not_said(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "no-log": (),
                "stale": ((NOW - DRAIN_LOG_FRESH_SECONDS - 1, wait_line(689)),),
                "future": ((NOW + 120, wait_line(689)),),
                "no-wait-line": ((NOW - 5, "Restart deferred wait complete"),),
                "garbage-number": ((NOW - 5, wait_line(689).replace("689s", "xs")),),
            }
            for label, lines in cases.items():
                with self.subTest(label):
                    home = self.draining(root / label)
                    if lines:
                        drain_log(home, *lines)
                    drain = gateway_drain(home, now=NOW)
                    self.assertIsNotNone(drain)
                    self.assertIsNone(drain.seconds_left)  # type: ignore[union-attr]
                    [notice] = gateway_notices(home, label="L", restart_command="c", now=NOW)
                    self.assertNotIn("left before", notice.text)
            garbled = self.draining(root / "not-utf8")
            (garbled / "logs").mkdir()
            (garbled / "logs" / "gateway.log").write_bytes(b"\xff\xfe" * 10 + b"\n")
            self.assertIsNone(gateway_drain(garbled, now=NOW).seconds_left)  # type: ignore[union-attr]

    def test_the_turn_count_falls_back_to_active_agents_then_to_none(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            counted = self.draining(root / "counted", active_work=None, active_agents=3)
            self.assertEqual(gateway_drain(counted, now=NOW).turns, 3)  # type: ignore[union-attr]
            text = gateway_notices(counted, label="L", restart_command="c", now=NOW)[0].text
            self.assertIn("waits for 3 running turns to finish", text)
            unknown = self.draining(root / "unknown", active_work="odd", active_agents=True)
            self.assertIsNone(gateway_drain(unknown, now=NOW).turns)  # type: ignore[union-attr]
            text = gateway_notices(unknown, label="L", restart_command="c", now=NOW)[0].text
            self.assertIn("waits for its running turns to finish", text)

    def test_a_drain_without_a_restart_is_a_shutdown(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp), restart_requested=False)
            text = gateway_notices(home, label="L", restart_command="c", now=NOW)[0].text
        self.assertTrue(text.startswith("L is shutting down: "))

    def test_a_draining_record_of_a_gone_or_foreign_gateway_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            no_pid = write_home(root / "no-pid", state=state_record(root / "no-pid", gateway_state="draining"), pid=None)
            self.assertIsNone(gateway_drain(no_pid, now=NOW))
            other = write_home(root / "other", state=state_record(root / "other", gateway_state="draining", pid=PID + 1))
            self.assertIsNone(gateway_drain(other, now=NOW))
            running = write_home(root / "running", state=state_record(root / "running"))
            self.assertIsNone(gateway_drain(running, now=NOW))


class DoctorRowTests(unittest.TestCase):
    def paths(self, root: Path) -> OmhPaths:
        return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")

    def test_a_gateway_that_needs_a_restart_warns_and_names_the_command(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_home(root / ".hermes", state=state_record(root / ".hermes", "unavailable"),
                       starts=[INSTALLED_EPOCH - 60], installed_at=INSTALLED_AT)
            [check] = _hermes_gateway_checks(self.paths(root))
        self.assertEqual(check.name, "hermes_gateway")
        self.assertTrue(check.ok)
        self.assertEqual(check.severity, "warning")
        self.assertIn("cannot write its session store", check.message)
        self.assertIn("started before OMH was updated", check.message)
        self.assertIn("`hermes gateway restart`", check.next_action)
        self.assertIn("OMH does not restart it", check.next_action)
        self.assertEqual(check.detail, {"findings": [NOTICE_STORE_UNAVAILABLE, NOTICE_STALE_BUNDLE],
                                        "restart_command": "hermes gateway restart"})

    def test_a_draining_gateway_warns_to_wait_and_names_the_knob(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_home(root / ".hermes", state=state_record(root / ".hermes", gateway_state="draining",
                                                            restart_requested=True, active_work=[UNIT]))
            [check] = _hermes_gateway_checks(self.paths(root))
        self.assertEqual((check.name, check.ok, check.severity), ("hermes_gateway", True, "warning"))
        self.assertIn("is restarting: it waits for 1 running turn", check.message)
        self.assertEqual(check.next_action, "wait for it to finish; the wait is capped by "
                                            "`agent.restart_after_turn_timeout`. OMH does not stop or restart it")
        self.assertEqual(check.detail, {"findings": [NOTICE_DRAINING], "restart_command": ""})

    def test_a_healthy_gateway_is_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_home(root / ".hermes", state=state_record(root / ".hermes"), starts=[INSTALLED_EPOCH + 60],
                       installed_at=INSTALLED_AT)
            [check] = _hermes_gateway_checks(self.paths(root))
        self.assertEqual((check.name, check.ok, check.severity, check.observed), ("hermes_gateway", True, "ok", True))
        self.assertIn("no restart needed", check.message)

    def test_no_gateway_recorded_is_ok_and_not_observed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir()
            [check] = _hermes_gateway_checks(self.paths(root))
        self.assertEqual((check.ok, check.severity, check.observed), (True, "ok", False))
        self.assertIn("no running Hermes gateway recorded", check.message)

    def test_a_profile_gateway_gets_its_own_row_only_when_it_needs_a_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes = root / ".hermes"
            hermes.mkdir()
            for name, status in (("kami", "unavailable"), ("quiet", "ok")):
                profile = hermes / "profiles" / name
                profile.mkdir(parents=True)
                (profile / "SOUL.md").write_text("identity\n", encoding="utf-8")
                write_home(profile, state=state_record(profile, status))
            checks = _hermes_gateway_checks(self.paths(root))
        self.assertEqual([check.name for check in checks], ["hermes_gateway", "hermes_gateway:kami"])
        self.assertEqual(checks[1].severity, "warning")
        self.assertIn("Hermes' gateway for profile kami cannot write", checks[1].message)
        self.assertIn("`hermes --profile kami gateway restart`", checks[1].next_action)


if __name__ == "__main__":
    unittest.main()
