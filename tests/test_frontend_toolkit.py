"""Offline contracts plus browser-backed measurements for the frontend phone-check toolkit."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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
        from omh.skills import frontend_toolkit_support as support
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
        from omh.skills import frontend_toolkit_support as support
        on_disk = {p.relative_to(TOOLKIT).as_posix() for p in TOOLKIT.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts}
        self.assertEqual(on_disk, set(support.TOOLKIT_RESOURCES))

    def test_support_templates_validate(self):
        from omh.skills import frontend_toolkit_support as support
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
        support = (ROOT / "src/skills/frontend_toolkit_support.py").read_text()
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

    def test_bad_selector_is_exit_2(self):
        self.refused([str(CLEAN), "--data", "li["], "measuring failed")

    def test_navigation_failure_is_exit_2(self):
        self.refused(["http://127.0.0.1:9/", "--timeout", "5"], "navigation failed")


if __name__ == "__main__":
    unittest.main()
