"""Normal-loop Kanban observation bridge; no native executor or grant API.

The host registry is schema availability, NOT session authorization. Hermes
still selects/exposes tools, enforces worker/child guards and asks the user.
Only a correlated normal-loop pre/post pair can create an OMH receipt.
"""
from __future__ import annotations

from . import runtime_paths

from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import re
import secrets
import stat
from threading import RLock
from typing import Protocol, TypeGuard, runtime_checkable

from omh.system.descriptor_lock import DescriptorLockError, locked_descriptor
from omh.workflows.agent_board import (
    AgentBoard, AgentBoardRequest, HostIdentity, MAX_INTAKE_BYTES, board_reference, native_schema_supported,
)

from .runtime_reader import default_omh_home


class BoardStoreError(ValueError):
    """Closed safe error: unavailable storage must never reopen an action."""


@dataclass(frozen=True)
class _Pending:
    board: str
    request_id: str


class AgentBoardBridge:
    """Atomic bounded metadata transactions shared by OMH-origin processes.

    The short OS lock covers load/check/reserve/save, never a native call. A
    durable in-flight marker serializes creates even after process death. No
    waiting queue, automatic retry, timeout expiry or implicit resume exists.
    """

    def __init__(self, home: Path, *, root_identity: str | None) -> None:
        self.home: Path = home.expanduser().resolve()
        self.root_identity: str | None = root_identity
        self._pending: dict[str, _Pending] = {}
        self._lock: RLock = RLock()

    def _board(self, board: str) -> AgentBoard:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", board):
            raise ValueError("invalid_board_slug")
        return AgentBoard(board, board_reference(self.root_identity or "unattributable", board))

    def _path(self, board: AgentBoard) -> Path:
        return self.home / "runtime" / "agent-board" / (board.board_ref[7:] + ".json")

    @contextmanager
    def _transaction(self, board: str, *, write: bool = True) -> Generator[AgentBoard, None, None]:
        state = self._board(board)
        path = self._path(state)
        if not write and not path.exists():
            yield state
            return
        try:
            parent = self.home
            for part in ("runtime", "agent-board"):
                parent = parent / part
                parent.mkdir(mode=0o700, exist_ok=True, parents=True)
                if parent.is_symlink() or not parent.is_dir():
                    raise BoardStoreError("unsafe_board_store")
            lock_path = path.with_suffix(".lock")
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            if lock_path.is_symlink() or path.is_symlink():
                raise BoardStoreError("unsafe_board_store")
            descriptor = os.open(lock_path, flags, 0o600)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise BoardStoreError("unsafe_board_store")
                with self._lock, locked_descriptor(descriptor, lock_path):
                    if path.exists():
                        read_fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                        with os.fdopen(read_fd, "rb") as handle:
                            info = os.fstat(handle.fileno())
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                raise BoardStoreError("unsafe_board_store")
                            raw = handle.read(MAX_INTAKE_BYTES + 1)
                        if len(raw) > MAX_INTAKE_BYTES:
                            raise BoardStoreError("board_store_limit")
                        state = AgentBoard.restore(board, state.board_ref, raw.decode("utf-8"))
                    yield state
                    if write:
                        self._save(path, state)
            finally:
                os.close(descriptor)
        except (OSError, UnicodeError, DescriptorLockError) as error:
            raise BoardStoreError("board_store_unavailable") from error

    def _save(self, path: Path, state: AgentBoard) -> None:
        encoded = json.dumps(state.snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_INTAKE_BYTES:
            raise BoardStoreError("board_store_limit")
        temporary = path.with_suffix("." + secrets.token_hex(16) + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                _ = handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def prepare(self, payload: Mapping[str, object], *, host: HostIdentity | None,
                schemas: Mapping[str, object], hooks: frozenset[str]) -> AgentBoardRequest:
        board = payload.get("board")
        if not isinstance(board, str):
            raise ValueError("board_required")
        if self.root_identity is None:
            return self._board(board).prepare(payload, host=host, schemas=schemas, hooks=hooks)
        with self._transaction(board) as state:
            result = state.prepare(payload, host=host, schemas=schemas, hooks=hooks, board_is_safe=True)
        return result

    def status(self, board: str, request_id: str) -> AgentBoardRequest:
        with self._transaction(board, write=False) as state:
            return state.status(request_id)

    def pre(self, *, host: HostIdentity | None, tool_name: str, arguments: Mapping[str, object],
            schemas: Mapping[str, object], hooks: frozenset[str]) -> dict[str, object] | None:
        board = arguments.get("board")
        if not isinstance(board, str) or not tool_name.startswith("kanban_"):
            return None
        state = self._board(board)
        if not self._path(state).exists():
            return None
        with self._transaction(board) as state:
            matches = state.matching_requests(host=host, tool_name=tool_name, arguments=arguments)
            if not matches:
                return None
            if (self.root_identity is None or host is None
                    or not native_schema_supported(schemas.get(tool_name), {"tool_name": tool_name, "arguments": dict(arguments)})
                    or not {"pre_tool_call", "post_tool_call"} <= hooks):
                return {"action": "block", "message": "OMH board capability unavailable; action not admitted."}
            if len(matches) != 1 or not state.begin(matches[0], host=host, tool_name=tool_name, arguments=arguments):
                return {"action": "block", "message": "OMH board action refused: stale, foreign, replayed or reconciliation required."}
            pending = _Pending(board, matches[0])
        # A failed save must never arm this process or permit native dispatch.
        with self._lock:
            self._pending[host.call_ref] = pending
        return None

    def post(self, *, host: HostIdentity, tool_name: str, arguments: Mapping[str, object],
             result: object, binding_is_safe: bool = True) -> dict[str, object] | None:
        with self._lock:
            pending = self._pending.pop(host.call_ref, None)
        if pending is None:
            return None
        with self._transaction(pending.board) as state:
            receipt = state.observe(pending.request_id, host=host, tool_name=tool_name,
                                    arguments=arguments, result=result, binding_is_safe=binding_is_safe)
        return receipt


def _dict(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _object(value: object) -> TypeGuard[dict[str, object]]:
    return _dict(value) and all(isinstance(key, str) for key in value)


@runtime_checkable
class _Registry(Protocol):
    def get_definitions(self, tool_names: set[str], quiet: bool = False) -> list[dict[str, object]]: ...


@runtime_checkable
class _Lifecycle(Protocol):
    def has_hook(self, hook_name: str) -> bool: ...


@runtime_checkable
class _BoardPaths(Protocol):
    def kanban_home(self) -> Path: ...
    def kanban_db_path(self, board: str) -> Path: ...


def host_capabilities() -> tuple[dict[str, object], frozenset[str]]:
    """Probe current host registry scope, never private agent/session globals.

    These are available schemas, not an authenticated session grant. The
    normal Hermes loop remains the only authority that may invoke an action.
    """
    try:
        registry: object = getattr(import_module("tools.registry"), "registry", None)
        lifecycle = import_module("hermes_cli.lifecycle")
    except ModuleNotFoundError as error:
        if error.name in {"tools", "tools.registry", "hermes_cli", "hermes_cli.lifecycle"}:
            return {}, frozenset()
        raise
    if not isinstance(registry, _Registry) or not isinstance(lifecycle, _Lifecycle):
        return {}, frozenset()
    names = {"kanban_" + operation for operation in (
        "create", "link", "comment", "heartbeat", "request_review", "request_changes", "block",
        "unblock", "complete", "show", "list", "attachments")}
    names.add("delegate_task")
    schemas: dict[str, object] = {}
    for definition in registry.get_definitions(names, quiet=True):
        function = definition.get("function")
        if _object(function) and isinstance(function.get("name"), str):
            schemas[str(function["name"])] = definition
    hooks = frozenset(name for name in ("pre_tool_call", "post_tool_call") if lifecycle.has_hook(name))
    return schemas, hooks


def effective_root(board: str) -> str | None:
    """Resolve path identity only. Never open native DB, profile or board data."""
    if os.environ.get("HERMES_KANBAN_DB", "").strip():
        return None
    try:
        paths = import_module("hermes_cli.kanban_db")
    except ModuleNotFoundError as error:
        if error.name in {"hermes_cli", "hermes_cli.kanban_db"}:
            return None
        raise
    if not isinstance(paths, _BoardPaths) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", board):
        return None
    root = paths.kanban_home().expanduser().resolve()
    expected = root / "kanban.db" if board == "default" else root / "kanban" / "boards" / board / "kanban.db"
    if paths.kanban_db_path(board).expanduser().resolve() != expected:
        return None
    return str(root)


@dataclass(frozen=True)
class _PrepareCall:
    host: HostIdentity
    digest: str


# Hermes fires pre_tool_call on a bounded hook worker thread and then runs the
# handler on the caller's thread, so a ContextVar cannot carry the pre to the
# handler. This process-local registry is keyed by the host's own session/task
# identity; each entry is consumed exactly once by the matching handler call.
_PREPARE_CALLS: dict[tuple[Path, str, str], _PrepareCall] = {}
_PREPARE_CALLS_LOCK = RLock()
_MAX_PREPARE_CALLS = 64
_BRIDGES: dict[tuple[Path, Path, str | None], AgentBoardBridge] = {}
_BRIDGES_LOCK = RLock()


def _arm_prepare_call(host: HostIdentity, digest: str) -> None:
    key = (runtime_paths.default_hermes_home(), host.session_id, host.task_id)
    with _PREPARE_CALLS_LOCK:
        _ = _PREPARE_CALLS.pop(key, None)
        if len(_PREPARE_CALLS) >= _MAX_PREPARE_CALLS:
            # Bounded: drop the oldest armed pre rather than grow without limit.
            _ = _PREPARE_CALLS.pop(next(iter(_PREPARE_CALLS)))
        _PREPARE_CALLS[key] = _PrepareCall(host, digest)


def _disarm_prepare_call(host: HostIdentity | None) -> None:
    if host is None:
        return
    with _PREPARE_CALLS_LOCK:
        _ = _PREPARE_CALLS.pop((runtime_paths.default_hermes_home(), host.session_id, host.task_id), None)


def _input_digest(arguments: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(dict(arguments), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _host(kwargs: Mapping[str, object]) -> HostIdentity | None:
    values = [kwargs.get(key) for key in ("session_id", "task_id", "tool_call_id")]
    if not all(isinstance(value, str) for value in values):
        return None
    try:
        return HostIdentity(str(values[0]), str(values[1]), str(values[2]))
    except ValueError:
        return None


def handler_identity(args: Mapping[str, object], kwargs: Mapping[str, object]) -> HostIdentity | None:
    """Consume the exact pre of this handler, including Hermes' omitted call ID."""
    session_id, task_id = kwargs.get("session_id"), kwargs.get("task_id")
    if not isinstance(session_id, str) or not isinstance(task_id, str):
        return None
    with _PREPARE_CALLS_LOCK:
        pending = _PREPARE_CALLS.pop((runtime_paths.default_hermes_home(), session_id, task_id), None)
    if pending is None or pending.digest != _input_digest(args):
        return None
    return pending.host


def installed_bridge(board: str) -> AgentBoardBridge:
    root = effective_root(board)
    home = default_omh_home().expanduser().resolve()
    key = (runtime_paths.default_hermes_home(), home, root)
    with _BRIDGES_LOCK:
        bridge = _BRIDGES.get(key)
        if bridge is None:
            bridge = AgentBoardBridge(home, root_identity=root)
            _BRIDGES[key] = bridge
        return bridge


class _JsonDecoder(Protocol):
    def loads(self, s: str) -> object: ...


_decoder: _JsonDecoder = json


def _stored_boards(home: Path) -> Iterator[AgentBoard]:
    directory = home / "runtime" / "agent-board"
    if directory.is_symlink() or directory.parent.is_symlink():
        raise BoardStoreError("unsafe_board_store")
    for index, path in enumerate(directory.glob("*.json")):
        if index >= 200 or path.is_symlink():
            raise BoardStoreError("board_store_limit")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BoardStoreError("unsafe_board_store")
            raw = handle.read(MAX_INTAKE_BYTES + 1)
        if len(raw) > MAX_INTAKE_BYTES:
            raise BoardStoreError("board_store_limit")
        data = _decoder.loads(raw.decode("utf-8"))
        if not _object(data) or not isinstance(data.get("board"), str) or not isinstance(data.get("board_ref"), str):
            raise BoardStoreError("invalid_board_store")
        board, ref = str(data["board"]), str(data["board_ref"])
        if path.name != ref[7:] + ".json":
            raise BoardStoreError("invalid_board_store")
        yield AgentBoard.restore(board, ref, raw.decode("utf-8"))


def installed_status(request_id: str) -> AgentBoardRequest:
    """Resolve a unique request in bounded OMH metadata after a plugin restart."""
    home = default_omh_home().expanduser().resolve()
    results: list[AgentBoardRequest] = []
    for state in _stored_boards(home):
        root = effective_root(state.board)
        if root is None or board_reference(root, state.board) != state.board_ref:
            continue
        result = state.status(request_id)
        if result["reason"] != "request_not_found":
            results.append(result)
    if len(results) != 1:
        raise BoardStoreError("request_missing_or_ambiguous")
    return results[0]


def pre_agent_board(kwargs: Mapping[str, object]) -> dict[str, object] | None:
    tool_name = kwargs.get("tool_name")
    args = kwargs.get("args", kwargs.get("tool_input"))
    identity = _host(kwargs)
    if tool_name == "omh_agent_board":
        _disarm_prepare_call(identity)
        if identity is not None and _object(args):
            _arm_prepare_call(identity, _input_digest(args))
        return None
    if not isinstance(tool_name, str) or not tool_name.startswith("kanban_") or not _object(args):
        return None
    board = args.get("board")
    if not isinstance(board, str):
        return None
    try:
        bridge = installed_bridge(board)
        for state in _stored_boards(bridge.home):
            if (state.matching_requests(host=identity, tool_name=tool_name, arguments=args)
                    and (state.board != board or bridge.root_identity is None
                         or state.board_ref != board_reference(bridge.root_identity, board))):
                return {"action": "block", "message": "OMH board binding changed or unavailable; tracked action refused."}
        # OMH always prepares canonical explicit slugs. Leave normalization of
        # unrelated native calls to Hermes instead of narrowing its interface.
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", board):
            return None
        schemas, hooks = host_capabilities()
        return bridge.pre(host=identity, tool_name=tool_name, arguments=args, schemas=schemas, hooks=hooks)
    except (ValueError, OSError, DescriptorLockError):
        return {"action": "block", "message": "OMH board correlation unavailable; no tracked action admitted."}


def post_agent_board(kwargs: Mapping[str, object]) -> None:
    identity = _host(kwargs)
    tool_name = kwargs.get("tool_name")
    args = kwargs.get("args", kwargs.get("tool_input"))
    if tool_name == "omh_agent_board":
        _disarm_prepare_call(identity)
    if identity is None or not isinstance(tool_name, str) or not _object(args):
        return
    # Search only this process's exact armed call, not caller-chosen board paths.
    with _BRIDGES_LOCK:
        bridges = list(_BRIDGES.values())
    board = args.get("board")
    root = effective_root(board) if isinstance(board, str) else None
    for bridge in bridges:
        _ = bridge.post(host=identity, tool_name=tool_name, arguments=args, result=kwargs.get("result"),
                        binding_is_safe=root is not None and root == bridge.root_identity)
