"""Offline contracts plus browser-backed measurements for the frontend phone-check toolkit."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _local_package import load_local_package
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

    def test_target_classification(self):
        api = helper_api()
        self.assertFalse(api.is_small_target(44, 44))
        self.assertTrue(api.is_small_target(43.9, 60))
        self.assertTrue(api.is_small_target(60, 30))
        rects = [{"path": f"b{i}", "width": 30, "height": 30} for i in range(25)]
        rects.append({"path": "ok", "width": 48, "height": 48})
        result = api.small_targets(rects)
        self.assertEqual(result["count"], 25)
        self.assertEqual(len(result["first"]), 20)
        self.assertEqual(api.small_targets([], minimum=10), {"count": 0, "first": []})

    def test_input_classification(self):
        api = helper_api()
        fields = [{"path": "a", "font_px": 15.9}, {"path": "b", "font_px": 16}, {"path": "c", "font_px": 12}]
        self.assertEqual(api.small_inputs(fields)["count"], 2)
        self.assertEqual(api.small_inputs(fields, minimum=12)["count"], 0)

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

    def test_bad_selector_is_exit_2(self):
        self.refused([str(CLEAN), "--data", "li["], "measuring failed")

    def test_navigation_failure_is_exit_2(self):
        self.refused(["http://127.0.0.1:9/", "--timeout", "5"], "navigation failed")


if __name__ == "__main__":
    unittest.main()
