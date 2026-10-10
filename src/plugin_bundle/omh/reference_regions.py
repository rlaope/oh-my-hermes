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
# A Markdown block-quote line: at most three spaces of indent, then `>` (or a
# nested `>>` / `> >`), then a space or the end of the line. An escaped `\>`
# is a literal character, `>text` with no space is not a quote, and `> 5`
# reads as a comparison in chat, so a digit after the space starts nothing.
_BLOCK_QUOTE_LINE = re.compile(r"^ {0,3}(>(?: ?>)*(?:[ \t]+(?![ \t0-9])[^\r\n]*)?)(?=\r?$)", re.MULTILINE)
# A line opened by a relay header carries someone else's words: a bracketed
# relay tag (`[REPORT]`), an arrow between two agent roles with or without
# brackets (`[planner -> reviewer]`, `planner -> reviewer:`), or a named
# sender carrying an agent id addressing an agent role (`Reviewer (agent-7)
# to lead:`). Tags and roles are closed lists: a person's own `[WIP]` or
# `[summary]`, an arrow between versions or environments (`v1 -> v2:`,
# `staging -> prod:`), and a parenthesis in an ordinary sentence
# (`Deploy (v2) to staging:`) stay executable.
_RELAY_ROLES = (
    r"(?:agent|subagent|worker|bot|assistant|planner|reviewer|executor|architect|critic|verifier"
    r"|lead|leader|orchestrator|coordinator|analyst|debugger|tester|writer|designer|researcher|explorer)"
)
_RELAY_ROLE = rf"{_RELAY_ROLES}(?:[-_#]?\d{{1,4}})?\b"
_RELAY_AGENT_ID = rf"{_RELAY_ROLES}[-_# ]?\d{{1,6}}"
_RELAY_NAME = r"[\w.@-]{1,40}"
_RELAY_HEADER_LINE = re.compile(
    r"^[ \t]*(?:"
    r"\[[ \t]*(?:report|relay|relayed|forwarded|fwd)[ \t]*\]"
    rf"|\[[ \t]*{_RELAY_ROLE}[ \t]*(?:->|\u2192)[ \t]*{_RELAY_ROLE}[ \t]*\]"
    rf"|{_RELAY_ROLE}[ \t]*(?:->|\u2192)[ \t]*{_RELAY_ROLE}[ \t]*:"
    rf"|{_RELAY_NAME}(?: {_RELAY_NAME})? \([ \t]*{_RELAY_AGENT_ID}[ \t]*\) to {_RELAY_ROLE}[ \t]*:"
    r")[^\r\n]*",
    re.MULTILINE | re.IGNORECASE,
)
# A URL with an explicit scheme. It ends at whitespace, a quote or backtick, an
# angle bracket, a `$` (an invocation sigil glued to a link starts the
# person's own words), or the first CJK or Hangul character, so a particle or
# clause glued to the link stays executable. An apostrophe between two letters
# or digits (`it's-broken`, `pull/1's`) stays inside it: masking up to the
# apostrophe would leave a lone `'` that a later pass over the projected text
# reads as an opening quote. Trailing sentence punctuation and an unbalanced
# closing bracket are not part of it, as linkifiers read them. `./name` and
# `/name` have no scheme.
_URL = re.compile(
    r"(?<![\w.+-])[A-Za-z][A-Za-z0-9+.-]*://"
    r"(?:[^\s<>\"'`$\u1100-\u11ff\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]|(?<=[A-Za-z0-9])'(?=[A-Za-z0-9]))+"
)
_URL_TRAILING = ".,;:!?)]"
_URL_BRACKETS = {")": "(", "]": "["}


def _url_span(message: str, start: int, end: int) -> tuple[int, int]:
    while end > start and message[end - 1] in _URL_TRAILING:
        closer = message[end - 1]
        if closer in _URL_BRACKETS and message.count(_URL_BRACKETS[closer], start, end) >= message.count(closer, start, end):
            break
        end -= 1
    return start, end


@dataclass(frozen=True)
class ReferenceRegions:
    executable_text: str
    # Quoted and fenced text: removed from executable text, and still read as
    # reference context (text-transform fast path, diagnostic workflow
    # mentions).
    references: tuple[str, ...]
    # Relay-header lines and URLs: removed from executable text only. Kept out
    # of `references` so a link or a relayed line never opens the fast path a
    # quoted reference opens.
    masked_spans: tuple[str, ...] = ()
    # Block-quote lines: removed from executable text and read as diagnostic
    # context like `references`, but kept out of `references` so a pasted
    # `> error` line never opens the text-transform fast path either.
    quoted_lines: tuple[str, ...] = ()
    # The URLs among `masked_spans`: a link still names a concrete target.
    links: tuple[str, ...] = ()


def executable_routing_text(message: str) -> str:
    """Project matching input without altering the original message or CJK clauses."""
    return reference_regions(message).executable_text


@lru_cache(maxsize=4096)
def reference_regions(message: str) -> ReferenceRegions:
    """Shield quotes, exact-length inline backticks, backtick/tilde fences,
    block-quote lines, relay-header lines, and scheme URLs.

    Escapes consume the following character. Apostrophes between word characters
    are not delimiters; adjacency is read on the original message, so a
    possessive glued to a link (`pull/1's`) is still an apostrophe. Fences start
    on an otherwise blank line and close on a line containing only the same
    delimiter, at least as long as the opener. Unclosed regions shield through
    EOF, leaving earlier executable text intact. One left-to-right pass decides
    every region: a line region or URL that starts outside a quote or fence is
    taken whole, so a stray quote inside it opens nothing, and one that starts
    inside a quote or fence is part of that region and adds nothing. Masking
    preserves character positions and line breaks, never joins words.
    """
    candidates = sorted(
        (
            *((*match.span(1), "quote") for match in _BLOCK_QUOTE_LINE.finditer(message)),
            *((*match.span(), "relay") for match in _RELAY_HEADER_LINE.finditer(message)),
            *((*_url_span(message, *match.span()), "link") for match in _URL.finditer(message)),
        )
    )
    taken: list[tuple[int, int, str]] = []
    covered = 0

    def take_through(index: int) -> None:
        nonlocal covered
        while candidates and candidates[0][0] <= index:
            region = candidates.pop(0)
            if region[0] >= covered and region[1] > region[0]:
                taken.append(region)
                covered = region[1]

    def drop_through(index: int) -> None:
        while candidates and candidates[0][0] < index:
            candidates.pop(0)

    spans: list[tuple[int, int]] = []
    start = -1
    closer = ""
    fence = False
    for match in _DELIMITERS.finditer(message):
        token = match.group()
        index, end = match.span()
        if start < 0:
            take_through(index)
            if index < covered:
                continue
        if token.startswith("\\"):
            continue
        apostrophe = (
            token in {"'", "’"}
            and index > 0
            and end < len(message)
            and message[index - 1].isalnum()
            and message[end].isalnum()
            # CJK clauses touch quotes without spaces; they are boundaries,
            # unlike apostrophes within Latin words or contractions.
            and unicodedata.east_asian_width(message[index - 1]) not in {"W", "F"}
            and unicodedata.east_asian_width(message[end]) not in {"W", "F"}
        )
        if apostrophe:
            continue
        if start >= 0:
            if fence:
                line_end = message.find("\n", end)
                if line_end == -1:
                    line_end = len(message)
                if (
                    token[0] == closer[0]
                    and len(token) >= len(closer)
                    and not message[message.rfind("\n", 0, index) + 1:index].strip()
                    and not message[end:line_end].strip()
                ):
                    spans.append((start, end))
                    start = -1
            elif token == closer:
                spans.append((start, end))
                start = -1
            if start < 0:
                drop_through(end)
            continue
        if token in _QUOTES:
            start, closer, fence = index, _QUOTES[token], False
        elif token[0] in {"`", "~"}:
            fence = len(token) >= 3 and not message[message.rfind("\n", 0, index) + 1:index].strip()
            if token[0] == "`" or fence:
                start, closer = index, token
    if start >= 0:
        spans.append((start, len(message)))
    else:
        take_through(len(message))
    projected = list(message)
    for region_start, region_end in (*spans, *((s, e) for s, e, _ in taken)):
        projected[region_start:region_end] = [
            char if char in "\r\n" else " " for char in message[region_start:region_end]
        ]

    def kind(*kinds: str) -> tuple[str, ...]:
        return tuple(message[s:e] for s, e, k in taken if k in kinds)

    return ReferenceRegions(
        "".join(projected),
        tuple(message[s:e] for s, e in spans),
        kind("relay", "link"),
        kind("quote"),
        kind("link"),
    )
