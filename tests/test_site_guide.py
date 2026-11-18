"""Start Guide page (site/guide/): structure, translations, and the generated model lists.

The guide is the one page a new visitor is sent to, so these pin what it must
keep: every section it promises, a Start Guide link beside Docs in each
header, all four languages for every key it uses, and model lists that match
the shipped recommendation catalog.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from omh.catalogs.model_chain_table import MODEL_DISPLAY_LABELS
from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
GUIDE = SITE / "guide" / "index.html"
GUIDE_I18N = SITE / "guide" / "guide-i18n.js"
LANGS = ("en", "ko", "ja", "zh")
SECTIONS = ("what", "install", "routing", "dag", "fresh", "tui", "omher", "more")


def _guide_strings() -> dict[str, dict[str, str]]:
    text = GUIDE_I18N.read_text(encoding="utf-8")
    body = text[text.index("})({") + 3 : text.rindex(");")]
    # The object literal uses bare locale keys; quote them to read it as JSON.
    return json.loads(re.sub(r"(?m)^(\s+)(en|ko|ja|zh):", r'\1"\2":', body))


def _site_keys() -> set[str]:
    text = (SITE / "i18n.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s{4}"([^"]+)": \{', text, re.M))


class SiteGuideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = GUIDE.read_text(encoding="utf-8")

    def test_every_section_and_its_rail_link_is_present(self) -> None:
        for section in SECTIONS:
            with self.subTest(section=section):
                self.assertRegex(self.page, rf'<section class="[^"]*" id="{section}"')
                self.assertIn(f'<a href="#{section}">', self.page)

    def test_install_commands_match_the_public_installers(self) -> None:
        for command in (
            "curl -fsSL https://omher.app/install | sh",
            "omh setup",
            "omh model",
            "omh update",
            "irm https://omher.app/install.ps1 | iex",
            "curl -fsSL https://omher.app/omher | sh",
        ):
            with self.subTest(command=command):
                self.assertIn(f'data-copy-text="{command}"', self.page.replace("&gt;", ">"))
        for served in ("install", "install.ps1", "omher"):
            self.assertTrue((SITE / served).is_file(), served)

    def test_every_key_the_page_uses_exists_in_all_four_languages(self) -> None:
        guide = _guide_strings()
        shared = _site_keys()
        used = set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', self.page))
        used |= set(re.findall(r'"(guide\.dag\.(?:wait|run|done))"', (SITE / "guide" / "guide.js").read_text()))
        self.assertTrue(used)
        for key in sorted(used):
            with self.subTest(key=key):
                if key.startswith("guide."):
                    self.assertIn(key, guide)
                    self.assertEqual(set(guide[key]), set(LANGS))
                    for lang in LANGS:
                        self.assertTrue(guide[key][lang].strip(), f"{key}[{lang}]")
                else:
                    self.assertIn(key, shared)

    def test_no_guide_key_is_left_unused(self) -> None:
        used = set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', self.page))
        used |= {"guide.dag.run", "guide.dag.done"}
        self.assertEqual(sorted(set(_guide_strings()) - used), [])

    def test_kept_english_words_are_not_translated(self) -> None:
        guide = _guide_strings()
        for key, values in guide.items():
            en_codes = re.findall(r"<code>([^<]+)</code>", values["en"])
            for lang in LANGS[1:]:
                with self.subTest(key=key, lang=lang):
                    self.assertEqual(sorted(re.findall(r"<code>([^<]+)</code>", values[lang])), sorted(en_codes))

    def test_start_guide_sits_beside_docs_in_every_header(self) -> None:
        home = (SITE / "index.html").read_text(encoding="utf-8")
        topbar = home.split('<header class="topbar topbar--glass"', 1)[1].split("</header>", 1)[0]
        self.assertIn(
            '<a href="docs/" data-i18n="nav.docs">Docs</a>\n      <a class="nav__guide" href="guide/" data-i18n="nav.guide">Start Guide</a>',
            topbar,
        )
        self.assertIn('"nav.guide"', (SITE / "i18n.js").read_text(encoding="utf-8"))
        for page in sorted((SITE / "docs").rglob("index.html")):
            with self.subTest(page=page.relative_to(SITE).as_posix()):
                header = page.read_text(encoding="utf-8").split("</header>", 1)[0]
                depth = len(page.relative_to(SITE / "docs").parts) - 1
                self.assertIn(f'href="{"../" * (depth + 1)}guide/">Start Guide</a>', header)
        guide_header = self.page.split("</header>", 1)[0]
        self.assertIn('href="../docs/" data-i18n="nav.docs"', guide_header)
        self.assertIn('href="./" aria-current="page" data-i18n="nav.guide"', guide_header)

    def test_model_lists_match_the_shipped_catalog(self) -> None:
        region = self.page.split("<!-- omh:guide-chains:begin", 1)[1].split("<!-- omh:guide-chains:end -->", 1)[0]
        categories = SHIPPED_MODEL_RECOMMENDATIONS["categories"]
        for name in ("quick", "deep", "visual-engineering"):
            with self.subTest(category=name):
                card = region.split(f"<code>{name}</code>", 1)[1].split("</ol>", 1)[0]
                shown = re.findall(r"<span>([^<]+)</span><em", card)
                expected = [MODEL_DISPLAY_LABELS[entry["model_alias"]] for entry in categories[name]]
                self.assertEqual(shown, expected)
        first, second = categories["deep"][:2]
        fall = region.split("data-fall", 1)[1]
        self.assertLess(
            fall.index(MODEL_DISPLAY_LABELS[first["model_alias"]]),
            fall.index(MODEL_DISPLAY_LABELS[second["model_alias"]]),
        )

    def test_rendered_region_is_current_and_pages_rerenders_it(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "render_site_guide.py"), "--check"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/render_site_guide.py --write", workflow)
        self.assertLess(
            workflow.index("python tools/render_site_guide.py --write"),
            workflow.index("name: Prepare static site"),
        )
        self.assertIn('"src/coding/model_recommendations.py"', workflow)

    def test_local_assets_exist(self) -> None:
        for ref in re.findall(r'(?:src|poster|href)="(\.\./[^"#?]+)"', self.page):
            target = (GUIDE.parent / ref).resolve()
            if ref.endswith("/"):
                target = target / "index.html"
            with self.subTest(ref=ref):
                self.assertTrue(target.is_file(), ref)
        for ref in ("guide-i18n.js", "guide.js"):
            self.assertTrue((GUIDE.parent / ref).is_file())

    def test_scripts_load_in_order(self) -> None:
        order = [self.page.index(f'src="{s}"') for s in ("../i18n.js", "guide-i18n.js", "../app.js", "guide.js")]
        self.assertEqual(order, sorted(order))


if __name__ == "__main__":
    unittest.main()
