"""Tests for the opt-in omh-lsp tools (lsp_definition / lsp_references / lsp_rename) and lsp_nav core."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from _module_patch import patch_modules  # noqa: E402

from omh.plugin_bundle.omh import lsp_bridge  # noqa: E402
from omh.plugin_bundle.omh.lsp_nav import (  # noqa: E402
    OverlapError,
    ScopeMismatch,
    StaleFile,
    UnsupportedEdit,
    apply_text_edits,
    apply_workspace_edit,
    find_symbol_column,
    normalize_locations,
    path_to_uri,
    py_index,
    utf16_col,
    valid_identifier,
    workspace_edit_targets,
)
from omh.plugin_bundle.omh.tools import lsp_nav_tool  # noqa: E402
from omh.plugin_bundle.omh.tools.lsp_nav_tool import (  # noqa: E402
    OMH_LSP_DEFINITION_SCHEMA,
    OMH_LSP_REFERENCES_SCHEMA,
    OMH_LSP_RENAME_SCHEMA,
    _lsp_tools_enabled,
    lsp_definition_handler,
    lsp_references_handler,
    lsp_rename_handler,
)


def _edit(line, start, end, new, end_line=None):
    return {"range": {"start": {"line": line, "character": start},
                      "end": {"line": line if end_line is None else end_line, "character": end}},
            "newText": new}


class Utf16Tests(unittest.TestCase):
    def test_round_trip_with_emoji_and_korean(self):
        line = "x = '😀한글' + LIMIT"
        for index in range(len(line) + 1):
            self.assertEqual(py_index(line, utf16_col(line, index)), index)
        at = line.index("LIMIT")
        self.assertEqual(utf16_col(line, at), at + 1)  # the emoji is two UTF-16 units

    def test_korean_is_one_unit(self):
        self.assertEqual(utf16_col("한글x", 2), 2)


class SymbolColumnTests(unittest.TestCase):
    def test_whole_identifier_preferred(self):
        line = "from .core import LIMIT_ALIAS, LIMIT"
        self.assertEqual(find_symbol_column(line, "LIMIT"), line.rindex("LIMIT"))
        line = "limit = max_x + x"
        self.assertEqual(find_symbol_column(line, "x"), len(line) - 1)

    def test_occurrence_n(self):
        line = "a = b + b * b"
        self.assertEqual(find_symbol_column(line, "b", 2), 8)
        self.assertEqual(find_symbol_column(line, "b", 3), 12)
        self.assertIsNone(find_symbol_column(line, "b", 4))

    def test_no_substring_match(self):
        # A substring match points the server at another symbol (LIMIT inside LIMIT_ALIAS / MAX_LIMIT).
        self.assertIsNone(find_symbol_column("value = LIMITS", "LIMIT"))
        self.assertIsNone(find_symbol_column("return LIMIT_ALIAS + MAX_LIMIT", "LIMIT"))
        self.assertIsNone(find_symbol_column("nothing here", "LIMIT"))


class IdentifierTests(unittest.TestCase):
    def test_python_rules(self):
        self.assertTrue(valid_identifier("MAX_LIMIT", ".py"))
        for bad in ("class", "1x", "a b", ""):
            self.assertFalse(valid_identifier(bad, ".py"), bad)

    def test_other_suffix(self):
        self.assertTrue(valid_identifier("my-name", ".ts"))
        self.assertFalse(valid_identifier("a b", ".ts"))


class LocationTests(unittest.TestCase):
    def test_forms(self):
        loc = {"uri": "file:///a.py", "range": {"start": {"line": 1, "character": 2}, "end": {"line": 1, "character": 3}}}
        link = {"targetUri": "file:///b.py", "targetRange": {"start": {"line": 0, "character": 0}},
                "targetSelectionRange": {"start": {"line": 4, "character": 5}}}
        self.assertEqual(normalize_locations(None), [])
        self.assertEqual(normalize_locations(loc), [("file:///a.py", 1, 2)])
        self.assertEqual(normalize_locations([loc, link]), [("file:///a.py", 1, 2), ("file:///b.py", 4, 5)])


class TextEditTests(unittest.TestCase):
    def test_multiple_edits_one_line(self):
        self.assertEqual(apply_text_edits("a + a\n", [_edit(0, 0, 1, "bb"), _edit(0, 4, 5, "bb")]), "bb + bb\n")

    def test_overlap_rejected(self):
        with self.assertRaises(OverlapError):
            apply_text_edits("abcdef\n", [_edit(0, 0, 3, "x"), _edit(0, 2, 4, "y")])

    def test_crlf_and_trailing_newline_preserved(self):
        text = "LIMIT = 1\r\nprint(LIMIT)\r\n"
        out = apply_text_edits(text, [_edit(0, 0, 5, "CAP"), _edit(1, 6, 11, "CAP")])
        self.assertEqual(out, "CAP = 1\r\nprint(CAP)\r\n")

    def test_end_of_line_position_is_before_line_ending(self):
        self.assertEqual(apply_text_edits("ab\r\ncd", [_edit(0, 2, 2, "!")]), "ab!\r\ncd")

    def test_utf16_positions(self):
        text = "s = '😀'; LIMIT\n"
        col = utf16_col(text, text.index("LIMIT"))
        self.assertEqual(apply_text_edits(text, [_edit(0, col, col + 5, "CAP")]), "s = '😀'; CAP\n")


class WorkspaceEditTargetTests(unittest.TestCase):
    def test_document_changes(self):
        edit = {"documentChanges": [{"textDocument": {"uri": "file:///a.py", "version": 1}, "edits": [_edit(0, 0, 1, "x")]}]}
        self.assertEqual(list(workspace_edit_targets(edit)), ["file:///a.py"])

    def test_changes(self):
        edit = {"changes": {"file:///a.py": [_edit(0, 0, 1, "x")], "file:///b.py": [_edit(1, 0, 1, "y")]}}
        self.assertEqual(sorted(workspace_edit_targets(edit)), ["file:///a.py", "file:///b.py"])

    def test_resource_op_unsupported(self):
        for kind in ("create", "rename", "delete"):
            with self.assertRaises(UnsupportedEdit):
                workspace_edit_targets({"documentChanges": [{"kind": kind, "uri": "file:///a.py"}]})


class _Root(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, text):
        path = os.path.join(self.root, *rel.split("/"))  # native separators: the code compares realpaths
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8", newline="") as handle:
            return handle.read()

    def snapshot(self, *paths):
        return {p: Path(p).read_bytes() for p in paths}


class ApplyWorkspaceEditTests(_Root):
    def test_applies_all_files(self):
        a = self.write("a.py", "LIMIT = 1\n")
        b = self.write("pkg/b.py", "from a import LIMIT\r\nprint(LIMIT)\r\n")
        targets = {path_to_uri(a): [_edit(0, 0, 5, "CAP")],
                   path_to_uri(b): [_edit(0, 14, 19, "CAP"), _edit(1, 6, 11, "CAP")]}
        result = apply_workspace_edit(self.root, targets, self.snapshot(a, b))
        self.assertEqual(sorted(result), [("a.py", 1), (os.path.join("pkg", "b.py"), 2)])
        self.assertEqual(self.read("a.py"), "CAP = 1\n")
        self.assertEqual(self.read("pkg/b.py"), "from a import CAP\r\nprint(CAP)\r\n")

    def test_scope_escape_dotdot(self):
        a = self.write("a.py", "LIMIT = 1\n")
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        escaped = os.path.join(self.root, "..", os.path.basename(outside), "o.py")
        Path(escaped).write_text("LIMIT = 2\n")
        targets = {path_to_uri(a): [_edit(0, 0, 5, "CAP")], "file://" + escaped: [_edit(0, 0, 5, "CAP")]}
        with self.assertRaises(ScopeMismatch):
            apply_workspace_edit(self.root, targets, self.snapshot(a))
        self.assertEqual(self.read("a.py"), "LIMIT = 1\n")
        self.assertEqual(Path(escaped).read_text(), "LIMIT = 2\n")

    def test_scope_escape_symlink(self):
        a = self.write("a.py", "LIMIT = 1\n")
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        target = os.path.join(outside, "o.py")
        Path(target).write_text("LIMIT = 2\n")
        link = os.path.join(self.root, "link.py")
        os.symlink(target, link)
        targets = {path_to_uri(a): [_edit(0, 0, 5, "CAP")], path_to_uri(link): [_edit(0, 0, 5, "CAP")]}
        with self.assertRaises(ScopeMismatch):
            apply_workspace_edit(self.root, targets, {**self.snapshot(a), os.path.realpath(target): b"LIMIT = 2\n"})
        self.assertEqual(self.read("a.py"), "LIMIT = 1\n")
        self.assertEqual(Path(target).read_text(), "LIMIT = 2\n")

    def test_stale_bytes(self):
        a = self.write("a.py", "LIMIT = 1\n")
        expected = self.snapshot(a)
        self.write("a.py", "LIMIT = 9\n")
        with self.assertRaises(StaleFile):
            apply_workspace_edit(self.root, {path_to_uri(a): [_edit(0, 0, 5, "CAP")]}, expected)
        self.assertEqual(self.read("a.py"), "LIMIT = 9\n")

    def test_multi_file_atomicity_second_stale(self):
        a = self.write("a.py", "LIMIT = 1\n")
        b = self.write("b.py", "print(LIMIT)\n")
        expected = self.snapshot(a, b)
        self.write("b.py", "print(LIMIT)  # changed\n")
        targets = {path_to_uri(a): [_edit(0, 0, 5, "CAP")], path_to_uri(b): [_edit(0, 6, 11, "CAP")]}
        with self.assertRaises(StaleFile):
            apply_workspace_edit(self.root, targets, expected)
        self.assertEqual(self.read("a.py"), "LIMIT = 1\n")
        self.assertEqual(self.read("b.py"), "print(LIMIT)  # changed\n")


class CheckFnGatingTests(unittest.TestCase):
    def setUp(self):
        old = os.environ.pop("OMH_LSP_TOOLS", None)
        if old is not None:
            self.addCleanup(os.environ.__setitem__, "OMH_LSP_TOOLS", old)
        self.addCleanup(os.environ.pop, "OMH_LSP_TOOLS", None)
        self._profile(None)

    def _profile(self, text):
        from omh.plugin_bundle.omh import runtime_paths

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        if text is not None:
            (home / "config.yaml").write_text(text, encoding="utf-8")
        patcher = mock.patch.object(runtime_paths, "default_hermes_home", return_value=home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_env(self):
        self.assertFalse(_lsp_tools_enabled())
        for value in ("1", "true", "On", "yes"):
            os.environ["OMH_LSP_TOOLS"] = value
            self.assertTrue(_lsp_tools_enabled(), value)
        for value in ("0", "false", "", "maybe"):
            os.environ["OMH_LSP_TOOLS"] = value
            self.assertFalse(_lsp_tools_enabled(), value)

    def test_profile_setting(self):
        self._profile("plugins:\n  entries:\n    omh:\n      settings:\n        lsp_tools: true\n")
        self.assertTrue(_lsp_tools_enabled())
        self._profile("plugins:\n  entries:\n    omh:\n      settings:\n        lsp_tools: off\n")
        self.assertFalse(_lsp_tools_enabled())

    def test_registration_uses_dedicated_toolset_and_check_fn(self):
        from omh.plugin_bundle.omh import register

        recorded = {}

        class Ctx:
            def register_tool(self, name, toolset, schema, handler, **kwargs):
                recorded[name] = (toolset, schema, handler, kwargs)

            def register_hook(self, name, handler):
                pass

        register(Ctx())
        for name, schema in (("lsp_definition", OMH_LSP_DEFINITION_SCHEMA), ("lsp_references", OMH_LSP_REFERENCES_SCHEMA),
                             ("lsp_rename", OMH_LSP_RENAME_SCHEMA)):
            self.assertEqual(recorded[name][0], "omh-lsp")
            self.assertEqual(recorded[name][1], schema)
            self.assertIs(recorded[name][3].get("check_fn"), _lsp_tools_enabled)


class _FakeBridge:
    """Stands in for lsp_bridge: records requests and answers from a table."""

    def __init__(self, answers, available=True, git=True):
        self.answers, self.available_ok, self.git = answers, available, git
        self.calls, self.notified = [], []
        self.synced_by_method = {}

    def available(self):
        return (object(), None) if self.available_ok else (None, "lsp_unavailable: disabled")

    def in_git_worktree(self, path):
        return self.git

    def request(self, path, builder, open_paths, timeout, open_texts=None):
        method, params = builder()
        self.calls.append((method, params))
        self.opened = list(open_paths)
        self.synced = dict(open_texts or {})
        self.synced_by_method.setdefault(method, []).append(dict(open_texts or {}))
        answer = self.answers.get(method)
        return answer(params) if callable(answer) else answer

    def notify_changed(self, path, paths):
        self.notified.extend(paths)


class HandlerTests(_Root):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(lsp_nav_tool, "_workspace_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.core = self.write("pkg/core.py", "LIMIT = 2\n\ndef budget():\n    return LIMIT\n")
        self.use = self.write("use.py", "from pkg.core import LIMIT\nprint(LIMIT, 'LIMIT')\n")

    def fake(self, answers, **kw):
        bridge = _FakeBridge(answers, **kw)
        for name in ("available", "in_git_worktree", "request", "notify_changed"):
            patcher = mock.patch.object(lsp_bridge, name, getattr(bridge, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        return bridge

    def rename_edit(self):
        return {"documentChanges": [
            {"textDocument": {"uri": path_to_uri(self.core), "version": 1},
             "edits": [_edit(0, 0, 5, "CAP"), _edit(3, 11, 16, "CAP")]},
            {"textDocument": {"uri": path_to_uri(self.use), "version": 1},
             "edits": [_edit(0, 21, 26, "CAP"), _edit(1, 6, 11, "CAP")]},
        ]}

    def call(self, handler, **args):
        return json.loads(handler(args, task_id="t"))

    def test_no_workspace(self):
        self.fake({}, git=False)
        out = self.call(lsp_references_handler, path="pkg/core.py", line=1, symbol="LIMIT")
        self.assertEqual(out["error"], "no_workspace")
        self.assertIn("git", out["hint"])

    def test_lsp_unavailable(self):
        self.fake({}, available=False)
        out = self.call(lsp_definition_handler, path="use.py", line=2, symbol="LIMIT")
        self.assertEqual(out["error"], "lsp_unavailable")

    def test_not_found(self):
        self.fake({})
        out = self.call(lsp_definition_handler, path="pkg/missing.py", line=1, symbol="x")
        self.assertEqual(out["error"], "not_found")

    def test_symbol_not_found_hint_has_line(self):
        self.fake({})
        out = self.call(lsp_definition_handler, path="pkg/core.py", line=3, symbol="LIMIT")
        self.assertEqual(out["error"], "symbol_not_found")
        self.assertIn("def budget():", out["hint"])

    def test_definition_position_and_payload(self):
        bridge = self.fake({"textDocument/definition": lambda p: {
            "uri": path_to_uri(self.core), "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}}}})
        out = self.call(lsp_definition_handler, path="use.py", line=2, symbol="LIMIT")
        self.assertEqual(bridge.calls[0][1]["position"], {"line": 1, "character": 6})
        self.assertEqual(out, {"ok": True, "count": 1, "locations": [
            {"path": os.path.join("pkg", "core.py"), "line": 1, "column": 1, "text": "LIMIT = 2"}]})

    def test_references_drop_outside_root(self):
        loc = lambda uri, line, ch: {"uri": uri, "range": {"start": {"line": line, "character": ch}, "end": {"line": line, "character": ch + 5}}}  # noqa: E731
        bridge = self.fake({"textDocument/references": [
            loc(path_to_uri(self.core), 0, 0), loc(path_to_uri(self.use), 1, 6), loc("file:///elsewhere/x.py", 0, 0)]})
        out = self.call(lsp_references_handler, path="pkg/core.py", line=1, symbol="LIMIT")
        self.assertEqual(bridge.calls[0][1]["context"], {"includeDeclaration": True})
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["outside_root"], 1)
        self.assertEqual(bridge.opened[0], self.core)
        self.assertIn(self.use, bridge.opened)

    def test_definition_opens_target_only(self):
        bridge = self.fake({"textDocument/definition": None})
        out = self.call(lsp_definition_handler, path="use.py", line=2, symbol="LIMIT")
        self.assertEqual(out["error"], "no_result")
        self.assertEqual(bridge.opened, [self.use])

    def test_invalid_name(self):
        self.fake({})
        for bad in ("class", "1x"):
            out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name=bad)
            self.assertEqual(out["error"], "invalid_name", bad)

    def test_prepare_rename_null(self):
        self.fake({"textDocument/prepareRename": None})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP")
        self.assertEqual(out["error"], "no_result")
        self.assertIn("renameable", out["hint"])

    def test_preview_writes_nothing(self):
        before = (self.read("pkg/core.py"), self.read("use.py"))
        bridge = self.fake({"textDocument/prepareRename": {"start": {}, "end": {}},
                            "textDocument/rename": self.rename_edit()})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP", apply=False)
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["applied"])
        self.assertEqual(out["total_edits"], 4)
        self.assertEqual({(e["old"], e["new"]) for e in out["edits"]}, {("LIMIT", "CAP")})
        self.assertEqual((self.read("pkg/core.py"), self.read("use.py")), before)
        self.assertEqual(bridge.notified, [])

    def test_apply_writes_and_notifies(self):
        bridge = self.fake({"textDocument/prepareRename": {"start": {}, "end": {}},
                            "textDocument/rename": self.rename_edit()})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP")
        self.assertTrue(out["applied"], out)
        self.assertEqual(out["total_edits"], 4)
        self.assertEqual(self.read("pkg/core.py"), "CAP = 2\n\ndef budget():\n    return CAP\n")
        self.assertEqual(self.read("use.py"), "from pkg.core import CAP\nprint(CAP, 'LIMIT')\n")
        self.assertEqual(sorted(bridge.notified), sorted([self.core, self.use]))

    def test_rename_syncs_disk_snapshot_of_every_workspace_file(self):
        # The verifier's 2c case: preview, another writer edits use.py, then apply. The server must be
        # given the CURRENT bytes of every file it may edit, not whatever it cached at preview time.
        bridge = self.fake({"textDocument/prepareRename": {"start": {}, "end": {}},
                            "textDocument/rename": self.rename_edit()})
        self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP", apply=False)
        self.write("use.py", "from pkg.core import LIMIT\nprint(LIMIT, 'LIMIT')\n")  # same text, rewritten
        self.write("use.py", "from pkg.core import LIMIT\nprint(LIMIT, 'LIMIT')  # edited\n")
        self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP", apply=False)
        sent = bridge.synced_by_method["textDocument/rename"][-1]
        self.assertEqual(sent[self.use], "from pkg.core import LIMIT\nprint(LIMIT, 'LIMIT')  # edited\n")
        self.assertEqual(sent[self.core], self.read("pkg/core.py"))

    def test_rename_refuses_file_changed_after_sync(self):
        original = (self.read("pkg/core.py"), self.read("use.py"))

        def edit_then_race(_params):
            # Another writer changes use.py while the server computes the edit.
            with open(self.use, "a", encoding="utf-8", newline="") as handle:
                handle.write("# raced\n")
            return self.rename_edit()

        bridge = self.fake({"textDocument/prepareRename": {"start": {}, "end": {}},
                            "textDocument/rename": edit_then_race})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP")
        self.assertEqual(out["error"], "stale_file", out)
        self.assertEqual(self.read("pkg/core.py"), original[0])
        self.assertEqual(self.read("use.py"), original[1] + "# raced\n")
        self.assertEqual(bridge.notified, [])

    def test_rename_resyncs_target_the_server_reached_alone(self):
        stub = self.write("pkg/core.pyi", "LIMIT: int\n")
        edit = self.rename_edit()
        edit["documentChanges"].append({"textDocument": {"uri": path_to_uri(stub), "version": 1},
                                        "edits": [_edit(0, 0, 5, "CAP")]})
        bridge = self.fake({"textDocument/prepareRename": {"start": {}, "end": {}}, "textDocument/rename": edit})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP")
        self.assertTrue(out["applied"], out)
        self.assertEqual(len(bridge.synced_by_method["textDocument/rename"]), 2)
        self.assertIn(stub, bridge.synced_by_method["textDocument/rename"][1])
        self.assertEqual(self.read("pkg/core.pyi"), "CAP: int\n")

    def test_rename_on_already_renamed_line_says_done(self):
        # gpt-4o-mini renamed once (every reference), then asked 42 more times per reference.
        self.write("use.py", "from pkg.core import CAP\nprint(CAP, 'LIMIT')\n")
        before = self.read("use.py")
        bridge = self.fake({})
        out = self.call(lsp_rename_handler, path="use.py", line=1, symbol="LIMIT", new_name="CAP")
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["already_renamed"])
        self.assertFalse(out["applied"])
        self.assertIn("every reference", out["hint"])
        self.assertEqual(self.read("use.py"), before)
        self.assertEqual(bridge.calls, [])

    def test_rename_symbol_missing_and_new_name_absent_still_fails(self):
        self.fake({})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=3, symbol="LIMIT", new_name="CAP")
        self.assertEqual(out["error"], "symbol_not_found")

    def test_applied_rename_says_every_reference_done(self):
        self.fake({"textDocument/prepareRename": {"start": {}, "end": {}},
                   "textDocument/rename": self.rename_edit()})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP")
        self.assertTrue(out["applied"], out)
        self.assertIn("every reference", out["hint"])

    def test_repeat_rename_new_name_contains_old_says_done_and_sends_nothing(self):
        # Verifier's case: LIMIT -> MAX_LIMIT next to LIMIT_ALIAS; a repeat must not rename LIMIT_ALIAS.
        self.write("use.py", "from pkg.core import MAX_LIMIT, LIMIT_ALIAS\nprint(LIMIT_ALIAS + MAX_LIMIT)\n")
        before = self.read("use.py")
        bridge = self.fake({"textDocument/prepareRename": {"start": {}, "end": {}},
                            "textDocument/rename": self.rename_edit()})
        out = self.call(lsp_rename_handler, path="use.py", line=2, symbol="LIMIT", new_name="MAX_LIMIT")
        self.assertTrue(out.get("already_renamed"), out)
        self.assertEqual(bridge.calls, [])
        self.assertEqual(self.read("use.py"), before)

    def test_symbol_only_inside_longer_identifier_is_not_found(self):
        self.write("use.py", "from pkg.core import LIMIT_ALIAS\nprint(LIMIT_ALIAS)\n")
        bridge = self.fake({"textDocument/prepareRename": {"start": {}, "end": {}},
                            "textDocument/rename": self.rename_edit()})
        out = self.call(lsp_rename_handler, path="use.py", line=2, symbol="LIMIT", new_name="CAP")
        self.assertEqual(out["error"], "symbol_not_found", out)
        self.assertEqual(bridge.calls, [])

    def test_invalid_new_name_on_its_own_line_is_invalid_not_done(self):
        self.write("pkg/kw.py", "def run():\n    return 1\n")
        self.fake({})
        out = self.call(lsp_rename_handler, path="pkg/kw.py", line=1, symbol="missing", new_name="def")
        self.assertEqual(out["error"], "invalid_name", out)

    def test_rename_resource_op_writes_nothing(self):
        edit = self.rename_edit()
        edit["documentChanges"].append({"kind": "rename", "oldUri": path_to_uri(self.use), "newUri": "file:///x.py"})
        self.fake({"textDocument/prepareRename": {"start": {}, "end": {}}, "textDocument/rename": edit})
        out = self.call(lsp_rename_handler, path="pkg/core.py", line=1, symbol="LIMIT", new_name="CAP")
        self.assertEqual(out["error"], "unsupported_edit")
        self.assertEqual(self.read("pkg/core.py"), "LIMIT = 2\n\ndef budget():\n    return LIMIT\n")

    def test_bridge_error_mapped(self):
        def boom(*_a, **_k):
            raise lsp_bridge.BridgeError("timeout", "slow")

        self.fake({})
        with mock.patch.object(lsp_bridge, "request", boom):
            out = self.call(lsp_definition_handler, path="use.py", line=2, symbol="LIMIT")
        self.assertEqual(out["error"], "timeout")


class BridgeGateTests(unittest.TestCase):
    def test_in_git_worktree_false_without_host(self):
        with patch_modules({"agent.lsp.workspace": None}):
            self.assertFalse(lsp_bridge.in_git_worktree(__file__))

    def test_available_without_host(self):
        with patch_modules({"agent.lsp": None}):
            svc, reason = lsp_bridge.available()
        self.assertIsNone(svc)
        self.assertTrue(reason.startswith("lsp_unavailable"))


if __name__ == "__main__":
    unittest.main()
