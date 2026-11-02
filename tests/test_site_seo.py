"""Search and share metadata for the omher.app static site.

Every page under site/ is either indexable (canonical URL, Open Graph and
Twitter card, listed in sitemap.xml) or explicitly noindex (absent from the
sitemap). The sitemap, robots.txt, manifest, and share image must exist and
agree with the pages, so a new page cannot ship without metadata and a moved
page cannot leave a dead sitemap entry.
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE = PROJECT_ROOT / "site"
ORIGIN = "https://omher.app"
SHARE_IMAGE = f"{ORIGIN}/assets/og/omh-share.png"


class _HeadCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.title = ""
        self.jsonld: list[str] = []
        self.h1 = 0
        self._in_title = False
        self._in_jsonld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key:
                self.meta[key] = values.get("content", "")
        elif tag == "link":
            self.links.append(values)
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and values.get("type") == "application/ld+json":
            self._in_jsonld = True
            self.jsonld.append("")
        elif tag == "h1":
            self.h1 += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_jsonld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self.jsonld[-1] += data

    def link(self, rel: str) -> dict[str, str] | None:
        for entry in self.links:
            if rel in entry.get("rel", "").split():
                return entry
        return None


def _parse(path: Path) -> _HeadCollector:
    collector = _HeadCollector()
    collector.feed(path.read_text(encoding="utf-8"))
    return collector


def _url_for(path: Path) -> str:
    relative = path.relative_to(SITE).as_posix()
    if relative == "index.html":
        return f"{ORIGIN}/"
    if relative.endswith("/index.html"):
        return f"{ORIGIN}/{relative[: -len('index.html')]}"
    return f"{ORIGIN}/{relative}"


def _sitemap_urls() -> list[str]:
    text = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<loc>([^<]+)</loc>", text)


def _pages() -> list[Path]:
    return sorted(SITE.rglob("*.html"))


def _is_noindex(page: _HeadCollector) -> bool:
    return "noindex" in page.meta.get("robots", "")


def _local(url: str) -> Path:
    path = url[len(ORIGIN):].lstrip("/")
    target = SITE / path
    return target / "index.html" if path == "" or path.endswith("/") else target


class SiteSeoTests(unittest.TestCase):
    def test_every_page_is_indexable_with_metadata_or_marked_noindex(self) -> None:
        for path in _pages():
            page = _parse(path)
            with self.subTest(page=path.relative_to(SITE).as_posix()):
                self.assertTrue(page.title.strip())
                self.assertTrue(page.meta.get("description", "").strip())
                self.assertIsNotNone(page.link("icon"))
                if _is_noindex(page):
                    self.assertIsNone(page.link("canonical"))
                    continue
                canonical = page.link("canonical")
                self.assertIsNotNone(canonical)
                self.assertEqual(canonical["href"], _url_for(path))
                self.assertEqual(page.meta.get("og:url"), _url_for(path))
                self.assertEqual(page.meta.get("og:image"), SHARE_IMAGE)
                self.assertEqual(page.meta.get("twitter:image"), SHARE_IMAGE)
                self.assertEqual(page.meta.get("twitter:card"), "summary_large_image")
                # X previews a bare-domain link only with these; a redesign once dropped
                # the whole share block, so pin the X-specific tags too.
                self.assertEqual(page.meta.get("twitter:site"), "@rlaope")
                self.assertEqual(page.meta.get("og:image:type"), "image/png")
                self.assertEqual(
                    page.meta.get("twitter:image:alt"), page.meta.get("og:image:alt")
                )
                for key in ("og:title", "og:description", "og:site_name", "og:type"):
                    self.assertTrue(page.meta.get(key, "").strip(), key)
                self.assertEqual(page.h1, 1 + (path.parent.name == "hermes-agent-architecture"))

    def test_titles_and_descriptions_fit_search_snippets(self) -> None:
        for path in _pages():
            page = _parse(path)
            if _is_noindex(page):
                continue
            with self.subTest(page=path.relative_to(SITE).as_posix()):
                self.assertLessEqual(len(page.title.strip()), 70)
                self.assertGreaterEqual(len(page.meta["description"].strip()), 50)
                self.assertLessEqual(len(" ".join(page.meta["description"].split())), 230)

    def test_sitemap_lists_exactly_the_indexable_pages(self) -> None:
        indexable = {
            _url_for(path) for path in _pages() if not _is_noindex(_parse(path))
        }
        listed = _sitemap_urls()
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(listed), indexable)
        for url in listed:
            with self.subTest(url=url):
                self.assertTrue(_local(url).is_file())

    def test_robots_allows_crawling_and_names_the_sitemap(self) -> None:
        robots = (SITE / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *", robots)
        self.assertNotRegex(robots, r"(?m)^Disallow: /\s*$")
        self.assertIn(f"Sitemap: {ORIGIN}/sitemap.xml", robots)

    def test_share_image_is_a_1200_by_630_png(self) -> None:
        data = (SITE / "assets" / "og" / "omh-share.png").read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (1200, 630))

    def test_manifest_icons_and_favicon_exist(self) -> None:
        manifest = json.loads((SITE / "site.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "Oh My Hermes")
        for icon in manifest["icons"]:
            with self.subTest(icon=icon["src"]):
                self.assertTrue((SITE / icon["src"].lstrip("/")).is_file())
        self.assertTrue((SITE / "favicon.ico").is_file())

    def test_home_structured_data_names_the_software(self) -> None:
        page = _parse(SITE / "index.html")
        self.assertEqual(len(page.jsonld), 1)
        graph = json.loads(page.jsonld[0])["@graph"]
        kinds = {node["@type"]: node for node in graph}
        self.assertEqual(kinds["WebSite"]["url"], f"{ORIGIN}/")
        software = kinds["SoftwareApplication"]
        self.assertEqual(software["name"], "Oh My Hermes")
        self.assertIn("https://github.com/rlaope/oh-my-hermes", software["sameAs"])
        self.assertEqual(software["image"], SHARE_IMAGE)

    def test_not_found_page_is_noindex(self) -> None:
        page = _parse(SITE / "404.html")
        self.assertTrue(_is_noindex(page))


if __name__ == "__main__":
    unittest.main()
