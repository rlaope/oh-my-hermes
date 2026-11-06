"""Which installer generations a running OMH process still imports from.

`omh update` collects superseded generations, and an OMH TUI left open
through an update (with the gateway attach under it) keeps importing from the
generation it started on: its `site-packages` is on that process tree's path
until it exits. The updater's own `sys.executable` names only itself, and a
process listing is neither portable nor needed. Instead the long-running
process holds an exclusive OS lock (`file_lock`: `fcntl` on POSIX,
`msvcrt.locking` on Windows) on a file named for its generation, under
`<installer root>/generation-holds/`, and update's GC keeps every generation
whose file it cannot lock. The OS drops the lock when the process ends, by any
means, so a crashed TUI holds nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import sys
import time

try:
    from ..system.local_store import FileLockTimeout, file_lock
except ImportError:  # pragma: no cover - direct-source installer smoke.
    from system.local_store import FileLockTimeout, file_lock

HOLDS_DIRNAME = "generation-holds"
HOLD_ATTEMPTS = 20
HOLD_RETRY_SECONDS = 0.05


def generation_of(prefix: Path) -> Path | None:
    """The generation whose venv is `prefix`, through the `current` pointer too: the one the pointer names when
    this is called, so a long-running process reads its own once, at its start."""
    try:
        venv = prefix.expanduser().resolve()
    except OSError:
        return None
    if venv.name == "venv" and venv.parent.parent.name == "generations":
        return venv.parent
    return None


def _sidecar(holds: Path, stem: str) -> Path:
    return holds / f".{stem}.lock"


@contextmanager
def hold_running_generation(prefix: str | None = None) -> Iterator[str]:
    """Hold this process's generation against update's GC until the block exits.

    Yields the held generation's name, or "" when this process does not run
    from an installer generation (a source checkout, pip, npm) or the hold
    could not be taken; the block runs either way.
    """
    generation = generation_of(Path(prefix or sys.prefix))
    if generation is None:
        yield ""
        return
    holds = generation.parent.parent / HOLDS_DIRNAME
    stem = f"{generation.name}.{os.getpid()}"
    lock = ExitStack()
    held = ""
    for _attempt in range(HOLD_ATTEMPTS):
        try:
            lock.enter_context(file_lock(holds / stem, timeout_seconds=0.0, private=True))
        except FileLockTimeout:
            # A GC probe locks every hold file it lists for a moment, this new
            # one included; it lets go at once, so try again.
            lock.close()
            time.sleep(HOLD_RETRY_SECONDS)
            continue
        except OSError:
            break
        # A GC probe that took this file before the lock did removes it while
        # holding it; a lock on that unlinked file would hold nothing.
        if _sidecar(holds, stem).exists():
            held = generation.name
            break
        lock.close()
    if not held:
        print(
            f"omh: could not hold generation {generation.name} for this session; "
            "an `omh update` while it runs may remove the files it imports from.",
            file=sys.stderr,
        )
    try:
        yield held
    finally:
        lock.close()
        if held:
            try:
                _sidecar(holds, stem).unlink(missing_ok=True)
            except OSError:
                pass


def held_generations(root: Path) -> set[str]:
    """Generation names some live process holds under `root`; stale holds are removed."""
    holds = root / HOLDS_DIRNAME
    held: set[str] = set()
    try:
        entries = list(holds.iterdir()) if holds.is_dir() else []
    except OSError:
        return held
    for sidecar in entries:
        name = sidecar.name
        if not (name.startswith(".") and name.endswith(".lock")):
            continue
        stem = name[1 : -len(".lock")]
        generation = stem.rpartition(".")[0]
        if not generation:
            continue
        try:
            with file_lock(holds / stem, timeout_seconds=0.0):
                # Unlinked while locked on POSIX, so a holder that opened the
                # file meanwhile finds it gone once it locks, and retries.
                if os.name != "nt":
                    sidecar.unlink(missing_ok=True)
        except FileLockTimeout:
            held.add(generation)
            continue
        except OSError:
            # Unreadable or denied (Windows refuses a file another process
            # holds open): it cannot be shown stale, so it holds.
            held.add(generation)
            continue
        if os.name == "nt":
            # Windows will not delete a file a starting holder has open, so
            # removing it after the probe closes it cannot strand that holder.
            try:
                sidecar.unlink(missing_ok=True)
            except OSError:
                pass
    return held
