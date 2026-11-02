"""Accept rendered `omh-` display names as canonical names during routing.

Wrapper chat bodies render installable skills with their `omh-` display label so
the prose matches the host's own `Reading skill omh-<name>` status line. Users
echo that label straight back ("use omh-visual-qa"), so routing matching has to
resolve the display form to the same workflow as the canonical form.

This module is deliberately pure text: callers pass the display-to-canonical
mapping they already know, so the plugin bundle can reuse it without importing
the skill catalog. It lives in the bundle so a host that cannot import the
`omh` package runs the same code; `omh.routing.display_names` re-exports it.
Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# `omh-<segment>(-<segment>)*`, and the same for the `ulw-` label the workflow-
# engine skills render. The leading boundary keeps `foo-omh-x` and a bare `omh`
# out of the match, and requiring one segment after the dash keeps a bare `omh-`
# out of it too. That guard matters more for `ulw`: a bare `ulw` is `ultrawork`'s
# own routing alias, so it must stay untouched here and reach the router as-is.
_DISPLAY_MENTION_RE = re.compile(r"(?<![0-9a-z])(?:omh|ulw)-[0-9a-z]+(?:-[0-9a-z]+)*")


def canonical_display_mentions(value: str, canonical_by_display: Mapping[str, str]) -> str:
    """Rewrite `omh-<skill>` display mentions in `value` back to canonical names.

    A mention that does not resolve to a known display name is left untouched, so
    `omh-nonexistent`, `omh-`, and a bare `omh` keep whatever behavior they had.
    """
    if not value or not canonical_by_display:
        return value

    def _replace(match: re.Match[str]) -> str:
        mention = match.group(0)
        segments = mention.split("-")
        # Longest first so `omh-code-review` resolves to `code-review` rather
        # than stopping at a shorter name, while trailing segments that are not
        # part of any display name stay in the text.
        for end in range(len(segments), 1, -1):
            candidate = "-".join(segments[:end])
            canonical = canonical_by_display.get(candidate)
            if canonical is not None:
                return canonical + mention[len(candidate) :]
        return mention

    return _DISPLAY_MENTION_RE.sub(_replace, value)
