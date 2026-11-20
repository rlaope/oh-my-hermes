"""Which OMH TUI sessions this OMH home has open, and how each one ended: what a reopen reads to come back by itself.

Every TUI that takes a stored session (launch, `/new`, `/resume`, the
picker) writes the session here as `live`, with its pid, this machine's boot
and the terminal it runs in (`terminal_key`); the session it moved away from
becomes `closed`. When the TUI exits, `end_state_for_exit` decides how:

* `closed`: the person left (`/exit`, Ctrl+D, a normal close, a relaunch for
  an update, Ctrl+C before the terminal went raw). Never reopened by itself.
* `dropped`: a terminal hang-up (SIGHUP), SIGTERM, SIGBREAK or an uncaught
  crash. A `live` entry whose process is gone (SIGKILL, power loss: its boot
  differs from this one, or its pid no longer runs) is swept to `dropped` by
  the next reader. A dropped session may be reopened once
  (`claim_resumable`, which marks it `resumed`).

Liveness that cannot be told counts as alive: a session that may still run
is never handed out again.

Kept in `<omh_home>/tui/live-sessions.json` (`omh_tui_live_sessions/v1`,
newest last, at most `MAX_ENTRIES`), written 0600 by temp file and rename
under `live-sessions.lock` (fcntl on POSIX, msvcrt on Windows), waited for at
most `LOCK_WAIT_SECONDS` and then given up. `resume-pending` beside it exists
exactly when some entry is `dropped`, so a shell can test for it without
Python. Every function is best effort: an unreadable, corrupt, oversized or
symlinked file reads as empty, and no OS or JSON failure reaches the caller.
Stdlib only; nothing is spawned, signalled or sent anywhere.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import errno
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time
from typing import Any, TypeVar

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]
try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None  # type: ignore[assignment]

LIVE_SESSIONS_FILE = "live-sessions.json"
PENDING_MARKER = "resume-pending"
LOCK_FILE = "live-sessions.lock"
LIVE_SESSIONS_SCHEMA = "omh_tui_live_sessions/v1"

LIVE = "live"
CLOSED = "closed"
DROPPED = "dropped"
RESUMED = "resumed"
STATES = (LIVE, CLOSED, DROPPED, RESUMED)
END_STATES = (CLOSED, DROPPED)

MAX_ENTRIES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_FIELD_CHARS = 4096
PRUNE_AFTER = timedelta(days=7)  # closed and resumed entries older than this are forgotten
LOCK_WAIT_SECONDS = 2.0
LOCK_POLL_SECONDS = 0.05
# Two boot identities this close (in seconds) are one boot: Windows' is computed from the clock and rounded, and
# macOS' moves with a clock correction. Two real boots are always further apart than this.
BOOT_TOLERANCE_SECONDS = 60

TERMINAL_KEY_ENV = (
    "OMHER_TERMINAL_LINK", "CMUX_SURFACE_ID", "HERDR_PANE_ID", "ITERM_SESSION_ID", "TERM_SESSION_ID",
    "KITTY_WINDOW_ID", "WEZTERM_PANE", "WT_SESSION", "OTTY_PANE_ID", "TMUX_PANE",
)
TERMINAL_KEY_MAX_CHARS = 200

_LINUX_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
_WINDOWS_STILL_ACTIVE = 259
_WINDOWS_INVALID_PARAMETER = 87
_WINDOWS_QUERY_LIMITED_INFORMATION = 0x1000

_T = TypeVar("_T")
# What a store read, write or probe can raise that is not a bug here: the file system, a malformed document
# (JSONDecodeError and UnicodeDecodeError are ValueErrors; deep nesting is a RecursionError), a ctypes call.
_BEST_EFFORT = (OSError, ValueError, RecursionError, TypeError)


def terminal_key(environ: Mapping[str, str]) -> str:
    """`NAME=value` for the first `TERMINAL_KEY_ENV` name `environ` sets to a printable, non-empty value of at most
    `TERMINAL_KEY_MAX_CHARS` characters; "" when none does. The terminal's own persistent id, only ever read."""
    for name in TERMINAL_KEY_ENV:
        value = environ.get(name)
        if isinstance(value, str) and value and len(value) <= TERMINAL_KEY_MAX_CHARS and value.isprintable():
            return f"{name}={value}"
    return ""


def end_state_for_exit(code: int | None, signalled: bool) -> str:
    """`dropped` for an exit the person did not choose (an exit signal, or `code` None: an uncaught crash);
    `closed` for every exit the TUI returned itself, whatever its code."""
    return DROPPED if signalled or code is None else CLOSED


def boot_identity() -> str:
    """This machine's current boot: Linux's boot id, macOS' `kern.boottime` seconds, Windows' boot time (now minus
    `GetTickCount64`, rounded to 10 s); "" where it cannot be read."""
    try:
        if sys.platform.startswith("linux"):
            return _LINUX_BOOT_ID.read_text(encoding="ascii").strip()[:MAX_FIELD_CHARS]
        if sys.platform == "darwin":
            return _darwin_boot_seconds()
        if sys.platform == "win32":
            return _windows_boot_seconds()
    except (_BEST_EFFORT + (AttributeError, ImportError)):
        return ""
    return ""


def _darwin_boot_seconds() -> str:
    import ctypes

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        sysctlbyname = libc.sysctlbyname
    except (OSError, AttributeError):
        return ""
    buffer = ctypes.create_string_buffer(16)  # struct timeval: tv_sec (8 bytes), tv_usec
    size = ctypes.c_size_t(16)
    if sysctlbyname(b"kern.boottime", buffer, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0 or size.value < 8:
        return ""
    seconds = int.from_bytes(buffer.raw[:8], sys.byteorder, signed=True)
    return str(seconds) if seconds > 0 else ""


def _windows_boot_seconds() -> str:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    booted = time.time() - kernel32.GetTickCount64() / 1000
    return str(int(round(booted / 10) * 10))


def pid_alive(pid: int) -> bool:
    """Whether process `pid` may still run. False only when the OS says it does not; anything else, another user's
    process included, is True. POSIX asks with signal 0 (nothing is delivered), Windows with `OpenProcess`."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return True
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # PermissionError (another user's process) or an answer that says nothing: alive
    return True


def _windows_pid_alive(pid: int) -> bool:
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(_WINDOWS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return getattr(ctypes, "get_last_error")() != _WINDOWS_INVALID_PARAMETER  # no such process; access denied is alive
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == _WINDOWS_STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except (_BEST_EFFORT + (AttributeError, ImportError)):
        return True


def _same_boot(recorded: str, current: str) -> bool:
    """Whether two boot identities name one boot; unknown on either side is the same (the pid decides then)."""
    if not recorded or not current or recorded == current:
        return True
    if recorded.isdigit() and current.isdigit():
        return abs(int(recorded) - int(current)) <= BOOT_TOLERANCE_SECONDS
    return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parsed(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _directory(omh_home: Path) -> Path:
    return Path(omh_home) / "tui"


def _real(path: str) -> str:
    return os.path.normcase(os.path.realpath(path)) if path else ""


def _text(value: object, limit: int = MAX_FIELD_CHARS) -> str | None:
    return value if isinstance(value, str) and len(value) <= limit and value.isprintable() else None


def _entry(value: object) -> dict[str, Any] | None:
    """A stored entry in the schema's shape, or None for anything else."""
    if not isinstance(value, dict):
        return None
    session_id = _text(value.get("session_id"), TERMINAL_KEY_MAX_CHARS)
    fields = {name: _text(value.get(name)) for name in ("hermes_home", "cwd", "terminal_key", "boot", "updated_at")}
    pid = value.get("pid")
    if (not session_id or any(field is None for field in fields.values()) or value.get("state") not in STATES
            or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0):
        return None
    return {"session_id": session_id, **fields, "state": value["state"], "pid": pid}


def _load(directory: Path) -> list[dict[str, Any]]:
    """The kept entries, oldest first, one per session id; [] for a missing, symlinked, oversized or corrupt file."""
    path = directory / LIVE_SESSIONS_FILE
    try:
        if path.is_symlink():
            return []
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return []
            raw = handle.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return []
        record = json.loads(raw.decode("utf-8"))
    except _BEST_EFFORT:
        return []
    if not isinstance(record, dict) or record.get("schema_version") != LIVE_SESSIONS_SCHEMA:
        return []
    sessions = record.get("sessions")
    if not isinstance(sessions, list):
        return []
    kept: dict[str, dict[str, Any]] = {}
    for value in sessions:
        entry = _entry(value)
        if entry is not None:
            kept.pop(entry["session_id"], None)  # the later one wins and keeps its place
            kept[entry["session_id"]] = entry
    return list(kept.values())


def _write_private(path: Path, data: bytes) -> None:
    """`data` at `path`, mode 0600, by a temp file in the same directory and a rename (a symlink there is replaced,
    never followed)."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(6)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _sync_marker(directory: Path, entries: list[dict[str, Any]]) -> None:
    marker = directory / PENDING_MARKER
    wanted = any(entry["state"] == DROPPED for entry in entries)
    if wanted and not marker.is_file():
        if marker.is_symlink():
            marker.unlink()
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
    elif not wanted and (marker.exists() or marker.is_symlink()):
        marker.unlink()


def _sweep(entries: list[dict[str, Any]], now: datetime) -> None:
    """`live` entries whose process is gone become `dropped`, stamped now (when they were found gone)."""
    boot = boot_identity()
    for entry in entries:
        if entry["state"] == LIVE and (not _same_boot(entry["boot"], boot) or not pid_alive(entry["pid"])):
            entry["state"], entry["updated_at"] = DROPPED, _stamp(now)


def _pruned(entries: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    def stale(entry: dict[str, Any]) -> bool:
        if entry["state"] not in (CLOSED, RESUMED):
            return False
        moment = _parsed(entry["updated_at"])
        return moment is None or now - moment > PRUNE_AFTER

    return [entry for entry in entries if not stale(entry)][-MAX_ENTRIES:]


@contextmanager
def _locked(directory: Path) -> Iterator[bool]:
    """Hold `LOCK_FILE` while the block runs; yields False (the block should do nothing) when it could not be
    taken within `LOCK_WAIT_SECONDS`, or on a platform with no file lock."""
    if fcntl is None and msvcrt is None:
        yield False
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(directory / LOCK_FILE, flags, 0o600)
    except OSError:
        yield False
        return
    held = False
    try:
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                held = True
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or time.monotonic() >= deadline:
                    break
                time.sleep(LOCK_POLL_SECONDS)
        yield held
    finally:
        try:
            if held and fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif held:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            pass
        os.close(descriptor)


def _update(
    omh_home: Path, change: Callable[[list[dict[str, Any]], datetime], _T], default: _T, *, create: bool = True,
) -> _T:
    """Under the lock: read, sweep, `change` the entries in place, prune, and write back what moved; `change`'s
    answer, or `default` when the lock or the store failed. Without `create`, a home with neither the store nor the
    marker answers `default` at once and gains no file."""
    try:
        directory = _directory(omh_home)
        if not create and not any(os.path.lexists(directory / name) for name in (LIVE_SESSIONS_FILE, PENDING_MARKER)):
            return default
        with _locked(directory) as held:
            if not held:
                return default
            entries = _load(directory)
            before = json.dumps(entries)
            now = _utc_now()
            _sweep(entries, now)
            answer = change(entries, now)
            entries[:] = _pruned(entries, now)
            if json.dumps(entries) != before:
                document = {"schema_version": LIVE_SESSIONS_SCHEMA, "sessions": entries}
                _write_private(directory / LIVE_SESSIONS_FILE, (json.dumps(document, indent=2) + "\n").encode("utf-8"))
            _sync_marker(directory, entries)
            return answer
    except _BEST_EFFORT:
        return default


def _move_last(entries: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    entries[:] = [*(kept for kept in entries if kept is not entry), entry]


def record_live(
    omh_home: Path, session_id: str, hermes_home: str, cwd: str, environ: Mapping[str, str], *, previous: str = "",
) -> None:
    """This process now runs `session_id` (in `hermes_home`, from `cwd`, in the terminal `environ` names); the
    `previous` session it moved away from, if this process held it, is `closed`."""
    if not _text(session_id, TERMINAL_KEY_MAX_CHARS) or not hermes_home:
        return
    entry = {
        "session_id": session_id, "hermes_home": os.path.abspath(hermes_home)[:MAX_FIELD_CHARS],
        "cwd": os.path.abspath(cwd)[:MAX_FIELD_CHARS] if cwd else "", "terminal_key": terminal_key(environ),
        "state": LIVE, "pid": os.getpid(), "boot": boot_identity(), "updated_at": "",
    }
    if _entry({**entry, "updated_at": "x"}) is None:
        return  # a path that cannot be stored (a control character in it)

    def change(entries: list[dict[str, Any]], now: datetime) -> None:
        stamp = _stamp(now)
        for kept in list(entries):
            if previous and previous != session_id and kept["session_id"] == previous and _ours_live(kept):
                kept["state"], kept["updated_at"] = CLOSED, stamp
                _move_last(entries, kept)
        entries[:] = [kept for kept in entries if kept["session_id"] != session_id]
        entries.append({**entry, "updated_at": stamp})

    _update(omh_home, change, None)


def _ours_live(entry: Mapping[str, Any]) -> bool:
    return entry["state"] == LIVE and entry["pid"] == os.getpid()


def record_end(omh_home: Path, session_id: str, state: str) -> None:
    """`session_id`, which this process ran, ended as `state` (`closed` or `dropped`). An entry another process
    holds now, or one no longer `live`, is left as it is."""
    if not session_id or state not in END_STATES:
        return

    def change(entries: list[dict[str, Any]], now: datetime) -> None:
        for kept in entries:
            if kept["session_id"] == session_id and _ours_live(kept):
                kept["state"], kept["updated_at"] = state, _stamp(now)
                _move_last(entries, kept)
                return

    _update(omh_home, change, None, create=False)


def claim_resumable(
    omh_home: Path, *, hermes_homes: Collection[str], cwd: str, environ: Mapping[str, str],
    max_age_hours: float = 72,
) -> dict[str, Any] | None:
    """The dropped session a reopen in this terminal (else this directory) should run, marked `resumed` so no other
    reopen takes it too; a copy of its entry, or None.

    Candidates are `dropped`, live in one of `hermes_homes` and younger than `max_age_hours`. The newest whose
    terminal key is this terminal's wins; else, outside omher (`TERM_PROGRAM=omher`, whose terminals always carry
    their own key), the newest from the same directory.
    """
    homes = {_real(home) for home in hermes_homes if home}
    key = terminal_key(environ)
    here = _real(cwd)
    allow_cwd = environ.get("TERM_PROGRAM") != "omher"

    def change(entries: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
        oldest = now - timedelta(hours=max_age_hours)

        def candidate(entry: dict[str, Any]) -> bool:
            moment = _parsed(entry["updated_at"])
            # One entry per session id: a dropped session another TUI has taken again is `live`, never a candidate.
            return (entry["state"] == DROPPED and moment is not None and moment >= oldest
                    and _real(entry["hermes_home"]) in homes)

        candidates = [entry for entry in reversed(entries) if candidate(entry)]
        chosen = next((entry for entry in candidates if key and entry["terminal_key"] == key), None)
        if chosen is None and allow_cwd and here:
            chosen = next((entry for entry in candidates if entry["cwd"] and _real(entry["cwd"]) == here), None)
        if chosen is None:
            return None
        chosen["state"], chosen["updated_at"] = RESUMED, _stamp(now)
        _move_last(entries, chosen)
        return dict(chosen)

    return _update(omh_home, change, None, create=False)


def pending(omh_home: Path) -> bool:
    """Whether some session of this home is `dropped` (after sweeping `live` ones whose process is gone); the
    `PENDING_MARKER` file is brought in line with the answer."""
    return _update(omh_home, lambda entries, _now: any(entry["state"] == DROPPED for entry in entries), False,
                   create=False)
