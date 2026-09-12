"""Adapter for Hermes on_room_member_activity, not a room-terminal contract."""
from __future__ import annotations

from . import runtime_paths

from collections.abc import Callable
from datetime import datetime, timezone
import json
import secrets
from typing import Protocol, runtime_checkable

from omh.system.local_store import atomic_write_json, atomic_write_text, file_lock
from omh.system.paths import OmhPaths
from .activity_observer import ActivityObserver, ObserverStatus
from .activity_observer_events import EventError, opaque_ref
from .activity_observer_state import JSON
from .group_activity_status import Status, profile_slot, status_path

HOOK = "on_room_member_activity"
KINDS = frozenset({"tool.started", "tool.completed", "tool.output_risk", "request.opened",
                   "message.delta", "message.interim", "reasoning.delta", "turn.error"})
COORDINATES = ("room_id", "thread_id", "member_id", "turn_id", "task_id")


class Registration(Protocol):
    def dispose(self) -> None: ...


@runtime_checkable
class ObserverHost(Protocol):
    def get_config(self, key: str, default: JSON = None) -> JSON: ...
    def register_hook(self, name: str, callback: Callable[..., None]) -> Registration: ...
    def on_unload(self, callback: Callable[[], None]) -> Registration: ...


class NativeObserver:
    """Profile-owned adapter; raw payloads never leave the callback stack."""
    def __init__(self, paths: OmhPaths, key: bytes) -> None:
        self.paths, self.key = paths, key
        self.accepting = True
        self.registration: Registration | None = None
        self._generations: dict[str, int] = {}  # Mutated only by the host's per-consumer callback worker.
        self.engine = ActivityObserver(paths, opaque_ref(key, "profile"), on_status=self._publish_status)

    def observe(self, *, payload: JSON = None, **metadata: JSON) -> None:
        del payload  # Do not inspect, hash, log, retain, or forward native content.
        if not self.accepting:
            return
        try:
            coordinates: dict[str, str] = {}
            for name in COORDINATES:
                value = metadata.get(name)
                if not isinstance(value, str) or not 1 <= len(value) <= 1024:
                    raise EventError("invalid_identity")
                coordinates[name] = value
            generation, sequence, kind = metadata.get("execution_generation"), metadata.get("seq"), metadata.get("kind")
            if not isinstance(generation, int) or isinstance(generation, bool) or not 0 <= generation <= 10**9:
                raise EventError("invalid_identity")
            if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= 10**9:
                raise EventError("invalid_sequence")
            if not isinstance(kind, str) or len(kind) > 32 or kind not in KINDS:
                raise EventError("unknown_kind")
            task = opaque_ref(self.key, json.dumps([coordinates[name] for name in COORDINATES], separators=(",", ":")))
            previous = self._generations.get(task)
            if previous is not None and generation < previous:
                raise EventError("stale_event")
            if previous is None and len(self._generations) >= 64:
                raise EventError("room_capacity")
            self._generations[task] = generation
            # Native sequence belongs to a hidden member session, not the whole room.
            scope = json.dumps([coordinates[name] for name in COORDINATES] + [generation], separators=(",", ":"))
            session = opaque_ref(self.key, "session:" + scope)
            event = {"schema": "omh_group_activity_event/v1", "profile_ref": self.engine.profile_ref,
                "session_ref": session, "room_ref": opaque_ref(self.key, "room:" + coordinates["room_id"]),
                "member_ref": opaque_ref(self.key, "member:" + coordinates["room_id"] + ":" + coordinates["member_id"]),
                "turn_ref": opaque_ref(self.key, "turn:" + scope),
                "kind": "tool_call" if kind == "tool.started" else "activity",
                "event_ref": opaque_ref(self.key, f"{session}:{sequence}:{kind}"), "sequence": sequence,
                "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            self.engine.enqueue(event)
        except (EventError, UnicodeError) as exc:
            self.engine.reject_event(exc.code if isinstance(exc, EventError) else "invalid_identity")

    def status(self) -> Status:
        status = self.engine.status()
        return {"readiness": "ready" if self.accepting else "stopped", "compatibility": "on_room_member_activity/v1",
                "dropped": status["dropped"], "gapped": status["gapped"], "rejected": status["rejected"],
                "write_failed": status["write_failed"], "last_outcome": status["last_outcome"]}

    def _publish_status(self, status: ObserverStatus) -> None:
        # Called by the engine worker only, including startup and shutdown.
        atomic_write_json(status_path(self.paths.omh_home, self.paths.hermes_home),
            {**status, "schema": "omh_group_activity_observer_status/v1",
             "readiness": "ready" if self.accepting else "stopped", "compatibility": "on_room_member_activity/v1"}, private=True)

    def close(self) -> None:
        self.accepting = False
        if self.registration is not None:
            self.registration.dispose()
        # Host-owned upstream queues cannot be drained through the plugin API.
        # Accepted OMH events drain; native completeness was never claimed.
        self.engine.close(timeout=1)


def register(ctx: ObserverHost) -> NativeObserver:
    """Create a private profile key at registration, never on dispatch."""
    # In a native host omh_home is the common profile setting, not a separate
    # programmatic override. Standalone adapter contexts retain their API.
    override = ctx.get_config("omh_home", None) if runtime_paths._host() is None else None
    omh_home, home = runtime_paths.resolve_homes(override)
    paths = OmhPaths(omh_home, home)
    key_path = paths.runtime_dir / "group-activity-keys" / f"{profile_slot(paths.hermes_home)}.key"
    with file_lock(key_path, private=True, timeout_seconds=1) as lock:
        if not lock["enforced"]:
            raise EventError("profile_key_lock_unavailable")
        try:
            with key_path.open("rb") as handle:
                encoded = handle.read(66)
            if len(encoded) != 65 or encoded[-1:] != b"\n":
                raise EventError("profile_key_invalid")
            key = bytes.fromhex(encoded[:64].decode("ascii"))
            if len(key) != 32:
                raise EventError("profile_key_invalid")
        except FileNotFoundError:
            key = secrets.token_bytes(32)
            atomic_write_text(key_path, key.hex() + "\n", private=True)
    observer = NativeObserver(paths, key)
    try:
        observer.registration = ctx.register_hook(HOOK, observer.observe)
        ctx.on_unload(observer.close)
    except (TypeError, ValueError):
        observer.close()
        raise
    return observer
