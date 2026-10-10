"""Lexical reference regions shared by routing matchers, never output rewriting.

The block-quote, relay-header and URL regions follow the mask list of
oh-my-openagent's skill-pointer arming guard (concept only, commit 1f031d0d4);
the patterns and wording here are OMH's own.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata


_QUOTES = {"'": "'", '"': '"', "\u2018": "\u2019", "\u201c": "\u201d", "\u300c": "\u300d", "\u300e": "\u300f"}
_DELIMITERS = re.compile(r"\\.|`+|~+|['\"\u2018\u2019\u201c\u201d\u300c\u300d\u300e\u300f]", re.DOTALL)
# A Markdown block-quote line: at most three spaces of indent, then `>`. An
# escaped `\>` is a literal character and starts nothing.
_BLOCK_QUOTE_LINE = re.compile(r"^ {0,3}(>[^\r\n]*)", re.MULTILINE)
# A line opened by a relay header carries someone else's words: a bracketed
# relay tag (`[REPORT]`), an arrow between two names with or without brackets
# (`[planner -> reviewer]`, `planner -> reviewer:`), or a named sender with an
# id addressing a recipient (`Reviewer (agent-7) to lead:`). The tags are a
# closed list so a person's own `[WIP]` or `[urgent]` stays executable.
_RELAY_NAME = r"[\w.@-]{1,40}"
_RELAY_HEADER_LINE = re.compile(
    r"^[ \t]*(?:"
    r"\[[ \t]*(?:report|relay|relayed|forwarded|fwd|result|summary|output|log)[ \t]*\]"
    rf"|\[[ \t]*{_RELAY_NAME}[ \t]*(?:->|\u2192)[ \t]*{_RELAY_NAME}[ \t]*\]"
    rf"|{_RELAY_NAME}[ \t]*(?:->|\u2192)[ \t]*{_RELAY_NAME}[ \t]*:"
    rf"|{_RELAY_NAME}(?: {_RELAY_NAME})? \([^()\r\n]{{1,40}}\) to {_RELAY_NAME}(?: {_RELAY_NAME})?[ \t]*:"
    r")[^\r\n]*",
    re.MULTILINE | re.IGNORECASE,
)
# A URL with an explicit scheme. It ends at whitespace, a quote or backtick, an
# angle bracket, or the first CJK or Hangul character, so a particle or clause
# glued to the link stays executable. `./name` and `/name` have no scheme.
_URL = re.compile(
    r"(?<![\w.+-])[A-Za-z][A-Za-z0-9+.-]*://"
    r"[^\s<>\"'`\u1100-\u11ff\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]+"
)


@dataclass(frozen=True)
class ReferenceRegions:
    executable_text: str
    # Quoted, fenced and block-quoted text: removed from executable text, and
    # still read as reference context (text-transform fast path, diagnostic
    # workflow mentions).
    references: tuple[str, ...]
    # Relay-header lines and URLs: removed from executable text only. Kept out
    # of `references` so a link or a relayed line never opens the fast path a
    # quoted reference opens.
    masked_spans: tuple[str, ...] = ()


def executable_routing_text(message: str) -> str:
    """Project matching input without altering the original message or CJK clauses."""
    return reference_regions(message).executable_text


@lru_cache(maxsize=4096)
def reference_regions(message: str) -> ReferenceRegions:
    """Shield quotes, exact-length inline backticks, backtick/tilde fences,
    block-quote lines, relay-header lines, and scheme URLs.

    Escapes consume the following character. Apostrophes between word characters
    are not delimiters. Fences start on an otherwise blank line and close on a
    line containing only the same delimiter, at least as long as the opener.
    Unclosed regions shield through EOF, leaving earlier executable text intact.
    Line regions and URLs are found first and blanked before delimiters are
    scanned, so a stray quote inside a quoted line or a link opens nothing.
    Masking preserves character positions and line breaks, never joins words.
    """
    quoted_lines = [match.span(1) for match in _BLOCK_QUOTE_LINE.finditer(message)]
    masked = [
        span
        for span in (
            *(match.span() for match in _RELAY_HEADER_LINE.finditer(message)),
            *(match.span() for match in _URL.finditer(message)),
        )
        if not any(start <= span[0] < end for start, end in quoted_lines)
    ]
    blanked = list(message)
    for start, end in (*quoted_lines, *masked):
        blanked[start:end] = [" "] * (end - start)
    scan = "".join(blanked)
    spans: list[tuple[int, int]] = []
    start = -1
    closer = ""
    fence = False
    for match in _DELIMITERS.finditer(scan):
        token = match.group()
        if token.startswith("\\"):
            continue
        index, end = match.span()
        apostrophe = (
            token in {"'", "\u2019"}
            and index > 0
            and end < len(scan)
            and scan[index - 1].isalnum()
            and scan[end].isalnum()
            # CJK clauses touch quotes without spaces; they are boundaries,
            # unlike apostrophes within Latin words or contractions.
            and unicodedata.east_asian_width(scan[index - 1]) not in {"W", "F"}
            and unicodedata.east_asian_width(scan[end]) not in {"W", "F"}
        )
        if apostrophe:
            continue
        if start >= 0:
            if fence:
                line_end = scan.find("\n", end)
                if line_end == -1:
                    line_end = len(scan)
                if (
                    token[0] == closer[0]
                    and len(token) >= len(closer)
                    and not scan[scan.rfind("\n", 0, index) + 1:index].strip()
                    and not scan[end:line_end].strip()
                ):
                    spans.append((start, end))
                    start = -1
            elif token == closer:
                spans.append((start, end))
                start = -1
            continue
        if token in _QUOTES:
            start, closer, fence = index, _QUOTES[token], False
        elif token[0] in {"`", "~"}:
            fence = len(token) >= 3 and not scan[scan.rfind("\n", 0, index) + 1:index].strip()
            if token[0] == "`" or fence:
                start, closer = index, token
    if start >= 0:
        spans.append((start, len(scan)))
    projected = list(message)
    references: list[str] = []
    for start, end in sorted((*spans, *quoted_lines)):
        references.append(message[start:end])
    for start, end in (*spans, *quoted_lines, *masked):
        projected[start:end] = [char if char in "\r\n" else " " for char in message[start:end]]
    return ReferenceRegions(
        "".join(projected),
        tuple(references),
        tuple(message[start:end] for start, end in sorted(masked)),
    )
