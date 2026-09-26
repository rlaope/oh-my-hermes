"""`sys.modules` patches in the suite must not leave a package pointing at a dropped module.

See `tests/_module_patch.py` for the mechanism and the #1885 failure it caused.
The first two cases rebuild that failure on a throwaway package: the control
shows the plain patch splits one module into two objects, the second that
`patch_modules` does not. The gate then re-derives every `sys.modules` patch in
`tests/` from source, so a new one written the plain way fails here rather than
in whichever worker partition first imports its victim after it.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _module_patch import patch_modules

TESTS = Path(__file__).resolve().parent
PACKAGE = "_module_patch_probe"
# The helper wraps the plain patch, and this file's control case uses it to
# show the split; nothing else may.
PLAIN_PATCH_ALLOWED = ("_module_patch.py", "test_module_patch_policy.py")


def _is_sys_modules(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == "sys.modules"
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def plain_sys_modules_patches() -> list[str]:
    """Every `<anything>.dict(sys.modules, ...)` call under tests/, outside the helper."""

    found: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name in PLAIN_PATCH_ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "dict"
                and node.args
                and _is_sys_modules(node.args[0])
            ):
                found.append(f"{path.relative_to(TESTS)}:{node.lineno}")
    return found


class ModulePatchTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        package = Path(temporary.name) / PACKAGE
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "planner.py").write_text("CAP = 100\n\ndef over(size):\n    return size > CAP\n", encoding="utf-8")
        (package / "tool.py").write_text("from .planner import over\n", encoding="utf-8")
        sys.path.insert(0, temporary.name)
        self.addCleanup(sys.path.remove, temporary.name)
        self.addCleanup(self._forget)
        __import__(PACKAGE)

    def _forget(self) -> None:
        for name in [name for name in sys.modules if name == PACKAGE or name.startswith(f"{PACKAGE}.")]:
            del sys.modules[name]

    def _patch_reaches_the_tool(self) -> bool:
        """Patch the planner the way the victim test does, then call through the tool."""

        planner = __import__(PACKAGE, fromlist=["planner"]).planner
        tool = __import__(f"{PACKAGE}.tool", fromlist=["over"])
        with mock.patch.object(planner, "CAP", 1):
            return tool.over(2)

    def test_control_the_plain_patch_splits_the_module(self) -> None:
        with mock.patch.dict(sys.modules, {}):
            __import__(f"{PACKAGE}.tool")
        self.assertFalse(self._patch_reaches_the_tool())

    def test_patch_modules_leaves_one_module(self) -> None:
        with patch_modules({}):
            __import__(f"{PACKAGE}.tool")
        self.assertTrue(self._patch_reaches_the_tool())

    def test_start_and_stop_forget_the_same_way(self) -> None:
        patcher = patch_modules({"_module_patch_probe_host": object()})
        patcher.start()
        __import__(f"{PACKAGE}.tool")
        self.assertIn("_module_patch_probe_host", sys.modules)
        patcher.stop()
        self.assertNotIn("_module_patch_probe_host", sys.modules)
        self.assertTrue(self._patch_reaches_the_tool())

    def test_every_sys_modules_patch_in_the_suite_goes_through_patch_modules(self) -> None:
        self.assertEqual(
            plain_sys_modules_patches(),
            [],
            "patch sys.modules with `from _module_patch import patch_modules`, not "
            "mock.patch.dict: the plain patch drops what the block imported but leaves "
            "the parent package's attribute, and the next test to import that module "
            "gets two copies of it (see tests/_module_patch.py).",
        )


if __name__ == "__main__":
    unittest.main()
