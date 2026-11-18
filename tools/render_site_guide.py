"""Render the model-list region of the Start Guide (site/guide/index.html).

The guide shows three categories with the models they try, in order, plus one
"provider said no" example. Those names come from the shipped recommendation
catalog, so the page never names a model the catalog no longer ships. Pages
re-renders the region on every deploy (like the skill guide), so a model
onboarding PR does not have to touch the site.

    uv run python tools/render_site_guide.py --write
    uv run python tools/render_site_guide.py --check
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path
import re

from omh.catalogs.model_chain_table import MODEL_DISPLAY_LABELS
from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS

ROOT = Path(__file__).resolve().parents[1]

PAGE = ROOT / "site" / "guide" / "index.html"
BEGIN = "<!-- omh:guide-chains:begin (generated: uv run python tools/render_site_guide.py --write; source: src/coding/model_recommendations.py) -->"
END = "<!-- omh:guide-chains:end -->"

# (category, i18n key of its plain-words purpose)
CATEGORIES = (
    ("quick", "guide.route.cat.quick"),
    ("deep", "guide.route.cat.deep"),
    ("visual-engineering", "guide.route.cat.visual"),
)
FALLBACK_CATEGORY = "deep"
LOGOS = {
    "claude": "claude-color.svg",
    "gpt": "openai.svg",
    "glm": "zhipu-color.svg",
    "kimi": "moonshot.svg",
    "gemini": "gemini-color.svg",
    "deepseek": "deepseek-color.svg",
    "grok": "grok.svg",
}
PURPOSE_EN = {
    "guide.route.cat.quick": "Short tasks",
    "guide.route.cat.deep": "Strong default",
    "guide.route.cat.visual": "Screens and frontend",
}


def _chain(category: str) -> list[dict[str, str]]:
    chain = SHIPPED_MODEL_RECOMMENDATIONS["categories"][category]
    if len(chain) < 2:
        raise ValueError(f"category {category!r} ships fewer than two models")
    return chain


def _model(entry: dict[str, str], cls: str = "") -> str:
    family = entry["model_family"]
    logo = LOGOS.get(family)
    if logo is None:
        raise ValueError(f"no logo for model family {family!r}: add it to LOGOS in tools/render_site_guide.py")
    label = html.escape(MODEL_DISPLAY_LABELS[entry["model_alias"]])
    effort = html.escape(entry["reasoning_effort"])
    extra = f" {cls}" if cls else ""
    effort_tag = f'<em class="g-eff g-eff--{effort}">{effort}</em>' if effort else ""
    return (
        f'<span class="g-model{extra}"><img src="../assets/models/{logo}" alt="" width="20" height="20">'
        f"<span>{label}</span>{effort_tag}</span>"
    )


def render_region() -> str:
    lines = [BEGIN, '<div class="g-cats">']
    for category, key in CATEGORIES:
        chain = _chain(category)
        lines.append('  <article class="g-cat rv">')
        lines.append(
            f'    <header><code>{category}</code><span data-i18n="{key}">{PURPOSE_EN[key]}</span></header>'
        )
        lines.append('    <ol class="g-chain">')
        for rank, entry in enumerate(chain, 1):
            lines.append(f'      <li><b>{rank}</b>{_model(entry)}</li>')
        lines.append("    </ol>")
        lines.append("  </article>")
    lines.append("</div>")
    first, second = _chain(FALLBACK_CATEGORY)[:2]
    lines.append('<div class="g-fall rv" aria-label="Fallback example" data-fall>')
    lines.append(
        f'  <span class="g-fall__lab caps"><code>{FALLBACK_CATEGORY}</code></span>'
    )
    lines.append(
        f'  <div class="g-fall__step g-fall__step--no">{_model(first)}'
        '<small data-i18n="guide.route.no">Provider said no</small></div>'
    )
    lines.append('  <span class="g-fall__arrow" aria-hidden="true"></span>')
    lines.append(
        f'  <div class="g-fall__step g-fall__step--go">{_model(second)}'
        '<small data-i18n="guide.route.runs">Next in line runs</small></div>'
    )
    lines.append("</div>")
    lines.append(END)
    return "\n".join(lines)


_REGION = re.compile(re.escape(BEGIN.split(" (")[0]) + r".*?" + re.escape(END), re.S)


def apply(text: str) -> str:
    if not _REGION.search(text):
        raise SystemExit(f"{PAGE}: guide-chains region markers not found")
    return _REGION.sub(lambda _m: render_region(), text, count=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    current = PAGE.read_text(encoding="utf-8")
    rendered = apply(current)
    if args.write:
        if rendered != current:
            PAGE.write_text(rendered, encoding="utf-8")
        return 0
    if rendered != current:
        print(f"{PAGE.relative_to(ROOT)} is stale: run uv run python tools/render_site_guide.py --write")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
