"""Which OMH TUI sessions this OMH home has open, and how each one ended: what a reopen reads to come back by itself.

Every TUI that takes a stored session (launch, `/new`, `/resume`, the
picker) joins the session's entry as one of its `owners` (its pid, this
machine's boot and the terminal it runs in, `terminal_key`); two windows may
hold one session. Moving away leaves the session it moved from. When the TUI
exits, `end_state_for_exit` decides how its owner leaves; the entry itself
ends only when its last owner leaves, and then as that owner left:

* `closed`: the person left (`/exit`, Ctrl+D, a normal close, a relaunch for
  an update, Ctrl+C before the terminal went raw). Never reopened by itself.
* `dropped`: a terminal hang-up (SIGHUP), SIGTERM, SIGBREAK, an uncaught
  crash, or a gateway the TUI lost mid session. An owner whose process is gone
  (SIGKILL, power loss: its boot differs from this one, or its pid no longer
  runs) is swept away by the next writer; an entry left with no owner is
  `dropped`. A dropped session may be reopened once (`claim_resumable`, which
  marks it `resumed`).

Liveness that cannot be told counts as alive: a session that may still run
is never handed out again.

Kept in `<omh_home>/tui/live-sessions.json` (`omh_tui_live_sessions/v1`,
newest last, at most `MAX_ENTRIES`), written 0600 by temp file and rename
under `live-sessions.lock` (fcntl on POSIX, msvcrt on Windows), waited for at
most `LOCK_WAIT_SECONDS` and then given up. Two small files beside it let a
shell decide without Python whether a sweep could find anything:
`resume-pending` exists exactly when some entry is `dropped`, and `live-pids`
holds, on one line, the boot its writer ran on (`boot_identity()` without
spaces, `-` when unknown) and then the pids of every live owner (gone when
there is none), so a pid no longer running there, or on Linux a boot id other
than the recorded one, means a TUI vanished without a word. Every
function is best effort: an unreadable, corrupt, oversized or non-regular file
(a symlink, a FIFO) reads as empty and is never opened in a way that could
block, the small files are only ever replaced atomically or removed, and no OS
or JSON failure reaches the caller. Stdlib only; nothing is spawned, signalled
or sent anywhere.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
import copy
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

from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat

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
LIVE_PIDS_FILE = "live-pids"
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
        moment = strict_fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _directory(omh_home: Path) -> Path:
    return Path(omh_home) / "tui"


def _real(path: str) -> str:
    return os.path.normcase(os.path.realpath(path)) if path else ""


def _text(value: object, limit: int = MAX_FIELD_CHARS) -> str | None:
    return value if isinstance(value, str) and len(value) <= limit and value.isprintable() else None


def _owner(value: object) -> dict[str, Any] | None:
    """A stored owner (`pid`, `boot`, `terminal_key`) in its shape, or None for anything else."""
    if not isinstance(value, dict):
        return None
    pid, boot, key = value.get("pid"), _text(value.get("boot")), _text(value.get("terminal_key"))
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or boot is None or key is None:
        return None
    return {"pid": pid, "boot": boot, "terminal_key": key}


def _entry(value: object) -> dict[str, Any] | None:
    """A stored entry in the schema's shape, or None for anything else. An entry written before `owners` existed
    (one `pid` and `boot`) reads as one owner while `live`, none otherwise."""
    if not isinstance(value, dict):
        return None
    session_id = _text(value.get("session_id"), TERMINAL_KEY_MAX_CHARS)
    fields = {name: _text(value.get(name)) for name in ("hermes_home", "cwd", "terminal_key", "updated_at")}
    if not session_id or any(field is None for field in fields.values()) or value.get("state") not in STATES:
        return None
    state = value["state"]
    stored = value.get("owners")
    if isinstance(stored, list):
        owners = [owner for owner in map(_owner, stored) if owner is not None]
    else:
        legacy = _owner({"pid": value.get("pid"), "boot": value.get("boot"), "terminal_key": fields["terminal_key"]})
        if legacy is None:
            return None
        owners = [legacy]
    unique = list({owner["pid"]: owner for owner in owners}.values()) if state == LIVE else []
    return {"session_id": session_id, **fields, "state": state, "owners": unique}


def _read_regular(path: Path, limit: int) -> bytes | None:
    """At most `limit` + 1 bytes of the regular file at `path`; None when it is missing or anything else (a symlink,
    a FIFO, a device, a directory). Checked before the open, which neither follows nor blocks, and again after it."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0))
        descriptor = os.open(path, flags)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return None
        return handle.read(limit + 1)


def _load(directory: Path) -> list[dict[str, Any]]:
    """The kept entries, oldest first, one per session id; [] for a missing, non-regular, oversized or corrupt
    file."""
    try:
        raw = _read_regular(directory / LIVE_SESSIONS_FILE, MAX_FILE_BYTES)
        if raw is None or len(raw) > MAX_FILE_BYTES:
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
    """`data` at `path`, mode 0600, by a temp file in the same directory and a rename (whatever held the name, a
    symlink or a FIFO, is replaced, never followed or opened)."""
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


def _publish(path: Path, data: bytes | None) -> None:
    """Bring the small file at `path` in line with `data` (None: no file), by atomic replace or unlink only; a
    regular file already holding `data` is left alone. Best effort."""
    try:
        if data is None:
            if os.path.lexists(path):
                os.unlink(path)
        elif _read_regular(path, len(data)) != data:
            _write_private(path, data)
    except OSError:
        pass


def boot_word(boot: str) -> str:
    """`boot` as the first word of `LIVE_PIDS_FILE`: its spaces removed, `-` when unknown or not printable ASCII.
    On Linux it is the boot id verbatim, which the shell hook compares with `/proc/sys/kernel/random/boot_id`."""
    word = "".join(boot.split())
    return word if word and word.isascii() and word.isprintable() else "-"


def _live_pids(entries: list[dict[str, Any]], boot: str) -> bytes | None:
    """`<boot> <pid> <pid> ...` for every live owner (all on `boot`: the sweep before it removed the others)."""
    pids = sorted({owner["pid"] for entry in entries if entry["state"] == LIVE for owner in entry["owners"]})
    return (" ".join([boot_word(boot), *map(str, pids)]) + "\n").encode("ascii") if pids else None


def _sync_files(directory: Path, entries: list[dict[str, Any]], boot: str) -> None:
    """`PENDING_MARKER` exists iff some entry is `dropped`; `LIVE_PIDS_FILE` names this boot and every live owner's
    pid, or is gone when none is left."""
    _publish(directory / PENDING_MARKER, b"" if any(entry["state"] == DROPPED for entry in entries) else None)
    _publish(directory / LIVE_PIDS_FILE, _live_pids(entries, boot))


def _owner_alive(owner: Mapping[str, Any], boot: str) -> bool:
    return _same_boot(owner["boot"], boot) and pid_alive(owner["pid"])


def _leave(entry: dict[str, Any], owner: Mapping[str, Any]) -> None:
    """`owner` no longer holds `entry`; the entry keeps the terminal of the owner that left last."""
    entry["owners"] = [kept for kept in entry["owners"] if kept["pid"] != owner["pid"]]
    entry["terminal_key"] = owner["terminal_key"]


def _sweep(entries: list[dict[str, Any]], now: datetime, boot: str) -> None:
    """Owners whose process is gone (another boot than `boot`, or the pid no longer runs) leave their `live` entry;
    an entry left with no owner becomes `dropped`, stamped now (when it was found gone)."""
    for entry in entries:
        if entry["state"] != LIVE:
            continue
        for owner in [owner for owner in entry["owners"] if not _owner_alive(owner, boot)]:
            _leave(entry, owner)
        if not entry["owners"]:
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
    taken within `LOCK_WAIT_SECONDS`, when the name holds anything but a regular file, or on a platform with no file
    lock."""
    if fcntl is None and msvcrt is None:
        yield False
        return
    path = directory / LOCK_FILE
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(path) and not stat.S_ISREG(os.lstat(path).st_mode):
            yield False
            return
        flags = (os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                 | getattr(os, "O_CLOEXEC", 0))
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        yield False
        return
    held = False
    try:
        try:
            regular = stat.S_ISREG(os.fstat(descriptor).st_mode)
        except OSError:
            regular = False
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while regular:
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
    answer, or `default` when the lock or the store failed. Without `create`, a home with none of the store's files
    answers `default` at once and gains no file."""
    try:
        directory = _directory(omh_home)
        if not create and not any(os.path.lexists(directory / name)
                                  for name in (LIVE_SESSIONS_FILE, PENDING_MARKER, LIVE_PIDS_FILE)):
            return default
        with _locked(directory) as held:
            if not held:
                return default
            entries = _load(directory)
            before = json.dumps(entries)
            now = _utc_now()
            boot = boot_identity()
            _sweep(entries, now, boot)
            answer = change(entries, now)
            entries[:] = _pruned(entries, now)
            if json.dumps(entries) != before:
                document = {"schema_version": LIVE_SESSIONS_SCHEMA, "sessions": entries}
                _write_private(directory / LIVE_SESSIONS_FILE, (json.dumps(document, indent=2) + "\n").encode("utf-8"))
            _sync_files(directory, entries, boot)
            return answer
    except _BEST_EFFORT:
        return default


def _move_last(entries: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    entries[:] = [*(kept for kept in entries if kept is not entry), entry]


def _owned_by(entry: Mapping[str, Any], pid: int) -> dict[str, Any] | None:
    """`pid`'s owner of `entry` while the entry is `live`, else None."""
    if entry["state"] != LIVE:
        return None
    return next((owner for owner in entry["owners"] if owner["pid"] == pid), None)


def _end(entry: dict[str, Any], owner: Mapping[str, Any], state: str, stamp: str) -> bool:
    """`owner` leaves `entry` as `state`; the entry ends as `state` when it was the last owner (the last window's
    end decides: a drop elsewhere followed by a close here is `closed`). Whether the entry ended."""
    _leave(entry, owner)
    if entry["owners"]:
        return False
    entry["state"], entry["updated_at"] = state, stamp
    return True


def record_live(
    omh_home: Path, session_id: str, hermes_home: str, cwd: str, environ: Mapping[str, str], *, previous: str = "",
) -> None:
    """This process now holds `session_id` (in `hermes_home`, from `cwd`, in the terminal `environ` names), beside
    any other TUI that holds it too; it leaves the `previous` session it moved away from, which is `closed` once no
    other TUI holds it."""
    if not _text(session_id, TERMINAL_KEY_MAX_CHARS) or not hermes_home:
        return
    key = terminal_key(environ)
    owner = {"pid": os.getpid(), "boot": boot_identity(), "terminal_key": key}
    fields = {
        "session_id": session_id, "hermes_home": os.path.abspath(hermes_home)[:MAX_FIELD_CHARS],
        "cwd": os.path.abspath(cwd)[:MAX_FIELD_CHARS] if cwd else "", "terminal_key": key,
    }
    if _entry({**fields, "state": LIVE, "owners": [owner], "updated_at": "x"}) is None:
        return  # a path that cannot be stored (a control character in it)

    def change(entries: list[dict[str, Any]], now: datetime) -> None:
        stamp = _stamp(now)
        for kept in list(entries):
            if not previous or previous == session_id or kept["session_id"] != previous:
                continue
            mine = _owned_by(kept, owner["pid"])
            if mine is not None and _end(kept, mine, CLOSED, stamp):
                _move_last(entries, kept)
        held = next((kept for kept in entries if kept["session_id"] == session_id), None)
        others = [kept for kept in held["owners"] if kept["pid"] != owner["pid"]] if held and held["state"] == LIVE else []
        entries[:] = [kept for kept in entries if kept is not held]
        entries.append({**fields, "state": LIVE, "owners": [*others, owner], "updated_at": stamp})

    _update(omh_home, change, None)


def record_end(omh_home: Path, session_id: str, state: str, pid: int | None = None) -> None:
    """Process `pid` (this one by default), which held `session_id`, left it as `state` (`closed` or `dropped`).
    The entry ends as `state` only when that was its last owner; one `pid` does not hold is left as it is."""
    if not session_id or state not in END_STATES:
        return
    leaving = os.getpid() if pid is None else pid

    def change(entries: list[dict[str, Any]], now: datetime) -> None:
        for kept in entries:
            mine = _owned_by(kept, leaving) if kept["session_id"] == session_id else None
            if mine is not None:
                if _end(kept, mine, state, _stamp(now)):
                    _move_last(entries, kept)
                return

    _update(omh_home, change, None, create=False)


def claim_resumable(
    omh_home: Path, *, hermes_homes: Collection[str], cwd: str, environ: Mapping[str, str],
    max_age_hours: float = 72, strict_keys: bool = False,
) -> dict[str, Any] | None:
    """The dropped session a reopen in this terminal (else this directory) should run, marked `resumed` so no other
    reopen takes it too; a copy of its entry, or None.

    Candidates are `dropped` (no TUI holds them), live in one of `hermes_homes` and younger than `max_age_hours`.
    The newest whose terminal key is this terminal's wins; else, outside omher (`TERM_PROGRAM=omher`, whose
    terminals always carry their own key), the newest from the same directory. With `strict_keys` (an unattended
    start: the shell hook), the directory never hands over a session another known terminal left.
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

        def same_folder(entry: dict[str, Any]) -> bool:
            if strict_keys and key and entry["terminal_key"] and entry["terminal_key"] != key:
                return False
            return bool(entry["cwd"]) and _real(entry["cwd"]) == here

        candidates = [entry for entry in reversed(entries) if candidate(entry)]
        chosen = next((entry for entry in candidates if key and entry["terminal_key"] == key), None)
        if chosen is None and allow_cwd and here:
            chosen = next((entry for entry in candidates if same_folder(entry)), None)
        if chosen is None:
            return None
        chosen["state"], chosen["updated_at"] = RESUMED, _stamp(now)
        _move_last(entries, chosen)
        return copy.deepcopy(chosen)

    return _update(omh_home, change, None, create=False)


def release_claim(omh_home: Path, session_id: str) -> bool:
    """Give back a claim the launch could not open: the `resumed` entry of `session_id` is `dropped` again (stamped
    now) and `PENDING_MARKER` re-armed, so a later launch that can open its home reopens it. Whether one was."""
    if not session_id:
        return False

    def change(entries: list[dict[str, Any]], now: datetime) -> bool:
        for kept in entries:
            if kept["session_id"] == session_id and kept["state"] == RESUMED:
                kept["state"], kept["updated_at"] = DROPPED, _stamp(now)
                _move_last(entries, kept)
                return True
        return False

    return _update(omh_home, change, False, create=False)


def pending(omh_home: Path) -> bool:
    """Whether some session of this home is `dropped` (after sweeping owners whose process is gone); the
    `PENDING_MARKER` and `LIVE_PIDS_FILE` files are brought in line with the answer."""
    return _update(omh_home, lambda entries, _now: any(entry["state"] == DROPPED for entry in entries), False,
                   create=False)


def entries(omh_home: Path) -> list[dict[str, Any]]:
    """What the record holds, oldest first, read without the lock and without changing anything (for
    `omh auto-resume status`). Each entry is a copy in the schema's shape plus `gone`: True for a `live` entry
    every owner of which has left without a word (the next sweep makes it `dropped`). [] when unreadable."""
    try:
        kept = _load(_directory(omh_home))
        boot = boot_identity()
    except _BEST_EFFORT:
        return []
    return [{**copy.deepcopy(entry), "gone": entry["state"] == LIVE
             and not any(_owner_alive(owner, boot) for owner in entry["owners"])} for entry in kept]
