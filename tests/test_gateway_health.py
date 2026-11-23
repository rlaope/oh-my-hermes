"""`omh doctor`'s gateway health section: fleet against build, fleet shape, messaging adapter states.

The log fixture (`fixtures/gateway_health/host_gateway.log`) is a multiplexed
host's `logs/gateway.log` in the exact line shapes Hermes 0.23.3 writes
(`gateway/run_adapters.py`, `run_adapters_recovery.py`, `run_startup.py`, the
Discord adapter's connect failure), with invented profile and bot names: a
transient fatal error and its reconnect, a Discord bot refused for privileged
intents twice (each with a traceback after the adapter's reason), a second
profile's Slack connecting and then failing with no reason logged, the bot's
recovery, a primary profile's line and a truncated last line.

Everything is read from files; nothing runs a process (the listing and the
gateway records are injected).
"""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from omh.maintenance import gateway_health as health
from omh.maintenance.gateway_health import (
    BUILD_BEFORE,
    BUILD_CURRENT,
    BUILD_OTHER_COMMIT,
    FINDING_ADAPTER_DOWN,
    FINDING_INCOMPLETE_RESTART,
    FINDING_PENDING_RESTART,
    FINDING_SHARED_PROFILE,
    FINDING_STALE_GATEWAY,
    FINDING_UNRECORDED,
    RESTART_NOTE,
    gateway_health,
)
from omh.maintenance.hermes_gateway_formats import (
    LOG_LINE_CHARS,
    REASON_CHARS,
    REASON_NONE,
    REASON_PRIVILEGED_INTENTS,
    REASON_TOKEN_REJECTED,
    REASON_TRANSIENT,
    REASON_UNRECOGNIZED,
    STATE_CONNECTED,
    STATE_DEGRADED,
    STATE_FAILED,
    STATE_FATAL,
    STATUS_MISSING,
    STATUS_READ,
    STATUS_UNRECOGNIZED,
    AdapterEvent,
    adapter_events,
    bounded_reason,
    classify_reason,
    parse_adapter_line,
    read_build_stamp,
    read_fleet_restart_state,
    read_gateway_log,
)
from omh.system import process_listing
from omh.system.process_listing import gateway_runs, procargs2_argv
from omh.tui.bot_board import Gateway

FIXTURE = Path(__file__).parent / "fixtures" / "gateway_health" / "host_gateway.log"
COMMIT = "c0ffee5389ae585ef77387a962aee05b1bcf1702"
BUILT_AT = "2026-11-21T11:06:39.131982+00:00"
BUILT_EPOCH = datetime(2026, 11, 21, 11, 6, 39, 131982, tzinfo=UTC).timestamp()
NO_RECORD = Gateway("", False, problem="no gateway record")
# Token-shaped, built at run time so no literal in the tree looks like a real credential.
TOKEN = ".".join(("x" * 24, "y" * 6, "z" * 27))


def fixture_lines() -> list[str]:
    return FIXTURE.read_text(encoding="utf-8").splitlines()


def latest(events: list[AdapterEvent]) -> dict[tuple[str, str], AdapterEvent]:
    found: dict[tuple[str, str], AdapterEvent] = {}
    for event in events:
        found[(event.profile, event.platform)] = event
    return found


class AdapterLineShapes(unittest.TestCase):
    def test_every_quoted_shape_is_read(self) -> None:
        cases = {
            "2026-11-23 17:05:01,462 WARNING gateway.run: ✗ discord failed to connect (profile: harbor)":
                ("harbor", "discord", STATE_FAILED, "", ""),
            "2026-11-23 17:23:30,806 INFO gateway.run: ✓ discord connected (profile: harbor)":
                ("harbor", "discord", STATE_CONNECTED, "", ""),
            "2026-11-23 15:02:41,906 INFO gateway.run: ✓ discord reconnected (profile: harbor)":
                ("harbor", "discord", STATE_CONNECTED, "", ""),
            "2026-11-23 15:02:10,118 ERROR gateway.run: Fatal discord adapter error for multiplexed profile harbor "
            "(discord_websocket_health_stale)": ("harbor", "discord", STATE_FATAL, "", "discord_websocket_health_stale"),
            "2026-11-23 17:30:12,500 INFO gateway.run: ✓ telegram connected": ("", "telegram", STATE_CONNECTED, "", ""),
            "2026-11-23 17:30:12,500 INFO gateway.run: ✓ telegram reconnected successfully":
                ("", "telegram", STATE_CONNECTED, "", ""),
            "2026-11-23 17:30:12,500 WARNING gateway.run: ✗ telegram failed to connect": ("", "telegram", STATE_FAILED, "", ""),
            "2026-11-23 17:30:12,500 ERROR gateway.run: ✗ slack error (profile: quay): invalid_auth":
                ("quay", "slack", STATE_FAILED, "invalid_auth", ""),
            "2026-11-23 17:30:12,500 ERROR gateway.run: ✗ slack error: invalid_auth": ("", "slack", STATE_FAILED, "invalid_auth", ""),
            "2026-11-23 17:30:12,500 ERROR gateway.run: Fatal slack adapter error (slack_socket_closed): socket closed":
                ("", "slack", STATE_FATAL, "socket closed", "slack_socket_closed"),
            "2026-11-23 17:30:12,500 INFO gateway.run: ✓ telegram connected (degraded)": ("", "telegram", STATE_DEGRADED, "", ""),
            "2026-11-23 17:30:12,500 INFO gateway.run: ⚠ telegram reconnected in degraded mode (receive path not yet "
            "confirmed)": ("", "telegram", STATE_DEGRADED, "", ""),
        }
        for line, (profile, platform, state, reason, code) in cases.items():
            with self.subTest(line=line):
                event = parse_adapter_line(line)
                self.assertIsNotNone(event)
                assert event is not None
                self.assertEqual((event.profile, event.platform, event.state, event.reason, event.code),
                                 (profile, platform, state, reason, code))
                self.assertIsNotNone(event.epoch)

    def test_other_lines_are_not_adapter_states(self) -> None:
        for line in (
            "2026-11-23 17:23:30,802 INFO hermes_plugins.platforms__discord.adapter: [Discord] Connected as Harbor#0042",
            "2026-11-23 17:05:01,467 INFO gateway.run_profile_reconcile: [MULTIPLEX] Now serving profile 'harbor' "
            "(0 adapter(s) connected; control-socket)",
            "discord.errors.PrivilegedIntentsRequired: Shard ID None is requesting privileged intents",
            "2026-11-23 17:05:01,462 WARNING gateway.run: ✗ discord failed to connect (profile: harbor) and more",
            "2026-11-23 17:31:0",
            "✓ discord connected (profile: harbor)",
            "",
        ):
            with self.subTest(line=line):
                self.assertIsNone(parse_adapter_line(line))


class AdapterHistory(unittest.TestCase):
    def test_a_failure_followed_by_a_later_success_reads_connected(self) -> None:
        states = latest(adapter_events(fixture_lines()))
        harbor = states[("harbor", "discord")]
        self.assertEqual(harbor.state, STATE_CONNECTED)
        self.assertEqual(harbor.logged, "2026-11-23 17:23:30")

    def test_a_success_followed_by_a_later_failure_reads_failed_with_the_adapters_reason(self) -> None:
        lines = fixture_lines()
        cut = next(index for index, line in enumerate(lines) if "17:23:26" in line)
        states = latest(adapter_events(lines[:cut]))
        harbor = states[("harbor", "discord")]
        self.assertEqual(harbor.state, STATE_FAILED)
        self.assertEqual(harbor.logged, "2026-11-23 17:05:01")
        self.assertIn("requesting privileged intents", harbor.reason)  # attributed across the traceback lines
        self.assertEqual(classify_reason(harbor), REASON_PRIVILEGED_INTENTS)

    def test_interleaved_profiles_keep_their_own_states_and_reasons(self) -> None:
        states = latest(adapter_events(fixture_lines()))
        quay = states[("quay", "slack")]
        self.assertEqual(quay.state, STATE_FAILED)  # connected at 16:30, failed at 17:10
        self.assertEqual(quay.reason, "")  # a Discord reason never goes to a Slack failure
        self.assertEqual(classify_reason(quay), REASON_NONE)
        self.assertEqual(states[("", "telegram")].state, STATE_CONNECTED)

    def test_a_reason_goes_to_one_failure_only_and_only_close_after_it(self) -> None:
        reason = ("2026-11-23 10:00:00,000 ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect "
                  "to Discord: boom")
        first = "2026-11-23 10:00:01,000 WARNING gateway.run: ✗ discord failed to connect (profile: one)"
        second = "2026-11-23 10:00:02,000 WARNING gateway.run: ✗ discord failed to connect (profile: two)"
        late = "2026-11-23 10:10:00,000 WARNING gateway.run: ✗ discord failed to connect (profile: one)"
        events = adapter_events([reason, first, second])
        self.assertEqual([event.reason for event in events], ["boom", ""])
        self.assertEqual(adapter_events([reason, late])[0].reason, "")

    def test_the_transient_fatal_code_is_known(self) -> None:
        event = adapter_events(fixture_lines())[0]
        self.assertEqual((event.state, classify_reason(event)), (STATE_FATAL, REASON_TRANSIENT))


class GatewayLogRead(unittest.TestCase):
    def write(self, root: Path, data: bytes, name: str = "gateway.log") -> Path:
        path = root / "logs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return root / "logs" / "gateway.log"

    def test_the_fixture_reads_with_a_truncated_last_line(self) -> None:
        log = read_gateway_log(FIXTURE)
        self.assertEqual(log.status, STATUS_READ)
        self.assertEqual(latest(list(log.events))[("harbor", "discord")].state, STATE_CONNECTED)

    def test_a_huge_line_and_bytes_that_are_not_utf8_neither_raise_nor_hide_the_lines_around_them(self) -> None:
        with TemporaryDirectory() as tmp:
            raw = FIXTURE.read_bytes()
            data = raw + b"2026-11-23 17:40:00,000 INFO gateway.run: " + b"x" * (3 << 20) + b"\n\xff\xfe\n" + (
                "2026-11-23 17:41:00,000 WARNING gateway.run: ✗ discord failed to connect (profile: harbor)\n".encode()
            )
            log = read_gateway_log(self.write(Path(tmp), data))
            self.assertEqual(log.status, STATUS_READ)
            self.assertLessEqual(log.bytes_read, 1 << 20)
            self.assertEqual(latest(list(log.events))[("harbor", "discord")].state, STATE_FAILED)
            self.assertTrue(all(len(event.reason) <= REASON_CHARS for event in log.events))
        self.assertGreater(3 << 20, LOG_LINE_CHARS)

    def test_a_tail_that_starts_mid_line_drops_the_cut_line(self) -> None:
        with TemporaryDirectory() as tmp:
            line = "2026-11-23 17:41:00,000 WARNING gateway.run: ✗ discord failed to connect (profile: harbor)\n"
            path = self.write(Path(tmp), ("noise " * 40 + "\n").encode() + line.encode())
            log = read_gateway_log(path, tail_bytes=len(line.encode()) + 10)
            self.assertEqual([event.profile for event in log.events], ["harbor"])

    def test_a_rotated_log_is_read_before_a_short_current_one(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, FIXTURE.read_bytes(), "gateway.log.1")
            path = self.write(root, b"2026-11-23 18:00:00,000 INFO gateway.run: Gateway running\n")
            states = latest(list(read_gateway_log(path).events))
            self.assertEqual(states[("harbor", "discord")].state, STATE_CONNECTED)

    def test_missing_and_unrecognized_logs_say_so(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(read_gateway_log(root / "logs" / "gateway.log").status, STATUS_MISSING)
            path = self.write(root, b"{\"event\": \"connected\"}\nsomething else\n")
            self.assertEqual(read_gateway_log(path).status, STATUS_UNRECOGNIZED)


class Reasons(unittest.TestCase):
    def test_ids_and_tokens_are_never_kept_and_the_text_is_bounded(self) -> None:
        text = bounded_reason(f"channel 1234567890123456789 refused token {TOKEN} " + "y" * 400)
        self.assertNotIn("1234567890123456789", text)
        self.assertNotIn(TOKEN, text)
        self.assertIn("<id>", text)
        self.assertIn("<redacted>", text)
        self.assertLessEqual(len(text), REASON_CHARS)

    def test_known_and_unknown_reasons(self) -> None:
        def event(reason: str = "", code: str = "", platform: str = "discord") -> AdapterEvent:
            return AdapterEvent("p", platform, STATE_FAILED, "2026-11-23 10:00:00", 0.0, reason, code)

        self.assertEqual(classify_reason(event(code="discord_intents_required")), REASON_PRIVILEGED_INTENTS)
        self.assertEqual(classify_reason(event("LoginFailure: Improper token has been passed.")), REASON_TOKEN_REJECTED)
        self.assertEqual(classify_reason(event(code="discord_auth_error")), REASON_TOKEN_REJECTED)
        self.assertEqual(classify_reason(event("Cannot connect to host discord.com:443")), REASON_UNRECOGNIZED)
        self.assertEqual(classify_reason(event()), REASON_NONE)
        self.assertEqual(classify_reason(event("requesting privileged intents", platform="slack")), REASON_UNRECOGNIZED)


class BuildAndRestartRecords(unittest.TestCase):
    def test_build_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            install = Path(tmp)
            self.assertEqual(read_build_stamp(install).status, STATUS_MISSING)
            (install / "install-stamp.json").write_text(json.dumps({"schemaVersion": 2, "commit": COMMIT, "builtAt": BUILT_AT}))
            stamp = read_build_stamp(install)
            self.assertEqual((stamp.status, stamp.commit), (STATUS_READ, COMMIT))
            self.assertAlmostEqual(stamp.built_at or 0, BUILT_EPOCH)
            for body in ('{"commit": "abc"}', "[]", "not json", '{"builtAt": "yesterday"}'):
                (install / "install-stamp.json").write_text(body)
                self.assertEqual(read_build_stamp(install).status, STATUS_UNRECOGNIZED, body)

    def test_the_obligation_record_hermes_reads(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / ".hermes"
            install = root / "hermes-agent"
            install.mkdir(parents=True)
            locks = Path(tmp) / "locks"
            locks.mkdir()
            environ = {"HERMES_GATEWAY_LOCK_DIR": str(locks)}
            self.assertEqual(read_fleet_restart_state(root, install, environ).obligation, "")
            key = hashlib.sha256(os.path.normcase(str(install.resolve())).encode()).hexdigest()[:16]
            for path in (locks / f"host-update-restart-{key}.json", locks / "host-update-restart.json",
                         root / "fleet_restart_pending"):
                with self.subTest(path=path.name):
                    path.write_text("corrupt is still owed")
                    self.assertEqual(read_fleet_restart_state(root, install, environ).obligation, str(path))
                    path.unlink()
            xdg = Path(tmp) / "state"
            (xdg / "hermes" / "gateway-locks").mkdir(parents=True)
            (xdg / "hermes" / "gateway-locks" / "host-update-restart.json").write_text("{}")
            self.assertTrue(read_fleet_restart_state(root, install, {"XDG_STATE_HOME": str(xdg)}).obligation)

    def test_the_latest_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            environ = {"HERMES_GATEWAY_LOCK_DIR": str(root / "locks")}
            self.assertEqual(read_fleet_restart_state(root, root / "hermes-agent", environ).receipt_status, STATUS_MISSING)
            receipt = root / "logs" / "update_receipts" / "latest.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({
                "schema": 1, "outcome": "success", "finished_at": "2026-11-21T11:07:46+00:00",
                "gateway_restart": {"incomplete": True, "phase_error": "replayed gateway for profile one did not come up"},
                "fleet": [{"profile": "default", "state": "current"}, {"profile": "one", "state": "stale"}],
            }))
            state = read_fleet_restart_state(root, root / "hermes-agent", environ)
            self.assertEqual((state.receipt_kind, state.restart_incomplete, state.stale_fleet), ("update", True, 1))
            self.assertIn("did not come up", state.phase_error)
            receipt.write_text(json.dumps({"schema": 1, "kind": "plugin-check", "outcome": "updates-available"}))
            state = read_fleet_restart_state(root, root / "hermes-agent", environ)
            self.assertEqual((state.receipt_kind, state.restart_incomplete), ("plugin-check", False))
            receipt.write_text("{")
            self.assertEqual(read_fleet_restart_state(root, root / "hermes-agent", environ).receipt_status,
                             STATUS_UNRECOGNIZED)


class Fleet(unittest.TestCase):
    """The composed report, with gateway records and the process listing injected."""

    def home(self, tmp: str, *, stamp: bool = True, profiles: tuple[str, ...] = ("harbor", "quay")) -> Path:
        root = Path(tmp) / ".hermes"
        (root / "hermes-agent").mkdir(parents=True)
        if stamp:
            (root / "hermes-agent" / "install-stamp.json").write_text(json.dumps({"commit": COMMIT, "builtAt": BUILT_AT}))
        for name in profiles:
            (root / "profiles" / name).mkdir(parents=True)
            (root / "profiles" / name / "config.yaml").write_text("model: {}\n")
        return root

    def run_health(self, root: Path, records: dict[str, Gateway] | None = None,
                   listed: tuple[bool, list[tuple[int, str]]] = (True, []), starts: dict[int, float] | None = None):
        records = records or {}

        def reader(home: Path) -> Gateway:
            return records.get(home.name, NO_RECORD)

        return gateway_health(
            root, environ={"HERMES_GATEWAY_LOCK_DIR": str(root / "locks")}, gateway_reader=reader,
            list_processes=lambda: listed, process_start=lambda pid: (starts or {}).get(pid),
        )

    def test_a_gateway_started_before_the_build_is_named_with_hermes_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            report = self.run_health(root, {".hermes": Gateway("running", True, 4100, active_agents=2,
                                                                 served=("default", "harbor"),
                                                                 started=BUILT_EPOCH - 2 * 86400)})
            self.assertEqual(report.gateways[0].build, BUILD_BEFORE)
            self.assertIn(FINDING_STALE_GATEWAY, report.findings)
            self.assertTrue(any("PID 4100 (2 turn(s) live now) with `hermes gateway restart`" in action
                                and RESTART_NOTE in action for action in report.next_actions))

    def test_the_records_commit_stamp_is_believed_over_its_start_time(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            early = BUILT_EPOCH - 120
            current = self.run_health(root, {".hermes": Gateway("running", True, 4100, started=early, code_sha=COMMIT)})
            self.assertEqual(current.gateways[0].build, BUILD_CURRENT)
            self.assertNotIn(FINDING_STALE_GATEWAY, current.findings)
            other = self.run_health(root, {".hermes": Gateway("running", True, 4100, started=BUILT_EPOCH + 60,
                                                               code_sha="deadbeef")})
            self.assertEqual(other.gateways[0].build, BUILD_OTHER_COMMIT)

    def test_unrecorded_processes_and_a_profile_served_twice_are_named_by_pid(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            records = {
                ".hermes": Gateway("running", True, 4100, served=("default", "harbor"), code_sha=COMMIT),
                "harbor": Gateway("running", True, 4200, code_sha=COMMIT),
            }
            listed = (True, [(4200, ""), (5100, "default"), (5200, "")])
            report = self.run_health(root, records, listed, {5100: BUILT_EPOCH - 86400, 5200: BUILT_EPOCH + 10})
            self.assertEqual([process.pid for process in report.gateways], [4100, 4200, 5100, 5200])
            self.assertEqual(report.shared_profiles, {"harbor": [4100, 4200]})
            self.assertIn(FINDING_UNRECORDED, report.findings)
            self.assertIn(FINDING_SHARED_PROFILE, report.findings)
            self.assertIn("4 gateway process(es) running, 2 recorded, serving 2 profile(s); 2 not recorded by this "
                          "Hermes root; 1 profile(s) served by more than one.", report.lines)
            text = "\n".join(report.lines)
            self.assertIn("PID 5100 runs `hermes gateway run` (`--profile default` on its command line)", text)
            self.assertIn("PID 4100 already serves that profile here", text)
            self.assertIn("find what started PID 5100, 5200", "\n".join(report.next_actions))

    def test_honest_absence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / ".hermes"
            root.mkdir()
            report = self.run_health(root, listed=(False, []))
            text = "\n".join(report.lines)
            self.assertIn("Hermes install not found", text)
            self.assertIn("no process listing is available on this platform", text)
            self.assertIn("no running Hermes gateway", text)
            self.assertIn("no Hermes update receipt", text)
            self.assertIn("(no log)", text)
            self.assertEqual(report.findings, ())
            self.assertNotIn("healthy", text)
            self.assertEqual(report.process_listing, "not_available")
        with TemporaryDirectory() as tmp:
            root = self.home(tmp, stamp=False)
            self.assertIn("no Hermes build stamp", "\n".join(self.run_health(root).lines))

    def test_hermes_pending_restart_and_an_incomplete_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            (root / "fleet_restart_pending").write_text("expected_sha=abc\n")
            receipt = root / "logs" / "update_receipts" / "latest.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"gateway_restart": {"incomplete": True, "phase_error": ""}, "fleet": []}))
            report = self.run_health(root)
            self.assertIn(FINDING_PENDING_RESTART, report.findings)
            self.assertIn(FINDING_INCOMPLETE_RESTART, report.findings)
            self.assertIn("Hermes records a pending fleet restart", "\n".join(report.lines))
            self.assertTrue(any(action.startswith("restart the gateways with Hermes' own `hermes gateway restart`")
                                for action in report.next_actions))

    def test_the_adapter_section_reads_the_host_log_and_a_profiles_own_log(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            lines = fixture_lines()
            cut = next(index for index, line in enumerate(lines) if "17:23:26" in line)
            (root / "logs").mkdir()
            (root / "logs" / "gateway.log").write_text("\n".join(lines[:cut]) + "\n", encoding="utf-8")
            (root / "profiles" / "quay" / "logs").mkdir()
            (root / "profiles" / "quay" / "logs" / "gateway.log").write_text(
                "2026-11-23 18:00:00,000 INFO gateway.run: ✓ slack connected\n", encoding="utf-8")
            record_error = ("Discord rejected the connection because privileged Gateway Intents are not enabled. "
                            "Hermes is requesting: - Message Content Intent - Server Members Intent (required for "
                            "username allowlists and/or DISCORD_ALLOWED_ROLES)")
            from omh.tui.bot_board import Platform

            records = {".hermes": Gateway("running", True, 4100, served=("default", "harbor"), code_sha=COMMIT,
                                          platforms=(Platform("harbor:discord", "fatal", record_error),))}
            report = self.run_health(root, records)
            by_key = {(state.profile, state.platform): state for state in report.adapters}
            harbor = by_key[("harbor", "discord")]
            self.assertEqual((harbor.state, harbor.reason_kind), (STATE_FAILED, REASON_PRIVILEGED_INTENTS))
            self.assertIn("Hermes requests Message Content and Server Members", harbor.fix)
            self.assertIn("Bot page, Privileged Gateway Intents", harbor.fix)
            self.assertIn("`hermes gateway restart`", harbor.fix)
            self.assertEqual(by_key[("quay", "slack")].state, STATE_CONNECTED)  # its own log's newer line wins
            self.assertIn(FINDING_ADAPTER_DOWN, report.findings)
            self.assertIn("harbor discord: failed to connect at 2026-11-23 17:05:01", "\n".join(report.lines))
            # Without Hermes' own guidance in the record, the rule is stated rather than guessed.
            unguided = self.run_health(root, {".hermes": Gateway("running", True, 4100, served=("default", "harbor"))})
            fix = {(s.profile, s.platform): s for s in unguided.adapters}[("harbor", "discord")].fix
            self.assertIn("and Server Members too when the profile has a role allowlist", fix)

    def test_a_standalone_profiles_adapter_fix_names_its_own_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            log = root / "profiles" / "harbor" / "logs" / "gateway.log"
            log.parent.mkdir()
            log.write_text("2026-11-23 18:00:00,000 ERROR gateway.run: ✗ discord error: LoginFailure: Improper token "
                           f"has been passed. {TOKEN}\n", encoding="utf-8")
            report = self.run_health(root, {"harbor": Gateway("running", True, 4200, code_sha=COMMIT)})
            state = report.adapters[0]
            self.assertEqual((state.profile, state.reason_kind), ("harbor", REASON_TOKEN_REJECTED))
            self.assertIn("`hermes --profile harbor gateway restart`", state.fix)
            self.assertNotIn(TOKEN, json.dumps(report.to_dict()))


class GatewayProcessListing(unittest.TestCase):
    def test_gateway_runs_and_their_profiles(self) -> None:
        py = "/opt/py/bin/python3"
        argvs = [
            (101, [py, "-m", "hermes_cli.main", "--profile", "default", "gateway", "run", "--quiet"]),
            (102, [py, "-m", "hermes_cli.main", "gateway", "run", "--quiet", "--idle-exit"]),
            (103, [py, "-I", "-m", "hermes_cli.main", "-p", "harbor", "gateway", "run"]),
            (104, [py, "-m", "hermes_cli.main", "--profile=quay", "gateway", "run"]),
            (105, [py, "/home/u/.hermes/hermes-agent/hermes", "gateway", "run"]),
            (106, [py, "-m", "hermes_cli.main", "chat"]),
            (107, [py, "-m", "hermes_cli.main", "gateway", "status"]),
            (108, [py, "-I", "-c", "import os; main(['gateway', 'run'])"]),
            (109, ["/bin/zsh", "-c", "hermes gateway run"]),
            (110, [py, "-m", "hermes_cli.main", "--profile", "gateway", "run"]),
            (111, [py]),
        ]
        self.assertEqual(gateway_runs(argvs),
                         [(101, "default"), (102, ""), (103, "harbor"), (104, "quay"), (105, "")])

    def test_a_kernel_argument_buffer_yields_its_arguments_and_never_its_environment(self) -> None:
        raw = (struct.pack("i", 3) + b"/opt/py/bin/python3\0\0\0\0" + b"python3\0-m\0hermes_cli.main\0"
               + b"DISCORD_BOT_TOKEN=secret\0HOME=/home/u\0")
        self.assertEqual(procargs2_argv(raw), ["python3", "-m", "hermes_cli.main"])
        self.assertEqual(procargs2_argv(raw[:30]), [])  # cut before argc strings end
        self.assertEqual(procargs2_argv(b"\0\0"), [])
        self.assertEqual(procargs2_argv(struct.pack("i", 0) + b"x\0"), [])

    def test_linux_proc_cmdline(self) -> None:
        with TemporaryDirectory() as tmp:
            proc = Path(tmp)
            (proc / "4100").mkdir()
            (proc / "4100" / "cmdline").write_bytes(b"python3\0-m\0hermes_cli.main\0gateway\0run\0")
            (proc / "self").mkdir()
            (proc / "4200").mkdir()  # no cmdline: a process that exited mid-walk
            self.assertEqual(process_listing._linux_argvs(proc), [(4100, ["python3", "-m", "hermes_cli.main", "gateway", "run"])])

    def test_no_listing_is_not_an_empty_listing(self) -> None:
        with mock.patch.object(process_listing.sys, "platform", "win32"):
            self.assertEqual(process_listing.hermes_gateway_processes(), (False, []))

    @unittest.skipUnless(process_listing.sys.platform in {"darwin", "linux"}, "the kernel listing is macOS and Linux")
    def test_the_real_listing_finds_this_process_without_spawning(self) -> None:
        with mock.patch("subprocess.Popen", side_effect=AssertionError("spawned")):
            argvs = process_listing.process_argvs()
        assert argvs is not None
        self.assertIn(os.getpid(), {pid for pid, _argv in argvs})


class DoctorRow(unittest.TestCase):
    def test_the_row_warns_never_fails_and_the_summary_prints_the_section(self) -> None:
        from omh.commands.setup import _print_doctor_summary
        from omh.maintenance.doctor import _gateway_health_check
        from omh.paths import OmhPaths

        with TemporaryDirectory() as tmp:
            root = Fleet().home(tmp)
            report = Fleet().run_health(root, listed=(True, [(5100, "default")]), starts={5100: BUILT_EPOCH - 86400})
            with mock.patch.object(health, "gateway_health", return_value=report):
                check = _gateway_health_check(OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=root))
            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "warning")
            assert check.detail is not None
            self.assertEqual(check.detail["schema_version"], "omh_gateway_health/v1")
            self.assertIn("find what started PID 5100", check.next_action)
            payload = {"ok": True, "checks": [check.__dict__], "summary": {}, "recommended_next_action": ""}
            out = io.StringIO()
            with redirect_stdout(out), mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
                _print_doctor_summary(payload)
            text = out.getvalue()
            self.assertIn("Hermes gateways (read-only)", text)
            self.assertIn("PID 5100 runs `hermes gateway run`", text)
            self.assertIn("Fix: find what started PID 5100", text)
            self.assertNotIn("- gateway_health:", text)


if __name__ == "__main__":
    unittest.main()
