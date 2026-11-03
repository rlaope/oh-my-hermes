"""`register()` moves the first turns' package imports onto a thread, and `pre_llm_call` waits for it.

The capability families and the router cost a session's first user turns 80-300 ms to import.
`register()` starts a daemon thread that imports them while the person types; it must not make
`register()` itself wait (the plugin-load deadline), and `pre_llm_call` must not run beside it, so
no turn enters the same import cycle from another thread. A warm-up that fails or cannot start
changes nothing: the call sites import as they did and report there.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

import omh.plugin_bundle.omh as bundle  # noqa: E402
from omh.plugin_bundle.omh.hooks import llm_hooks  # noqa: E402


TESTS_DIR = Path(__file__).resolve().parent
WARMED = ("omh.capabilities.families", "omh.routing.chat")
_FRESH_REGISTER = f"""
import json, sys, threading
from unittest import mock
from _local_package import load_local_package
load_local_package()
import omh.plugin_bundle.omh as bundle
from omh.plugin_bundle.omh.hooks import llm_hooks

class Context:
    def register_tool(self, *args, **kwargs): pass
    def register_hook(self, name, handler): pass
    def register_memory_provider(self, provider): pass
    def get_config(self, key, default=None): return default

names, release, real = {WARMED!r}, threading.Event(), llm_hooks._warm_imports
def held():
    release.wait(60)
    real()
with mock.patch.object(bundle, "_admit_host", lambda: None), mock.patch.object(llm_hooks, "_warm_imports", held):
    bundle.register(Context())
after_register = {{name: name in sys.modules for name in names}}
release.set()
llm_hooks._await_import_warmup()
print(json.dumps({{"after_register": after_register, "after_warmup": {{name: name in sys.modules for name in names}}}}))
"""


class _Context:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}

    def register_tool(self, *args: object, **kwargs: object) -> None:
        return None

    def register_hook(self, name: str, handler: object) -> None:
        self.hooks[name] = handler

    def register_memory_provider(self, provider: object) -> None:
        return None

    def get_config(self, key: str, default: object = None) -> object:
        return default


class ImportWarmupTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(llm_hooks, "_import_warmup", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self) -> _Context:
        ctx = _Context()
        with mock.patch.object(bundle, "_admit_host", lambda: None):
            bundle.register(ctx)
        return ctx

    def test_register_returns_before_the_warmup_and_the_first_turn_waits_for_it(self) -> None:
        release, started = threading.Event(), threading.Event()

        def slow_imports() -> None:
            started.set()
            release.wait(10)

        with mock.patch.object(llm_hooks, "_warm_imports", slow_imports):
            ctx = self.register()
            self.assertTrue(started.wait(10))
            warmup = llm_hooks._import_warmup
            self.assertIsNotNone(warmup)
            self.assertTrue(warmup.is_alive(), "register() must not wait for the imports")
            turn_done = threading.Event()

            def first_turn() -> None:
                ctx.hooks["pre_llm_call"](session_id="warmup", user_message="hi", platform="tui", turn_id="t1")
                turn_done.set()

            turn = threading.Thread(target=first_turn, daemon=True)
            turn.start()
            self.assertFalse(turn_done.wait(0.3), "pre_llm_call must not run beside the warm-up")
            release.set()
            self.assertTrue(turn_done.wait(30))
            turn.join(30)
        self.assertFalse(warmup.is_alive())

    def test_the_warmup_starts_once_per_process_copy(self) -> None:
        with mock.patch.object(llm_hooks, "_warm_imports", lambda: None):
            self.register()
            first = llm_hooks._import_warmup
            self.register()
        self.assertIs(llm_hooks._import_warmup, first)

    def test_the_warmup_loads_the_modules_the_first_turns_import(self) -> None:
        # A fresh interpreter: in this one the suite has imported both modules already.
        result = subprocess.run([sys.executable, "-P", "-c", _FRESH_REGISTER], capture_output=True, text=True,
                                check=False, timeout=120, env={**os.environ, "PYTHONPATH": str(TESTS_DIR)})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        loaded = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(loaded["after_register"], {name: False for name in WARMED})
        self.assertEqual(loaded["after_warmup"], {name: True for name in WARMED})
        self.assertEqual(result.stderr, "")

    def test_a_failed_import_raises_nothing(self) -> None:
        # A `None` entry makes the import raise ImportError, as on a host without `omh`.
        with mock.patch.dict(sys.modules, {"omh.capabilities.families": None}):
            llm_hooks._warm_imports()
            self.assertIsNone(sys.modules["omh.capabilities.families"])
        with mock.patch.dict(sys.modules, {"omh.routing.chat": None}):
            llm_hooks._warm_imports()

    def test_a_thread_that_cannot_start_leaves_registration_and_the_first_turn_as_they_were(self) -> None:
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("can't start new thread")):
            ctx = self.register()
        self.assertIsNone(llm_hooks._import_warmup)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn("pre_tool_call", ctx.hooks)
        llm_hooks._await_import_warmup()


if __name__ == "__main__":
    unittest.main()
