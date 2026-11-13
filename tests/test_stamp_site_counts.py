"""tools/stamp_site_counts.py bakes the GitHub star count into the built site.

The Pages workflow runs it on `_site` before the upload and again every six
hours on a schedule, so the header never shows a count frozen at the last
commit. These tests pin the placeholder rewrite, the compact format shared
with site/app.js, the keep-the-old-value path on an API failure, and that
the token never reaches the output.
"""

from __future__ import annotations

import contextlib
import email.message
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ghs_secretTokenValue1234567890"


def _stamper():
    spec = importlib.util.spec_from_file_location(
        "stamp_site_counts_under_test", ROOT / "tools" / "stamp_site_counts.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class StampSiteCountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _stamper()

    def _run(self, site: Path, urlopen) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": TOKEN}), mock.patch.object(
            self.mod.urllib.request, "urlopen", urlopen
        ), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.mod.main([str(site)])
        return code, out.getvalue()

    def _site(self, tmp: str) -> Path:
        site = Path(tmp)
        (site / "docs").mkdir()
        (site / "index.html").write_text(
            '<a class="nav__icon" href="x"><svg></svg><b data-stars>4.9k</b></a>\n'
            '<a data-gh-star><span class="n" data-star-count hidden></span></a>\n'
            '<b data-stars="4900" class="k">4.9k</b>\n'
            '<b data-stars-note>keep me</b>\n',
            encoding="utf-8",
        )
        (site / "docs" / "index.html").write_text("<p>no counts here</p>\n", encoding="utf-8")
        return site

    def test_compact_matches_app_js(self) -> None:
        cases = {
            # 5350 / 1000 is 5.3499... in binary, so JS toFixed(1) gives 5.3.
            0: "0", 999: "999", 1000: "1k", 1049: "1k", 1050: "1.1k", 4900: "4.9k",
            5311: "5.3k", 5350: "5.3k", 5450: "5.5k", 99_949: "99.9k", 99_950: "100k",
            100_000: "100k", 123_456: "123k", 1_000_000: "1M", 1_250_000: "1.3M",
        }
        for n, shown in cases.items():
            self.assertEqual(self.mod.compact(n), shown, n)
        app_js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn('if (n >= 1e5) return Math.round(n / 1e3) + "k";', app_js)

    def test_every_placeholder_is_stamped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = self._site(tmp)
            payload = b'{"stargazers_count": 5311, "forks": 1}'
            code, out = self._run(site, lambda request, timeout: _Response(payload))
            page = (site / "index.html").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn('<b data-stars="5311">5.3k</b>', page)
        self.assertIn('<span class="n" data-star-count="5311" hidden>5.3k</span>', page)
        self.assertIn('<b data-stars="5311" class="k">5.3k</b>', page)
        self.assertIn("<b data-stars-note>keep me</b>", page)
        self.assertNotIn("4.9k", page)
        self.assertIn("5311 (5.3k) stamped into 3 placeholder(s) in 1 file(s)", out)
        self.assertNotIn(TOKEN, out)

    def test_request_sends_the_token_only_as_a_header(self) -> None:
        seen = {}

        def urlopen(request, timeout):
            seen["auth"] = request.get_header("Authorization")
            seen["url"] = request.full_url
            return _Response(b'{"stargazers_count": 12}')

        with tempfile.TemporaryDirectory() as tmp:
            self._run(self._site(tmp), urlopen)
        self.assertEqual(seen["auth"], f"Bearer {TOKEN}")
        self.assertEqual(seen["url"], "https://api.github.com/repos/rlaope/oh-my-hermes")

    def test_api_failure_keeps_the_old_value_and_hides_the_token(self) -> None:
        failures = (
            urllib.error.HTTPError(
                "https://api.github.com/repos/rlaope/oh-my-hermes", 403,
                f"rate limited for {TOKEN}", email.message.Message(), None,
            ),
            urllib.error.URLError(f"no route ({TOKEN})"),
            TimeoutError("timed out"),
        )
        # HTTPError wraps a temporary file; left open, its finalizer warns into whichever
        # later test happens to be capturing stderr when the garbage collector runs.
        self.addCleanup(failures[0].close)
        for failure in failures:
            with self.subTest(type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                site = self._site(tmp)
                before = (site / "index.html").read_text(encoding="utf-8")

                def urlopen(request, timeout, failure=failure):
                    raise failure

                code, out = self._run(site, urlopen)
                self.assertEqual(code, 0)
                self.assertEqual((site / "index.html").read_text(encoding="utf-8"), before)
                self.assertIn("kept the existing values", out)
                self.assertNotIn(TOKEN, out)

    def test_bad_payload_keeps_the_old_value(self) -> None:
        for payload in (b"not json", b"[]", b'{"stargazers_count": "5311"}', b'{"stargazers_count": true}'):
            with self.subTest(payload), tempfile.TemporaryDirectory() as tmp:
                site = self._site(tmp)
                before = (site / "index.html").read_text(encoding="utf-8")
                code, out = self._run(site, lambda request, timeout, p=payload: _Response(p))
                self.assertEqual(code, 0)
                self.assertEqual((site / "index.html").read_text(encoding="utf-8"), before)
                self.assertIn("kept the existing values", out)

    def test_pages_workflow_bakes_and_refreshes_the_count(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '17 */6 * * *'", workflow)
        self.assertIn("run: python tools/stamp_site_counts.py _site", workflow)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", workflow)
        self.assertLess(workflow.index("cp -R site/. _site/"), workflow.index("stamp_site_counts.py _site"))
        self.assertLess(workflow.index("stamp_site_counts.py _site"), workflow.index("upload-pages-artifact"))
        self.assertIn('- "tools/stamp_site_counts.py"', workflow)

    def test_home_page_has_one_star_code_path(self) -> None:
        page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        self.assertRegex(page, r'<b data-stars="\d+">[^<]+</b>')
        self.assertNotIn("stargazers_count", page)
        self.assertNotIn("api.github.com/repos/rlaope/oh-my-hermes')", page)


if __name__ == "__main__":
    unittest.main()
