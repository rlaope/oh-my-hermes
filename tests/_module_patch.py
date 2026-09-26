"""Patch `sys.modules` without leaving a package pointing at a dropped module.

`mock.patch.dict(sys.modules, ...)` restores the dict by dropping every module
first imported inside the block, but the import also set an attribute on the
parent package, and that attribute survives. Afterwards the two import forms
disagree: `from package import child` reads the stale attribute, while
`from .child import name` inside a sibling re-imports `child` as a new module
object. A test that patches one and calls through the other then patches a
module nobody reads.

That is how #1885's `--workers 2` run failed the hash-cap test in
`test_document_plan_tool`: `host_session()` registers the plugin inside such a
block, which imports every tool, and the victim module was imported after it
in the same process. The serial runner imports every test module before
running any test, so the order never arose there.

Every `sys.modules` patch in the suite goes through `patch_modules`;
`tests/test_module_patch_policy.py` fails on one that does not.
"""

from __future__ import annotations

import sys
from types import ModuleType, TracebackType
from typing import Any, Mapping
from unittest import mock


class patch_modules:
    """`mock.patch.dict(sys.modules, values)`, plus forgetting what the block imported.

    Usable as a context manager or with `start()` / `stop()`, like the patcher
    it wraps.
    """

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._patcher = mock.patch.dict(sys.modules, values)
        self._before: set[str] = set()

    def __enter__(self) -> None:
        self._before = set(sys.modules)
        self._patcher.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        imported = {name: sys.modules[name] for name in set(sys.modules) - self._before}
        self._patcher.__exit__(exc_type, exc, traceback)
        for name, module in imported.items():
            if name in sys.modules:
                continue
            parent_name, _, child = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if isinstance(parent, ModuleType) and vars(parent).get(child) is module:
                delattr(parent, child)

    def start(self) -> None:
        self.__enter__()

    def stop(self) -> None:
        self.__exit__(None, None, None)
