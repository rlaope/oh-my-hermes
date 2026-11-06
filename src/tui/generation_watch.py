"""Whether `omh update` installed another OMH generation under this running TUI.

The TUI imports from the installer generation it started on until it exits
(`install.generation_hold`), so an update reaches it only through a restart.
`omh update` moves one pointer, `<installer root>/current`, to the generation
it installed. The watch reads that link, one `readlink` at most every
`CHECK_SECONDS`, and compares the generation it names with the one this
process started on. It reads nothing over the network and writes nothing. A
TUI that does not run from an installer generation (a checkout, pip, the npm
launcher's cache) has no pointer to read and no watch.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

from ..install.generation_hold import generation_of

CHECK_SECONDS = 5.0
CURRENT = "current"


class GenerationWatch:
    """The generation `current` names, read at most every `every` seconds; `poll` says when it moved."""

    def __init__(self, generation: Path, *, every: float = CHECK_SECONDS,
                 read_link: Callable[[Path], str] = os.readlink) -> None:
        self.root = generation.parent.parent  # the installer root: `<root>/generations/<name>`
        self.running = generation.name  # the generation this process imports from
        self.seen = generation.name  # the one `current` named at the last read
        self.every = every
        self.due = 0.0
        self.read_link = read_link

    def poll(self, now: float) -> str | None:
        """The generation `current` names when that moved since the last read, which may be this process's own again
        (an update rolled back); None between reads, when it did not move, or when the link cannot be read."""
        if now < self.due:
            return None
        self.due = now + self.every
        name = self._pointed()
        if not name or name == self.seen:
            return None
        self.seen = name
        return name

    def _pointed(self) -> str:
        """The last part of the link's target: a relative POSIX symlink and an absolute Windows junction alike."""
        try:
            return Path(self.read_link(self.root / CURRENT)).name
        except (OSError, ValueError):
            return ""

    def label(self, name: str) -> str:
        """`4.0.6 main@1a2b3c4d` for generation `name`, read from its files (`self_update.generation_identity`); the
        directory's name when it records neither a version nor a commit, or its files cannot be read."""
        from ..install.self_update import generation_identity, identity_label

        try:
            return identity_label(generation_identity(self.root / "generations" / name)) or name
        except OSError:
            return name


def watch_for(prefix: str) -> GenerationWatch | None:
    """The watch for a process whose venv is `prefix` (`sys.prefix`), read once at the TUI's start; None outside an
    installer generation."""
    generation = generation_of(Path(prefix))
    return GenerationWatch(generation) if generation is not None else None
