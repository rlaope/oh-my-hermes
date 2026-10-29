"""Hermes subagents as the OMH TUI holds them: a roster folded from gateway events, and the rows it draws.

Pure state and rendering. Nothing here reads a file, opens a socket, starts a
process or calls the gateway: the app hands `Roster.apply` each `subagent.*`
event it reads, hands `Roster.ingest_tail` a `subagent.tail` reply, and asks
for rows when it repaints.

What the gateway sends, measured against Hermes 6c61c3e27d. One function,
`tui_gateway/tool_progress.py::_progress_subagent`, builds every frame; the
frames it built for a scripted run are `tests/fixtures/tui_gateway/subagent_relay.jsonl`.

- Every frame carries `goal`, and from the child relay's identity
  `subagent_id`, `model`, `tool_count` and `child_session_id`, the child's
  own Hermes session. So any frame can introduce an agent, not only its first.
- `subagent.start` is the first frame of a child. `subagent.spawn_requested`
  is in the gateway's event contract, but the child relay has no entry for
  it and drops it; it is folded here (as a queued agent) in case it arrives.
- `subagent.tool` names the call in `tool_name` and carries `tool_preview`
  when the call has one; its `tool_count` already counts that call.
- `subagent.thinking` carries one line in `text`, or no `text` at all while
  the session hides reasoning.
- `subagent.progress` carries a summary naming the child's last five tools,
  after every fifth call (`🔀 [set 1 · 1/3] terminal, read_file, patch,
  terminal, terminal` from Hermes d923a5eb48's relay): calls the
  `subagent.tool` frames already reported, so it adds no log row. It is kept,
  without Hermes' `🔀 [set …]` tag, as the agent's progress line
  (`Agent.progress`). The calls after the last full batch of five are never
  sent as one, and with reasoning hidden a thinking frame has no `text`.
- `subagent.complete` carries `status` (`completed`, `interrupted`, or a
  failure: `failed`, `error`, `timeout`), `duration_seconds`, and `summary`,
  the child's reply cut to 500 characters, or its error. On Hermes' success
  path it also carries `output_tokens`, what the child wrote; the failure
  path (`finish_failed`) sends no token count.
- `subagent.text`, the child's streamed reply, is never sent on the parent's
  session: the gateway mirrors it onto the child's own session and skips the
  emit. It is not in the event contract and it is not folded here. An agent's
  reply reaches its log as the `summary` of its `subagent.complete`, or
  through `subagent.tail` while the child is live.
- No frame carries a role or a name. An agent's display name is the first
  words of its goal, without the `[dag:<run>/<node>]` marker a dag-ulw node's
  goal ends with (the node's label comes first) or an omh_team helper's. The
  dag marker binds the agent to its node (`Agent.dag_node`), as it binds the
  child in OMH's ledger (`delegation_ledger.dag_binding`).

What the dag tree under the composer shows of an agent (`dag_tree`) is kept
apart from its log, which a tail may replace: its latest call
(`Agent.last_call`), its latest thinking or reply line (`Agent.said`: a
thinking line, the first line of `subagent.complete`'s summary, or a tail's
last line), its latest progress line (`Agent.progress`), and which of the two
came last (`Agent.progress_newest`).

The fold. An agent is keyed by `subagent_id`; a frame without a usable one
changes nothing. The id is stored as it arrived and is never drawn: rows show
the goal and `Agent.name`. A frame that shows life (`start`, `tool`, `thinking`,
`progress`) makes the agent when it is new, so one whose `start` was missed,
or which `clear` dropped while it was still running, comes back the next time
it reports. `complete` never makes one: a verdict on an agent that was never
shown has no row to land on. A finished agent is frozen, so a repeated
`complete` or a late frame cannot change its verdict, its time or its log,
and a late `subagent.tail` can only fill a log that is still empty.

Tokens. No frame before `subagent.complete` counts tokens, but Hermes adds
each of the child's API calls to the `output_tokens` of the child's own row
in state.db as it goes (a per-call delta, applied by a background writer
as the call returns). So `token_sessions` names the child
sessions the HUD poller reads on its thread, and `ingest_tokens` takes what
it read: a running agent's count is the last read, a finished one's is
`subagent.complete`'s, or the last read when it carried none. A count of 0
(the column's default before the first call) is no count, and a row says
nothing about tokens until it has one.

Bounds. The roster holds `ROSTER_CAP` agents; one more pushes out a finished
agent, or the one seen longest ago when none has finished (every frame that
names an agent counts as seeing it, so a busy agent stays however early it
first reported), and `evicted` counts them until `clear`. A log holds `LOG_ROW_CAP` rows; `dropped` counts
the ones pushed out, and the log view says so on its first row. Every stored
string is cut to a fixed length when it is read.

Every gateway string is cleaned line by line by `markdown.clean_text` when it
is stored, as the transcript cleans its text, so widths are measured on what
will show. `screen.paint_line` strips every row again when it paints.
"""

from __future__ import annotations

from collections import deque
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from ..plugin_bundle.omh.hud_text import compact_count, elapsed_text
from . import gateway_contract as contract
from .markdown import clean_text, wrap_prefixed
from .panels import SPINNER_FRAMES
from .prompts import CHOICE_MARK
from .style import Line, Span
from .theme import Theme, kind_style
from .width import cell_width, clusters_as_written, truncate, truncate_line, wrap_line

QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
INTERRUPTED = "interrupted"
FAILED_STATUSES = frozenset({"failed", "error", "timeout"})  # Hermes' SUBAGENT_FAILURE_STATUSES
FINISHED_STATUSES = FAILED_STATUSES | {COMPLETED, INTERRUPTED}

MAIN_ID = ""  # the main agent's row: `apply` ignores an empty `subagent_id`, so no agent has it

ROSTER_CAP = 64
LOG_ROW_CAP = 400
ID_CHARS = 128
GOAL_CHARS = 500
LABEL_CHARS = 80  # a model or a tool name
ROW_CHARS = 600  # one log row, and a tool call's preview
SUMMARY_CHARS = 2000  # four times what Hermes sends
TAIL_CHARS = 32768  # twice the gateway's 16 KB tail, so a reply within its contract is never cut here
MAX_TOOL_COUNT = 999_999
MAX_SECONDS = 1_000_000_000
MAX_TOKEN_COUNT = 10**12
# A finished agent whose `subagent.complete` gave no count (Hermes' failure path) is read this much longer: the
# delta of the call that ended it lands just after the frame, and the poller reads at least every eight seconds.
TOKEN_SETTLE_SECONDS = 10.0

NAME_CELLS = 16
MIN_GOAL_CELLS = 12  # a list row keeps its right-hand figures only while the goal has this much room

MAIN_NAME = "main"
UNNAMED = "agent"
UNNAMED_TOOL = "tool"
MAIN_MARK = "●"
DONE_MARK = "○"
FAILED_MARK = "✗"
QUEUED_MARK = "◌"
INTERRUPTED_MARK = "▪"
OPEN_MARK = "↓ agents"  # what Down opens, after the count on the info line
WAITING = "waiting"  # a queued agent's figure: how long it has waited for a worker
# The order the agent view keeps rows in when it has no room for all: running first, done last.
KEEP_RANK = {RUNNING: 0, QUEUED: 1, **{status: 2 for status in FAILED_STATUSES}, INTERRUPTED: 3, COMPLETED: 4}
SELECTED_MARK = CHOICE_MARK  # the pointer every menu marks its row with; `▸` here is a folded row
UNSELECTED_MARK = "  "
COLUMN_GAP = "  "
FACT_SEPARATOR = " · "
CUT_MARK = "…"
TOOL_MARK = "● "  # dim: the log keeps no call's outcome; the name is in its family's hue, as in the transcript
THINKING_MARK = "▸ "
LOG_INDENT = "  "
NO_OUTPUT = "no output yet"
TOKENS_MARK = "↓"  # output tokens, as the turn's working row and its done line say them
ROW_TOKENS_WORD = " tokens"  # left off a list row's count, `↓1.3k`, where the model and the figures share the row
NO_BREAK_SPACE = "\N{NO-BREAK SPACE}"  # `wrap_line` breaks on spaces only
TAIL_CUT_NOTICE = "… earlier output not shown"

LOG_TEXT = "text"
LOG_THINKING = "thinking"
LOG_TOOL = "tool"
LOG_PROGRESS = "progress"  # only ever an `Agent.progress`: the log keeps no progress row
# Hermes' tag before a progress line's tool names (`tools/delegate_tool_progress.py`, `_flush`): `🔀 [set 2 · 3/9] `.
_PROGRESS_TAG = re.compile(r"\A(?:🔀\s*)?(?:\[[^\]]*\]\s*)?")


class LogRow(NamedTuple):
    kind: str
    text: str
    detail: str = ""  # a tool call's preview


class Hit(NamedTuple):
    """The cells a click on one row of the agent list lands in: `start` to `end` (exclusive), 0-based screen
    columns, and the id of that row's agent (`MAIN_ID` for main), as `App.clickable` keeps them."""

    start: int
    end: int
    subagent_id: str


def _new_log() -> deque[LogRow]:
    return deque(maxlen=LOG_ROW_CAP)


@dataclass
class Agent:
    subagent_id: str
    status: str
    started_at: float  # the app's clock at the first frame seen, or at `start` after a wait in the queue
    goal: str = ""
    model: str = ""
    tool_count: int = 0
    last_tool: str = ""
    finished_at: float | None = None
    duration: float | None = None  # Hermes' own `duration_seconds`, when the `subagent.complete` carried one
    child_session_id: str = ""  # the child's own Hermes session, whose state.db row counts its tokens as it runs
    output_tokens: int | None = None  # what it wrote: `subagent.complete`'s count, else the last state.db read
    tokens_final: bool = False  # `output_tokens` is `subagent.complete`'s, so no read replaces it
    log: deque[LogRow] = field(default_factory=_new_log)
    dropped: int = 0  # rows the cap pushed out of `log`
    tail_cut: bool = False  # `log` was seeded from a tail that had already lost its beginning
    seen: int = 0  # the roster's count of frames when one last named this agent; the lowest was seen longest ago
    log_gen: int = 0  # moves whenever `log`, `dropped` or `tail_cut` changes, so the wrapped log is redone only then
    dag_node: str = ""  # the dag node its goal's `[dag:<run>/<node>]` marker binds it to, by its graph id
    last_call: LogRow | None = None  # its latest tool call, as the log first wrote it
    said: LogRow | None = None  # its latest thinking or reply line
    progress: LogRow | None = None  # its latest progress line, the names of its last calls
    progress_newest: bool = False  # `progress` came after `said`

    @property
    def name(self) -> str:
        """The first words of the goal that fit `NAME_CELLS`; a first word longer than that is cut."""
        return _first_words(self.goal.split(), NAME_CELLS) or UNNAMED

    def elapsed(self, now: float) -> float:
        """Seconds it ran: Hermes' own figure once it finished with one, else measured from `started_at`."""
        if self.duration is not None:
            return self.duration
        end = now if self.finished_at is None else self.finished_at
        return max(0.0, end - self.started_at)


# ── reading a payload ─────────────────────────────────────────────────────


def _first_words(words: list[str], cells: int) -> str:
    """The first of `words` that fit `cells`; a first word longer than that is cut. Empty with no words.

    A `:` or `;` the last word ended on goes (`child alpha:` is `child
    alpha`): a name is set into sentences (`steering {name}: …`,
    `Interrupted {name}.`). A `.` stays, as `e.g.` and `v1.2.` keep theirs.
    """
    if not words:
        return ""
    name = words[0]
    for word in words[1:]:
        if cell_width(f"{name} {word}") > cells:
            break
        name = f"{name} {word}"
    return truncate(name.rstrip(":;") or name, cells)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else _whole_clusters(text, limit) + CUT_MARK


def _whole_clusters(text: str, limit: int) -> str:
    """`text` from its start to at most `limit` of its own characters, in whole clusters (`width.clusters_as_written`):
    the one `limit` falls in is left out, so a cut never splits a ZWJ family, a skin tone, a flag or a base from its
    marks, and never normalizes what it keeps."""
    return text if len(text) <= limit else "".join(clusters_as_written(text[: limit + 1])[:-1])


def _lines(text: str) -> list[str]:
    """The non-blank lines of `text`, each cleaned the way the transcript cleans a line."""
    cleaned = (clean_text(line).rstrip() for line in text.split("\n"))
    return [line for line in cleaned if line.strip()]


def _one_line(value: object, limit: int) -> str:
    """A payload string as one clean line: breaks and runs of spaces become one space, a cut ends in `…`.

    At most `limit` characters are read, so a huge field costs what a small one does.
    """
    raw = _text(value)
    line = " ".join(" ".join(_lines(_whole_clusters(raw, limit))).split())
    return line + CUT_MARK if len(raw) > limit else line


def _bounded(value: object, ceiling: int) -> bool:
    """True for a real number from 0 to `ceiling`; NaN, an infinity and a bool are not one."""
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= ceiling


def _identify(agent: Agent, payload: dict[str, Any]) -> None:
    """Take the identity fields a frame carries; one that is missing or mistyped leaves the agent's own."""
    from ..plugin_bundle.omh.delegation_graph import dag_node_id
    from ..plugin_bundle.omh.delegation_ledger import dag_binding, without_goal_marker  # the ledger's own markers

    # A dag node's child is named by its node's label: the `[dag:<run>/<node>]` marker is for OMH, not the strip.
    marked = _one_line(payload.get("goal"), GOAL_CHARS)
    goal = without_goal_marker(marked)
    if goal:
        agent.goal = goal
    bound = dag_binding(marked)
    if bound:
        agent.dag_node = dag_node_id(bound["run"], bound["node"])
    model = _one_line(payload.get("model"), LABEL_CHARS)
    if model:
        agent.model = model
    count = payload.get("tool_count")
    if isinstance(count, int) and _bounded(count, MAX_TOOL_COUNT):
        agent.tool_count = count
    session = payload.get("child_session_id")
    if isinstance(session, str) and session.strip() and len(session) <= ID_CHARS:
        agent.child_session_id = session


def _push(agent: Agent, kind: str, text: str, detail: str = "") -> None:
    if len(agent.log) == LOG_ROW_CAP:
        agent.dropped += 1
    agent.log.append(LogRow(kind, _cut(text, ROW_CHARS), detail))
    agent.log_gen += 1


# ── rendering ─────────────────────────────────────────────────────────────


def _mark(agent: Agent, theme: Theme, spinner_frame: int) -> Span:
    if agent.status == RUNNING:
        return Span(SPINNER_FRAMES[spinner_frame % len(SPINNER_FRAMES)], theme.running)
    if agent.status == QUEUED:
        return Span(QUEUED_MARK, theme.muted)
    if agent.status in FAILED_STATUSES:
        return Span(FAILED_MARK, theme.error)
    if agent.status == INTERRUPTED:
        return Span(INTERRUPTED_MARK, theme.muted)
    return Span(DONE_MARK, theme.muted)


# Where a structured goal's title ends: at its first field label or at the end of its first sentence. The labels are
# the node prompt's own (skills/dag-ulw, ulw-plan and ulw-work: TASK, DELIVERABLE, SCOPE, VERIFY, STOP WHEN), a closed
# list, so `README:` or `JSON:` in a title stays.
FIELD_LABELS = ("TASK", "DELIVERABLE", "SCOPE", "VERIFY", "STOP WHEN")
_FIELD_LABEL = re.compile(r"\s(?:" + "|".join(re.escape(label) for label in FIELD_LABELS) + r"):(?:\s|$)")
# An abbreviation's dot ends no sentence (`Fix e.g. the bug`); a dot inside a word (`v1.2`) has no space after it.
TITLE_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "cf.")
_SENTENCE_END = re.compile(
    "".join(rf"(?<!\b{re.escape(word)})" for word in TITLE_ABBREVIATIONS) + r"(?<=[.!?])\s", re.IGNORECASE
)


def short_title(goal: str) -> str:
    """An agent row's title: the ledger's title for the goal (`title_from_goal`: no leading `TASK:`, no dag or team
    marker), up to its first field label or the end of its first sentence. A dag lane's goal is its label and its
    marker, so it keeps the whole label."""
    from ..plugin_bundle.omh.delegation_ledger import dag_binding, title_from_goal  # the ledger's own rules

    title = title_from_goal(goal)
    if dag_binding(goal):
        return title
    title = _FIELD_LABEL.split(title, maxsplit=1)[0]
    return _SENTENCE_END.split(title, maxsplit=1)[0].rstrip(" .")


def _tools_text(count: int) -> str:
    return f"{count} tool{'' if count == 1 else 's'}"


def _tokens_text(count: int | None) -> str:
    """`↓1.2k tokens`, what an agent wrote, as the turn's working row says it; "" until there is a count."""
    return f"{TOKENS_MARK}{compact_count(count)} tokens" if count else ""


def _collapsed_row(cut: list[Agent], theme: Theme) -> Line:
    """The agent view's last row, for the agents it has no room for: `○ 3 done`, else `+4 more · 1 waiting · 3 done`
    (running, waiting, failed and done ones counted, in that order)."""
    if all(agent.status in (COMPLETED, INTERRUPTED) for agent in cut):
        return (Span(UNSELECTED_MARK), Span(DONE_MARK, theme.muted), Span(f" {len(cut)} done", theme.muted))
    counts = [
        (sum(1 for agent in cut if agent.status == RUNNING), "running"),
        (sum(1 for agent in cut if agent.status == QUEUED), WAITING),
        (sum(1 for agent in cut if agent.status in FAILED_STATUSES), "failed"),
        (sum(1 for agent in cut if agent.status in (COMPLETED, INTERRUPTED)), "done"),
    ]
    said = "".join(f"{FACT_SEPARATOR}{count} {word}" for count, word in counts if count)
    return (Span(UNSELECTED_MARK), Span(f"+{len(cut)} more{said}", theme.muted))


def _dropped_text(agent: Agent) -> str:
    """The log view's first row when rows are missing; a cut tail hides how many, so it gives no number."""
    if agent.tail_cut:
        return TAIL_CUT_NOTICE
    if agent.dropped:
        return f"… {agent.dropped} earlier row{'' if agent.dropped == 1 else 's'} dropped"
    return ""


def _log_row(row: LogRow, width: int, theme: Theme) -> list[Line]:
    rest: Line = (Span(LOG_INDENT),)
    if row.kind == LOG_TOOL:
        preview = f"{COLUMN_GAP}{row.detail}" if row.detail else ""
        spans = (Span(row.text, kind_style(row.text, theme)), Span(preview, theme.muted))
        return wrap_prefixed(spans, (Span(TOOL_MARK, theme.dim),), rest, width)
    if row.kind == LOG_THINKING:
        return wrap_prefixed((Span(row.text, theme.thinking),), (Span(THINKING_MARK, theme.muted),), rest, width)
    return wrap_line((Span(row.text, theme.text),), width)


# ── the roster ────────────────────────────────────────────────────────────


class Roster:
    """The subagents the TUI is showing, in the order they first reported."""

    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}
        self.evicted = 0  # agents the cap pushed out since the last `clear`
        self.kept: frozenset[str] = frozenset()  # the agents the last `clear` kept for an open dag run
        self._frames = 0  # frames that named a held agent, for `Agent.seen`
        # Each agent's log rows as `log_lines` last wrapped them, with the agent, log generation, width and theme
        # they were wrapped for: a log view repaints every tick, and its log changes far less often.
        self._wrapped: dict[str, tuple[Agent, int, int, Theme, list[Line]]] = {}
        self._handlers: dict[str, Callable[[str, dict[str, Any], float], None]] = {
            contract.SUBAGENT_SPAWN_REQUESTED: self._on_spawn_requested,
            contract.SUBAGENT_START: self._on_alive,
            contract.SUBAGENT_PROGRESS: self._on_progress,
            contract.SUBAGENT_THINKING: self._on_thinking,
            contract.SUBAGENT_TOOL: self._on_tool,
            contract.SUBAGENT_COMPLETE: self._on_complete,
        }

    # ── input ──

    def apply(self, event_type: str, payload: object, now: float) -> None:
        """Fold one gateway event; `now` is the app's clock.

        An event type that is not one of the six above, a payload that is not
        an object, and a `subagent_id` that is missing, blank (the gateway
        contract refuses a call naming it), over-long or not a string each
        change nothing. Nothing raises.
        """
        handler = self._handlers.get(event_type) if isinstance(event_type, str) else None
        if handler is None or not isinstance(payload, dict):
            return
        subagent_id = payload.get("subagent_id")
        if not isinstance(subagent_id, str) or not subagent_id.strip() or len(subagent_id) > ID_CHARS:
            return
        handler(subagent_id, payload, now)
        agent = self.agents.get(subagent_id)
        if agent is not None:
            self._frames += 1
            agent.seen = self._frames

    def token_sessions(self, now: float) -> tuple[str, ...]:
        """The child sessions whose state.db rows the HUD poller reads output tokens from, for `ingest_tokens`.

        Every agent with a child session whose count `subagent.complete` has
        not given: while it runs or waits, and for `TOKEN_SETTLE_SECONDS`
        after it finished without one. `now` is the app's clock.
        """
        return tuple(
            agent.child_session_id
            for agent in self.agents.values()
            if agent.child_session_id
            and not agent.tokens_final
            and (agent.finished_at is None or now - agent.finished_at <= TOKEN_SETTLE_SECONDS)
        )

    def ingest_tokens(self, counts: Mapping[str, object]) -> None:
        """Take each agent's output tokens from a state.db read, child session id to count.

        A count `subagent.complete` gave is kept. A missing, mistyped or
        out-of-range count, and 0 (no call made yet), change nothing.
        """
        for agent in self.agents.values():
            count = counts.get(agent.child_session_id) if agent.child_session_id else None
            if agent.tokens_final or not isinstance(count, int) or not _bounded(count, MAX_TOKEN_COUNT) or not count:
                continue
            agent.output_tokens = count

    def lose_unfinished(self, now: float) -> None:
        """Mark every agent that has not finished interrupted at `now`: the gateway that ran it is gone (a respawn)."""
        for agent in self.agents.values():
            if agent.status not in FINISHED_STATUSES:
                agent.status, agent.finished_at = INTERRUPTED, now

    def clear(self, keep: frozenset[str] = frozenset()) -> None:
        """Drop every agent but those bound to a dag node in `keep`: the app calls this when a new turn starts, keeping
        the lanes of the dag run still open (they outlive the turn that sent them), and when it leaves a session,
        keeping none. The agents kept are noted in `kept` until `drop_kept` lets them go."""
        for key in [key for key, agent in self.agents.items() if not (agent.dag_node and agent.dag_node in keep)]:
            del self.agents[key]
            self._wrapped.pop(key, None)
        self.kept = frozenset(self.agents)
        self.evicted = 0

    def drop_kept(self, runs: frozenset[str]) -> frozenset[str]:
        """Drop the agents `clear` kept whose dag node belongs to one of `runs` (`d:<run>`, the runs a payload shows
        over), a node that left the drawing since (a superseded repair) included; the ids dropped. An agent that
        arrived in this turn is never one of them."""
        return self._drop(frozenset(key for key in self.kept
                                    if key in self.agents and self.agents[key].dag_node.rpartition(":")[0] in runs))

    def drop_runs(self, runs: frozenset[str]) -> frozenset[str]:
        """Drop every agent whose dag node belongs to one of `runs` (`d:<run>`): a run that is over, which the view no
        longer draws (`AgentViewMixin._retire_finished_run`); the ids dropped."""
        return self._drop(frozenset(key for key, agent in self.agents.items()
                                    if agent.dag_node and agent.dag_node.rpartition(":")[0] in runs))

    def _drop(self, dropped: frozenset[str]) -> frozenset[str]:
        for key in dropped:
            del self.agents[key]
            self._wrapped.pop(key, None)
        self.kept -= dropped
        return dropped

    def ingest_tail(self, subagent_id: str, text: str, truncated: bool = False) -> None:
        """Replace an agent's log with the `text` of a `subagent.tail` reply; `truncated` is the reply's own flag.

        A tail the gateway cut opens in the middle of a line, so that line is
        dropped and the log view says earlier output is missing. A tail with
        no line in it, and an id the roster does not hold, change nothing. A
        finished agent is frozen: a tail can only seed its log while the log
        is empty, never replace the reply its `subagent.complete` put there.
        """
        agent = self.agents.get(subagent_id)
        if agent is None or not isinstance(text, str) or (agent.status in FINISHED_STATUSES and agent.log):
            return
        cut = truncated is True or len(text) > TAIL_CHARS
        tail = text[-TAIL_CHARS:]
        if cut:
            tail = tail.partition("\n")[2]
        rows = _lines(tail)
        if not rows:
            return
        agent.log = deque((LogRow(LOG_TEXT, _cut(row, ROW_CHARS)) for row in rows), maxlen=LOG_ROW_CAP)
        agent.dropped = max(0, len(rows) - LOG_ROW_CAP)
        agent.tail_cut = cut
        agent.log_gen += 1
        agent.said, agent.progress_newest = agent.log[-1], False

    def _make_room(self) -> None:
        """Keep the roster under its cap: a finished agent leaves first, else the one seen longest ago."""
        if len(self.agents) < ROSTER_CAP:
            return
        finished = next((key for key, agent in self.agents.items() if agent.status in FINISHED_STATUSES), None)
        evicted = finished if finished is not None else min(self.agents, key=lambda key: self.agents[key].seen)
        del self.agents[evicted]
        self._wrapped.pop(evicted, None)
        self.evicted += 1

    def _live(self, subagent_id: str, payload: dict[str, Any], now: float, status: str) -> Agent | None:
        """The agent a sign of life belongs to, made when it is new; None once it has finished."""
        agent = self.agents.get(subagent_id)
        if agent is None:
            self._make_room()
            agent = self.agents[subagent_id] = Agent(subagent_id, status, now)
        elif agent.status in FINISHED_STATUSES:
            return None
        elif agent.status == QUEUED and status == RUNNING:
            agent.status, agent.started_at = RUNNING, now  # the wait for a worker is not run time
        _identify(agent, payload)
        return agent

    def _on_spawn_requested(self, subagent_id: str, payload: dict[str, Any], now: float) -> None:
        self._live(subagent_id, payload, now, QUEUED)

    def _on_alive(self, subagent_id: str, payload: dict[str, Any], now: float) -> None:
        self._live(subagent_id, payload, now, RUNNING)

    def _on_thinking(self, subagent_id: str, payload: dict[str, Any], now: float) -> None:
        agent = self._live(subagent_id, payload, now, RUNNING)
        text = _one_line(payload.get("text"), ROW_CHARS)
        if agent is not None and text:
            _push(agent, LOG_THINKING, text)
            agent.said, agent.progress_newest = agent.log[-1], False

    def _on_progress(self, subagent_id: str, payload: dict[str, Any], now: float) -> None:
        agent = self._live(subagent_id, payload, now, RUNNING)
        text = _PROGRESS_TAG.sub("", _one_line(payload.get("text"), ROW_CHARS), count=1)
        if agent is not None and text:
            agent.progress, agent.progress_newest = LogRow(LOG_PROGRESS, text), True

    def _on_tool(self, subagent_id: str, payload: dict[str, Any], now: float) -> None:
        agent = self._live(subagent_id, payload, now, RUNNING)
        if agent is None:
            return
        agent.last_tool = _one_line(payload.get("tool_name"), LABEL_CHARS) or UNNAMED_TOOL
        preview = _one_line(payload.get("tool_preview") or payload.get("text"), ROW_CHARS)
        _push(agent, LOG_TOOL, agent.last_tool, preview)
        agent.last_call = agent.log[-1]

    def _on_complete(self, subagent_id: str, payload: dict[str, Any], now: float) -> None:
        agent = self.agents.get(subagent_id)
        if agent is None or agent.status in FINISHED_STATUSES:
            return
        _identify(agent, payload)
        status = _text(payload.get("status")).lower()
        agent.status = status if status in FINISHED_STATUSES else COMPLETED
        agent.finished_at = now
        duration = payload.get("duration_seconds")
        if _bounded(duration, MAX_SECONDS):
            agent.duration = float(duration)
        tokens = payload.get("output_tokens")
        if isinstance(tokens, int) and _bounded(tokens, MAX_TOKEN_COUNT):
            agent.output_tokens, agent.tokens_final = tokens, True
        summary = _lines(_text(payload.get("summary") or payload.get("text"))[:SUMMARY_CHARS])
        for line in summary:
            _push(agent, LOG_TEXT, line)
        if summary:  # its reply's first line, or its error
            agent.said, agent.progress_newest = LogRow(LOG_TEXT, _cut(summary[0], ROW_CHARS)), False

    # ── output ──

    def ids(self) -> tuple[str, ...]:
        """`MAIN_ID`, then every agent in roster order: the rows of the list, top to bottom."""
        return (MAIN_ID, *self.agents)

    def running_count(self) -> int:
        """How many agents are still running."""
        return sum(1 for agent in self.agents.values() if agent.status == RUNNING)

    def count_text(self) -> str:
        """`2 agents`, `1 agent`, or `64+ agents` once the cap pushed some out; "" with no agent."""
        count = len(self.agents)
        if not count:
            return ""
        return f"{count}{'+' if self.evicted else ''} agent{'' if count == 1 else 's'}"

    def view_lines(self, width: int, theme: Theme, spinner_frame: int, max_rows: int, now: float) -> list[Line]:
        """The agent view under the info line while no key is the list's: the list's own rows, none highlighted.

        `● main`, then each agent in roster order, as `list_lines` draws them,
        so Down highlights a row without moving one. More agents than
        `max_rows` holds collapse into one last row: running agents are kept
        first, then those waiting for a worker, then failed, interrupted and
        done ones, and the last row counts the rest, `○ 3 done` when every one
        of them finished, else `+4 more · 1 waiting · 3 done`. The rows kept
        stay in roster order. In two rows or fewer `● main` gives its row up
        first, so a running agent is still named. With no agent there is no
        view.
        """
        if not self.agents or max_rows <= 0:
            return []
        ids = self.ids()
        if len(ids) <= max_rows:
            return [self._list_row(row_id, False, width, theme, spinner_frame, now) for row_id in ids]
        main = [MAIN_ID] if max_rows > 2 else []
        room = max(max_rows - 1 - len(main), 0)  # main, when it keeps its row, and the last row
        ranked = sorted(self.agents, key=lambda key: KEEP_RANK.get(self.agents[key].status, len(KEEP_RANK)))
        kept = set(ranked[:room])
        shown = [*main, *(key for key in self.agents if key in kept)]
        rows = [self._list_row(row_id, False, width, theme, spinner_frame, now) for row_id in shown]
        cut = [agent for key, agent in self.agents.items() if key not in kept]
        return [*rows, truncate_line(_collapsed_row(cut, theme), width)]

    def list_lines(
        self, width: int, theme: Theme, selected: str, spinner_frame: int, max_rows: int, now: float
    ) -> tuple[list[Line], tuple[str, ...]]:
        """One row for main and one per agent, and the id each row is for (`MAIN_ID` for main).

        A row is its selection marker, status glyph and title (`short_title`
        of its goal, muted once the agent finished), with `model · elapsed ·
        N tools · ↓N` at the right edge (the model once a frame named it, the
        tokens once there is a count; `waiting <elapsed>` for an agent still
        waiting for a worker); the `selected` row is one `menu_current` bar
        across `width`. More rows than `max_rows` scroll just far enough to
        keep the selected one on screen. Where the title would be left less
        than `MIN_GOAL_CELLS`, the token count goes first, then the tool
        count, then, with the time alone left beside it, the model, and then
        the figures go as before: the token count, the tool count, the time,
        each whole (a waiting agent keeps `waiting` on its clock). With no
        agent there is no list.
        """
        if not self.agents or max_rows <= 0:
            return [], ()
        ids = self.ids()
        index = ids.index(selected) if selected in ids else 0
        start = min(max(index - max_rows + 1, 0), max(len(ids) - max_rows, 0))
        shown = ids[start : start + max_rows]
        rows = [self._list_row(row_id, row_id == selected, width, theme, spinner_frame, now) for row_id in shown]
        return rows, shown

    def _list_row(
        self, row_id: str, current: bool, width: int, theme: Theme, spinner_frame: int, now: float
    ) -> Line:
        agent = self.agents.get(row_id)
        if agent is None:
            mark, label, figures = Span(MAIN_MARK, theme.running), MAIN_NAME, [""]
        else:
            elapsed = elapsed_text(agent.elapsed(now))
            mark, label = _mark(agent, theme, spinner_frame), short_title(agent.goal) or UNNAMED
            if agent.status == QUEUED:  # its clock is the wait: a row that never changes reads as a dead one
                figures = [f"{WAITING} {elapsed}", elapsed, ""]
            else:
                tools = f"{elapsed}{FACT_SEPARATOR}{_tools_text(agent.tool_count)}"
                tokens = _tokens_text(agent.output_tokens).removesuffix(ROW_TOKENS_WORD)
                figures = [*([f"{tools}{FACT_SEPARATOR}{tokens}"] if tokens else []), tools, elapsed, ""]
            if agent.model:  # the model leads and stays longest: all of it, no tokens, model and time, model alone
                led = figures[:1] if agent.status == QUEUED else figures[:-1]  # a wait keeps its word: `waiting 35s`
                figures = [*(f"{agent.model}{FACT_SEPARATOR}{figure}" for figure in led), agent.model, ""]
        lead = SELECTED_MARK if current else UNSELECTED_MARK
        fixed = cell_width(f"{lead}{mark.text} ")
        for figure in figures:  # ends on "", which always stays
            room = width - fixed - (cell_width(f"{COLUMN_GAP}{figure}") if figure else 0)
            if room >= MIN_GOAL_CELLS:
                break
        label = truncate(label, room)
        pad = " " * (room - cell_width(label))
        right = f"{pad}{COLUMN_GAP}{figure}" if figure else ""
        if current:
            return truncate_line((Span(f"{lead}{mark.text} {label}{right or pad}", theme.menu_current),), width)
        # A finished agent's goal is muted, as Claude Code dims an idle one: what still runs reads first.
        finished = agent is not None and agent.status in FINISHED_STATUSES
        return truncate_line(
            (Span(lead), mark, Span(f" {label}", theme.muted if finished else theme.text), Span(right, theme.muted)),
            width,
        )

    def log_lines(self, subagent_id: str, width: int, theme: Theme, now: float) -> list[Line]:
        """An agent's log view: its goal, `status · elapsed · N tools · ↓N tokens · model`, a blank row, its log.

        Everything is wrapped to `width`. A log that lost rows opens by saying
        so; an empty one says `no output yet`. An id the roster does not hold
        (`MAIN_ID` included) has no rows. The rows under the header are
        wrapped again only when the log, the width or the theme changed since
        the last call; the header, whose elapsed time moves, every time.
        """
        agent = self.agents.get(subagent_id)
        if agent is None:
            return []
        # A no-break space holds the count to its unit, so a wrap never leaves `tokens` alone on the next row.
        facts = [
            elapsed_text(agent.elapsed(now)), _tools_text(agent.tool_count),
            _tokens_text(agent.output_tokens).replace(" ", NO_BREAK_SPACE), agent.model,
        ]
        state = _mark(agent, theme, 0).style  # the agent's own state: running blue, failed red, else grey
        status = Span(agent.status, state)
        rest = Span("".join(f"{FACT_SEPARATOR}{fact}" for fact in facts if fact), theme.muted)
        header: list[Line] = [
            *wrap_line((Span(agent.goal or UNNAMED, state),), width),
            *wrap_line((status, rest), width),
            (),
        ]
        return header + self._wrapped_log(agent, width, theme)

    def _wrapped_log(self, agent: Agent, width: int, theme: Theme) -> list[Line]:
        """The rows under the log view's header, from `_wrapped` while nothing they depend on has changed."""
        held = self._wrapped.get(agent.subagent_id)
        if held is not None and held[0] is agent and held[1:3] == (agent.log_gen, width) and held[3] is theme:
            return held[4]
        rows: list[Line] = []
        notice = _dropped_text(agent)
        if notice:
            rows.append(truncate_line((Span(notice, theme.muted),), width))
        if not agent.log:
            rows.append(truncate_line((Span(NO_OUTPUT, theme.muted),), width))
        for row in agent.log:
            rows.extend(_log_row(row, width, theme))
        self._wrapped[agent.subagent_id] = (agent, agent.log_gen, width, theme, rows)
        return rows
