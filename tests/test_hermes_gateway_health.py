"""Hermes' gateway needs attention: the lines the OMH TUI's launch and `omh doctor` show, from its files alone.

Nothing is said unless `gateway_state.json` is a fresh record (re-stamped
within Hermes' own 120 s bound) of a gateway running in this home. Three
findings, each said as Hermes', none acted on:

- the session store: Hermes' aggregate `unavailable` survives a restart until
  the new process publishes its own, so it is said only when the error log
  holds a store failure logged after the last recorded start, and the line
  says what that failure was. A deleted profile still referenced gets no
  restart advice (a restart does not clear it); a replaced store does, with
  its blast radius;
- a stale plugin bundle: the last recorded start precedes `installed_at`;
- a drain: a restart (capped by `agent.restart_after_turn_timeout`, its count
  and time left from the fresh wait line), a drain request (keeps running), or
  a stop. A draining gateway gets that line alone.

The record and log shapes are the owner machine's on 2026-11-02 (Hermes
0.22.5), trimmed.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from omh.maintenance.doctor import _hermes_gateway_checks
from omh.maintenance.hermes_gateway import (
    DRAIN_LOG_FRESH_SECONDS,
    DRAIN_LOG_TAIL_BYTES,
    DRAIN_REQUEST,
    DRAIN_RESTART,
    DRAIN_STOPPING,
    GATEWAY_STATE_BYTES,
    NOTICE_DELETED_PROFILE_STORE,
    NOTICE_DRAINING,
    NOTICE_PROFILE_NOT_SERVED,
    NOTICE_STALE_BUNDLE,
    NOTICE_STORE_UNAVAILABLE,
    RUNTIME_STATUS_STALE_SECONDS,
    gateway_drain,
    gateway_notice_home,
    gateway_notices,
    gateway_session_store_status,
    store_failure,
)
from omh.paths import OmhPaths

NOW = float(int(time.time()))
STARTED = NOW - 3600  # the gateway's last recorded start
INSTALLED_AT = datetime.fromtimestamp(STARTED + 60, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
PID = 55515
# One chat unit as Hermes' `_describe_active_work` records it while draining.
UNIT = {"kind": "chat", "session": "agent:kami:discord:thread:1", "pid": PID, "elapsed_s": 1823.3}
REPLACED = ("FATAL: state.db was replaced underneath the gateway; refusing further writes to this file. Divert "
            "transcripts to sessions/<id>.jsonl (and the gateway pending_messages spool) and restore or reopen "
            "after operator intervention.")
MCP_NOISE = "MCP OAuth setup failed for 'notion': non-interactive environment and no cached tokens found."


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat()


def stamp(at: float) -> str:
    """Python logging's asctime, in local time, as Hermes writes it."""
    return datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M:%S") + ",515"


def missing_profile(home: Path, name: str = "opti-sol-base") -> str:
    return (f"[gateway] Warning: SQLite session store unavailable, falling back to JSONL: Named profile home does "
            f"not exist: {home / 'profiles' / name}. Create the profile explicitly before using it.")


def pid_record(home: Path, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "pid": PID, "kind": "hermes-gateway",
        "argv": ["hermes_cli/main.py", "gateway", "run", "--external-supervisor"],
        "start_time": 179359173648, "hermes_home": str(home),
    }
    record.update(overrides)
    return record


def state_record(home: Path, status: object = "ok", **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        **pid_record(home), "gateway_state": "running", "exit_reason": None, "restart_requested": False,
        "active_agents": 2, "platforms": {}, "session_store": {"status": status},
        "updated_at": iso(NOW - 10), "code_version": "0.22.5", "served_profiles": ["default", "kami"],
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
    errors: list[tuple[float, str]] | None = None,
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
    if errors is not None:
        log_lines(home / "logs" / "gateway.error.log", errors)
    return home


def log_lines(path: Path, lines: list[tuple[float, str]], *, level: str = "ERROR", logger: str = "hermes_state") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        f"{stamp(at)} {body}\n" if body.startswith("[gateway]") else f"{stamp(at)} {level} {logger}: {body}\n"
        for at, body in lines
    )
    path.write_text(text, encoding="utf-8")


def drain_log(home: Path, *lines: tuple[float, str]) -> None:
    log_lines(home / "logs" / "gateway.log", list(lines), level="INFO", logger="gateway.run")


def wait_line(seconds: int, units: int = 1) -> str:
    return (f"Restart deferred: waiting on {units} active work unit(s) (0 wedged and excluded, 0 restart-safe and "
            f"excluded; {seconds}s remaining before force drain): [{UNIT!r}]")


def kinds(home: Path) -> list[str]:
    _home, label, command = gateway_notice_home(home)
    return [notice.kind for notice in gateway_notices(home, label=label, restart_command=command, now=NOW)]


def only(home: Path):
    _home, label, command = gateway_notice_home(home)
    [notice] = gateway_notices(home, label=label, restart_command=command, now=NOW)
    return notice


class RecordEvidenceTests(unittest.TestCase):
    def test_ok_and_unavailable_are_read_from_a_fresh_record_of_the_running_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            ok = write_home(Path(tmp) / "ok", state=state_record(Path(tmp) / "ok"))
            self.assertEqual(gateway_session_store_status(ok, now=NOW), "ok")
            down = write_home(Path(tmp) / "down", state=state_record(Path(tmp) / "down", "unavailable"))
            self.assertEqual(gateway_session_store_status(down, now=NOW), "unavailable")

    def test_missing_files_say_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            no_state = write_home(Path(tmp) / "no-state")
            self.assertIsNone(gateway_session_store_status(no_state, now=NOW))
            # A clean stop unlinks gateway.pid; the state file it leaves is not a running gateway.
            stopped = write_home(Path(tmp) / "no-pid", state=state_record(Path(tmp) / "no-pid", "unavailable"), pid=None)
            self.assertIsNone(gateway_session_store_status(stopped, now=NOW))
            self.assertIsNone(gateway_session_store_status(Path(tmp) / "absent", now=NOW))

    def test_missing_keys_and_odd_shapes_say_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases: dict[str, object] = {
                "no-store-key": {"pid": PID, "gateway_state": "running", "updated_at": iso(NOW)},
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
                    write_home(home, state=state, starts=[STARTED], errors=[(NOW - 5, REPLACED)])  # type: ignore[arg-type]
                    self.assertIsNone(gateway_session_store_status(home, now=NOW))
                    self.assertEqual(kinds(home), [])

    def test_an_oversized_record_is_not_one_hermes_wrote(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(home, state=state_record(home, "unavailable", padding="x" * GATEWAY_STATE_BYTES))
            self.assertIsNone(gateway_session_store_status(home, now=NOW))

    def test_a_record_of_another_home_another_pid_or_a_gone_gateway_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            elsewhere = write_home(root / "a", state=state_record(root / "other", "unavailable"))
            self.assertIsNone(gateway_session_store_status(elsewhere, now=NOW))
            other_pid = write_home(root / "b", state=state_record(root / "b", "unavailable", pid=PID + 1))
            self.assertIsNone(gateway_session_store_status(other_pid, now=NOW))
            gone: dict[str, dict[str, object]] = {
                "stopped": {"gateway_state": "stopped"},
                "startup_failed": {"gateway_state": "startup_failed"},
                "null-state": {"gateway_state": None},
                "loop-watchdog": {"gateway_state": "degraded", "exit_reason": "loop_liveness_watchdog"},
                "shutdown-watchdog": {"gateway_state": "degraded", "exit_reason": "shutdown_watchdog"},
            }
            for label, overrides in gone.items():
                with self.subTest(label):
                    home = write_home(root / label, state=state_record(root / label, "unavailable", **overrides))
                    self.assertIsNone(gateway_session_store_status(home, now=NOW))
            record = state_record(root / "no-key", "unavailable")
            del record["gateway_state"]
            self.assertIsNone(gateway_session_store_status(write_home(root / "no-key", state=record), now=NOW))
            # A degraded gateway that is not a watchdog's exit still runs.
            degraded = write_home(root / "degraded", state=state_record(root / "degraded", "unavailable",
                                                                        gateway_state="degraded"))
            self.assertEqual(gateway_session_store_status(degraded, now=NOW), "unavailable")
            # A pid record of another home is that home's gateway, as Hermes reads it.
            foreign = write_home(root / "c", state=state_record(root / "c", "unavailable"),
                                 pid=pid_record(root / "elsewhere"))
            self.assertIsNone(gateway_session_store_status(foreign, now=NOW))

    def test_a_record_without_a_home_or_pid_is_read_as_this_homes(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            record = state_record(home, "unavailable")
            del record["hermes_home"], record["pid"]
            write_home(home, state=record)
            self.assertEqual(gateway_session_store_status(home, now=NOW), "unavailable")

    def test_a_record_no_one_re_stamped_is_no_evidence(self) -> None:
        # Hermes' `_RUNTIME_STATUS_STALE_TTL_S`: a gateway killed by OOM or SIGKILL leaves its record behind.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases: dict[str, object] = {
                "stale": iso(NOW - RUNTIME_STATUS_STALE_SECONDS - 1),
                "far-future": iso(NOW + RUNTIME_STATUS_STALE_SECONDS + 1),
                "missing": None,
                "unparseable": "yesterday",
                "not-text": 1793591736,
            }
            for label, updated in cases.items():
                with self.subTest(label):
                    record = state_record(root / label, "unavailable", gateway_state="draining",
                                          restart_requested=True, updated_at=updated)
                    if updated is None:
                        del record["updated_at"]
                    home = write_home(root / label, state=record, starts=[STARTED], installed_at=INSTALLED_AT,
                                      errors=[(NOW - 5, REPLACED)])
                    self.assertIsNone(gateway_drain(home, now=NOW))
                    self.assertEqual(kinds(home), [])
            fresh = write_home(root / "fresh", state=state_record(root / "fresh", updated_at=iso(NOW - 119)))
            self.assertEqual(gateway_session_store_status(fresh, now=NOW), "ok")

    def test_a_fifo_where_a_file_should_be_never_blocks(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("no FIFOs on this platform")
        for name in ("gateway_state.json", "gateway.pid", "gateway-starts.log"):
            with self.subTest(name), TemporaryDirectory() as tmp:
                home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"), starts=[STARTED],
                                  installed_at=INSTALLED_AT, errors=[(NOW - 5, REPLACED)])
                (home / name).unlink()
                os.mkfifo(home / name)
                started = time.monotonic()
                kinds(home)
                self.assertLess(time.monotonic() - started, 2.0)
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"), starts=[STARTED])
            (home / "logs").mkdir()
            os.mkfifo(home / "logs" / "gateway.error.log")
            self.assertIsNone(store_failure(home))

    def test_an_oversized_pid_record_is_not_read(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"), starts=[STARTED],
                              errors=[(NOW - 5, REPLACED)],
                              pid=pid_record(Path(tmp), padding="x" * (64 << 10)))
            self.assertEqual(kinds(home), [])

    def test_a_manifest_nested_past_the_recursion_limit_says_nothing_instead_of_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp)), starts=[STARTED], installed_at=INSTALLED_AT)
            (home / "plugins" / "omh" / ".omh-plugin-manifest.json").write_text("[" * 100_000, encoding="utf-8")
            self.assertEqual(kinds(home), [])


class StoreFailureTests(unittest.TestCase):
    def test_the_flag_alone_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"), starts=[STARTED])
            self.assertEqual(kinds(home), [])
            write_home(home, errors=[(NOW - 60, MCP_NOISE)])
            self.assertEqual(kinds(home), [])

    def test_a_failure_from_before_the_last_start_is_the_old_processes_and_says_nothing(self) -> None:
        # A restarted gateway keeps the old process's `unavailable` until it publishes its own.
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"), starts=[STARTED - 86400, STARTED],
                              errors=[(STARTED - 30, REPLACED), (NOW - 60, MCP_NOISE)])
            self.assertIsNone(store_failure(home))
            self.assertEqual(kinds(home), [])
            no_ledger = write_home(Path(tmp) / "no-ledger", state=state_record(Path(tmp) / "no-ledger", "unavailable"),
                                   errors=[(NOW - 5, REPLACED)])
            self.assertEqual(kinds(no_ledger), [])

    def test_a_deleted_profile_still_referenced_is_named_without_restart_advice(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_home(home, state=state_record(home, "unavailable"), starts=[STARTED],
                       errors=[(STARTED - 30, REPLACED), (NOW - 600, missing_profile(home)), (NOW - 60, MCP_NOISE)])
            notice = only(home)
        self.assertEqual(notice.kind, NOTICE_DELETED_PROFILE_STORE)
        self.assertEqual(
            notice.text,
            "Hermes' gateway reports its session store unavailable: a deleted profile `opti-sol-base` is still "
            "referenced in Hermes (a cron job, a kanban board or a served profile; Hermes logged \"Named profile "
            f"home does not exist\" at {stamp(NOW - 600)[:19]}). Your own sessions are unaffected. Remove that "
            "reference or recreate the profile; a restart does not clear it.",
        )
        self.assertEqual(notice.restart_command, "")
        self.assertNotIn("hermes gateway restart", notice.text + notice.next_action)
        self.assertIn("`hermes profile create opti-sol-base`", notice.next_action)
        self.assertIn("OMH changes nothing", notice.next_action)

    def test_a_replaced_store_gets_the_restart_and_its_blast_radius_and_no_guarantee(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"), starts=[STARTED],
                              errors=[(NOW - 600, missing_profile(Path(tmp))), (NOW - 5, REPLACED)])
            notice = only(home)
        self.assertEqual(notice.kind, NOTICE_STORE_UNAVAILABLE)
        self.assertEqual(
            notice.text,
            f"Hermes' gateway cannot write a session store it holds (Hermes logged \"state.db was replaced\" at "
            f"{stamp(NOW - 5)[:19]}). Restarting it with `hermes gateway restart` reopens its stores; that restarts "
            "every bot it serves and first waits for their running turns.",
        )
        self.assertEqual(notice.restart_command, "hermes gateway restart")
        self.assertNotIn("fine", notice.text)
        self.assertNotIn("unaffected", notice.text)

    def test_a_parked_profile_and_an_unnamed_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            kami = root / "p" / "profiles" / "kami"
            parked = (f"[MULTIPLEX] Profile 'kami' not served: its session store is unusable ({kami}): "
                      f"{kami / 'state.db'} did not open: database disk image is malformed")
            home = write_home(root / "p", state=state_record(root / "p", "unavailable"), starts=[STARTED],
                              errors=[(NOW - 5, parked)])
            notice = only(home)
            self.assertEqual(notice.kind, NOTICE_PROFILE_NOT_SERVED)
            self.assertIn("does not serve profile `kami`", notice.text)
            self.assertIn("The other profiles' sessions are unaffected.", notice.text)
            self.assertEqual(notice.restart_command, "")
            unnamed = write_home(root / "u", state=state_record(root / "u", "unavailable"), starts=[STARTED],
                                 errors=[(NOW - 5, "[gateway] Warning: SQLite session store unavailable, falling "
                                                   "back to JSONL: disk I/O error")])
            notice = only(unnamed)
            self.assertEqual(notice.kind, NOTICE_STORE_UNAVAILABLE)
            self.assertIn("Hermes logged \"session store unavailable\"", notice.text)
            self.assertEqual(notice.restart_command, "hermes gateway restart")

    def test_an_ok_store_ignores_any_failure_line(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp)), starts=[STARTED], errors=[(NOW - 5, REPLACED)])
            self.assertEqual(kinds(home), [])


class StaleBundleTests(unittest.TestCase):
    def test_a_gateway_started_before_the_bundle_install_needs_a_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp)), starts=[STARTED], installed_at=INSTALLED_AT)
            notice = only(home)
        self.assertEqual(notice.kind, NOTICE_STALE_BUNDLE)
        started = datetime.fromtimestamp(STARTED, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(
            notice.text,
            f"Hermes' gateway started before OMH was updated (last start {started}, OMH plugin installed "
            f"{INSTALLED_AT}), so it still runs the old OMH plugin code; restarting it with `hermes gateway restart` "
            "loads the new code, restarts every bot it serves and first waits for their running turns.",
        )

    def test_a_gateway_started_after_the_install_or_without_evidence_says_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)

            def home(name: str, **files: object) -> Path:
                return write_home(root / name, state=state_record(root / name), **files)  # type: ignore[arg-type]

            self.assertEqual(kinds(home("fresh", starts=[STARTED + 120], installed_at=INSTALLED_AT)), [])
            self.assertEqual(kinds(home("no-ledger", installed_at=INSTALLED_AT)), [])
            self.assertEqual(kinds(home("no-bundle", starts=[STARTED])), [])
            self.assertEqual(kinds(home("bad-stamp", starts=[STARTED], installed_at="yesterday")), [])
            no_record = write_home(root / "no-record", starts=[STARTED], installed_at=INSTALLED_AT)
            self.assertEqual(kinds(no_record), [])

    def test_both_findings_are_said_store_first(self) -> None:
        with TemporaryDirectory() as tmp:
            home = write_home(Path(tmp), state=state_record(Path(tmp), "unavailable"), starts=[STARTED],
                              installed_at=INSTALLED_AT, errors=[(NOW - 5, REPLACED)])
            self.assertEqual(kinds(home), [NOTICE_STORE_UNAVAILABLE, NOTICE_STALE_BUNDLE])

    def test_a_profile_home_names_its_own_restart(self) -> None:
        self.assertEqual(
            gateway_notice_home(Path("/h/profiles/kami"), "kami"),
            (Path("/h/profiles/kami"), "Hermes' gateway for profile kami", "hermes --profile kami gateway restart"),
        )


class DrainingTests(unittest.TestCase):
    def draining(self, home: Path, **overrides: object) -> Path:
        fields: dict[str, object] = {"gateway_state": "draining", "restart_requested": True, "active_agents": 1,
                                     "active_work": [UNIT]}
        fields.update(overrides)
        return write_home(home, state=state_record(home, "unavailable", **fields), starts=[STARTED],
                          installed_at=INSTALLED_AT, errors=[(NOW - 5, REPLACED)])

    def test_a_restart_wait_names_the_turns_the_time_left_and_the_knob_and_nothing_else(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp))
            drain_log(home, (NOW - 40, wait_line(719)), (NOW - 10, wait_line(689)), (NOW - 5, "unrelated line"))
            notice = only(home)
        self.assertEqual(notice.kind, NOTICE_DRAINING)
        self.assertEqual(notice.restart_command, "")
        self.assertEqual(
            notice.text,
            "Hermes' gateway is restarting: it waits for 1 running turn to finish first (about 679s left before it "
            "stops them anyway), and does not start new turns until it is done; Hermes holds or refuses new "
            "messages as `runtime_draining`. Hermes caps the wait with `agent.restart_after_turn_timeout`.",
        )
        self.assertEqual(notice.next_action, "wait for it to finish; the wait is capped by "
                                             "`agent.restart_after_turn_timeout`. OMH does not stop or restart it")

    def test_the_newest_wait_line_wins_over_an_earlier_drains(self) -> None:
        # Two drains: the earlier one's line counts down on another deadline, so the oldest line gives other numbers.
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp))
            drain_log(home, (NOW - 50, wait_line(1500, units=3)), (NOW - 10, wait_line(200, units=2)))
            drain = gateway_drain(home, now=NOW)
            self.assertEqual((drain.seconds_left, drain.turns), (190, 2))  # type: ignore[union-attr]

    def test_the_wait_lines_count_is_the_awaited_one(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp), active_work=[UNIT, UNIT, UNIT])
            drain_log(home, (NOW - 10, wait_line(300, units=1)))
            self.assertIn("waits for 1 running turn to finish", only(home).text)

    def test_without_a_fresh_wait_line_the_time_left_is_not_said(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "no-log": (),
                "stale": ((NOW - DRAIN_LOG_FRESH_SECONDS - 1, wait_line(689)),),
                "future": ((NOW + 120, wait_line(689)),),
                "no-wait-line": ((NOW - 5, "Restart deferred wait complete"),),
                "garbage-number": ((NOW - 5, wait_line(689).replace("689s", "xs")),),
                "negative-left": ((NOW - 5, wait_line(689).replace("689s", "-689s")),),
                "not-anchored": ((NOW - 5, "someone typed: 689s remaining before force drain)"),),
            }
            for label, lines in cases.items():
                with self.subTest(label):
                    home = self.draining(root / label)
                    if lines:
                        drain_log(home, *lines)
                    drain = gateway_drain(home, now=NOW)
                    self.assertIsNotNone(drain)
                    self.assertIsNone(drain.seconds_left)  # type: ignore[union-attr]
                    self.assertNotIn("left before", only(home).text)
            garbled = self.draining(root / "not-utf8")
            (garbled / "logs").mkdir(exist_ok=True)
            (garbled / "logs" / "gateway.log").write_bytes(b"\xff\xfe" * 10 + b"\n")
            self.assertIsNone(gateway_drain(garbled, now=NOW).seconds_left)  # type: ignore[union-attr]

    def test_a_wait_line_before_the_tail_window_is_not_read(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp))
            drain_log(home, (NOW - 10, wait_line(689)))
            with (home / "logs" / "gateway.log").open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp(NOW - 5)} INFO gateway.run: {'x' * DRAIN_LOG_TAIL_BYTES}\n")
            self.assertIsNone(gateway_drain(home, now=NOW).seconds_left)  # type: ignore[union-attr]

    def test_the_turn_count_skips_what_the_wait_excludes_then_falls_back(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            excluded = [UNIT, {**UNIT, "kind": "cron", "wedged": True}, {**UNIT, "kind": "cron", "restart_safe": True}]
            mixed = self.draining(root / "mixed", active_work=excluded, active_agents=3)
            self.assertEqual(gateway_drain(mixed, now=NOW).turns, 1)  # type: ignore[union-attr]
            counted = self.draining(root / "counted", active_work=None, active_agents=3)
            self.assertIn("waits for 3 running turns to finish", only(counted).text)
            unknown = self.draining(root / "unknown", active_work="odd", active_agents=True)
            self.assertIsNone(gateway_drain(unknown, now=NOW).turns)  # type: ignore[union-attr]
            self.assertIn("waits for its running turns to finish", only(unknown).text)

    def test_a_drain_request_keeps_running_and_names_no_restart_knob(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp), restart_requested=False)
            (home / ".drain_request.json").write_text('{"requested_at": 1}', encoding="utf-8")
            drain_log(home, (NOW - 10, wait_line(689)))
            self.assertEqual(gateway_drain(home, now=NOW).reason, DRAIN_REQUEST)  # type: ignore[union-attr]
            notice = only(home)
        self.assertIn("is paused for new turns by a drain request", notice.text)
        self.assertIn("keeps running", notice.text)
        self.assertNotIn("restart_after_turn_timeout", notice.text + notice.next_action)
        self.assertNotIn("left before", notice.text)
        self.assertIn("OMH does not touch it", notice.next_action)

    def test_a_drain_without_a_restart_or_a_request_is_a_stop(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp), restart_requested=False)
            drain_log(home, (NOW - 10, wait_line(689)))
            self.assertEqual(gateway_drain(home, now=NOW).reason, DRAIN_STOPPING)  # type: ignore[union-attr]
            notice = only(home)
        self.assertTrue(notice.text.startswith("Hermes' gateway is stopping: "))
        self.assertNotIn("restart_after_turn_timeout", notice.text + notice.next_action)
        self.assertEqual(notice.next_action, "wait for it to stop; OMH does not stop or restart it")

    def test_a_restart_requested_wins_over_a_drain_request(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self.draining(Path(tmp))
            (home / ".drain_request.json").write_text("{}", encoding="utf-8")
            self.assertEqual(gateway_drain(home, now=NOW).reason, DRAIN_RESTART)  # type: ignore[union-attr]

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
    """Doctor reads the wall clock, so these records are stamped now."""

    def paths(self, root: Path) -> OmhPaths:
        return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")

    def state(self, home: Path, status: str = "ok", **overrides: object) -> dict[str, object]:
        return state_record(home, status, updated_at=iso(time.time()), **overrides)

    def test_a_replaced_store_and_a_stale_bundle_warn_and_name_the_command(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_home(root / ".hermes", state=self.state(root / ".hermes", "unavailable"), starts=[STARTED],
                       installed_at=INSTALLED_AT, errors=[(time.time() - 5, REPLACED)])
            [check] = _hermes_gateway_checks(self.paths(root))
        self.assertEqual(check.name, "hermes_gateway")
        self.assertTrue(check.ok)
        self.assertEqual(check.severity, "warning")
        self.assertIn("cannot write a session store it holds", check.message)
        self.assertIn("started before OMH was updated", check.message)
        self.assertEqual(check.next_action, "run `hermes gateway restart` when a restart suits the bots it serves; "
                                            "OMH does not restart it")
        self.assertEqual(check.detail, {"findings": [NOTICE_STORE_UNAVAILABLE, NOTICE_STALE_BUNDLE],
                                        "restart_command": "hermes gateway restart"})

    def test_a_deleted_profile_reference_says_what_to_remove_and_no_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes = root / ".hermes"
            write_home(hermes, state=self.state(hermes, "unavailable"), starts=[STARTED],
                       errors=[(time.time() - 60, missing_profile(hermes))])
            [check] = _hermes_gateway_checks(self.paths(root))
        self.assertEqual(check.severity, "warning")
        self.assertIn("a deleted profile `opti-sol-base` is still referenced", check.message)
        self.assertNotIn("gateway restart", check.message + check.next_action)
        self.assertEqual(check.detail, {"findings": [NOTICE_DELETED_PROFILE_STORE], "restart_command": ""})

    def test_draining_rows_split_restart_request_and_stop(self) -> None:
        cases = {
            "restart": (True, False, "the wait is capped by `agent.restart_after_turn_timeout`"),
            "request": (False, True, "removed or expires; OMH does not touch it"),
            "stop": (False, False, "wait for it to stop; OMH does not stop or restart it"),
        }
        for label, (restart, requested, action) in cases.items():
            with self.subTest(label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                hermes = root / ".hermes"
                write_home(hermes, state=self.state(hermes, gateway_state="draining", active_work=[UNIT],
                                                    restart_requested=restart))
                if requested:
                    (hermes / ".drain_request.json").write_text("{}", encoding="utf-8")
                [check] = _hermes_gateway_checks(self.paths(root))
                self.assertEqual((check.ok, check.severity), (True, "warning"))
                self.assertIn(action, check.next_action)
                self.assertEqual(check.detail, {"findings": [NOTICE_DRAINING], "restart_command": ""})
                if label != "restart":
                    self.assertNotIn("restart_after_turn_timeout", check.message + check.next_action)

    def test_a_healthy_gateway_is_ok(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_home(root / ".hermes", state=self.state(root / ".hermes"), starts=[STARTED + 120],
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

    def test_a_profile_gateway_gets_its_own_row_only_when_it_has_something_to_say(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes = root / ".hermes"
            hermes.mkdir()
            for name, status in (("kami", "unavailable"), ("quiet", "ok")):
                profile = hermes / "profiles" / name
                profile.mkdir(parents=True)
                (profile / "SOUL.md").write_text("identity\n", encoding="utf-8")
                write_home(profile, state=self.state(profile, status), starts=[STARTED],
                           errors=[(time.time() - 5, REPLACED)])
            checks = _hermes_gateway_checks(self.paths(root))
        self.assertEqual([check.name for check in checks], ["hermes_gateway", "hermes_gateway:kami"])
        self.assertEqual(checks[1].severity, "warning")
        self.assertIn("Hermes' gateway for profile kami cannot write", checks[1].message)
        self.assertIn("`hermes --profile kami gateway restart`", checks[1].next_action)


if __name__ == "__main__":
    unittest.main()
