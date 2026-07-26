"""Read what Hermes actually remembers, not just how large the file is.

Hermes keeps its built-in memory in ``~/.hermes/memories/MEMORY.md`` and
``USER.md`` as a ``§``-delimited entry list, and enforces a *character* cap per
file on write (``hermes-agent/tools/memory_tool.py``). OMH's advisory lane used
``stat().st_size`` for that comparison, which is a different unit: UTF-8 spends
three bytes on a Hangul syllable, so a Korean MEMORY.md reads about 1.2x its own
length. A 1,933-character file reports as ``2347 bytes (cap ~2200)`` and looks
over budget while Hermes still accepts writes. An ASCII file of the same length
reports correctly, which is why the mismatch went unnoticed.

Counting characters fixes the unit. Splitting the entries is what lets the rest
of OMH say *which* entry is stale or already duplicated in its own store,
instead of only how full the file is.

Read-only by construction: nothing here opens a file for writing. Hermes owns
these files, and the `memory` tool it exposes to the model is the surface that
edits them.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

# Hermes' own entry separator; see ENTRY_DELIMITER in its memory tool.
HERMES_MEMORY_DELIMITER = "§"

# Hermes memory files and the character caps it enforces on write.
MEMORY_FILE_CAP_CHARS = 2200
USER_FILE_CAP_CHARS = 1375

HERMES_MEMORY_FILES = (
    ("MEMORY.md", MEMORY_FILE_CAP_CHARS),
    ("USER.md", USER_FILE_CAP_CHARS),
)


@dataclass(frozen=True)
class HermesMemoryFile:
    """One Hermes memory file as OMH observed it."""

    label: str
    path: Path
    exists: bool
    chars: int
    cap: int
    entries: tuple[str, ...]
    age_days: float
    error: str = ""

    @property
    def over_cap(self) -> bool:
        return self.exists and self.chars > self.cap

    @property
    def headroom_chars(self) -> int:
        """Characters a new entry may occupy, delimiter included."""
        if not self.exists:
            return self.cap
        return max(0, self.cap - self.chars)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "path": str(self.path),
            "exists": self.exists,
            "chars": self.chars,
            "cap": self.cap,
            "over_cap": self.over_cap,
            "headroom_chars": self.headroom_chars,
            "entry_count": len(self.entries),
            "age_days": round(self.age_days, 1),
            "error": self.error,
        }


def parse_memory_entries(text: str) -> tuple[str, ...]:
    """Split one Hermes memory file into its entries."""
    return tuple(entry.strip() for entry in text.split(HERMES_MEMORY_DELIMITER) if entry.strip())


def memory_char_count(entries: tuple[str, ...] | list[str]) -> int:
    """Count characters the way Hermes counts them when enforcing the cap."""
    if not entries:
        return 0
    return len(HERMES_MEMORY_DELIMITER.join(entries))


def read_hermes_memory_file(
    path: Path,
    *,
    label: str,
    cap: int,
    now: float | None = None,
) -> HermesMemoryFile:
    """Read one memory file. Never raises: an unreadable file reports its error."""
    moment = time.time() if now is None else now
    if not path.exists():
        return HermesMemoryFile(label, path, False, 0, cap, (), 0.0)
    try:
        text = path.read_text(encoding="utf-8")
        age_days = max(0.0, (moment - path.stat().st_mtime) / 86400.0)
    except (OSError, UnicodeDecodeError) as error:
        return HermesMemoryFile(label, path, True, 0, cap, (), 0.0, error=str(error))
    entries = parse_memory_entries(text)
    return HermesMemoryFile(label, path, True, memory_char_count(entries), cap, entries, age_days)


def read_hermes_memory(
    hermes_home: str | Path,
    *,
    now: float | None = None,
) -> tuple[HermesMemoryFile, ...]:
    """Read every Hermes memory file under one Hermes home."""
    memories_dir = Path(hermes_home).expanduser() / "memories"
    return tuple(
        read_hermes_memory_file(memories_dir / name, label=name, cap=cap, now=now)
        for name, cap in HERMES_MEMORY_FILES
    )


# A fact restated in Hermes' own words shares most of its nouns but almost none
# of its punctuation or particles, so token overlap separates "already known"
# from "new" where exact matching cannot. The threshold is deliberately loose:
# this only decides what to *show* a reviewer, never what to write.
DUPLICATE_SIMILARITY_THRESHOLD = 0.6

_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def text_tokens(text: str) -> frozenset[str]:
    """Comparable tokens for one memory summary or entry."""
    return frozenset(_TOKEN_PATTERN.findall(text.lower()))


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of two memory texts, 0.0 when either side has no tokens."""
    left_tokens = text_tokens(left)
    right_tokens = text_tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def nearest_entry(text: str, entries: tuple[str, ...] | list[str]) -> tuple[int, float]:
    """Index and score of the entry closest to ``text``; ``(-1, 0.0)`` when none."""
    best_index = -1
    best_score = 0.0
    for index, entry in enumerate(entries):
        score = similarity(text, entry)
        if score > best_score:
            best_index, best_score = index, score
    return best_index, best_score
