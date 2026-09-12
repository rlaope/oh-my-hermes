"""Native Hermes registry egress guard.

Only a configured registry target is covered.  This module deliberately does
not import SQLite: it is imported only after the real final arguments reach a
registered wrapper.
"""

from __future__ import annotations

from . import runtime_paths

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

PRIVATE_TOKEN = "__omh_egress_attempt_token"
MAX_LIVE_CALLS = 512
MAX_FINAL_ARGUMENT_BYTES = 262_144
_ACTIONS = frozenset({"message_send", "review_submit", "ci_dispatch", "merge", "external_write"})
_DESTINATIONS = frozenset({"chat_channel", "repository", "review_thread", "workflow", "endpoint"})


def _canonical(value: object) -> bytes:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_FINAL_ARGUMENT_BYTES:
        raise ValueError("final arguments exceed the configured egress bound")
    return encoded


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or not value.replace("_", "a").isalnum():
        raise ValueError(f"{label} must be a top-level argument name")
    return value


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    action_class: str
    destination_class: str
    destination_arg: str
    payload_arg: str


@dataclass(slots=True)
class LiveCall:
    """Mutable phase of one authenticated host invocation."""
    target: Target
    session_id: str
    tool_call_id: str
    wrapper: Callable
    phase: str = "armed"
    attempt_id: str = ""


def _parse_config(raw: object) -> tuple[dict[str, Target], dict[str, str], str]:
    """Return valid targets, target-specific blocks, and an optional global block."""
    if not isinstance(raw, dict):
        return {}, {}, "enabled egress configuration is invalid"
    tools = raw.get("tools")
    if not isinstance(tools, dict) or not tools:
        return {}, {}, "enabled egress configuration is invalid"
    targets: dict[str, Target] = {}
    invalid: dict[str, str] = {}
    for tool_name, entry in tools.items():
        if not isinstance(tool_name, str) or not tool_name or len(tool_name) > 64:
            return {}, {}, "enabled egress configuration contains an invalid tool name"
        try:
            if not isinstance(entry, dict) or set(entry) != {"action_class", "destination_class", "destination_arg", "payload_arg"}:
                raise ValueError("target is not an object")
            target = Target(
                name=tool_name,
                action_class=str(entry["action_class"]),
                destination_class=str(entry["destination_class"]),
                destination_arg=_name(entry["destination_arg"], "destination_arg"),
                payload_arg=_name(entry["payload_arg"], "payload_arg"),
            )
            if target.action_class not in _ACTIONS or target.destination_class not in _DESTINATIONS:
                raise ValueError("classification is unsupported")
            targets[tool_name] = target
        except (KeyError, TypeError, ValueError):
            invalid[tool_name] = "configured egress target is invalid"
    return targets, invalid, ""


class Guard:
    """One registration's bounded token map; live calls are never evicted."""

    def __init__(self, home: Path, targets: dict[str, Target], invalid: dict[str, str], global_error: str,
                 entry_for: Callable[[str], object | None]) -> None:
        self.home = home.resolve()
        self.targets = targets
        self.invalid = invalid
        self.global_error = global_error
        self.entry_for = entry_for
        self.wrappers: dict[str, Callable] = {}
        self.live: dict[str, LiveCall] = {}
        self.by_call: dict[tuple[str, str, str], str] = {}
        self.lock = threading.Lock()

    def pre(self, *, tool_name: str = "", session_id: str = "", tool_call_id: str = "", **_: object):
        if self.global_error:
            return {"action": "block", "message": "BLOCKED: " + self.global_error}
        if tool_name in self.invalid:
            return {"action": "block", "message": "BLOCKED: " + self.invalid[tool_name]}
        target = self.targets.get(tool_name)
        if target is None:
            return None
        wrapper = self.wrappers.get(tool_name)
        entry = self.entry_for(tool_name)
        if wrapper is None or entry is None or getattr(entry, "handler", None) is not wrapper:
            return {"action": "block", "message": "BLOCKED: configured egress wrapper is inactive"}
        if not isinstance(session_id, str) or not session_id or not isinstance(tool_call_id, str) or not tool_call_id:
            return {"action": "block", "message": "BLOCKED: egress host session and tool-call identity are required"}
        with self.lock:
            call_key = (session_id, tool_call_id, tool_name)
            if call_key in self.by_call:
                return {"action": "block", "message": "BLOCKED: egress call is already in flight"}
            if len(self.live) >= MAX_LIVE_CALLS:
                return {"action": "block", "message": "BLOCKED: egress correlation capacity is exhausted"}
            token = secrets.token_urlsafe(32)
            self.live[token] = LiveCall(target, session_id, tool_call_id, wrapper)
            self.by_call[call_key] = token
        return {"action": "modify", "args": {PRIVATE_TOKEN: token}}

    def before_handler(self, tool_name: str, args: object, handler_kwargs: dict[str, object]):
        if not isinstance(args, dict):
            return None, None, "BLOCKED: final egress arguments are invalid"
        token = args.get(PRIVATE_TOKEN)
        if not isinstance(token, str):
            return None, None, "BLOCKED: final egress correlation identity is invalid"
        with self.lock:
            live = self.live.get(token)
            if (
                live is None or live.target.name != tool_name
                or live.wrapper is not self.wrappers.get(tool_name)
                or live.phase != "armed"
                or handler_kwargs.get("session_id") != live.session_id
            ):
                return None, None, "BLOCKED: final egress correlation identity is invalid"
            live.phase = "opening"
        forwarded = dict(args)
        forwarded.pop(PRIVATE_TOKEN, None)
        try:
            destination = forwarded[live.target.destination_arg]
            payload = forwarded[live.target.payload_arg]
            from .egress_attempt_receipts import AttemptStore
            opened = AttemptStore(self.home).open_attempt(
                session_id=live.session_id,
                tool_call_id=live.tool_call_id,
                tool_name=tool_name,
                action_class=live.target.action_class,
                destination_class=live.target.destination_class,
                request_fingerprint=_digest(forwarded),
                effect_id=_digest({"tool": tool_name, "request": forwarded}),
                destination_digest=_digest(destination),
                payload_digest=_digest(payload),
                payload_bytes=len(_canonical(payload)),
                # Model arguments are not an approval authority.  No invented
                # approval or idempotency reference is ever stored.
                approval_ref=None,
                idempotency_key=None,
            )
        except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
            with self.lock:
                self._discard(token)
            return None, None, f"BLOCKED: egress attempt was not durably recorded ({type(exc).__name__})"
        if opened["disposition"] != "created":
            with self.lock:
                self._discard(token)
            return None, None, "BLOCKED: egress attempt already exists; do not replay it"
        with self.lock:
            live.attempt_id = str(opened["attempt_id"])
            live.phase = "opened"
        return token, forwarded, None

    def post(self, *, tool_name: str = "", args: object = None, session_id: str = "", tool_call_id: str = "",
             status: str = "", **_: object) -> None:
        with self.lock:
            token = self.by_call.get((session_id, tool_call_id, tool_name))
            if token is None:
                return
            live = self.live.get(token)
            if (
                live is None or live.target.name != tool_name or live.session_id != session_id
                or live.tool_call_id != tool_call_id
            ):
                return
            if live.phase != "opened":
                self._discard(token)
                return
            live.phase = "terminal_pending"
            attempt_id = live.attempt_id
        terminal = {"blocked": "blocked", "cancelled": "cancelled", "error": "error", "ok": "returned"}.get(status, "unknown")
        try:
            from .egress_attempt_receipts import AttemptStore
            AttemptStore(self.home).record_terminal(attempt_id, terminal)
        except (OSError, ValueError, RuntimeError):
            with self.lock:
                current = self.live.get(token)
                if current is live:
                    current.phase = "opened"
            return
        with self.lock:
            self._discard(token)


    def _discard(self, token: str) -> None:
        """Release correlation while the registration lock is held."""
        live = self.live.pop(token, None)
        if live is not None:
            self.by_call.pop((live.session_id, live.tool_call_id, live.target.name), None)


class RegistrationContext(Protocol):
    register_hook: Callable[..., object]
    register_tool: Callable[..., object]


def register(ctx: RegistrationContext, raw: object) -> None:
    """Install only after ``ctx.get_config(...).enabled`` selected this feature."""
    targets, invalid, global_error = _parse_config(raw)
    home, _ = runtime_paths.resolve_homes(raw.get("omh_home") if isinstance(raw, dict) else None)
    from tools.registry import registry
    scope = getattr(getattr(ctx, "_manager", None), "scope_key", None)
    guard = Guard(home, targets, invalid, global_error, lambda name: registry.get_entry(name, scope=scope))
    ctx.register_hook("pre_tool_call", guard.pre)
    ctx.register_hook("post_tool_call", guard.post)
    for name in tuple(targets):
        original = registry.get_entry(name, scope=scope)
        if original is None or original.max_result_size_chars is not None or original.dynamic_schema_overrides is not None:
            guard.invalid[name] = "configured egress wrapper cannot preserve target metadata"
            continue
        def sync(args, _name=name, _original=original, **kwargs):
            _, forwarded, error = guard.before_handler(_name, args, kwargs)
            return json.dumps({"error": error}) if error else _original.handler(forwarded, **kwargs)
        async def asynchronous(args, _name=name, _original=original, **kwargs):
            _, forwarded, error = guard.before_handler(_name, args, kwargs)
            return json.dumps({"error": error}) if error else await _original.handler(forwarded, **kwargs)
        wrapper = asynchronous if original.is_async else sync
        guard.wrappers[name] = wrapper
        try:
            ctx.register_tool(
                name, original.toolset, original.schema, wrapper, check_fn=original.check_fn,
                requires_env=original.requires_env, is_async=original.is_async,
                description=original.description, emoji=original.emoji, override=True,
            )
        except (PermissionError, RuntimeError, TypeError, ValueError):
            # Do not roll the hook back: the configured target remains blocked.
            guard.invalid[name] = "configured egress wrapper is inactive"
