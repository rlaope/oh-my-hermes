"""The session's git branch and how many files differ, read off the render path for the row under the info line.

`GitWatcher` runs `git --no-optional-locks status --porcelain=v2 --branch`
in the session's working directory on a thread of its own: once at start,
again on `refresh()` (a turn ended, a tool finished) and every
`INTERVAL_SECONDS` besides, never twice within `MIN_GAP_SECONDS`. A frame
only ever reads the last answer (`state`), so a slow or missing git never
holds a frame up, and `stop()` kills a read in flight. Each run has
`TIMEOUT_SECONDS`; one that does not finish, a git that is not installed, a
directory that is not a repository, or output this module cannot read all
leave `state` None, and the row shows no branch. Nothing is written: the
optional-locks flag keeps `status` from refreshing the index, and no
repository-configured fsmonitor hook runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import subprocess
import threading
import time

TIMEOUT_SECONDS = 2.0
INTERVAL_SECONDS = 15.0
MIN_GAP_SECONDS = 2.0  # the least time between two reads, however often a refresh asks
SHORT_SHA = 7  # a detached HEAD is named by this much of its commit
# `core.fsmonitor=false`: a repository's configured fsmonitor hook never runs for a read the person did not ask for.
ARGV = ("git", "-c", "core.fsmonitor=false", "--no-optional-locks", "status", "--porcelain=v2", "--branch")


@dataclass(frozen=True)
class GitState:
    branch: str  # the branch, or a detached HEAD's short sha
    changed: int  # tracked files modified, staged, renamed or unmerged
    untracked: int


def parse_status(text: str) -> GitState | None:
    """`git status --porcelain=v2 --branch` read as a `GitState`; None when it names no head."""
    head = oid = ""
    changed = untracked = 0
    for line in text.splitlines():
        if line.startswith("# branch.head "):
            head = line.removeprefix("# branch.head ").strip()
        elif line.startswith("# branch.oid "):
            oid = line.removeprefix("# branch.oid ").strip()
        elif line.startswith(("1 ", "2 ", "u ")):
            changed += 1
        elif line.startswith("? "):
            untracked += 1
    if head == "(detached)":
        head = oid[:SHORT_SHA] if oid and oid != "(initial)" else ""
    return GitState(head, changed, untracked) if head else None


def read_status(
    cwd: str,
    popen: Callable[..., subprocess.Popen[str]] | None = None,
    started: Callable[[subprocess.Popen[str] | None], None] = lambda process: None,
) -> GitState | None:
    """One read in `cwd`; None for anything but a clean answer from git (see the module docstring). `started` is
    handed the running git, then None once it is done, so a watcher that stops can kill it."""
    try:
        # A ref or a path that is not UTF-8 (an unborn `caf\xe9`, core.quotePath=false) reads as U+FFFD, not a crash.
        process = (subprocess.Popen if popen is None else popen)(
            list(ARGV), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", errors="replace")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    started(process)
    try:
        out, _err = process.communicate(timeout=TIMEOUT_SECONDS)
    except (OSError, ValueError, subprocess.SubprocessError):  # a timeout, or output it cannot read: no branch
        process.kill()
        process.wait()
        return None
    finally:
        started(None)
    return parse_status(out) if process.returncode == 0 else None


class GitWatcher:
    """Keeps the newest `read_status` of `cwd` in `state`; `start`, `refresh` and `stop` never block on git.

    A burst of `refresh` calls (a turn's tool calls finishing one after another) reads at most once every
    `MIN_GAP_SECONDS`, and `stop` kills a read in flight, so quitting never waits on git or leaves it running.
    """

    def __init__(self, cwd: str, read: Callable[[str], GitState | None] | None = None) -> None:
        self.cwd = cwd
        self.state: GitState | None = None
        self._read = read or (lambda where: read_status(where, started=self._track))
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self.on_change: Callable[[], None] | None = None

    def start(self, wake: Callable[[], None] | None = None) -> None:
        """Start the reading thread; `wake` is called, on that thread, when a read changes `state`."""
        self.on_change = wake
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="omh-git-status", daemon=True)
            self._thread.start()

    def refresh(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 1.0) -> None:
        self._stopping.set()
        self._wake.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.kill()
        if self._thread is not None:
            self._thread.join(timeout)

    def _track(self, process: subprocess.Popen[str] | None) -> None:
        with self._lock:
            self._process = process
        if process is not None and self._stopping.is_set():
            process.kill()  # stopped while it was starting

    def _run(self) -> None:
        while not self._stopping.is_set():
            read_at = time.monotonic()
            state = self._read(self.cwd)
            if state != self.state and not self._stopping.is_set():
                self.state = state
                if self.on_change is not None:
                    self.on_change()
            self._wake.wait(INTERVAL_SECONDS)
            self._wake.clear()
            self._stopping.wait(max(MIN_GAP_SECONDS - (time.monotonic() - read_at), 0.0))
