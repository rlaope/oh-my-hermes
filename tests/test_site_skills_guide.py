"""The public skill guide (site/docs/skills/) is rendered from skills/*/SKILL.md.

The Pages workflow re-renders it on every deploy, so a skill edit never needs a
manual regen. These tests pin what the renderer must keep true on the current
tree: every skill outside the ULW engine gets a card, the ULW engine gets none,
and each card carries the skill's own words.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _renderer():
    spec = importlib.util.spec_from_file_location(
        "render_site_skills_under_test", ROOT / "tools" / "render_site_skills.py"
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class SiteSkillGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _renderer()
        cls.records = cls.mod.records()
        cls.page = cls.mod.render(cls.records)

    def test_every_non_ulw_skill_has_exactly_one_card(self) -> None:
        expected = sorted(
            p.parent.name
            for p in (ROOT / "skills").glob("*/SKILL.md")
            if not (p.parent.name == "dag-ulw" or p.parent.name.startswith("ulw-"))
        )
        cards = re.findall(r'<details class="skill-card" id="([^"]+)"', self.page)
        self.assertEqual(sorted(cards), expected)
        self.assertIn(f'<span id="skill-count">{len(expected)}</span>', self.page)

    def test_ulw_engine_is_left_out(self) -> None:
        cards = re.findall(r'<details class="skill-card" id="([^"]+)"', self.page)
        self.assertFalse([c for c in cards if c == "dag-ulw" or c.startswith("ulw-")])

    def test_cards_carry_the_skill_text(self) -> None:
        for rec in self.records:
            with self.subTest(skill=rec["name"]):
                self.assertTrue(rec["hook"].strip())
                self.assertTrue(rec["why"] or rec["summary"])
                self.assertIn(rec["lane"], {lane for lane, _, _ in self.mod.LANES})

    def test_shared_rail_lines_do_not_repeat_across_cards(self) -> None:
        counts: dict[str, int] = {}
        for rec in self.records:
            for line in rec["done"]:
                counts[line] = counts.get(line, 0) + 1
        self.assertFalse({line: n for line, n in counts.items() if n >= self.mod.SHARED_LINE})

    def test_lane_counts_add_up(self) -> None:
        chips = re.findall(r'data-lane-filter="(\w+)"[^>]*>[^<]*<span>(\d+)</span>', self.page)
        totals = dict(chips)
        self.assertEqual(int(totals.pop("all")), sum(int(n) for n in totals.values()))

    def test_committed_page_exists_and_is_linked_from_docs(self) -> None:
        self.assertTrue(self.mod.PAGE.is_file())
        docs = (ROOT / "site" / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="skills/"', docs)

    def test_pages_workflow_refreshes_the_guide(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/render_site_skills.py --write", workflow)
        self.assertIn('"skills/**"', workflow)


if __name__ == "__main__":
    unittest.main()
