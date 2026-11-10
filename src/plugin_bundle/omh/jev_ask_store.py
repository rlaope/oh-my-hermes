"""Where `omh_jev_ask` finds its route and records what it did -- never a key or any text.

Three things live here, all local:

* The operator setting `<omh_home>/jev/settings.json`. `{"openrouter_route":
  true}` is the only way the OpenRouter route becomes available: an
  `OPENROUTER_API_KEY` on its own is an OpenRouter account, not a request to
  send OMH's questions through it, and treating it as one would make every
  OpenRouter user a Jev user. The same file is the home for the route-question
  answerer opt-in proposed in #1816, so one Jev egress has one consent file.
  OMH never writes it. It is a local-trust opt-in, not a control against the
  host model: anything with write access to `<omh_home>` -- the operator, and
  a model with a file tool -- can write it. It chooses which of the person's
  own keys an ask may use; it cannot send an ask, which still needs this
  turn's consent (`jev_consent`). Two more keys serve a self-hosted
  Jev-compatible server: `{"local_http_endpoint": true}` lets
  `TYPESAFE_BASE_URL` name a plain-HTTP root on a loopback, private, or
  link-local host, and `"typesafe_model"` names the model id such an
  operator endpoint serves.
* Route availability. The key VALUE is read only at call time, through the
  host's profile-scoped reader (`agent.secret_scope.get_secret`) when Hermes
  is present and `os.environ` only when that import does not exist. A host
  that refuses the read (`UnscopedSecretError` under the multiplexing gateway)
  makes the route unresolvable; OMH never falls back to another source.
* The ask ledger `<omh_home>/jev/asks.jsonl`: one metadata-only line per
  attempted ask, every status included. It carries hashes, counts, statuses,
  usage, and cost, and never the key, `state`, question text, or the reply.
  `omh doctor` reads it for the last status. It is a record, not evidence:
  a model with a file tool can append a row, so `omh_route_answer` confirms
  an `omh_jev_ask` provenance claim against `answered_ask` -- the asks this
  process itself answered -- and never against the file.

Stdlib and intra-bundle imports only.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from .awareness_delivery import _awareness_delivery_lock, _awareness_delivery_lock_at

JEV_DIRNAME: Final = "jev"
SETTINGS_FILENAME: Final = "settings.json"
LEDGER_FILENAME: Final = "asks.jsonl"
OPENROUTER_SETTING_KEY: Final = "openrouter_route"
LOCAL_HTTP_SETTING_KEY: Final = "local_http_endpoint"
TYPESAFE_MODEL_SETTING_KEY: Final = "typesafe_model"
# A served model id as Ollama, vLLM, or llama.cpp spell one
# (`clef-flash:latest`, `org/model@rev`), never free text.
_OPERATOR_MODEL_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")
LEDGER_SCHEMA_VERSION: Final = "omh_jev_ask_record/v1"
MAX_SETTINGS_BYTES: Final = 4096
MAX_LEDGER_BYTES: Final = 512 * 1024
MAX_LEDGER_LINES: Final = 512
_LEDGER_LOCK_SECONDS: Final = 2.0
MAX_REMEMBERED_ASKS: Final = 256

_answered_lock = threading.Lock()
# ask_id -> the ledger record of an ask this process sent and Jev answered.
_answered_asks: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

ROUTE_TYPESAFE: Final = "typesafe"
ROUTE_OPENROUTER: Final = "openrouter"
ROUTE_NONE: Final = "none"
# route id -> key variable name. The URLs live in `jev_ask_client.ROUTES`,
# which only the tool may import; `tests/test_jev_ask_tool.py` pins that the
# two tables name the same routes and the same variables.
ROUTE_KEY_NAMES: Final[dict[str, str]] = {
    ROUTE_TYPESAFE: "TYPESAFE_API_KEY",
    ROUTE_OPENROUTER: "OPENROUTER_API_KEY",
}


class KeyUnresolvable(RuntimeError):
    """The host refused to read the key for this profile."""


def settings_path(omh_home: Path) -> Path:
    return Path(omh_home) / JEV_DIRNAME / SETTINGS_FILENAME


def ledger_path(omh_home: Path) -> Path:
    return Path(omh_home) / JEV_DIRNAME / LEDGER_FILENAME


def _read_settings(omh_home: Path) -> dict[str, Any]:
    """The operator settings object, or {} for a missing, symlinked, oversized, or unreadable file."""
    path = settings_path(omh_home)
    try:
        if path.is_symlink():
            return {}
        with path.open("rb") as handle:
            raw = handle.read(MAX_SETTINGS_BYTES + 1)
    except OSError:
        return {}
    if len(raw) > MAX_SETTINGS_BYTES:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def openrouter_route_enabled(omh_home: Path) -> bool:
    """True only for a readable settings file whose `openrouter_route` is the literal `true`."""
    return _read_settings(omh_home).get(OPENROUTER_SETTING_KEY) is True


def local_http_endpoint_enabled(omh_home: Path) -> bool:
    """True only for a readable settings file whose `local_http_endpoint` is the literal `true`.

    It lets `TYPESAFE_BASE_URL` name a plain-HTTP root, and only one whose
    host is `localhost` or a loopback, private, or link-local IP literal
    (`jev_ask_client.route_url`): a Jev-compatible server on this machine or
    the local network. It widens nothing for a public host.
    """
    return _read_settings(omh_home).get(LOCAL_HTTP_SETTING_KEY) is True


def operator_typesafe_model(omh_home: Path) -> str:
    """The `typesafe_model` id the operator named, or "" when unset or not a plain model id.

    The tool applies it only when `TYPESAFE_BASE_URL` names an endpoint other
    than TypeSafe's own, so the first-party route keeps its pinned versions.
    """
    value = _read_settings(omh_home).get(TYPESAFE_MODEL_SETTING_KEY)
    if not isinstance(value, str) or not _OPERATOR_MODEL_ID.fullmatch(value):
        return ""
    return value


def read_key(name: str) -> str:
    """The key value for one variable name, or "" when it is not set.

    Raises KeyUnresolvable when the host's scoped reader refuses. The value is
    returned to the one caller that sends it and is never stored.
    """
    try:
        from agent.secret_scope import UnscopedSecretError, get_secret
    except ImportError:
        return str(os.environ.get(name, "") or "")
    try:
        value = get_secret(name)
    except UnscopedSecretError as error:
        raise KeyUnresolvable(f"the host did not resolve {name} for this profile") from error
    return str(value or "")


def resolve_route(requested: str, omh_home: Path) -> tuple[str, str]:
    """(route, key variable name) for a requested route, or (ROUTE_NONE, "") when none resolves.

    `auto` prefers the first-party route. A forced route whose key is absent
    does not fall back. Raises KeyUnresolvable from `read_key`.
    """
    candidates: list[str]
    if requested == ROUTE_TYPESAFE:
        candidates = [ROUTE_TYPESAFE]
    elif requested == ROUTE_OPENROUTER:
        candidates = [ROUTE_OPENROUTER]
    else:
        candidates = [ROUTE_TYPESAFE, ROUTE_OPENROUTER]
    for route in candidates:
        if route == ROUTE_OPENROUTER and not openrouter_route_enabled(omh_home):
            continue
        name = ROUTE_KEY_NAMES[route]
        if read_key(name):
            return route, name
    return ROUTE_NONE, ""


def route_available(omh_home: Path) -> str:
    """Which route an ask would take right now, for `check_fn`; never raises."""
    try:
        route, _ = resolve_route("auto", omh_home)
    except KeyUnresolvable:
        return ROUTE_NONE
    except Exception:  # noqa: BLE001 - classified: availability probe fails closed to "none", and the tool stays hidden
        return ROUTE_NONE
    return route


def route_available_by_names(omh_home: Path, env_names: set[str] | frozenset[str]) -> str:
    """The same answer from variable NAMES only, for `omh doctor`; reads no value."""
    if ROUTE_KEY_NAMES[ROUTE_TYPESAFE] in env_names:
        return ROUTE_TYPESAFE
    if ROUTE_KEY_NAMES[ROUTE_OPENROUTER] in env_names and openrouter_route_enabled(omh_home):
        return ROUTE_OPENROUTER
    return ROUTE_NONE


# Every primitive the descriptor-anchored ledger write needs. `os.replace`
# shares `os.rename`'s renameat implementation but is not listed in
# `os.supports_dir_fd` on every CPython, so `os.rename` stands for both.
_DIR_FD_WRITE: Final = bool(
    getattr(os, "O_NOFOLLOW", 0)
    and getattr(os, "O_DIRECTORY", 0)
    and hasattr(os, "fchmod")
    and hasattr(os, "getuid")
    and os.open in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
)
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)


def append_ledger_record(omh_home: Path, record: Mapping[str, Any]) -> bool:
    """Append one metadata-only record, keeping the newest MAX_LEDGER_LINES; False when unwritable.

    On POSIX every step after the parent check runs relative to one directory
    descriptor: `<omh_home>/jev` is opened `O_DIRECTORY|O_NOFOLLOW`, checked to
    be a directory this user owns and the same inode the path named, and the
    lock, read, temp create, chmod and rename all go through that descriptor.
    Swapping the directory for a symlink after that open cannot redirect the
    write. Without `dir_fd` support (Windows) the path-based write remains: it
    refuses a symlinked parent or ledger when checked, but a parent swapped
    between that check and the temp-file create or the replace is followed --
    a bounded residual that needs an attacker able to rename entries inside
    the person's own `<omh_home>`.
    """
    path = ledger_path(omh_home)
    if _DIR_FD_WRITE:
        return _append_ledger_record_at(path, record)
    try:
        for ancestor in (path, path.parent):
            if ancestor.is_symlink():
                return False
        with _awareness_delivery_lock(path, timeout_seconds=_LEDGER_LOCK_SECONDS):
            lines = _ledger_lines(path)
            lines.append(json.dumps(dict(record), sort_keys=True, ensure_ascii=True))
            lines = lines[-MAX_LEDGER_LINES:]
            # A random, exclusively created name: a predictable one let a
            # planted symlink redirect this write and its chmod at any file.
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            replaced = False
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    try:
                        os.fchmod(handle.fileno(), 0o600)
                    except (AttributeError, OSError):
                        pass  # mkstemp already created it 0600; best-effort as before
                    handle.write("\n".join(lines) + "\n")
                os.replace(temporary, path)
                replaced = True
            finally:
                if not replaced:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
    except OSError:
        return False
    return True


def _open_ledger_dir(directory: Path) -> int:
    """Open ``directory`` without following a link and prove it is the one the path named."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    expected = os.lstat(directory)
    if not stat.S_ISDIR(expected.st_mode):
        raise OSError(f"ledger directory is not a directory: {directory}")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC)
    keep = False
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != os.getuid()
            or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
        ):
            raise OSError(f"ledger directory changed or is not ours: {directory}")
        os.fchmod(fd, 0o700)
        keep = True
    finally:
        if not keep:
            os.close(fd)
    return fd


def _append_ledger_record_at(path: Path, record: Mapping[str, Any]) -> bool:
    name = path.name
    try:
        dir_fd = _open_ledger_dir(path.parent)
    except OSError:
        return False
    try:
        with _awareness_delivery_lock_at(dir_fd, name, timeout_seconds=_LEDGER_LOCK_SECONDS):
            try:
                current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if current is not None and stat.S_ISLNK(current.st_mode):
                return False
            lines = _ledger_lines_at(dir_fd, name)
            lines.append(json.dumps(dict(record), sort_keys=True, ensure_ascii=True))
            lines = lines[-MAX_LEDGER_LINES:]
            temporary = f".{name}.{secrets.token_hex(8)}.tmp"
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC,
                0o600,
                dir_fd=dir_fd,
            )
            replaced = False
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write("\n".join(lines) + "\n")
                os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                replaced = True
            finally:
                if not replaced:
                    try:
                        os.unlink(temporary, dir_fd=dir_fd)
                    except OSError:
                        pass
    except OSError:
        return False
    finally:
        os.close(dir_fd)
    return True


def read_ledger_records(omh_home: Path) -> list[dict[str, Any]]:
    """Every parseable record, oldest first; an unreadable ledger reads as empty."""
    records: list[dict[str, Any]] = []
    for line in _ledger_lines(ledger_path(omh_home)):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("schema_version") == LEDGER_SCHEMA_VERSION:
            records.append(data)
    return records


def remember_answered_ask(record: Mapping[str, Any]) -> None:
    """Keep an answered ask's record in this process; only `omh_jev_ask` calls this."""
    ask_id = str(record.get("ask_id") or "")
    if not ask_id or record.get("status") != "answered":
        return
    with _answered_lock:
        _ = _answered_asks.pop(ask_id, None)
        _answered_asks[ask_id] = dict(record)
        while len(_answered_asks) > MAX_REMEMBERED_ASKS:
            _ = _answered_asks.popitem(last=False)


def answered_ask(ask_id: str) -> dict[str, Any] | None:
    """The record of an ask THIS process sent and Jev answered, else None.

    Process-local on purpose: the ledger file is writable by anything with
    access to `<omh_home>`, so a row there proves nothing. A restart forgets
    every ask, which can only refuse a claim.
    """
    wanted = str(ask_id or "").strip()
    if not wanted:
        return None
    with _answered_lock:
        record = _answered_asks.get(wanted)
        return dict(record) if record is not None else None


def forget_answered_asks() -> None:
    """Test seam: forget every answered ask."""
    with _answered_lock:
        _answered_asks.clear()


def ledger_summary(omh_home: Path) -> dict[str, Any]:
    records = read_ledger_records(omh_home)
    return {
        "ledger_calls": len(records),
        "last_status": str(records[-1].get("status", "")) if records else "",
    }


def _ledger_lines(path: Path) -> list[str]:
    try:
        if path.is_symlink() or not path.is_file():
            return []
        with path.open("rb") as handle:
            raw = handle.read(MAX_LEDGER_BYTES + 1)
    except OSError:
        return []
    return _ledger_text_lines(raw)


def _ledger_lines_at(dir_fd: int, name: str) -> list[str]:
    """`_ledger_lines` for ``name`` under ``dir_fd``; a link or non-file reads as empty."""
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | _CLOEXEC, dir_fd=dir_fd)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return []
            raw = handle.read(MAX_LEDGER_BYTES + 1)
    except OSError:
        return []
    return _ledger_text_lines(raw)


def _ledger_text_lines(raw: bytes) -> list[str]:
    text = raw[-MAX_LEDGER_BYTES:].decode("utf-8", errors="replace")
    return [line for line in text.splitlines() if line.strip().startswith("{")]


__all__ = [
    "KeyUnresolvable",
    "LEDGER_SCHEMA_VERSION",
    "LOCAL_HTTP_SETTING_KEY",
    "OPENROUTER_SETTING_KEY",
    "ROUTE_KEY_NAMES",
    "ROUTE_NONE",
    "ROUTE_OPENROUTER",
    "ROUTE_TYPESAFE",
    "TYPESAFE_MODEL_SETTING_KEY",
    "answered_ask",
    "append_ledger_record",
    "forget_answered_asks",
    "ledger_path",
    "ledger_summary",
    "local_http_endpoint_enabled",
    "openrouter_route_enabled",
    "operator_typesafe_model",
    "read_key",
    "read_ledger_records",
    "remember_answered_ask",
    "resolve_route",
    "route_available",
    "route_available_by_names",
    "settings_path",
]
