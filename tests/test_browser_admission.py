"""Request admission is host-only, uncached, revocable, and owner-bound."""
from contextlib import AbstractContextManager, ExitStack
from contextvars import copy_context
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _browser_adapter_support import Adapter, HostContext, host_session, request
from omh.plugin_bundle.omh import register
from _module_patch import patch_modules


class BrowserAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.home = Path(self.stack.enter_context(TemporaryDirectory())) / "omh"
        self.host = self.stack.enter_context(host_session())
        self.adapter = Adapter()
        self.ctx = HostContext(self.home, self.adapter)
        register(self.ctx)

    def call(self, args=None, **kwargs):
        return json.loads(self.ctx.tools["omh_browser"](request() if args is None else args, **kwargs))

    def admit(self, **kwargs):
        boundary = getattr(self.ctx, "browser_task", None)
        assert callable(boundary), "host-only explicit task admission missing"
        scope = boundary("task", **kwargs)
        assert isinstance(scope, AbstractContextManager)
        return scope

    def test_enabled_adapter_is_not_admission(self):
        self.assertFalse(self.ctx.checks["omh_browser"]())
        self.assertEqual(self.call()["reason"], "admission_required")
        self.assertFalse(self.adapter.calls)
        self.assertFalse(self.home.exists())

    def test_model_arguments_and_dispatch_owner_cannot_grant_admission(self):
        result = self.call(request(admitted=True, owner="owner", session_id="owner"), session_id="owner")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(self.adapter.calls)
        self.assertFalse(self.home.exists())

    def test_explicit_scope_exposes_and_reaps_then_revokes_copied_context(self):
        with self.admit():
            self.assertTrue(self.ctx.checks["omh_browser"]())
            lease = self.call()
            self.assertEqual(lease["status"], "active")
            copied = copy_context()
        self.assertFalse(self.adapter.live)
        self.assertFalse(self.ctx.checks["omh_browser"]())
        self.assertFalse(copied.run(self.ctx.checks["omh_browser"]))
        self.assertEqual(copied.run(self.call)["status"], "blocked")

    def test_current_request_owner_principal_and_task_are_revalidated(self):
        with self.admit():
            for variable in (self.host._SESSION_ID, self.host._SESSION_MESSAGE_ID,
                             self.host._BROWSER_CONTROL_PRINCIPAL,
                             self.host._BROWSER_CONTROL_TRANSPORT_FAMILY):
                token = variable.set("foreign")
                try:
                    self.assertFalse(self.ctx.checks["omh_browser"]())
                    self.assertEqual(self.call()["status"], "blocked")
                finally:
                    variable.reset(token)
            self.assertEqual(self.call(session_id="foreign")["status"], "blocked")
            self.assertEqual(self.call(request(task="unadmitted"))["status"], "blocked")
            self.assertFalse(self.adapter.calls)
            self.assertFalse(self.home.exists())

    def test_expired_admission_hides_schema_and_refuses_before_io(self):
        with patch("omh.plugin_bundle.omh.browser_bridge.time", return_value=1000) as clock:
            with self.admit(ttl_seconds=1):
                self.assertTrue(self.ctx.checks["omh_browser"]())
                clock.return_value = 1001
                self.assertFalse(self.ctx.checks["omh_browser"]())
                self.assertEqual(self.call()["status"], "blocked")
        self.assertFalse(self.adapter.calls)
        self.assertFalse(self.home.exists())

    def test_unsupported_host_scoping_fails_closed(self):
        import sys
        registry = sys.modules["tools.registry"]
        with patch.object(registry, "check_fn_cache_scope", return_value=None):
            with self.assertRaisesRegex(ValueError, "host_scope_unavailable"):
                with self.admit():
                    self.fail("unsupported host was admitted")
        self.assertFalse(self.adapter.calls)
        self.assertFalse(self.home.exists())

    def test_host_without_uncached_availability_api_cannot_admit(self):
        from types import SimpleNamespace
        unsupported = SimpleNamespace(CHECK_FN_CACHE_BYPASS="", check_fn_cache_scope=lambda: "")
        with patch_modules({"tools.registry": unsupported}):
            register(self.ctx)
            with self.assertRaisesRegex(ValueError, "host_scope_unavailable"):
                with self.admit():
                    self.fail("unsupported cache API was admitted")

    def test_session_end_revokes_admission_before_cleanup(self):
        with self.admit():
            self.assertEqual(self.call()["status"], "active")
            self.ctx.hooks["on_session_end"][-1](session_id="owner")
            self.assertFalse(self.ctx.checks["omh_browser"]())
            self.assertFalse(self.adapter.live)
            self.assertEqual(self.call()["status"], "blocked")

    def test_environment_identity_is_not_a_host_request(self):
        self.host._SESSION_ID.set(None)
        with patch.dict("os.environ", {"HERMES_SESSION_ID": "owner"}):
            with self.assertRaisesRegex(ValueError, "host_scope_unavailable"):
                with self.admit():
                    self.fail("ambient environment was admitted")
        self.assertFalse(self.home.exists())

    def test_session_end_revokes_even_after_request_identity_changes(self):
        with self.admit():
            copied = copy_context()
            self.host._SESSION_MESSAGE_ID.set("session-end-request")
            self.ctx.hooks["on_session_end"][-1](session_id="owner")
            self.assertFalse(copied.run(self.ctx.checks["omh_browser"]))

    def test_scope_exit_surfaces_unobserved_cleanup(self):
        try:
            with self.assertRaisesRegex(ValueError, "cleanup_unknown"):
                with self.admit():
                    self.assertEqual(self.call()["status"], "active")
                    self.adapter.release = lambda *args: {"reaped": False}
        finally:
            self.adapter.release = Adapter.release.__get__(self.adapter)
            self.ctx.hooks["on_session_end"][-1](session_id="owner")
        self.assertFalse(self.adapter.live)
