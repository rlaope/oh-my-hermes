"""The OMH panels the TUI draws above the composer (the plan) and under the info line (the agent view).

Two halves. `HudPoller` reads `read_omh_hud` IN PROCESS on a background thread
-- the retired Hermes status widget had to spawn a Python child every two
seconds for the same payload -- importing the HUD reader there on its first
read rather than with this module, and hands each new payload to the UI thread
through a latest-value slot it can poll without blocking. Each read also takes
the output tokens of the subagents the agent view is watching from state.db,
in one read-only query (`read_output_tokens`). `panel_lines` turns
one payload into styled rows: the agents block (header, activity rows,
`+N more`), then the delegation block (the conversation's delegation graph,
drawn by `delegation_view` as its tree, the boxes being `/dag`'s, and once
every lane has settled one summary line, `dag_run_summary`), then the plan
block (`[Plan]` header and its checklist). The app asks for the plan block
alone for the slot above the composer, where the plan always sat, and for the
agents and delegation blocks alone for the agent view under the info line
(the owner's call of 2026-10-21: the subagent view goes under the prompt,
always expanded, as Claude Code's agent list does). While the
delegation block holds native lanes, the agents block leaves out their
activity rows, so no lane is drawn twice; its header (`● main │ …`) keeps the
session's cost and tokens. The delegation block is the one block painted at
the terminal's colour depth (`dag_style`); the rest of the panel is 24-bit.

The information design is that widget's, which this module took over when
it was deleted: the same glyphs, labels, colour roles, column grid and shed
priorities, ported to `Line`s, and `tests/test_tui_panels.py` holds the rows
to the ones the widget drew (`tests/fixtures/tui_panel_rows.json`). The widget's
`⚚ [OMH] vX` brand is not drawn (the version stays in the banner); its
session-wide chips (repeat guard, in-flight tool calls) move to the right of
the info line under the composer through `hud_chips`, but not its yolo chip
(see there); the agents block opens with `● main`, as the agent list does.

The panel never draws more than the rows it is given. Under pressure
activity rows go first, done ones first and running ones last (always
disclosed on a `+N more` row, `+N done` when every row it stands for
finished), then the delegation tree shrinks to a few rows (its renderer hides
done lanes first and running ones last, disclosed on a `+N more nodes` row),
then plan items (the window shrinks around the active item, the header always
stays), then the agents header, then the delegation block down to its header
and then that header, then the plan header.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import timezone
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
import traceback
from typing import Any
import unicodedata
from urllib.parse import quote

from ..plugin_bundle.omh.hud_text import elapsed_text, todo_unchanged_text
from ..version import __version__
from .background import BackgroundProcess, read_processes, still_running
from .escapes import strip_escapes
from .style import NO_COLOR, TRUECOLOR, Line, Span, Style
from .theme import CATCH_MARK as CATCH_MARK  # re-exported: app and tests read the mark from here
from .theme import Theme
from .width import cell_width, cluster_width, clusters, line_width, truncate, truncate_line
from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat

HUD_POLL_MIN_SECONDS = 2.0
HUD_POLL_MAX_SECONDS = 8.0
TOKEN_WATCH_CAP = 64  # the roster's own cap: one query never names more child sessions than the agent view holds
# A session's background-process ownership facts read off state.db on the poller thread (`HudPoller.poll_once`):
LINEAGE_READS = 5  # reads that may ask again while the earlier segments are `unverified`
ROUTE_READS = 5  # reads that may ask again while no row of the session is there to name its route
PARENT_CACHE = 256  # spawning sessions decided per session; one past this is not asked and not this session's
PARENT_READS = 5  # reads that may ask again about a spawning session state.db could not decide (`delegated_from`)
DELEGATION_DEPTH = 8  # delegation links followed from a spawning session back to this one
FAILURE_CHARS = 200  # a failed read's `error` in the snapshot: class, where it raised, and its repr, cut to this

# The fields that drift on every poll without anything having happened: the
# widget's VOLATILE_KEYS. A payload differing only here is still delivered (so
# figures stay fresh), but it does not reset the poll back-off.
VOLATILE_KEYS = frozenset(
    {
        "cache_hit_percentage",
        "context_percentage",
        "cost_usd",
        "elapsed_seconds",
        "observed_at",
        "tokens",
        "tokens_per_second",
        "tool_count",
        "turn_count",
        "oldest_open_elapsed_seconds",
        "updated_age_seconds",
    }
)

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# The agent view's first row, the agents block's header and the agent list's main row alike.
MAIN_MARK = "●"
MAIN_NAME = "main"
# The host's shimmer clock ticks every 90 ms; the spinner and the active
# item's colour wave read their frame from it.
FRAME_MILLISECONDS = 90
SEPARATOR = " │ "
ROW_SEPARATOR = "  ·  "
TODO_DISPLAY_ROWS = 8
PLAN_MARKERS = {"active": "[•]", "done": "[✓]", "pending": "[ ]"}
WAITING_CHROME_CELLS = 12  # ` (waiting: ` plus the closing `)`
MIN_ITEM_TEXT_CELLS = 24
REASON_CELLS_CEILING = 48  # TODO_BLOCKED_REASON_DISPLAY_CHARS in runtime_reader.py
DEFAULT_AGENT_ROWS = 5
ROUTE_PREFIX = "category:"
MAESTRO_EXECUTOR_SHORT_NAMES = {
    "codex": "codex",
    "claude_code": "claude",
    "pi_family_runtime": "pi",
    "hermes_local": "hermes",
}
STATE_ABBREVIATIONS = {
    "running": "run",
    "blocked": "block",
    "failed": "fail",
    "scheduled": "sched",
    "archived": "arch",
    "review": "rev",
}
# The widget's text allowlist: letters, digits and the punctuation the row
# grammar is shaped by. Everything else (controls, escapes, emoji) is dropped.
_SAFE_PUNCTUATION = frozenset(" .:/_·|+()[]!-',;?\"#%&=@~")


# ── poller ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HudSnapshot:
    """One delivery: whose payload, the payload (None = empty panel), when it was read, the watched subagents'
    output tokens the same read took (child session id to count; `read_output_tokens`), the session's background
    processes still running (`background.still_running`), oldest first, and how many `HudPoller.refresh` calls came
    before the read started (a read is newer than a refresh only when this is at least what that call returned)."""

    session_id: str
    payload: Mapping[str, Any] | None
    received_at: float
    output_tokens: Mapping[str, int] = field(default_factory=dict)
    processes: tuple[BackgroundProcess, ...] = ()
    refreshes: int = 0
    earlier: tuple[str, ...] = ()  # the conversation's earlier segments the read verified (`earlier_segments`)
    failed: bool = False  # a read that raised (`HudPoller._read_failed`): its processes are the last ones read


HudReader = Callable[..., Mapping[str, Any]]


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_volatile(item) for key, item in value.items() if key not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_without_volatile(item) for item in value]
    return value


def _fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


class HudPoller:
    """Reads the HUD payload off the UI thread and keeps the newest one for `take()`.

    Nothing is read, and nothing delivered, until `set_session` names the
    stored session id: before that the panel stays empty rather than showing
    whichever session was active last. Switching to another id (a new session,
    or the rotation compression makes) delivers an empty snapshot at once, so
    the previous session's plan never outlives the switch, and wakes the
    thread to read the new one. A read that finishes after a switch is
    discarded.

    The interval starts at two seconds and doubles to eight while the payload
    is unchanged apart from `VOLATILE_KEYS`; any other change resets it. A read
    that keeps a new snapshot calls `on_snapshot` (the wake `start` was given),
    so the UI loop takes it at once instead of at its next idle wake-up.

    Each read also takes `output_tokens` for the child sessions `watch_tokens`
    last named. A count that moved is a change like any other, so the poll
    stays at two seconds while subagents are writing and backs off once they
    stop. With no session watched there is no query.

    Each read also takes the session's background processes from Hermes'
    `processes.json` (`background.read_processes`) and keeps every one it has
    seen while it still runs, so a row another interpreter's rewrite dropped
    stays until its process ends. A process starting or ending is a change.
    The first read of a session also reads which earlier segments of its
    conversation rotating compaction left (`earlier_segments`): their
    processes are this session's too, and when the session switched from is
    one of them, what was kept for it is kept on. Reads go on asking which
    route keys Hermes recorded for those ids (`recorded_routes`) until one
    is found, for a messaging session's processes.
    """

    def __init__(
        self,
        omh_home: Any,
        hermes_home: Any,
        *,
        package_version: str = __version__,
        reader: HudReader | None = None,  # None: `runtime_reader.read_omh_hud`, imported on the first read
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._omh_home = omh_home
        self._hermes_home = hermes_home
        self._package_version = package_version
        self._reader = reader
        self._clock = clock
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._session = ""
        self._generation = 0
        self._pending: HudSnapshot | None = None
        self._watched: tuple[str, ...] = ()
        self._processes: dict[str, BackgroundProcess] = {}
        self._earlier: tuple[str, ...] | None = None  # None: not settled yet for this session
        self._earlier_reads = 0
        self._routes: tuple[str, ...] | None = None  # the route keys Hermes recorded for those ids; None: ask
        self._route_reads = 0
        self._parents: dict[str, bool] = {}  # spawning session id -> whether this session delegated to it (decided)
        self._parent_asks: dict[str, int] = {}  # spawning session id -> reads that could not decide it yet
        self._parents_for: tuple[str, ...] = ()  # the session's ids the "not delegated" answers were decided against
        self._left: tuple[str, dict[str, BackgroundProcess]] = ("", {})  # the session switched from, its processes
        # `refresh` calls, and the most a read that started after them has accounted for: that read is kept as new.
        self._refreshes = 0
        self._refreshed = 0
        self._last_full = ""
        self._last_structural = ""
        self._interval = HUD_POLL_MIN_SECONDS
        self.on_snapshot: Callable[[], None] | None = None

    def start(self, wake: Callable[[], None] | None = None) -> None:
        """Start the reading thread; `wake` is called, on that thread, after each read that keeps a new snapshot."""
        self.on_snapshot = wake
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="omh-hud-poller", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stopping.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def set_session(self, stored_id: str) -> None:
        with self._lock:
            if stored_id == self._session:
                return
            self._left = (self._session, self._processes)  # kept on if the first read finds it an earlier segment
            self._session = stored_id
            self._generation += 1
            self._processes = {}
            self._earlier, self._earlier_reads, self._routes, self._route_reads = None, 0, None, 0
            self._parents, self._parent_asks, self._parents_for = {}, {}, ()
            self._last_full = ""
            self._last_structural = ""
            self._interval = HUD_POLL_MIN_SECONDS
            self._pending = HudSnapshot(stored_id, None, self._clock())
        self._wake.set()

    def watch_tokens(self, session_ids: Sequence[str]) -> None:
        """Name the child sessions each read takes output tokens for (`Roster.token_sessions`); none stops it.

        A session not watched before (a subagent that just started) wakes the
        thread and starts the back-off over, so its first count does not wait
        out an eight-second interval. Naming the same sessions again, or
        fewer, wakes nothing.
        """
        watched = tuple(session_ids)[:TOKEN_WATCH_CAP]
        with self._lock:
            new = not set(watched) <= set(self._watched)
            self._watched = watched
            if new:
                self._interval = HUD_POLL_MIN_SECONDS
        if new:
            self._wake.set()

    def refresh(self) -> int:
        """Read again now rather than at the next poll, and start the back-off over (Hermes' plan just changed, or a
        turn ended). The first read that starts after this call is kept even when nothing in it changed, so the UI
        sees what runs once a turn is over (`App._take_background`); a read already under way is not that read.
        Returns the count a snapshot's `refreshes` reaches once it comes from such a read."""
        with self._lock:
            self._interval = HUD_POLL_MIN_SECONDS
            self._refreshes += 1
            count = self._refreshes
            # A turn may have recorded the route (`_record_gateway_session_peer`) or delegated: ask again.
            self._routes, self._route_reads = None, 0
            self._parents = {parent: True for parent, owned in self._parents.items() if owned}
            self._parent_asks = {}
        self._wake.set()
        return count

    def take(self) -> HudSnapshot | None:
        """The newest snapshot not yet taken, or None. Never blocks on a read."""
        with self._lock:
            snapshot, self._pending = self._pending, None
        return snapshot

    def poll_once(self) -> float:
        """Read once for the current session and return the seconds to wait before the next read."""
        with self._lock:
            session, generation, watched, tracked = self._session, self._generation, self._watched, self._processes
            refreshes, earlier, (left, carried), routes = self._refreshes, self._earlier, self._left, self._routes
            earlier_reads, route_reads, parents = self._earlier_reads, self._route_reads, dict(self._parents)
            asks, parents_for = dict(self._parent_asks), self._parents_for
        if not session:
            return HUD_POLL_MAX_SECONDS
        payload = self._read(session)
        # The home this read resolved, so the tokens come from the state.db the payload describes.
        home = payload.get("hermes_home")
        tokens = read_output_tokens(home, watched)
        process_home = home if isinstance(home, str) else self._hermes_home
        settled_earlier: tuple[str, ...] | None = earlier
        if earlier is None:  # until Hermes' links verify every earlier segment, or `LINEAGE_READS` reads asked
            earlier, resolved = earlier_segments(process_home, session)
            earlier_reads += 1
            if left in earlier:
                tracked, left, carried = {**carried, **tracked}, "", {}
            if resolved or earlier_reads >= LINEAGE_READS:
                settled_earlier, left, carried = earlier, "", {}
        settled_routes: tuple[str, ...] | None = routes
        if routes is None:  # until a row of the session is there, or `ROUTE_READS` reads asked; again after a turn
            routes, found = recorded_routes(process_home, (session, *earlier))
            route_reads += 1
            if found or route_reads >= ROUTE_READS:
                settled_routes = routes
        owners = (session, *earlier)
        if owners != parents_for:  # "not delegated" was decided against other ids (an unverified lineage, a rotation)
            parents, asks, parents_for = {parent: True for parent, owned in parents.items() if owned}, {}, owners

        def parent_owned(parent: str) -> bool:
            if parent in parents:
                return parents[parent]
            if len(parents) + len(asks) >= PARENT_CACHE:
                return False
            answer = delegated_from(process_home, parent, owners)
            if answer is None:  # state.db could not say (a row not there yet, a read that failed): ask again
                asks[parent] = asks.get(parent, 0) + 1
                if asks[parent] < PARENT_READS:
                    return False
                answer = False
            asks.pop(parent, None)
            parents[parent] = answer
            return answer

        processes = still_running(tracked, read_processes(process_home, session, earlier, routes, parent_owned))
        running = sorted(processes.values(), key=lambda process: (process.started_at, process.proc_id))
        shown = [[process.proc_id, process.notify, process.watched] for process in running]
        full = _fingerprint([payload, tokens, shown])
        structural = _fingerprint([_without_volatile(payload), tokens, shown])
        with self._lock:
            if generation != self._generation:
                return HUD_POLL_MIN_SECONDS
            self._processes, self._earlier, self._left = processes, settled_earlier, (left, carried)
            self._earlier_reads = earlier_reads
            self._parents_for = parents_for
            if refreshes == self._refreshes:
                self._routes, self._route_reads = settled_routes, route_reads
                self._parents, self._parent_asks = parents, asks
            else:  # a refresh since this read began: the route and the sessions found not delegated are asked again
                self._parents, self._parent_asks = {parent: True for parent, owned in parents.items() if owned}, {}
            fresh = full != self._last_full or refreshes != self._refreshed
            self._refreshed = refreshes
            if fresh:
                self._last_full = full
                self._pending = HudSnapshot(session, payload, self._clock(), tokens, tuple(running), refreshes, earlier)
            if structural != self._last_structural:
                self._last_structural = structural
                self._interval = HUD_POLL_MIN_SECONDS
            else:
                self._interval = min(self._interval * 2, HUD_POLL_MAX_SECONDS)
            interval = self._interval
        wake = self.on_snapshot
        if fresh and wake is not None:
            wake()
        return interval

    def _read(self, session: str) -> Mapping[str, Any]:
        try:
            reader = self._reader
            if reader is None:  # on the poller's thread, so the UI thread never waits for this import
                from ..plugin_bundle.omh.runtime_reader import read_omh_hud as reader
            return reader(
                self._omh_home,
                self._hermes_home,
                session_ref=session,
                session_scoped=True,
                tui_identity_expected=True,
                package_version=self._package_version,
            )
        except Exception as error:  # noqa: BLE001 - classified in tests/test_broad_exception_policy.py
            return {"error": type(error).__name__}

    def _run(self) -> None:
        while not self._stopping.is_set():
            # Cleared before the read, so a `set_session` landing during it
            # cuts the following wait short instead of being lost.
            self._wake.clear()
            try:
                interval = self.poll_once()
            except Exception as error:  # noqa: BLE001 - classified in tests/test_broad_exception_policy.py
                interval = self._read_failed(error)
            self._wake.wait(interval)

    def _read_failed(self, error: BaseException) -> float:
        """A read that raised past the readers' own guards (or the wake it ends with): the panel says so, naming the
        class, where it raised and its repr (`failure_text`), so a failure that repeats is diagnosable from the screen;
        the snapshot is `failed`, so the background row takes nothing from it (`App._take_background`: no end, no
        quiet stamp, no session change). It calls no callback: the UI loop takes it at its next step, so nothing
        here can raise out of the thread. The next read comes after the longest interval, and the one after it is
        delivered whatever it reads."""
        with self._lock:
            session = self._session
            if session:
                running = tuple(sorted(self._processes.values(), key=lambda process: (process.started_at,
                                                                                     process.proc_id)))
                self._pending = HudSnapshot(session, {"error": failure_text(error)}, self._clock(), {}, running, 0,
                                            self._earlier or (), failed=True)
                self._last_full = self._last_structural = ""
            self._interval = HUD_POLL_MAX_SECONDS
        return HUD_POLL_MAX_SECONDS


def failure_text(error: BaseException) -> str:
    """`<class> at <function>:<line>: <repr>`, cut to `FAILURE_CHARS`: the innermost frame the exception passed."""
    frames = traceback.extract_tb(error.__traceback__)
    where = f" at {frames[-1].name}:{frames[-1].lineno}" if frames else ""
    return truncate(f"{type(error).__name__}{where}: {error!r}", FAILURE_CHARS)

def earlier_segments(hermes_home: object, session_id: str) -> tuple[tuple[str, ...], bool]:
    """The earlier segments of `session_id`'s conversation, nearest first, as far as Hermes' compaction links verify
    them (`live_session.compaction_ancestors`, read-only), and whether the walk resolved: an `unverified` answer
    (a state.db that could not be read, a row not there yet) lists only the segments it verified, and may list more
    when asked again. None, resolved, for no home. A rotation is the only way one session continues another, so a
    session switched to that does not name the one left is another conversation."""
    from ..plugin_bundle.omh.live_session import compaction_ancestors

    if not isinstance(hermes_home, str) or not hermes_home or not session_id:
        return (), True
    try:
        answer = compaction_ancestors(hermes_home, session_id)
    except (OSError, ValueError):
        return (), False
    found = answer.get("ancestors")
    segments = tuple(item for item in found if isinstance(item, str)) if isinstance(found, list) else ()
    return segments, answer.get("status") == "resolved"


def _state_db(hermes_home: object) -> sqlite3.Connection | None:
    """`<hermes_home>/state.db` opened as the HUD reader opens it (`mode=ro`, a quarter-second busy wait, the path
    quoted); None for no home, no file, or one that cannot be opened."""
    if not isinstance(hermes_home, str) or not hermes_home:
        return None
    try:
        state_db = Path(hermes_home) / "state.db"
        if not state_db.is_file():
            return None
    except (OSError, ValueError):
        return None
    try:
        return sqlite3.connect(f"file:{quote(str(state_db))}?mode=ro", uri=True, timeout=0.25)
    except sqlite3.Error:
        return None


def delegated_from(hermes_home: object, session_id: str, owners: Collection[str]) -> bool | None:
    """Whether `session_id` is a subagent session one of `owners` delegated to, directly or through other subagents
    (at most `DELEGATION_DEPTH` links), read-only off state.db; None when state.db cannot say yet (no file, a row not
    there yet, a read that failed), which the caller asks again. A link is a row whose `_delegate_from` names its
    own `parent_session_id` (`tools/delegate_tool.py`, which stamps it once on the child): taken from the first
    segment of the row's conversation when the child was itself rotated (`compaction_ancestors`), so a parallel
    continuation of one of `owners` counts as theirs, as `conversation_segments` counts it. A branch or a reset is
    another conversation and is no link."""
    from ..plugin_bundle.omh.live_session import compaction_ancestors

    if session_id in owners:
        return True
    connection = _state_db(hermes_home)
    if connection is None:
        return None
    try:
        current = session_id
        for _ in range(DELEGATION_DEPTH):
            found = compaction_ancestors(str(hermes_home), current).get("ancestors")
            first = found[-1] if isinstance(found, list) and found and isinstance(found[-1], str) else current
            if first in owners:
                return True
            row = connection.execute(
                "SELECT parent_session_id, model_config FROM sessions WHERE id = ?", (first,)
            ).fetchone()
            if row is None:
                return None
            if not isinstance(row[0], str) or not row[0] or not isinstance(row[1], str):
                return False
            config = json.loads(row[1])
            if not isinstance(config, dict) or config.get("_delegate_from") != row[0]:
                return False
            current = row[0]
            if current in owners:  # the last link read is tested too
                return True
        return False
    except (sqlite3.Error, OSError, ValueError, RecursionError):
        return None
    finally:
        connection.close()


def recorded_routes(hermes_home: object, session_ids: Sequence[str]) -> tuple[tuple[str, ...], bool]:
    """The route keys Hermes recorded on `session_ids`' rows of the state.db under `hermes_home`
    (`sessions.session_key`: a messaging chat's `agent:<namespace>:<platform>:…`, a local session's route), read-only,
    and whether any of those rows is there (one with no key settles the question until a turn ends). No ids, no
    home, no file, and any SQLite failure read as none, with no row seen."""
    connection = _state_db(hermes_home) if session_ids else None
    if connection is None:
        return (), False
    try:
        rows = connection.execute(
            f"SELECT session_key FROM sessions WHERE id IN ({','.join('?' for _ in session_ids)})", tuple(session_ids)
        ).fetchall()
    except sqlite3.Error:
        return (), False
    finally:
        connection.close()
    return tuple(sorted({row[0] for row in rows if isinstance(row[0], str) and row[0]})), bool(rows)


def read_output_tokens(hermes_home: object, session_ids: Sequence[str]) -> dict[str, int]:
    """`sessions.output_tokens` for each of `session_ids` the state.db under `hermes_home` holds, in one query.

    Read-only: the file is opened as the HUD reader opens it (`mode=ro`, a
    quarter-second busy wait, the path quoted so a `#` or `?` in it is not
    read as the URI's), never created, and closed before this returns.
    Hermes adds each API call's output tokens to a child's own row as the
    call returns, so a running child's count grows here. A child whose row
    Hermes closed for compaction (`compression.in_place: false`) goes on
    writing in a new row the gateway's frames never name, so its count is
    the sum over every segment of it (`live_session.conversation_segments`),
    as Hermes' own per-agent count is; that lineage is read only for such a
    row. No ids, no home, no file, and any SQLite failure (a locked or
    half-written database, one without the table) read as no counts, never
    as zero.
    """
    from ..plugin_bundle.omh.live_session import COMPACTION_END_REASON, conversation_segments

    if not session_ids or not isinstance(hermes_home, str) or not hermes_home:
        return {}
    try:
        state_db = Path(hermes_home) / "state.db"
        if not state_db.is_file():
            return {}
    except (OSError, ValueError):
        return {}
    try:
        connection = sqlite3.connect(f"file:{quote(str(state_db))}?mode=ro", uri=True, timeout=0.25)
    except sqlite3.Error:
        return {}
    try:
        columns = {row[1] for row in connection.execute('PRAGMA table_info("sessions")')}
        # One of two fixed literals, never caller text.
        reason = "end_reason" if "end_reason" in columns else "NULL"
        rows = connection.execute(
            f"SELECT id, output_tokens, {reason} FROM sessions WHERE id IN ({','.join('?' for _ in session_ids)})",
            tuple(session_ids),
        ).fetchall()
        counts = {str(row[0]): row[1] for row in rows if isinstance(row[1], int)}
        for row in rows:
            if row[2] != COMPACTION_END_REASON or not isinstance(row[1], int):
                continue
            segments = sorted(conversation_segments(connection, str(row[0])))
            written = connection.execute(
                f"SELECT output_tokens FROM sessions WHERE id IN ({','.join('?' for _ in segments)})", segments
            ).fetchall()
            counts[str(row[0])] = sum(found[0] for found in written if isinstance(found[0], int))
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return counts


# ── small formatters (ports of the widget's helpers) ───────────────────────


def _sanitize(value: Any) -> str:
    # Whole escape sequences first: dropping only their ESC byte would leave `[31m` as text.
    text = unicodedata.normalize("NFC", strip_escapes("" if value is None else str(value)))
    return "".join(ch for ch in text if ch in _SAFE_PUNCTUATION or unicodedata.category(ch)[0] in "LN")


def _safe_text(value: Any) -> str:
    return _sanitize(value)[:96]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value: Any) -> int:
    """`Number(value) || 0` for the integer counts the payload carries."""
    if _finite(value):
        return int(value)
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return 0
        return int(number) if math.isfinite(number) else 0
    return 0


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _elapsed(value: Any) -> str:
    return elapsed_text(value) if _finite(value) else ""


def _pad(text: str, cells: int) -> str:
    return text + " " * max(0, cells - cell_width(text))


def _cut(value: Any, cells: int) -> str:
    """The widget's `truncateCells`: sanitize, then cut by cells with an ellipsis."""
    return truncate(_safe_text(value), max(0, cells))


def _token_count_text(value: Any) -> str:
    if not _finite(value) or value < 0:
        return ""
    if value < 1000:
        return f"{math.floor(value)}"
    amount, unit = (value / 1000, "k") if value < 999_950 else (value / 1_000_000, "m")
    return f"{amount:.1f}{unit}"


def _cost_provenance(row: Mapping[str, Any]) -> str:
    """The word the host recorded for a cost (status first, else source); it alone earns a zero a figure."""
    return _safe_text(row.get("cost_status")) or _safe_text(row.get("cost_source"))


def _cost_text(row: Mapping[str, Any]) -> str:
    cost = row.get("cost_usd")
    if not _finite(cost):
        return ""
    if cost > 0:
        return f"{'~' if row.get('cost_approximate') else ''}${cost:.4f}"
    if row.get("cost_approximate"):
        return ""
    provenance = _cost_provenance(row)
    return f"${cost:.4f} ({provenance})" if provenance else ""


def _observed_percent(label: str, value: Any) -> str:
    return f"{label} {value}%" if _finite(value) else ""


def _frame(now: float) -> int:
    return int(now * 1000) // FRAME_MILLISECONDS if _finite(now) else 0


def _epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = strict_fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _bold(style: Style) -> Style:
    return replace(style, bold=True)


def _line(*spans: Span | None) -> Line:
    return tuple(span for span in spans if span is not None and span.text)


# ── info line chips ────────────────────────────────────────────────────────


def _valid(payload: Any) -> bool:
    return isinstance(payload, Mapping) and not payload.get("error") and payload.get("privacy") == "metadata_only"


def _repeat_chip(repeat: Mapping[str, Any]) -> tuple[str, str]:
    """`repeat xN [cycle-of-P] [blocked|approval]` and the stage it reached, or ("", "")."""
    count = _count(repeat.get("consecutive"))
    if repeat.get("status") != "observed" or count < 2:
        return "", ""
    period = _count(repeat.get("period")) or 1
    stage = _safe_text(repeat.get("stage")) if _count(repeat.get("intercepted")) >= 1 else ""
    suffix = " blocked" if stage == "blocking" else " approval" if stage == "approval" else ""
    return f"repeat x{count}{f' cycle-of-{period}' if period > 1 else ''}{suffix}", stage


def hud_chips(payload: Any, theme: Theme, turn_runs: bool = True, question_waits: bool = False) -> tuple[Line, ...]:
    """The HUD's session-wide chips for the info line's right side, each its own line; none without a valid payload.

    The chips are the widget header's facts about the whole session rather
    than its agents: a repeating call (muted while watched, warn once refused,
    error once escalated to a person) and the exact in-flight tool calls (only
    where this install has seen `post_tool_call` fire, and only while
    `turn_runs`: the snapshot lags the turn's end by a poll or more). While
    `question_waits` the calls are counted without the oldest one's seconds,
    since the working row's clock is that wait's. The widget's `yolo mode:
    on|off` chip is not drawn: the info line states the approval mode (accept
    all) as Hermes confirmed it for this session, and the HUD's reading of
    Hermes' saved state lags behind a switch, so the two said opposite things.
    """
    if not _valid(payload):
        return ()
    chips: list[Line] = []
    chip, stage = _repeat_chip(_mapping(payload.get("repeat")))
    if chip:
        tone = theme.error if stage == "approval" else theme.warn if stage == "blocking" else theme.muted
        chips.append((Span(chip, replace(tone, bold=stage != "watching")),))
    activity = _mapping(payload.get("activity"))
    if turn_runs and activity.get("live") and activity.get("post_tool_call_observed"):
        count = _plural(_count(activity.get("open_call_count")), "tool")
        oldest = _elapsed(activity.get("oldest_open_elapsed_seconds")) or "0s"
        chips.append((Span(count if question_waits else f"{count} · {oldest}", theme.warn),))
    return tuple(chips)


# ── plan block ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Plan:
    status: str  # "established" | "all_done"
    title: str
    counts: Mapping[str, Any]
    items: tuple[Mapping[str, Any], ...]
    current_phase: str
    live: bool
    unchanged: str
    shot: Mapping[str, Any]


def _plan_view(payload: Mapping[str, Any]) -> _Plan | None:
    todo = _mapping(payload.get("todo"))
    status = todo.get("status")
    if status not in ("established", "all_done"):
        return None
    activity = _mapping(payload.get("activity"))
    # Green and moving only while the in-flight signal says something runs;
    # where this install never saw post_tool_call fire, liveness cannot be
    # read either way, so the plan keeps the pre-liveness always-live shape.
    answerable = bool(activity.get("post_tool_call_observed"))
    items = tuple(_rows(todo.get("items")))
    if status == "established" and not items:
        return None
    return _Plan(
        status=str(status),
        title=_safe_text(todo.get("title")),
        counts=_mapping(todo.get("counts")),
        items=items,
        current_phase=_safe_text(todo.get("display_phase")),
        live=bool(activity.get("live")) if answerable else True,
        unchanged=todo_unchanged_text(dict(todo)),
        shot=_mapping(payload.get("parallel_shot")),
    )


def _depth(item: Mapping[str, Any]) -> int:
    depth = item.get("depth")
    return min(depth, 3) if isinstance(depth, int) and not isinstance(depth, bool) and depth > 0 else 0


def _groups(items: Sequence[Mapping[str, Any]]) -> list[tuple[str, list[Mapping[str, Any]]]]:
    """Consecutive items of one phase; a phaseless subtask continues its parent's group."""
    groups: list[tuple[str, list[Mapping[str, Any]]]] = []
    for item in items:
        phase = _safe_text(item.get("phase"))
        if groups and (groups[-1][0] == phase or (not phase and _depth(item) > 0)):
            groups[-1][1].append(item)
        else:
            groups.append((phase, [item]))
    return groups


def _window_rows(plan: _Plan, start: int, end: int) -> int:
    """Rows a window occupies: its items, one header per phased group, and a fold line per hidden side."""
    phased = sum(1 for phase, _ in _groups(plan.items[start:end]) if phase)
    return end - start + phased + (1 if start > 0 else 0) + (1 if end < len(plan.items) else 0)


def _first_remaining(plan: _Plan) -> int:
    return next((index for index, item in enumerate(plan.items) if item.get("state") != "done"), -1)


def _initial_window(plan: _Plan) -> tuple[int, int]:
    """At most eight items, anchored just before the first remaining one."""
    total = len(plan.items)
    first = _first_remaining(plan)
    anchor = 0 if first < 0 else max(0, first - 1)
    start = min(anchor, total - TODO_DISPLAY_ROWS) if total > TODO_DISPLAY_ROWS else 0
    return start, min(total, start + TODO_DISPLAY_ROWS)


def _shrink_window(plan: _Plan, start: int, end: int) -> tuple[int, int]:
    """One item fewer: a done item ahead of the one the panel exists to show first (it joins the `✓ N done` row),
    then from the side farther from that item."""
    active = next((index for index, item in enumerate(plan.items) if item.get("state") == "active"), -1)
    focus = active if active >= 0 else max(_first_remaining(plan), 0)
    focus = min(max(focus, start), end - 1)
    if start < focus and plan.items[start].get("state") == "done":
        return start + 1, end
    if end - 1 - focus >= focus - start:
        return start, end - 1
    return start + 1, end


def _shot_badge(shot: Mapping[str, Any], now: float, theme: Theme) -> Span | None:
    """`parallel shot ×N` while N of the batch's calls are open; else the measured peak, dimmed with its age.

    No badge shows a number below 2: a batch whose calls never overlapped (a peak of 1, calls run one after another
    inside the plugin's grouping window) was no parallel shot. While one call of a real overlap is still open, the
    badge is the peak's.
    """
    if shot.get("status") != "observed":
        return None
    open_count = _count(shot.get("open_count"))
    if open_count > 1:
        return Span(f" · parallel shot ×{open_count}", theme.label)
    peak = _count(shot.get("peak_open_count"))
    if peak < 2:
        return None
    observed = _epoch(shot.get("observed_at"))
    age = elapsed_text(max(0.0, now - observed)) if observed is not None and _finite(now) else ""
    return Span(f" · parallel shot ×{peak}{f' ({age} ago)' if age else ''}", theme.muted)


def _skipped_clause(counts: Mapping[str, Any]) -> str:
    skipped = _count(counts.get("skipped"))
    return f" ({skipped} skipped)" if skipped > 0 else ""


def _plan_header(plan: _Plan, now: float, theme: Theme) -> Line:
    counts = plan.counts
    title = Span(f" {plan.title}", theme.muted) if plan.title else None
    badge = _shot_badge(plan.shot, now, theme)
    total = _count(counts.get("total"))
    if plan.status == "all_done":
        worked = max(0, _count(counts.get("done")) - _count(counts.get("skipped")))
        return _line(
            Span("[Plan]", theme.heading),
            title,
            Span(SEPARATOR, theme.rule),
            Span(f"✓ {worked}/{total}", theme.ok),
            Span(_skipped_clause(counts), theme.muted),
            badge,
        )
    phases = _count(counts.get("phases"))
    return _line(
        Span("[Plan]", theme.heading),
        title,
        Span(SEPARATOR, theme.rule),
        Span(f"{_count(counts.get('done'))}/{total}", theme.warn),
        Span(_skipped_clause(counts), theme.muted),
        Span(f" · {phases} phases", theme.muted) if phases > 1 else None,
        badge,
    )


def _shimmer(text: str, frame: int, theme: Theme) -> list[Span]:
    """A colour wave through the active item's text; the characters never move."""
    units = clusters(text)
    if not units:
        return []
    cycle = max(8, len(units) + 4)
    head = frame % cycle
    spans: list[Span] = []
    for index, unit in enumerate(units):
        style = _bold(theme.muted) if (index - head) % cycle < 3 else _bold(theme.ok)
        if spans and spans[-1].style == style:
            spans[-1] = Span(spans[-1].text + unit, style)
        else:
            spans.append(Span(unit, style))
    return spans


def _plan_item(
    plan: _Plan, item: Mapping[str, Any], indent: str, columns: int, frame: int, theme: Theme, motion: bool = True
) -> Line:
    budget = max(16, columns - 10)
    reason_cells = max(8, min(REASON_CELLS_CEILING, budget - WAITING_CHROME_CELLS - MIN_ITEM_TEXT_CELLS))
    reason = _cut(item.get("blocked_reason"), reason_cells)
    text = _cut(item.get("text"), max(8, budget - reason_cells - WAITING_CHROME_CELLS) if reason else budget)
    state = item.get("state")
    marker = PLAN_MARKERS.get(str(state), "[ ]")
    waiting = Span(f" ({'skipped' if state == 'done' else 'waiting'}: {reason})", theme.warn) if reason else None
    if state == "done":  # done is quiet: its words muted, only the check in the done hue
        return _line(Span(f"{indent}[", theme.muted), Span("✓", theme.ok), Span(f"] {text}", theme.muted), waiting)
    if state != "active":
        return _line(Span(f"{indent}{marker} {text}", theme.text), waiting)
    style = _bold(theme.ok if plan.live else theme.warn)
    if plan.live and motion:
        return _line(Span(f"{indent}{marker} ", style), *_shimmer(text, frame, theme), waiting)
    if plan.live:
        return _line(Span(f"{indent}{marker} {text}", style), waiting)
    unchanged = Span(f" (unchanged {plan.unchanged})", theme.muted) if plan.unchanged else None
    return _line(Span(f"{indent}{marker} {text}", style), waiting, unchanged)


def _fold(count: int, side: str, theme: Theme) -> Line:
    return _line(Span(f"... ({count} {side} task{'' if count == 1 else 's'})", theme.muted))


def _done_fold(count: int, theme: Theme) -> Line:
    """The done items above the window, folded into one quiet row."""
    return _line(Span("✓", theme.ok), Span(f" {count} done", theme.muted))


def _current_item(plan: _Plan) -> Mapping[str, Any] | None:
    """The item the plan is on: the active one, else the first not done."""
    active = next((item for item in plan.items if item.get("state") == "active"), None)
    return active or next((item for item in plan.items if item.get("state") != "done"), None)


def _with_hint(head: Line, tail: Line, hint: str, columns: int, theme: Theme) -> Line:
    """`head`, then `tail` cut to what is left, then `hint` dim on the right edge; the hint goes first when the
    row is narrow, then `tail`."""
    hint_cells = cell_width(hint) + 2 if hint else 0
    room = columns - line_width(head) - hint_cells
    if hint and room < min(line_width(tail), 12):
        hint_cells, room = 0, columns - line_width(head)
    kept = truncate_line(tail, room) if room > 0 and tail else ()
    row = (*head, *kept)
    if not hint_cells:
        return row
    return (*row, Span(" " * max(columns - line_width(row) - cell_width(hint), 2)), Span(hint, theme.faint))


def plan_state(payload: Any) -> str:
    """`open` while the payload's plan has an item left, `done` once every item is, "" without a plan."""
    plan = _plan_view(payload) if _valid(payload) else None
    if plan is None:
        return ""
    return "done" if plan.status == "all_done" else "open"


def plan_text(payload: Any) -> str:
    """The whole plan as text, for `/todos` and a retired plan: its header worded as the panel's, then every item
    under its phase; "" without a plan."""
    plan = _plan_view(payload) if _valid(payload) else None
    if plan is None:
        return ""
    counts = plan.counts
    title = f" {plan.title}" if plan.title else ""
    total = _count(counts.get("total"))
    if plan.status == "all_done":  # the count as the panel's header says it (`_plan_header`)
        count = f"✓ {max(0, _count(counts.get('done')) - _count(counts.get('skipped')))}/{total}"
    else:
        count = f"{_count(counts.get('done'))}/{total}"
    rows = [f"[Plan]{title}{SEPARATOR}{count}{_skipped_clause(counts)}"]
    for phase, items in _groups(plan.items):
        if phase:
            rows.append(phase)
        for item in items:
            indent = "  " * (_depth(item) + (1 if phase else 0))
            state = item.get("state")
            reason = _safe_text(item.get("blocked_reason"))
            waiting = f" ({'skipped' if state == 'done' else 'waiting'}: {reason})" if reason else ""
            rows.append(f"{indent}{PLAN_MARKERS.get(str(state), '[ ]')} {_safe_text(item.get('text'))}{waiting}")
    return "\n".join(rows)


# ── catch rows ─────────────────────────────────────────────────────────────

# One emoji per catch kind (`catch_log.CATCH_KINDS`), between the mark and the sentence. Each is a default-emoji
# code point (no U+FE0F) two cells wide. A kind not listed here is not printed.
CATCH_EMOJI = {"repeat_loop": "🔁", "truncated_read": "📖", "plan_continued": "📋", "unarmed_wait": "⏰"}


def _catch_sentence(entry: Mapping[str, Any]) -> str:
    """What OMH did, worded from the entry's kind and numbers; "" for a kind or number this cannot word."""
    kind = entry.get("kind")
    numbers = {key: value for key, value in entry.items() if isinstance(value, int) and not isinstance(value, bool)}
    if kind == "repeat_loop" and numbers.get("laps", 0) > 0 and numbers.get("period", 0) > 0:
        if numbers["period"] == 1:
            return f"stopped a loop of {numbers['laps']} identical calls"
        return f"stopped a loop of {numbers['period']} calls repeated {numbers['laps']} times"
    if kind == "truncated_read" and numbers.get("offset", 0) > 0:
        return f"pointed the re-read at line {numbers['offset']}"
    if kind == "plan_continued" and numbers.get("open_items", 0) > 0:
        count = numbers["open_items"]
        return f"kept going, plan has {count} open item{'' if count == 1 else 's'}"
    if kind == "unarmed_wait":
        return "flagged a wait with nothing armed to wake it"
    return ""


def catch_lines(payload: Any) -> list[tuple[int, str]] | None:
    """The payload's catches as `(seq, line)`, oldest first: `🔁 stopped a loop of 3 identical calls`, the mark
    (`CATCH_MARK`) drawn before it apart. An entry this cannot word keeps its `seq` with the line "", so a reader
    still counts it as seen; one without a usable `seq` is left out. None for a payload that is not a readable HUD
    (an error, or not metadata-only): it says nothing about which catches exist, so a reader must not set a mark on it.
    """
    if not _valid(payload):
        return None
    catches = payload.get("catches")
    rows: list[tuple[int, str]] = []
    for entry in catches if isinstance(catches, list) else []:
        seq = entry.get("seq") if isinstance(entry, Mapping) else None
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            continue
        emoji = CATCH_EMOJI.get(str(entry.get("kind")))
        sentence = _catch_sentence(entry) if emoji else ""
        rows.append((seq, f"{emoji} {sentence}" if sentence else ""))
    return rows


def _plan_lines(
    plan: _Plan, start: int, end: int, collapsed: bool, columns: int, now: float, theme: Theme, motion: bool = True,
    fold_key: str = "", folded: bool = False,
) -> list[Line]:
    """The plan: its header, then its items in the window. Collapsed (`folded` by the person, or shed for room) it is
    the header alone, naming the item it is on. With `fold_key` the header says on its right edge what that key
    does now: `fold` while expanded, `expand` while the person folded it, and nothing while it is collapsed for
    room, where the key could not expand it."""
    header = _plan_header(plan, now, theme)
    if plan.status == "all_done":
        return [header]
    if collapsed:
        current = _current_item(plan)
        tail: Line = (Span(" ▸ ", theme.dim), Span(_safe_text(current.get("text")), theme.text)) if current else ()
        return [_with_hint(header, tail, f"{fold_key} expand" if fold_key and folded else "", columns, theme)]
    lines = [_with_hint(header, (), f"{fold_key} fold" if fold_key else "", columns, theme)]
    frame = _frame(now)
    budget = max(16, columns - 10)
    if start > 0 and all(item.get("state") == "done" for item in plan.items[:start]):
        lines.append(_done_fold(start, theme))
    elif start > 0:
        lines.append(_fold(start, "earlier", theme))
    for phase, items in _groups(plan.items[start:end]):
        if phase:
            tone = theme.label if phase == plan.current_phase else theme.muted
            lines.append(_line(Span(truncate(phase, budget), _bold(tone))))
        for item in items:
            indent = "  " * (_depth(item) + (1 if phase else 0))
            lines.append(_plan_item(plan, item, indent, columns, frame, theme, motion))
    if end < len(plan.items):
        lines.append(_fold(len(plan.items) - end, "later", theme))
    return lines


# ── agents block ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Agents:
    rows: tuple[Mapping[str, Any], ...]  # the MAIN row (if any) first, then the agent rows
    main_count: int
    wanted: int  # rows shown before any pressure: five by default, never fewer than are running
    hidden: int  # rows the reader already capped
    in_graph: int = 0  # native rows left out because the delegation block draws their lanes


def _is_running(row: Mapping[str, Any]) -> bool:
    return not row.get("state") or row.get("state") == "running"


def _delegation_graph(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    graph = _mapping(payload.get("delegation_graph"))
    return graph if graph.get("status") == "active" and _rows(graph.get("nodes")) else None


def _agents_view(payload: Mapping[str, Any], with_graph: bool = True) -> _Agents | None:
    """The agents block's rows; `with_graph` False when the delegation block is not drawn beside it, so no native row
    is left out for a lane nothing draws."""
    active = bool(payload.get("active"))
    agents = _mapping(payload.get("subagents"))
    main = _rows(_mapping(payload.get("maestro")).get("rows"))[:1] if active else []
    rows = _rows(agents.get("rows")) if active else []
    hidden = _count(agents.get("hidden_rows")) if active else 0
    graph = _delegation_graph(payload) if with_graph else None
    drawn = _graph_sessions(graph)
    listed = rows
    hidden_in_graph = 0
    if drawn:
        # A native row whose child the delegation block draws is left out, so one lane is not drawn twice; a row the
        # graph does not hold stays. The header keeps the session's cost and tokens, and Maestro and board rows stay.
        listed = [
            row for row in rows
            if _safe_text(row.get("role")) != "hermes-native" or _safe_text(row.get("task_id")) not in drawn
        ]
        # The rows the reader did not list are counted the same way: the ones the graph draws are its lanes.
        hidden_in_graph = min(hidden, max(0, _count(agents.get("hidden_in_graph")))) if active else 0
        hidden -= hidden_in_graph
    in_graph = len(rows) - len(listed) + hidden_in_graph
    # With no row of its own and no lane in the graph, a header would only say `ready` over the tree's own `◆ main`.
    if not (main or listed or hidden or in_graph):
        return None
    running = sum(1 for row in listed if _is_running(row))
    wanted = len(main) + min(len(listed), max(max(DEFAULT_AGENT_ROWS - len(main), 1), running))
    return _Agents(rows=tuple(main + listed), main_count=len(main), wanted=wanted, hidden=hidden, in_graph=in_graph)


def _graph_sessions(graph: Mapping[str, Any] | None) -> frozenset[str]:
    """The short child session ids (`session_tail`) of the native lanes the delegation graph draws."""
    if graph is None or graph.get("source") != "native" or not isinstance(graph.get("nodes"), list):
        return frozenset()
    return frozenset(
        tail for node in graph["nodes"] if isinstance(node, Mapping) and (tail := _safe_text(node.get("session_tail")))
    )


GRAPH_HOLDS_ALL = "lanes in the graph below"


def _outside_graph_label(view: _Agents) -> str:
    """The header's count while the delegation block draws some of the lanes: what this block still lists, called
    `other`, so the one count of the graph's lanes is the delegation header's."""
    rows = view.rows[view.main_count:]
    if not rows and not view.hidden:
        return GRAPH_HOLDS_ALL
    counts = [_plural(len(rows) + view.hidden, "other agent")]
    for word, matches in (
        ("running", _is_running),
        ("blocked", lambda row: row.get("state") in ("blocked", "failed")),
        ("done", lambda row: row.get("state") == "done"),
    ):
        count = sum(1 for row in rows if matches(row))
        if count:
            counts.append(f"{count} {word}")
    return " · ".join(counts)


def _state_label(active: bool, agents: Mapping[str, Any]) -> str:
    if not active:
        return "ready"
    running = _count(agents.get("running"))
    blocked = _count(agents.get("blocked"))
    done = _count(agents.get("completed"))
    if not running and not blocked and done:
        return f"{done} done"
    parts = [_plural(_count(agents.get("active")), "agent")]
    if running:
        parts.append(f"{running} running")
    if blocked:
        parts.append(f"{blocked} blocked")
    if done:
        parts.append(f"{done} done")
    return " · ".join(parts)


def _session_metrics(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    """(cost, tokens, ctx) summed over the projected rows; "" for any figure no row carries."""
    main = _rows(_mapping(payload.get("maestro")).get("rows"))
    rows = main + _rows(_mapping(payload.get("subagents")).get("rows"))
    cost = sum(row["cost_usd"] for row in rows if _finite(row.get("cost_usd")))
    tokens = sum(row["tokens"] for row in rows if _finite(row.get("tokens")))
    approximate = any(row.get("cost_approximate") for row in rows)
    zero_provenance = next(
        (
            _cost_provenance(row)
            for row in rows
            if _finite(row.get("cost_usd"))
            and row["cost_usd"] == 0
            and not row.get("cost_approximate")
            and _cost_provenance(row)
        ),
        "",
    )
    if cost > 0:
        cost_text = f"{'~' if approximate else ''}${cost:.3f}"
    else:
        cost_text = f"${cost:.3f} ({zero_provenance})" if zero_provenance else ""
    token_text = f"{_token_count_text(tokens)} tokens" if any(_finite(row.get("tokens")) for row in rows) else ""
    ctx = main[0].get("context_percentage") if main and _finite(main[0].get("context_percentage")) else None
    if ctx is None:
        ctx = next((row["context_percentage"] for row in rows if _finite(row.get("context_percentage"))), None)
    return cost_text, token_text, f"ctx {ctx}%" if ctx is not None else ""


def _agents_header(payload: Mapping[str, Any], columns: int, theme: Theme, view: _Agents | None = None) -> Line:
    active = bool(payload.get("active"))
    agents = _mapping(payload.get("subagents"))
    board = _mapping(payload.get("kanban"))
    # One marker for one fact: rows from outside this conversation are listed.
    outside = agents.get("scope") in ("global", "mixed") or any(
        row.get("scope") == "global" for row in _rows(_mapping(payload.get("maestro")).get("rows"))
    )
    cost, tokens, ctx = _session_metrics(payload)
    label = _outside_graph_label(view) if view is not None and view.in_graph else _state_label(active, agents)
    board_tally = (
        f" · board {_count(board.get('queued'))}q {_count(board.get('running'))}r {_count(board.get('blocked'))}b"
        if _count(board.get("rows_total")) > 0
        else ""
    )
    return _line(
        Span(f"{MAIN_MARK} ", theme.running),
        Span(MAIN_NAME, theme.heading),
        Span(SEPARATOR, theme.rule),
        Span(f"{'[global] ' if outside else ''}{label}", theme.muted if label == GRAPH_HOLDS_ALL else
             theme.warn if active else theme.ok),
        Span(board_tally, theme.muted),
        Span(" · dispatcher not observed", theme.warn) if board.get("dispatcher_presence") == "not_observed"
        else None,
        Span(f"{f' • {cost}' if cost else ''}{f' • {ctx}' if ctx else ''}", theme.muted),
        Span(f" • {tokens}", theme.muted) if columns >= 100 and tokens else None,
    )


def _route_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    """(kind, text): `category:name(model:effort)`, `(executor/maestro model)` or `kanban/assignee(model:effort)`."""
    model_name = _safe_text(row.get("model")).split("/")[-1]
    effort = _safe_text(row.get("effort"))
    model = ":".join(part for part in (model_name, effort) if part)
    if _safe_text(row.get("lane_backend")) == "kanban":
        assignee = _safe_text(row.get("assignee")) or "unassigned"
        detail = f"{model_name}{f':{effort}' if effort else ''}" if model_name else ""
        return "kanban", f"kanban/{assignee}{f'({detail})' if detail else ''}"
    lane = _safe_text(row.get("dispatch_lane"))
    if lane:
        executor = _safe_text(row.get("executor_profile"))
        short = MAESTRO_EXECUTOR_SHORT_NAMES.get(executor, executor)
        return "maestro", f"({short}/{lane}{f' {model_name}' if model_name else ''})"
    origin = _safe_text(row.get("route_origin"))
    tag = "fallback" if origin == "fallback" else "inherit" if origin == "exhausted_to_inherit" else ""
    detail = " ".join(part for part in (model, tag) if part)
    route_category = _safe_text(row.get("route_category"))
    category = _safe_text(row.get("category"))
    if origin == "exhausted_to_inherit" and route_category:
        category = route_category
    label = _safe_text(row.get("route_label"))
    if label:
        # Hermes' delegation backend ran this child on the user's option: a model that equals the parent's is not
        # inheritance there, and the option is named beside whatever lane the model maps to.
        lane = "" if category == "inherit" else category
        text = f"{ROUTE_PREFIX}{lane}@{label}{f'({detail})' if detail else ''}"
    elif category == "inherit":
        text = f"inherit{f'({model})' if model else ''}"
    elif category:
        text = f"{ROUTE_PREFIX}{category}{f'({detail})' if detail else ''}"
    else:
        text = model
    return ("route-fallback" if tag else "route"), text


def _compact_route(text: str) -> str:
    return text[len(ROUTE_PREFIX):] if text.startswith(ROUTE_PREFIX) else text


def _kind_tag(row: Mapping[str, Any]) -> str:
    if _safe_text(row.get("lane_backend")) == "kanban":
        return "[bot] "
    return "" if _safe_text(row.get("dispatch_lane")) or _safe_text(row.get("executor_profile")) else "[sub] "


@dataclass(frozen=True)
class _Grid:
    """Columns every row of one list shares, so the tails line up vertically."""

    tokens: bool
    route_full: int
    route_compact: int
    scope: int


def _grid(rows: Sequence[Mapping[str, Any]]) -> _Grid:
    routes = [_route_identity(row)[1] for row in rows]
    return _Grid(
        tokens=any(_token_count_text(row.get("tokens")) for row in rows),
        route_full=max((cell_width(text) for text in routes), default=0),
        route_compact=max((cell_width(_compact_route(text)) for text in routes), default=0),
        scope=max((cell_width(_kind_tag(row)) for row in rows), default=0),
    )


def _route_style(kind: str, theme: Theme) -> Style:
    if kind == "route":
        return theme.label
    if kind in ("route-fallback", "maestro"):
        return theme.warn
    return theme.muted


def _row_marker(state: Any, board: bool, spinner: str, theme: Theme) -> tuple[str, Style, Style]:
    """(marker, marker style, state-word style), by the row's state; a board lane's running one in the running blue."""
    if state in ("blocked", "failed"):
        return "▲", theme.error, theme.error
    if state == "stale":
        return "!", theme.warn, theme.warn
    if state == "done":
        return "✓", theme.ok, theme.ok
    if state == "queued":
        # A queued task has no worker yet, so it must not spin.
        return "·", theme.dim, theme.muted
    return spinner, theme.running if board else theme.warn, theme.running if board else theme.ok


def _segment_style(kind: str, theme: Theme) -> Style:
    # The cache figure is the one row segment the owner reads in amber.
    return theme.warn if kind == "cache" else theme.muted


def _activity_row(
    row: Mapping[str, Any], main: bool, grid: _Grid, columns: int, frame: int, extra_seconds: float, theme: Theme
) -> Line:
    """One agent as a grid row: marker, tag, id, title, route column, then the fixed state/elapsed/tokens tail."""
    raw_state = row.get("state")
    board = _safe_text(row.get("lane_backend")) == "kanban"
    state = (_safe_text(row.get("native_status")) if board else "") or _safe_text(raw_state) or "running"
    state_text = STATE_ABBREVIATIONS.get(state, state) if columns < 100 else state
    task_id = _pad(_cut(_safe_text(row.get("task_id")) or _safe_text(row.get("role")) or "agent", 8), 8)
    turn = f"turn {row['turn_count']}" if _finite(row.get("turn_count")) else ""
    tools = f"{row['tool_count']} tools" if _finite(row.get("tool_count")) else ""
    turn_tools = f"{turn} ({tools})" if turn and tools else turn or tools
    route_kind, route_text = _route_identity(row)
    fallbacks = row.get("fallback_count")
    rate = row.get("tokens_per_second")
    # (kind, text, drop rank): position is reading order, rank is shed order.
    optional = [
        segment
        for segment in (
            ("fallback", f"fallback:{fallbacks}" if _finite(fallbacks) and fallbacks > 0 else "", 1),
            ("rate", f"{math.floor(rate + 0.5)} tok/s" if _finite(rate) else "", 6),
            ("cache", _observed_percent("cache", row.get("cache_hit_percentage")), 2),
            ("context", _observed_percent("ctx", row.get("context_percentage")), 3),
            ("turn", turn_tools, 4),
            ("cost", _cost_text(row), 5),
        )
        if segment[1]
    ]
    running = _is_running(row)
    elapsed_value = row.get("elapsed_seconds")
    if running:
        elapsed_value = (elapsed_value if _finite(elapsed_value) else 0) + extra_seconds
    state_width = 5 if columns < 100 else 7
    tokens_width = 16 if grid.tokens else 0
    tail_width = state_width + 3 + 7 + tokens_width
    token_text = _token_count_text(row.get("tokens"))
    tail_tokens = (f" · {token_text:>6} tokens" if token_text else " " * tokens_width) if grid.tokens else ""
    tail_state = _pad(truncate(state_text, state_width), state_width)
    elapsed_cell = _pad("", 7) if _safe_text(raw_state) == "queued" else _pad(_elapsed(elapsed_value) or "0s", 7)
    scope = _pad(_kind_tag(row), grid.scope)
    prefix_width = cell_width(f"{scope}{task_id} ")
    budget = max(24, columns - 4)
    separator_width = cell_width(ROW_SEPARATOR)
    route_room = budget - prefix_width - tail_width - separator_width - 8 - 2
    route_full, route_compact = grid.route_full, grid.route_compact
    if route_compact > route_room + 4:
        route_full = route_compact = 0
    shed_prefix = route_full > route_room
    route_cap = route_compact if shed_prefix else route_full
    route_width = separator_width + route_cap if route_cap else 0
    route_label = _compact_route(route_text) if shed_prefix else route_text
    route_cell = f"{ROW_SEPARATOR}{_pad(route_label, route_cap)}" if route_cap else ""
    action_cap = max(10, min(48, math.floor(columns * 0.4)))
    action_width = max(4, min(action_cap, budget - prefix_width - route_width - tail_width - 2))
    fixed_width = prefix_width + action_width + route_width + tail_width
    while optional:
        metadata = ROW_SEPARATOR.join(text for _, text, _ in optional)
        if fixed_width + separator_width + cell_width(metadata) + 2 <= budget:
            break
        shed = 0
        for index in range(1, len(optional)):
            if optional[index][2] > optional[shed][2]:
                shed = index
        optional.pop(shed)
    spinner = SPINNER_FRAMES[(frame if running else 0) % len(SPINNER_FRAMES)]
    marker, marker_style, status_style = _row_marker(raw_state, board, spinner, theme)
    secondary = theme.muted
    segments = [Span(f"{ROW_SEPARATOR}{text}", _segment_style(kind, theme)) for kind, text, _ in optional]
    return _line(
        Span(f"{marker} ", marker_style),
        Span(scope, _bold(theme.muted)),
        Span(f"{_pad('MAIN', 8) if main else task_id} ", secondary),
        Span(_pad(_cut(row.get("action"), action_width), action_width), theme.text),
        Span(route_cell, _route_style(route_kind, theme)),
        Span("  "),
        Span(tail_state, status_style),
        Span(f" · {elapsed_cell}", secondary),
        Span(tail_tokens, theme.muted),
        *segments,
    )


DAG_INDENT = "  "
DAG_HEADER_ROWS = 1  # what the block keeps under the most pressure: its header
DAG_FEW_ROWS = 4  # header, root and two lanes: what it keeps while the plan still has items to give


def dag_style(role: str, theme: Theme, level: int = 0, levels: int = 1, depth: str = TRUECOLOR) -> Style:
    """The theme role for one piece of the delegation view (`delegation_view` names them), painted at `depth`.

    A tree's edge takes the step of the theme's gradient for its level, the
    top of the drawing violet and its bottom blue by default. A box's border
    and glyph take its node's state (`node`), and its title and status words
    the same hue lifted to a word's contrast (`node-title`, `node-word`;
    `node_style`); the connector between two frontiers is dim, and blue into a
    frontier with a node running. A title is bold; a field with no record dim.
    """
    kind, _, state = role.partition(":")
    if kind == "edge":
        steps = theme.dag_edges
        at = round(min(max(level, 0), levels - 1) / (levels - 1) * (len(steps) - 1)) if levels > 1 else 0
        style = steps[at] if steps else theme.dim
    elif kind in ("node", "node-word", "node-title"):
        style = node_style(state, theme, words=kind != "node")
        style = _bold(style) if kind == "node-title" else style
    elif kind == "connector":
        style = node_style("running", theme) if state == "running" else theme.dim
    elif kind in ("glyph", "status"):
        style = {
            "running": theme.running, "stuck": theme.warn, "done": theme.ok, "failed": theme.error,
            "interrupted": theme.warn, "root": theme.running,
        }.get(state, theme.muted)
    else:
        style = {
            "header": theme.label, "title": _bold(theme.text), "category": theme.label, "model": theme.hint,
            "unknown": theme.dim, "group": theme.hint, "more": theme.muted, "": theme.text,
            "frontier": theme.dim, "dependency": theme.text,
        }.get(kind, theme.muted)
    # A theme without colour (`theme.without_colour`) stays so at any depth asked for.
    return replace(style, depth=depth) if depth != style.depth and style.depth != NO_COLOR else style


def node_style(state: str, theme: Theme, words: bool = False) -> Style:
    """A box's colour by its node's state, from the theme's roles: selected (`/dag`'s highlight) the violet the
    edge gradient starts at, running the blue it ends at, handed out the step between them, failed and cancelled
    the error colour, stuck the warning colour, done the terminal's own foreground, waiting and unknown dim.

    Lines and glyphs are marks and reach 3:1 (`dag_edges`, `dim`). With
    `words`, the same hue reaches the 4.5:1 a word needs (`dag_words`), and
    waiting and unknown take `muted`, since words never go on `dim`.
    """
    steps = theme.dag_words if words else theme.dag_edges
    quiet = theme.muted if words else theme.dim
    if not steps:
        return theme.text if state == "done" else theme.running if state in ("selected", "running") else quiet
    return {
        "selected": steps[0], "running": steps[-1], "dispatched": steps[len(steps) // 2], "failed": theme.error,
        "interrupted": theme.error, "stuck": theme.warn, "done": theme.text,
    }.get(state, quiet)


@dataclass
class _DagCache:
    """Views already laid out for one graph object: a repaint (the spinner's every frame) reuses them."""

    graph: Mapping[str, Any] | None = None
    views: dict[tuple[int, int | None], Any] = field(default_factory=dict)


_dag_cache = _DagCache()


def graph_is_dag(payload: Any) -> bool:
    """Whether the payload's active delegation graph is a DAG run: a `depends_on` edge, or a dispatch from a lane
    (a layer under a layer), rather than one fan-out from main."""
    graph = _delegation_graph(payload) if isinstance(payload, Mapping) else None
    if graph is None:
        return False
    roots = {_safe_text(node.get("id")) for node in _rows(graph.get("nodes")) if node.get("kind") == "root"}
    return any(
        edge.get("kind") == "depends_on" or _safe_text(edge.get("from")) not in roots
        for edge in _rows(graph.get("edges"))
    )


def _dag_view(graph: Mapping[str, Any], columns: int, budget: int | None) -> Any:
    """The tree for this graph object at this size, laid out once; a new payload with the same structure reuses
    the renderer's own layout decision, so only its durations are drawn again.

    Always the tree: the panel is the agent view under the info line, whose
    cap (`layout.agent_view_cap`, 7 rows on most terminals) is under the 10
    rows that even one lane's box takes with its header and no sections. The
    boxes are `/dag`'s (`dag_page_lines`).
    """
    from ..plugin_bundle.omh.delegation_view import render_delegation_view

    if _dag_cache.graph is not graph:
        _dag_cache.graph, _dag_cache.views = graph, {}
    key = (columns, budget)
    if key not in _dag_cache.views:
        if len(_dag_cache.views) > 32:
            _dag_cache.views.clear()
        width = max(8, columns - len(DAG_INDENT))
        _dag_cache.views[key] = render_delegation_view(graph, width=width, max_lines=budget, layout="tree")
    return _dag_cache.views[key]


def dag_line(row: Sequence[Any], levels: int, theme: Theme, depth: str = TRUECOLOR) -> Line:
    """One row of a delegation view as styled spans: the same text at every depth, only its colours differ."""
    return _line(
        *(Span(segment.text, dag_style(segment.role, theme, segment.level, levels, depth)) for segment in row)
    )


def dag_page_lines(
    payload: Any, width: int, theme: Theme, depth: str = TRUECOLOR, focus: Any = None, aura: int | None = None,
) -> tuple[list[Line], Any] | None:
    """The delegation graph in this payload as `/dag` draws it: boxes with Dependencies and Node details and no
    height limit, at `focus` (a `delegation_view.Focus`); its lines and the view, whose `boxes` the pager moves
    through. None when the payload holds no active graph. `aura` is the phase a running node's box stands at in the
    dag-ulw aura (`_aura_box`); None (the aura does not move here) draws every box in its state's colour."""
    from ..plugin_bundle.omh.delegation_view import render_delegation_view

    graph = _delegation_graph(payload) if isinstance(payload, Mapping) else None
    if graph is None:
        return None
    view = render_delegation_view(graph, width=max(8, width), layout="box", focus=focus)
    lines = [dag_line(row, view.levels, theme, depth) for row in view.lines]
    if aura is not None and view.layout == "box":
        running = {str(node.get("id")) for node in _rows(graph.get("nodes")) if node.get("state") == "running"}
        tops: dict[int, list[tuple[str, int]]] = {}
        for node_id, top, bottom in view.boxes:
            tops.setdefault(top, []).append((node_id, bottom))
        for top, row in tops.items():
            # The top border of each box on this row, left to right, is the box's first cell and its width.
            borders, at = [], 0
            for segment in view.lines[top]:
                if segment.role.startswith("node"):
                    borders.append((at, cell_width(segment.text)))
                at += cell_width(segment.text)
            for (node_id, bottom), (left, size) in zip(row, borders):
                if node_id in running:
                    for line in range(top, bottom + 1):
                        lines[line] = _aura_box(view.lines[line], view.levels, theme, depth, left, size,
                                                line in (top, bottom), aura)
    topology = graph.get("dag_topology")
    if isinstance(topology, Mapping):  # a dag-ulw run: its critical path and bottlenecks close the page
        from .dag_block import topology_lines

        lines += [(), *topology_lines(topology, width, theme)]
    return lines, view


def _aura_box(
    row: Sequence[Any], levels: int, theme: Theme, depth: str, left: int, size: int, rule: bool, phase: int,
) -> Line:
    """One line of a running node's box in `/dag` with its border and title in the dag-ulw aura at `phase`: the
    gradient stepped across the box's `size` cells from `left`, the band moving through (`aura.aura_style`). A `rule`
    line (the box's top or bottom border) is border all through; on the others, the side borders and the title."""
    from .aura import aura_style

    spans: list[Span] = []
    at = 0
    for segment in row:
        style = dag_style(segment.role, theme, segment.level, levels, depth)
        for cluster in clusters(segment.text):  # one style a glyph, never one inside it
            offset = at - left
            inside = 0 <= offset < size and (rule or offset in (0, size - 1) or segment.role.startswith("node-title"))
            painted = aura_style(theme.aura, theme.aura_glint, offset, size, phase) if inside else style
            if spans and spans[-1].style == painted:
                spans[-1] = Span(spans[-1].text + cluster, painted)
            else:
                spans.append(Span(cluster, painted))
            at += cluster_width(cluster)
    return _line(*spans)


# A lane in one of these states has finished: `delegation_graph.SETTLED_STATES` (the bundle module the panel does
# not import at load).
SETTLED_NODE_STATES = frozenset({"done", "failed", "interrupted", "unknown"})


def dag_run_summary(graph: Mapping[str, Any]) -> str:
    """`DAG · export feature · done 5/6 · 1 failed` once every lane of `graph` has settled; "" while one has not.

    A finished run's delegation block is this one line, until the graph
    lingers out of the HUD (`delegation_graph.GRAPH_LINGER_SECONDS`) as the
    whole block did; the agent view under the composer draws nothing for it
    once its turn ends (`agent_view._run_gone`). The counts are the lanes'
    recorded states; lanes the reader left out
    (`hidden_nodes`) leave the run unread, so it stays a tree, and so does a
    dag-ulw run that is not over (`dag_open`: a node whose child went quiet
    is still out, though its lane reads settled). `/dag` still draws the
    whole graph.
    """
    lanes = [node for node in _rows(graph.get("nodes")) if node.get("kind") != "root"]
    if not lanes or _count(graph.get("hidden_nodes")) or graph.get("dag_open") or any(
        node.get("state") not in SETTLED_NODE_STATES for node in lanes
    ):
        return ""
    counts = {state: sum(1 for node in lanes if node.get("state") == state) for state in SETTLED_NODE_STATES}
    said = [f"done {counts['done']}/{len(lanes)}"]
    said += [f"{counts[state]} {state}" for state in ("failed", "interrupted", "unknown") if counts[state]]
    # A dag-ulw node accepted while its handoff could not be read where its child wrote it (`dag_run.settle`).
    unchecked = sum(1 for node in lanes if node.get("handoff_checked") is False)
    if unchecked:
        said.append(f"{unchecked} handoff not checked")
    return " · ".join(["DAG", _safe_text(graph.get("name")) or "delegation", *said])


def _dag_lines(graph: Mapping[str, Any], budget: int, columns: int, theme: Theme, depth: str) -> list[Line]:
    summary = dag_run_summary(graph)
    if summary:
        return [_line(Span(DAG_INDENT), Span(summary, dag_style("header", theme, depth=depth)))]
    view = _dag_view(graph, columns, budget)
    return [_line(Span(DAG_INDENT), *dag_line(row, view.levels, theme, depth)) for row in view.lines[:budget]]


def _agents_lines(
    payload: Mapping[str, Any],
    agents: _Agents,
    layout: _Layout,
    columns: int,
    now: float,
    extra_seconds: float,
    theme: Theme,
    motion: bool = True,
) -> list[Line]:
    lines = [_agents_header(payload, columns, theme, agents)]
    kept = _kept_rows(agents, layout.rows_shown)
    shown = [agents.rows[index] for index in kept]
    grid = _grid(shown)
    frame = _frame(now) if motion else 0
    for index in kept:
        row = agents.rows[index]
        lines.append(_activity_row(row, index < agents.main_count, grid, columns, frame, extra_seconds, theme))
    hidden = _hidden_rows(agents, layout.rows_shown)
    if shown and hidden:
        cut = [row for index, row in enumerate(agents.rows) if index not in kept]
        done = not agents.hidden and all(row.get("state") == "done" for row in cut)
        lines.append(_line(Span(f"  +{hidden} {'done' if done else 'more'}", theme.muted)))
    return lines


# The order activity rows are kept in when the block has no room for all: running first, finished last.
ROW_KEEP_RANK = {"running": 0, "queued": 1, "scheduled": 1, "blocked": 2, "failed": 2, "stale": 2, "review": 3}
DONE_ROW_RANK = 4


def _kept_rows(agents: _Agents, count: int) -> list[int]:
    """The indexes of the `count` rows to draw, in their own order: main rows first, then running ones, then those
    waiting or stuck, and done ones last."""
    def rank(index: int) -> int:
        if index < agents.main_count:
            return -1
        row = agents.rows[index]
        return 0 if _is_running(row) else ROW_KEEP_RANK.get(_safe_text(row.get("state")), DONE_ROW_RANK)

    return sorted(sorted(range(len(agents.rows)), key=rank)[: max(count, 0)])


# ── layout under a row budget ──────────────────────────────────────────────


@dataclass
class _Layout:
    plan_on: bool
    plan_start: int
    plan_end: int
    plan_collapsed: bool
    agents_on: bool
    rows_shown: int
    dag_on: bool = False
    dag_budget: int = 0


def _hidden_rows(agents: _Agents, rows_shown: int) -> int:
    return len(agents.rows) - rows_shown + agents.hidden


def _height(layout: _Layout, plan: _Plan | None, agents: _Agents | None) -> int:
    height = 0
    if plan is not None and layout.plan_on:
        height += 1
        if plan.status == "established" and not layout.plan_collapsed:
            height += _window_rows(plan, layout.plan_start, layout.plan_end)
    if layout.dag_on:
        height += layout.dag_budget
    if agents is not None and layout.agents_on:
        height += 1
        height += layout.rows_shown
        # `+N more` rides under at least one row; alone, the header's counts say it.
        if layout.rows_shown and _hidden_rows(agents, layout.rows_shown):
            height += 1
    return height


def _fit(plan: _Plan | None, agents: _Agents | None, dag_on: bool, natural: int, max_rows: int,
         folded: bool) -> _Layout:
    """The rows each block gets within `max_rows`, the least valuable shed first; `folded` starts the plan collapsed
    (the person folded it)."""
    start, end = _initial_window(plan) if plan is not None and plan.status == "established" else (0, 0)
    layout = _Layout(
        plan_on=plan is not None,
        plan_start=start,
        plan_end=end,
        plan_collapsed=folded,
        agents_on=agents is not None,
        rows_shown=agents.wanted if agents is not None else 0,
        dag_on=dag_on,
        dag_budget=natural,
    )
    while _height(layout, plan, agents) > max_rows and _shed(layout, plan, agents):
        pass
    return layout


def plan_room_collapsed(payload: Any, max_rows: int) -> bool:
    """Whether the plan drawn alone (as the app's slot draws it, with no agents or delegation tree) is its header
    alone in `max_rows` for want of rows, whatever the person's fold: there its fold key can change nothing."""
    if max_rows <= 0 or not isinstance(payload, Mapping) or payload.get("error"):
        return False
    plan = _plan_view(payload) if payload.get("privacy") == "metadata_only" else None
    if plan is None or plan.status != "established":
        return False
    return _fit(plan, None, False, 0, max_rows, False).plan_collapsed


def _shed(layout: _Layout, plan: _Plan | None, agents: _Agents | None) -> bool:
    """Take away the least valuable row; False when nothing is left to take.

    Agent rows go first, then the delegation tree shrinks to a few rows
    before the plan does. The plan header still goes last.
    """
    if agents is not None and layout.agents_on:
        if layout.rows_shown:
            layout.rows_shown -= 1
            return True
    if layout.dag_on and layout.dag_budget > DAG_FEW_ROWS:
        layout.dag_budget -= 1
        return True
    if plan is not None and layout.plan_on and plan.status == "established" and not layout.plan_collapsed:
        if layout.plan_end - layout.plan_start > 1:
            layout.plan_start, layout.plan_end = _shrink_window(plan, layout.plan_start, layout.plan_end)
        else:
            # Below one item with its header and folds there is no honest
            # checklist left; the header alone still carries done/total.
            layout.plan_collapsed = True
        return True
    if agents is not None and layout.agents_on:
        layout.agents_on = False
        return True
    if layout.dag_on and layout.dag_budget > DAG_HEADER_ROWS:
        layout.dag_budget -= 1
        return True
    if layout.dag_on:
        layout.dag_on = False
        return True
    if plan is not None and layout.plan_on:
        layout.plan_on = False
        return True
    return False


RUNNING_NODE_STATES = frozenset({"running", "stuck"})


def agent_view_keep(payload: Any, width: int, *, show_agents: bool = True, show_graph: bool = True) -> int:
    """The rows the agent view needs to draw every running agent of `payload`, for `layout.agent_view_cap`.

    The agents block's header, its main and running rows and a `+N` row for
    the rest; the delegation tree's rows at the smallest height that hides no
    running lane (its renderer hides done lanes first and running ones last).
    0 for a payload with no running agent, so the cap stays the usual one.
    """
    if not _valid(payload):
        return 0
    keep = 0
    agents = _agents_view(payload, show_graph) if show_agents else None
    if agents is not None:
        running = agents.main_count + sum(1 for row in agents.rows[agents.main_count:] if _is_running(row))
        if running:
            keep += 1 + running + int(len(agents.rows) + agents.hidden > running)
    dag = _delegation_graph(payload) if show_graph else None
    if dag is not None:
        lanes = [node for node in _rows(dag.get("nodes")) if node.get("kind") != "root"]
        idle = sum(1 for node in lanes if node.get("state") not in RUNNING_NODE_STATES)
        if idle < len(lanes):
            columns = max(20, width)
            low, high = 1, len(_dag_view(dag, columns, None).lines)
            while low < high:  # the smallest height whose tree hides no running lane
                middle = (low + high) // 2
                if _dag_view(dag, columns, middle).hidden_nodes <= idle:
                    high = middle
                else:
                    low = middle + 1
            keep += high
    return keep


def agent_view_count(payload: Any, *, show_agents: bool = True, show_graph: bool = True) -> int:
    """How many agents the agent view stands for: the agents block's rows (main's aside) and the ones the reader did
    not list, and the delegation graph's lanes. 0 without a valid payload."""
    if not _valid(payload):
        return 0
    agents = _agents_view(payload, show_graph) if show_agents else None
    count = len(agents.rows) - agents.main_count + agents.hidden if agents is not None else 0
    dag = _delegation_graph(payload) if show_graph else None
    if dag is not None:
        count += sum(1 for node in _rows(dag.get("nodes")) if node.get("kind") != "root")
    return count


def _notice(payload: Mapping[str, Any], theme: Theme) -> Line:
    return _line(Span(f"⚚ OMH HUD unavailable: {_safe_text(payload.get('error')) or 'reader error'}", theme.muted))


def panel_lines(
    payload: Any,
    width: int,
    max_rows: int,
    theme: Theme,
    now: float,
    *,
    received_at: float | None = None,
    show_agents: bool = True,
    show_plan: bool = True,
    show_graph: bool = True,
    agents_inset: int = 0,
    motion: bool = True,
    color_depth: str = TRUECOLOR,
    plan_folded: bool = False,
    fold_key: str = "",
) -> list[Line]:
    """The panel rows for one HUD payload: never more than `max_rows`, none wider than `width` cells.

    `now` is wall-clock seconds; it drives the spinner, the active item's
    colour wave, and the age of a finished parallel shot. `received_at` (the
    snapshot's) lets a running agent's elapsed figure tick between polls.
    Without `show_agents` the agents block is left out: the app passes that
    while its own roster shows the agents, so they are drawn once, from one
    source. Without `show_graph` the delegation block is left out. Without
    `show_plan` the plan block is left out: the app passes that for a
    finished plan it has retired, and for the agent view under the info line.
    `agents_inset` cells go before each row of the agents block, drawn that
    much narrower (the agent view's rows start under the info line's text,
    as the delegation tree's `DAG_INDENT` does). Without `motion` (reduced
    motion) the spinner holds its first frame and the plan does not wave.
    `color_depth` is the depth the delegation graph is painted at
    (`style.color_depth`). `plan_folded` draws the plan as its header alone
    (the person folded it), and `fold_key` names the key that folds and
    expands it on the header's right edge.
    """
    if max_rows <= 0 or width <= 0 or not isinstance(payload, Mapping):
        return []
    if payload.get("error"):
        return [truncate_line(_notice(payload, theme), width)]
    if payload.get("privacy") != "metadata_only":
        return []
    columns = max(20, width)
    plan = _plan_view(payload) if show_plan else None
    agents = _agents_view(payload, show_graph) if show_agents else None
    dag = _delegation_graph(payload) if show_graph else None
    # A finished run is its one summary line (`dag_run_summary`), else its tree at full height.
    natural = (1 if dag_run_summary(dag) else len(_dag_view(dag, columns, None).lines)) if dag is not None else 0
    dag_on = dag is not None and natural > 0
    layout = _fit(plan, agents, dag_on, natural, max_rows, plan_folded)
    # Expanding a plan the rows would collapse anyway shows nothing more: its header offers no `expand` there.
    expandable = plan_folded and not _fit(plan, agents, dag_on, natural, max_rows, False).plan_collapsed
    extra = max(0.0, now - received_at) if received_at is not None and _finite(now) and _finite(received_at) else 0.0
    lines: list[Line] = []
    if agents is not None and layout.agents_on:
        inset = (Span(" " * agents_inset),) if agents_inset > 0 else ()
        rows = _agents_lines(payload, agents, layout, max(20, columns - agents_inset), now, extra, theme, motion)
        lines += [_line(*inset, *row) for row in rows]
    if dag is not None and layout.dag_on and layout.dag_budget > 0:
        lines += _dag_lines(dag, layout.dag_budget, columns, theme, color_depth)
    if plan is not None and layout.plan_on:
        lines += _plan_lines(
            plan, layout.plan_start, layout.plan_end, layout.plan_collapsed, columns, now, theme, motion, fold_key,
            expandable,
        )
    return [truncate_line(line, width) for line in lines[:max_rows]]
