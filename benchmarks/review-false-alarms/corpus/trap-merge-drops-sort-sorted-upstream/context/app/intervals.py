"""Interval helpers. An interval is a (start, end) pair of minutes, end exclusive."""


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def merge_busy(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Join overlapping or touching intervals."""
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
