#!/usr/bin/env python3
"""Gmail and Google Calendar monitor for a Hermes cron monitor job.

Hermes runs this as a cron job's `--monitor-script`, with no arguments, from
`<profile>/scripts/`, before the agent on every tick. Hermes hashes the exact
stdout bytes: unchanged output suppresses the agent run (no model call),
changed output wakes the agent with a diff. So the output holds only ids and
event start times, sorted, never a subject, a sender, a snippet, an event title
or a fetch time:

    monitor: gmail watch=<name>
    matched=2
    message 18c2f0a1b2c3d4e5
    message 18c2f0a1b2c3d4e6

    monitor: calendar watch=<name>
    event 3k2j1h0g9f8e7d6c start=2026-11-24T10:00:00+09:00

Gmail prints the ids of the newest messages that match the search, so a new
matching message changes it, and so does a message leaving the match (read,
when the search says `is:unread`; archived, when it says `in:inbox`).

Calendar prints every timed event that starts after now and within
`lead_minutes`, plus the event(s) with the latest start already passed, looking
back 24 hours (`event none` when there is none). An event entering the lead
window adds its line, so two events entering in one tick, or one added ahead
of an event already shown, each wake the agent; when an event starts it
replaces the earlier started one, one more change the prompt answers with
[SILENT]. All-day and cancelled events are left out.

It holds no credential and reads none. It runs Hermes' own google-workspace
skill CLI, which signs in with the profile's Google sign-in
(`<profile>/google_token.json`, set up by that skill) and refreshes it itself:
one fixed argv per tick, `<python> <profile>/skills/productivity/
google-workspace/scripts/google_api.py gmail search --max <n> -- <query>` or
`... calendar list --start <t> --end <t> --max 100 --calendar <id>`, on this
interpreter, no shell, stdin closed, a 90 s timeout, output capped. Both are
reads. This script only checks that the token file exists; it never opens it,
and writes nothing itself (its only output is stdout and stderr); the skill's
CLI rewrites `google_token.json` when it refreshes the sign-in, as it does for
the agent. A job that sets `--interpreter` runs that CLI on the other Python,
which may lack the Google libraries; leave it unset.

Failure is never a change, and never silent:
- No google-workspace skill, no Google sign-in, a sign-in Google no longer
  accepts, or a config error prints one fixed line, `error reason=<reason>`,
  and exits 0. Hermes sees that line change once, wakes the agent once to
  report it, and stays quiet while it holds.
- The CLI failing any other way, timing out, or printing something that is not
  the JSON it documents prints nothing on stdout and one `unreachable
  reason=<reason>` line on stderr, and exits 1. Hermes treats that as a failed
  monitor source: no change, no agent run, the stored hash kept. It alerts the
  job's failure target on the first failed tick and holds back repeats of the
  same failure for `cron.failure_repeat_alert_hours` (6 by default); a tick
  that succeeds closes the incident.

Installed as `<profile>/scripts/google_watch_<watch>.py`; the file name names
the watch, whose config is `<profile>/monitors/<watch>.json`. `--config PATH`
selects a config directly (manual runs, tests). Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path

EXIT_OK = 0
EXIT_UNREACHABLE = 1

SCRIPT_PREFIX = "google_watch_"
CONFIG_DIR = "monitors"
KINDS = ("gmail", "calendar")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
GMAIL_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,1024}$")
CALENDAR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%+@-]{0,199}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
SKILL_CLI = Path("skills/productivity/google-workspace/scripts/google_api.py")
TOKEN_FILE = "google_token.json"
TIMEOUT_S = 90
MAX_OUTPUT = 4 * 1024 * 1024
LOOKBACK = dt.timedelta(hours=24)
CALENDAR_MAX = 100
# What google_api.py prints on stderr when the profile's Google sign-in no
# longer works, as opposed to a network or API failure.
SIGN_IN_MARKERS = ("Not authenticated", "Token is invalid", "invalid_grant", "Re-run setup")


class ConfigError(Exception):
    pass


class Persistent(Exception):
    """A failure that holds until a person fixes it: one fixed line, exit 0."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Transient(Exception):
    """A failure that may pass on its own: nothing on stdout, exit 1."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------- config


def _int(raw: dict, key: str, default: int, low: int, high: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ConfigError(f"{key} must be a whole number from {low} to {high}")
    return value


def load_config(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise ConfigError("config file not readable") from None
    except ValueError:
        raise ConfigError("config file is not JSON") from None
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ConfigError("name must match [a-z0-9][a-z0-9_-]{0,63}")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ConfigError("kind must be gmail or calendar")
    cfg: dict = {"name": name, "kind": kind}
    if kind == "gmail":
        query = raw.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 300 or CONTROL_RE.search(query):
            raise ConfigError("query must be one Gmail search of at most 300 characters")
        cfg["query"] = query.strip()
        cfg["limit"] = _int(raw, "limit", 10, 1, 50)
    else:
        calendar = raw.get("calendar", "primary")
        if not isinstance(calendar, str) or not CALENDAR_RE.fullmatch(calendar):
            raise ConfigError("calendar must be primary or a calendar id")
        cfg["calendar"] = calendar
        cfg["lead_minutes"] = _int(raw, "lead_minutes", 15, 1, 240)
    return cfg


def hermes_home(script: Path) -> Path:
    env_home = os.environ.get("HERMES_HOME", "").strip()
    return Path(env_home) if env_home else script.resolve().parent.parent


def resolve_config(arg: str | None) -> tuple[Path, str | None]:
    """(config path, watch name from the script's file name or None)."""
    if arg:
        return Path(arg), None
    script = Path(sys.argv[0])
    stem = script.stem
    if not stem.startswith(SCRIPT_PREFIX) or len(stem) == len(SCRIPT_PREFIX):
        raise ConfigError(f"install this file as scripts/{SCRIPT_PREFIX}<watch>.py or pass --config")
    name = stem[len(SCRIPT_PREFIX):]
    return hermes_home(script) / CONFIG_DIR / f"{name}.json", name


# ---------------------------------------------------------------- the skill CLI


def _utc(stamp: dt.datetime) -> str:
    return stamp.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def skill_argv(cli: Path, cfg: dict, now: dt.datetime) -> list[str]:
    if cfg["kind"] == "gmail":
        return [sys.executable, str(cli), "gmail", "search", "--max", str(cfg["limit"]), "--", cfg["query"]]
    end = now + dt.timedelta(minutes=cfg["lead_minutes"])
    return [sys.executable, str(cli), "calendar", "list", "--start", _utc(now - LOOKBACK), "--end", _utc(end),
            "--max", str(CALENDAR_MAX), "--calendar", cfg["calendar"]]


def run_skill(home: Path, cfg: dict, now: dt.datetime) -> list:
    cli = home / SKILL_CLI
    if not cli.is_file():
        raise Persistent("skill_missing")
    if not (home / TOKEN_FILE).is_file():
        raise Persistent("not_signed_in")
    try:
        done = subprocess.run(skill_argv(cli, cfg, now), stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=TIMEOUT_S, check=False, cwd=str(home))
    except subprocess.TimeoutExpired:
        raise Transient("cli_failed") from None  # one reason for a hang and a failure: one Hermes incident
    except OSError:
        raise Transient("cli_failed") from None
    if done.returncode != 0:
        stderr = done.stderr[:MAX_OUTPUT].decode("utf-8", errors="replace")
        if any(marker in stderr for marker in SIGN_IN_MARKERS):
            raise Persistent("sign_in_expired")
        raise Transient("cli_failed")
    if len(done.stdout) > MAX_OUTPUT:
        raise Transient("reply_too_large")
    try:
        data = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Transient("bad_response") from None
    if not isinstance(data, list):
        raise Transient("bad_response")
    return data


# ---------------------------------------------------------------- digests


def gmail_lines(messages: list) -> list[str]:
    ids = sorted({m["id"] for m in messages
                  if isinstance(m, dict) and isinstance(m.get("id"), str) and GMAIL_ID_RE.fullmatch(m["id"])})
    if messages and not ids:
        raise Transient("bad_response")  # a reply whose shape changed must not read as "no mail"
    return [f"matched={len(ids)}", *(f"message {message_id}" for message_id in ids)]


def strict_fromisoformat(text):
    # Python 3.14 reads T24:00:00 as the next midnight; 3.11-3.13 refuse it.
    # Only that reading moves the date past the one the text starts with, so
    # refusing it here makes every supported interpreter agree.
    parsed = datetime.fromisoformat(text)
    if parsed.time() == time(0) and not text.startswith(date_spellings(parsed.date())):
        raise ValueError("hour must be in 0..23")
    return parsed


def date_spellings(day):
    week_year, week, weekday = day.isocalendar()
    spellings = (f"{day.year:04d}-{day.month:02d}-{day.day:02d}", f"{day.year:04d}{day.month:02d}{day.day:02d}",
                 f"{week_year:04d}-W{week:02d}-{weekday}", f"{week_year:04d}W{week:02d}{weekday}")
    if weekday == 1:
        spellings += (f"{week_year:04d}-W{week:02d}", f"{week_year:04d}W{week:02d}")
    return spellings


def _start(value: object) -> dt.datetime | None:
    """A timed event's start with its offset; None for an all-day date or anything unreadable.

    Google Calendar sends a timed start as RFC 3339 with an offset or `Z`
    (`2026-11-24T10:00:00+09:00`, `2026-11-24T01:00:00Z`) and an all-day one as
    a date (`2026-11-24`). `Z` is rewritten to `+00:00` so Python 3.10 reads it,
    a time without an offset is unreadable (it names no instant), and hour 24 is
    refused on every Python (3.14 alone would read it as the next midnight).
    """
    if not isinstance(value, str) or "T" not in value or CONTROL_RE.search(value) or len(value) > 40:
        return None
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        stamp = strict_fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def calendar_lines(events: list, now: dt.datetime, lead_minutes: int) -> list[str]:
    """Every timed event starting in (now, now + lead], plus the latest one already started.

    An event entering the lead window adds its line; when it starts it becomes the latest
    started event and the one before it leaves, which is one more change the prompt answers
    with [SILENT]. Two events entering in one tick, or one added ahead of an event already
    shown, each get their own line.
    """
    horizon = now + dt.timedelta(minutes=lead_minutes)
    upcoming, started = [], []
    for event in events:
        if not isinstance(event, dict) or event.get("status") == "cancelled":
            continue
        event_id, raw_start = event.get("id"), event.get("start")
        start = _start(raw_start)
        if not (isinstance(event_id, str) and EVENT_ID_RE.fullmatch(event_id) and start is not None):
            continue
        if now < start <= horizon:
            upcoming.append((start, event_id, raw_start))
        elif now - LOOKBACK <= start <= now:
            started.append((start, event_id, raw_start))
    if started:
        latest = max(start for start, _id, _raw in started)
        upcoming.extend(item for item in started if item[0] == latest)
    if events and not upcoming and not any(isinstance(e, dict) and isinstance(e.get("id"), str)
                                           and EVENT_ID_RE.fullmatch(e["id"]) for e in events):
        raise Transient("bad_response")  # a reply whose shape changed must not read as "no event"
    if not upcoming:
        return ["event none"]
    return [f"event {event_id} start={raw}" for _start_at, event_id, raw in sorted(upcoming)]


# ---------------------------------------------------------------- main


def _emit(lines: list[str]) -> None:
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Gmail and Google Calendar monitor for a Hermes cron monitor job.")
    parser.add_argument("--config", help="watch config JSON (default: from this file's name)")
    parser.add_argument("--now", help=argparse.SUPPRESS)  # manual runs and tests: an ISO time with an offset
    args = parser.parse_args(argv)
    kind, name = "google", "?"
    try:
        config_path, expected = resolve_config(args.config)
        if expected is not None:
            name = expected
        cfg = load_config(config_path)
        kind = cfg["kind"]
        if expected is not None and cfg["name"] != expected:
            raise ConfigError("config name does not match the script's watch name")
        name = cfg["name"]
        now = _start(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
        if now is None:
            raise ConfigError("--now must be an ISO time with an offset")
    except ConfigError as exc:
        _emit([f"monitor: {kind} watch={name}", "error reason=config"])
        print(f"monitor: config error: {exc}", file=sys.stderr)
        return EXIT_OK
    header = f"monitor: {kind} watch={name}"
    try:
        data = run_skill(hermes_home(Path(sys.argv[0])), cfg, now)
        lines = gmail_lines(data) if kind == "gmail" else calendar_lines(data, now, cfg["lead_minutes"])
    except Persistent as exc:
        _emit([header, f"error reason={exc.reason}"])
        return EXIT_OK
    except Transient as exc:
        print(f"{header} unreachable reason={exc.reason}", file=sys.stderr)
        return EXIT_UNREACHABLE
    _emit([header, *lines])
    return EXIT_OK


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    sys.exit(run(sys.argv[1:]))
