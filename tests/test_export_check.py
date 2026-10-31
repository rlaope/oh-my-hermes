"""The round-end export check: names an edited module exports or imports that no longer exist.

The measured miss (OPT-A live run, 2026-10-30): after renaming `compute_quota`, GPT models
updated `from .quota import compute_quota` in `api.py` and left `__all__ = ["compute_quota"]`.
No test that imports the new name fails and pyright reports nothing, so the stale entry stayed.
These tests pin what the check says, when it stays silent, and where its note sits in the one
`pre_verify` message.
"""

from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import export_check, impact_check
from omh.plugin_bundle.omh.tools import lsp_nav_tool
from omh.plugin_bundle.omh.consistency_trigger import Verdict
from omh.plugin_bundle.omh.hooks import nudge_budget, verify_hooks
from omh.plugin_bundle.omh.impact_check import format_note as impact_format_note

NO_COPY = Verdict(False, "no_copy_or_reference")

QUOTA = "def allocate_quota(units: int) -> int:\n    return units * 3\n\n\nclass LegacyPlanner:\n    def compute_quota(self) -> int:\n        return 1\n"
STALE_API = 'from .quota import allocate_quota\n\n__all__ = ["compute_quota"]\n'
FIXED_API = 'from .quota import allocate_quota\n\n__all__ = ["allocate_quota"]\n'


class _Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "ws"
        (self.root / ".git").mkdir(parents=True)

    def write(self, relative: str, text: str) -> str:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def note(self, *relatives: str, reported: str = "") -> str:
        return export_check.round_end_note("s", [str(self.root / relative) for relative in relatives], reported,
                                           str(self.root))


class StaleAllTest(_Workspace):
    def test_the_measured_miss_is_named_by_file_and_line(self):
        self.write("src/benchapp/__init__.py", "")
        self.write("src/benchapp/quota.py", QUOTA)
        self.write("src/benchapp/api.py", STALE_API)
        note = self.note("src/benchapp/api.py", "src/benchapp/quota.py")
        self.assertEqual(note.splitlines(), [
            "OMH export check: a file you edited names something that no longer exists:",
            "src/benchapp/api.py:3: `__all__` lists `compute_quota`, which this module no longer defines or imports",
            "Update or remove each stale name.",
        ])

    def test_each_check_of_edited_python_files_logs_its_row_count(self):
        self.write("src/benchapp/__init__.py", "")
        self.write("src/benchapp/quota.py", QUOTA)
        self.write("src/benchapp/api.py", STALE_API)
        with self.assertLogs("omh.export_check", "INFO") as logs:
            self.note("src/benchapp/api.py")
        self.assertRegex(logs.output[0], r"export_check round_end session=s files=1 rows=1 deadline=0 ms=\d+$")

    def test_a_stale_entry_added_with_plus_equals_is_named(self):
        self.write("pkg/mod.py", "__all__ = ['kept']\n__all__ += ['gone']\nkept = 1\n")
        self.assertIn("pkg/mod.py:2: `__all__` lists `gone`", self.note("pkg/mod.py"))

    def test_without_a_workspace_root_the_path_is_shown_whole_with_slashes(self):
        path = self.write("pkg/mod.py", "__all__ = ['gone']\n")
        note = export_check.round_end_note("s", [path])
        self.assertIn(f"{Path(path).as_posix()}:1: `__all__` lists `gone`", note)

    def test_a_correct_rename_is_silent(self):
        self.write("src/benchapp/__init__.py", "")
        self.write("src/benchapp/quota.py", QUOTA)
        self.write("src/benchapp/api.py", FIXED_API)
        self.assertEqual(self.note("src/benchapp/api.py", "src/benchapp/quota.py"), "")

    def test_every_valid_way_to_bind_an_exported_name_is_silent(self):
        # The control template's package: a submodule exported without an import, a name bound in
        # both arms of a try, `+=`, `append`, `extend`, a name defined after `__all__`, and more.
        self.write("src/store/rows.py", "ROW_LIMIT = 5\n\n\ndef load_rows(count):\n    return list(range(count))\n")
        self.write("src/store/formats.py", "")
        self.write("src/store/codecs.py", "")
        self.write("src/store/drivers/__init__.py", "")
        self.write("src/store/__init__.py", (
            "import os.path\nfrom . import formats\nfrom .rows import load_rows, ROW_LIMIT as LIMIT\n"
            "try:\n    from ._native import fast_rows\nexcept ImportError as missing:\n    fast_rows = None\n"
            "if os.path.sep:\n    class Reader:\n        pass\nfor index, (left, *rest) in enumerate([(1, 2)]):\n    pass\n"
            "with open(__file__) as handle:\n    pass\n"
            "def configure():\n    global CONFIGURED\n    CONFIGURED = True\n"
            "TOTAL: int = 0\nCOUNT = 0\nCOUNT += 1\n"
            '__all__ = ["load_rows", "LIMIT", "formats", "codecs", "drivers", "fast_rows", "missing", "Reader"]\n'
            '__all__ += ["STORE_VERSION", "os", "index", "left", "rest", "handle", "configure", "CONFIGURED"]\n'
            '__all__.append("TOTAL")\n__all__.extend(("COUNT",))\nSTORE_VERSION = "1"\n'
        ))
        self.assertEqual(self.note("src/store/__init__.py"), "")

    def test_a_module_whose_names_cannot_be_known_is_skipped(self):
        # Each is how a real package binds names without a statement: found in a sweep over CPython's
        # standard library, a 4,576-file site-packages, Hermes and this repo (re, attrs, numpy, the shim).
        for body in (
            "from .other import *\n",
            "def __getattr__(name):\n    return name\n",
            "__getattr__ = make_getattr(__name__)\n",
            "globals()['gone'] = 1\n",
            "def add():\n    from pkg import mod\n    setattr(mod, 'gone', 1)\n",
            "import sys\nsetattr(sys.modules[__name__], 'gone', 1)\n",
            "import enum\n@enum.global_enum\nclass Flag(enum.IntFlag):\n    gone = 1\n",
            # Found by the review on Hermes: tui_gateway/server.py hands itself to a registry.
            "import sys\nimport registry\nregistry.register(sys.modules[__name__])\n",
            "import sys\nsys.modules[__name__].__dict__.update(gone=1)\n",
            "for name in ('gone',):\n    vars()[name] = 1\n",
            "locals()['gone'] = 1\n",
            "import enum\nclass S(enum.IntEnum):\n    gone = 1\nS._convert_('S', __name__, lambda n: True)\n",
            "__path__.append('elsewhere')\n",
            "__all__ = ['gone'] + []\n",
            "__all__.extend(other.__all__)\n",
        ):
            with self.subTest(body=body):
                self.write("pkg/mod.py", f"__all__ = ['gone']\n{body}")
                self.assertEqual(self.note("pkg/mod.py"), "")

    def test_attribute_writes_on_other_objects_do_not_hide_the_module(self):
        # `setattr(self, ...)`, a template environment's `globals`, a function's own `vars()`: none
        # of them writes this module's names, so a stale entry beside them is still named.
        self.write("pkg/mod.py", (
            "class C:\n    def __init__(self, **kw):\n        for k, v in kw.items():\n            setattr(self, k, v)\n"
            "def init(env):\n    env.globals['x'] = 1\n    env.exec('code')\n    return vars()\n"
            "__all__ = ['C', 'init', 'gone']\n"
        ))
        self.assertIn("pkg/mod.py:9: `__all__` lists `gone`", self.note("pkg/mod.py"))

    def test_implicit_module_names_and_compiled_or_namespace_submodules_are_bound(self):
        self.write("pkg/_speedups.cpython-311-darwin.so", "")
        self.write("pkg/_typed.pyi", "")
        self.write("pkg/legacy.pyc", "")
        self.write("pkg/nsdir/mod.py", "")  # a namespace subpackage: no __init__.py
        self.write("pkg/__init__.py", "__all__ = ['__doc__', '__file__', '_speedups', '_typed', 'legacy', 'nsdir']\n")
        self.assertEqual(self.note("pkg/__init__.py"), "")

    def test_an_invalid_escape_in_the_edited_file_raises_no_warning_here(self):
        self.write("pkg/mod.py", 'import re\nPAT = re.compile("\\d+")\n__all__ = ["PAT"]\n')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(self.note("pkg/mod.py"), "")
        self.assertEqual([item for item in caught if issubclass(item.category, SyntaxWarning)], [])

    def test_a_deadline_returns_the_rows_found_so_far(self):
        for index in range(3):
            self.write(f"pkg/m{index}.py", "__all__ = ['gone']\n")
        ticks = iter([0.0, 0.0, 0.0, 0.0] + [100.0] * 50)
        with patch.object(export_check.time, "monotonic", lambda: next(ticks)), \
                self.assertLogs("omh.export_check", "INFO") as logs:
            note = self.note("pkg/m0.py", "pkg/m1.py", "pkg/m2.py")
        self.assertIn("pkg/m0.py:1:", note)
        self.assertNotIn("pkg/m2.py:1:", note)
        # The log line says the row count is partial (#2439 review).
        self.assertRegex(logs.output[0], r"files=3 rows=\d deadline=1 ")

    def test_parse_errors_unknown_paths_and_other_files_are_silent(self):
        self.write("pkg/broken.py", "__all__ = ['gone'\n")
        self.write("pkg/notes.txt", "__all__ = ['gone']\n")
        self.assertEqual(self.note("pkg/broken.py", "pkg/notes.txt", "pkg/missing.py"), "")
        # Hermes reports landed paths as absolute; a relative one has no root to resolve against.
        self.write("pkg/mod.py", "__all__ = ['gone']\n")
        self.assertEqual(export_check.round_end_note("s", ["pkg/mod.py"]), "")
        for value in (None, "pkg/mod.py", 7, [None, 3]):
            self.assertEqual(export_check.round_end_note("s", value), "")


class StaleImportTest(_Workspace):
    def test_a_relative_and_an_absolute_import_of_a_renamed_name_are_named(self):
        self.write("src/benchapp/__init__.py", "")
        self.write("src/benchapp/quota.py", QUOTA)
        self.write("src/benchapp/api.py", 'from .quota import compute_quota\n\n__all__ = ["compute_quota"]\n')
        self.write("src/benchapp/service.py", "from benchapp.quota import compute_quota as cq\n")
        self.write("src/benchapp/report.py", "from .quota import (\n    allocate_quota,\n    compute_quota,\n)\n")
        note = self.note("src/benchapp/api.py", "src/benchapp/service.py", "src/benchapp/report.py")
        self.assertIn("src/benchapp/api.py:1: `from .quota import compute_quota`: src/benchapp/quota.py no longer defines "
                      "`compute_quota`", note)
        self.assertIn("src/benchapp/service.py:1: `from benchapp.quota import compute_quota`", note)
        # A parenthesized import names the line of the stale name, the line pyright names.
        self.assertIn("src/benchapp/report.py:3: `from .quota import compute_quota`", note)
        # The `__all__` entry is bound by the stale import, so it is that import that is named.
        self.assertNotIn("`__all__` lists", note)

    def test_imports_that_resolve_or_leave_the_workspace_are_silent(self):
        self.write("src/benchapp/__init__.py", "from . import formats\n")
        self.write("src/benchapp/formats.py", "")
        self.write("src/benchapp/quota.py", QUOTA)
        # `src/typing.py` sits where an absolute import is resolved, so only the standard-library
        # rule keeps `from typing import Any` off it; `helpers.py` inside the package is not on that path.
        self.write("src/typing.py", "")
        self.write("src/benchapp/helpers.py", "")
        self.write("src/benchapp/nsdir/mod.py", "")  # a namespace subpackage
        self.write("src/benchapp/api.py", (
            "import os\nfrom os import path\nfrom . import formats, nsdir\nfrom .quota import allocate_quota, LegacyPlanner\n"
            "from benchapp import quota, nsdir as ns\nfrom requests import get\nfrom .absent import thing\n"
            "from typing import Any\nfrom helpers import tool\n"
            "try:\n    from .quota import optional_name\nexcept ImportError:\n    optional_name = None\n"
        ))
        self.assertEqual(self.note("src/benchapp/api.py"), "")

    def test_a_plugin_folder_named_like_an_installed_package_is_not_resolved(self):
        # Found by the review on Hermes: plugins/platforms/telegram/update_admission.py's
        # `from telegram import Update` means python-telegram-bot, not the plugin's own folder.
        self.write("pyproject.toml", "")
        self.write("plugins/platforms/telegram/__init__.py", "from .adapter import Adapter\n")
        self.write("plugins/platforms/telegram/adapter.py", "class Adapter:\n    pass\n")
        self.write("plugins/platforms/telegram/update_admission.py", "from telegram import Update\n")
        self.write("scripts/setuptools.py", "def other():\n    pass\n")
        self.write("scripts/build.py", "from setuptools import setup\n")
        self.assertEqual(self.note("plugins/platforms/telegram/update_admission.py", "scripts/build.py"), "")
        # A virtualenv inside the checkout imports from its own site-packages, never the checkout
        # (found by the sweep: onnxruntime's `from utils import ...` against the repo's utils.py).
        self.write("utils.py", "def mine():\n    pass\n")
        self.write("venv/lib/python3.11/site-packages/tool/models/__init__.py", "")
        self.write("venv/lib/python3.11/site-packages/tool/models/export.py", "from utils import onnx_inference\n")
        self.assertEqual(self.note("venv/lib/python3.11/site-packages/tool/models/export.py"), "")

    def test_a_bare_name_in_a_non_package_directory_reads_the_sibling_module_first(self):
        # #2439 review: `from conftest import x` in tests/test_a.py was resolved to the root's
        # conftest.py. pytest's `prepend` mode (and a script's own `sys.path[0]`) reads tests/'s.
        self.write("conftest.py", "def root_fixture():\n    pass\n")
        self.write("tests/conftest.py", "def make_user():\n    pass\n")
        self.write("tests/test_a.py", "from conftest import make_user\n")
        self.assertEqual(self.note("tests/test_a.py"), "")
        self.write("tests/test_b.py", "from conftest import make_account\n")
        self.assertIn("tests/test_b.py:1: `from conftest import make_account`: tests/conftest.py no longer defines",
                      self.note("tests/test_b.py"))
        # A package's own folder is not on the path: tests/ with an `__init__.py` still reads the root's.
        self.write("pkgtests/__init__.py", "")
        self.write("pkgtests/conftest.py", "def make_user():\n    pass\n")
        self.write("pkgtests/test_c.py", "from conftest import root_fixture\n")
        self.assertEqual(self.note("pkgtests/test_c.py"), "")

    def test_a_namespace_package_module_reads_the_root_module_too(self):
        # #2454 review: a directory without `__init__.py` is also a PEP 420 namespace package, whose
        # `from config import KEY` reads src/config.py. With two candidates, a name is stale only
        # when both lack it.
        self.write("pyproject.toml", "")
        self.write("src/config.py", "KEY = 1\n")
        self.write("src/ns/config.py", "OTHER = 1\n")
        self.write("src/ns/mod.py", "from config import KEY\n")
        self.assertEqual(self.note("src/ns/mod.py"), "")
        self.write("utils.py", "def helper():\n    pass\n")
        self.write("app/utils.py", "def other():\n    pass\n")
        self.write("app/main.py", "from utils import helper\n")
        self.write("scripts/utils.py", "from utils import helper\n")  # the sibling is the importer itself
        self.assertEqual(self.note("app/main.py", "scripts/utils.py"), "")
        self.write("src/ns/stale.py", "from config import GONE\n")
        self.assertIn("src/ns/stale.py:1: `from config import GONE`: src/ns/config.py no longer defines `GONE`",
                      self.note("src/ns/stale.py"))

    def test_a_path_on_another_windows_drive_is_shown_whole(self):
        # #2439 review: `os.path.relpath` raises ValueError across Windows drives, and the broad
        # except dropped the whole note. The impact note's `workspace_relative` had the same exposure.
        self.write("pkg/mod.py", "__all__ = ['gone']\n")
        path = str(self.root / "pkg/mod.py")

        def other_drive(target, start=None):
            raise ValueError("path is on mount 'D:', start on mount 'C:'")

        def drive(value):
            return ("D:" if value == path else "C:", value)

        with patch.object(export_check.os.path, "relpath", other_drive), \
                patch.object(export_check.os.path, "splitdrive", drive):
            note = self.note("pkg/mod.py")
            self.assertEqual(lsp_nav_tool.workspace_relative(path, str(self.root)), Path(path).as_posix())
        self.assertIn(f"{Path(path).as_posix()}:1: `__all__` lists `gone`", note)
        self.assertIs(impact_check.workspace_relative, lsp_nav_tool.workspace_relative)
        # Any other ValueError is not this fallback's: it still raises.
        with patch.object(export_check.os.path, "relpath", other_drive):
            with self.assertRaises(ValueError):
                lsp_nav_tool.workspace_relative(path, str(self.root))

    def test_a_package_directory_wins_over_a_same_named_module(self):
        self.write("src/x.py", "")
        self.write("src/x/__init__.py", "a = 1\n")
        self.write("src/user.py", "from x import a\n")
        self.assertEqual(self.note("src/user.py"), "")
        self.write("src/user.py", "from x import b\n")
        self.assertIn("src/user.py:1: `from x import b`: src/x/__init__.py no longer defines `b`", self.note("src/user.py"))

    def test_a_module_written_into_from_outside_is_not_judged_as_a_target(self):
        self.write("tui/__init__.py", "")
        self.write("tui/server.py", "import sys\nimport methods\nmethods.register(sys.modules[__name__])\n")
        self.write("tui/entry.py", "from tui.server import dispatch\n")
        self.assertEqual(self.note("tui/entry.py"), "")


class PreVerifyCompositionTest(_Workspace):
    def setUp(self):
        super().setUp()
        nudge_budget.reset_nudge_budget()
        self.addCleanup(nudge_budget.reset_nudge_budget)
        verify_hooks.reset_stashed_answers()
        self.addCleanup(verify_hooks.reset_stashed_answers)
        self.write("src/benchapp/__init__.py", "")
        self.write("src/benchapp/quota.py", QUOTA)
        self.api = self.write("src/benchapp/api.py", STALE_API)
        self.home = Path(self._tmp.name) / "omh"

    def fire(self, **overrides):
        payload = {"session_id": "export-session", "coding": True, "attempt": 0, "final_response": "{}",
                   "changed_paths": [self.api], "omh_home": str(self.home)}
        payload.update(overrides)
        # The workspace root comes from the turn's tool calls (`consistency_trigger.turn_root`).
        with patch.object(verify_hooks, "turn_root", lambda session_id: str(self.root)):
            return verify_hooks.pre_verify(**payload)

    def test_a_delegated_child_gets_the_note_and_returns_its_full_answer(self):
        # The note is always on, so a delegated child that leaves a stale export pays one more round;
        # it gets no consistency check and no sentinel, only the note and the full-answer closing.
        message = self.fire(platform="subagent")["message"]
        self.assertEqual(message, f"{self.note('src/benchapp/api.py')}\n{verify_hooks.ROUND_END_CLOSING_UNSTASHED}")
        self.assertNotIn("export-session", verify_hooks._STASHED_ANSWERS)

    def test_the_note_sits_between_the_impact_note_and_the_check_under_one_closing(self):
        impact = impact_format_note([("src/benchapp/report.py", 5, "error")], recheck_tool=False)
        with patch.object(verify_hooks, "round_end_note", lambda session_id, changed_paths: impact):
            message = self.fire()["message"]
        self.assertLess(message.index("OMH impact check"), message.index("OMH export check"))
        self.assertLess(message.index("OMH export check"), message.index("OMH round-end consistency check"))
        self.assertTrue(message.endswith(verify_hooks.ROUND_END_CLOSING))
        self.assertEqual(message.count("When you are done"), 1)

    def test_the_note_alone_outside_coding_gets_the_one_closing(self):
        message = self.fire(coding=False)["message"]
        self.assertEqual(message, f"{self.note('src/benchapp/api.py')}\n{verify_hooks.ROUND_END_CLOSING}")

    def test_only_the_first_stop_runs_it_and_a_clean_tree_adds_nothing(self):
        self.assertIsNone(self.fire(coding=False, attempt=1))
        Path(self.api).write_text(FIXED_API, encoding="utf-8")
        self.assertIsNone(self.fire(coding=False))
        with patch.object(verify_hooks, "round_end_trigger", lambda session_id, code_paths: Verdict(True, "copy")):
            self.assertEqual(self.fire()["message"],
                             f"{verify_hooks.ROUND_END_CHECKLIST}\n{verify_hooks.ROUND_END_CLOSING}")

    def test_the_note_continues_the_turn_when_the_trigger_finds_no_copy(self):
        # The trigger only decides whether the consistency check earns a round of its own. The
        # export note is the work, so it continues the turn, and the check rides along with it.
        def trigger(session_id, code_paths):
            raise AssertionError("beside the export note the check needs no verdict")

        with patch.object(verify_hooks, "round_end_trigger", trigger):
            message = self.fire()["message"]
        self.assertEqual(message, "\n".join((self.note("src/benchapp/api.py"), verify_hooks.ROUND_END_CHECKLIST,
                                             verify_hooks.ROUND_END_CLOSING)))

    def test_no_copy_and_a_clean_tree_end_the_turn(self):
        Path(self.api).write_text(FIXED_API, encoding="utf-8")
        with patch.object(verify_hooks, "round_end_trigger", lambda session_id, code_paths: NO_COPY):
            self.assertIsNone(self.fire())

    def test_a_line_the_impact_note_names_is_not_named_again(self):
        # An edited importer's stale `from .quota import compute_quota` is also a pyright error.
        Path(self.api).write_text('from .quota import compute_quota\n\n__all__ = ["compute_quota"]\n', encoding="utf-8")
        service = self.write("src/benchapp/service.py", "from benchapp.quota import compute_quota as cq\n")
        impact = impact_format_note([("src/benchapp/api.py", 1, '"compute_quota" is unknown import symbol')],
                                    recheck_tool=False)
        with patch.object(verify_hooks, "round_end_note", lambda session_id, changed_paths: impact):
            message = self.fire(changed_paths=[self.api, service])["message"]
        self.assertEqual(message.count("src/benchapp/api.py:1:"), 1)
        self.assertIn("src/benchapp/service.py:1: `from benchapp.quota import compute_quota`", message)
        # With every row already named, there is no export note at all.
        with patch.object(verify_hooks, "round_end_note", lambda session_id, changed_paths: impact):
            message = self.fire()["message"]
        self.assertNotIn("OMH export check", message)


if __name__ == "__main__":
    unittest.main()
