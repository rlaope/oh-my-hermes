"""Did OMH's awareness hook return a payload for model input?

`pre_llm_call` is how OMH gets its primer and route hint in front of Hermes.
Nothing recorded whether that ever happened:

- `host_observation` is invocation evidence, not evidence that this hook
  returned awareness content. The delivery path therefore needs its own
  metadata-only signal even though Hermes supplies session/task/turn identity.
- Hermes wraps every hook callback in try/except and only logs a warning, so a
  hook that raises disappears without a user-visible trace.

Between those two, awareness could be dead for weeks and the only symptom would
be a user learning to type "load OMH" by hand. This records the one fact that
distinguishes those worlds.

The ledger observes the `pre_llm_call` hook returning injection content. It is
not host-consumption acknowledgement and does not prove a model received,
processed, or acted on that content.

Counters, not an append-only log. A per-turn log on the hottest path in the
system is how a journal reached ~4.7k rows of noise; a fixed-shape counter file
cannot grow.
"""

from __future__ import annotations

from . import runtime_paths

import errno
import hashlib
import json
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - absent on Windows.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - present only on Windows.
    msvcrt = None

LOCK_MECHANISM_FCNTL = "fcntl"
LOCK_MECHANISM_MSVCRT = "msvcrt"
LOCK_MECHANISM_NONE = "none"
# Both backends report "already held" through errno rather than a dedicated
# exception: flock uses EACCES/EAGAIN, msvcrt.locking uses EACCES for LK_NBLCK.
_LOCK_BUSY_ERRNOS = frozenset(
    {errno.EACCES, errno.EAGAIN, errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}
)
_LOCK_TIMEOUT_SECONDS = 0.1
_LOCK_POLL_INTERVAL = 0.001


AWARENESS_DELIVERY_SCHEMA_VERSION = "omh_awareness_delivery/v1"
AWARENESS_DELIVERY_FILE = "awareness_delivery.json"
_SESSION_FINGERPRINT_PREFIX = "sha256:"
_MAX_SESSION_ROUTE_FINGERPRINTS = 64


def _is_session_fingerprint(value: str) -> bool:
    digest = value.removeprefix(_SESSION_FINGERPRINT_PREFIX)
    return (
        value.startswith(_SESSION_FINGERPRINT_PREFIX)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _runtime_dir(omh_home: str = "") -> Path:
    root = runtime_paths.expand_path(omh_home) if omh_home else runtime_paths.default_omh_home()
    return root / "runtime"


def awareness_delivery_path(omh_home: str = "") -> Path:
    return _runtime_dir(omh_home) / AWARENESS_DELIVERY_FILE


def read_awareness_delivery(omh_home: str = "") -> dict[str, Any]:
    """Current counters, or an empty record when nothing has been delivered."""
    try:
        data = json.loads(awareness_delivery_path(omh_home).read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return _empty()
    except (OSError, json.JSONDecodeError):
        return {**_empty(), "unreadable": True}
    if not isinstance(data, dict) or not _valid_delivery_record(data):
        return {**_empty(), "unreadable": True}
    return {**_empty(), **data}


def _empty() -> dict[str, Any]:
    return {
        "schema_version": AWARENESS_DELIVERY_SCHEMA_VERSION,
        "delivery_count": 0,
        "route_hint_count": 0,
        "suppressed_count": 0,
        "first_attempted_at": "",
        "first_delivered_at": "",
        "last_delivered_at": "",
        "last_context_chars": 0,
        "accumulated_context_chars": 0,
        "session_route_fingerprints": {},
        "unreadable": False,
    }


def _valid_delivery_record(data: dict[str, Any]) -> bool:
    if data.get("schema_version") != AWARENESS_DELIVERY_SCHEMA_VERSION:
        return False
    for key in (
        "delivery_count",
        "route_hint_count",
        "suppressed_count",
        "last_context_chars",
        "accumulated_context_chars",
    ):
        value = data.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
    for key in ("first_attempted_at", "first_delivered_at", "last_delivered_at"):
        if not isinstance(data.get(key, ""), str):
            return False
    fingerprints = data.get("session_route_fingerprints", {})
    if not isinstance(fingerprints, dict):
        return False
    if len(fingerprints) > _MAX_SESSION_ROUTE_FINGERPRINTS:
        return False
    if any(
        not isinstance(key, str)
        or not _is_session_fingerprint(key)
        or not isinstance(value, str)
        for key, value in fingerprints.items()
    ):
        return False
    return int(data.get("route_hint_count", 0)) <= int(data.get("delivery_count", 0))


def _acquire_delivery_lock(handle: Any, lock_path: Path) -> str:
    """Take an exclusive OS lock, on POSIX or Windows, and say which granted it.

    This module is vendored into the user's Hermes install and imports nothing
    from omh core, so it carries its own two-backend lock instead of sharing
    `local_store.file_lock`. Before it had the msvcrt branch, a Windows host
    took no lock at all here, and the read-modify-write below could interleave
    between concurrent turns and lose counter increments with nothing saying so.

    Both backends use bounded non-blocking attempts. This is best-effort
    telemetry on the model-dispatch path, so contention drops a counter rather
    than delaying the user operation.
    """
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    if fcntl is not None:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return LOCK_MECHANISM_FCNTL
            except OSError as exc:
                if exc.errno not in _LOCK_BUSY_ERRNOS:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for awareness delivery lock: {lock_path}")
                time.sleep(_LOCK_POLL_INTERVAL)
    if msvcrt is None:
        return LOCK_MECHANISM_NONE
    while True:
        try:
            # msvcrt.locking locks a byte range from the current position, so
            # the region has to be pinned to byte 0 on acquire and release for
            # the two calls to describe the same region.
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return LOCK_MECHANISM_MSVCRT
        except OSError as exc:
            if exc.errno not in _LOCK_BUSY_ERRNOS:
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError(f"could not lock {lock_path} within {_LOCK_TIMEOUT_SECONDS}s") from exc
            time.sleep(_LOCK_POLL_INTERVAL)


def _release_delivery_lock(handle: Any, mechanism: str) -> None:
    if mechanism == LOCK_MECHANISM_FCNTL:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if mechanism == LOCK_MECHANISM_MSVCRT:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def _awareness_delivery_lock(path: Path) -> Iterator[str]:
    """Serialize the counter read-modify-write; yields the mechanism that held it.

    A `none` yield means the host had neither backend and the mutual-exclusion
    guarantee did not hold. The block still runs -- refusing would disable
    awareness recording entirely -- but the caller can tell the difference.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.touch(mode=0o600, exist_ok=True)
    lock_path.chmod(0o600)
    with lock_path.open("a+", encoding="utf-8") as handle:
        mechanism = _acquire_delivery_lock(handle, lock_path)
        try:
            yield mechanism
        finally:
            _release_delivery_lock(handle, mechanism)


def _write_delivery_record(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp")
    created = False
    try:
        with tmp.open("x", encoding="utf-8") as handle:
            created = True
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        tmp.chmod(0o600)
        tmp.replace(path)
        path.chmod(0o600)
    except OSError:
        if created and tmp.exists() and not tmp.is_symlink():
            tmp.unlink()
        raise


def _session_fingerprint(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"{_SESSION_FINGERPRINT_PREFIX}{digest}"


def _normalized_session_routes(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, route_fingerprint in value.items():
        if not isinstance(key, str) or not isinstance(route_fingerprint, str):
            continue
        session_fingerprint = key if _is_session_fingerprint(key) else _session_fingerprint(key)
        normalized[session_fingerprint] = route_fingerprint
    while len(normalized) > _MAX_SESSION_ROUTE_FINGERPRINTS:
        normalized.pop(next(iter(normalized)))
    return normalized


def _record_from_current(
    current: dict[str, Any],
    fingerprints: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": AWARENESS_DELIVERY_SCHEMA_VERSION,
        "delivery_count": int(current["delivery_count"]),
        "route_hint_count": int(current["route_hint_count"]),
        "suppressed_count": int(current["suppressed_count"]),
        "first_attempted_at": current["first_attempted_at"],
        "first_delivered_at": current["first_delivered_at"],
        "last_delivered_at": current["last_delivered_at"],
        "last_context_chars": int(current["last_context_chars"]),
        "accumulated_context_chars": int(current["accumulated_context_chars"]),
        "session_route_fingerprints": fingerprints,
    }


def claim_route_guidance_delivery(
    *,
    session_id: str,
    route_fingerprint: str,
    omh_home: str = "",
) -> bool:
    """Atomically claim one session/route pair, failing open on ledger faults."""
    if not session_id or not route_fingerprint:
        return True
    path = awareness_delivery_path(omh_home)
    try:
        with _awareness_delivery_lock(path):
            current = read_awareness_delivery(omh_home)
            fingerprints = _normalized_session_routes(
                current.get("session_route_fingerprints", {})
            )
            session_fingerprint = _session_fingerprint(session_id)
            if fingerprints.get(session_fingerprint) == route_fingerprint:
                return False
            fingerprints[session_fingerprint] = route_fingerprint
            while len(fingerprints) > _MAX_SESSION_ROUTE_FINGERPRINTS:
                fingerprints.pop(next(iter(fingerprints)))
            _write_delivery_record(path, _record_from_current(current, fingerprints))
    except (OSError, TimeoutError, TypeError, ValueError):
        return True
    return True


def record_awareness_delivery(
    *,
    delivered: bool,
    route_hint: bool,
    context_chars: int,
    observed_at: str,
    omh_home: str = "",
    session_id: str = "",
    route_fingerprint: str = "",
) -> dict[str, Any] | None:
    """Bump counters for one `pre_llm_call` hook result. Best-effort and metadata-only.

    Records that an injection payload was returned and how big it was, never what it said:
    the prompt and the hint text stay out of this file, as they stay out of
    every other OMH ledger.

    A write failure returns None rather than raising. Losing a counter is
    acceptable; breaking the hook that feeds the model is not.
    """
    path = awareness_delivery_path(omh_home)
    try:
        with _awareness_delivery_lock(path):
            current = read_awareness_delivery(omh_home)
            fingerprints = _normalized_session_routes(
                current.get("session_route_fingerprints", {})
            )
            if delivered and route_hint and session_id and route_fingerprint:
                fingerprints[_session_fingerprint(session_id)] = route_fingerprint
                while len(fingerprints) > _MAX_SESSION_ROUTE_FINGERPRINTS:
                    fingerprints.pop(next(iter(fingerprints)))
            updated = {
                "schema_version": AWARENESS_DELIVERY_SCHEMA_VERSION,
                "delivery_count": int(current["delivery_count"]) + (1 if delivered else 0),
                "route_hint_count": int(current["route_hint_count"]) + (1 if route_hint else 0),
                "suppressed_count": int(current["suppressed_count"]) + (0 if delivered else 1),
                "first_attempted_at": current["first_attempted_at"] or observed_at,
                "first_delivered_at": current["first_delivered_at"] or (observed_at if delivered else ""),
                "last_delivered_at": observed_at if delivered else current["last_delivered_at"],
                "last_context_chars": (
                    max(0, int(context_chars)) if delivered else int(current["last_context_chars"])
                ),
                "accumulated_context_chars": int(current["accumulated_context_chars"])
                + (max(0, int(context_chars)) if delivered else 0),
                "session_route_fingerprints": fingerprints,
            }
            _write_delivery_record(path, updated)
    except (OSError, TimeoutError, TypeError, ValueError):
        return None
    return updated


def route_guidance_already_delivered(
    *,
    session_id: str,
    route_fingerprint: str,
    omh_home: str = "",
) -> bool:
    if not session_id or not route_fingerprint:
        return False
    current = read_awareness_delivery(omh_home)
    fingerprints = _normalized_session_routes(current.get("session_route_fingerprints", {}))
    return fingerprints.get(_session_fingerprint(session_id)) == route_fingerprint
