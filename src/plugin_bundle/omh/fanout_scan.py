"""One bounded listing of the fanout root, shared by the two per-turn readers.

`pre_llm_call` reads the fanout root twice on every turn: the running-work
board (`status_board_reader`) wants in-flight markers, and the unacknowledged
dispatch reminder (`dispatch_outcomes`) wants finished units. Both used to
enumerate every directory the root has ever held. The board then opened four
JSON files per directory, so the per-turn cost grew with the machine's whole
fanout history -- 0.8 ms at an empty root, 150 ms at a thousand directories --
and nothing prunes the root, so it only ever grows.

A fanout id is `fanout-<sha256(goal)[:12]>` (see `omh.coding.fanout`). It is a
content hash, NOT a timestamp, so the names carry no order and slicing a
sorted name list would pick an arbitrary eight of a thousand -- silently
hiding running units and finished dispatches rather than bounding a cost. The
only order a hash-named directory has is on disk, so this helper stats each
candidate once and keeps the newest `limit` by that stamp; the expensive
per-directory reads then happen only for the ones that survive.

That leaves one cheap `stat` per directory, which is the floor: selecting the
newest N of an unindexed directory cannot be done without looking at all of
them. What it removes is the unbounded read -- four file opens and a JSON
parse each -- which was the whole of the growth.

Boundaries:

- A bound is stated, never silent. `newest_fanout_dirs` returns how many
  directories it passed over so a caller can report a truncated scan as
  truncated. A reader that drops that number is claiming a completeness it
  did not measure.
- Which stamp means "newest" is the caller's to decide, because the two
  readers are asking different questions -- `activity_of` is theirs, and
  returning `None` from it drops the directory from the scan entirely.
- Never raises. A vanished, unlistable, or replaced root is reported as a
  failed listing; the callers map that into their own vocabularies (the board
  distinguishes `absent` from `unreadable`, and does its own root check for
  it, because the two mean different things there).
- Metadata only. Names and mtimes; nothing here opens a file.
"""

from __future__ import annotations

import heapq
import os
from pathlib import Path
from typing import Callable, Final

# How many fanout directories either per-turn reader will look inside. Lived
# in `dispatch_outcomes` as the bound on how many summaries it READ; shared
# here because it is now also the bound on how many the board OPENS, and two
# copies of one number is how the two readers would come to disagree about
# which fanouts a turn saw.
RECENT_FANOUT_DIR_LIMIT: Final[int] = 8


def newest_fanout_dirs(
    root: Path,
    *,
    limit: int,
    activity_of: Callable[[Path], float | None],
    name_filter: Callable[[str], object] | None = None,
) -> tuple[bool, list[Path], int]:
    """The `limit` most recently active child directories of `root`.

    Returns `(listed, dirs, omitted)`. `listed` is False when the root could
    not be enumerated at all -- the caller decides what that means. `dirs` is
    newest first by `activity_of`. `omitted` is how many candidate
    directories the bound passed over, so a caller can say its scan was
    bounded instead of implying it saw everything.

    `name_filter` runs before any syscall, so a root holding files or foreign
    directories costs nothing for them.
    """
    bounded = limit if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else 0
    newest: list[tuple[float, str, Path]] = []
    candidates = 0
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if name_filter is not None and not name_filter(entry.name):
                    continue
                try:
                    # `follow_symlinks=False` answers from the directory entry
                    # itself where the filesystem carries a type, so an
                    # ordinary child costs no syscall here -- and it refuses a
                    # symlink to a directory, which both readers already did.
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                child = Path(entry.path)
                activity = activity_of(child)
                if activity is None:
                    continue
                candidates += 1
                candidate = (activity, entry.name, child)
                if len(newest) < bounded:
                    heapq.heappush(newest, candidate)
                elif bounded and candidate > newest[0]:
                    heapq.heappushpop(newest, candidate)
    except OSError:
        return False, [], 0
    return True, [entry[2] for entry in sorted(newest, reverse=True)], max(0, candidates - len(newest))


def path_mtime(path: Path) -> float | None:
    """`path`'s modification time, or None when it cannot be stat-ed."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None
