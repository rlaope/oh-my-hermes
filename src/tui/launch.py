"""How bare `omh` opens the OMH TUI through Hermes' own launcher.

`omh` runs the person's `hermes --tui` with `HERMES_TUI_DIR` pointing at
`frontend/` beside this file. Hermes' launcher then resolves the profile, the
resume target, the working directory and session ownership exactly as it does
for its own terminal, and runs `frontend/dist/entry.js` in place of its Ink
app. That file is a small Node shim that hands the terminal to
`omh.tui.app.main` on the interpreter named in `OMH_TUI_PYTHON`, started with
`-E -P` so neither the launcher's `PYTHONPATH` nor the working directory is
on its import path. (`-E` does not hide a custom `PYTHONUSERBASE`: `site`
reads that variable from the environment either way.) That interpreter does
not always find the `omh` this process runs on its own path: the npm and Bun
launcher puts its extracted cache on the path in-process. So
`omh` also names the directory its `omh` package was imported from
(`SITE_ENV`, `omh_import_root`), and the shim puts that directory first on
the path unless the interpreter already imports `omh` from there. An OMH that
still cannot import itself exits 75, so `omh` falls back.

When the TUI cannot start it creates the file `omh` named in
`FALLBACK_SENTINEL_ENV` and exits with `FALLBACK_EXIT`, and `omh` opens
Hermes' own terminal instead (`hermes --tui` where Node is found and the
reason is the OMH TUI's own, plain `hermes` otherwise; `hermes_tui_fits`),
after one line on stderr saying why, so a failure costs the person the OMH
surface, never the session. The TUI writes what it said into that file, and
`omh` says it again once Hermes' terminal closes, since that terminal clears
the screen it was said on. `omh_tui_blocker` is the
same choice made before anything starts. Exit 75 without that file (Hermes
uses 75 on paths of its own), like every other exit code, is the session
ending and is returned as it is.

The TUI also writes the session it has open, with the Hermes home it runs
on, into the file `omh` named in `SESSION_FILE_ENV`, beside the fallback
marker, so `omh` can name that session once the TUI exits
(`closed_session`). Hermes keeps a file like it for its own epilogue, but
removes it before `omh` gets control back. A session the person closes then
exits `CLOSED_EXIT` instead of 0, so Hermes prints no epilogue of its own and
`omh` prints its card in its place, returning 0 to the shell.

An `omh` that runs from an installer generation also names a relaunch marker
(`RELAUNCH_FILE_ENV`). When `omh update` installs another generation under
the running TUI and the person picks Restart, the TUI creates that file and
exits `RELAUNCH_EXIT`; `omh` then opens the installed generation's own
`omh --resume <session>` in its place (`commands.bare_launch`), with
`UPDATED_ENV` set so that TUI offers `/gateway restart` once when the shared
gateway still runs the old OMH plugin code.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile
from typing import TextIO

from .terminal import terminal_blocker, terminal_supported

# EX_TEMPFAIL. Not 0/1/2/130 (ordinary exits) and not 42, which Hermes'
# launcher reads as "relaunch as `hermes update`".
FALLBACK_EXIT = 75
# The file that makes a `FALLBACK_EXIT` a fallback request: Hermes exits 75
# (EX_TEMPFAIL) on paths of its own, so `omh` reopens Hermes' terminal only
# when the TUI also created this file. `omh` names a path in a private
# directory it creates, and removes the directory when the launch ends
# (`fallback_sentinel`); `gateway_spawn` drops every `OMH_TUI_` name, so the
# gateway and its tools never see it.
FALLBACK_SENTINEL_ENV = "OMH_TUI_FALLBACK_SENTINEL"
# The file the TUI keeps `{"session_id": ..., "hermes_home": ..., "opened": [...]}` in for the
# session it has open (`write_active_session`), in the same private directory.
SESSION_FILE_ENV = "OMH_TUI_SESSION_FILE"
# Set to "1" by a bare `omh --resume` (no session named): the TUI opens the session picker as soon as it starts.
PICK_SESSION_ENV = "OMH_TUI_PICK_SESSION"
# How much of that file `closed_session` reads: an id, a path and the launch's earlier ids.
SESSION_FILE_BYTES = 16384
# What the TUI exits with, in place of 0, when the person closes a session `omh` launched (`SESSION_FILE_ENV`
# set), and what `omh` turns back into 0. Hermes' launcher prints its exit summary, naming `hermes --tui
# --resume`, only for 0 and 130 (`_launch_tui` in `hermes_cli/main_tui_launch.py`), so `omh`'s card is the
# only one. The same condition gates its `--worktree` exit question, which `omh` never asks for. Not 1 or 2,
# not 42 (Hermes relaunches as `hermes update`), not `FALLBACK_EXIT`, and below the 128 + signal range.
CLOSED_EXIT = 77
# How much of the TUI's reason the marker keeps (`request_fallback`).
FALLBACK_REASON_BYTES = 4096
# What the TUI exits with when the person asked it to restart on the OMH generation `omh update` installed under
# it (`request_relaunch`): `omh` then starts the installed generation's `omh --resume <session>` in its place.
# Not 0/1/2/130, not 42 (Hermes relaunches as `hermes update`), not `FALLBACK_EXIT` or `CLOSED_EXIT`, below the
# 128 + signal range, and passed on by Hermes' launcher as it is (no epilogue: it prints one for 0 and 130 only).
RELAUNCH_EXIT = 78
# The file that makes a `RELAUNCH_EXIT` a relaunch request, in the same private directory, as `FALLBACK_SENTINEL_ENV`
# makes a 75 a fallback: a 78 from anything else is an exit code. A TUI whose environment names none (one `omh`
# did not launch) cannot be relaunched and does not offer it.
RELAUNCH_FILE_ENV = "OMH_TUI_RELAUNCH_FILE"
# Set to "1" in the relaunched `omh`'s environment: the TUI it opens started for an update, so when the shared
# gateway it attaches to still runs the old OMH plugin code it offers `/gateway restart` once.
UPDATED_ENV = "OMH_TUI_UPDATED"
# Its value and the marker's content when the TUI left in plan mode, which only the TUI knows (a prompt goes as `/plan`).
UPDATED_PLAN = "plan"
UPDATED_PLAIN = "1"
# Windows opens a descriptor in text mode unless told otherwise, which rewrites line ends and stops at Ctrl+Z.
_BINARY = getattr(os, "O_BINARY", 0)
# The directory the TUI's interpreter imports `omh` from when its own path
# does not already import it from there (`omh_import_root`). `omh` always sets
# it, so a value left in the person's environment never picks the tree.
SITE_ENV = "OMH_TUI_SITE"
# Signals that end `omh` while the TUI runs: closing the terminal window sends SIGHUP.
EXIT_SIGNALS = ("SIGTERM", "SIGHUP")

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
FRONTEND_ENTRY = FRONTEND_DIR / "dist" / "entry.js"


def node_available(environ: Mapping[str, str], hermes_home: Path) -> bool:
    """Whether Hermes' launcher will find Node: `HERMES_NODE`, `node` on PATH, or Hermes' own tools.

    Best effort. Hermes resolves Node through its package manager, which can
    also fetch it; a miss here only means `omh` opens plain `hermes` instead
    of a TUI (Hermes' own TUI needs Node as well), never that a launch fails.
    """
    explicit = environ.get("HERMES_NODE", "")
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return True
    if shutil.which("node", path=environ.get("PATH")):
        return True
    return any(
        candidate.is_file() and os.access(candidate, os.X_OK)
        for candidate in sorted((hermes_home / "tools").glob("node-*/bin/node"))
    )


def omh_tui_available(
    stdin: TextIO | None, stdout: TextIO | None, environ: Mapping[str, str], hermes_home: Path
) -> bool:
    """Whether bare `omh` should try the OMH TUI before Hermes' own terminal."""
    return not omh_tui_blocker(stdin, stdout, environ, hermes_home)


def omh_tui_blocker(
    stdin: TextIO | None, stdout: TextIO | None, environ: Mapping[str, str], hermes_home: Path
) -> str:
    """Why bare `omh` cannot try the OMH TUI here, in one line, or "" when it can."""
    if not terminal_supported(stdin, stdout, environ):
        return terminal_blocker(stdin, stdout, environ) or "this terminal cannot host the OMH TUI"
    if not FRONTEND_ENTRY.is_file():
        return f"the OMH TUI frontend is missing from this install ({FRONTEND_ENTRY})"
    if not node_available(environ, hermes_home):
        return "no Node found for Hermes' launcher (HERMES_NODE, PATH, or Hermes' tools/node-*)"
    return ""


def hermes_tui_fits(environ: Mapping[str, str]) -> bool:
    """Whether the fallback may ask for Hermes' own TUI rather than plain `hermes`.

    Not under `TERM=dumb`, where no TUI draws, and not under `OMH_NO_TUI=1`,
    the escape every OMH cursor UI honours beside it (the setup menu, the
    theme picker). The reasons that are the OMH TUI's alone, no `termios`
    (Windows), its frontend missing, its own exit 75, leave Hermes' TUI
    able to open. Node is the caller's separate check (`node_available`):
    Hermes' TUI needs it as much as the OMH TUI does.
    """
    return environ.get("TERM", "") != "dumb" and environ.get("OMH_NO_TUI", "") != "1"


def omh_import_root() -> str:
    """The import-path directory the running `omh` package was imported from.

    For example `site-packages` for a wheel install, or the extracted cache
    `site` under the npm and Bun launcher. The path is not resolved: a uv
    editable install is a tree of links into `src/`, and resolving would name
    `src/` rather than the directory this process imported `omh` from.
    """
    import omh

    return os.path.dirname(os.path.dirname(os.path.abspath(omh.__file__)))


def omh_tui_environment(
    environ: Mapping[str, str], *, python: str, site: str, omh_home: Path, fallback_sentinel: Path,
    session_file: Path, pick_session: bool = False, relaunch_file: Path | None = None,
) -> dict[str, str]:
    """The environment `hermes --tui` runs with when it should start the OMH TUI.

    `OMH_HOME` carries the home this `omh` resolved (including `--omh-home` and
    `--scope project`, and for `--profile <name>` the store that profile's
    config names) across the three processes in between, which do not see
    `omh`'s own arguments. `SITE_ENV` is set over any inherited value.
    `PICK_SESSION_ENV` is set only for `pick_session` (a bare `omh --resume`),
    and an inherited one is dropped otherwise. `RELAUNCH_FILE_ENV` likewise:
    only a launch that can relaunch the TUI names one.
    """
    env = dict(environ)
    env["HERMES_TUI_DIR"] = str(FRONTEND_DIR)
    env["OMH_TUI_PYTHON"] = python
    env[SITE_ENV] = site
    env["OMH_HOME"] = str(omh_home)
    env[FALLBACK_SENTINEL_ENV] = str(fallback_sentinel)
    env[SESSION_FILE_ENV] = str(session_file)
    env.pop(PICK_SESSION_ENV, None)
    if pick_session:
        env[PICK_SESSION_ENV] = "1"
    env.pop(RELAUNCH_FILE_ENV, None)
    if relaunch_file is not None:
        env[RELAUNCH_FILE_ENV] = str(relaunch_file)
    return env


@contextmanager
def fallback_sentinel() -> Iterator[Path]:
    """A path where no file is yet, in a new private directory (mode 0700, under the temp directory).

    The directory and whatever is in it are removed when the block exits,
    by return or by exception. A signal ends the process without that
    unless it is turned into an exception first: SIGHUP and SIGTERM are,
    while `exit_on_signals` is in force around this block (bare `omh` keeps
    it in force while the TUI runs). SIGKILL leaves the directory behind.
    """
    directory = Path(tempfile.mkdtemp(prefix="omh-tui-"))
    try:
        yield directory / "fallback"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _exit_on_signal(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


@contextmanager
def exit_on_signals() -> Iterator[None]:
    """While the block runs, `EXIT_SIGNALS` raise `SystemExit(128 + signum)`; the handlers they replace come back after.

    Left to their default action they end `omh` at once and no `finally`
    runs. A signal the platform does not have is skipped, and off the main
    thread nothing is installed, as `omh.tui.app` does for the same pair.
    """
    previous: dict[int, object] = {}
    for name in EXIT_SIGNALS:
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.signal(signum, _exit_on_signal)
        except ValueError:
            break  # handlers can only be installed from the main thread
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler if handler is not None else signal.SIG_DFL)


def fallback_requested(returncode: int, sentinel: Path) -> bool:
    """Whether the TUI asked `omh` to open Hermes' own terminal: `FALLBACK_EXIT` and the file it was named."""
    return returncode == FALLBACK_EXIT and os.path.lexists(sentinel)


def request_fallback(environ: Mapping[str, str], reason: str = "") -> int:
    """Create the file named in `FALLBACK_SENTINEL_ENV`, if any, holding `reason`, and return `FALLBACK_EXIT`.

    The TUI returns `FALLBACK_EXIT` only through this; the frontend shim and
    its import bootstrap create the file the same way, empty, before they
    exit 75. When the file cannot be created, `omh` passes the 75 on as an
    exit code instead of opening Hermes' terminal. `reason` is what the TUI
    printed about why it did not start: Hermes' own TUI clears the screen it
    was printed on, so `omh` prints it again once that terminal closes
    (`fallback_reason`). Its last `FALLBACK_REASON_BYTES` are kept, since a
    traceback's cause is at its end; a marker whose reason could not be
    written still asks for the fallback.
    """
    path = environ.get(FALLBACK_SENTINEL_ENV, "")
    if path:
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags, 0o600)
        except OSError:
            return FALLBACK_EXIT
        try:
            os.write(descriptor, reason.encode("utf-8", "replace")[-FALLBACK_REASON_BYTES:])
        except OSError:
            pass
        finally:
            os.close(descriptor)
    return FALLBACK_EXIT


def relaunch_requested(returncode: int, marker: Path) -> bool:
    """Whether the TUI asked `omh` to start the installed generation in its place: `RELAUNCH_EXIT` and the file."""
    return returncode == RELAUNCH_EXIT and os.path.lexists(marker)


def relaunch_updated_value(marker: Path) -> str:
    """What `UPDATED_ENV` says in the relaunched `omh`: what the marker holds (`request_relaunch`)."""
    try:
        return UPDATED_PLAN if marker.read_bytes() == UPDATED_PLAN.encode() else UPDATED_PLAIN
    except OSError:
        return UPDATED_PLAIN


def request_relaunch(environ: Mapping[str, str], *, plan_mode: bool = False) -> bool:
    """Create the file named in `RELAUNCH_FILE_ENV`, holding `UPDATED_PLAN` for a TUI in plan mode and empty otherwise;
    whether it now exists, so the TUI may exit `RELAUNCH_EXIT`. False when the environment names none or it cannot be
    written: then a 78 would only end the session, and the TUI does not leave for it."""
    path = environ.get(RELAUNCH_FILE_ENV, "")
    if not path:
        return False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            if plan_mode:
                os.write(descriptor, UPDATED_PLAN.encode())
        finally:
            os.close(descriptor)
    except OSError:
        return False
    return True


def fallback_reason(sentinel: Path) -> list[str]:
    """The lines the TUI wrote into the fallback marker (`request_fallback`), printable characters only."""
    try:
        descriptor = os.open(sentinel, os.O_RDONLY | _BINARY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return []
    try:
        data = os.read(descriptor, FALLBACK_REASON_BYTES)
    except OSError:
        data = b""
    finally:
        os.close(descriptor)
    lines = ("".join(char for char in line if char.isprintable()) for line in data.decode("utf-8", "replace").splitlines())
    return [line for line in lines if line.strip()]


def closed_session(path: Path) -> tuple[str, str, tuple[str, ...]]:
    """The session id and Hermes home the TUI last wrote to the file named in `SESSION_FILE_ENV`, with the sessions
    the launch had open before it, newest last; ("", "", ()) when it wrote none, or wrote something this cannot
    read as an id and a home.

    Read before the private directory is removed. The home is the
    `HERMES_HOME` the TUI ran with, which is where Hermes put the session:
    Hermes' launcher may pick a profile (`--profile`, or the sticky active
    profile) that `omh` did not name.
    """
    nothing: tuple[str, str, tuple[str, ...]] = ("", "", ())
    try:
        descriptor = os.open(path, os.O_RDONLY | _BINARY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return nothing
    try:
        data = os.read(descriptor, SESSION_FILE_BYTES)
    except OSError:
        data = b""
    finally:
        os.close(descriptor)
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return nothing
    if not isinstance(record, dict):
        return nothing
    session_id, hermes_home = record.get("session_id"), record.get("hermes_home")
    if not isinstance(session_id, str) or not isinstance(hermes_home, str):
        return nothing
    if not session_id.isprintable() or not session_id.strip() or not os.path.isabs(hermes_home):
        return nothing
    opened = record.get("opened")
    earlier = tuple(item.strip() for item in opened if isinstance(item, str) and item.isprintable() and item.strip()) \
        if isinstance(opened, list) else ()
    return session_id.strip(), hermes_home, earlier
