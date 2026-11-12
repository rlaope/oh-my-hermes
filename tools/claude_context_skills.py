"""Count the skill rows in a saved Claude Code `/context` report. Maintainer-only.

Usage:
    claude -p "/context" > context.md     # in the project to measure
    uv run python tools/claude_context_skills.py context.md [--json]

Claude Code lists each skill's name and description inside a budget and drops
descriptions past it (https://code.claude.com/docs/en/skills#skill-descriptions-are-cut-short).
Under `### Skills`, `/context` prints one `| <name> | <source> | <tokens> |` row
per listed skill; a row whose tokens read `< 20` is counted name-only here. A
description of about 45 characters or less also reads `< 20`, so a name-only
count is an upper bound on dropped descriptions unless every description in that
source is longer. The script reads a file and never runs `claude`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

NAME_ONLY = "< 20"
_ROW = re.compile(r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<source>[^|]+?)\s*\|\s*(?P<tokens>[^|]+?)\s*\|\s*$")
_LISTING = re.compile(r"^\|\s*Skills\s*\|\s*(?P<tokens>[^|]+?)\s*\|")


def parse_context(text: str) -> dict[str, object]:
    """Per-source counts of the `### Skills` table plus the Skills category size."""
    lines = text.splitlines()
    listing = next((match.group("tokens") for line in lines if (match := _LISTING.match(line))), None)
    try:
        start = lines.index("### Skills") + 1
    except ValueError:
        raise ValueError("no `### Skills` section in this /context output") from None
    sources: dict[str, dict[str, object]] = {}
    for line in lines[start:]:
        if line.startswith("#"):
            break
        match = _ROW.match(line)
        if not match or match.group("name") == "Skill" or set(match.group("name")) <= {"-"}:
            continue
        # `Plugin (name)` rows group under their plugin; other sources stay as printed.
        row = sources.setdefault(match.group("source"), {"listed": 0, "with_description": 0, "name_only": 0,
                                                         "name_only_skills": []})
        row["listed"] += 1
        if match.group("tokens") == NAME_ONLY:
            row["name_only"] += 1
            row["name_only_skills"].append(match.group("name"))
        else:
            row["with_description"] += 1
    return {"skills_listing_tokens": listing, "sources": sources}


def _format(payload: dict[str, object]) -> str:
    out = [f"Skills listing: {payload['skills_listing_tokens'] or 'not reported'}"]
    for source, row in payload["sources"].items():
        out.append(f"{source}: {row['listed']} listed, {row['with_description']} with a description, "
                   f"{row['name_only']} name-only ({NAME_ONLY})")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("context", type=Path, help="saved output of `claude -p \"/context\"`")
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = parser.parse_args(argv)
    try:
        payload = parse_context(args.context.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2) if args.json else _format(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
