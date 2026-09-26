"""Deterministic host double; callbacks retain their real lifecycle semantics."""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from threading import Event
from types import SimpleNamespace

from _local_package import load_local_package

load_local_package()

from omh.workflows.browser_adapter import RawCapabilities
from _module_patch import patch_modules


class HostContext:
    def __init__(self, home, adapter=None, enabled=True):
        self.home = home
        self.browser_adapter = adapter
        self.enabled = enabled
        self.tools = {}
        self.checks = {}
        self.hooks = {}

    def get_config(self, key, default=None):
        if key == "browser_adapter":
            return {"enabled": self.enabled, "omh_home": str(self.home)}
        return default

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = handler
        self.checks[name] = kwargs.get("check_fn", lambda: True)

    def register_hook(self, name, handler):
        self.hooks.setdefault(name, []).append(handler)


@contextmanager
def host_session(owner="owner", message="request", principal="principal"):
    """Only the host identity/cache API is doubled; lease IO/callbacks are real."""
    session = SimpleNamespace(**{name: ContextVar(name, default=None) for name in (
        "_SESSION_ID", "_SESSION_MESSAGE_ID", "_BROWSER_CONTROL_PRINCIPAL",
        "_BROWSER_CONTROL_TRANSPORT_FAMILY")})
    session._SESSION_ID.set(owner)
    session._SESSION_MESSAGE_ID.set(message)
    session._BROWSER_CONTROL_PRINCIPAL.set(principal)
    session._BROWSER_CONTROL_TRANSPORT_FAMILY.set("local-api")
    registry = SimpleNamespace(CHECK_FN_CACHE_BYPASS="", check_fn_cache_scope=lambda: "",
                               no_cache_check_fn=lambda fn: fn)
    with patch_modules({"gateway": SimpleNamespace(session_context=session),
                                   "gateway.session_context": session,
                                   "tools.registry": registry}):
        yield session


class Adapter:
    adapter_id = "fixture"
    adapter_version = "1"

    def __init__(self):
        self.calls = Counter()
        self.live = set()
        self.entered: Event | None = None
        self.proceed: Event | None = None
        self.crash = False
        self.revision = 1
        self.readback = True
        self.elements = [{"role": "button", "name": "PRIVATE LABEL", "key": "one"}]
        self.cap: RawCapabilities = {
            "schema_version": "browser_adapter_capabilities/v1",
            "modes": ["headless"], "channels": ["semantic_state", "screenshot"],
            "mutation_interception": "none", "unsupported": ["upload"],
            "limits": {"leases": 2, "tabs": 1, "actions": 4, "ttl_seconds": 60,
                       "capability_seconds": 30, "elements": 8, "state_bytes": 4096},
        }

    def capabilities(self):
        self.calls["capabilities"] += 1
        return deepcopy(self.cap)

    def start(self, lease_id, scope, deadline, /):
        self.calls["start"] += 1
        self.live.add(lease_id)
        if self.entered:
            assert self.proceed is not None
            self.entered.set()
            if not self.proceed.wait(5):
                raise TimeoutError("fixture barrier timed out")
        if self.crash:
            raise RuntimeError("host crash")
        return {"tabs": ["tab-1"]}

    def observe(self, lease_id, tab_id, deadline):
        self.calls["observe"] += 1
        return {"url": "http://localhost/page?secret=PRIVATE", "revision": self.revision,
                "readback": self.readback, "elements": deepcopy(self.elements),
                "cookies": "PRIVATE COOKIE", "dom": "PRIVATE DOM"}

    def act(self, lease_id, tab_id, revision, key, operation, deadline, /):
        self.calls["act"] += 1
        if revision != self.revision:
            return {"status": "stale_state"}
        self.revision += 1
        return {"status": "observed"}

    def release(self, lease_id, deadline, /):
        self.calls["release"] += 1
        self.live.discard(lease_id)
        return {"reaped": True}


def request(**updates):
    value = {"operation": "acquire", "task": "task", "auth_boundary": "opaque-auth",
             "origins": ["http://localhost"], "actions": ["read"], "mode": "headless"}
    value.update(updates)
    return value
