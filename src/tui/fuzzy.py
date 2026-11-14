"""Subsequence matching for the slash menu and the pickers.

A needle matches a haystack when its characters (casefolded) appear in order, not necessarily side by side, so
`rld` finds `reload-skills`. Stdlib only and deterministic. The callers keep their prefix and substring matches
first and in their own order and append what only this finds (`subsequence_tail`, `slash.completions`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

# What starts a segment of a name or a title; a hit right after one reads as an initial.
SEGMENT_BREAKS = frozenset("-_/ .\n\t:")

_PREFIX = 30000
_CONTIGUOUS = 20000
_SEGMENT_START = 12
_ADJACENT = 8
_SCATTERED = 1

Row = TypeVar("Row")


def subsequence_score(needle: str, haystack: str) -> int | None:
    """None when `needle`'s characters do not appear in `haystack` in order, else a score, higher the better.

    A haystack that starts with the needle outscores one that contains it, which outscores the rest; among the
    rest, hits at the start of a segment (after `-`, `_`, `/`, a space or a dot) and hits next to the previous
    one outscore scattered ones. An empty needle matches everything with the same score.
    """
    needle = needle.casefold()
    haystack = haystack.casefold()
    if not needle:
        return 0
    if haystack.startswith(needle):
        return _PREFIX - len(haystack)
    at = haystack.find(needle)
    if at >= 0:
        return _CONTIGUOUS - at
    # best[j]: the best score matching the needle so far with its last character at haystack[j].
    best: list[int | None] = [None] * len(haystack)
    for step, char in enumerate(needle):
        following: list[int | None] = [None] * len(haystack)
        # The best earlier score, by position, that a hit further on may follow.
        carried: int | None = None
        for position, found in enumerate(haystack):
            if step and position:
                earlier = best[position - 1]
                if earlier is not None and (carried is None or earlier > carried):
                    carried = earlier
            if found != char:
                continue
            gain = _SCATTERED
            if position == 0 or haystack[position - 1] in SEGMENT_BREAKS:
                gain = _SEGMENT_START
            if step == 0:
                following[position] = gain
                continue
            if carried is None:
                continue
            adjacent = best[position - 1] if position else None
            score = carried + gain
            if adjacent is not None:
                score = max(score, adjacent + gain + _ADJACENT)
            following[position] = score
        best = following
    reached = [score for score in best if score is not None]
    return max(reached) if reached else None


def best_subsequence_score(needle: str, fields: Sequence[str]) -> int | None:
    """The best `subsequence_score` over `fields`, each matched on its own so a needle never spans two."""
    scores = [score for score in (subsequence_score(needle, field) for field in fields) if score is not None]
    return max(scores) if scores else None


def subsequence_tail(rows: Sequence[Row], needle: str, fields: Callable[[Row], Sequence[str]]) -> list[Row]:
    """`rows` whose fields contain `needle` as a substring, in their order, then the rows that only match as a
    subsequence of one field, best score first and in their order among equals. An empty needle keeps every row.
    """
    needle = needle.casefold()
    if not needle:
        return list(rows)
    contained: list[Row] = []
    scattered: list[tuple[int, int, Row]] = []
    for number, row in enumerate(rows):
        parts = fields(row)
        if needle in "\n".join(parts).casefold():
            contained.append(row)
            continue
        score = best_subsequence_score(needle, parts)
        if score is not None:
            scattered.append((-score, number, row))
    scattered.sort(key=lambda item: item[:2])
    return contained + [row for _, _, row in scattered]
