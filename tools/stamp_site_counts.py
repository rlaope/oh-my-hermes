"""Bake the repository's GitHub star count into the built site.

The Pages workflow runs this on `_site` before the upload, so every
`[data-stars]` and `[data-star-count]` placeholder carries the real count
(`data-stars="5311"` plus the compact text `5.3k`) without waiting for the
visitor's own, unauthenticated and often rate-limited, API call. The client
(`site/app.js`) only ever raises that baked figure.

    GITHUB_TOKEN=... python tools/stamp_site_counts.py _site

The token is optional (it lifts the rate limit) and is never printed. When
the API call fails, every placeholder keeps the value it already has and the
script still exits 0, so a GitHub hiccup never fails a deploy.
"""
from __future__ import annotations

import argparse
from decimal import ROUND_HALF_UP, Decimal
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

REPO = "rlaope/oh-my-hermes"
API = "https://api.github.com/repos/"
TIMEOUT = 10

# `<tag ... data-stars ...>text</tag>` and the same for `data-star-count`;
# an existing value on the attribute is replaced, and `data-stars-x` is not
# a match.
PLACEHOLDER = re.compile(
    r"(?P<open><(?P<tag>[A-Za-z][\w-]*)\b[^>]*?\s)"
    r"data-(?P<name>stars|star-count)(?:=\"[^\"]*\")?(?=[\s>/])"
    r"(?P<rest>[^>]*>)(?P<text>[^<]*)(?P<close></(?P=tag)\s*>)"
)


def _fixed1(value: float) -> str:
    """JavaScript's `value.toFixed(1)` with a trailing `.0` dropped."""
    text = str(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return text[:-2] if text.endswith(".0") else text


def compact(n: int) -> str:
    """The same rules as `compact()` in site/app.js: 5311 -> 5.3k."""
    if n >= 1e6:
        return _fixed1(n / 1e6) + "M"
    if n >= 1e5:
        return str(int(Decimal(n / 1e3).quantize(Decimal("1"), rounding=ROUND_HALF_UP))) + "k"
    if n >= 1e3:
        return _fixed1(n / 1e3) + "k"
    return str(n)


def stamp(text: str, stars: int) -> tuple[str, int]:
    """Write `stars` into every placeholder; returns the new text and the count."""
    shown = compact(stars)

    def repl(match: re.Match[str]) -> str:
        return (
            f'{match["open"]}data-{match["name"]}="{stars}"{match["rest"]}'
            f'{shown}{match["close"]}'
        )

    return PLACEHOLDER.subn(repl, text)


def fetch_stars(repo: str, token: str | None) -> int:
    """Return `stargazers_count`; raises on any failure."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "oh-my-hermes-pages",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API + repo, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.loads(response.read(1_000_000))
    stars = data.get("stargazers_count") if isinstance(data, dict) else None
    if not isinstance(stars, int) or isinstance(stars, bool) or stars < 0:
        raise ValueError("response has no stargazers_count")
    return stars


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", type=Path, help="built site directory (e.g. _site)")
    parser.add_argument("--repo", default=REPO)
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN") or None

    try:
        stars = fetch_stars(args.repo, token)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        if token:
            reason = reason.replace(token, "***")
        print(f"star count: API call failed ({reason}); kept the existing values")
        return 0

    files = placeholders = 0
    for page in sorted(args.site.rglob("*.html")):
        before = page.read_text(encoding="utf-8")
        after, n = stamp(before, stars)
        if n:
            files += 1
            placeholders += n
            if after != before:
                page.write_text(after, encoding="utf-8")
    print(f"star count: {stars} ({compact(stars)}) stamped into {placeholders} placeholder(s) in {files} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
