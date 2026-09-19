from __future__ import annotations

import errno
import json
import os
import random
import secrets
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

LOCK_MECHANISM_FCNTL = "fcntl"
LOCK_MECHANISM_MSVCRT = "msvcrt"
LOCK_MECHANISM_NONE = "none"
LOCK_UNENFORCED_REASON = "no_os_file_lock"
# Both backends report "the region is already held" through errno rather than a
# dedicated exception: fcntl.flock uses EACCES/EAGAIN, msvcrt.locking uses
# EACCES for LK_NBLCK and EDEADLK when a blocking attempt gives up.
_LOCK_BUSY_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dir(path: Path, *, private: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if private:
        _with_windows_retry(lambda: path.chmod(0o700))


def is_junction(path: Path) -> bool:
    """True when *path* is a Windows directory junction.

    ``Path.is_junction`` only ever returns True on Windows, so the probe is
    fetched by name rather than called directly.
    """
    probe = getattr(path, "is_junction", None)
    return bool(probe and probe())


def is_directory_link(path: Path) -> bool:
    """True when *path* is a symlink or a Windows directory junction.

    A directory link answers True to ``is_dir()`` when it resolves and False
    when it dangles, so every removal or replacement decision has to ask about
    the link itself before it asks about the link's target.
    """
    return path.is_symlink() or is_junction(path)


def discard_path(path: Path, *, ignore_errors: bool = False) -> None:
    """Remove *path* whatever it is: symlink, junction, file, or directory.

    ``shutil.rmtree`` cannot remove a symbolic link. It descends into the
    link's target, fails, and with ``ignore_errors=True`` leaves the link in
    place without a word. A leftover link at a path an install is about to
    rename over then breaks that rename, because ``rename(2)`` refuses to
    rename a directory over a non-directory (``ENOTDIR``). Removal therefore
    has to dispatch on the entry type, and a directory link has to be unlinked
    as a link rather than walked as a directory.

    ``ignore_errors`` mirrors ``shutil.rmtree``'s flag and extends it to the
    unlink branches, so a best-effort pre-clean stays best-effort for every
    entry type instead of only for real directories. A missing path is always
    a no-op.
    """
    if path.is_dir() and not is_directory_link(path):
        shutil.rmtree(path, ignore_errors=ignore_errors)
        return
    if not path.exists() and not is_directory_link(path):
        return
    try:
        if is_junction(path):
            # A junction is a directory entry; unlink refuses it on Windows.
            path.rmdir()
        else:
            path.unlink()
    except OSError:
        if not ignore_errors:
            raise


def ensure_file(path: Path, *, private: bool = False) -> None:
    # The chmod goes through the same Windows retry `atomic_write_text` uses,
    # and for the same recorded reason: chmod opens the file and races the
    # sharing window, so it is denied while a concurrent holder has the file
    # open. `file_lock` calls this on its lock sidecar *before* taking the
    # lock, so every waiter runs it at once against a file the other waiters
    # already hold open -- the one place in this module where that window is
    # not merely possible but structural.
    if not path.exists():
        path.touch(mode=0o600 if private else 0o666)
    if private:
        _with_windows_retry(lambda: path.chmod(0o600))


def can_write_dir(path: Path, *, probe_name: str = ".write-test", private: bool = False) -> bool:
    try:
        ensure_dir(path, private=private)
        probe = path / probe_name
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _with_windows_retry(operation: Callable[[], None]) -> None:
    # Windows denies replace/chmod while the target is transiently opened by
    # a concurrent reader or replacer (WinError 5/32); POSIX never does. The
    # backoff is jittered: barrier-synchronized writers re-collide in
    # lockstep on deterministic delays.
    for delay in (0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8):
        try:
            operation()
            return
        except PermissionError:
            if os.name != "nt":
                raise
            time.sleep(delay * (0.5 + random.random()))
    operation()


def atomic_write_text(path: Path, text: str, *, private: bool = False) -> None:
    ensure_dir(path.parent, private=private)
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
    created_tmp = False
    try:
        # newline="" keeps written bytes platform-stable ("\n" stays "\n");
        # managed-file freshness checks compare disk bytes against template bytes.
        with tmp.open("x", encoding="utf-8", newline="") as handle:
            created_tmp = True
            handle.write(text)
        if private:
            tmp.chmod(0o600)
        _with_windows_retry(lambda: tmp.replace(path))
        if private:
            _with_windows_retry(lambda: path.chmod(0o600))
    except OSError:
        if created_tmp and tmp.exists() and not tmp.is_symlink():
            tmp.unlink()
        raise


def atomic_replace_text(path: Path, text: str, *, guard: Callable[[], bool]) -> bool:
    """Replace `path` atomically, aborting when `guard()` says it moved under us.

    `atomic_write_text` above is for files OMH owns outright, where the last
    writer is always right. This one is for a file somebody else also writes
    -- the person's Hermes `config.yaml` -- where the last writer being right
    means losing the other's update.

    The guard runs with the replacement already on disk as a temp file in the
    same directory AND already carrying the destination's mode, so the only
    thing left after it returns is the rename. That is what makes the
    compare sufficient: the last instant another writer's change can be
    observed is the guard, and the window after it is one `os.replace`,
    which is atomic. Returns False, having replaced nothing, when the guard
    refuses.

    The destination's mode is read first, before the temp file exists,
    because a rename installs the temp file's mode and the temp file was
    created under this process's umask; without this a config a person had
    chmodded to 0600 would silently widen on the next OMH write. Reading it
    up front is also what keeps the guard-to-rename window empty -- an
    earlier version did the `stat` and the `chmod` between the two and then
    described the window as one rename, which was not true.
    """
    ensure_dir(path.parent)
    try:
        mode = path.stat().st_mode & 0o7777
    except FileNotFoundError:
        mode = 0
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
    created_tmp = False
    try:
        with tmp.open("x", encoding="utf-8", newline="") as handle:
            created_tmp = True
            handle.write(text)
        if mode:
            _with_windows_retry(lambda: tmp.chmod(mode))
        if not guard():
            tmp.unlink()
            return False
        _with_windows_retry(lambda: tmp.replace(path))
        return True
    except OSError:
        if created_tmp and tmp.exists() and not tmp.is_symlink():
            tmp.unlink()
        raise


def atomic_write_json(path: Path, data: dict[str, Any], *, private: bool = False) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n", private=private)


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def read_json_object_result(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    # RecursionError: a pathologically nested document (e.g. 60k open
    # brackets) overflows the JSON decoder's recursion before it can raise
    # JSONDecodeError. Callers use this reader on never-raise config paths
    # (dispatch model preferences, category-maestro), so that shape must read
    # as malformed, not abort a prepare or dispatch with a traceback.
    try:
        return read_json_object(path), None
    except (OSError, JSONDecodeError, RecursionError, ValueError) as exc:
        return None, str(exc)


def read_jsonl_objects(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{path}: {exc}"]
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except JSONDecodeError as exc:
            errors.append(f"{path}:{index}: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"{path}:{index}: event must be an object")
            continue
        records.append(record)
    return records, errors


class FileLockTimeout(TimeoutError):
    """Raised when an advisory file lock cannot be acquired within the timeout."""


def _acquire_os_file_lock(
    handle: Any,
    path: Path,
    *,
    deadline: float,
    poll_interval: float,
    timeout_seconds: float,
) -> str:
    """Take an exclusive OS lock on the already-open sidecar handle.

    Returns the mechanism that granted it. Both backends are polled through
    their non-blocking flag so one shared timeout covers either platform.
    """
    while True:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return LOCK_MECHANISM_FCNTL
            # msvcrt.locking locks a byte range starting at the current file
            # position, so the region has to be pinned to byte 0 on both the
            # acquire and the release for the two calls to describe one region.
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return LOCK_MECHANISM_MSVCRT
        except OSError as exc:
            if exc.errno not in _LOCK_BUSY_ERRNOS:
                raise
            if time.monotonic() >= deadline:
                raise FileLockTimeout(f"could not acquire lock on {path} within {timeout_seconds}s") from exc
            time.sleep(poll_interval)


def _release_os_file_lock(handle: Any, mechanism: str) -> None:
    if mechanism == LOCK_MECHANISM_FCNTL:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def file_lock(
    path: Path,
    *,
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.05,
    private: bool = False,
) -> Iterator[dict[str, Any]]:
    """Hold an exclusive advisory lock on the ``.<name>.lock`` sidecar of path.

    ``path`` itself is never opened, created, or written here; only the sidecar
    is. POSIX locks through ``fcntl.flock`` and Windows through
    ``msvcrt.locking``, so mutual exclusion is a real OS lock on both and the
    yielded mapping reports ``enforced: True``.

    On a platform with neither module the lock cannot be taken at all. The
    block still runs - refusing to run would break every caller - but the
    yielded mapping reports ``locked: False``, ``enforced: False`` and a
    ``reason``, so a caller can surface that the mutual-exclusion guarantee did
    not hold instead of assuming it did.
    """
    lock_path = path.with_name(f".{path.name}.lock")
    ensure_dir(lock_path.parent, private=private)
    if fcntl is None and msvcrt is None:
        yield {
            "locked": False,
            "enforced": False,
            "mechanism": LOCK_MECHANISM_NONE,
            "reason": LOCK_UNENFORCED_REASON,
        }
        return
    ensure_file(lock_path, private=private)
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    handle = lock_path.open("a+")
    try:
        mechanism = _acquire_os_file_lock(
            handle,
            path,
            deadline=deadline,
            poll_interval=poll_interval,
            timeout_seconds=timeout_seconds,
        )
        try:
            yield {"locked": True, "enforced": True, "mechanism": mechanism, "reason": ""}
        finally:
            _release_os_file_lock(handle, mechanism)
    finally:
        handle.close()


def append_jsonl_locked(path: Path, record: dict[str, Any], *, private: bool = True) -> dict[str, Any]:
    """Append one JSON line to ``path`` while holding an exclusive OS lock.

    Callers used to take ``fcntl.flock`` on the journal handle directly and
    skip locking entirely when fcntl was missing. On Windows that meant
    concurrent appenders had no mutual exclusion at all, and -- unlike
    ``file_lock``, which reports ``enforced: False`` -- nothing said so, which
    is the worse half of the bug: a guarantee that quietly is not one.

    Going through ``file_lock`` gets ``msvcrt.locking`` on Windows, so the
    guarantee actually holds there, and keeps the honest signal for a platform
    that has neither backend.

    Returns the lock status mapping so a caller can surface an unenforced
    write. The append happens either way, because refusing to write on such a
    platform would break every caller rather than protect anything.
    """
    ensure_dir(path.parent, private=private)
    ensure_file(path, private=private)
    with file_lock(path, private=private) as lock:
        # newline="" for the same reason atomic_write_text uses it: text mode
        # would translate "\n" to "\r\n" on Windows, so the same record would
        # land as different bytes per platform. The callers this replaced wrote
        # in translating mode and had that drift.
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
        return dict(lock)


def locked_json_update(
    path: Path,
    mutate_fn: Callable[[dict[str, Any]], dict[str, Any] | None],
    *,
    default: dict[str, Any] | None = None,
    private: bool = False,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    with file_lock(path, timeout_seconds=timeout_seconds, private=private):
        current, _ = read_json_object_result(path)
        if current is None:
            current = dict(default) if default is not None else {}
        updated = mutate_fn(current)
        if updated is None:
            updated = current
        atomic_write_json(path, updated, private=private)
        return updated
