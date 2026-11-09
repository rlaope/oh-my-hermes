"""Render the public skill guide at site/docs/skills/index.html.

The page is built from the generated tap pack (`skills/*/SKILL.md`), so it
never states anything a skill body does not. The ULW engine (`ulw-*`,
`dag-ulw`) has its own section on the home page and is left out here.

    uv run python tools/render_site_skills.py --write
    uv run python tools/render_site_skills.py --check
"""
from __future__ import annotations

import argparse
import html
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
PAGE = ROOT / "site" / "docs" / "skills" / "index.html"

# Lane order and short labels follow the `Workflow Lane` line every skill body carries.
LANES = (
    ("Intent -> plan", "plan", "Plan and decide"),
    ("Coding handoff", "code", "Code, review and ship"),
    ("Research and company ops", "research", "Research and company ops"),
    ("Materials and visual summaries", "materials", "Materials and visuals"),
    ("Automation and status", "ops", "Automation and status"),
    ("Retained knowledge", "memory", "Memory and knowledge"),
)
LANE_FALLBACK = "Research and company ops"
MAX_TRIGGERS = 6
MAX_BULLETS = 3
SHARED_LINE = 3


def excluded(name: str) -> bool:
    return name == "dag-ulw" or name.startswith("ulw-")


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    fields: dict[str, str] = {}
    if not match:
        return fields
    for line in match.group(1).splitlines():
        found = re.match(r"\s*(name|description|category|role|phase):\s*(.*)$", line)
        if found and found.group(1) not in fields:
            value = found.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            fields[found.group(1)] = value
    return fields


def _sections(text: str) -> dict[str, str]:
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    parts = re.split(r"^## +(.+?)\s*$", body, flags=re.M)
    sections = {"_intro": re.sub(r"\A\s*# .*\n", "", parts[0]).strip()}
    for index in range(1, len(parts) - 1, 2):
        sections.setdefault(parts[index].strip(), parts[index + 1].strip())
    return sections


def _paragraph(block: str) -> str:
    for chunk in re.split(r"\n\s*\n", block or ""):
        chunk = chunk.strip()
        if chunk and not chunk.startswith(("- ", "* ", "1. ", "Strong routing signals")):
            return " ".join(line.strip() for line in chunk.splitlines())
    return ""


def _bullets(block: str) -> list[str]:
    items: list[str] = []
    for line in (block or "").splitlines():
        found = re.match(r"\s*(?:[-*]|\d+\.)\s+(.*)$", line)
        if found and not line.startswith((" ", "\t")):
            items.append(found.group(1).strip())
        elif items and line.strip() and line.startswith((" ", "\t")):
            items[-1] += " " + line.strip()
    return items


def _lane(sections: dict[str, str]) -> str:
    found = re.search(r"Current lane: \*\*(.+?)\*\*", sections.get("Workflow Lane", ""))
    lane = found.group(1) if found else LANE_FALLBACK
    return lane if lane in {entry[0] for entry in LANES} else LANE_FALLBACK


def _example(block: str) -> tuple[str, str]:
    good = (block or "").split("Bad example:")[0]
    prompt = re.search(r"- Prompt:\s*(.+)", good)
    expected = re.search(r"- Expected behavior:\s*(.+)", good)
    return (prompt.group(1).strip() if prompt else "", expected.group(1).strip() if expected else "")


def _summary(description: str) -> tuple[str, str, list[str]]:
    text = re.sub(r"^\[omh\]\s*", "", description)
    triggers: list[str] = []
    said = re.search(r"\s*Use when the user says:\s*(.+)$", text)
    if said:
        text = text[: said.start()].strip()
        triggers = [t.strip().rstrip(".") for t in said.group(1).split(",") if t.strip()]
    hook, _, rest = text.partition(": ")
    if not rest:
        return text, "", triggers
    rest = rest[0].upper() + rest[1:]
    return hook.strip(), rest.strip(), triggers


def skill_record(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    front = _frontmatter(text)
    sections = _sections(text)
    hook, summary, triggers = _summary(front.get("description", ""))
    why = _paragraph(sections.get("Why This Exists", ""))
    if not why:
        why = _paragraph(sections.get("_intro", ""))
    when = re.sub(r"^Use (?:this skill )?when\s+", "", _paragraph(sections.get("When to Use", "")))
    when = when[:1].upper() + when[1:]
    steps = _bullets(sections.get("Procedure", "")) or _bullets(sections.get("Default Behavior", ""))
    prompt, expected = _example(sections.get("Examples", ""))
    return {
        "name": front.get("name") or path.parent.name,
        "role": front.get("role", ""),
        "hook": hook,
        "summary": summary,
        "triggers": triggers[:MAX_TRIGGERS],
        "lane": _lane(sections),
        "why": why,
        "when": when,
        "steps": steps[:4],
        "avoid": _bullets(sections.get("Do Not Use When", ""))[:MAX_BULLETS],
        "prompt": prompt,
        "expected": expected,
        "done": _bullets(sections.get("Completion Checklist", "")),
    }


def records(root: Path = SKILLS) -> list[dict]:
    paths = sorted(p for p in root.glob("*/SKILL.md") if not excluded(p.parent.name))
    raw = [skill_record(p) for p in paths]
    # Checklist lines shared by many skills are the common rail, not what this
    # skill checks; keep only the lines that say something about the skill itself.
    seen: dict[str, int] = {}
    for rec in raw:
        for line in rec["done"]:
            seen[line] = seen.get(line, 0) + 1
    for rec in raw:
        rec["done"] = [line for line in rec["done"] if seen[line] < SHARED_LINE][:MAX_BULLETS]
    return raw


def _inline(text: str, names: set[str]) -> str:
    out: list[str] = []
    for index, piece in enumerate(re.split(r"`([^`]+)`", text)):
        if index % 2:
            code = html.escape(piece)
            if piece in names:
                out.append(f'<a class="skill-ref" href="#{code}"><code>{code}</code></a>')
            else:
                out.append(f"<code>{code}</code>")
        else:
            escaped = html.escape(piece, quote=False)
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped))
    return "".join(out)


def _card(rec: dict, names: set[str], lane_key: str) -> str:
    name = html.escape(rec["name"])
    blocks: list[str] = []
    if rec["summary"]:
        blocks.append(f'<p class="skill-card__lead">{_inline(rec["summary"], names)}</p>')
    if rec["why"]:
        blocks.append(f'<h4>Why it exists</h4><p>{_inline(rec["why"], names)}</p>')
    if rec["when"]:
        blocks.append(f'<h4>Use it when</h4><p>{_inline(rec["when"], names)}</p>')
    if rec["steps"]:
        items = "".join(f"<li>{_inline(s, names)}</li>" for s in rec["steps"])
        blocks.append(f"<h4>How it runs</h4><ol>{items}</ol>")
    if rec["prompt"]:
        expected = f'<p class="skill-example__result">{_inline(rec["expected"], names)}</p>' if rec["expected"] else ""
        blocks.append(
            '<h4>Example</h4><div class="skill-example">'
            f'<p class="skill-example__prompt">{_inline(rec["prompt"], names)}</p>{expected}</div>'
        )
    if rec["avoid"]:
        items = "".join(f"<li>{_inline(s, names)}</li>" for s in rec["avoid"])
        blocks.append(f"<h4>Not for</h4><ul>{items}</ul>")
    if rec["done"]:
        items = "".join(f"<li>{_inline(s, names)}</li>" for s in rec["done"])
        blocks.append(f"<h4>Done when</h4><ul>{items}</ul>")
    if rec["triggers"]:
        chips = "".join(f"<code>{html.escape(t)}</code>" for t in rec["triggers"])
        blocks.append(f'<p class="skill-card__say"><span>Say</span>{chips}</p>')
    source = f"https://github.com/rlaope/oh-my-hermes/blob/main/skills/{name}/SKILL.md"
    blocks.append(f'<p class="skill-card__source"><a href="{source}">Read the full SKILL.md</a></p>')
    search = html.escape(" ".join([rec["name"], rec["hook"], rec["summary"], *rec["triggers"]]).lower())
    return (
        f'<details class="skill-card" id="{name}" data-lane="{lane_key}" data-search="{search}">'
        f'<summary><span class="skill-card__name">{name}</span>'
        f'<span class="skill-card__hook">{_inline(rec["hook"], names)}</span></summary>'
        f'<div class="skill-card__body">{"".join(blocks)}</div></details>'
    )


HEAD = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>OMH skills · What each skill does | Oh My Hermes</title>
    <meta name="description" content="{description}">
    <link rel="canonical" href="https://omher.app/docs/skills/">
    <meta property="og:type" content="article">
    <meta property="og:site_name" content="Oh My Hermes">
    <meta property="og:title" content="OMH skills · What each skill does">
    <meta property="og:description" content="{description}">
    <meta property="og:url" content="https://omher.app/docs/skills/">
    <meta property="og:image" content="https://omher.app/assets/og/omh-share.png">
    <meta property="og:image:type" content="image/png">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta property="og:image:alt" content="Oh My Hermes: the coding harness with Hermes Agent wired into IDE.">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="OMH skills · What each skill does">
    <meta name="twitter:description" content="{description}">
    <meta name="twitter:image" content="https://omher.app/assets/og/omh-share.png">
    <meta name="twitter:image:alt" content="Oh My Hermes: the coding harness with Hermes Agent wired into IDE.">
    <meta name="twitter:site" content="@rlaope">
    <meta name="twitter:creator" content="@rlaope">
    <link rel="icon" href="../../favicon.ico" sizes="48x48">
    <link rel="icon" type="image/png" sizes="96x96" href="../../assets/favicon-96.png">
    <link rel="apple-touch-icon" href="../../assets/omh-logo-pinklight-180.png">
    <link rel="manifest" href="../../site.webmanifest">
    <meta name="theme-color" content="#04070c">
    <link rel="stylesheet" href="../../styles.css">
  </head>
"""

GITHUB_ICON = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2C6.48 2 2 6.58 2 12.22c0 4.52 2.87 8.35 6.85 9.7.5.09.68-.22.68-.49v-1.73c-2.78.62-3.37-1.37-3.37-1.37-.45-1.18-1.11-1.5-1.11-1.5-.91-.64.07-.63.07-.63 1 .07 1.53 1.06 1.53 1.06.9 1.56 2.35 1.11 2.92.85.09-.66.35-1.11.63-1.37-2.22-.26-4.55-1.14-4.55-5.06 0-1.12.39-2.03 1.03-2.75-.1-.26-.45-1.31.1-2.71 0 0 .84-.28 2.75 1.05A9.37 9.37 0 0 1 12 6.92c.85 0 1.7.12 2.5.35 1.9-1.33 2.74-1.05 2.74-1.05.55 1.4.2 2.45.1 2.71.64.72 1.03 1.63 1.03 2.75 0 3.93-2.34 4.79-4.57 5.05.36.32.68.94.68 1.9v2.8c0 .27.18.58.69.48A10.06 10.06 0 0 0 22 12.22C22 6.58 17.52 2 12 2Z"></path></svg>'
)

SCRIPT = """
    <script>
      (() => {
        const input = document.getElementById("skill-search");
        const chips = [...document.querySelectorAll("[data-lane-filter]")];
        const cards = [...document.querySelectorAll(".skill-card")];
        const groups = [...document.querySelectorAll(".skill-lane")];
        const count = document.getElementById("skill-count");
        let lane = "all";
        const apply = () => {
          const words = input.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
          let shown = 0;
          for (const card of cards) {
            const hit = (lane === "all" || card.dataset.lane === lane)
              && words.every((w) => card.dataset.search.includes(w));
            card.hidden = !hit;
            if (hit) shown += 1;
          }
          for (const group of groups) {
            group.hidden = !group.querySelector(".skill-card:not([hidden])");
          }
          count.textContent = String(shown);
        };
        input.addEventListener("input", apply);
        for (const chip of chips) {
          chip.addEventListener("click", () => {
            lane = chip.dataset.laneFilter;
            for (const other of chips) other.setAttribute("aria-pressed", String(other === chip));
            apply();
          });
        }
        document.getElementById("skill-expand").addEventListener("click", (event) => {
          const open = event.currentTarget.getAttribute("aria-pressed") !== "true";
          event.currentTarget.setAttribute("aria-pressed", String(open));
          event.currentTarget.textContent = open ? "Collapse all" : "Expand all";
          for (const card of cards) if (!card.hidden) card.open = open;
        });
        const openFromHash = () => {
          const card = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
          if (!card || !card.classList.contains("skill-card")) return;
          card.hidden = false;
          card.open = true;
          card.scrollIntoView({ block: "start", behavior: "instant" });
        };
        window.addEventListener("hashchange", openFromHash);
        window.addEventListener("load", openFromHash);
      })();
    </script>
"""


def render(recs: list[dict]) -> str:
    names = {r["name"] for r in recs}
    total = len(recs)
    description = (
        f"All {total} OMH skills outside the ULW engine, grouped by work lane: what each one does, "
        "when to use it, an example request, and what done looks like."
    )
    by_lane: dict[str, list[dict]] = {full: [] for full, _, _ in LANES}
    for rec in recs:
        by_lane[rec["lane"]].append(rec)

    chips = [f'<button type="button" class="skill-filter" data-lane-filter="all" aria-pressed="true">All <span>{total}</span></button>']
    toc = []
    groups = []
    for full, key, label in LANES:
        members = by_lane[full]
        if not members:
            continue
        chips.append(
            f'<button type="button" class="skill-filter" data-lane-filter="{key}" aria-pressed="false">'
            f"{html.escape(label)} <span>{len(members)}</span></button>"
        )
        toc.append(f'<a href="#lane-{key}">{html.escape(label)}</a>')
        cards = "\n".join("          " + _card(r, names, key) for r in members)
        groups.append(
            f'        <section class="docs-section skill-lane" id="lane-{key}" data-lane-group="{key}">\n'
            f'          <p class="eyebrow">{len(members)} skills</p>\n'
            f"          <h2>{html.escape(label)}</h2>\n"
            f"{cards}\n"
            "        </section>"
        )

    toc_html = "\n        ".join(toc)
    return (
        HEAD.format(description=html.escape(description))
        + f"""  <body class="docs-page skills-page">
    <!-- generated: uv run python tools/render_site_skills.py --write; source: skills/*/SKILL.md -->
    <a class="skip-link" href="#content">Skip to content</a>
    <header class="topbar topbar--solid" aria-label="Primary">
      <a class="brand brand--link" href="../../">OMH</a>
      <nav class="nav" aria-label="Primary navigation">
        <a href="../">Docs</a>
        <a aria-current="page" href="./">Skills</a>
        <a href="../hermes-agent-architecture/">Architecture</a>
        <a class="nav__icon" href="https://github.com/rlaope/oh-my-hermes" aria-label="Open OMH on GitHub" title="GitHub repository">
          {GITHUB_ICON}
        </a>
      </nav>
    </header>

    <main class="docs-shell" id="content" tabindex="-1">
      <aside class="docs-toc docs-toc--desktop" aria-label="Skill lanes">
        <a href="#start">Overview</a>
        {toc_html}
      </aside>

      <article class="docs-content">
        <header class="docs-hero docs-hero--clean" id="start">
          <p class="eyebrow">Skill guide</p>
          <h1>Every OMH skill, in plain words.</h1>
          <p>
            {total} skills, grouped by the kind of work they take on. Open a card to read what the
            skill is for, when it fits, a request that triggers it, and what has to be true before
            it calls the work done. You never run these by hand: ask Hermes in your own words, or
            name the skill (<code>/omh-plan</code>), and Hermes loads the right one. The ULW engine
            (<code>ulw-*</code>, <code>dag-ulw</code>) has its own section on the
            <a href="../../#workflows">home page</a>.
          </p>
        </header>

        <div class="skill-tools" role="search">
          <label class="skill-search">
            <span class="sr-only">Search skills</span>
            <input id="skill-search" type="search" placeholder="Search: budget, sprite, review" autocomplete="off">
          </label>
          <p class="skill-tools__count"><span id="skill-count">{total}</span> shown</p>
          <button type="button" class="skill-filter skill-filter--ghost" id="skill-expand" aria-pressed="false">Expand all</button>
          <div class="skill-filters" aria-label="Filter by lane">
            {''.join(chips)}
          </div>
        </div>

"""
        + "\n\n".join(groups)
        + """
      </article>
    </main>

    <footer class="footer"><span>Generated from each skill's SKILL.md on main. The skill text is the source of truth.</span><span><a href="../">Back to docs</a></span></footer>
"""
        + SCRIPT
        + """  </body>
</html>
"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render(records())
    current = PAGE.read_text(encoding="utf-8") if PAGE.is_file() else ""
    if args.write:
        PAGE.parent.mkdir(parents=True, exist_ok=True)
        PAGE.write_text(expected, encoding="utf-8")
        print(f"wrote {PAGE.relative_to(ROOT)} ({len(records())} skills)")
        return
    if current != expected:
        print(f"stale: {PAGE.relative_to(ROOT)}; run tools/render_site_skills.py --write")
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()
