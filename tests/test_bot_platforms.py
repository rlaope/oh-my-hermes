"""Each Hermes bot's messaging platforms, per bot (`gateway_health.bot_platforms`, `omh hermes platforms`).

The per-bot view is question 3 of `omh doctor`'s gateway health section, read by
the same code: the serving gateway's record entry first, else the newest log
line of that gateway's run. These cases pin what each surface (the TUI bot
board, omher through `omh hermes platforms`) is handed: the orderings that must
read as connected or as not connected, the states that must read as unknown,
honest absence, the log shapes a machine really has (CRLF, rotated, huge, cut
mid-write), and that no log line, token or address leaves the producer.

Everything is synthetic: neutral names (`demo-bot`), records injected, logs
written into a temporary home. No process is listed and none is run.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import datetime
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from omh.maintenance.gateway_health import BOT_PLATFORMS_SCHEMA, bot_platforms, bot_platforms_payload
from _credential_fixtures import AWS_ACCESS_KEY_ID, AWS_TEMPORARY_ACCESS_KEY_ID
from omh.maintenance import hermes_gateway_formats as formats
from omh.maintenance.gateway_health import _adapter_line, gateway_health
from omh.maintenance.hermes_gateway_formats import (
    REASON_PRIVILEGED_INTENTS,
    REASON_TOKEN_REJECTED,
    REASON_TRANSIENT,
    LogCache,
    bounded_reason,
    iso_utc,
)
from omh.tui.bot_board import BotPlatforms, Gateway, Platform, PlatformStatus

BOT = "demo-bot"
NO_RECORD = Gateway("", False, problem="no gateway record")
# Token- and webhook-shaped, built at run time so no literal in the tree looks like a real credential.
TOKEN = ".".join(("x" * 24, "y" * 6, "z" * 27))
WEBHOOK = "https://discord.com/api/webhooks/" + "1" * 18 + "/" + "w" * 40 + "?wait=" + "q" * 12
SLACK_HOOK = "https://hooks.slack.com/services/" + "/".join(("T" + "0" * 8, "B" + "0" * 8, "s" * 24))
API_KEY = "k7" * 24
AWS_SECRET_SAMPLE = "/".join(("wJalrXUtnFEMI", "K7MDENG", "bPxRfiCY" + "EXAMPLEKEY"))  # AWS's documented example shape
INTENTS_REASON = ("Shard ID None is requesting privileged intents that have not been explicitly enabled in the "
                  "developer portal.")
RECORD_GUIDANCE = ("Discord rejected the connection because privileged Gateway Intents are not enabled. Hermes is "
                   "requesting: - Message Content Intent - Server Members Intent (required for username allowlists "
                   "and/or DISCORD_ALLOWED_ROLES). Enable them in the Developer Portal (Bot > Privileged Gateway Intents).")


def formats_listing():
    from omh.system.process_listing import GatewayListing

    return GatewayListing(True, ())


def stamp(day: int, hour: int, minute: int = 0) -> str:
    return f"2020-01-{day:02d} {hour:02d}:{minute:02d}:00,000"


def epoch(day: int, hour: int, minute: int = 0) -> float:
    return datetime(2020, 1, day, hour, minute).timestamp()


def connected(day: int, hour: int, minute: int = 0) -> str:
    return f"{stamp(day, hour, minute)} INFO gateway.run: ✓ discord connected (profile: {BOT})"


def fatal(day: int, hour: int, minute: int = 0, code: str = "discord_intents_required") -> str:
    return (f"{stamp(day, hour, minute)} ERROR gateway.run: Fatal discord adapter error for multiplexed profile {BOT} "
            f"({code})")


def rescanned(day: int, hour: int, minute: int = 0, connected_count: int = 0) -> str:
    return (f"{stamp(day, hour, minute)} INFO gateway.run_profile_reconcile: [MULTIPLEX] Re-scanned profile '{BOT}' "
            f"after config/.env change ({connected_count} adapter(s) connected)")


def refused(day: int, hour: int, minute: int = 0) -> str:
    return (f"{stamp(day, hour, minute)} ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect to "
            f"Discord: {INTENTS_REASON}\n{stamp(day, hour, minute)} WARNING gateway.run: ✗ discord failed to connect "
            f"(profile: {BOT})")


class PerBot(unittest.TestCase):
    def home(self, tmp: str, *, profiles: tuple[str, ...] = (BOT,)) -> Path:
        root = Path(tmp) / ".hermes"
        root.mkdir()
        for name in profiles:
            (root / "profiles" / name).mkdir(parents=True)
            (root / "profiles" / name / "config.yaml").write_text("model: {}\n")
        return root

    def host(self, root: Path, *lines: str, newline: str = "\n") -> Path:
        log = root / "logs" / "gateway.log"
        log.parent.mkdir(exist_ok=True)
        log.write_bytes(newline.join(lines).encode("utf-8") + newline.encode())
        return log

    def read(self, root: Path, records: dict[str, Gateway] | None = None, **kwargs) -> dict[str, BotPlatforms]:
        records = records or {}
        found = bot_platforms(root, gateway_reader=lambda home: records.get(home.name, NO_RECORD), **kwargs)
        return {bot.profile: bot for bot in found}

    def serving(self, started: float, *platforms: Platform) -> dict[str, Gateway]:
        return {".hermes": Gateway("running", True, 4100, served=("default", BOT), started=started, platforms=platforms)}

    def only(self, bots: dict[str, BotPlatforms], name: str = BOT) -> PlatformStatus:
        self.assertEqual(len(bots[name].platforms), 1, bots[name])
        return bots[name].platforms[0]

    # ── orderings ──────────────────────────────────────────────────────────

    def test_a_refusal_three_days_ago_then_a_later_connect_reads_connected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, refused(20, 9), connected(23, 9))
            state = self.only(self.read(root, self.serving(epoch(20, 8))))
            self.assertEqual((state.status, state.attention, state.since, state.reason_kind), ("connected", False, "", ""))

    def test_a_connect_then_a_later_fatal_error_reads_disconnected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, connected(23, 9),
                      f"{stamp(23, 10)} ERROR gateway.run: Fatal discord adapter error for multiplexed profile {BOT} "
                      "(discord_auth_error)")
            state = self.only(self.read(root, self.serving(epoch(23, 8))))
            self.assertEqual((state.status, state.attention, state.reason_kind), ("disconnected", True, REASON_TOKEN_REJECTED))
            self.assertEqual(state.since, iso_utc(epoch(23, 10)))
            self.assertEqual(state.restart, "hermes -p default gateway restart")  # the host serves it: named, never sticky
            self.assertIn("reset it in the Discord Developer Portal", state.fix)

    def test_a_connect_then_refusals_reads_failed_since_the_first_one_with_hermes_guidance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, connected(23, 8), refused(23, 9), refused(23, 9, 30))
            record = Platform(f"{BOT}:discord", "fatal", RECORD_GUIDANCE, True, True, "discord_intents_required")
            state = self.only(self.read(root, self.serving(epoch(23, 7), record)))
            self.assertEqual((state.status, state.attention, state.reason_kind),
                             ("disconnected", True, REASON_PRIVILEGED_INTENTS))  # the record's own state: fatal
            self.assertEqual(state.since, iso_utc(epoch(23, 9)), "since the first refusal after the connect")
            self.assertEqual(state.logged, iso_utc(epoch(23, 9, 30)))
            self.assertEqual(state.intents, ("Message Content", "Server Members"))
            self.assertIn("requesting privileged intents", state.reason)  # the log's own words, this run
            self.assertIn("Message Content Intent - Server Members Intent", state.guidance)  # Hermes' record, whole
            self.assertIn("Bot page, Privileged Gateway Intents", state.fix)

    def test_without_hermes_guidance_no_intent_is_guessed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, refused(23, 9))
            state = self.only(self.read(root, self.serving(epoch(23, 8))))
            self.assertEqual((state.status, state.reason_kind, state.intents, state.guidance),
                             ("failed", REASON_PRIVILEGED_INTENTS, (), ""))
            self.assertIn("and Server Members too when the profile has a role allowlist", state.fix)

    def test_a_reconnect_hermes_retries_on_its_own_reads_reconnecting_without_attention(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, connected(23, 8),
                      f"{stamp(23, 9)} ERROR gateway.run: Fatal discord adapter error for multiplexed profile {BOT} "
                      "(discord_websocket_health_stale)",
                      f"{stamp(23, 9, 1)} INFO gateway.run: Secondary discord reconnect retry in 30s (profile: {BOT})")
            state = self.only(self.read(root, self.serving(epoch(23, 7))))
            self.assertEqual((state.status, state.attention, state.since), ("reconnecting", False, iso_utc(epoch(23, 9))))
            transient = self.only(self.read(root, self.serving(epoch(23, 7), Platform(
                f"{BOT}:discord", "retrying", "", True, True, "discord_websocket_health_stale"))))
            self.assertEqual((transient.status, transient.attention, transient.reason_kind),
                             ("reconnecting", True, REASON_TRANSIENT), "Hermes flags it as needing a person")

    def test_the_record_decides_now_over_a_newer_failure_line(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, refused(23, 9))
            state = self.only(self.read(root, self.serving(epoch(23, 8), Platform(f"{BOT}:discord", "connected",
                                                                                   current=True))))
            self.assertEqual((state.status, state.attention, state.since), ("connected", False, ""))

    def test_a_platform_removed_from_a_bot_shows_nothing_after_hermes_serves_it_again(self) -> None:
        # Hermes drops a profile's verdicts when its config or .env changes (Discord removed, a token replaced) and
        # serves it again: the old failure is from before that, so with no record entry there is nothing to show.
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            records = self.serving(epoch(23, 7))
            for before in (fatal(23, 8), refused(23, 8)):
                with self.subTest(before=before[:60]):
                    self.host(root, before, rescanned(23, 9))
                    self.assertEqual(self.read(root, records)[BOT].platforms, ())
                    report = gateway_health(root, environ={}, gateway_reader=lambda home: records.get(home.name, NO_RECORD),
                                            list_processes=formats_listing, process_start=lambda pid: None)
                    self.assertNotIn("adapter_not_connected", report.findings)
                    self.assertIn(f"no adapter line since Hermes served {BOT} again", "\n".join(report.lines))

    def test_after_a_re_serve_a_connect_or_a_new_failure_is_the_state_now(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            records = self.serving(epoch(23, 7))
            self.host(root, fatal(23, 8), rescanned(23, 9), connected(23, 9, 1))
            self.assertEqual(self.only(self.read(root, records)).status, "connected")
            self.host(root, fatal(23, 8), rescanned(23, 9), refused(23, 9, 30))
            state = self.only(self.read(root, records))
            self.assertEqual((state.status, state.since), ("failed", iso_utc(epoch(23, 9, 30))),
                             "since restarts at the new failure")
            self.host(root, rescanned(23, 9), connected(23, 9, 1), fatal(23, 10, code="discord_auth_error"))
            state = self.only(self.read(root, records))
            self.assertEqual((state.status, state.attention, state.since), ("disconnected", True, iso_utc(epoch(23, 10))))

    def test_a_re_scan_that_kept_the_connection_then_a_much_later_failure_reads_disconnected_since_then(self) -> None:
        # The generic shape behind the measured outage: a config change re-scans the bot while it stays connected,
        # and hours later a reconnect is refused for privileged intents with no line after it.
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            records = self.serving(epoch(23, 7))
            self.host(root, connected(23, 8), rescanned(23, 8, 1, connected_count=1),
                      f"{stamp(23, 14)} INFO gateway.run: Secondary discord reconnect retry in 30s (profile: {BOT})",
                      f"{stamp(23, 14, 1)} ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect to "
                      f"Discord: {INTENTS_REASON}",
                      fatal(23, 14, 2))
            state = self.only(self.read(root, records))
            self.assertEqual((state.status, state.attention, state.reason_kind),
                             ("disconnected", True, REASON_PRIVILEGED_INTENTS))
            self.assertEqual(state.since, iso_utc(epoch(23, 14)), "since the later reconnect, not the re-scan")

    def test_a_failure_of_the_re_serve_itself_still_counts(self) -> None:
        # Hermes logs "Now serving" / "Re-scanned" after the adapters it restarted failed: those lines are that attempt's.
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, refused(23, 9),
                      f"{stamp(23, 9)} INFO gateway.run_profile_reconcile: [MULTIPLEX] Now serving profile '{BOT}' "
                      "(0 adapter(s) connected; control-socket)")
            state = self.only(self.read(root, self.serving(epoch(23, 7))))
            self.assertEqual((state.status, state.reason_kind), ("failed", REASON_PRIVILEGED_INTENTS))
            self.host(root, connected(23, 8), rescanned(23, 9))
            self.assertEqual(self.read(root, self.serving(epoch(23, 7)))[BOT].platforms, (),
                             "an old connect is no more believed than an old failure")

    # ── unknown is never connected and never disconnected ──────────────────

    def test_lines_that_say_nothing_about_now_read_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp, profiles=(BOT, "other-bot"))
            self.host(root, refused(20, 9),
                      f"{stamp(20, 9)} INFO gateway.run: ✓ slack connected (profile: other-bot)")
            records = {".hermes": Gateway("running", True, 4100, served=("default", BOT), started=epoch(23, 8))}
            bots = self.read(root, records)
            earlier, unserved = self.only(bots), self.only(bots, "other-bot")
            self.assertEqual((earlier.status, earlier.unknown_why, earlier.attention), ("unknown", "earlier_run", False))
            self.assertEqual((unserved.status, unserved.unknown_why), ("unknown", "not_served"))
            self.assertEqual(earlier.since, "")
            for state in (earlier, unserved):
                self.assertNotIn(state.status, ("connected", "failed", "disconnected", "reconnecting"))

    def test_a_failure_the_log_cannot_give_to_one_bot_is_unknown_for_each(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp, profiles=(BOT, "other-bot"))
            self.host(root,
                      f"{stamp(23, 9)} INFO gateway.run: Secondary discord reconnect retry in 30s (profile: {BOT})",
                      f"{stamp(23, 9)} INFO gateway.run: Secondary discord reconnect retry in 30s (profile: other-bot)",
                      f"{stamp(23, 9, 1)} ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect "
                      f"to Discord: {INTENTS_REASON}")
            records = {".hermes": Gateway("running", True, 4100, served=("default", BOT, "other-bot"),
                                          started=epoch(23, 8))}
            bots = self.read(root, records)
            for name in (BOT, "other-bot"):
                with self.subTest(name=name):
                    state = self.only(bots, name)
                    # each has its own newer retry line, which is the state now; the shared refusal is not theirs alone
                    self.assertEqual(state.status, "reconnecting")
            mine = Platform(f"{BOT}:discord", "connected", current=True)
            other = Platform("other-bot:discord", "connected", current=True)
            records[".hermes"] = Gateway("running", True, 4100, served=("default", BOT, "other-bot"),
                                         started=epoch(23, 8), platforms=(mine, other))
            self.assertEqual({self.only(self.read(root, records), name).status for name in (BOT, "other-bot")},
                             {"connected"}, "each record says it is up: the line is history")

    # ── honest absence ─────────────────────────────────────────────────────

    def test_a_bot_with_no_messaging_platform_or_no_log_shows_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            bots = self.read(root, self.serving(epoch(23, 8)))
            self.assertEqual(bots[BOT].platforms, ())
            self.assertEqual(bots[BOT].log, "missing")
            self.assertEqual(bots["default"].log, "missing")
            self.host(root, f"{stamp(23, 9)} INFO gateway.run: ✓ local disconnected (0.00s) (profile: {BOT})")
            self.assertEqual(self.read(root, self.serving(epoch(23, 8)))[BOT].platforms, (),
                             "Hermes' in-process local adapter is no messaging platform")

    def test_an_unreadable_host_log_means_an_empty_list_cannot_be_believed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            log = self.host(root, "not a line Hermes writes")
            bots = self.read(root, self.serving(epoch(23, 8)))
            self.assertEqual((bots["default"].log, bots[BOT].log), ("unrecognized", "unrecognized"))
            log.write_text(connected(23, 9) + "\n", encoding="utf-8")
            self.assertEqual(self.read(root, self.serving(epoch(23, 8)))[BOT].log, "missing")

    def test_a_record_entry_alone_is_enough_and_a_state_it_does_not_know_is_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            state = self.only(self.read(root, self.serving(epoch(23, 8), Platform(f"{BOT}:slack", "warming_up",
                                                                                   current=True))))
            self.assertEqual((state.platform, state.status, state.unknown_why), ("slack", "unknown", "unknown_state"))
            for record_state, status in (("connecting", "connecting"), ("disabled", "disabled"),
                                         ("degraded", "degraded")):
                with self.subTest(record_state=record_state):
                    state = self.only(self.read(root, self.serving(epoch(23, 8), Platform(
                        f"{BOT}:slack", record_state, current=True))))
                    self.assertEqual((state.status, state.attention), (status, False))

    # ── the log shapes a machine has ───────────────────────────────────────

    def test_a_crlf_log_reads_the_same(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, connected(23, 8), *refused(23, 9).split("\n"), newline="\r\n")
            state = self.only(self.read(root, self.serving(epoch(23, 7))))
            self.assertEqual((state.status, state.reason_kind), ("failed", REASON_PRIVILEGED_INTENTS))
            self.assertNotIn("\r", state.reason)

    def test_a_line_cut_mid_write_is_left_and_the_state_before_it_stands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            log = self.host(root, connected(23, 8))
            with log.open("ab") as handle:
                handle.write(f"{stamp(23, 9)} WARNING gateway.run: ✗ discord fail".encode())  # no newline yet
            state = self.only(self.read(root, self.serving(epoch(23, 7))))
            self.assertEqual(state.status, "connected")

    def test_a_rotated_log_is_read_when_the_current_one_is_short_and_a_missing_one_is_said(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            log = self.host(root, f"{stamp(23, 9, 5)} INFO gateway.run: Starting gateway")
            log.with_name("gateway.log.1").write_text(refused(23, 9) + "\n", encoding="utf-8")
            state = self.only(self.read(root, self.serving(epoch(23, 8))))
            self.assertEqual(state.status, "failed")
            log.unlink()
            log.with_name("gateway.log.1").unlink()
            bots = self.read(root, self.serving(epoch(23, 8)))
            self.assertEqual((bots["default"].log, bots[BOT].platforms), ("missing", ()))

    def test_a_huge_log_is_read_from_its_tail_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            filler = [f"{stamp(23, 9, 10)} INFO gateway.run: inbound message handled {n:06d}" for n in range(4000)]
            self.host(root, refused(23, 9), *filler)
            tail = 64 << 10
            self.assertGreater((root / "logs" / "gateway.log").stat().st_size, 2 * tail)
            self.assertEqual(self.read(root, self.serving(epoch(23, 8)), log_tail_bytes=tail)[BOT].platforms, (),
                             "a refusal before the tail is not read, and nothing is claimed in its place")
            self.host(root, *filler, connected(23, 9, 5), refused(23, 9, 20))
            state = self.only(self.read(root, self.serving(epoch(23, 8)), log_tail_bytes=tail))
            self.assertEqual((state.status, state.since), ("failed", iso_utc(epoch(23, 9, 20))))

    # ── nothing but the classified state leaves ────────────────────────────

    def test_no_log_line_token_webhook_or_id_reaches_the_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root,
                      f"{stamp(23, 9)} ERROR hermes_plugins.platforms__discord.adapter: [Discord] Failed to connect to "
                      f"Discord: LoginFailure: Improper token has been passed. {TOKEN} via {WEBHOOK} for "
                      f"guild {'4' * 18} owner demo@example.invalid",
                      "Traceback (most recent call last):",
                      '  File "/opt/hermes-agent/plugins/platforms/discord/adapter.py", line 1564, in connect',
                      f"{stamp(23, 9)} WARNING gateway.run: ✗ discord failed to connect (profile: {BOT})")
            record = Platform(f"{BOT}:discord", "fatal", f"token {TOKEN} rejected; webhook {WEBHOOK}; also "
                              f"{SLACK_HOOK} and key {API_KEY}", False, True, "discord_auth_error")
            records = self.serving(epoch(23, 8), record)
            found = bot_platforms(root, gateway_reader=lambda home: records.get(home.name, NO_RECORD))
            text = json.dumps([asdict(bot) for bot in found])
            for secret in (TOKEN, "w" * 40, "q" * 12, "s" * 24, API_KEY, "4" * 18, "demo@example.invalid", "Traceback",
                           "adapter.py",
                           "1564", "ERROR hermes_plugins", "gateway.run:"):
                self.assertNotIn(secret, text, secret)
            state = found[[bot.profile for bot in found].index(BOT)].platforms[0]
            self.assertEqual(state.reason_kind, REASON_TOKEN_REJECTED)
            self.assertIn("<redacted>", state.reason + state.guidance)

    def test_every_common_credential_shape_is_taken_out_and_plain_words_stay(self) -> None:
        secrets = {
            "Authorization: Bearer " + "ab12" * 8: "Authorization: Bearer <redacted>",
            "Bearer " + "Zx9" * 13: "Bearer <redacted>",
            "Basic " + "dXNlcjpwYXNzd29yZDEyMzQ1Ng==": "Basic <redacted>",
            "token=" + "a1" * 10 + ":" + "b2" * 10: "token=<redacted>",
            "key=" + "0123456789abcdef" * 2: "key=<redacted>",
            "code=" + "c3" * 15: "code=<redacted>",
            "api_key: " + "q8" * 10: "api_key: <redacted>",
            "password=hunter22": "password=<redacted>",
            "key=" + AWS_ACCESS_KEY_ID: "key=<redacted>",
            f"access key {AWS_ACCESS_KEY_ID} denied": "access key <redacted> denied",
            f"access key {AWS_TEMPORARY_ACCESS_KEY_ID} denied": "access key <redacted> denied",
            "token: " + "QWERTYUIOPASDFGHJKL1": "token: <redacted>",
            "secret " + AWS_SECRET_SAMPLE: "secret <redacted>",
            "blob " + "2Xz++nd6e08VJBq/" + "Aa1" * 8 + "==": "blob <redacted>",
            "twilio " + "f" * 16 + "0" * 16: "twilio <redacted>",
        }
        for raw, want in secrets.items():
            with self.subTest(raw=raw[:24]):
                self.assertEqual(bounded_reason(raw, 600), want)
        for words in ("discord_websocket_health_stale_reconnect_timeout_exceeded",
                      "Hermes is requesting: - Message Content Intent - Server Members Intent (required for username "
                      "allowlists and/or DISCORD_ALLOWED_ROLES)",
                      "Enable it on the Bot page, Privileged Gateway Intents", "error code: 4014",
                      "403 Forbidden (error code: 50001): Missing Access", "missing key: DISCORD_BOT_TOKEN",
                      "no token: DISCORD_BOT_TOKEN is unset", "Close code: 4014"):
            with self.subTest(words=words[:24]):
                self.assertEqual(bounded_reason(words, 600), words)

    def test_a_path_with_a_digit_in_a_long_run_goes_as_the_price_of_base64(self) -> None:
        self.assertEqual(bounded_reason("see https://discord.com/developers/applications"),
                         "see https://discord.com/developers/applications")  # Hermes' own links: no digit, kept
        self.assertEqual(bounded_reason("at /home/user2024/projects/demo-bot/logs"), "at <redacted>")

    def test_escapes_control_and_bidi_characters_never_leave_the_producer(self) -> None:
        raw = "\x1b[31mred\x1b[0m \x1b]8;;http://evil.invalid\x07click\x1b]8;;\x07 \u202eevil\u202c \x9b2J nul\x00bel\x07 end"
        self.assertEqual(bounded_reason(raw), "red click evil nulbel end")
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, f"{stamp(23, 9)} ERROR gateway.run: ✗ discord error (profile: {BOT}): {raw}")
            state = self.only(self.read(root, self.serving(epoch(23, 8))))
            report = gateway_health(root, environ={}, gateway_reader=lambda home: self.serving(epoch(23, 8)).get(
                home.name, NO_RECORD), list_processes=lambda: formats_listing(), process_start=lambda pid: None)
        for text in (state.reason, state.fix, *(_adapter_line(adapter) for adapter in report.adapters)):
            self.assertFalse([ch for ch in text if ch in "\x1b\x9b\x00\x07\u202e\u202c"], text)

    def test_a_board_that_reads_again_does_not_parse_an_unchanged_log_again(self) -> None:
        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            log = self.host(root, refused(23, 9))
            cache = LogCache()
            calls = []
            real = formats._tail

            def counted(path, limit):
                calls.append(path)
                return real(path, limit)

            records = self.serving(epoch(23, 8))
            with mock.patch.object(formats, "_tail", counted):
                first = self.read(root, records, log_reader=cache.read)
                reads = len(calls)
                second = self.read(root, records, log_reader=cache.read)
                self.assertEqual(len(calls), reads, "an unchanged log costs a stat")
                self.assertEqual(first, second)
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(connected(23, 9, 30) + "\n")
                self.assertEqual(self.only(self.read(root, records, log_reader=cache.read)).status, "connected")
                self.assertGreater(len(calls), reads)

    @unittest.skipUnless(os.name == "posix", "the gateway record's liveness probe is POSIX-only")
    def test_every_leak_the_review_found_stays_out_of_the_command_output(self) -> None:
        from omh.commands.main import main
        from omh.tui.bot_board import process_facts

        leaks = {
            "bearer": "Authorization: Bearer " + "ab12" * 8,
            "bot": "Bot " + "Q1w2E3r4" * 3,
            "token": "token=" + "a1" * 10 + ":" + "b2" * 10,
            "key": "key=" + "0123456789abcdef" * 2,
            "code": "code=" + "c3" * 15,
            "secret": "secret=" + "s3cr3t" * 3,
            "password": "password=hunter22",
            "hex": "f" * 16 + "0" * 16,
            "base64": "2Xz++nd6e08VJBq/" + "Aa1" * 8 + "==",
            "ansi": "\x1b[31mred\x1b[0m",
            "osc8": "\x1b]8;;http://evil.invalid\x07click\x1b]8;;\x07",
            "bidi": "\u202eevil\u202c",
        }
        with TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"HOME": tmp, "USERPROFILE": tmp}):
            root = self.home(tmp)
            pid = os.getpid()
            (root / "gateway_state.json").write_text(json.dumps({
                "pid": pid, "start_time": process_facts(pid)[0], "hermes_home": str(root), "gateway_state": "running",
                "served_profiles": ["default", BOT]}), encoding="utf-8")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.host(root, f"{now},000 ERROR gateway.run: ✗ discord error (profile: {BOT}): RuntimeError: "
                      + " ".join(leaks.values()))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(root), "hermes",
                                       "platforms"]), 0)
        printed = out.getvalue()
        bots = {bot["profile"]: bot for bot in json.loads(printed)["bots"]}
        state = bots[BOT]["platforms"][0]
        self.assertEqual((state["status"], state["reason_kind"]), ("failed", "unrecognized"))
        for name, leak in leaks.items():
            secret = leak if name in ("ansi", "osc8", "bidi", "hex", "base64") else leak.split("=", 1)[-1].split(" ")[-1]
            with self.subTest(leak=name):
                self.assertNotIn(secret, printed)
                self.assertNotIn(json.dumps(secret)[1:-1], printed)
        for ch in ("\x1b", "\u202e", "\x07"):
            self.assertNotIn(json.dumps(ch)[1:-1], printed)
        self.assertIn("~/.hermes/logs/gateway.log", state["fix"])
        self.assertNotIn(tmp, printed.replace(json.dumps(str(root))[1:-1], ""), "no absolute path with a home folder")

    def test_the_command_prints_the_schema_and_every_bot(self) -> None:
        from omh.commands.main import main

        with TemporaryDirectory() as tmp:
            root = self.home(tmp)
            self.host(root, refused(23, 9))
            payload = bot_platforms_payload(root)
            self.assertEqual(payload["schema_version"], BOT_PLATFORMS_SCHEMA)
            out = io.StringIO()
            with redirect_stdout(out):
                status = main(["--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(root), "hermes", "platforms"])
            self.assertEqual(status, 0)
            printed = json.loads(out.getvalue())
            self.assertEqual(printed["schema_version"], "omh_bot_platforms/v1")
            bots = {bot["profile"]: bot for bot in printed["bots"]}
            self.assertEqual(set(bots), {"default", BOT})
            # No gateway record runs here, so the line is said as not served: unknown, never failed.
            self.assertEqual([(p["platform"], p["status"], p["unknown_why"]) for p in bots[BOT]["platforms"]],
                             [("discord", "unknown", "not_served")])
            self.assertFalse((Path(tmp) / ".omh").exists(), "the command writes nothing, not even OMH's own home")


if __name__ == "__main__":
    unittest.main()
