"""The row above the composer for this session's background processes (the owner's design of 2026-10-28).

A Hermes turn can start a `terminal` command in the background and end. With
the tool's default, `notify_on_complete: False`, Hermes queues no completion
when it exits (`tools/process_registry.py`, `_publish_finished`), so the
session never wakes and nothing on screen says work is still running. While
this session owns such a process, one row says so, and once one ends unreported
the row offers Enter to tell the session.

What is read: Hermes' crash-recovery checkpoint, `<hermes_home>/processes.json`,
read-only and bounded (`PROCESSES_MAX_BYTES`). Hermes rewrites it from its
running table at every spawn and exit (`ProcessCheckpointMixin._write_checkpoint`),
so it lists running processes only, never an exit code. The gateway's
`process.list` RPC is not called: it drains completion notifications as it
answers (`tui_gateway/server.py`, `_session_processes`).

Whose: a row whose `session_key` names this session's stored id in one of
the two shapes Hermes records. The `terminal` tool records the turn's
current session key (`tools/terminal_tool.py`, `get_current_session_key`).
A session the TUI gateway runs itself has its stored id as that key
(`tui_gateway/prompt_turn.py`, `set_current_session_key(session["session_key"])`),
the key `session.info` reports as `stored_session_id`, the TUI's `stored_id`.
A local session the gateway owns runs on its route key instead,
`agent:<namespace>:local:dm:<stored id>`: `local_source` makes a `local` DM
whose chat id is the session id (`gateway/session_local_recovery.py`), and
`build_session_key` lays a DM with a chat id out as namespace, platform,
`dm`, chat id, with no participant or thread after it (`gateway/session.py`);
the namespace is `agent:main`, `agent:main~` or `agent:<profile>`, one word
after `agent:` (`_session_key_namespace`). Any other key, a messaging chat's,
or a session whose id only begins or ends like this one's, is another session.
Rotating compaction (`compression.in_place: false`) gives the session a new
stored id while a process keeps the key it started under, so the earlier
segments of the conversation are matched too (`earlier`).

A messaging session (a Telegram or Discord chat a bot profile serves,
resumed here) runs on its chat's route key, which no id of the session
spells. Hermes records that key on the session's own `state.db` row
(`sessions.session_key`, written with the row and refreshed with each turn's
routing peer, `gateway/session_recovery.py`), and the poller reads it
(`routes`). No route is guessed from a key's shape.

One more rule holds for every key: a route outlives one conversation on its
chat (a gateway-side `/new` keeps a local session's route too), so a row is
this session's only when its `parent_session_id`, the session-db id of the
conversation that spawned it (`tools/process_registry.py`), is one of this
session's ids or names a session this one delegated to (`parent_owned`: a
subagent spawns under its own id, `tools/delegate_tool_dispatch.py`). A row
that names no spawning session is decided by its key alone, except under a
recorded route, which every conversation on the chat shares.

Running or ended: every interpreter of a profile rewrites the file from its
own table, so a row can drop out while its process still runs. A host
process is therefore asked directly, by pid and the start time Hermes
recorded (`bot_board.process_is_record`, Hermes' own liveness rule, which a
reused pid does not pass). Where that cannot be asked (another pid
namespace, or off POSIX, where signal 0 is not a probe) the row's presence
decides whether the running row shows, and the process is never said to
have finished (`askable`): a row gone may be one another writer dropped. A
host process whose row another writer drops before the first read is never
seen at all.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Any

from .markdown import clean_text
from .style import Line, Span
from .theme import Theme, kind_style
from .width import cell_width, line_width, truncate, truncate_line

# As `bot_board.ON_POSIX`: signal 0 is a probe only on POSIX. Not imported from there, so a session without a
# background process or the bot board never loads that module.
ON_POSIX = os.name == "posix"

PROCESSES_FILE = "processes.json"
# One running process is about 1.5 KB of checkpoint; a file past this is not read at all.
PROCESSES_MAX_BYTES = 1 << 20
LABEL_CELLS = 32  # the command's words in `terminal(<label>)`, cut with `…`
LABEL_MIN_CELLS = 8  # how short the label is cut to keep the row's right side before the right side goes
PROC_ID_CHARS = 64
PID_LIMIT = 1 << 31
WHOLE_LIMIT = 1 << 63  # a recorded integer past this (a pid, a start time) is not one Hermes wrote
EPOCH_LIMIT = 1e12  # seconds: a `started_at` this far from 1970 either way is not one
# `build_session_key` for a local session: `agent`, the profile word, then these, then the stored id.
ROUTE_HEAD = "agent"
LOCAL_ROUTE = ("local", "dm")

BACKGROUND_WORD = "background"
TOOL_NAME = "terminal"  # the tool that starts a background process
DONE_GLYPH = "✓"
REPORT_KEY = "↵"
REPORT_WORDS = " report result"
WILL_PING = "🔔 will ping you when done"
WILL_PING_MATCH = "🔔 will ping you on a match"
NO_PING = "🔕 "
NO_PING_WORDS = "Hermes won't be pinged · "
WATCHER = "OMH"
WATCHER_WORDS = " is watching it"
# Where OMH cannot ask whether the process still runs (`askable`), it cannot watch for the end either.
NO_PING_UNWATCHED = "won't ping you · "
ASK_WORDS = "ask Hermes for the result"
SIDE_GAP = 2  # the fewest cells between the row's left side and its right side
REPORT_PROMPT = "The background process {calls} finished. Check its result and continue."
REPORT_PROMPTS = "The background processes {calls} finished. Check their results and continue."


@dataclass(frozen=True)
class BackgroundProcess:
    """One running process of this session, as the checkpoint lists it."""

    proc_id: str  # Hermes' process id, `proc_…`
    pid: int | None
    host: bool  # the pid is this machine's (`pid_scope: host`)
    start_time: int | None  # Hermes' start-time fingerprint for the pid (`host_start_time`)
    command: str
    started_at: float  # epoch seconds
    notify: bool  # `notify_on_complete`: Hermes wakes the session when it exits
    watched: bool  # `watch_patterns`: Hermes wakes the session on a matching line, not on exit


def _whole(value: Any) -> int | None:
    """A non-negative integer below `WHOLE_LIMIT`, else None: a huge one would overflow where it is used as a float."""
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < WHOLE_LIMIT else None


def _seconds(value: Any) -> float | None:
    """An epoch within `EPOCH_LIMIT`, else None (NaN, an infinity and a huge integer compare outside)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not -EPOCH_LIMIT < value < EPOCH_LIMIT:
        return None
    return float(value)


def owns_key(key: Any, stored_ids: Collection[str]) -> bool:
    """Whether a process's recorded `session_key` is one of `stored_ids`: the id itself, or the local route
    `agent:<namespace>:local:dm:<id>` (see the module's docstring). Never a prefix, a suffix or a part of one."""
    if not isinstance(key, str) or not key:
        return False
    if key in stored_ids:
        return True
    parts = key.split(":", 4)
    return (
        len(parts) == 5 and parts[0] == ROUTE_HEAD and bool(parts[1]) and tuple(parts[2:4]) == LOCAL_ROUTE
        and parts[4] in stored_ids
    )


def _process(
    row: Any, stored_ids: Collection[str], routes: Collection[str], parent_owned: Callable[[str], bool]
) -> BackgroundProcess | None:
    if not isinstance(row, dict):
        return None
    key, parent = row.get("session_key"), row.get("parent_session_id")
    recorded = isinstance(key, str) and key in routes
    if not (recorded or owns_key(key, stored_ids)):
        return None
    if isinstance(parent, str) and parent:
        if parent not in stored_ids and not parent_owned(parent):
            return None
    elif recorded and not owns_key(key, stored_ids):
        return None  # a chat's route with no spawning session named: any conversation on the chat may own it
    proc_id, command, started_at = row.get("session_id"), row.get("command"), _seconds(row.get("started_at"))
    if not isinstance(proc_id, str) or not proc_id or len(proc_id) > PROC_ID_CHARS or not isinstance(command, str):
        return None
    if started_at is None:
        return None
    pid = _whole(row.get("pid"))
    watch = row.get("watch_patterns")
    return BackgroundProcess(
        proc_id=proc_id,
        pid=pid if pid is not None and 1 < pid < PID_LIMIT else None,
        host=row.get("pid_scope") == "host",
        start_time=_whole(row.get("host_start_time")),
        command=command,
        started_at=started_at,
        notify=row.get("notify_on_complete") is True,
        watched=isinstance(watch, list) and any(isinstance(item, str) and item for item in watch),
    )


def read_processes(
    hermes_home: object,
    session_key: str,
    earlier: Sequence[str] = (),
    routes: Sequence[str] = (),
    parent_owned: Callable[[str], bool] = lambda _parent: False,
) -> tuple[BackgroundProcess, ...]:
    """The rows of `<hermes_home>/processes.json` this session owns: under its stored id or one of the `earlier`
    segments of its conversation (`owns_key`), or one of the `routes` Hermes recorded for those ids, and spawned by
    one of those ids or by a session `parent_owned` says this one delegated to (see the module's docstring); none
    for no home, no key, or a file that is missing, unreadable, past
    `PROCESSES_MAX_BYTES`, or not a list, or whose rows cannot be read. Never raises (the HUD poller's thread calls
    it, and an exception there would end that thread), never writes."""
    if not isinstance(hermes_home, str) or not hermes_home or not session_key:
        return ()
    stored_ids = {session_key, *earlier}
    try:
        with open(Path(hermes_home) / PROCESSES_FILE, "rb") as handle:
            raw = handle.read(PROCESSES_MAX_BYTES + 1)
    except (OSError, ValueError):
        return ()
    if len(raw) > PROCESSES_MAX_BYTES:
        return ()
    try:
        rows = json.loads(raw)
    except (ValueError, RecursionError):
        return ()
    if not isinstance(rows, list):
        return ()
    try:
        found = tuple(_process(row, stored_ids, set(routes), parent_owned) for row in rows)
    except (ArithmeticError, ValueError, TypeError, RecursionError):
        return ()  # a value the checks above did not foresee: nothing is read rather than the poller lost
    return tuple(process for process in found if process is not None)


def askable(process: BackgroundProcess) -> bool:
    """Whether this machine can ask whether the process still runs: a host pid, on POSIX."""
    return process.host and process.pid is not None and ON_POSIX


def process_running(process: BackgroundProcess) -> bool | None:
    """Whether a host process still runs and is the one Hermes started; None where that cannot be asked here."""
    if not askable(process):
        return None
    from .bot_board import process_is_record  # on demand, as `ON_POSIX` says

    return process_is_record(process.pid, process.start_time)


def still_running(
    tracked: Mapping[str, BackgroundProcess],
    listed: Sequence[BackgroundProcess],
    probe: Callable[[BackgroundProcess], bool | None] = process_running,
) -> dict[str, BackgroundProcess]:
    """The processes that still run: those tracked so far and those `listed` now (a listed row is the newer copy),
    each kept while `probe` says it runs, or, where it cannot tell, while the checkpoint lists it."""
    named = {process.proc_id for process in listed}
    merged = {**tracked, **{process.proc_id: process for process in listed}}
    kept: dict[str, BackgroundProcess] = {}
    for proc_id, process in merged.items():
        running = probe(process)
        if running or (running is None and proc_id in named):
            kept[proc_id] = process
    return kept


def process_label(command: str) -> str:
    """`command`'s first words for `terminal(<label>)`: leading `cd <dir> &&` and `NAME=value` assignments dropped,
    the rest cut to `LABEL_CELLS` with `…`. Only those two prefixes are dropped; nothing else is read into it."""
    words = clean_text(command).split()
    while words:
        if words[0] == "cd":
            if "&&" not in words:
                break
            words = words[words.index("&&") + 1 :]
        elif _assignment(words[0]):
            words = words[_assignment_end(words) :]
            if words[:1] == ["&&"]:
                words = words[1:]
        else:
            break
    return truncate(" ".join(words), LABEL_CELLS) if words else ""


def _assignment(word: str) -> bool:
    name, equals, _value = word.partition("=")
    return bool(equals) and name.isidentifier() and name.isascii()


def _assignment_end(words: Sequence[str]) -> int:
    """How many words the assignment at `words[0]` takes: one, or up to the word that closes a quote it opens."""
    value = words[0].partition("=")[2]
    quote = value[:1]
    if quote not in ("'", '"') or (len(value) > 1 and value.endswith(quote)):
        return 1
    return next((index + 1 for index, word in enumerate(words[1:], 1) if word.endswith(quote)), len(words))


def tool_call(process: BackgroundProcess) -> str:
    """`terminal(<label>)`, as the report prompt names the process."""
    return f"{TOOL_NAME}({process_label(process.command)})"


def report_prompt(processes: Sequence[BackgroundProcess]) -> str:
    """The one prompt Enter sends for the processes that ended unreported, each named by its call and proc id."""
    calls = ", ".join(f"`{tool_call(process)}` ({process.proc_id})" for process in processes)
    return (REPORT_PROMPT if len(processes) == 1 else REPORT_PROMPTS).format(calls=calls)


def running_text(seconds: float) -> str:
    """`13s`, `7m 13s`, `1h 07m 13s`: with seconds always, so the row visibly ticks."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total // 3600}h {total // 60 % 60:02d}m {total % 60:02d}s"


def ago_text(seconds: float) -> str:
    """`0:12`, `14:05`, `1:02:03`: how long ago a process ended, as a clock."""
    total = max(0, int(seconds))
    if total < 3600:
        return f"{total // 60}:{total % 60:02d}"
    return f"{total // 3600}:{total // 60 % 60:02d}:{total % 60:02d}"


def _call(label: str, theme: Theme) -> tuple[Span, ...]:
    return (Span(TOOL_NAME, kind_style(TOOL_NAME, theme)), Span(f"({label})", theme.muted))


def _sides(left: Callable[[str], Line], label: str, right: Line, width: int) -> Line:
    """The left side drawn with `label`, then `right` flush to the edge. Where both do not fit the label is cut
    first, down to `LABEL_MIN_CELLS`; then `right` goes and the label is cut again, down to its `…`, so the clock
    stays; only then is the left side cut at the edge."""
    for side, shortest in ((right, LABEL_MIN_CELLS), ((), 1)):
        room = width - (SIDE_GAP + line_width(side) if side else 0)
        over = line_width(left(label)) - room
        if over > 0 and cell_width(label) - over < shortest:
            continue
        shown = left(truncate(label, cell_width(label) - over) if over > 0 else label)
        return (*shown, Span(" " * (width - line_width(shown) - line_width(side))), *side) if side else shown
    return truncate_line(left(label), width)


def _watching(theme: Theme) -> tuple[Span, ...]:
    """`OMH is watching it` in a catch row's colours (`theme.catch_mark`, `catch_words`), else brand and muted."""
    steps = theme.catch_mark or (theme.brand,)
    words = theme.catch_words if theme.catch_mark else theme.muted
    mark = tuple(Span(char, steps[min(index, len(steps) - 1)]) for index, char in enumerate(WATCHER))
    return (*mark, Span(WATCHER_WORDS, words))


def running_line(
    process: BackgroundProcess, *, more: int, now: float, glyph: str, turn_runs: bool, theme: Theme, width: int
) -> Line:
    """`<glyph> background  terminal(<label>)  1h 07m 13s`, then who will be told when it ends: nothing while a turn
    runs (the model may be waiting on it), `🔔 will ping you…` when Hermes will wake the session, else
    `🔕 Hermes won't be pinged · OMH is watching it`, or, where OMH cannot ask whether it still runs (`askable`),
    `🔕 won't ping you · ask Hermes for the result`. `more` counts the session's other running processes."""
    word = theme.background_word

    def left(label: str) -> Line:
        return (
            Span(glyph, word), Span(" "), Span(BACKGROUND_WORD, word), Span("  "), *_call(label, theme),
            Span(f"  {running_text(now - process.started_at)}", theme.faint),
            *((Span(f"  +{more} more", theme.muted),) if more else ()),
        )

    if turn_runs:
        right: Line = ()
    elif process.notify:
        right = (Span(WILL_PING, theme.ok),)
    elif process.watched:
        right = (Span(WILL_PING_MATCH, theme.ok),)
    elif askable(process):
        right = (Span(NO_PING, theme.warn), Span(NO_PING_WORDS, theme.warn), *_watching(theme))
    else:
        words = theme.catch_words if theme.catch_mark else theme.muted
        right = (Span(NO_PING, theme.warn), Span(NO_PING_UNWATCHED, theme.warn), Span(ASK_WORDS, words))
    return _sides(left, process_label(process.command), right, width)


def finished_line(process: BackgroundProcess, *, ago: float, theme: Theme, width: int, more: int = 0) -> Line:
    """`✓ background  terminal(<label>)  finished 0:12 ago`, the state in `ok`, and `↵ report result` at the edge.
    `more` counts the other processes that ended unreported since, which the same Enter reports."""

    def left(label: str) -> Line:
        return (
            Span(DONE_GLYPH, theme.ok), Span(" "), Span(BACKGROUND_WORD, replace(theme.ok, bold=True)), Span("  "),
            *_call(label, theme), Span(f"  finished {ago_text(ago)} ago", theme.ok),
            *((Span(f"  +{more} more", theme.muted),) if more else ()),
        )

    right: Line = (Span(REPORT_KEY, replace(theme.text, bold=True)), Span(REPORT_WORDS, theme.hint))
    return _sides(left, process_label(process.command), right, width)
