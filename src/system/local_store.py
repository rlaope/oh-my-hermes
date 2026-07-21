from __future__ import annotations

import errno
import json
import os
import secrets
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dir(path: Path, *, private: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if private:
        path.chmod(0o700)


def ensure_file(path: Path, *, private: bool = False) -> None:
    if not path.exists():
        path.touch(mode=0o600 if private else 0o666)
    if private:
        path.chmod(0o600)


def can_write_dir(path: Path, *, probe_name: str = ".write-test", private: bool = False) -> bool:
    try:
        ensure_dir(path, private=private)
        probe = path / probe_name
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def atomic_write_text(path: Path, text: str, *, private: bool = False) -> None:
    ensure_dir(path.parent, private=private)
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
    created_tmp = False
    try:
        with tmp.open("x", encoding="utf-8") as handle:
            created_tmp = True
            handle.write(text)
        if private:
            tmp.chmod(0o600)
        tmp.replace(path)
        if private:
            path.chmod(0o600)
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
    try:
        return read_json_object(path), None
    except (OSError, JSONDecodeError, ValueError) as exc:
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


@contextmanager
def file_lock(
    path: Path,
    *,
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.05,
    private: bool = False,
) -> Iterator[dict[str, Any]]:
    lock_path = path.with_name(f".{path.name}.lock")
    ensure_dir(lock_path.parent, private=private)
    if fcntl is None:
        yield {"locked": False, "reason": "fcntl_unavailable"}
        return
    ensure_file(lock_path, private=private)
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    handle = lock_path.open("a+")
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise FileLockTimeout(f"could not acquire lock on {path} within {timeout_seconds}s") from exc
                time.sleep(poll_interval)
        try:
            yield {"locked": True, "reason": ""}
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


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
