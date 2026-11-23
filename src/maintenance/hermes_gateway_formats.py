"""Readers for the Hermes-side files `omh doctor`'s gateway health section parses, one per format.

Each reader owns one shape Hermes writes and nothing else, so a Hermes
format change fails here, loudly, as "unrecognized" rather than as a wrong
report further up:

- the build stamp, ``<install>/install-stamp.json`` (``builtAt``, ``commit``);
- Hermes' own pending fleet restart: the host obligation record
  (``hermes_cli/update_host_obligation.py``: ``host-update-restart-<key>.json``
  in the host state directory, or the older unkeyed ``host-update-restart.json``,
  or a home's ``fleet_restart_pending`` marker; Hermes reads any of them being
  present, parseable or not, as a restart still owed) and the update receipt
  Hermes itself reads, ``<root>/logs/update_receipts/latest.json``
  (``hermes_cli/update_receipt.py``: ``gateway_restart`` and ``fleet``);
- the gateway log's messaging-adapter lines, ``<home>/logs/gateway.log``
  (``gateway/run_adapters.py``, ``run_adapters_recovery.py``, ``run_startup.py``
  and the Discord adapter's connect failure), one anchored pattern per shape.

Everything is a bounded read of a regular file; nothing here imports Hermes,
spawns, signals or writes. Log stamps are Python logging's ``asctime`` in the
local time of the writing process and are read in this process's local time,
as the other gateway readers do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
from collections.abc import Mapping

from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat

BUILD_STAMP_FILENAME = "install-stamp.json"
BUILD_STAMP_BYTES = 64 << 10
RECEIPT_BYTES = 1 << 20
RECEIPT_RELATIVE = Path("logs") / "update_receipts" / "latest.json"
HOST_OBLIGATION_NAME = "host-update-restart.json"  # Hermes' `HOST_OBLIGATION_NAME`
PROFILE_MARKER_NAME = "fleet_restart_pending"  # Hermes' `PROFILE_MARKER_NAME`
GATEWAY_LOG_RELATIVE = Path("logs") / "gateway.log"
# The newest adapter lines sit at the end; a busy host log gains about a megabyte a day.
GATEWAY_LOG_TAIL_BYTES = 1 << 20
LOG_LINE_CHARS = 4096  # a longer line is cut before it is matched: no shape below is near this long
REASON_CHARS = 200
# A `✗ … failed to connect` line takes the adapter's own reason only from a line logged this close before it.
REASON_WINDOW_SECONDS = 120.0
# A profile's re-serve (`Now serving profile`, `Re-scanned profile … after config/.env change`) is logged after the
# adapters it restarted connected or failed; its adapter lines logged this close before it are that attempt's, older
# ones are from before it (Hermes dropped their verdicts: `run_profile_reconcile._drop_stale_platform_verdicts`).
ATTEMPT_WINDOW_SECONDS = 120.0

STATUS_READ = "read"
STATUS_MISSING = "missing"
STATUS_UNREADABLE = "unreadable"
STATUS_UNRECOGNIZED = "unrecognized"

STATE_CONNECTED = "connected"
STATE_DEGRADED = "degraded"
STATE_FAILED = "failed"
STATE_FATAL = "fatal"
STATE_RETRYING = "retrying"  # Hermes waits to reconnect a served profile's adapter (`Secondary … reconnect retry`)
STATE_DISCONNECTED = "disconnected"  # the adapter was stopped (`✓ … disconnected (…s)`)
STATE_RESERVED = "reserved"  # no adapter state: the profile was served again (`[MULTIPLEX] …`); platform is ""
# Adapters that carry no messaging platform: Hermes' in-process `local` adapter connects and disconnects with every
# local session, and is no bot.
NON_MESSAGING_PLATFORMS = frozenset({"local"})
AMBIGUOUS_PROFILE = "?"  # a reason line while several profiles' reconnects for its platform were open

REASON_PRIVILEGED_INTENTS = "discord_privileged_intents"
REASON_TOKEN_REJECTED = "discord_token_rejected"
REASON_TRANSIENT = "transient"
REASON_UNRECOGNIZED = "unrecognized"
REASON_NONE = "none_logged"
# Fatal codes the Discord adapter marks retryable: Hermes reconnects on its own.
TRANSIENT_CODES = frozenset({"discord_websocket_health_stale", "discord_connect_timeout", "discord_gateway_task_exited"})


@dataclass(frozen=True)
class BuildStamp:
    status: str  # STATUS_READ, STATUS_MISSING or STATUS_UNRECOGNIZED
    path: str
    built_at: float | None = None
    commit: str = ""


@dataclass(frozen=True)
class FleetRestartState:
    """What Hermes' own files record about a fleet restart an update still owes."""

    obligation: str  # the obligation record or marker found, "" when none is
    receipt_status: str  # STATUS_READ, STATUS_MISSING or STATUS_UNRECOGNIZED
    receipt_path: str
    receipt_kind: str = ""  # "update" for an update's receipt, else what its `kind` names
    finished_at: str = ""
    restart_incomplete: bool = False
    phase_error: str = ""
    stale_fleet: int = 0  # rows of the receipt's fleet matrix it marks stale


@dataclass(frozen=True)
class AdapterEvent:
    """One messaging adapter's state as one gateway log line records it."""

    profile: str  # the profile the line names; "" for the home's own (primary) profile
    platform: str
    state: str  # one of the STATE_* names
    logged: str  # the line's own stamp, as Hermes wrote it
    epoch: float | None
    reason: str = ""  # Hermes' words, bounded and redacted; "" when the log gives none
    code: str = ""  # a fatal error's code
    candidates: tuple[str, ...] = ()  # for an AMBIGUOUS_PROFILE reason: the profiles whose reconnects were open


@dataclass(frozen=True)
class LogRead:
    path: str
    status: str  # STATUS_READ, STATUS_MISSING, STATUS_UNREADABLE or STATUS_UNRECOGNIZED (no line is Hermes')
    bytes_read: int = 0
    stamped_lines: int = 0
    events: tuple[AdapterEvent, ...] = ()


_STAMP = r"^(?P<stamp>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d{3} (?P<level>[A-Z]+) "
_RUN = _STAMP + r"gateway\.run: "
_PLATFORM = r"(?P<platform>[a-z][a-z0-9_]*)"
_PROFILE = r"\(profile: (?P<profile>[^()\s]+)\)"
_STAMPED = re.compile(_STAMP + r"\S+: ")
_CONNECTED_PROFILE = re.compile(_RUN + "✓ " + _PLATFORM + r" (?:re)?connected " + _PROFILE + "$")
_CONNECTED_PRIMARY = re.compile(_RUN + "✓ " + _PLATFORM + r" (?:connected|reconnected successfully)$")
_DEGRADED_PRIMARY = re.compile(
    _RUN + "(?:✓ " + _PLATFORM + r" connected \(degraded\)|⚠ (?P<platform2>[a-z][a-z0-9_]*) reconnected in degraded mode\b.*)$"
)
_FAILED_PROFILE = re.compile(_RUN + "✗ " + _PLATFORM + r" failed to connect " + _PROFILE + "$")
_FAILED_PRIMARY = re.compile(_RUN + "✗ " + _PLATFORM + r" failed to connect$")
_ERROR_PROFILE = re.compile(_RUN + "✗ " + _PLATFORM + r" error " + _PROFILE + r": (?P<reason>.+)$")
_ERROR_PRIMARY = re.compile(_RUN + "✗ " + _PLATFORM + r" error: (?P<reason>.+)$")
_FATAL_PROFILE = re.compile(
    _RUN + "Fatal " + _PLATFORM + r" adapter error for multiplexed profile (?P<profile>[^()\s]+) \((?P<code>[^()]*)\)$"
)
_FATAL_PRIMARY = re.compile(_RUN + "Fatal " + _PLATFORM + r" adapter error \((?P<code>[^()]*)\): (?P<reason>.+)$")
_DISCONNECTED = re.compile(_RUN + "✓ " + _PLATFORM + r" disconnected \([0-9.]+s\)(?: " + _PROFILE + ")?$")
# `gateway/run_adapters_recovery.py`: a served profile's adapter waits to reconnect, with no `✗` line.
_SECONDARY_RETRY = re.compile(_RUN + "Secondary " + _PLATFORM + r" reconnect retry in \d+s " + _PROFILE + "$")
# The adapter's own reason (`plugins/platforms/discord`): before the gateway's `✗ … failed to connect` at startup,
# and on its own after a served profile's `Secondary … reconnect retry`, which writes no `✗` line.
_ADAPTER_REASON = re.compile(
    _STAMP + r"hermes_plugins\.platforms__" + _PLATFORM + r"\.adapter: \[[^\]]+\] Failed to connect to [^:]+: (?P<reason>.+)$"
)
# `gateway/run_profile_reconcile.py`: a profile served again, after a config/.env change or when it was added.
_RESERVED = re.compile(
    _STAMP + r"gateway\.run_profile_reconcile: \[MULTIPLEX\] (?:Re-scanned profile '(?P<profile>[^'\s]+)' after "
    r"config/\.env change|Now serving profile '(?P<profile2>[^'\s]+)') \(\d+ adapter\(s\) connected[^()]*\)$"
)
# What any line `adapter_events` reads must hold: a cheap test before the patterns run.
_GATEWAY_MARKS = ("✓ ", "✗ ", "Fatal ", "Secondary ", "⚠ ")
# ANSI and OSC escape sequences (an OSC 8 link included), dropped from Hermes' text before anything else.
_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x9b[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
# What a reason text never keeps, replaced in this order: credentials first (tokens, a webhook's path, any long
# opaque run), then ids, addresses and queries.
_SCRUBS = (
    (re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{20,}"), "<redacted>"),  # Discord bot token
    (re.compile(r"xox[a-z]-[A-Za-z0-9-]{10,}"), "<redacted>"),  # Slack token
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), "<redacted>"),  # Telegram bot token
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "<redacted>"),  # an AWS access key id, with or without a label
    # A webhook address carries its credential in the path: everything after `webhooks/` (Discord) or `services/`
    # (Slack) goes.
    (re.compile(r"(https?://(?:[\w-]+\.)*(?:discord(?:app)?\.com/api(?:/v\d+)?/webhooks|hooks\.slack\.com/services)/)\S+"),
     r"\1<redacted>"),
    # A credential after its scheme (`Authorization: Bearer …`, `Basic …`, `Bot …` with a digit in it) or its label
    # (`token=`, `api_key:`, `password=`, an OAuth `code=` …): the label stays, the value goes.
    (re.compile(r"(?i)\b((?:authorization:\s*)?(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1<redacted>"),
    (re.compile(r"(?i)\b(bot\s+)(?=[A-Za-z0-9._~+/=-]*\d)[A-Za-z0-9._~+/=-]{16,}"), r"\1<redacted>"),
    # Not when what follows is an environment variable's name (`missing key: DISCORD_BOT_TOKEN`), and for `code` and
    # `key` only a value with a letter and a digit, or 16 characters: discord.py's `(error code: 50001)` stays. The
    # name test also keeps a secret made only of capitals and `_` with no digit; real keys of that shape are rare.
    (re.compile(r"(?i)\b(token|access_token|refresh_token|api[_-]?key|apikey|client_secret|secret|password|passwd|pwd)"
                r"(\s*[:=]\s*)(?-i:(?![A-Z][A-Z_]*(?![\w])))[^\s,;'\"&)]{6,}"), r"\1\2<redacted>"),
    (re.compile(r"(?i)\b(code|key)(\s*[:=]\s*)(?-i:(?![A-Z][A-Z_]*(?![\w])))"
                r"(?:(?=[^\s,;'\"&)]*[A-Za-z])(?=[^\s,;'\"&)]*\d)[^\s,;'\"&)]{6,}|[^\s,;'\"&)]{16,})"), r"\1\2<redacted>"),
    # Any other opaque run of 32 or more key characters holding both a letter and a digit: hex, base64 and the rest.
    # `/` is a base64 character, so a URL path or file path with a digit in a 32-character run goes too (Hermes' own
    # guidance links hold none); that is the price of never keeping a base64 secret's tail.
    (re.compile(r"(?<![\w+/=-])(?=[A-Za-z0-9+/=_-]*[0-9])(?=[A-Za-z0-9+/=_-]*[A-Za-z])[A-Za-z0-9+/=_-]{32,}"),
     "<redacted>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"(https?://[^\s?#]+)[?#]\S*"), r"\1?<redacted>"),  # a URL's query or fragment
    (re.compile(r"\b[UCWTGBDE](?=[A-Z0-9]*\d)[A-Z0-9]{8,}\b"), "<id>"),  # Slack team, user and channel ids
    (re.compile(r"\d{15,}"), "<id>"),  # Discord ids
)


def read_build_stamp(install_dir: Path) -> BuildStamp:
    """``builtAt`` (an ISO time) and ``commit`` from Hermes' build stamp; unrecognized without a readable ``builtAt``."""
    path = install_dir / BUILD_STAMP_FILENAME
    if not _regular_file(path):
        return BuildStamp(STATUS_MISSING, str(path))
    data = _bounded_json(path, BUILD_STAMP_BYTES)
    built_at = _iso_epoch(data.get("builtAt")) if data is not None else None
    if data is None or built_at is None:
        return BuildStamp(STATUS_UNRECOGNIZED, str(path))
    commit = data.get("commit")
    return BuildStamp(STATUS_READ, str(path), built_at, commit if isinstance(commit, str) else "")


def host_state_dir(environ: Mapping[str, str]) -> Path:
    """Hermes' host state directory (`update_restart_recovery._host_state_dir`), from the same environment."""
    override = environ.get("HERMES_GATEWAY_LOCK_DIR", "")
    if override:
        return Path(override)
    state_home = environ.get("XDG_STATE_HOME", "")
    if not os.path.isabs(state_home):
        state_home = os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(state_home) / "hermes" / "gateway-locks"


def host_obligation_paths(install_dir: Path, environ: Mapping[str, str]) -> list[Path]:
    """This install's keyed obligation record, then the older unkeyed one, as Hermes looks for them.

    The key is the first 16 hex digits of the sha256 of the install directory's
    resolved, case-normalized path (`update_host_obligation.host_obligation_path`).
    """
    try:
        install = os.path.normcase(str(install_dir.resolve()))
    except (OSError, RuntimeError):
        install = os.path.normcase(str(install_dir))
    key = hashlib.sha256(install.encode("utf-8")).hexdigest()[:16]
    directory = host_state_dir(environ)
    return [directory / f"{Path(HOST_OBLIGATION_NAME).stem}-{key}.json", directory / HOST_OBLIGATION_NAME]


def read_fleet_restart_state(root_home: Path, install_dir: Path, environ: Mapping[str, str]) -> FleetRestartState:
    """Hermes' pending-fleet-restart record and its latest update receipt's restart outcome.

    Only what the files say: Hermes' own verdict also probes the live fleet,
    which OMH does not, so this never claims Hermes would or would not warn.
    """
    candidates = [*host_obligation_paths(install_dir, environ), root_home / PROFILE_MARKER_NAME]
    obligation = next((str(path) for path in candidates if _exists_as_file(path)), "")
    receipt_path = root_home / RECEIPT_RELATIVE
    if not _regular_file(receipt_path):
        return FleetRestartState(obligation, STATUS_MISSING, str(receipt_path))
    receipt = _bounded_json(receipt_path, RECEIPT_BYTES)
    if receipt is None:
        return FleetRestartState(obligation, STATUS_UNRECOGNIZED, str(receipt_path))
    kind = receipt.get("kind")
    restart = receipt.get("gateway_restart")
    finished = receipt.get("finished_at")
    finished_text = finished if isinstance(finished, str) else ""
    if kind is not None or not isinstance(restart, dict):
        return FleetRestartState(
            obligation, STATUS_READ, str(receipt_path), str(kind) if isinstance(kind, str) else "other", finished_text
        )
    phase_error = restart.get("phase_error")
    fleet = receipt.get("fleet")
    stale = sum(1 for row in fleet if isinstance(row, dict) and row.get("state") == "stale") if isinstance(fleet, list) else 0
    return FleetRestartState(
        obligation, STATUS_READ, str(receipt_path), "update", finished_text,
        restart.get("incomplete") is True,
        bounded_reason(phase_error) if isinstance(phase_error, str) else "",
        stale,
    )


def read_gateway_log(log_path: Path, *, tail_bytes: int = GATEWAY_LOG_TAIL_BYTES) -> LogRead:
    """The adapter events in the tail of one gateway log, oldest first, with the rotated ``.1`` before it when short.

    The first line of a tail that starts mid-file is dropped (the read cut
    it), undecodable bytes are replaced, and every line is cut to
    `LOG_LINE_CHARS` before it is matched.
    """
    if not _regular_file(log_path):
        return LogRead(str(log_path), STATUS_MISSING)
    text, read = _tail(log_path, tail_bytes)
    if text is None:
        return LogRead(str(log_path), STATUS_UNREADABLE)
    rotated = log_path.with_name(log_path.name + ".1")
    if read < tail_bytes and _regular_file(rotated):
        older, older_read = _tail(rotated, tail_bytes - read)
        if older is not None:
            text, read = older + "\n" + text, read + older_read
    lines = [line[:LOG_LINE_CHARS] for line in text.splitlines()]
    stamped = sum(1 for line in lines if _STAMPED.match(line))
    if lines and not stamped:
        return LogRead(str(log_path), STATUS_UNRECOGNIZED, read)
    return LogRead(str(log_path), STATUS_READ, read, stamped, tuple(adapter_events(lines)))


class LogCache:
    """`read_gateway_log` for a caller that reads the same logs again and again (the TUI bot board): a log whose file
    and rotated `.1` keep the inode, size and modification time they had at the last read is not read again. It holds
    at most `limit` logs, the oldest dropped first."""

    def __init__(self, limit: int = 256) -> None:
        self._limit = limit
        self._held: dict[tuple[str, int], tuple[tuple[object, object], LogRead]] = {}

    def read(self, path: Path, tail_bytes: int = GATEWAY_LOG_TAIL_BYTES) -> LogRead:
        key = (str(path), tail_bytes)
        signature = (_file_signature(path), _file_signature(path.with_name(path.name + ".1")))
        held = self._held.get(key)
        if held is not None and signature[0] is not None and held[0] == signature:
            return held[1]
        log = read_gateway_log(path, tail_bytes=tail_bytes)
        self._held.pop(key, None)
        if len(self._held) >= self._limit:
            self._held.pop(next(iter(self._held)))
        self._held[key] = (signature, log)
        return log


def _file_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        st = path.stat()
    except (OSError, ValueError):
        return None
    return st.st_ino, st.st_size, st.st_mtime_ns


def adapter_events(lines: list[str]) -> list[AdapterEvent]:
    """Every adapter state line in `lines`, in file order.

    The Discord adapter logs why it failed (`[Discord] Failed to connect to
    Discord: …`) without naming the profile. That line is a failure in its own
    right: a served profile's reconnect (`Secondary discord reconnect retry …
    (profile: P)`) writes no `✗` line after it. It goes to the one profile
    whose reconnect for that platform is open (a `Fatal … multiplexed profile`
    or `Secondary … reconnect retry` line not yet followed by that profile's
    own connected, failed or stopped line); with none open, to the log's own
    profile (""); with more than one open, to `AMBIGUOUS_PROFILE` with those
    profiles as `candidates`, since the log cannot say whose it is. Such an
    event is dropped once every candidate has connected again after it.

    A `✗ … failed to connect (profile: Q)` within `REASON_WINDOW_SECONDS` after
    the reason takes it only when the reason went to Q or to no one; an
    unattributed reason event is then withdrawn, as it was Q's. A reason
    given to another profile's open reconnect stays there.

    A profile served again (`[MULTIPLEX] Now serving profile 'P'`, `… Re-scanned
    profile 'P' after config/.env change`) comes back as a `STATE_RESERVED`
    event for P with no platform, in its place in the file.
    """
    events: list[AdapterEvent | None] = []
    reconnecting: dict[str, list[str]] = {}  # platform -> profiles whose reconnect is open, oldest first
    pending: dict[str, tuple[str, float | None, int | None, str | None]] = {}  # platform -> (reason, epoch, index, owner)
    for line in lines:
        if "gateway.run" not in line and ".adapter: [" not in line:
            continue  # neither the gateway's nor an adapter's line: no pattern below can match it
        if (match := _RESERVED.match(line)) is not None:
            events.append(AdapterEvent(match["profile"] or match["profile2"], "", STATE_RESERVED, match["stamp"],
                                       _log_epoch(match["stamp"])))
            continue
        if ".adapter: [" in line and "Failed to connect" not in line:
            continue
        if ".adapter: [" not in line and not any(mark in line for mark in _GATEWAY_MARKS):
            continue
        if (match := _ADAPTER_REASON.match(line)) is not None:
            platform = match["platform"]
            reason, at = bounded_reason(match["reason"]), _log_epoch(match["stamp"])
            open_now = reconnecting.get(platform, [])
            owner = open_now[0] if len(open_now) == 1 else "" if not open_now else None
            index = len(events)
            events.append(AdapterEvent(
                AMBIGUOUS_PROFILE if owner is None else owner, platform, STATE_FAILED, match["stamp"], at, reason,
                candidates=tuple(open_now) if owner is None else (),
            ))
            pending[platform] = (reason, at, index, owner)
            continue
        event = parse_adapter_line(line)
        if event is None:
            continue
        open_now = reconnecting.setdefault(event.platform, [])
        if event.profile and event.state in {STATE_RETRYING, STATE_FATAL}:
            if event.profile not in open_now:
                open_now.append(event.profile)
        elif event.profile in open_now:
            open_now.remove(event.profile)
        if event.state == STATE_FAILED and not event.reason and event.platform in pending:
            reason, at, index, owner = pending[event.platform]
            close = at is not None and event.epoch is not None and 0 <= event.epoch - at <= REASON_WINDOW_SECONDS
            if close and owner in {None, "", event.profile}:
                del pending[event.platform]
                event = AdapterEvent(event.profile, event.platform, event.state, event.logged, event.epoch, reason)
                if index is not None and owner != event.profile:
                    events[index] = None
        events.append(event)
    kept = [event for event in events if event is not None]
    return [event for position, event in enumerate(kept) if not _reconnected_since(event, kept[position + 1:])]


def _reconnected_since(event: AdapterEvent, later: list[AdapterEvent]) -> bool:
    """Whether every candidate of an ambiguous reason connected again after it (never true for any other event)."""
    if event.profile != AMBIGUOUS_PROFILE:
        return False
    back = {other.profile for other in later
            if other.platform == event.platform and other.state in {STATE_CONNECTED, STATE_DEGRADED}}
    return all(candidate in back for candidate in event.candidates)


def parse_adapter_line(line: str) -> AdapterEvent | None:
    """One gateway log line as an adapter state, or None when it is not one of the shapes Hermes writes for that."""
    for pattern, state in (
        (_CONNECTED_PROFILE, STATE_CONNECTED),
        (_CONNECTED_PRIMARY, STATE_CONNECTED),
        (_FAILED_PROFILE, STATE_FAILED),
        (_FAILED_PRIMARY, STATE_FAILED),
        (_ERROR_PROFILE, STATE_FAILED),
        (_ERROR_PRIMARY, STATE_FAILED),
        (_FATAL_PROFILE, STATE_FATAL),
        (_FATAL_PRIMARY, STATE_FATAL),
        (_SECONDARY_RETRY, STATE_RETRYING),
        (_DISCONNECTED, STATE_DISCONNECTED),
    ):
        match = pattern.match(line)
        if match is None:
            continue
        if match["platform"] in NON_MESSAGING_PLATFORMS:
            return None
        groups = match.groupdict()
        return AdapterEvent(
            groups.get("profile") or "", match["platform"], state, match["stamp"], _log_epoch(match["stamp"]),
            bounded_reason(groups["reason"]) if groups.get("reason") else "", groups.get("code") or "",
        )
    match = _DEGRADED_PRIMARY.match(line)
    if match is not None:
        platform = match["platform"] or match["platform2"]
        return AdapterEvent("", platform, STATE_DEGRADED, match["stamp"], _log_epoch(match["stamp"]))
    return None


def classify_reason(event: AdapterEvent) -> str:
    """A failure's reason as one of the REASON_* names: what the fix depends on."""
    if event.platform == "discord" and (
        "requesting privileged intents" in event.reason or event.code == "discord_intents_required"
    ):
        return REASON_PRIVILEGED_INTENTS
    if event.platform == "discord" and ("Improper token has been passed" in event.reason or event.code == "discord_auth_error"):
        return REASON_TOKEN_REJECTED
    if event.code in TRANSIENT_CODES:
        return REASON_TRANSIENT
    if not event.reason and not event.code:
        return REASON_NONE
    return REASON_UNRECOGNIZED


def strip_controls(text: str) -> str:
    """`text` on one line with no escape sequence (ANSI colour, an OSC 8 link) and no control or format character (a
    bidi override, NUL, BEL): what every string a surface shows from Hermes' files goes through."""
    cleaned = " ".join(_ESCAPES.sub("", text).split())
    return "".join(ch for ch in cleaned if unicodedata.category(ch) not in ("Cc", "Cf"))


def bounded_reason(text: str, limit: int = REASON_CHARS) -> str:
    """Hermes' reason text on one line, at most `limit` characters (`REASON_CHARS` unless said): with no escape
    sequence or control or format character (ANSI colour, an OSC 8 link, a bidi override), and without Discord, Slack
    or Telegram bot tokens, a Discord or Slack webhook's credential path, a bearer or labelled secret, any other opaque
    run of 32 or more key characters, Discord and Slack ids, email addresses, or a URL's query (`_SCRUBS`)."""
    cleaned = strip_controls(text)
    for pattern, replacement in _SCRUBS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def iso_utc(epoch: float | None) -> str:
    if epoch is None:
        return ""
    try:
        return datetime.fromtimestamp(epoch, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return ""


def _log_epoch(stamp: str) -> float | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _iso_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = strict_fromisoformat(value.strip().replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except (OSError, ValueError):
        return False


def _exists_as_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _bounded_json(path: Path, limit: int) -> dict[str, object] | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            return None
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _tail(path: Path, limit: int) -> tuple[str | None, int]:
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            start = max(0, size - limit)
            handle.seek(start)
            raw = handle.read(limit)
    except OSError:
        return None, 0
    text = raw.decode("utf-8", errors="replace")
    if start > 0:
        text = text.partition("\n")[2]
    return text, len(raw)
