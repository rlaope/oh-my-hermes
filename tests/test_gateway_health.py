"""`omh doctor`'s gateway health section: fleet against build, fleet shape, messaging adapter states.

The log fixture (`fixtures/gateway_health/host_gateway.log`) is a multiplexed
host's `logs/gateway.log` in the exact line shapes Hermes 0.23.3 writes
(`gateway/run_adapters.py`, `run_adapters_recovery.py`, `run_startup.py`, the
Discord adapter's connect failure), with invented profile and bot names: a
transient fatal error and its reconnect; the measured incident's sequence, where
a served profile's reconnect (`Secondary discord reconnect retry … (profile: …)`)
ends in the adapter's privileged-intents reason with a traceback and NO `✗`
line; the manual restart that failed the same way, this time with Hermes' `✗`
line; a second profile's Slack connecting, failing with no reason logged and
being stopped; the bot's recovery; the in-process `local` adapter; a primary
profile's line and a truncated last line.

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
from omh.maintenance.gateway_health import STATE_STALE, STATE_UNSERVED
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
    STATE_DISCONNECTED,
    STATE_FAILED,
    STATE_RETRYING,
    STATE_FATAL,
    STATUS_MISSING,
    STATUS_READ,
    STATUS_UNRECOGNIZED,
    AMBIGUOUS_PROFILE,
    AdapterEvent,
    adapter_events,
    bounded_reason,
    classify_reason,
    iso_utc,
    parse_adapter_line,
    read_build_stamp,
    read_fleet_restart_state,
    read_gateway_log,
)
from omh.system import process_listing
from omh.system.process_listing import GatewayListing, gateway_runs, procargs2_argv
from omh.tui.bot_board import Gateway, Platform

FIXTURE = Path(__file__).parent / "fixtures" / "gateway_health" / "host_gateway.log"
COMMIT = "c0ffee5389ae585ef77387a962aee05b1bcf1702"
BUILT_AT = "2026-11-21T11:06:39.131982+00:00"
BUILT_EPOCH = datetime(2026, 11, 21, 11, 6, 39, 131982, tzinfo=UTC).timestamp()
NO_RECORD = Gateway("", False, problem="no gateway record")
# Token-shaped, built at run time so no literal in the tree looks like a real credential.
TOKEN = ".".join(("x" * 24, "y" * 6, "z" * 27))


def utc(stamp: str) -> str:
    """A log stamp as the section shows it: read in this machine's local time, printed in UTC."""
    return iso_utc(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp())


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
            "2026-10-14 15:05:01,231 WARNING gateway.run: ✗ discord failed to connect (profile: harbor)":
                ("harbor", "discord", STATE_FAILED, "", ""),
            "2026-10-14 15:23:30,403 INFO gateway.run: ✓ discord connected (profile: harbor)":
                ("harbor", "discord", STATE_CONNECTED, "", ""),
            "2026-10-14 13:02:41,453 INFO gateway.run: ✓ discord reconnected (profile: harbor)":
                ("harbor", "discord", STATE_CONNECTED, "", ""),
            "2026-10-14 13:02:10,059 ERROR gateway.run: Fatal discord adapter error for multiplexed profile harbor "
            "(discord_websocket_health_stale)": ("harbor", "discord", STATE_FATAL, "", "discord_websocket_health_stale"),
            "2026-10-14 15:30:12,250 INFO gateway.run: ✓ telegram connected": ("", "telegram", STATE_CONNECTED, "", ""),
            "2026-10-14 15:30:12,250 INFO gateway.run: ✓ telegram reconnected successfully":
                ("", "telegram", STATE_CONNECTED, "", ""),
            "2026-10-14 15:30:12,250 WARNING gateway.run: ✗ telegram failed to connect": ("", "telegram", STATE_FAILED, "", ""),
            "2026-10-14 15:30:12,250 ERROR gateway.run: ✗ slack error (profile: quay): invalid_auth":
                ("quay", "slack", STATE_FAILED, "invalid_auth", ""),
            "2026-10-14 15:30:12,250 ERROR gateway.run: ✗ slack error: invalid_auth": ("", "slack", STATE_FAILED, "invalid_auth", ""),
            "2026-10-14 15:30:12,250 ERROR gateway.run: Fatal slack adapter error (slack_socket_closed): socket closed":
                ("", "slack", STATE_FATAL, "socket closed", "slack_socket_closed"),
            "2026-10-14 15:30:12,250 INFO gateway.run: ✓ telegram connected (degraded)": ("", "telegram", STATE_DEGRADED, "", ""),
            "2026-10-14 15:30:12,250 INFO gateway.run: ⚠ telegram reconnected in degraded mode (receive path not yet "
            "confirmed)": ("", "telegram", STATE_DEGRADED, "", ""),
            "2026-10-14 13:58:43,490 INFO gateway.run: Secondary discord reconnect retry in 30s (profile: harbor)":
                ("harbor", "discord", STATE_RETRYING, "", ""),
            "2026-11-11 11:45:21,000 INFO gateway.run: ✓ slack disconnected (0.42s) (profile: quay)":
                ("quay", "slack", STATE_DISCONNECTED, "", ""),
            "2026-11-11 11:45:21,000 INFO gateway.run: ✓ slack disconnected (1.07s)": ("", "slack", STATE_DISCONNECTED, "", ""),
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
            "2026-10-14 15:23:30,401 INFO hermes_plugins.platforms__discord.adapter: [Discord] Connected as Harbor#0042",
            "2026-10-14 15:05:01,233 INFO gateway.run_profile_reconcile: [MULTIPLEX] Now serving profile 'harbor' "
            "(0 adapter(s) connected; control-socket)",
            "discord.errors.PrivilegedIntentsRequired: Shard ID None is requesting privileged intents",
            "2026-10-14 15:05:01,231 WARNING gateway.run: ✗ discord failed to connect (profile: harbor) and more",
            "2026-10-14 15:31:0",
            "✓ discord connected (profile: harbor)",
            "2026-10-14 15:04:59,052 INFO gateway.run: ✓ local disconnected (0.00s) (profile: harbor)",  # no bot
            "",
        ):
            with self.subTest(line=line):
                self.assertIsNone(parse_adapter_line(line))


class AdapterHistory(unittest.TestCase):
    def test_a_failure_followed_by_a_later_success_reads_connected(self) -> None:
        states = latest(adapter_events(fixture_lines()))
        harbor = states[("harbor", "discord")]
        self.assertEqual(harbor.state, STATE_CONNECTED)
        self.assertEqual(harbor.logged, "2026-10-14 15:23:30")

    def test_a_success_followed_by_a_later_failure_reads_failed_with_the_adapters_reason(self) -> None:
        lines = fixture_lines()
        cut = next(index for index, line in enumerate(lines) if "15:23:26" in line)
        states = latest(adapter_events(lines[:cut]))
        harbor = states[("harbor", "discord")]
        self.assertEqual(harbor.state, STATE_FAILED)
        self.assertEqual(harbor.logged, "2026-10-14 15:05:01")
        self.assertIn("requesting privileged intents", harbor.reason)  # attributed across the traceback lines
        self.assertEqual(classify_reason(harbor), REASON_PRIVILEGED_INTENTS)

    def test_the_incidents_served_profile_reconnect_fails_with_no_x_line(self) -> None:
        # Hermes' secondary reconnect writes only the adapter's reason; it supersedes the transient fatal before it.
        lines = fixture_lines()
        cut = next(index for index, line in enumerate(lines) if line.startswith("2026-10-14 14:30"))
        harbor = latest(adapter_events(lines[:cut]))[("harbor", "discord")]
        self.assertEqual((harbor.state, harbor.logged), (STATE_FAILED, "2026-10-14 14:08:17"))
        self.assertEqual(classify_reason(harbor), REASON_PRIVILEGED_INTENTS)
        retry = adapter_events(lines[:7])[-1]
        self.assertEqual((retry.profile, retry.state), ("harbor", STATE_RETRYING))

    def test_connected_then_stopped_reads_disconnected(self) -> None:
        self.assertEqual(latest(adapter_events(fixture_lines()))[("quay", "slack")].state, STATE_DISCONNECTED)

    def test_interleaved_profiles_keep_their_own_states_and_reasons(self) -> None:
        lines = fixture_lines()
        cut = next(index for index, line in enumerate(lines) if line.startswith("2026-10-14 15:25"))
        states = latest(adapter_events(lines[:cut]))
        quay = states[("quay", "slack")]
        self.assertEqual(quay.state, STATE_FAILED)  # connected at 16:30, failed at 17:10
        self.assertEqual(quay.reason, "")  # a Discord reason never goes to a Slack failure
        self.assertEqual(classify_reason(quay), REASON_NONE)
        self.assertEqual(latest(adapter_events(lines))[("", "telegram")].state, STATE_CONNECTED)

    def test_a_reason_goes_to_one_failure_only_and_only_close_after_it(self) -> None:
        reason = ("2026-10-14 08:00:00,000 ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect "
                  "to Discord: boom")
        first = "2026-10-14 08:00:01,000 WARNING gateway.run: ✗ discord failed to connect (profile: one)"
        second = "2026-10-14 08:00:02,000 WARNING gateway.run: ✗ discord failed to connect (profile: two)"
        late = "2026-10-14 08:10:00,000 WARNING gateway.run: ✗ discord failed to connect (profile: one)"
        events = adapter_events([reason, first, second])
        # The reason is its own failure until `first` takes it; given to no profile, it is then withdrawn.
        self.assertEqual([(event.profile, event.reason) for event in events], [("one", "boom"), ("two", "")])
        self.assertEqual([event.reason for event in adapter_events([reason, late])], ["boom", ""])

    def test_a_reason_given_to_the_wrong_profile_is_withdrawn_when_the_x_line_names_another(self) -> None:
        retry = "2026-10-14 08:00:00,000 INFO gateway.run: Secondary discord reconnect retry in 30s (profile: one)"
        reason = ("2026-10-14 08:00:05,000 ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect "
                  "to Discord: boom")
        failed = "2026-10-14 08:00:05,050 WARNING gateway.run: ✗ discord failed to connect (profile: two)"
        events = adapter_events([retry, reason, failed])
        # `one`'s reconnect is open, so the reason is its; `two`'s startup failure does not take it.
        self.assertEqual([(event.profile, event.state, event.reason) for event in events],
                         [("one", STATE_RETRYING, ""), ("one", STATE_FAILED, "boom"), ("two", STATE_FAILED, "")])

    def test_a_connected_line_hours_earlier_never_claims_a_lone_reason(self) -> None:
        lines = [
            "2026-10-14 09:00:00,000 INFO gateway.run: ✓ discord connected (profile: alpha)",
            "2026-10-14 10:00:00,000 ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect to "
            "Discord: Shard ID None is requesting privileged intents that have not been explicitly enabled",
        ]
        states = latest(adapter_events(lines))
        self.assertEqual(states[("alpha", "discord")].state, STATE_CONNECTED)
        self.assertEqual(states[("", "discord")].state, STATE_FAILED)  # the log's own (primary) bot

    def test_two_open_reconnects_leave_a_reason_unattributed(self) -> None:
        lines = [
            "2026-10-14 08:00:00,000 INFO gateway.run: Secondary discord reconnect retry in 30s (profile: one)",
            "2026-10-14 08:00:01,000 INFO gateway.run: Secondary discord reconnect retry in 30s (profile: two)",
            "2026-10-14 08:00:05,000 ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect to "
            "Discord: boom",
            "2026-10-14 08:00:40,000 INFO gateway.run: ✓ discord reconnected (profile: two)",
        ]
        states = latest(adapter_events(lines))
        self.assertEqual(states[("one", "discord")].state, STATE_RETRYING)  # never given a reason it may not own
        self.assertEqual(states[("two", "discord")].state, STATE_CONNECTED)
        self.assertNotIn(("", "discord"), states)
        unowned = states[(AMBIGUOUS_PROFILE, "discord")]  # kept for the platform: `one` has not connected since
        self.assertEqual((unowned.candidates, unowned.reason), (("one", "two"), "boom"))
        lines.append("2026-10-14 08:01:00,000 INFO gateway.run: ✓ discord reconnected (profile: one)")
        self.assertNotIn((AMBIGUOUS_PROFILE, "discord"), latest(adapter_events(lines)))  # both are back: dropped

    def test_an_unattributable_refusal_is_said_for_the_platform_with_its_fix(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Fleet().home(tmp)
            (root / "logs").mkdir()
            (root / "logs" / "gateway.log").write_text("\n".join([
                "2026-10-14 08:00:00,000 INFO gateway.run: Secondary discord reconnect retry in 30s (profile: harbor)",
                "2026-10-14 08:00:01,000 INFO gateway.run: Secondary discord reconnect retry in 30s (profile: quay)",
                "2026-10-14 08:00:05,000 ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect "
                "to Discord: Shard ID None is requesting privileged intents that have not been explicitly enabled",
            ]) + "\n", encoding="utf-8")
            report = Fleet().run_health(root, {".hermes": Gateway("running", True, 4100, code_sha=COMMIT,
                                                                    served=("default", "harbor", "quay"))})
            text = "\n".join(report.lines)
            self.assertIn("discord: one of the profiles harbor, quay failed to connect at", text)
            self.assertIn("Privileged Gateway Intents", text)
            self.assertIn(FINDING_ADAPTER_DOWN, report.findings)
            up = tuple(Platform(f"{name}:discord", "connected", "", False, True) for name in ("harbor", "quay"))
            healed = Fleet().run_health(root, {".hermes": Gateway("running", True, 4100, code_sha=COMMIT, platforms=up,
                                                                    served=("default", "harbor", "quay"))})
            self.assertEqual(healed.findings, ())  # every candidate's record says connected: history, not a finding
            self.assertIn("each one's own gateway record says it is connected now", "\n".join(healed.lines))

    def test_a_reason_with_no_open_reconnect_belongs_to_the_x_line_that_follows(self) -> None:
        lines = [
            "2026-10-14 08:00:00,000 INFO gateway.run: ✓ discord connected (profile: one)",  # closed, not open
            "2026-10-14 08:00:05,000 ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect to "
            "Discord: boom",
            "2026-10-14 08:00:05,100 WARNING gateway.run: ✗ discord failed to connect (profile: two)",
        ]
        events = adapter_events(lines)
        self.assertEqual([(event.profile, event.state, event.reason) for event in events],
                         [("one", STATE_CONNECTED, ""), ("two", STATE_FAILED, "boom")])

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
            data = raw + b"2026-10-14 15:40:00,000 INFO gateway.run: " + b"x" * (3 << 20) + b"\n\xff\xfe\n" + (
                "2026-10-14 15:41:00,000 WARNING gateway.run: ✗ discord failed to connect (profile: harbor)\n".encode()
            )
            log = read_gateway_log(self.write(Path(tmp), data))
            self.assertEqual(log.status, STATUS_READ)
            self.assertLessEqual(log.bytes_read, 1 << 20)
            self.assertEqual(latest(list(log.events))[("harbor", "discord")].state, STATE_FAILED)
            self.assertTrue(all(len(event.reason) <= REASON_CHARS for event in log.events))
        self.assertGreater(3 << 20, LOG_LINE_CHARS)

    def test_a_tail_that_starts_mid_line_drops_the_cut_line(self) -> None:
        with TemporaryDirectory() as tmp:
            line = "2026-10-14 15:41:00,000 WARNING gateway.run: ✗ discord failed to connect (profile: harbor)\n"
            path = self.write(Path(tmp), ("noise " * 40 + "\n").encode() + line.encode())
            log = read_gateway_log(path, tail_bytes=len(line.encode()) + 10)
            self.assertEqual([event.profile for event in log.events], ["harbor"])

    def test_a_rotated_log_is_read_before_a_short_current_one(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, FIXTURE.read_bytes(), "gateway.log.1")
            path = self.write(root, b"2026-10-14 16:00:00,000 INFO gateway.run: Gateway running\n")
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

    def test_slack_telegram_ids_emails_and_queries_are_scrubbed(self) -> None:
        slack = "xoxb-" + "-".join(("1234567890", "1234567890123", "AbCdEfGhIjKlMnOpQrStUvWx"))
        telegram = "123456789:" + "A" * 35
        text = bounded_reason(f"invalid_auth for team T01ABCDEF2 user U01ABCDEFG owner a.person@example.com {slack} "
                              f"bot {telegram} at https://api.example.com/x?token=abc#frag; UNAVAILABLE stays")
        for secret in ("T01ABCDEF2", "U01ABCDEFG", "a.person@example.com", slack, telegram, "token=abc"):
            self.assertNotIn(secret, text)
        self.assertIn("https://api.example.com/x?<redacted>", text)
        self.assertIn("UNAVAILABLE stays", text)  # a capitalized word is not an id

    def test_known_and_unknown_reasons(self) -> None:
        def event(reason: str = "", code: str = "", platform: str = "discord") -> AdapterEvent:
            return AdapterEvent("p", platform, STATE_FAILED, "2026-10-14 08:00:00", 0.0, reason, code)

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
                   listed: tuple[bool, list[tuple[int, str]]] = (True, []), starts: dict[int, float] | None = None,
                   idle_exit: tuple[int, ...] = (), now: float = BUILT_EPOCH + 86400):
        records = records or {}

        def reader(home: Path) -> Gateway:
            return records.get(home.name, NO_RECORD)

        # Each listed process is the command line Hermes would show, read by the real listing parser, so a flag the
        # listing misses fails on what is reported, not on how the harness builds the listing.
        argvs = [(pid, ["/opt/py/bin/python3", "-m", "hermes_cli.main", *(["--profile", profile] if profile else []),
                        "gateway", "run", "--quiet", *(["--idle-exit"] if pid in idle_exit else [])])
                 for pid, profile in listed[1]]

        def listing() -> GatewayListing:
            if not listed[0]:
                return GatewayListing(False)
            with mock.patch.object(process_listing, "process_argvs", return_value=argvs):
                return process_listing.hermes_gateway_processes()

        # The clock is the call-time `time.time` (the default of `gateway_health`'s `now`), held still here.
        with mock.patch("time.time", return_value=now):
            return gateway_health(
                root, environ={"HERMES_GATEWAY_LOCK_DIR": str(root / "locks")}, gateway_reader=reader,
                list_processes=listing, process_start=lambda pid: (starts or {}).get(pid),
            )

    def test_a_gateway_started_before_the_build_is_named_with_hermes_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            report = self.run_health(root, {".hermes": Gateway("running", True, 4100, active_agents=2,
                                                                 served=("default", "harbor"),
                                                                 started=BUILT_EPOCH - 2 * 86400)})
            self.assertEqual(report.gateways[0].build, BUILD_BEFORE)
            self.assertIn(FINDING_STALE_GATEWAY, report.findings)
            self.assertTrue(any("PID 4100 (2 turn(s) live now) with `hermes -p default gateway restart`" in action
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
            (root / "hermes-agent" / "install-stamp.json").write_text(json.dumps({"commit": COMMIT[:8], "builtAt": BUILT_AT}))
            short = self.run_health(root, {".hermes": Gateway("running", True, 4100, started=early, code_sha=COMMIT)})
            self.assertEqual(short.gateways[0].build, BUILD_CURRENT)  # a short stamp and a full record agree

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
            self.assertIn("same profile name as PID 4100 here", text)
            self.assertIn("find what started PID 5100, 5200", "\n".join(report.next_actions))

    def test_an_unrecorded_process_is_never_called_stale_or_this_homes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            records = {".hermes": Gateway("running", True, 4100, served=("default",), code_sha=COMMIT)}
            report = self.run_health(root, records, (True, [(5100, "default")]), {5100: BUILT_EPOCH - 86400})
            self.assertEqual(report.findings, (FINDING_UNRECORDED,))
            text = "\n".join(report.lines)
            self.assertIn("that is before this install's build (2026-11-21T11:06:39Z): if it runs this install, it "
                          "serves pre-update code", text)
            self.assertIn("carries the same profile name as PID 4100 here, and which home it serves is not recorded", text)
            self.assertNotIn("already serves", text)
            self.assertIn("the process listing recognizes", text)

    def test_a_clients_idle_exit_gateway_is_said_as_ending_itself_and_is_no_finding(self) -> None:
        # One `hermes chat` in a throwaway home (an OMH dispatch's child, a script, a test) auto-starts a detached
        # `gateway run --idle-exit` that Hermes ends once idle: not a stray for the person to stop.
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            records = {".hermes": Gateway("running", True, 4100, served=("default",), code_sha=COMMIT)}
            report = self.run_health(root, records, (True, [(5100, "default")]), {5100: BUILT_EPOCH + 10},
                                     idle_exit=(5100,), now=BUILT_EPOCH + 70)
            self.assertEqual(report.findings, ())
            self.assertEqual(health.asdict(report.gateways[1]).get("idle_exit"), True)
            text = "\n".join(report.lines)
            self.assertIn("PID 5100 runs `hermes gateway run --idle-exit` (`--profile default` on its command line) "
                          "and no record under this Hermes root names it", text)
            self.assertIn("When its idle exit is armed, Hermes ends it after `gateway.unmanaged_idle_exit_seconds`", text)
            self.assertNotIn("same profile name as PID 4100", text)
            self.assertIn("2 gateway process(es) running, 1 recorded, serving 1 profile(s); 1 not recorded by this "
                          "Hermes root, 1 of them a client's idle-exit gateway.", report.lines)
            self.assertEqual(report.next_actions, ())

    def test_an_idle_exit_gateway_beside_a_stray_leaves_only_the_stray_to_find(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            report = self.run_health(root, {}, (True, [(5100, "default"), (5200, "")]), {5100: BUILT_EPOCH},
                                     idle_exit=(5100,), now=BUILT_EPOCH + 60)
            self.assertEqual(report.findings, (FINDING_UNRECORDED,))
            actions = "\n".join(report.next_actions)
            self.assertIn("find what started PID 5200:", actions)
            self.assertNotIn("5100", actions)

    def test_an_idle_exit_gateway_past_the_threshold_is_a_stray_again(self) -> None:
        # Hermes keeps such a gateway up when its idle exit is off, a supervisor is detected, or a probe fails
        # closed; past `IDLE_EXIT_STALE_SECONDS` it is reported as a stray, with what may hold it.
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            report = self.run_health(root, {}, (True, [(5100, "default")]), {5100: BUILT_EPOCH},
                                     idle_exit=(5100,), now=BUILT_EPOCH + 2 * 3600)
            self.assertEqual(report.findings, (FINDING_UNRECORDED,))
            self.assertEqual(health.asdict(report.gateways[0]).get("overdue"), True)
            self.assertIn("find what started PID 5100:", "\n".join(report.next_actions))
            text = "\n".join(report.lines)
            self.assertIn("has not exited after more than 3600 s", text)
            self.assertIn("started 2026-11-21T11:06:39Z", text)
            self.assertIn("sets the value to 0 or when Hermes detects a supervisor", text)
            self.assertIn("an idle check of its own fails", text)

    def test_an_idle_exit_gateway_of_unknown_start_is_said_as_such_and_is_no_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            report = self.run_health(root, {}, (True, [(5100, "default")]), idle_exit=(5100,))
            self.assertEqual(report.findings, ())
            self.assertIn("Its start time could not be read.", "\n".join(report.lines))

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
            cut = next(index for index, line in enumerate(lines) if "15:23:26" in line)
            (root / "logs").mkdir()
            (root / "logs" / "gateway.log").write_text("\n".join(lines[:cut]) + "\n", encoding="utf-8")
            (root / "profiles" / "quay" / "logs").mkdir()
            (root / "profiles" / "quay" / "logs" / "gateway.log").write_text(
                "2026-10-14 16:00:00,000 INFO gateway.run: ✓ slack connected\n", encoding="utf-8")
            record_error = ("Discord rejected the connection because privileged Gateway Intents are not enabled. "
                            "Hermes is requesting: - Message Content Intent - Server Members Intent (required for "
                            "username allowlists and/or DISCORD_ALLOWED_ROLES)")
            records = {".hermes": Gateway("running", True, 4100, served=("default", "harbor", "quay"), code_sha=COMMIT,
                                          platforms=(Platform("harbor:discord", "fatal", record_error, True, True,
                                                              "discord_intents_required"),))}
            report = self.run_health(root, records)
            by_key = {(state.profile, state.platform): state for state in report.adapters}
            harbor = by_key[("harbor", "discord")]
            self.assertEqual((harbor.state, harbor.reason_kind, harbor.source), ("fatal", REASON_PRIVILEGED_INTENTS, "record"))
            self.assertIn("requesting privileged intents", harbor.reason)  # the log's own words, this run
            self.assertIn("Hermes requests Message Content and Server Members", harbor.fix)
            self.assertIn("Bot page, Privileged Gateway Intents", harbor.fix)
            self.assertIn("`hermes -p default gateway restart`", harbor.fix)  # named: never the sticky profile
            self.assertEqual(by_key[("quay", "slack")].state, STATE_CONNECTED)  # its own log's newer line wins
            self.assertIn(FINDING_ADAPTER_DOWN, report.findings)
            self.assertIn(f"harbor discord: `fatal` by the serving gateway's own record (latest line "
                          f"{utc('2026-10-14 15:05:01')}); Hermes flags it as needing attention.", "\n".join(report.lines))
            # Without Hermes' own guidance in the record, the rule is stated rather than guessed.
            unguided = self.run_health(root, {".hermes": Gateway("running", True, 4100, served=("default", "harbor", "quay"))})
            self.assertIn(f"harbor discord: failed to connect at {utc('2026-10-14 15:05:01')}", "\n".join(unguided.lines))
            fix = {(s.profile, s.platform): s for s in unguided.adapters}[("harbor", "discord")].fix
            self.assertIn("and Server Members too when the profile has a role allowlist", fix)

    def test_the_record_decides_now_and_the_log_only_explains(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            (root / "logs").mkdir()
            log = root / "logs" / "gateway.log"
            log.write_text("2026-10-14 16:00:00,000 WARNING gateway.run: ✗ slack failed to connect (profile: quay)\n"
                           "2026-10-14 16:00:00,000 INFO gateway.run: ✓ discord connected (profile: harbor)\n",
                           encoding="utf-8")
            platforms = (Platform("quay:slack", "connected", "", False, True),
                         Platform("harbor:discord", "fatal", "Discord bot token rejected: x", False, True, "discord_auth_error"),
                         Platform("harbor:telegram", "connected", "", False, False))  # stamped by another process
            report = self.run_health(root, {".hermes": Gateway("running", True, 4100, served=("default", "harbor", "quay"),
                                                                 platforms=platforms)})
            by_key = {(state.profile, state.platform): state for state in report.adapters}
            self.assertEqual(by_key[("quay", "slack")].state, STATE_CONNECTED)  # record: connected, log: a failure
            self.assertEqual(by_key[("quay", "slack")].reason_kind, "")
            self.assertEqual((by_key[("harbor", "discord")].state, by_key[("harbor", "discord")].reason_kind),
                             ("fatal", REASON_TOKEN_REJECTED))  # record: fatal, log: connected
            self.assertNotIn(("harbor", "telegram"), by_key)  # not this process's entry, and no log line

    def test_a_line_from_an_earlier_run_or_for_an_unserved_profile_never_reads_as_now(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            (root / "logs").mkdir()
            (root / "logs" / "gateway.log").write_text(
                "2026-11-08 17:07:26,000 INFO gateway.run: ✓ slack connected (profile: harbor)\n"
                "2026-11-08 17:07:27,000 INFO gateway.run: ✓ discord connected (profile: quay)\n", encoding="utf-8")
            started = datetime(2026, 11, 21, 11, 4, 27).timestamp()
            report = self.run_health(root, {".hermes": Gateway("running", True, 4100, served=("default", "harbor"),
                                                                 started=started, code_sha=COMMIT)})
            by_key = {(state.profile, state.platform): state for state in report.adapters}
            stale = by_key[("harbor", "slack")]
            self.assertEqual((stale.state, stale.last_state, stale.reason_kind), (STATE_STALE, STATE_CONNECTED, ""))
            self.assertEqual(by_key[("quay", "discord")].state, STATE_UNSERVED)
            text = "\n".join(report.lines)
            self.assertIn("harbor slack: no adapter line since the gateway serving it started", text)
            self.assertIn("quay discord: no running gateway serves quay", text)
            self.assertNotIn("slack: connected", text)
            self.assertEqual(report.findings, ())

    def test_record_states_that_are_not_failures_raise_no_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            for state, code, message, words in (
                ("disabled", "multiplex_shared_ingress", "another profile owns this ingress",
                 "harbor discord: disabled by Hermes: another profile owns this ingress"),
                ("connecting", "", "", "harbor discord: connecting now"),
                ("warming_up", "", "", "harbor discord: state `warming_up`, which this check does not know"),
            ):
                with self.subTest(state=state):
                    platforms = (Platform("harbor:discord", state, message, False, True, code),)
                    report = self.run_health(root, {".hermes": Gateway("running", True, 4100, code_sha=COMMIT,
                                                                         served=("default", "harbor"),
                                                                         platforms=platforms)})
                    self.assertEqual(report.findings, ())
                    self.assertEqual(report.adapters[0].reason_kind, "")
                    self.assertIn(words, "\n".join(report.lines))
                    self.assertEqual(report.next_actions, ())

    def test_a_retry_hermes_flags_as_needing_attention_is_a_finding(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            platforms = (Platform("harbor:discord", "retrying", "", True, True, "discord_websocket_health_stale"),)
            report = self.run_health(root, {".hermes": Gateway("running", True, 4100, served=("default", "harbor"),
                                                                 platforms=platforms)})
            state = report.adapters[0]
            self.assertTrue(state.needs_attention)
            self.assertIn(FINDING_ADAPTER_DOWN, report.findings)
            self.assertIn("long enough to flag it as needing attention", state.fix)
            calm = self.run_health(root, {".hermes": Gateway("running", True, 4100, served=("default", "harbor"),
                                                               platforms=(Platform("harbor:discord", "retrying", "", False,
                                                                                   True, "discord_websocket_health_stale"),))})
            self.assertEqual(calm.findings, ())
            self.assertIn("harbor discord: reconnecting; Hermes retries it on its own", "\n".join(calm.lines))

    def test_within_one_log_the_line_written_last_wins_whatever_its_stamp(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            (root / "logs").mkdir()
            (root / "logs" / "gateway.log").write_text(
                "2027-01-01 00:00:00,000 INFO gateway.run: ✓ discord connected (profile: harbor)\n"
                "2026-10-14 08:00:00,000 WARNING gateway.run: ✗ discord failed to connect (profile: harbor)\n",
                encoding="utf-8")
            report = self.run_health(root, {".hermes": Gateway("running", True, 4100, served=("default", "harbor"))})
            self.assertEqual(report.adapters[0].state, STATE_FAILED)
            self.assertEqual(report.adapters[0].logged_as_written, "2026-10-14 08:00:00")
            self.assertTrue(report.adapters[0].logged.endswith("Z"))  # shown in UTC, as the gateway starts are

    def test_a_standalone_profiles_adapter_fix_names_its_own_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            log = root / "profiles" / "harbor" / "logs" / "gateway.log"
            log.parent.mkdir()
            log.write_text("2026-10-14 16:00:00,000 ERROR gateway.run: ✗ discord error: LoginFailure: Improper token "
                           f"has been passed. {TOKEN}\n", encoding="utf-8")
            report = self.run_health(root, {"harbor": Gateway("running", True, 4200, code_sha=COMMIT)})
            state = report.adapters[0]
            self.assertEqual((state.profile, state.reason_kind), ("harbor", REASON_TOKEN_REJECTED))
            self.assertIn("`hermes -p harbor gateway restart`", state.fix)
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
            # Hermes' launcher (`.hermes/bin/hermes`): `exec python -I -c '<bootstrap>' "$@"`.
            (112, [py, "-I", "-c", "import sys\nsys.path.insert(0, '/x/hermes-agent')\nfrom hermes_cli.main import main",
                   "gateway", "run", "--external-supervisor"]),
            (113, [py, "-I", "-c", "...hermes_cli...", "--profile", "harbor", "gateway", "run", "--replace"]),
            # Hermes' stderr stamper around the launcher is a wrapper, not a gateway.
            (114, [py, "-I", "-c", "...hermes_cli...", "--run-module", "hermes_cli.stderr_timestamp", "--",
                   "/x/.hermes/bin/hermes", "gateway", "run"]),
        ]
        self.assertEqual(gateway_runs(argvs), [(101, "default"), (102, ""), (103, "harbor"), (104, "quay"), (105, ""),
                                               (112, ""), (113, "harbor")])

    def test_a_retitled_hermes_is_said_and_not_counted(self) -> None:
        argvs = [(201, ["hermes"]), (202, ["python3", "-m", "hermes_cli.main", "gateway", "run"])]
        with mock.patch.object(process_listing, "process_argvs", return_value=argvs):
            self.assertEqual(process_listing.hermes_gateway_processes(), GatewayListing(True, ((202, ""),), (201,)))

    def test_a_clients_idle_exit_gateway_is_listed_as_such(self) -> None:
        # Hermes' `spawn_unmanaged_gateway` (a chat/TUI/cron client's own start) adds `--idle-exit`; for a home
        # outside `<root>/profiles/` it also passes `--profile default` as its selector.
        py = "/opt/py/bin/python3"
        argvs = [
            (301, [py, "-m", "hermes_cli.main", "--profile", "default", "gateway", "run", "--quiet", "--idle-exit"]),
            (302, [py, "-m", "hermes_cli.main", "--profile", "default", "gateway", "run", "--quiet"]),
            (303, [py, "-m", "hermes_cli.main", "chat", "--idle-exit"]),
            # The flag counts only after `gateway run`, never as a profile name or before the subcommand.
            (304, [py, "-m", "hermes_cli.main", "--profile", "--idle-exit", "gateway", "run", "--quiet"]),
        ]
        with mock.patch.object(process_listing, "process_argvs", return_value=argvs):
            listing = process_listing.hermes_gateway_processes()
        self.assertEqual(listing.gateways, ((301, "default"), (302, "default"), (304, "--idle-exit")))
        self.assertEqual(getattr(listing, "idle_exit", None), (301,))

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
            uid = (proc / "4100").stat().st_uid  # the fixture's own owner: `os.getuid` does not exist on Windows
            self.assertEqual(process_listing._linux_argvs(proc, uid),
                             [(4100, ["python3", "-m", "hermes_cli.main", "gateway", "run"])])
            self.assertEqual(process_listing._linux_argvs(proc, uid + 1), [])  # another user's process is not listed

    def test_no_listing_is_not_an_empty_listing(self) -> None:
        with mock.patch.object(process_listing.sys, "platform", "win32"):
            self.assertEqual(process_listing.hermes_gateway_processes(), GatewayListing(False))

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

    def test_a_reader_that_raises_costs_only_this_row(self) -> None:
        from omh.maintenance.doctor import _gateway_health_check, run_doctor
        from omh.paths import OmhPaths

        with TemporaryDirectory() as tmp:
            paths = OmhPaths(omh_home=Path(tmp) / ".omh", hermes_home=Path(tmp) / ".hermes")
            with mock.patch.object(health, "gateway_health", side_effect=TypeError("reshaped record")):
                check = _gateway_health_check(paths)
                rows = run_doctor(paths, state_write=False)
            self.assertEqual((check.ok, check.severity, check.observed), (True, "warning", False))
            self.assertEqual(check.message, "gateway health could not be read: TypeError")
            names = [row.name for row in rows]
            self.assertIn("gateway_health", names)
            self.assertIn("hermes_gateway", names)  # the rows around it still ran
            self.assertIn("plugin_delegation_protocol", names)


if __name__ == "__main__":
    unittest.main()
