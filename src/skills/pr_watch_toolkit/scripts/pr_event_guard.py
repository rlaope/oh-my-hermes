#!/usr/bin/env python3
"""Own-PR trigger guard and burst cap for a Hermes GitHub webhook route.

Hermes runs this as a webhook route's `--script` filter, with no arguments,
from `<profile>/scripts/`. The route payload arrives as JSON on stdin. The
guard decides, from the payload and its config alone, whether the event may
start a run:

- Own-PR guard: an event sent by one of the bot's own logins (or a workflow
  run it started), on a pull request one of them authored, on a head branch
  under one of the bot's branch prefixes, or a comment or review carrying the
  bot's marker, is dropped.
- Burst cap: at most `max_events` accepted events per `window_minutes` (default
  5 per 15 minutes); a further event inside the window is dropped, not queued.

It fails closed: an event it cannot read as a GitHub event (no `sender.login`,
for example a form-encoded delivery Hermes could not parse as JSON), a config
error, a window file it cannot lock, read or write, and any other error all
drop the event. A form-encoded delivery whose `payload` field holds the JSON
event is unwrapped first.

A dropped event prints `[SILENT]` (Hermes ignores the webhook) and one
`pr-event-guard: drop reason=<reason>` line on stderr. An accepted event prints
one `pr-event-guard: pass ...` line, which Hermes attaches to the payload as
`script_output`; payload text is never printed.

Installed as `<profile>/scripts/pr_event_guard_<route>.py`; the file name names
the route, whose config is `<profile>/pr_event_guard/<route>.json` and whose
window lives in `<profile>/pr_event_guard/<route>.state.json`. `--config PATH`
selects a config directly (manual runs, tests).

No network, no forge call, no process: stdlib only, so it runs on Hermes' own
interpreter. Every payload field is data: it is read through typed getters,
compared for equality or prefix, and never printed, executed or interpolated.

Exit codes: 0 decided (pass, or `[SILENT]` drop), 3 config error, 4 stdin is
not one JSON object, 5 the window state could not be locked, read or written.
A nonzero exit also makes Hermes ignore the webhook, so every failure drops
the event.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

EXIT_OK = 0
EXIT_CONFIG = 3
EXIT_PAYLOAD = 4
EXIT_LOCK = 5

SCRIPT_PREFIX = "pr_event_guard_"
SILENT = "[SILENT]"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}(\[bot\])?$")
# A prefix ends at a separator, so `bot/` never matches a person's `bottom-fix`.
PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,98}[/-]$")
DEFAULT_MAX_EVENTS = 5
DEFAULT_WINDOW_MINUTES = 15
MAX_STDIN = 32 * 1024 * 1024
MARKER_MIN, MARKER_MAX = 8, 200
LOCK_WAIT_S = 5.0
LOCK_STALE_S = 60.0


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------- config


def load_config(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config not found: {path}") from None
    except (OSError, ValueError) as exc:
        raise ConfigError(f"config unreadable: {path}: {exc.__class__.__name__}") from None
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ConfigError("name must match [a-z0-9][a-z0-9_-]{0,63}")
    logins = raw.get("own_logins") or []
    if not isinstance(logins, list) or not all(isinstance(v, str) and LOGIN_RE.match(v) for v in logins):
        raise ConfigError("own_logins must be a list of GitHub logins")
    prefixes = raw.get("own_branch_prefixes") or []
    if not isinstance(prefixes, list) or not all(isinstance(v, str) and PREFIX_RE.match(v) for v in prefixes):
        raise ConfigError("own_branch_prefixes must be a list of branch prefixes ending in / or -, such as bot/")
    if not logins and not prefixes:
        raise ConfigError("name the bot's own_logins or own_branch_prefixes; without either no event is its own")
    marker = raw.get("own_comment_marker")
    if marker is not None and (not isinstance(marker, str) or not MARKER_MIN <= len(marker.strip()) <= MARKER_MAX):
        raise ConfigError(f"own_comment_marker must be {MARKER_MIN} to {MARKER_MAX} characters")
    max_events = raw.get("max_events", DEFAULT_MAX_EVENTS)
    if not isinstance(max_events, int) or isinstance(max_events, bool) or not 1 <= max_events <= 100:
        raise ConfigError("max_events must be an integer from 1 to 100")
    window = raw.get("window_minutes", DEFAULT_WINDOW_MINUTES)
    if not isinstance(window, int) or isinstance(window, bool) or not 1 <= window <= 1440:
        raise ConfigError("window_minutes must be an integer from 1 to 1440")
    return {
        "name": name,
        "own_logins": frozenset(v.lower() for v in logins),
        "own_branch_prefixes": tuple(prefixes),
        "own_comment_marker": marker.strip() if isinstance(marker, str) else None,
        "max_events": max_events,
        "window_seconds": window * 60,
        "window_minutes": window,
    }


def resolve_config(arg: str | None) -> tuple[Path, str | None]:
    """(config path, route name from the script file or None)."""
    if arg:
        return Path(arg), None
    script = Path(sys.argv[0])
    env_home = os.environ.get("HERMES_HOME")
    home = Path(env_home) if env_home else script.resolve().parent.parent
    stem = script.stem
    if not stem.startswith(SCRIPT_PREFIX) or len(stem) == len(SCRIPT_PREFIX):
        raise ConfigError(f"install this file as scripts/{SCRIPT_PREFIX}<route>.py or pass --config")
    name = stem[len(SCRIPT_PREFIX):]
    return home / "pr_event_guard" / f"{name}.json", name


# ---------------------------------------------------------------- payload


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _login(value: object) -> str:
    return _text(_dict(value).get("login")).lower()


def _branches(payload: dict) -> list[str]:
    """Every head branch the payload names for the event's pull request or check."""
    found = [_text(_dict(_dict(payload.get("pull_request")).get("head")).get("ref"))]
    for key in ("check_run", "check_suite", "workflow_run"):
        block = _dict(payload.get(key))
        found.append(_text(block.get("head_branch")))
        found.append(_text(_dict(block.get("check_suite")).get("head_branch")))
        for pr in _list(block.get("pull_requests")):
            found.append(_text(_dict(_dict(pr).get("head")).get("ref")))
    ref = _text(payload.get("ref"))
    if ref.startswith("refs/heads/"):
        found.append(ref[len("refs/heads/"):])
    return [branch for branch in found if branch]


def _actors(payload: dict) -> list[str]:
    """Who caused the event: its sender, and for a workflow run who started it."""
    run = _dict(payload.get("workflow_run"))
    found = [_login(payload.get("sender")), _login(run.get("actor")), _login(run.get("triggering_actor"))]
    return [login for login in found if login]


def _authors(payload: dict) -> list[str]:
    """The pull request's (or the commented issue's) author logins."""
    found = [_login(_dict(payload.get("pull_request")).get("user")), _login(_dict(payload.get("issue")).get("user"))]
    return [login for login in found if login]


def _bodies(payload: dict) -> list[str]:
    return [_text(_dict(payload.get(key)).get("body")) for key in ("comment", "review")]


def own_reason(payload: dict, cfg: dict) -> str | None:
    """Why this event is the bot's own, or None when it is not."""
    logins = cfg["own_logins"]
    if logins:
        if any(actor in logins for actor in _actors(payload)):
            return "own_sender"
        if any(author in logins for author in _authors(payload)):
            return "own_pr_author"
    for branch in _branches(payload):
        if any(branch.startswith(prefix) for prefix in cfg["own_branch_prefixes"]):
            return "own_branch"
    marker = cfg["own_comment_marker"]
    if marker and any(marker in body for body in _bodies(payload)):
        return "own_marker"
    return None


def _parse_object(raw: bytes | str) -> dict | None:
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def unwrap(payload: dict) -> dict | None:
    """A form-encoded delivery reaches the script as {"payload": "<the JSON event>"}; read the event inside."""
    inner = payload.get("payload")
    if "sender" in payload or not isinstance(inner, str):
        return payload
    return _parse_object(inner)


# ---------------------------------------------------------------- burst window


def _window_now(accepted: object, now: float, window_seconds: int) -> list[int]:
    """Accepted stamps still inside the window. A stamp from the future (the clock moved back) counts as now."""
    kept = []
    for stamp in _list(accepted):
        if isinstance(stamp, int) and not isinstance(stamp, bool) and stamp > now - window_seconds:
            kept.append(min(stamp, int(now)))
    return sorted(kept)


def _take_lock(lock: Path) -> bool:
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
            continue
        os.close(fd)
        return True


def _read_window(state_path: Path) -> list | None:
    """The stored stamps; [] when there is no file yet, None when a file is there but unreadable."""
    try:
        raw = state_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    state = _parse_object(raw)
    accepted = _dict(state).get("accepted")
    return accepted if state is not None and isinstance(accepted, list) else None


def _write_window(state_path: Path, accepted: list[int]) -> None:
    tmp = state_path.with_name(state_path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"accepted": accepted}) + "\n")
    os.replace(tmp, state_path)


def admit(state_path: Path, cfg: dict, now: float) -> tuple[bool, int]:
    """Record the event when the window has room. Returns (admitted, accepted count in the window).

    An unreadable window file is read as a full window (and rewritten as one), so a damaged file
    drops events for one window instead of opening the cap.
    """
    lock = state_path.with_name(state_path.name + ".lock")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if not _take_lock(lock):
        raise TimeoutError("window state lock busy")
    try:
        stored = _read_window(state_path)
        if stored is None:
            accepted = [int(now)] * cfg["max_events"]
            _write_window(state_path, accepted)
            return False, len(accepted)
        accepted = _window_now(stored, now, cfg["window_seconds"])
        if len(accepted) >= cfg["max_events"]:
            return False, len(accepted)
        accepted.append(int(now))
        _write_window(state_path, accepted)
        return True, len(accepted)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- main


def read_payload(stream) -> dict | None:
    raw = stream.read(MAX_STDIN + 1)
    if len(raw) > MAX_STDIN:
        return None
    return _parse_object(raw)


def drop(reason: str) -> int:
    print(SILENT)
    print(f"pr-event-guard: drop reason={reason}", file=sys.stderr)
    return EXIT_OK


def run(argv: list[str], stdin=None, now: float | None = None) -> int:
    parser = argparse.ArgumentParser(description="Own-PR guard and burst cap for a Hermes GitHub webhook route.")
    parser.add_argument("--config", help="guard config JSON (default: from this file's name)")
    args = parser.parse_args(argv)
    try:
        config_path, expected = resolve_config(args.config)
        cfg = load_config(config_path)
        if expected is not None and cfg["name"] != expected:
            raise ConfigError(f"config name {cfg['name']!r} does not match the script's route {expected!r}")
    except ConfigError as exc:
        print(f"pr-event-guard: error reason=config detail={exc}", file=sys.stderr)
        return EXIT_CONFIG
    payload = read_payload(stdin if stdin is not None else sys.stdin.buffer)
    payload = unwrap(payload) if payload is not None else None
    if payload is None:
        print("pr-event-guard: error reason=payload detail=stdin is not one JSON object", file=sys.stderr)
        return EXIT_PAYLOAD
    if not _login(payload.get("sender")):
        return drop("unrecognized_payload")
    reason = own_reason(payload, cfg)
    if reason is not None:
        return drop(reason)
    state_path = config_path.with_name(config_path.stem + ".state.json")
    try:
        admitted, count = admit(state_path, cfg, time.time() if now is None else now)
    except (OSError, TimeoutError) as exc:
        print(f"pr-event-guard: error reason=state detail={exc.__class__.__name__}", file=sys.stderr)
        return EXIT_LOCK
    if not admitted:
        return drop(f"burst_cap window_count={count} max_events={cfg['max_events']} "
                    f"window_minutes={cfg['window_minutes']}")
    print(f"pr-event-guard: pass window_count={count} max_events={cfg['max_events']} "
          f"window_minutes={cfg['window_minutes']}")
    return EXIT_OK


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
