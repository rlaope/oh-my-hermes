"""Offline contracts plus browser-backed measurements for the frontend phone-check toolkit."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

from _local_package import load_local_package
from _module_patch import patch_modules
from _toolkit_path_guard import (POSIX_ONLY, assert_alias_does_not_exempt_links_below,
                                 assert_only_system_aliases_trusted)

load_local_package()
ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = ROOT / "src/skills/frontend_toolkit"
SCRIPT = TOOLKIT / "scripts/phone_check.py"
CLEAN = TOOLKIT / "examples/phone-clean.html"
OVERFLOW = TOOLKIT / "examples/phone-overflow.html"


def helper_api():
    spec = importlib.util.spec_from_file_location("phone_check_helper", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def browser_available():
    """True only when Playwright imports and its Chromium actually launches."""
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception:
        return False
    return True


def fake_playwright(on_goto):
    """A stand-in for `playwright.sync_api` whose `goto` runs `on_goto` first.

    Its `screenshot` behaves like the real one: given a path it opens it with
    "wb" (truncating an existing file and following a link), and it always
    returns the image bytes.
    """
    error = type("FakePlaywrightError", (Exception,), {})
    raw = {"viewport_meta": None, "scroll_width": 390, "client_width": 390, "inner_width": 390,
           "document_height": 844, "past_right": [], "past_right_total": 0, "data_selector": ".row",
           "first_data_y": 120, "first_action_y": 200, "targets_total": 0, "small_targets_total": 0,
           "small_targets": [], "fields_total": 0, "small_inputs_total": 0, "small_inputs": [],
           "measure": []}

    class Page:
        def set_default_timeout(self, *_):
            pass

        def on(self, *_):
            pass

        def goto(self, *_, **__):
            on_goto()

        def wait_for_timeout(self, *_):
            pass

        def evaluate(self, *_):
            return raw

        def screenshot(self, path=None, **_):
            data = b"\x89PNG fake shot"
            if path is not None:
                with open(path, "wb") as handle:
                    handle.write(data)
            return data

    class Browser:
        def new_context(self, **_):
            return self

        def new_cdp_session(self, *_):
            # No DevTools session here: the script goes on without the
            # browser's content width, as it does when the protocol refuses.
            raise error("no protocol session in the stand-in")

        def new_page(self):
            return Page()

        def close(self):
            pass

    class Runner:
        def __init__(self):
            self.chromium = self

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def launch(self, **_):
            return Browser()

    module = types.ModuleType("playwright.sync_api")
    module.Error = error
    module.sync_playwright = Runner
    return {"playwright": types.ModuleType("playwright"), "playwright.sync_api": module}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_main(self, *argv):
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            code = helper_api().main([str(item) for item in argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def refused(self, argv, message):
        code, out, err = self.run_main(*argv)
        self.assertEqual(code, 2, err)
        self.assertIn(message, err)
        self.assertEqual(out, "")


class OfflineCliTests(Fixture):
    def test_help_works_without_site_packages(self):
        result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), "--help"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--data", result.stdout)

    def test_argument_refusals(self):
        page = str(CLEAN)
        cases = (
            ([page, "--width", "50"], "--width"),
            ([page, "--height", "99999"], "--height"),
            ([page, "--timeout", "0"], "--timeout"),
            ([page, "--timeout", "9999"], "--timeout"),
            ([page, "--scroll", "-1", "--shot", self.root / "a.png"], "--scroll"),
            ([page, "--scroll", "10"], "--scroll only applies"),
            ([page, "--data", "  "], "--data"),
            ([page, "--measure", " , "], "--measure"),
            ([page, "--browser", self.root / "missing"], "--browser"),
            ([self.root / "nope.html"], "not a file"),
            ([self.root], "index.html"),
            ([ROOT / "README.md"], ".html"),
            (["ftp://example.com/x.html"], "http(s)"),
            ([page, "--shot", self.root / "a.txt"], ".png"),
            ([page, "--shot", self.root / "no-parent" / "a.png"], "parent"),
        )
        for argv, message in cases:
            with self.subTest(argv=argv):
                self.refused(argv, message)

    def test_shot_to_existing_path_or_link_refused(self):
        existing = self.root / "taken.png"
        existing.write_bytes(b"x")
        self.refused([str(CLEAN), "--shot", existing], "new path")
        link = self.root / "link.png"
        link.symlink_to(existing)
        self.refused([str(CLEAN), "--shot", link], "symlink")
        self.assertEqual(existing.read_bytes(), b"x")

    def test_shot_path_that_appears_during_load_is_left_untouched(self):
        # The early check passes, then a file or a link is created while the
        # page loads; the write must refuse instead of replacing or following it.
        victim = self.root / "victim.txt"
        victim.write_bytes(b"victim bytes")
        for name in ("file", "symlink"):
            with self.subTest(planted=name):
                shot = self.root / f"shot-{name}.png"

                def plant(shot=shot, name=name):
                    if name == "file":
                        shot.write_bytes(b"planted bytes")
                    else:
                        shot.symlink_to(victim)

                with patch_modules(fake_playwright(plant)):
                    code, out, err = self.run_main(CLEAN, "--shot", shot)
                self.assertEqual(code, 2, err)
                self.assertEqual(out, "")
                self.assertIn("--shot", err)
                self.assertEqual(victim.read_bytes(), b"victim bytes")
                if name == "file":
                    self.assertEqual(shot.read_bytes(), b"planted bytes")
                else:
                    self.assertTrue(shot.is_symlink())

    @POSIX_ONLY
    def test_shot_parent_replaced_by_a_link_during_load_is_refused(self):
        folder = self.root / "out"
        folder.mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()

        def swap_parent():
            folder.rmdir()
            folder.symlink_to(elsewhere, target_is_directory=True)

        with patch_modules(fake_playwright(swap_parent)):
            code, _, err = self.run_main(CLEAN, "--shot", folder / "shot.png")
        self.assertEqual(code, 2, err)
        self.assertIn("symlink", err)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def swap_after_the_last_path_check(self, api, swap):
        """Patch the write's own path check so that `swap` runs right after it passed."""
        checked = api.safe_path

        def safe_path_then_swap(value):
            path = checked(value)
            swap()
            return path

        return mock.patch.object(api, "safe_path", safe_path_then_swap)

    @POSIX_ONLY
    def test_shot_directory_swapped_for_a_link_after_the_last_check_is_refused(self):
        # The path check and the create are two steps. A directory above the
        # file that becomes a link between them must not move the write.
        for depth in ("parent", "grandparent"):
            with self.subTest(swapped=depth):
                api = helper_api()
                if not api.can_hold_directory():
                    self.skipTest("this platform cannot create a file inside a held directory")
                top = self.root / f"out-{depth}"
                folder = top / "inner" if depth == "grandparent" else top
                folder.mkdir(parents=True)
                elsewhere = self.root / f"elsewhere-{depth}"
                (elsewhere / "inner").mkdir(parents=True)

                def swap(top=top, folder=folder, elsewhere=elsewhere):
                    if folder != top:
                        folder.rmdir()
                    top.rmdir()
                    top.symlink_to(elsewhere, target_is_directory=True)

                with self.swap_after_the_last_path_check(api, swap), self.assertRaises(api.RunError) as refused:
                    api.write_new_file(folder / "shot.png", b"bytes")
                self.assertIn("symlink", str(refused.exception))
                self.assertEqual([p for p in elsewhere.rglob("*") if p.is_file()], [])

    def test_shot_write_failure_leaves_no_partial_file(self):
        api = helper_api()
        shot = self.root / "shot.png"

        def failing_fdopen(fd, *_, **__):
            os.close(fd)
            raise OSError(28, "No space left on device")

        with mock.patch.object(api.os, "fdopen", failing_fdopen):
            with self.assertRaises(api.RunError) as refused:
                api.write_new_file(shot, b"bytes")
        self.assertIn("could not be written", str(refused.exception))
        self.assertFalse(os.path.lexists(shot))

    def test_shot_is_written_where_a_directory_cannot_be_held(self):
        # Windows has no directory-relative create; the second check and the
        # exclusive create still write a new file and refuse an existing one.
        api = helper_api()
        shot = self.root / "shot.png"
        with mock.patch.object(api, "can_hold_directory", lambda: False):
            self.assertEqual(api.write_new_file(shot, b"bytes"), shot)
            self.assertEqual(shot.read_bytes(), b"bytes")
            with self.assertRaises(api.RunError):
                api.write_new_file(shot, b"other")
        self.assertEqual(shot.read_bytes(), b"bytes")

    @POSIX_ONLY
    def test_unsearchable_directory_is_refused_not_crashed(self):
        if os.geteuid() == 0:
            self.skipTest("root can search every directory")
        locked = self.root / "locked"
        (locked / "inner").mkdir(parents=True)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o700)
        self.refused([CLEAN, "--shot", locked / "inner" / "shot.png"], "path could not be checked")

    @POSIX_ONLY
    def test_directory_walk_keeps_one_descriptor_and_none_when_refused(self):
        api = helper_api()
        live = set()  # descriptor numbers are reused, so track what is open now
        real_open, real_close = os.open, os.close

        def tracking_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            live.add(fd)
            return fd

        def tracking_close(fd):
            live.discard(fd)
            real_close(fd)

        def walk(path):
            with mock.patch.object(api.os, "open", tracking_open), \
                    mock.patch.object(api.os, "close", tracking_close):
                return api.open_directory_without_links(path)

        top = self.root.resolve()
        deep = top / "a" / "b"
        deep.mkdir(parents=True)
        held = walk(deep)
        self.addCleanup(real_close, held)
        self.assertEqual(live, {held})
        self.assertTrue(os.path.samestat(os.fstat(held), os.stat(deep)))

        live.clear()
        (top / "a" / "link").symlink_to(deep)
        with self.assertRaises(OSError):
            walk(top / "a" / "link" / "below")
        self.assertEqual(live, set())

    @POSIX_ONLY
    def test_directory_walk_interrupted_before_any_statement_leaves_no_descriptor(self):
        api = helper_api()
        walk_code = api.open_directory_without_links.__code__
        source, first_line = inspect.getsourcelines(api.open_directory_without_links)
        returns = [first_line + node.lineno - 1
                   for node in ast.walk(ast.parse(textwrap.dedent("".join(source))))
                   if isinstance(node, ast.Return)]
        self.assertEqual(len(returns), 1)
        live = set()
        real_open, real_close = os.open, os.close

        def tracking_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            live.add(fd)
            return fd

        def tracking_close(fd):
            live.discard(fd)
            real_close(fd)

        deep = self.root.resolve() / "a" / "b"
        deep.mkdir(parents=True)

        def walk(stop_at=None):
            """Run the walk, raising KeyboardInterrupt just before its `stop_at`-th statement."""
            seen = []

            def local(frame, event, arg):
                if event == "line":
                    seen.append(frame.f_lineno)
                    if len(seen) - 1 == stop_at:
                        raise KeyboardInterrupt
                return local

            def tracer(frame, event, arg):
                return local if frame.f_code is walk_code else None

            previous = sys.gettrace()
            with mock.patch.object(api.os, "open", tracking_open), \
                    mock.patch.object(api.os, "close", tracking_close):
                sys.settrace(tracer)
                try:
                    return api.open_directory_without_links(deep), seen
                finally:
                    sys.settrace(previous)

        held, lines = walk()
        real_close(held)
        live.clear()
        # Every statement up to and including the one that hands the descriptor
        # back. An interrupt that lands in the cleanup after it, or inside a
        # statement, can still drop one descriptor; that is not covered here.
        last = max(index for index, line in enumerate(lines) if line == returns[0])
        self.assertGreater(len(set(lines[:last + 1])), 6, lines)
        for stop_at in range(last + 1):
            with self.subTest(statement=stop_at, line=lines[stop_at] - first_line):
                # Whatever this pass left open is closed before it is judged, so
                # one leak is one failure and nothing stays open after the test.
                left = None
                try:
                    with self.assertRaises(KeyboardInterrupt):
                        walk(stop_at)
                    left = set(live)
                finally:
                    for descriptor in live:
                        real_close(descriptor)
                    live.clear()
                self.assertEqual(left, set())

    def test_shot_is_written_once_when_the_path_stays_new(self):
        shot = self.root / "shot.png"
        with patch_modules(fake_playwright(lambda: None)):
            code, out, err = self.run_main(CLEAN, "--shot", shot)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["shot"], str(shot))
        self.assertEqual(shot.read_bytes(), b"\x89PNG fake shot")

    def test_symlinked_target_refused(self):
        link = self.root / "page.html"
        link.symlink_to(CLEAN)
        self.refused([link], "symlink")

    def test_missing_playwright_is_a_clear_exit_2(self):
        code = (
            "import sys, importlib.util\n"
            "sys.modules['playwright'] = None\n"
            "sys.modules['playwright.sync_api'] = None\n"
            f"spec = importlib.util.spec_from_file_location('pc', {str(SCRIPT)!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            f"raise SystemExit(m.main([{str(CLEAN)!r}]))\n")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("pip install playwright", result.stderr)
        self.assertIn("playwright install chromium", result.stderr)

    def test_only_macos_system_aliases_are_trusted(self):
        api = helper_api()
        assert_only_system_aliases_trusted(self, api.safe_path, api.system_alias, self.root,
                                           "symlink paths", traversal="path traversal")

    @POSIX_ONLY
    def test_a_trusted_alias_does_not_exempt_a_link_below_it(self):
        assert_alias_does_not_exempt_links_below(self, helper_api().safe_path, "symlink paths")


class PureHelperTests(unittest.TestCase):
    def test_overflow_is_measured_against_the_requested_width(self):
        api = helper_api()
        self.assertEqual(api.overflow_px(520, 390), 130)
        self.assertEqual(api.overflow_px(390, 390), 0)
        self.assertEqual(api.overflow_px(300, 390), 0)
        self.assertEqual(api.overflow_px(390.5, 390), 0.5)

    def test_finding_counts_everything_and_lists_a_bounded_few(self):
        api = helper_api()
        examples = [{"path": f"b{i}"} for i in range(25)]
        result = api.finding(25, examples)
        self.assertEqual(result["count"], 25)
        self.assertEqual(len(result["first"]), 20)
        # The count is the page's total, not the length of the example list.
        self.assertEqual(api.finding(7000, examples[:1]), {"count": 7000, "first": examples[:1]})
        self.assertEqual(api.finding(0, []), {"count": 0, "first": []})

    def test_report_counts_come_from_the_page_totals(self):
        # A page with 5001 targets and 5001 fields where only the last of each
        # is undersized: the page script returns totals over all of them and one
        # example each, and the report must carry those totals unchanged.
        api = helper_api()
        args = api.parser().parse_args([str(CLEAN)])
        plan = api.validate(args)
        raw = {"viewport_meta": None, "scroll_width": 390, "client_width": 390, "inner_width": 390,
               "document_height": 844, "past_right": [{"path": "p", "right": 400}] * 20,
               "past_right_total": 5001, "data_selector": ".row", "first_data_y": 120,
               "first_action_y": 200, "targets_total": 5001, "small_targets_total": 1,
               "small_targets": [{"path": "b5000", "width": 43, "height": 44}], "fields_total": 5001,
               "small_inputs_total": 1, "small_inputs": [{"path": "i5000", "font_px": 15}], "measure": []}
        report = api.build_report(args, plan, api.emulation(args), raw, [])
        self.assertEqual((report["small_targets"]["count"], report["small_targets"]["checked"]), (1, 5001))
        self.assertEqual((report["small_inputs"]["count"], report["small_inputs"]["checked"]), (1, 5001))
        self.assertEqual(report["elements_past_right_edge"]["count"], 5001)
        self.assertEqual(len(report["elements_past_right_edge"]["first"]), 20)

    def test_only_text_entry_controls_are_font_checked(self):
        api = helper_api()
        for name, kind in (("textarea", ""), ("select", ""), ("input", ""), ("input", "text"),
                           ("input", "search"), ("input", "email"), ("input", "number"), ("input", "date")):
            self.assertTrue(api.is_text_entry(name, kind), (name, kind))
        for kind in ("checkbox", "radio", "button", "submit", "reset", "file", "image", "range",
                     "color", "hidden", "RADIO"):
            self.assertFalse(api.is_text_entry("input", kind), kind)
        self.assertIn("opts.non_text_types", api.PAGE_SCRIPT)

    def test_first_action_must_reach_into_the_document_area(self):
        api = helper_api()
        self.assertTrue(api.in_document_area(bottom=48, right=120))
        self.assertFalse(api.in_document_area(bottom=-60, right=120))  # skip link parked above
        self.assertFalse(api.in_document_area(bottom=48, right=-1))    # parked left of the page
        self.assertFalse(api.in_document_area(bottom=0, right=120))
        self.assertIn("firstOnPage(opts.action_selector)", api.PAGE_SCRIPT)
        # A control fixed to the viewport is judged by its viewport box, not by box plus scroll.
        self.assertIn("if (fixedToViewport(el)) return r.bottom > 0 && r.right > 0;", api.PAGE_SCRIPT)
        # `position: fixed` under a containing ancestor is not fixed to the viewport.
        self.assertIn("if (!node.offsetParent) return true;", api.PAGE_SCRIPT)

    def test_start_side_follows_the_principal_writing_mode(self):
        api = helper_api()
        self.assertFalse(api.starts_at_right("horizontal-tb", "ltr"))
        self.assertTrue(api.starts_at_right("horizontal-tb", "rtl"))
        self.assertTrue(api.starts_at_right("vertical-rl", "ltr"))
        self.assertTrue(api.starts_at_right("sideways-rl", "ltr"))
        self.assertFalse(api.starts_at_right("vertical-lr", "rtl"))
        # The page script reads the start side from <body>, not from <html>.
        self.assertIn("getComputedStyle(document.body || doc)", api.PAGE_SCRIPT)

    def test_a_page_that_starts_at_the_right_is_reachable_leftward(self):
        # Client 0..120 on an RTL page scrolled to -130 is page -130..-10: on
        # the page, in the left overflow. Past the start edge (390) it is not.
        api = helper_api()
        self.assertTrue(api.in_document_area(bottom=98, right=-10, left=-130, start_edge=390))
        self.assertFalse(api.in_document_area(bottom=68, right=590, left=470, start_edge=390))
        self.assertFalse(api.in_document_area(bottom=-60, right=390, left=270, start_edge=390))
        # A control fixed to the viewport must cross the band the reader pans over.
        self.assertFalse(api.in_document_area(bottom=98, right=-10, left=-130, start_edge=520, fixed=True))
        self.assertTrue(api.in_document_area(bottom=98, right=390, left=270, start_edge=520, fixed=True))
        # The left-to-right rule is unchanged.
        self.assertFalse(api.in_document_area(bottom=48, right=-1))
        self.assertIn("if (startRight) return onPageFromRight(el, r);", api.PAGE_SCRIPT)

    def test_past_edge_note_names_the_left_side_on_a_right_start_page(self):
        api = helper_api()
        args = api.parser().parse_args([str(CLEAN)])
        plan = api.validate(args)
        raw = {"viewport_meta": None, "scroll_width": 520, "client_width": 390, "inner_width": 520,
               "document_height": 844, "past_right": [{"path": "div", "left": -130}], "past_right_total": 1,
               "data_selector": ".row", "first_data_y": None, "first_action_y": 50, "targets_total": 0,
               "small_targets_total": 0, "small_targets": [], "fields_total": 0, "small_inputs_total": 0,
               "small_inputs": [], "measure": [], "start_right": True}
        report = api.build_report(args, plan, api.emulation(args), raw, [])
        self.assertEqual(report["horizontal_overflow_px"], 130)
        self.assertEqual(report["elements_past_right_edge"]["note"], api.PAST_LEFT_EDGE_NOTE)
        self.assertIn("left edge", api.PAST_LEFT_EDGE_NOTE)
        raw["start_right"] = False
        report = api.build_report(args, plan, api.emulation(args), raw, [])
        self.assertEqual(report["elements_past_right_edge"]["note"], api.PAST_EDGE_NOTE)

    def test_page_script_takes_thresholds_and_list_limit_as_arguments(self):
        api = helper_api()
        for name in ("opts.min_target_px", "opts.min_input_font_px", "opts.list_limit"):
            self.assertIn(name, api.PAGE_SCRIPT)
        self.assertNotIn("raw_limit", api.PAGE_SCRIPT)

    def test_measure_list_splits_at_the_top_level(self):
        api = helper_api()
        self.assertEqual(api.split_selectors("header, .a:is(.b, .c) ,[x='1,2']"),
                         ["header", ".a:is(.b, .c)", "[x='1,2']"])

    def test_emulation_flags(self):
        api = helper_api()
        phone = api.emulation(api.parser().parse_args(["x"]))
        self.assertEqual((phone["width"], phone["height"], phone["device_scale_factor"]), (390, 844, 3))
        self.assertTrue(phone["mobile"] and phone["touch"] and phone["user_agent"])
        desk = api.emulation(api.parser().parse_args(["x", "--desktop"]))
        self.assertEqual((desk["width"], desk["height"]), (1440, 900))
        self.assertFalse(desk["mobile"] or desk["touch"])
        self.assertIsNone(desk["user_agent"])
        wide = api.emulation(api.parser().parse_args(["x", "--width", "320", "--height", "600"]))
        self.assertEqual((wide["width"], wide["height"]), (320, 600))


class ResourceTests(unittest.TestCase):
    def test_manifest_digests_match_bytes(self):
        from omh.skills import frontend_support as support
        manifest = json.loads((TOOLKIT / "upstream-manifest.json").read_text())
        self.assertEqual(manifest["schema"], "omh_frontend_toolkit_provenance/v1")
        self.assertEqual(set(manifest["files"]), set(support.TOOLKIT_RESOURCES) - {"upstream-manifest.json"})
        for name, entry in manifest["files"].items():
            digest = hashlib.sha256((TOOLKIT / name).read_bytes()).hexdigest()
            self.assertEqual(entry["local_sha256"], digest, name)
            self.assertEqual(entry["source_sha256"], digest, name)
            self.assertEqual(entry["classification"], "original_omh")
            self.assertEqual(entry["upstream"], [])
        self.assertEqual(support.frontend_toolkit_provenance_manifest()["files"], manifest["files"])

    def test_every_file_on_disk_is_a_declared_resource(self):
        from omh.skills import frontend_support as support
        on_disk = {p.relative_to(TOOLKIT).as_posix() for p in TOOLKIT.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts}
        self.assertEqual(on_disk, set(support.TOOLKIT_RESOURCES))

    def test_support_templates_validate(self):
        from omh.skills import frontend_support as support
        templates = support.frontend_toolkit_support_templates()
        self.assertEqual({t.relative_path for t in templates},
                         {"toolkit/" + p for p in support.TOOLKIT_RESOURCES})
        self.assertEqual({t.skill_name for t in templates}, {"frontend"})

    def test_registered_in_the_builtin_support_inventory(self):
        from omh.skills.support_files import builtin_skill_support_templates
        paths = {t.relative_path for t in builtin_skill_support_templates() if t.skill_name == "frontend"}
        self.assertIn("toolkit/scripts/phone_check.py", paths)

    def test_registered_in_package_data_and_gitattributes(self):
        pyproject = (ROOT / "pyproject.toml").read_text()
        attributes = (ROOT / ".gitattributes").read_text()
        support = (ROOT / "src/skills/frontend_support.py").read_text()
        for line in ("src/skills/frontend_toolkit/** text eol=lf",
                     "skills/omh-frontend/toolkit/** text eol=lf",
                     "agent-skills/omh-frontend/toolkit/** text eol=lf"):
            self.assertIn(line, attributes)
        for name in ("README.md", "LICENSE.upstream", "scripts/phone_check.py", "examples/phone-clean.html",
                     "examples/phone-overflow.html", "upstream-manifest.json"):
            self.assertIn(f'"frontend_toolkit/{name}"', pyproject)
            self.assertIn(f'"{name}"', support)


@unittest.skipUnless(browser_available(), "Playwright with a launchable Chromium is not available")
class BrowserTests(Fixture):
    def measure(self, page, *extra):
        code, out, err = self.run_main(page, *extra)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_overflow_fixture(self):
        report = self.measure(OVERFLOW, "--data", ".row", "--measure", "header,.wide")
        self.assertEqual(report["schema"], "omh_phone_check/v1")
        self.assertEqual(report["emulation"]["mobile"], True)
        self.assertEqual(report["emulation"]["touch"], True)
        self.assertEqual(report["viewport"], {"width": 390, "height": 844, "device_scale_factor": 3})
        self.assertEqual(report["horizontal_overflow_px"], 130)
        self.assertEqual(report["elements_past_right_edge"]["count"], 1)
        self.assertEqual(report["first_data_y"], 600)
        self.assertEqual(report["small_targets"]["count"], 1)
        self.assertEqual(report["small_inputs"]["count"], 1)
        self.assertEqual([m["height_px"] for m in report["measure"]], [600, 40])
        self.assertEqual(report["console_errors"], [])

    def test_clean_fixture(self):
        report = self.measure(CLEAN, "--data", ".row")
        self.assertEqual(report["horizontal_overflow_px"], 0)
        self.assertEqual(report["elements_past_right_edge"]["count"], 0)
        self.assertEqual(report["first_data_y"], 120)
        self.assertEqual(report["small_targets"]["count"], 0)
        self.assertEqual(report["small_inputs"]["count"], 0)

    def test_data_guess_and_not_found_hint(self):
        self.assertEqual(self.measure(CLEAN)["first_data_y"], 120)
        page = self.root / "empty.html"
        page.write_text("<!doctype html><title>t</title><p>no rows</p>")
        report = self.measure(page)
        self.assertEqual(report["first_data_y"], "not_found")
        self.assertIn("--data", report["first_data_hint"])

    def test_desktop_flag_drops_emulation(self):
        report = self.measure(CLEAN, "--desktop")
        self.assertEqual((report["viewport"]["width"], report["viewport"]["height"]), (1440, 900))
        self.assertEqual((report["emulation"]["mobile"], report["emulation"]["touch"]), (False, False))

    def test_console_and_page_errors_reported(self):
        page = self.root / "errors.html"
        page.write_text("<!doctype html><title>t</title><script>console.error('boom');"
                        "setTimeout(() => { throw new Error('late'); }, 0);</script>")
        sources = {e["source"] for e in self.measure(page)["console_errors"]}
        self.assertEqual(sources, {"console", "pageerror"})

    def test_shot_is_first_viewport_only(self):
        shot = self.root / "shot.png"
        self.measure(OVERFLOW, "--shot", shot, "--scroll", "200")
        data = shot.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        self.assertEqual((width, height), (390 * 3, 844 * 3))

    def test_counts_cover_every_element_past_a_few_thousand(self):
        # 5001 targets and 5001 fields; only the last of each is undersized.
        # Every other button is exactly 44 px, the boundary that is not small.
        buttons = "".join('<button style="width:44px;height:44px">b</button>' for _ in range(5000))
        buttons += '<button style="width:43px;height:44px">last</button>'
        fields = "".join('<input style="height:48px;font-size:16px">' for _ in range(5000))
        fields += '<input style="height:48px;font-size:15px">'
        wide = "".join('<div style="width:500px;height:2px"></div>' for _ in range(25))
        page = self.root / "many.html"
        page.write_text('<!doctype html><meta name="viewport" content="width=device-width">'
                        f'<style>body{{margin:0}} button,input{{display:block}}</style>{buttons}{fields}{wide}')
        report = self.measure(page, "--timeout", "120")
        self.assertEqual(report["small_targets"]["checked"], 10002)
        self.assertEqual(report["small_targets"]["count"], 1)
        self.assertEqual(report["small_targets"]["first"][0]["width"], 43)
        self.assertEqual(report["small_inputs"]["checked"], 5001)
        self.assertEqual(report["small_inputs"]["count"], 1)
        self.assertEqual(report["small_inputs"]["first"][0]["font_px"], 15)
        self.assertEqual(report["elements_past_right_edge"]["count"], 25)
        self.assertEqual(len(report["elements_past_right_edge"]["first"]), 20)

    def test_choice_controls_are_not_font_checked(self):
        page = self.root / "choices.html"
        page.write_text('<!doctype html><meta name="viewport" content="width=device-width"><style>'
                        'input{font-size:13.3px;width:48px;height:48px}</style>'
                        + '<input type="radio" name="r">' * 6
                        + '<input type="checkbox"><input type="range"><input type="text">')
        report = self.measure(page)
        self.assertEqual(report["small_inputs"]["checked"], 1)
        self.assertEqual(report["small_inputs"]["count"], 1)
        self.assertEqual(report["small_inputs"]["first"][0]["font_px"], 13.3)

    def test_skip_link_parked_above_the_page_is_not_the_first_action(self):
        page = self.root / "skip.html"
        page.write_text('<!doctype html><meta name="viewport" content="width=device-width"><style>'
                        'body{margin:0} .skip{position:absolute;top:-100px;left:0}'
                        ' main{padding-top:150px}</style>'
                        '<a class="skip" href="#main">Skip to content</a>'
                        '<main id="main"><a href="/start" style="display:block;height:48px">Start</a></main>')
        self.assertEqual(self.measure(page)["first_action_y"], 150)

    def scrolled_page(self, name, fixed_top):
        # The page scrolls itself by 200 px before it is measured, and carries
        # one control fixed to the viewport at `fixed_top`.
        page = self.root / name
        page.write_text('<!doctype html><meta name="viewport" content="width=device-width"><style>'
                        'body{margin:0;min-height:3000px} main{padding-top:150px}'
                        f' .pinned{{position:fixed;top:{fixed_top}px;left:0;display:block;height:48px}}</style>'
                        '<a class="pinned" href="#main">Pinned</a>'
                        '<main id="main"><a href="/start" style="display:block;height:48px">Start</a></main>'
                        '<script>window.scrollTo(0, 200)</script>')
        return page

    def test_fixed_control_parked_above_the_screen_stays_skipped_after_scroll(self):
        # Fixed at -100 px its box is above the screen at every scroll position;
        # adding the scroll offset would report it at 100 instead of skipping it.
        report = self.measure(self.scrolled_page("parked.html", -100))
        self.assertEqual(report["first_action_y"], 150)

    def test_fixed_control_on_screen_is_placed_by_its_viewport_box(self):
        report = self.measure(self.scrolled_page("pinned.html", 20))
        self.assertEqual(report["first_action_y"], 20)

    def contained_page(self, name, containing, fixed_top):
        # A `position: fixed` control under an ancestor that makes its own
        # containing block is fixed to that ancestor and scrolls with the page.
        page = self.root / name
        page.write_text('<!doctype html><meta name="viewport" content="width=device-width"><style>'
                        'body{margin:0;height:2500px} a,button{display:block;width:120px;height:48px}'
                        ' #real{position:absolute;top:150px}</style>'
                        f'<div style="position:absolute;top:0;left:0;width:200px;{containing}">'
                        f'<button style="position:fixed;top:{fixed_top}px">In the page</button></div>'
                        '<button id="real">Real</button>'
                        '<script>addEventListener("load", () => scrollTo(0, 200))</script>')
        return page

    def test_fixed_under_a_containing_ancestor_is_a_page_control(self):
        # Scrolled by 200 px, the control sits at document y 20 (viewport -180).
        # It is reachable by scrolling back, so it is the first action, at 20;
        # read as fixed to the viewport it was skipped and 150 was reported.
        for name, containing in (("transform", "transform:translateZ(0)"), ("filter", "filter:blur(0px)"),
                                 ("contain", "contain:paint"), ("will-change", "will-change:transform")):
            with self.subTest(containing=name):
                report = self.measure(self.contained_page(f"contained-{name}.html", containing, 20))
                self.assertEqual(report["first_action_y"], 20)

    def test_fixed_under_a_containing_ancestor_is_placed_in_page_px(self):
        # At 350 px inside the ancestor the control is at document y 350
        # (viewport 150 after the scroll); read as fixed to the viewport it
        # was reported at its viewport position.
        page = self.contained_page("contained-low.html", "transform:translateZ(0)", 350)
        report = self.measure(page, "--data", "div > button")
        self.assertEqual(report["first_action_y"], 350)
        self.assertEqual(report["first_data_y"], 350)

    def test_fixed_ancestor_inside_a_containing_ancestor_is_followed_to_the_top(self):
        # The control's own fixed ancestor is fixed to a transformed box, and
        # that box is fixed to the viewport: the control does not scroll.
        page = self.root / "nested.html"
        page.write_text('<!doctype html><meta name="viewport" content="width=device-width"><style>'
                        'body{margin:0;height:2500px} a{display:block;width:120px;height:48px}</style>'
                        '<div style="position:fixed;top:30px;left:0;transform:translateZ(0)">'
                        '<div style="position:fixed;top:10px;left:0"><a href="#x">Pinned</a></div></div>'
                        '<script>addEventListener("load", () => scrollTo(0, 200))</script>')
        self.assertEqual(self.measure(page)["first_action_y"], 40)

    def page(self, name, root_attrs, style, body):
        path = self.root / name
        path.write_text(f'<html {root_attrs}><head><meta name="viewport" content="width=device-width,'
                        'initial-scale=1"><style>body{margin:0;height:2000px} a,button{display:block;'
                        f'width:120px;height:48px;box-sizing:border-box}} {style}</style></head>{body}</html>')
        return path

    def left_overflow_page(self, name, root_attrs='dir="rtl"', body_attrs="", first="right:400px",
                           scroll=""):
        # A 520 px absolutely placed row on a page that starts at the right
        # overflows 130 px to the left; Chromium starts it at scrollX -130.
        # `#first` at right 400 px sits inside that left overflow at y 50.
        script = f'<script>addEventListener("load", () => scrollTo({scroll}))</script>' if scroll else ""
        return self.page(name, root_attrs,
                         ".wide{position:absolute;top:0;right:0;width:520px;height:10px}"
                         f" #first{{position:absolute;top:50px;{first}}}"
                         " #real{position:absolute;top:300px;right:0}",
                         f'<body {body_attrs}><div class="wide"></div><button id="first">first</button>'
                         f'<button id="real">real</button>{script}</body>')

    def test_rtl_page_overflowing_left_is_measured_where_the_reader_pans(self):
        # Before: the control in the left overflow was skipped (300) and the
        # root's scrollWidth missed the absolutely placed row (overflow 0).
        cases = (("plain", "right:400px", ""), ("scrolled", "right:400px", "-130, 200"),
                 ("visible-first", "right:0", "-130, 200"))
        for label, first, scroll in cases:
            with self.subTest(case=label):
                report = self.measure(self.left_overflow_page(f"rtl-{label}.html", first=first, scroll=scroll),
                                      "--data", "#first")
                self.assertEqual(report["first_action_y"], 50)
                self.assertEqual(report["first_data_y"], 50)
                self.assertEqual(report["horizontal_overflow_px"], 130)
                past = report["elements_past_right_edge"]
                self.assertIn({"path": "body > div", "left": -130}, past["first"])
                self.assertIn("left edge", past["note"])

    def test_the_start_side_is_read_from_body(self):
        # <body dir="rtl"> and body{direction:rtl} start at the right while
        # <html> still computes ltr; <html dir="rtl"><body dir="ltr"> starts at
        # the left and is measured exactly as a left-to-right page.
        for label, root, body in (("body-dir", "", 'dir="rtl"'), ("body-css", "", 'style="direction:rtl"')):
            with self.subTest(case=label):
                report = self.measure(self.left_overflow_page(f"{label}.html", root, body))
                self.assertEqual((report["first_action_y"], report["horizontal_overflow_px"]), (50, 130))
        ltr_body = self.page("ltr-body.html", 'dir="rtl"',
                             ".wide{position:absolute;top:0;left:0;width:520px;height:10px}"
                             " #first{position:absolute;top:50px;left:400px}",
                             '<body dir="ltr"><div class="wide"></div><button id="first">first</button></body>')
        report = self.measure(ltr_body)
        self.assertEqual((report["first_action_y"], report["horizontal_overflow_px"]), (50, 0))
        self.assertEqual(report["elements_past_right_edge"]["first"][0], {"path": "body > div", "right": 520})

    def test_rtl_control_parked_past_the_right_edge_stays_skipped(self):
        # An RTL page cannot scroll past its right edge, so a link parked
        # 200 px beyond it is off the page, with or without a left overflow.
        parked = "#parked{position:absolute;top:20px;right:-200px} #real{position:absolute;top:150px;right:0}"
        body = '<a id="parked" href="#">Parked</a><button id="real">real</button>'
        wide = '<div style="position:absolute;top:0;right:0;width:520px;height:10px"></div>'
        for label, extra in (("no-overflow", ""), ("left-overflow", wide)):
            with self.subTest(case=label):
                report = self.measure(self.page(f"parked-{label}.html", 'dir="rtl"', parked, extra + body))
                self.assertEqual(report["first_action_y"], 150)

    def test_rtl_scrolled_page_keeps_the_fixed_skip_link_skipped(self):
        # Scrolled down 200 px: a fixed skip link parked above stays skipped
        # and the control in the left overflow at document y 250 is first.
        page = self.page("rtl-fixed.html", 'dir="rtl"',
                         ".wide{position:absolute;top:0;right:0;width:520px;height:10px}"
                         " #skip{position:fixed;top:-100px;right:0} #pinned{position:fixed;top:400px;left:0}"
                         " #first{position:absolute;top:250px;right:400px}"
                         " #real{position:absolute;top:600px;right:0}",
                         '<div class="wide"></div><a id="skip" href="#">Skip</a>'
                         '<button id="pinned">left of the screen</button><button id="first">first</button>'
                         '<button id="real">real</button>'
                         '<script>addEventListener("load", () => scrollTo(0, 200))</script>')
        report = self.measure(page)
        self.assertEqual(report["first_action_y"], 250)
        self.assertEqual(report["horizontal_overflow_px"], 130)

    def test_vertical_rl_page_starts_at_the_right(self):
        # Vertical-rl text starts at the right edge: the first column of
        # controls sits in the left overflow at client x 0 and is the first action.
        page = self.page("vertical.html", 'style="writing-mode:vertical-rl"',
                         "body{height:auto} .wide{width:520px;height:10px}",
                         '<div class="wide"></div><button id="first">first</button>')
        report = self.measure(page)
        self.assertEqual(report["first_action_y"], 0)
        self.assertEqual(report["horizontal_overflow_px"], 250)

    def parked_left_page(self, name, style, body):
        # Standards mode, right-to-left: a skip link parked at left:-9999px,
        # y 20, the way a left-to-right site hides one, and the control the
        # reader meets first at y 300.
        path = self.root / name
        path.write_text('<!doctype html><html dir="rtl"><head><meta name="viewport" content="width=device-width,'
                        'initial-scale=1"><style>body{margin:0;height:2000px} a,button{display:block;'
                        'width:120px;height:48px;box-sizing:border-box}'
                        ' #skip{position:absolute;top:20px;left:-9999px} #real{position:absolute;top:300px;right:0}'
                        f' {style}</style></head><body>{body}<button id="real">real</button></body></html>')
        return path

    def test_rtl_link_parked_left_inside_a_clipping_box_is_not_the_first_action(self):
        # No scroll or pan shows a link clipped away by its container, so the
        # reachable button at 300 is first; counting every box left of the
        # start edge reported the link at 20. The same link in a box the
        # reader can scroll is reachable and stays first.
        box = ".box{position:absolute;top:0;right:0;width:390px;height:100px;overflow-x:%s}"
        body = '<div class="box"><a id="skip" href="#">Skip</a></div>'
        for overflow, expected in (("hidden", 300), ("auto", 20)):
            with self.subTest(overflow=overflow):
                report = self.measure(self.parked_left_page(f"box-{overflow}.html", box % overflow, body))
                self.assertEqual(report["first_action_y"], expected)
                self.assertEqual(report["horizontal_overflow_px"], 0)

    def test_rtl_link_parked_left_of_a_held_viewport_is_not_the_first_action(self):
        # With overflow-x hidden on the root the pan stops 1170 px out, far
        # short of the link; without it the same link is 9999 px of real left
        # overflow the reader can pan to.
        body = '<a id="skip" href="#">Skip</a>'
        for label, style, expected in (("held", "html,body{overflow-x:hidden}", 300), ("open", "", 20)):
            with self.subTest(viewport=label):
                report = self.measure(self.parked_left_page(f"viewport-{label}.html", style, body))
                self.assertEqual(report["first_action_y"], expected)

    def test_rtl_reachable_left_overflow_counts_beside_a_clipped_link(self):
        # One page with both: the clipped link at 20 is skipped and the control
        # in the 130 px left overflow at 50 is first, not the button at 300.
        page = self.parked_left_page(
            "both.html",
            ".box{position:absolute;top:0;right:0;width:390px;height:100px;overflow:hidden}"
            " .wide{position:absolute;top:0;right:0;width:520px;height:10px}"
            " #first{position:absolute;top:50px;right:400px}",
            '<div class="wide"></div><div class="box"><a id="skip" href="#">Skip</a></div>'
            '<button id="first">first</button>')
        report = self.measure(page)
        self.assertEqual(report["first_action_y"], 50)
        self.assertEqual(report["horizontal_overflow_px"], 130)

    def test_rtl_link_the_browser_has_not_rendered_yet_counts_when_scrolling_reaches_it(self):
        # `content-visibility: auto` leaves off-screen content unrendered, and an
        # unrendered box has no part an observer reports. Scrolling down renders
        # the link at 5000, so it is the first action. The same box inside a
        # container that clips it away is never rendered, and a link parked far
        # left inside it stays behind the box's own paint clip: the button at
        # 300 is first on both.
        lazy = ('<div style="position:absolute;top:5000px;right:0;width:300px;height:200px;'
                'content-visibility:auto"><a id="first" href="#"%s>first</a></div>')
        clip = '<div style="position:absolute;top:0;right:0;width:390px;height:100px;overflow:hidden">%s</div>'
        parked = ' style="position:absolute;left:-9999px"'
        # A box with `overflow-clip-margin` paints past its own edge: the box
        # lies off the page to the right, its link 500 px to its left is on it.
        past_edge = ('<div style="position:absolute;top:5000px;right:-500px;width:300px;height:200px;'
                     'content-visibility:auto;overflow-clip-margin:1000px">'
                     '<a id="first" href="#" style="position:absolute;left:-500px;top:0">first</a></div>')
        cases = (("reachable", lazy % "", 5000), ("clipped", clip % (lazy % ""), 300),
                 ("parked-left", lazy % parked, 300), ("painted-past-the-box", past_edge, 5000))
        for label, body, expected in cases:
            with self.subTest(lazy=label):
                report = self.measure(self.parked_left_page(f"lazy-{label}.html", "", body))
                self.assertEqual(report["first_action_y"], expected)

    def test_rtl_link_in_a_box_that_scrolls_the_other_way_counts(self):
        # A reversed flex line scrolls from 0 to a negative position. At 0 the
        # link sits above the scrollport (152) or left of it (500) and the reader
        # scrolls to it. The twins park a link on the side the box cannot scroll
        # toward, where it is never shown and the button at 300 is first.
        box = "position:absolute;top:500px;right:0;width:300px;height:100px;"
        tall = '<div style="height:400px;flex:none"></div>'
        wide = '<div style="width:600px;flex:none"></div>'
        link = '<a id="first" href="#" style="flex:none">first</a>'
        cases = (
            ("column-reverse", f'<div style="{box}overflow-y:auto;display:flex;flex-direction:column-reverse">'
                               f'{tall}{link}</div>', 152),
            ("column-reverse-below", f'<div style="{box}overflow-y:auto;display:flex;flex-direction:column-reverse">'
                                     '<div style="height:448px;flex:none"></div>'
                                     '<a id="first" href="#" style="position:absolute;top:300px;right:0">first</a></div>',
             300),
            ("row-reverse", f'<div dir="ltr" style="{box}overflow-x:auto;display:flex;flex-direction:row-reverse">'
                            f'{wide}{link}</div>', 500),
            ("row-left-parked", f'<div dir="ltr" style="{box}overflow-x:auto">'
                                '<a id="first" href="#" style="position:absolute;left:-200px;top:0">first</a>'
                                '<div style="width:720px;height:10px"></div></div>', 300),
            ("legacy-box-reverse", f'<div dir="ltr" style="{box}overflow:auto;display:-webkit-box;'
                                   '-webkit-box-direction:reverse"><div style="width:600px;height:20px"></div>'
                                   '<a id="first" href="#">first</a></div>', 500),
            ("vertical-lr", f'<div style="{box}overflow:auto;writing-mode:vertical-lr">'
                            '<div style="width:600px;height:50px"></div><a id="first" href="#">first</a></div>', 552),
        )
        for label, body, expected in cases:
            with self.subTest(box=label):
                report = self.measure(self.parked_left_page(f"reverse-{label}.html", "", body))
                self.assertEqual(report["first_action_y"], expected)

    def test_rtl_link_painted_left_of_a_page_that_does_not_scroll_there_is_skipped(self):
        # The box holds its layout (`content-visibility: auto`) and paints past
        # its edge, so its link is drawn left of page x 0 at y 100 while the page
        # stays 390 px wide: no pan reaches it, and the button at 300 is first.
        body = ('<div style="position:absolute;top:-500px;right:-500px;width:300px;height:200px;'
                'content-visibility:auto;overflow-clip-margin:1000px">'
                '<a id="first" href="#" style="position:absolute;left:-1000px;top:600px">first</a></div>')
        report = self.measure(self.parked_left_page("painted-left.html", "", body))
        self.assertEqual(report["horizontal_overflow_px"], 0)
        self.assertEqual(report["first_action_y"], 300)

    def no_scrolling_element_page(self, name, body, root=""):
        # Quirks mode with `overflow-x: auto` on both <html> and <body>: the
        # browser reports no scrolling element, and the root's scrollWidth stays
        # 390 however far the page pans.
        path = self.root / name
        path.write_text('<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>'
                        f'html,body{{direction:rtl;overflow-x:auto}} body{{margin:0;height:2000px}} {root}'
                        ' a,button{display:block;position:absolute;width:120px;height:48px}'
                        f' #real{{top:300px;right:0}}</style></head><body>{body}<button id="real">real</button>'
                        '</body></html>', encoding="utf-8")
        return path

    def test_rtl_page_with_no_scrolling_element_and_a_zoomed_root_keeps_its_edges(self):
        # A zoom on the root changes the root's clientWidth (195 at zoom 2, 780
        # at 0.5) while the page still starts at the viewport's right edge, so
        # an edge taken from the root is off by the zoom. At zoom 2 a link a
        # contained box paints left of a page that does not scroll was counted
        # (200); at zoom 0.5 a link on screen was dropped (150).
        painted = ('<div style="position:absolute;left:0;top:100px;width:300px;height:200px;contain:layout">'
                   '<a id="first" href="#" style="left:-200px;top:0">first</a></div>')
        report = self.measure(self.no_scrolling_element_page("zoom-painted-left.html", painted, "html{zoom:2}"))
        self.assertEqual(report["first_action_y"], 600)
        on_screen = ('<div style="position:absolute;left:-500px;top:100px;width:120px;height:60px;overflow:hidden">'
                     '<a id="first" href="#" style="left:0;top:0;width:700px">first</a></div>')
        report = self.measure(self.no_scrolling_element_page("zoom-on-screen.html", on_screen, "html{zoom:.5}"))
        self.assertEqual(report["first_action_y"], 50)

    def test_rtl_page_with_no_scrolling_element_and_a_narrow_root_keeps_its_start_edge(self):
        # A width on the root shrinks its clientWidth to 200 while the page
        # still starts at x 390: a small link at the start edge lay "past" an
        # edge taken from the root and was dropped.
        body = '<a id="first" href="#" style="top:100px;right:0;width:60px">first</a>'
        report = self.measure(self.no_scrolling_element_page("narrow-root.html", body, "html{width:200px}"))
        self.assertEqual(report["first_action_y"], 100)

    def test_rtl_page_with_no_scrolling_element_keeps_a_link_that_is_on_screen(self):
        # The page loads panned 500 px left and the link's unclipped part is on
        # screen at y 100; held to the root's width of 390 it was dropped.
        body = ('<div style="position:absolute;left:-500px;top:100px;width:120px;height:60px;overflow:hidden">'
                '<a id="first" href="#" style="left:0;top:0;width:700px">first</a></div>')
        page = self.no_scrolling_element_page("no-scroller-on-screen.html", body)
        self.assertEqual(self.measure(page)["first_action_y"], 100)
        # Without the phone emulation the same page loads unpanned, and the
        # browser reports its content box 500 px left of the layout viewport.
        self.assertEqual(self.measure(page, "--desktop", "--width", "390")["first_action_y"], 100)

    def test_rtl_page_with_no_scrolling_element_still_skips_a_link_painted_past_its_range(self):
        # Nothing widens this page, so the link a contained box paints left of
        # page x 0 cannot be panned to: with no far end at all it would count.
        body = ('<div style="position:absolute;top:-500px;right:-500px;width:300px;height:200px;'
                'content-visibility:auto;overflow-clip-margin:1000px">'
                '<a id="first" href="#" style="left:-1000px;top:600px">first</a></div>')
        report = self.measure(self.no_scrolling_element_page("no-scroller-painted-left.html", body))
        self.assertEqual(report["first_action_y"], 300)

    def test_rtl_measuring_runs_no_scroll_listener_of_the_page(self):
        # The link sits in a reversed scroll box whose listener loads more
        # content on the first scroll. Finding the link must not scroll the box:
        # the input and button the listener adds were counted as the page's own.
        body = ('<div id="box" style="position:absolute;top:500px;right:0;width:300px;height:100px;'
                'overflow-y:auto;display:flex;flex-direction:column-reverse">'
                '<div style="height:400px;flex:none"></div><a id="first" href="#" style="flex:none">first</a></div>'
                '<script>document.getElementById("box").addEventListener("scroll", () => {'
                'const more = document.createElement("article");'
                'more.innerHTML = "<input style=\'font-size:12px\'><button>loaded</button>";'
                'document.body.prepend(more); }, {once: true});</script>')
        report = self.measure(self.parked_left_page("scroll-listener.html", "", body))
        self.assertEqual(report["first_action_y"], 152)
        self.assertEqual(report["small_targets"]["checked"], 2)
        self.assertEqual(report["small_inputs"]["checked"], 0)

    def test_rtl_measuring_calls_no_scroll_and_fires_no_scroll_event(self):
        # The page reports every scroll call, every focus call (focusing
        # scrolls), every write to scrollTop or
        # scrollLeft and every scroll event as a console error. A reversed scroll box that hides the first link is the
        # case the script once scrolled; a scroll made after the counts are
        # taken would pass the count assertions and is caught here.
        body = ('<div id="box" style="position:absolute;top:500px;right:0;width:300px;height:100px;'
                'overflow-y:auto;display:flex;flex-direction:column-reverse">'
                '<div style="height:400px;flex:none"></div><a id="first" href="#" style="flex:none">first</a></div>'
                '<script>for (const [owner, names] of [[window, ["scrollTo", "scrollBy", "scroll"]],'
                ' [Element.prototype, ["scrollTo", "scrollBy", "scroll", "scrollIntoView", "scrollIntoViewIfNeeded"]],'
                ' [HTMLElement.prototype, ["focus"]]]) {'
                ' for (const name of names) { const native = owner[name];'
                ' owner[name] = function (...args) { console.error("scroll call " + name);'
                ' return native.apply(this, args); }; } }'
                ' for (const name of ["scrollTop", "scrollLeft"]) {'
                ' const native = Object.getOwnPropertyDescriptor(Element.prototype, name);'
                ' Object.defineProperty(Element.prototype, name, {get: native.get,'
                ' set(value) { console.error("scroll set " + name); native.set.call(this, value); }}); }'
                ' for (const type of ["scroll", "scrollend"]) {'
                ' document.addEventListener(type, () => console.error("event " + type), true); }</script>')
        report = self.measure(self.parked_left_page("no-scroll.html", "", body))
        self.assertEqual(report["first_action_y"], 152)
        self.assertEqual(report["console_errors"], [])

    def test_left_to_right_neighbours_are_unchanged(self):
        # These pass on the code before the right-to-left change as well; they
        # pin the left-to-right numbers the change must not move.
        parked = self.page("ltr-parked.html", "",
                           "#parked{position:absolute;top:20px;left:-200px} #real{position:absolute;top:150px;left:0}",
                           '<a id="parked" href="#">Parked</a><button id="real">real</button>')
        self.assertEqual(self.measure(parked)["first_action_y"], 150)
        hidden = self.page("hidden.html", 'style="overflow-x:hidden"',
                           "body{overflow-x:hidden} .wide{width:600px;height:20px}",
                           '<div class="wide"></div><button>b</button>')
        clip = self.page("clip.html", "", "body{overflow-x:clip} .wide{width:600px;height:20px}",
                         '<div class="wide"></div><button>b</button>')
        self.assertEqual(self.measure(hidden)["horizontal_overflow_px"], 0)
        self.assertEqual(self.measure(clip)["horizontal_overflow_px"], 210)

    def test_bad_selector_is_exit_2(self):
        self.refused([str(CLEAN), "--data", "li["], "measuring failed")

    def test_navigation_failure_is_exit_2(self):
        self.refused(["http://127.0.0.1:9/", "--timeout", "5"], "navigation failed")


if __name__ == "__main__":
    unittest.main()
