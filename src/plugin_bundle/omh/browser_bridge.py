"""Explicit browser host binding. No browser imports or IO on unrelated calls."""
from __future__ import annotations

from . import runtime_paths

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
from time import time

MUTATION_INTERCEPTION = "none"  # Hermes tool hooks are not last-mile interception.


def _host_identity():
    """Require task-local host identity AND both host schema-cache bypasses.

    Never use get_session_env: its environment fallback can alias requests.
    These installed-Hermes ContextVars are a versioned integration boundary;
    hosts without them or request-bound definition caching remain unavailable.
    """
    try:
        from gateway import session_context
        from tools.registry import CHECK_FN_CACHE_BYPASS, check_fn_cache_scope, no_cache_check_fn

        identity = tuple(getattr(session_context, name).get() for name in (
            "_SESSION_ID", "_BROWSER_CONTROL_PRINCIPAL",
            "_BROWSER_CONTROL_TRANSPORT_FAMILY", "_SESSION_MESSAGE_ID"))
        if (callable(no_cache_check_fn)
                and all(isinstance(value, str) and 0 < len(value) <= 256 for value in identity)
                and check_fn_cache_scope() == CHECK_FN_CACHE_BYPASS):
            return identity
    except (ImportError, AttributeError):
        return None  # Unsupported host API, not an availability success.
    return None


@dataclass
class _Admission:
    identity: tuple[str, ...]
    task: str
    expires_at: float
    active: bool = True  # Shared revocation reaches copy_context worker threads.


def register(ctx, config):
    # An adapter is a trusted host-supplied object, never reconstructed from
    # model arguments, import paths, configuration code, or executable names.
    adapter = getattr(ctx, "browser_adapter", None)
    effects_enabled = (config.get("effects_enabled") is True
                       and callable(getattr(ctx, "browser_effect_approval", None))
                       and all(callable(getattr(adapter, name, None)) for name in ("preview", "resume", "abort")))
    home, _ = runtime_paths.resolve_homes(config.get("omh_home"))
    manager = None
    admission: ContextVar[_Admission | None] = ContextVar("omh_browser_admission", default=None)

    @contextmanager
    def browser_task(task, *, ttl_seconds=300):
        """Trusted wrapper entry, BEFORE assembling schemas for an explicit task.

        This is not a model tool. The host binds its current request first and
        keeps this scope around execution; exiting revokes even copied contexts
        and reaps this owner's leases through this registration's adapter only.
        """
        from omh.workflows.browser_adapter import BrowserContractError, number, text

        identity = _host_identity()
        if identity is None:
            raise BrowserContractError("host_scope_unavailable")
        admitted = _Admission(identity, text(task, 256), time() + number(ttl_seconds, 300))
        token = admission.set(admitted)
        try:
            yield
        finally:
            admitted.active = False
            admission.reset(token)
            if manager is not None:
                if any(not result.get("reaped") for result in manager.cleanup(identity[0])):
                    raise BrowserContractError("cleanup_unknown")

    def available() -> _Admission | None:
        current = admission.get()
        if (adapter is not None and current is not None and current.active
                and time() < current.expires_at and _host_identity() == current.identity):
            return current
        return None

    def get_manager():
        nonlocal manager
        if manager is None:
            from omh.workflows.browser_lease_store import BrowserLeaseStore, BrowserSessionManager
            manager = BrowserSessionManager(BrowserLeaseStore(home), adapter)
        return manager

    def pre_tool_call(**kwargs):
        name = kwargs.get("tool_name")
        if not isinstance(name, str) or not name.startswith("browser_"):
            return None
        # Native browser tools cannot consume this lease or guarantee revision
        # checks. No implicit allowance based on GET, tool names, or same origin.
        return {"action": "block", "message": "browser_adapter: adapter_cannot_intercept; use the bound omh_browser lifecycle"}

    def handler(args, **kwargs):
        current = available()
        if current is None:
            return json.dumps({"status": "blocked", "reason": "admission_required"})
        operations = {"acquire", "act", "observe", "release"}
        if effects_enabled:
            operations |= {"effect_preview", "effect_execute", "effect_abort"}
        if not isinstance(args, dict) or not isinstance(args.get("operation"), str) or args["operation"] not in operations:
            return json.dumps({"status": "blocked", "reason": "invalid_operation"})
        owner = current.identity[0]
        if kwargs.get("session_id", owner) != owner:
            return json.dumps({"status": "blocked", "reason": "foreign_owner"})
        if args["operation"] == "acquire" and args.get("task") != current.task:
            return json.dumps({"status": "blocked", "reason": "foreign_task"})
        from omh.workflows.browser_adapter import BrowserContractError

        try:
            lifecycle = get_manager()
            if args["operation"].startswith("effect_"):
                from .browser_effects_bridge import handle

                result = handle(ctx, lifecycle, current, available, args)
            elif args["operation"] == "acquire":
                result = lifecycle.acquire(owner, args)
            elif args["operation"] == "release":
                result = lifecycle.release(owner, args.get("lease_id"))
            else:
                result = lifecycle.operate(owner, args)
        except BrowserContractError as exc:
            result = {"status": "blocked", "reason": str(exc)}
        return json.dumps(result, sort_keys=True)

    def on_session_end(**kwargs):
        identity = _host_identity()
        owner = kwargs.get("session_id")
        if adapter is None or identity is None or identity[0] != owner:
            return None
        current = admission.get()
        if current is not None and current.identity[0] == owner:
            current.active = False
        return get_manager().cleanup(owner)

    schema = {"name": "omh_browser", "description": "Explicit bounded host browser lease and semantic read lifecycle.",
              "parameters": {"type": "object", "required": ["operation"], "properties": {
                  "operation": {"type": "string", "enum": ["acquire", "observe", "act", "release"]},
                  "task": {"type": "string", "maxLength": 256},
                  "auth_boundary": {"type": "string", "maxLength": 256},
                  "origins": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                  "actions": {"type": "array", "items": {"type": "string"}},
                  "mode": {"type": "string", "enum": ["headless", "headed", "attached"]},
                  "lease_id": {"type": "string"}, "tab_id": {"type": "string"},
                  "revision": {"type": "integer"}, "handle": {"type": "string"},
                  "role": {"type": "string"}, "name": {"type": "string", "maxLength": 2048},
                  "action": {"type": "string", "enum": ["read"]}}}}
    if effects_enabled:
        from .browser_effects_bridge import extend_schema

        extend_schema(schema)
    # True is possible only with Hermes' request-bound bypass of BOTH caches.
    # Also bypass the registry's TTL/last-good cache on inactive probes.
    try:
        from tools.registry import no_cache_check_fn
    except ImportError:
        check = lambda: False
    else:
        check = no_cache_check_fn(available)
    ctx.register_tool("omh_browser", "omh", schema, handler, check_fn=check,
                      description=schema["description"])
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("on_session_end", on_session_end)
    return browser_task
