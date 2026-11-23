"""The OMH TUI's subagent views over `subagents.Roster`: the agent view, the agent list, one agent's log, mixed into `App`.

Subagents: every `subagent.*` event of the live session is folded into one
`subagents.Roster`, which a new session empties and a new turn empties of
all but the open dag run's lanes. The agent view
stands under the info line, always expanded, while there are agents (the
owner's call of 2026-10-21, after Claude Code's agent list): `● main` and one
row per agent, or the dag run's folding tree (`dag_tree`) while the
conversation's delegation graph is a DAG run, or, with no roster, the HUD's
agents block (`panels`). The
info line counts them (`3 agents · ↓ agents`). Down on an empty composer gives
the keys to the view's rows, which become a list the person picks from as
from a picker: the composer's rows are drawn blank while it is open (so
nothing moves), and the info line says its keys. Every key goes to the list
then; a key it does not bind does nothing. Enter or a click shows that
agent's session on the main screen (`subagent_session`, `_open_agent`): what
the person sends there goes to it, Esc or the list's `main` row goes back, and
where Hermes refuses the read the agent's log opens in the pager instead. In a
dag run Down gives the keys to the tree
instead (`_tree_key`): its rows fold and unfold, and Enter, `x` and `s` act
on the highlighted node's child as the list's keys do. The log is
read-only: `subagent.tail` is asked for the open agent while it runs, at most
every `TAIL_POLL_SECONDS`, and no more once `TAIL_MISSES_BEFORE_STOP` answers
in a row had no tail, until that agent sends a frame; nothing is sent to a
subagent but what the person types (`x`, `s`, a line in its session view). On the main screen the OMH TUI takes the mouse wherever the row a
report lands on is certain (the owner's decision of 2026-11-11, back from the
one of 2026-11-06): a drag selects and copies without the rail, and the wheel
up hands the mouse to the terminal until the next key (`App._screen_mouse`). With `OMH_TUI_MOUSE=0`
reports are on only while the agent list (or the dag tree) has the keys, and
the wheel and a drag are the terminal's. A pager, an agent's log among them,
takes them for its own wheel and drag (`pager`). A plain left click on a list
row opens that agent's log, or on the list's main row leaves the list; on a
tree row it takes the highlight, and on a node's row opens its child's log;
any other report goes to the main screen's selection where it takes the
mouse, and does nothing where it does not. Reports the terminal sent before it acted on an off
arrive after it, so `_set_mouse` notes when reporting went off and the
decoder is told: a report that starts arriving while reporting is on, or
within `keys.MOUSE_REPORT_SECONDS` after the off, types nothing if it
arrives whole within 0.8 s of its first byte, split across reads or not.
When the pause right after its first byte outlasts
`keys.REPORTING_ESCAPE_SECONDS`, that ESC is Esc, and the rest is dropped
only if it arrives within `keys.MOUSE_REPORT_SECONDS` after that. One that
starts later and is split right after its `ESC` or `ESC[` is read as keys
(`keys`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import gateway_contract as contract
from .background import tool_call
from .keys import BUTTON_LEFT, CHAR, DOWN, ENTER, ESCAPE, LEFT, RIGHT, UP, Key, Mouse, Paste, list_nav_step
from .layout import Budget, agent_view_cap, is_tiny, max_height
from ..plugin_bundle.omh.hud_text import compact_count, elapsed_text
from .dag_tree import TreeState, bound_node, run_key, tree_lines
from .panels import (
    RUNNING_NODE_STATES, agent_view_count, agent_view_keep, dag_run_summary, graph_is_dag, panel_lines,
)
from .composer import Composer
from .style import Line, Span, Style
from . import subagent_session as view_state
from .subagent_session import (
    CONTINUE_REFUSED, DEST_MAIN, DEST_STEER, DEST_VIEW, FROM_MAIN, READ_GAVE_UP, REFUSED_FOR_STEER, REFUSED_WHILE_VIEWING,
    TELL_CHILD_LEFT, VIEW_TEXT_KEPT, VIEW_REFUSED_ARMED, VIEW_TEXT_DROPPED, SEND_CONTINUE, SEND_STEER, SEND_UNSUPPORTED, STILL_RUNNING,
    UNSUPPORTED_LINE, WIRE_POLL, WIRE_WATCH, SubagentView, mark_rows,
)
from .subagents import (
    COMPLETED, ENDED, FINISHED_STATUSES, INTERRUPTED, MAIN_ID, OPEN_MARK, RUNNING, TOKENS_MARK, Agent, Hit, short_title,
)
from .width import cell_width
from .transcript import (
    AGENT_CANCELLED, AGENT_FAILED, AGENT_FINISHED, AGENT_INTERRUPTED, NOTICE_WARN, STEER_QUEUED, STEER_REFUSED,
    AgentDoneBlock, NoticeBlock, SteerBlock, Transcript, as_text,
)

# The list Down opens (the agent view's rows, `layout.agent_view_cap` of them; a longer roster scrolls), and one
# agent's log in the pager.
CHIP_SEPARATOR = " · "  # between the agent count and what Down opens, on the info line
# Its keys, on the info line while it is open, longest first: each keeps the two action keys and the way back.
AGENT_LIST_HINT = "↑↓ select · ⏎ view · x stop · s steer · esc back"
AGENT_LIST_HINTS = (
    AGENT_LIST_HINT, "⏎ view · x stop · s steer · esc back", "⏎ view · x stop · esc back", "x stop · esc back",
)
# The dag tree's keys, the same way: each keeps the fold keys, the two action keys and the way back while it fits.
TREE_HINT = "↑↓ select · ←/→ or space fold · ⏎ view · x interrupt · s steer · esc back"
TREE_HINTS = (
    TREE_HINT, "←/→ fold · ⏎ view · x interrupt · s steer · esc back", "←/→ fold · x interrupt · s steer · esc back",
    "←/→ fold · esc back",
)
# The fewest rows a tree takes the keys in: its highlight between a count above and one below. Under it Down opens the
# agent list in the view's rows, as it did before the tree.
MIN_TREE_ROWS = 3
# The most rows a dag run's tree takes under the composer, and never more than a third of the screen
# (`layout.agent_view_cap`). The owner, 2026-11-04: 17 rows was too big and 8 too little and too cramped; 16 holds a
# small run whole with its blank rows (the 6-node run in 14 at 150x42), and on a taller screen the tree stops growing
# there, `/dag` drawing the whole graph.
TREE_ROWS = 16
# What the info line says once `x` asked, longest first.
INTERRUPT_CONFIRM = "x again interrupts {name} · any other key cancels"
INTERRUPT_CONFIRMS = (INTERRUPT_CONFIRM, "x again interrupts {name}", "x again interrupts")
LEAVE_KEYS = frozenset({"q"})  # with Esc, Left and Ctrl+C, the plain keys that leave the list
# What the info line says while `s` has picked an agent, longest first: a narrow line takes the first that fits.
STEER_SAY = (
    "↪ steering {name}: enter sends it to that agent · esc cancels",
    "↪ steering {name} · enter sends · esc cancels",
    "↪ steering {name} · esc cancels",
    "↪ steer · esc cancels",
)
AGENT_FINISHED_NOTICE = "{name} has finished; there is nothing to {action}."
# How a finished agent's briefing names its end, by its status; every failure status is a failure.
AGENT_OUTCOMES = {COMPLETED: AGENT_FINISHED, INTERRUPTED: AGENT_INTERRUPTED, ENDED: AGENT_CANCELLED}
# An agent steer that settled after its session was left, as the main steer's notices say it, naming the agent and
# the session it was for.
AGENT_STEER_LEFT_NOTICE = (
    "Hermes answered the steer for {name} after you left session {session}. "
    "Its text is back in the composer and was not sent to this one."
)
AGENT_STEER_LEFT_UNANSWERED_NOTICE = (
    "Hermes did not answer the steer for {name} in {seconds:g} s, and you had left session {session}. "
    "Its text is back in the composer and was not sent to this one."
)
AGENT_INTERRUPTED_NOTICE = "Interrupted {name}."
AGENT_ALREADY_DONE_NOTICE = "{name} had already finished."
AGENT_INTERRUPT_REFUSED_NOTICE = "Hermes did not interrupt {name}: {reason}."
# A refused agent steer's row says what became of its text (`transcript.SteerBlock`'s outcome), with Hermes' reason
# when it gave one. Hermes refuses one for an agent that has finished or has no tool call left to take it at.
AGENT_STEER_REFUSED = "back in the composer — Hermes did not take the steer"
AGENT_STEER_REFUSED_BECAUSE = AGENT_STEER_REFUSED + " ({reason})"
AGENT_LOG_KEYS = "←/→ agents"
TAIL_POLL_SECONDS = 2.0
# What a subagent view's open answer needs from 4009 on a continue: Hermes refuses a turn on a running session so.
SESSION_BUSY = 4009
# Hermes answers `available: false` while an agent's log is not there yet, as it starts. Five answers in a row
# like that (ten seconds at the pace above) stop the calls for that agent, so one whose `subagent.complete`
# never comes is not asked forever; a new frame for it asks again.
TAIL_MISSES_BEFORE_STOP = 5
# A call with no answer this long no longer holds the next one back; its answer, if it still comes, is dropped.
TAIL_ANSWER_SECONDS = 10.0


def _changed_at(graph: Mapping[str, Any]) -> float:
    """When `graph` last moved (`delegation_graph`'s `changed_at`: its last start, stop or run-record write); 0 when
    the graph does not say."""
    changed = graph.get("changed_at")
    return float(changed) if isinstance(changed, int | float) and not isinstance(changed, bool) else 0.0


def _nearest_shown(state: TreeState, key: str, before: TreeState | None = None) -> str:
    """The row nearest above `key` that `state` still shows (its node, layer or `more` row), else the tree's first;
    `before`, the tree as last drawn, knows where a node that left the graph since stood."""
    parents = {**(before.parent if before is not None else {}), **state.parent}
    while key and key not in state.order:
        key = parents.get(key, "")
    return key or state.first


class AgentViewMixin:
    """`App`'s subagent view, list and log.

    The state it reads and writes is set in `App.__init__`, `mode` is
    `ModesMixin`'s, and the methods it calls without defining them are `App`'s.
    """

    def _agent_view(self, cols: int, rows: int, room: int | None = None) -> list[Line]:
        """The agent view under the info line (and in `room` rows at most, when given); the open agent list in the
        same rows, noting each row's agent id in `listed`.

        While the conversation's delegation graph is a DAG run its folding
        tree (`_tree_view`) is the view, in up to `TREE_ROWS` rows (a third
        of a short screen) from the start and no more rows than the tree has
        (the owner wants the graph in sight while it runs, and the area under
        the composer small); Down gives the tree the keys. A run
        that is over leaves the view as its turn ends (`_run_gone`): its end
        print in the transcript holds its final graph. Otherwise the roster's
        rows while it holds agents, else the HUD's agents block and the tree,
        each in `layout.agent_view_cap`.
        """
        self.listed = ()
        self.tree_state = None
        payload = self.hud.payload if self.hud is not None else None
        valid = isinstance(payload, Mapping) and not payload.get("error")  # else the slot says the reader failed
        frame, now = self._spinner_frame(), self.clock()
        if valid and graph_is_dag(payload):
            graph = payload["delegation_graph"]
            if not self._busy() and dag_run_summary(graph):
                self._retire_finished_run(graph)
            if self._run_gone(graph):
                # The view stands for the dag run while its graph is one; once it is over that is nothing at all.
                self.tree_selected = self.list_selected = None
                return []
            cap = self._view_cap(rows, cols, min(TREE_ROWS, rows // 3), room)
            lines = self._tree_view(payload, cols, cap)
            if self.list_selected is None:
                return lines
            listed, self.listed = self.roster.list_lines(cols, self.theme, self.list_selected, frame, len(lines), now)
            return listed + [()] * (len(lines) - len(listed))
        self.tree_selected = None  # no tree is drawn to hold the keys
        if self.roster.agents:
            running = self.roster.running_count()
            cap = self._view_cap(rows, cols, 1 + running + int(len(self.roster.agents) > running), room)
            viewing = self.viewing.subagent_id if self.viewing is not None else None
            if self.list_selected is not None:
                lines, self.listed = self.roster.list_lines(cols, self.theme, self.list_selected, frame, cap, now)
                return lines if viewing is None else mark_rows(lines, self.listed, viewing, self.list_selected, self.theme)
            if viewing is not None and viewing in self.roster.agents:
                # The list's rows stay in sight, the viewed one pointed at and kept on screen (`mark_rows`).
                lines, shown = self.roster.list_lines(cols, self.theme, viewing, frame, cap, now)
                return mark_rows(lines, shown, viewing, None, self.theme)
            return self.roster.view_lines(cols, self.theme, frame, cap, now)
        if not valid:
            return []
        return self._hud_view(payload, cols, self._view_cap(rows, cols, agent_view_keep(payload, cols), room))

    def _run_gone(self, graph: Mapping[str, Any]) -> bool:
        """Whether the view no longer draws `graph`'s dag run (the owner, 2026-10-26: a finished run stayed under the
        composer until the next prompt). It is over (`panels.dag_run_summary`) and no turn runs, or it was retired
        (`_retire_finished_run`) and has not moved since: a payload older than the end print that retired it still
        shows a lane running, and a later turn reads the same run over. A run whose every lane settled mid-turn
        keeps its tree (each layer shut) until the turn ends, and its end print with it. A run an
        extend or a repair moved on after its end (a newer `changed_at`, still open) is drawn again."""
        if not self._busy() and dag_run_summary(graph):
            return True
        if self.retired_run is None:
            return False
        key, changed = self.retired_run
        return run_key(graph) == key and (bool(dag_run_summary(graph)) or _changed_at(graph) <= changed)

    def _retire_finished_run(self, graph: Mapping[str, Any]) -> None:
        """Stop drawing `graph`'s dag run, which is over: as the turn ends with it over (`_agent_view`), or as its
        end print reads it over afresh (`App._dag_ends_due`) while the panel's payload may be older. Its children
        leave the roster with it, so the roster's rows do not take its place once its graph lingers out of the HUD.
        The rows its tree took go with it: on the bottom rows the region's top moves down by them (`App._render`)."""
        key, changed = run_key(graph), _changed_at(graph)
        self.retired_run = (key, changed)
        self._forget_agents(self.roster.drop_runs(frozenset(key.split())))

    def _tree_view(self, payload: Mapping[str, Any], cols: int, cap: int) -> list[Line]:
        """A dag run's folding tree (`dag_tree`) in `cap` rows, noting what its keys need in `tree_state`."""
        graph = payload["delegation_graph"]
        keys_free = (
            self.slot is None and self.picker is None and self.rewind_picker is None and self.model_picker is None
            and self.search is None
        )
        if cap < MIN_TREE_ROWS or not keys_free:
            self.tree_selected = None  # a question, a picker or the search has the keys now, or no room for a highlight
        if cap <= 0:
            return []
        frame, now = self._spinner_frame(), self.clock()
        self.tree_size = (cols, cap)
        folds = self._tree_folds(graph)

        processes = {process.proc_id: (tool_call(process), process.started_at) for process in self.bg_running}
        # The spinner and the waiting dots are the tree's motion: held while the window is unfocused, as the
        # ambience is (`_ambient_clock`, #2542). The times on its rows are content and count on at `wall`.
        frame, beat, wall = self._held_frame(), int(self._ambient_clock()) if self.motion else None, self.wall_clock()

        def draw() -> tuple[list[Line], TreeState]:
            return tree_lines(graph, self.roster, cols, cap, self.theme, frame, folds, self.tree_selected,
                              self.color_depth, now, self._aura_phase(), processes, wall, self.hud.received_at, beat)

        lines, self.tree_state = draw()
        self.tree_second = int(wall)
        if self.tree_selected is not None and self.tree_selected not in self.tree_state.order:
            # A fold hid the highlighted row, or its node left the graph: the nearest row above it still shown.
            self.tree_selected = _nearest_shown(self.tree_state, self.tree_selected)
            lines, self.tree_state = draw()
        return lines

    def _tree_folds(self, graph: Mapping[str, Any]) -> dict[str, bool]:
        """The person's folds for `graph`'s run: they belong to one run (a layer's key is only its label), so a new run
        starts with none."""
        run = run_key(graph)
        if run != self.tree_run:
            self.tree_folds, self.tree_run = {}, run
        return self.tree_folds

    def _tree_state_now(self) -> TreeState | None:
        """The tree the last frame drew, laid out again with the folds and the highlight as they are now: keys read
        in one batch arrive between two frames, and each must see what the one before it did."""
        payload = self.hud.payload if self.hud is not None else None
        valid = isinstance(payload, Mapping) and not payload.get("error")
        if self.tree_state is None or not valid or not graph_is_dag(payload):
            return None
        cols, cap = self.tree_size
        graph = payload["delegation_graph"]
        return tree_lines(
            graph, self.roster, cols, cap, self.theme, 0, self._tree_folds(graph), self.tree_selected, now=self.clock(),
        )[1]

    def _tree_available(self) -> bool:
        """Whether Down can give the tree the keys: the last frame drew one, and nothing else holds the keys (a
        question, a picker, the history search, the agent list)."""
        return (
            self.tree_state is not None and bool(self.tree_state.order) and self.tree_size[1] >= MIN_TREE_ROWS
            and self.slot is None and self.picker is None and self.rewind_picker is None and self.model_picker is None
            and self.search is None and self.list_selected is None
        )

    def _tree_say(self) -> tuple[tuple[str, ...], Style]:
        """What the info line says while the tree has the keys: its keys, or, once `x` asked, the confirmation."""
        agents = self.tree_state.agents if self.tree_state is not None else {}
        armed = self.roster.agents.get(self.interrupt_armed or "")
        if armed is not None and agents.get(self.tree_selected or "") == armed.subagent_id:
            return tuple(form.format(name=armed.name) for form in INTERRUPT_CONFIRMS), self.theme.warn
        return TREE_HINTS, self.theme.hint

    def _tree_key(self, event: Key | Paste) -> bool:
        """The dag tree's keys; True when the tree took the key, which it does with every key while it has them.

        Down on an empty composer gives the tree the keys, on its first
        running node, while one is drawn and no completion menu is open.
        Then Up and Down move over the layer, node and `N more` rows shown,
        stopping at either end. Left shuts the highlighted row, or on a shut
        one goes to its parent; Right opens it (an `N more` row gives way to
        the nodes it held, the first of them highlighted); Space flips it.
        On a node a child ran for, Enter opens that child's log (over the
        tree: leaving the log comes back to it), and `x` (once a second `x`
        confirms) and `s` interrupt and steer it as the agent list's keys
        do (`_agent_action`); on any other row they do nothing, so a key
        has one meaning wherever the highlight is. Esc, `q` or Ctrl+C
        leaves, and so does an Alt chord in the legacy encoding, which is
        then read as it would have been (`_agent_list_key`); any other key
        does nothing. A fold is kept in `tree_folds` and wins over the
        default and over shutting rows to fit, for as long as the run lasts
        (`_tree_folds`). A key that finds its highlighted row gone (a
        payload hid it since the last frame) moves the highlight to the
        nearest row still shown and does nothing else.
        """
        name = event.name if isinstance(event, Key) else ""  # a paste is no key of the tree's
        if self.tree_selected is None and not (
            name == DOWN or (isinstance(event, Key) and event.char == "n" and list_nav_step(event) == 1)
        ):
            return False
        if isinstance(event, Key) and name == CHAR and event.alt and not event.protocol:
            self.tree_selected = None  # a legacy Alt chord is also Esc and a key: it leaves, as the list's does
            return False
        state = self._tree_state_now()
        if self.tree_selected is None:
            if state is None or self.composer.text or self._menu_rows() or not self._tree_available():
                return False
            self.tree_selected = state.first
            return True
        armed, self.interrupt_armed = self.interrupt_armed, None  # any key ends a question it did not answer
        if state is None:  # no tree is drawn now (the run is over, or the graph left the HUD): the keys go back
            self.tree_selected = None
            return True
        if self.tree_selected not in state.order:
            # A payload since the last frame hid the highlighted row: the highlight moves to the nearest row still shown
            # and the key is spent on that, so no key acts on a row the person did not see highlighted.
            self.tree_selected = _nearest_shown(state, self.tree_selected, self.tree_state)
            return True
        key = self.tree_selected
        expanded = state.expanded.get(key, False)
        action = event.char if isinstance(event, Key) and name == CHAR and not event.ctrl and not event.alt else ""
        agent = state.agents.get(key)
        step = list_nav_step(event)
        if step != 0 or name in (UP, DOWN):
            delta = step if step != 0 else (-1 if name == UP else 1)
            at = state.order.index(key) + delta
            self.tree_selected = state.order[min(max(at, 0), len(state.order) - 1)]
        elif name == LEFT:
            if expanded:
                self.tree_folds[key] = False
            elif state.parent.get(key) in state.order:
                self.tree_selected = state.parent[key]
        elif name == RIGHT or action == " ":
            if key in state.foldable and (name != RIGHT or not expanded):
                self.tree_folds[key] = not expanded
                if not expanded:
                    self.tree_selected = state.reveals.get(key, key)  # an `N more` row gives way to its nodes
        elif name == ENTER:
            if agent is not None:
                self._open_agent(agent)
        elif action in ("x", "s"):
            if agent is not None:
                self._agent_action(action, agent, armed)
        elif name == ESCAPE or action in LEAVE_KEYS or (
            isinstance(event, Key) and name == CHAR and event.ctrl and event.char == "c"  # Shift or Alt too
        ):
            self.tree_selected = None
        return True

    def _open_dag_nodes(self) -> frozenset[str]:
        """The node ids of the conversation's dag run while it is open (a DAG graph whose lanes have not all settled,
        and not retired, `_run_gone`): the lanes whose agents a new turn keeps (`Roster.clear`)."""
        payload = self.hud.payload if self.hud is not None else None
        if not isinstance(payload, Mapping) or payload.get("error") or not graph_is_dag(payload):
            return frozenset()
        graph = payload["delegation_graph"]
        if dag_run_summary(graph) or self._run_gone(graph):
            return frozenset()
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        lanes = (node for node in nodes if isinstance(node, Mapping) and node.get("kind") != "root")
        return frozenset(str(node.get("id")) for node in lanes)

    def _view_cap(self, rows: int, cols: int, keep: int, room: int | None) -> int:
        """`layout.agent_view_cap` for `keep` rows, and no more than `room` when given."""
        cap = agent_view_cap(rows, cols, keep)
        return cap if room is None else min(cap, room)

    def _held_view_rows(self, wanted: int, budget: Budget, rows: int) -> int:
        """The most rows the view takes, wanting `wanted`, once a turn has ended and while the region is on the
        screen's last row, in a frame laid out as `budget` on a terminal of `rows` rows.

        While a turn runs the tail keeps its working rows (`layout.allocate`'s
        `tail_floor`), and on the bottom rows the composer stands right above
        the view: a view that took them once the turn ended pulled the
        composer up, and gave them back at the next turn. So only those rows
        are held: the view gets what the slot, the menu and the composer open
        now leave it, less the working rows, and never fewer rows than the
        turn's last frame gave it. A squeeze that was open as the turn ended
        (a draft, a menu, a question) is not held once it closes. The held
        rows stay blank above the composer, as rows the content gives up do
        (`layout`). A view that wants fewer rows gives them up at once; one
        that wants more than it did then drops the hold, so it does not snap
        back when it later wants fewer. An idle frame drawn above the bottom
        rows drops it too (`_render`). That covers a turn drawn there (the
        next frame is not on the bottom rows either) and a size change (the
        full redraw after it starts a new region, not on the bottom rows).
        Emptying the roster drops it as well (`_clear_roster`): `/new` keeps
        the region where it is.
        """
        if self.view_hold is None:
            return wanted
        last_wanted, last_given, working = self.view_hold
        if wanted > last_wanted:
            self.view_hold = None
            return wanted
        # What allocate left the view and the tail under the parts placed before them (`layout.allocate`).
        left = max_height(rows) - (
            budget.composer + budget.info + budget.bottom_rule + budget.rule + budget.below + budget.slot
        )
        return max(last_given, left - working)

    def _hud_view(self, payload: Mapping[str, Any], cols: int, cap: int, show_agents: bool = True) -> list[Line]:
        """The HUD's agents block (unless `show_agents` is False) and the delegation tree, in `cap` rows."""
        if cap <= 0:
            return []
        return panel_lines(
            payload, cols, cap, self.theme, self.wall_clock(), received_at=self.hud.received_at,
            show_plan=False, show_agents=show_agents, agents_inset=self._info_inset(),
            motion=self.motion, color_depth=self.color_depth,
        )

    def _agent_chip(self, room: int) -> Line:
        """The info line's count of the agents the view under it stands for, in `room` cells: `3 agents · ↓ agents`
        while Down would open their list, else the count alone; nothing with no agent, or no room for the count.

        During a dag run the count is the run's running lanes (`1,204 agents`), the lanes its tree draws as running,
        and the chip goes once none runs or the run is over (`_run_gone`, the view drawing nothing then): the roster
        holds every child the run ever started.
        """
        payload = self.hud.payload if self.hud is not None else None
        if isinstance(payload, Mapping) and not payload.get("error") and graph_is_dag(payload):
            graph = payload["delegation_graph"]
            lanes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
            running = sum(1 for node in lanes if isinstance(node, Mapping) and node.get("kind") != "root"
                          and node.get("state") in RUNNING_NODE_STATES)
            gone = dag_run_summary(graph) or self._run_gone(graph)
            count = f"{running:,} agent{'' if running == 1 else 's'}" if running and not gone else ""
        else:
            count = self.roster.count_text()
        if not count and not graph_is_dag(payload):
            number = agent_view_count(payload)
            count = f"{number:,} agent{'' if number == 1 else 's'}" if number else ""
        if not count:
            return ()
        opens = (self._list_available() or self._tree_available()) and not self.composer.text and not self._menu_rows()
        forms = [f"{count}{CHIP_SEPARATOR}{OPEN_MARK}", count] if opens else [count]
        shown = next((form for form in forms if cell_width(form) <= room), "")
        return (Span(shown, self.theme.hint),) if shown else ()

    def _agent_list_say(self) -> tuple[tuple[str, ...], Style]:
        """What the info line says while the list is open: its keys, or, once `x` asked, the confirmation in warn."""
        armed = self.roster.agents.get(self.interrupt_armed or "") if self.interrupt_armed == self.list_selected else None
        if armed is not None:
            return tuple(form.format(name=armed.name) for form in INTERRUPT_CONFIRMS), self.theme.warn
        return AGENT_LIST_HINTS, self.theme.hint

    def _clickable_rows(self) -> Sequence[str]:
        """What a click on each of the view's rows selects, top first: the list's agent ids while it is open, the tree's
        row keys while it has the keys ("" for a row a click does nothing on), else nothing."""
        if self.tree_selected is not None and self.tree_state is not None:
            return self.tree_state.rows
        return self.listed

    def _take_clickable(self, budget: Budget, listed: Sequence[str]) -> None:
        """Note the agent list's rows a click opens in the frame just drawn (or the dag tree's rows, while the tree has
        the keys), and ask for mouse reports while one of them is open, or wherever the main screen takes the mouse
        (`_take_main_mouse`).

        The list is the agent view's rows, from its first, under the info
        line: the region's last rows. A list row is clickable from edge to
        edge, and so is a tree row (one with nothing to select does nothing
        when clicked); nothing else is, the info line's count included. Reports stay
        off while the region's place on the screen is not certain, since no
        click could be read then.
        """
        cols, rows = self.size
        shown = listed[: budget.agents]
        # Counted up from the region's last row, the view's last.
        self.clickable = {budget.agents - 1 - index: (Hit(0, cols, row_id),)
                          for index, row_id in enumerate(shown)}
        self._take_main_mouse(bool(self.clickable))

    def _list_available(self) -> bool:
        """Whether the agent list can be shown: agents to list, a terminal with room for the agent view (the info
        line says its keys), and nothing else holding the keys (a question, a picker, the history search)."""
        cols, rows = self.size
        return (
            bool(self.roster.agents) and not is_tiny(rows, cols) and self.slot is None and self.picker is None
            and self.rewind_picker is None and self.model_picker is None and self.search is None
        )

    def _settle_list(self) -> None:
        """Take the keys back from a list that can no longer be shown; keep its highlight on a row it still has."""
        if self.list_selected is None:
            return
        if not self._list_available():
            self.list_selected = None
        elif self.list_selected not in self.roster.agents:
            self.list_selected = MAIN_ID

    def _agent_list_key(self, event: Key | Paste) -> bool:
        """The agent list's keys; True when the list took the key, which it does with every key while it is open.

        Down on an empty composer gives the list the keys, on the first
        agent, while there is one to list and no completion menu is open.
        Then Up and Down move, stopping at either end; Enter opens the
        highlighted agent's log (on main it only leaves); Esc, Left, `q` or
        Ctrl+C leaves; and on an agent `x` asks to interrupt it (a second `x`
        does) and `s` makes the next line sent its steer (`_agent_action`).
        Any other key, a paste or a sequence the decoder has no name for
        does nothing, so nothing typed with the list open reaches the
        composer (with mouse reports on, a terminal that answers in the
        legacy encoding sends such a sequence for every click). The one
        exception is an Alt chord in the legacy encoding, whose bytes are also
        Esc and a key arriving in one read: it leaves, as Esc does, and is then
        read as it would have been, so the key after the Esc is typed.
        """
        if self._tree_key(event):
            return True
        self._settle_list()
        name = event.name if isinstance(event, Key) else ""  # a paste is no key of the list's
        if self.list_selected is None:
            enter_list = name == DOWN or (
                isinstance(event, Key) and event.char == "n" and list_nav_step(event) == 1
            )
            if not enter_list or self.composer.text or self._menu_rows() or not self._list_available():
                return False
            self.list_selected = next(iter(self.roster.agents))
            return True
        armed, self.interrupt_armed = self.interrupt_armed, None  # any key ends a question it did not answer
        if isinstance(event, Key) and name == CHAR and event.alt and not event.protocol:
            self.list_selected = None
            return False
        action = event.char if isinstance(event, Key) and name == CHAR and not event.ctrl and not event.alt else ""
        if action in ("x", "s") and self.list_selected != MAIN_ID:
            self._agent_action(action, self.list_selected, armed)
        elif (step := list_nav_step(event)) != 0 or name in (UP, DOWN):
            delta = step if step != 0 else (-1 if name == UP else 1)
            ids = self.roster.ids()
            row = ids.index(self.list_selected) + delta
            self.list_selected = ids[min(max(row, 0), len(ids) - 1)]
        elif name == ENTER and self.list_selected != MAIN_ID:
            self._open_agent(self.list_selected)  # its session on the main screen, else its log over the list
        elif name == ENTER and (self.viewing is not None or self.view_opening is not None):
            self.list_selected = None  # main's row: back to main, an open still out dropped
            self._leave_view()
        elif name in (ENTER, ESCAPE, LEFT) or action in LEAVE_KEYS or (
            isinstance(event, Key) and name == CHAR and event.ctrl and event.char == "c"  # Shift or Alt too
        ):
            self.list_selected = None
        return True

    def _agent_action(self, action: str, subagent_id: str, armed: str | None) -> None:
        """`x` (once a second `x` confirms) interrupts the highlighted agent; `s` makes the next line sent its steer."""
        agent = self.roster.agents.get(subagent_id)
        if agent is None:
            return
        if agent.status in FINISHED_STATUSES:
            verb = "interrupt" if action == "x" else "steer"
            self.transcript.add_aside(NoticeBlock(AGENT_FINISHED_NOTICE.format(name=agent.name, action=verb)))
        elif action == "s":
            self.agent_steer = subagent_id
            self.list_selected = self.tree_selected = None  # the composer has the keys for the text
        elif armed == subagent_id:
            self._interrupt_agent(subagent_id, agent.name)
        else:
            self.interrupt_armed = subagent_id

    def _interrupt_agent(self, subagent_id: str, name: str) -> None:
        if not self.sid:
            return
        self._request(
            "subagent.interrupt",
            {"session_id": self.sid, "subagent_id": subagent_id},
            lambda result: self.transcript.add_aside(NoticeBlock(
                (AGENT_INTERRUPTED_NOTICE if result.get("found") is True else AGENT_ALREADY_DONE_NOTICE).format(name=name)
            )),
            lambda error: self._agent_refused(
                AGENT_INTERRUPT_REFUSED_NOTICE.format(name=name, reason=(as_text(error.get("message")) or "refused").rstrip("."))
            ),
        )

    def _agent_refused(self, notice: str) -> bool:
        self.transcript.add_aside(NoticeBlock(notice, NOTICE_WARN))
        return True

    def _steer_agent(self, subagent_id: str, text: str, owner: str = "") -> None:
        """Send `text`, the line the person typed after `s`, to the agent they picked (`subagent_id`, decided at Enter);
        what cannot go or is not taken goes back to the composer it was typed in (`owner`, `_owner_draft`), never
        into main's queue."""
        agent = self.roster.agents.get(subagent_id)
        if agent is None or agent.status in FINISHED_STATUSES or not self.sid:
            name = agent.name if agent is not None else "That agent"
            self._owner_transcript(owner).add_aside(
                NoticeBlock(AGENT_FINISHED_NOTICE.format(name=name, action="steer"), NOTICE_WARN))
            self._give_back_from(owner, text)
            return
        block = self.transcript.add_steer(text, agent=agent.name)  # held under what runs, as the main steer is
        sid, session = self.sid, self.stored_id or self.sid
        self._request(
            "subagent.steer",
            {"session_id": sid, "subagent_id": agent.subagent_id, "text": text},
            lambda result: self._on_agent_steered(sid, session, block, result, owner=owner),
            lambda error: self._on_agent_steered(sid, session, block, {}, as_text(error.get("message")).strip().rstrip("."),
                                                 owner=owner),
            lambda seconds: self._on_agent_steer_unanswered(sid, session, block, seconds, owner),  # back, never resent
            steer=block,
        )

    def _on_agent_steered(
        self, sid: str, session: str, block: SteerBlock, result: Mapping[str, Any], reason: str = "", owner: str = "",
    ) -> bool:
        """Hermes' answer to an agent steer: taken, or refused (with `reason` when Hermes gave one) and given back.

        Settled after `sid`, the session it went to, was left (named `session`), whatever the answer, its text
        comes back with a notice saying so, as the main steer's does.
        """
        if sid != self.sid:
            self._steer_back(block.text, AGENT_STEER_LEFT_NOTICE.format(name=block.agent, session=session), owner)
            return True
        if as_text(result.get("status")) == contract.STEER_QUEUED:
            self.transcript.steer_answered(block, STEER_QUEUED)
        else:
            said = AGENT_STEER_REFUSED_BECAUSE.format(reason=reason) if reason else AGENT_STEER_REFUSED
            self.transcript.steer_answered(block, STEER_REFUSED, said)
            self._give_back_from(owner, block.text)
        return True

    def _on_mouse(self, event: Mouse) -> None:
        """A plain left press on an agent's row of the list opens that agent's log, and on a dag tree row moves the
        highlight there and opens the node's child's log if it has one; any other report is the main screen's
        (`_screen_mouse`).

        The one other thing a click does is leave the list, from its main
        row, which has no log. `clickable` holds the cells of the last frame
        a click opens and is empty whenever the TUI has not asked for
        reports, so a report another program left on opens nothing. The
        report's row is read against the region's last row, and dropped while
        that row is not certain, while a question Hermes asked has the keys,
        or while the screen is being redrawn for a new size.
        """
        plain = event.button == BUTTON_LEFT and event.pressed and not (event.motion or event.shift or event.alt or event.ctrl)
        last = self.region.last_row(self.size[1])
        if not plain or last is None or self.pager is not None or self.slot is not None or self.redraw_at is not None:
            self._screen_mouse(event)
            return
        above, column = last - (event.y - 1), event.x - 1  # a report counts from 1
        target = next((hit.subagent_id for hit in self.clickable.get(above, ()) if hit.start <= column < hit.end), None)
        if target is None:
            self._screen_mouse(event)
            return
        if self.tree_selected is not None:  # a dag tree row: it takes the highlight, and a node's child its log opens
            if not target:
                return  # a count or blank row selects nothing
            self.tree_selected = target
            agent = self.tree_state.agents.get(target) if self.tree_state is not None else None
            if agent is not None:
                self._open_agent(agent)
            return
        if self.list_selected is not None:
            self.list_selected = target if target != MAIN_ID else None  # main has no log: the click leaves the list
        if target != MAIN_ID:
            self._open_agent(target)
        elif self.viewing is not None or self.view_opening is not None:
            self._leave_view()  # main's row: back to main, an open still out dropped

    # ── one subagent's session on the main screen (`subagent_session`) ──

    def _open_agent(self, subagent_id: str) -> None:
        """Show `subagent_id`'s session on the main screen, as Claude Code shows a teammate's; its log in the pager
        where the view cannot open (no session, no child session yet, or a read Hermes refuses: `_view_opened`).

        The read goes by the wire (`subagent_session.wire_for`): a lazy watch of the child's session on Hermes'
        stdio entry, a `session.transcript` read of its rows on the shared gateway; never a plain resume of the
        child. The agent already on screen only gives the composer the keys back."""
        agent = self.roster.agents.get(subagent_id)
        if agent is None:
            return
        if self.viewing is not None and self.viewing.subagent_id == subagent_id:
            self.list_selected = self.tree_selected = None
            return
        if self.rewind is not None or self.tell_draft is not None:
            self.transcript.add_notice(VIEW_REFUSED_ARMED, NOTICE_WARN)  # finish or cancel it first (NB1)
            self.list_selected = self.tree_selected = None
            return
        if not self.sid or not agent.child_session_id:
            self._open_agent_log(subagent_id)
            return
        if self.view_opening == subagent_id:
            return  # its open is out already: one intent, one read
        wire = view_state.wire_for(self.shared_gateway)
        method, params = view_state.open_call(wire, self.sid, subagent_id, agent.child_session_id, self.size[0])
        self.view_opening = subagent_id
        self.view_open_seq += 1
        sid, seq = self.sid, self.view_open_seq
        self._request(
            method, params,
            lambda result: self._view_opened(sid, seq, subagent_id, wire, result),
            lambda error: self._view_refused(sid, seq, subagent_id),
            lambda _seconds: self._view_refused(sid, seq, subagent_id),  # no answer: the log, as for a refusal
            watch=True,
        )

    def _open_wanted(self, sid: str, seq: int) -> bool:
        """Whether an open's answer is the latest open's, still wanted: none since replaced or cancelled it (`main`,
        Esc, a switch, `/new`, a respawn: `_cancel_view_open`), in the session it was asked in."""
        return self.view_opening is not None and seq == self.view_open_seq and sid == self.sid

    def _cancel_view_open(self) -> None:
        """Drop the open still out: its answer, when it comes, shows nothing (`_open_wanted`)."""
        self.view_opening = None
        self.view_open_seq += 1

    def _close_watch(self, watch: str) -> None:
        """`session.close` of a watch session an answer opened that no view shows; never the one the shown view owns
        (Hermes hands the same live watch sid to a second lazy resume of a child)."""
        if watch and (self.viewing is None or self.viewing.watch_sid != watch):
            self._request("session.close", {"session_id": watch}, lambda _result: None, lambda _error: True)

    def _view_refused(self, sid: str, seq: int, subagent_id: str) -> bool:
        """A refused open, of any kind: the agent's log in the pager, as before the view, if it is still wanted."""
        if self._open_wanted(sid, seq):
            self.view_opening = None
            self._open_agent_log(subagent_id)
        self._close_stale_watches(subagent_id)
        return True

    def _close_stale_watches(self, subagent_id: str) -> None:
        """Close the watch sids stale open answers left undecided, once no newer open of `subagent_id` is out; never
        one the shown view owns (`_close_watch`)."""
        if self.view_opening == subagent_id:
            return
        watches, self.view_stale_watches = self.view_stale_watches, set()
        for watch in sorted(watches):
            self._close_watch(watch)

    def _view_opened(self, sid: str, seq: int, subagent_id: str, wire: str, result: Mapping[str, Any]) -> None:
        """An open's answer: the view, filled from the history or rows it read, on the main screen. One that reads no
        view (`subagent_session.read_refused`) opens the agent's log instead. One that is not the latest open's, or
        was cancelled (`_open_wanted`), is dropped, and the watch session it opened closed unless the shown view owns
        it."""
        watch = as_text(result.get("session_id")) if wire == WIRE_WATCH else ""
        if not self._open_wanted(sid, seq):
            if watch and sid == self.sid and self.view_opening == subagent_id:
                self.view_stale_watches.add(watch)  # the newer open may get this very sid: decide at its answer
            else:
                self._close_watch(watch)
                self._close_stale_watches(subagent_id)
            return
        self.view_opening = None
        agent = self.roster.agents.get(subagent_id)
        if view_state.read_refused(wire, result) or agent is None:
            self._close_watch(watch)
            self._close_stale_watches(subagent_id)
            self._open_agent_log(subagent_id)
            return
        if self.viewing is not None:
            self._leave_view(redraw=False)
        # The roster's end wins: a read the host answered before it delivered the end still says running (R1-D6).
        stale = result.get(contract.TRANSCRIPT_RUNNING) is True and agent.status in FINISHED_STATUSES
        view = SubagentView(subagent_id, agent.name, sid, wire, Transcript(self.clock), watch_sid=watch,
                            running=result.get(contract.TRANSCRIPT_RUNNING) is True and not stale,
                            cursor=as_text(result.get(contract.TRANSCRIPT_NEXT_CURSOR)), polled_at=self.clock())
        view.transcript.cwd = self.transcript.cwd
        rows = result.get("messages") if wire == WIRE_WATCH else result.get(contract.TRANSCRIPT_ROWS)
        self._fill_view(view, rows, agent.goal)
        if wire == WIRE_POLL and not view.running:  # a finished child: its pages are read until an empty one
            view.pages_left = view_state.CATCH_UP_PAGES - 1  # the open's own read was one, sent after the end
            # A read answered before the end never says caught up: its rows may stop short of the last reply.
            if not view_state.page_read(view, counts=True, empty=view_state.caught_up(result) and not stale):
                self._read_spent(view)
        main = self._screen_draft()  # whatever the composer holds now is main's: set aside whole, the view's comes in
        main._drop_pending()
        child = self.child_drafts.pop(subagent_id, None) or Composer(history=main.history, on_record=main.on_record)
        child.set_vim(main.vim)
        view.main_draft = self._swap_draft(child)
        self.viewing = view
        self.transcript.offscreen = True  # main keeps folding, bounded by BLOCK_CAP, until it is shown again
        self.list_selected = self.tree_selected = None  # the composer has the keys: what is typed goes to the agent
        self._close_stale_watches(subagent_id)
        self._full_redraw()

    def _fill_view(self, view: SubagentView, rows: object, goal: str) -> None:
        """`view`'s transcript from the top: `› From main`, the brief (the goal, until a read brings its row, which
        then takes its place: `_on_view_rows`), then the rows read, drawn as a resumed session's are
        (`App._draw_history`). The rebuilt transcript holds no echo of a steer sent from the view, so every stored
        row is drawn and none is matched against an echo (`sent_steers` starts over)."""
        messages = view_state.message_rows(rows)
        view.transcript = Transcript(self.clock)
        view.transcript.cwd = self.transcript.cwd
        view.transcript.add_aside(NoticeBlock(FROM_MAIN, one_line=True))
        view.brief_pending, view.brief_block = False, None
        view.sent_steers.clear()
        if not view_state.has_brief(messages) and goal.strip():
            view.brief_block = view.transcript.add_user(goal, recorded=True)
            view.brief_pending = True
        self._draw_history(messages, into=view.transcript)

    def _leave_view(self, redraw: bool = True, close: bool = True) -> None:
        """Back to main: main's draft comes back exactly as the view set it aside, the view's unsent draft is kept for
        its agent (`child_drafts`), the watch session closes (the shared gateway's read holds none; `close` False when
        it went with the gateway), and main's transcript, which folded every main event meanwhile, is drawn again. An
        open still out is dropped as it answers."""
        self._cancel_view_open()
        self.agent_steer = None  # a picked `s` belongs to the composer that armed it
        view, self.viewing = self.viewing, None
        if view is None:
            return
        self.transcript.offscreen = False
        tell_text, tell_images = "", []
        if self.tell_draft is not None and self.tell_owner and self.tell_owner == view.watch_sid:
            # The child's tell field leaves with its view: its text is kept for that child, never main's (R2-F3).
            tell = self.composer
            tell._drop_pending()
            tell_text, tell_images = tell.expanded(), [image for _label, image in tell.images.values()]
            self.composer, self.tell_draft, self.tell_owner = self.tell_draft, None, ""
        if view.main_draft is not None:
            child = self._swap_draft(view.main_draft)
            child._drop_pending()
            if child.text.strip() or child.images:
                kept = self.child_drafts.get(view.subagent_id)
                if kept is None:
                    self.child_drafts[view.subagent_id] = child
                else:  # a late refusal kept text for it already: both stay, this draft on a new line after it
                    self._give_back(child.expanded(), [image for _label, image in child.images.values()], into=kept)
            view.main_draft = None
        if tell_text.strip() or tell_images:
            kept = self.child_drafts.setdefault(view.subagent_id, Composer(history=self.composer.history,
                                                                            on_record=self.composer.on_record))
            self._give_back(tell_text, tell_images, into=kept)
        view.sent_steers.clear()
        if view.watch_sid and close:
            self._request("session.close", {"session_id": view.watch_sid}, lambda _result: None, lambda _error: True)
        if redraw:
            self._full_redraw()

    def _swap_draft(self, draft: Composer) -> Composer:
        """Put `draft` where the screen's draft stands (`App._screen_draft`: the composer, or the one a question's or a
        tell row's own composer set aside) and hand back the one it replaces. A picked `s` belongs to the composer
        that armed it, so it goes."""
        self.agent_steer = None
        if self.tell_draft is not None:
            old, self.tell_draft = self.tell_draft, draft
        elif self.slot_draft is not None:
            old, self.slot_draft = self.slot_draft, draft
        else:
            old, self.composer = self.composer, draft
        return old

    def _screen_owner(self) -> str:
        """Who owns the composer on screen: "" for main, else the agent id of the view shown."""
        return self.viewing.subagent_id if self.viewing is not None else ""

    def _owner_draft(self, owner: str) -> Composer | None:
        """The draft of the composer `owner` typed in: main's (`_draft`, set aside while a view is shown) for "";
        for an agent, the composer of whichever view of it is on screen now, else its kept draft (`child_drafts`),
        which comes back whole when its view opens again; None for an agent no longer listed."""
        if not owner:
            return self._draft()
        if self.viewing is not None and self.viewing.subagent_id == owner:
            return self._screen_draft()
        if owner not in self.roster.agents:
            return None
        return self.child_drafts.setdefault(owner, Composer())

    def _owner_transcript(self, owner: str) -> Transcript:
        """Where a notice about what `owner` typed shows: the view of that agent while it is on screen, else main's."""
        if owner and self.viewing is not None and self.viewing.subagent_id == owner:
            return self.viewing.transcript
        return self.transcript

    def _give_back_to_owner(self, owner: str, text: str, images: Sequence[Any] = (), name: str = "") -> None:
        """Text not sent or not taken goes back to the composer it was typed in (`_owner_draft`), after its draft on
        a new line; for an agent no longer listed, one notice on main's screen holds it."""
        draft = self._owner_draft(owner)
        if draft is None:
            agent_name = name or owner
            self.transcript.add_notice(VIEW_TEXT_DROPPED.format(name=agent_name, text=text), NOTICE_WARN)
            return
        self._give_back(text, images, into=draft)

    def _give_back_to_view(self, view: SubagentView, text: str, images: Sequence[Any] = ()) -> None:
        """Text a view sent and its agent did not take goes back to that agent's composer (`_give_back_to_owner`),
        never into main's draft."""
        self._give_back_to_owner(view.subagent_id, text, images, view.name)

    def _prune_child_drafts(self) -> None:
        """Drop what agents the roster no longer holds owned: their kept drafts, so they stay as few as the roster's
        agents, and the pastes and drops typed in their views (an image staged for one is detached as it answers,
        `App._take_attachment`); a submit held for those goes back as `_release_held` decides."""
        for subagent_id in [key for key in self.child_drafts if key not in self.roster.agents]:
            del self.child_drafts[subagent_id]
        gone = [intake for intake in self.intakes if intake.owner and intake.owner not in self.roster.agents]
        for intake in gone:
            self.intakes.remove(intake)
        for owner in {intake.owner for intake in gone}:
            # A submit held for an image that will never join it goes back whole, never as its text alone (D12).
            self._give_back_held(owner)
        if gone:
            self._release_held()
            self._pump_claims()

    def _view_event(self, view: SubagentView, event: Any) -> None:
        """An event of the viewed child's watch session (Hermes mirrors its `message.*`, `reasoning.*` and `tool.*`
        there): folded into the view's transcript, never main's. A turn continued on it runs from its
        `message.start` to its `message.complete`."""
        if event.type == "message.start" and not view.running:
            view.turn_running = True
        view.transcript.apply(event)
        if event.type == "message.complete":
            view.turn_running = False
        elif event.type == "error":
            view.turn_running = False
            view.transcript.add_notice(as_text(event.payload.get("message")) or "The gateway reported an error.",
                                       NOTICE_WARN)
        self.dirty = True

    def _view_frame(self, event_type: str, payload: object) -> None:
        """A parent `subagent.*` frame for the agent on screen: its working row runs until its `subagent.complete`;
        on the shared gateway that end schedules a read of its last rows (`poll_due_at`: never a second read while
        one is out, still at most one a second)."""
        view = self.viewing
        if view is None or not isinstance(payload, Mapping) or as_text(payload.get("subagent_id")) != view.subagent_id:
            return
        if event_type == contract.SUBAGENT_COMPLETE:
            # On the shared gateway the next paced read reads its last rows; a read out now was sent before the end.
            view_state.child_ended(view, after=view.read_seq)

    def _poll_view_when_due(self) -> None:
        """`session.transcript` for the subagent on screen on the shared gateway, when `poll_due_at` says: while it
        runs at most one read a second, one at a time; once it ended, its pages one after another until an empty
        one. A read unanswered for `POLL_ANSWER_SECONDS` is forgotten (here and in the client) before the next goes."""
        view = self.viewing
        due = view_state.poll_due_at(view, self.clock())
        if view is None or due is None or self.clock() < due:
            return
        if view.poll_open and view.read_id is not None:
            self.pending.pop(view.read_id, None)
            self.client.forget(view.read_id)
            view.poll_open, view.read_id = False, None
        if not view.running and view.pages_left <= 0:
            self._read_spent(view)  # the post-end reads are all sent: none more goes
            return
        self._poll_view(view)

    def _poll_view(self, view: SubagentView) -> None:
        """One read from the view's cursor, fenced: only the latest read's answer, asked from the cursor the view
        still holds, applies (`_on_view_rows`)."""
        view.read_seq += 1
        seq, cursor = view.read_seq, view.cursor
        view.polled_at, view.poll_open, view.read_now = self.clock(), True, False
        if not view.running:
            view.pages_left -= 1  # a post-end read spends its one of `CATCH_UP_PAGES` as it goes, answered or not
        view.read_id = self._request(
            "session.transcript", view_state.read_params(view.parent_sid, view.subagent_id, cursor),
            lambda result: self._on_view_rows(view, seq, cursor, result),
            lambda error: self._on_view_rows(view, seq, cursor, {}),
        )

    def _on_view_rows(self, view: SubagentView, seq: int, cursor: str, result: Mapping[str, Any]) -> bool:
        """A read's answer: the new rows drawn in the view (the real brief in the goal's place), or all of them again
        on `reset`. Only the latest read's, asked from the view's cursor now, applies; one for a view since left, or
        with no rows to read (a refusal), changes nothing on screen. The cursor only moves forward and `running`
        only from true to false (`child_ended`)."""
        if seq != view.read_seq:
            return True
        view.poll_open, view.read_id = False, None
        if self.viewing is not view or cursor != view.cursor:
            return True
        if result.get(contract.TRANSCRIPT_AVAILABLE) is not True:
            if not view.running and view.pages_left <= 0:
                self._read_spent(view)  # a refused post-end read was spent as it went
            return True
        rows = view_state.message_rows(result.get(contract.TRANSCRIPT_ROWS))
        if result.get(contract.TRANSCRIPT_RESET) is True:
            agent = self.roster.agents.get(view.subagent_id)
            self._fill_view(view, rows, agent.goal if agent is not None else "")
            self._full_redraw()
        else:
            kept, brief = view_state.unseen_rows(view, rows)
            if brief is not None and view.brief_block is not None and brief.strip():
                view.transcript.replace_user_text(view.brief_block, brief)  # the brief in the goal's place, once
                self._full_redraw()
            self._draw_history(kept, into=view.transcript)
        view.cursor = as_text(result.get(contract.TRANSCRIPT_NEXT_CURSOR)) or view.cursor
        if result.get(contract.TRANSCRIPT_RUNNING) is not True:
            view_state.child_ended(view, after=seq - 1)  # the host samples `running` before it reads: this read counts
        # Caught up only on the wire's own empty `rows`, and only from a read sent after the end was seen.
        if not view_state.page_read(view, counts=seq > view.ended_seq, empty=view_state.caught_up(result)):
            self._read_spent(view)
        self.dirty = True
        return True

    def _read_spent(self, view: SubagentView) -> None:
        """Once the child ended and its `CATCH_UP_PAGES` post-end reads are all sent before an empty page: no read
        more goes, and one dim line in the view says the rest could not be read."""
        if view.running or view.pages_left > 0 or view.gave_up:
            return
        view.gave_up = True
        view.transcript.add_aside(NoticeBlock(READ_GAVE_UP.format(name=view.name), one_line=True))
        self.dirty = True

    def _send_to_view(self, text: str, shown: str, images: Sequence[Any]) -> None:
        """A line sent while a subagent's session is on screen goes to that subagent: a steer while it runs (or while a
        turn continued on its watch session runs); once it ended, a turn that continues its own conversation on
        Hermes' stdio entry, and on the shared gateway, which cannot, one dim row saying so with the text kept. A
        slash command, a `!` line or an image is main's: refused with one notice, the text kept."""
        view = self.viewing
        if view is None or not text.strip():
            return
        seen = shown or text
        if images or seen.startswith("!") or seen.startswith("/"):  # an image refuses the whole prompt: nothing goes
            view.transcript.add_notice(REFUSED_WHILE_VIEWING.format(name=view.name), NOTICE_WARN)
            self._give_back_to_view(view, text, images)
            return
        kind = view_state.send_kind(view)
        if kind == SEND_UNSUPPORTED:
            view.transcript.add_aside(NoticeBlock(UNSUPPORTED_LINE.format(name=view.name), one_line=True))
            self._give_back_to_view(view, text)
            return
        if kind == SEND_CONTINUE:
            view.transcript.add_user(text)
            view.turn_running = True
            self._request(
                "prompt.submit", {"session_id": view.watch_sid, "text": text}, lambda _result: None,
                lambda error: self._continue_refused(view, text, error),
                lambda seconds: self._continue_refused(view, text, {"message": f"no answer in {seconds:g} s"}),
                watch=True,
            )
            return
        block = view.transcript.add_steer(text, agent=view.name)
        if view.wire == WIRE_POLL:  # only a transcript read brings a steer's stored row back; stdio has none to match
            view.sent_steers.append(text)
            del view.sent_steers[:-view_state.SENT_STEERS_CAP]
        if kind == SEND_STEER:
            method, params = "subagent.steer", {"session_id": view.parent_sid, "subagent_id": view.subagent_id,
                                                "text": text}
        else:
            method, params = "session.steer", {"session_id": view.watch_sid, "text": text}
        self._request(
            method, params,
            lambda result: self._view_steered(view, block, result),
            lambda error: self._view_steered(view, block, {}, as_text(error.get("message")).strip().rstrip(".")),
            lambda seconds: self._view_steered(view, block, {}, f"no answer in {seconds:g} s"),
            steer=block, watch=True,
        )

    def _submit_dest(self) -> tuple[str, str]:
        """Where Enter sends what the composer holds, decided once, at Enter: the agent `s` picked (it wins), else the
        subagent on screen, else main (a tell row on screen takes it for main's or the asking child's turn)."""
        if self.agent_steer is not None:
            return (DEST_STEER, self.agent_steer)
        if self.viewing is not None and self.tell_draft is None:
            return (DEST_VIEW, self.viewing.subagent_id)
        return DEST_MAIN

    def _submit_to_child(
        self, dest: tuple[str, str], action: Any, images: Sequence[Any], steer: bool, now: bool,
    ) -> None:
        """Enter on a subagent destination (`_submit_dest`): the child's policy first (`_child_refuses`: the whole
        prompt refused, its text kept), then held behind this composer's own pastes still out (`App._hold_submit`,
        the destination kept with it), else sent (`_send_to_dest`). The `s` that picked it is spent once it goes."""
        if not action.text.strip():
            return
        owner = self._screen_owner()
        if self._child_refuses(dest, owner, action.text, action.shown, images):
            return
        if dest[0] == DEST_STEER:
            self.agent_steer = None
        if self._hold_submit(action, tuple(images), steer, now, dest=dest):
            return
        self._send_to_dest(dest, owner, action.text, action.shown, images)

    def _child_refuses(self, dest: tuple[str, str], owner: str, text: str, shown: str, images: Sequence[Any]) -> bool:
        """A child takes text alone: a slash command, a `!` line or any image refuses the whole prompt with one
        notice where it was typed, and the text goes back to that composer (`_give_back_to_owner`). True when
        refused."""
        seen = shown or text
        if not (images or seen.startswith("!") or seen.startswith("/")):
            return False
        kind, subagent_id = dest
        agent = self.roster.agents.get(subagent_id)
        name = agent.name if agent is not None else "that agent"
        notice = REFUSED_WHILE_VIEWING if kind == DEST_VIEW else REFUSED_FOR_STEER
        self._owner_transcript(owner).add_notice(notice.format(name=name), NOTICE_WARN)
        self._give_back_to_owner(owner, text, images, name)
        return True

    def _send_to_dest(self, dest: tuple[str, str], owner: str, text: str, shown: str, images: Sequence[Any]) -> None:
        """A child submit goes where Enter decided (`dest`), under the child's policy (`_child_refuses`): to the view
        of that agent while it is on screen (`_send_to_view`), to the agent `s` picked as its steer
        (`_steer_agent`); a view since left, or an agent gone, gives it back to the composer it was typed in, with a
        notice, never into main's queue."""
        if self._child_refuses(dest, owner, text, shown, images):
            return
        kind, subagent_id = dest
        if kind == DEST_STEER:
            self._steer_agent(subagent_id, text, owner)
        elif self.viewing is not None and self.viewing.subagent_id == subagent_id:
            self._send_to_view(text, shown, ())
        else:
            agent = self.roster.agents.get(subagent_id)
            name = agent.name if agent is not None else subagent_id
            if agent is not None:
                self.transcript.add_notice(VIEW_TEXT_KEPT.format(name=name), NOTICE_WARN)
            self._give_back_to_owner(owner, text, (), name)

    def _tell_child(self, watch: str, text: str, shown: str, images: Sequence[Any]) -> None:
        """What to tell a continued child instead of the approval it was denied: to that child's own session, the
        watch sid that asked, as main's tell goes into main's turn (`session.redirect` while its turn runs, a turn
        continued with `prompt.submit` once it ended); main's busy state plays no part. Refused or not taken, it
        goes back to that view's composer."""
        view = self.viewing if self.viewing is not None and self.viewing.watch_sid == watch else None
        if view is None:
            self.transcript.add_notice(TELL_CHILD_LEFT, NOTICE_WARN)
            self._give_back(text, images)
            return
        if self._child_refuses((DEST_VIEW, view.subagent_id), view.subagent_id, text, shown, images):
            return
        if not view.turn_running:
            self._send_to_view(text, shown, ())  # its turn ended: a continue on the watch sid
            return
        block = view.transcript.add_steer(text, agent=view.name)
        self._request(
            "session.redirect", {"session_id": watch, "text": text},
            lambda result: self._view_steered(view, block, {"status": contract.STEER_QUEUED} if as_text(
                result.get("status")) in (contract.STEER_REDIRECTED, contract.STEER_QUEUED) else result),
            lambda error: self._view_steered(view, block, {}, as_text(error.get("message")).strip().rstrip(".")),
            lambda seconds: self._view_steered(view, block, {}, f"no answer in {seconds:g} s"),
            steer=block, watch=True,
        )

    def _view_steered(self, view: SubagentView, block: SteerBlock, result: Mapping[str, Any], reason: str = "") -> bool:
        """Hermes' answer to a steer sent from the view: taken, or refused and its text back in the composer."""
        if as_text(result.get("status")) == contract.STEER_QUEUED:
            view.transcript.steer_answered(block, STEER_QUEUED)
            return True
        said = AGENT_STEER_REFUSED_BECAUSE.format(reason=reason) if reason else AGENT_STEER_REFUSED
        view.transcript.steer_answered(block, STEER_REFUSED, said)
        if block.text in view.sent_steers:
            view.sent_steers.remove(block.text)
        self._give_back_to_view(view, block.text)
        return True

    def _continue_refused(self, view: SubagentView, text: str, error: Mapping[str, Any]) -> bool:
        """A continue Hermes refused (4009 while the child still runs) or never answered: the turn is not running,
        one notice says so, and the text goes back where it was typed (`_give_back_to_view`); the next Enter decides
        steer or continue from the real state."""
        view.turn_running = False
        if error.get("code") == SESSION_BUSY:
            notice = STILL_RUNNING.format(name=view.name)
        else:
            reason = (as_text(error.get("message")) or "refused").strip().rstrip(".")
            notice = CONTINUE_REFUSED.format(name=view.name, reason=reason)
        view.transcript.add_notice(notice, NOTICE_WARN)
        self._give_back_to_view(view, text)
        return True

    def _open_agent_log(self, subagent_id: str) -> None:
        """One agent's log on the alternate screen, opened at its newest rows; nothing for an agent no longer held."""
        if subagent_id not in self.roster.agents:
            return
        self._cancel_view_open()  # the latest pick is this log: no open still out may show a view behind it
        self._open_pager("", [])
        self.log_agent = subagent_id
        self._refresh_agent_log(to_end=True)

    def _step_agent_log(self, step: int) -> None:
        """Left and Right in the log view: the agent before or after this one, stopping at either end."""
        ids = tuple(self.roster.agents)
        if self.log_agent not in ids:
            return
        self.log_agent = ids[min(max(ids.index(self.log_agent) + step, 0), len(ids) - 1)]
        if self.list_selected is not None:
            self.list_selected = self.log_agent  # leaving the log comes back to the row it shows
        node = next((key for key, agent in (self.tree_state.agents if self.tree_state else {}).items()
                     if agent == self.log_agent), None)
        if self.tree_selected is not None and node is not None:
            self.tree_selected = node
        self._refresh_agent_log(to_end=True)

    def _refresh_agent_log(self, to_end: bool = False) -> None:
        """Rebuild the open log from the roster; a view on its last page stays on it as rows arrive.

        An agent the roster no longer holds (a new turn began) keeps the rows
        last drawn.
        """
        agent = self.roster.agents.get(self.log_agent)
        if self.pager is None or agent is None:
            return
        cols, rows = self.size
        at_end = self.pager.top >= len(self.pager.lines) - self.pager.body_rows(rows)
        self.pager.title = f"{agent.name} · {AGENT_LOG_KEYS}"
        self.pager.lines = self.roster.log_lines(agent.subagent_id, cols, self.theme, self.clock())
        if to_end or at_end:
            self.pager.top = len(self.pager.lines)  # past the end: the pager shows the last full page

    def _tail_due_at(self) -> float | None:
        """When `_ask_tail_when_due` may next send a call, on the app's clock; None while it sends none."""
        agent = self.roster.agents.get(self.log_agent) if self.pager is not None else None
        if agent is None or agent.status != RUNNING or not self.sid:
            return None
        if self.tail_misses.get(agent.subagent_id, 0) >= TAIL_MISSES_BEFORE_STOP:
            return None
        if self.tail_asked_at is None:
            return self.clock()
        return self.tail_asked_at + (TAIL_ANSWER_SECONDS if self.tail_open else TAIL_POLL_SECONDS)

    def _ask_tail_when_due(self) -> None:
        """`subagent.tail` for the agent whose log is open, while it runs: at most one call every `TAIL_POLL_SECONDS`.

        The pace is the view's, not each agent's: the first call goes out as
        a log opens unless one went out less than `TAIL_POLL_SECONDS` before,
        and moving to another agent does not bring the next call forward.
        None goes out while the last has had no answer for less than
        `TAIL_ANSWER_SECONDS`, for an agent that is not running, for one whose
        last `TAIL_MISSES_BEFORE_STOP` answers had no tail and that sent no
        frame since, or without a session.
        """
        agent = self.roster.agents.get(self.log_agent) if self.pager is not None else None
        if agent is None or agent.status != RUNNING or not self.sid:
            return
        if self.tail_misses.get(agent.subagent_id, 0) >= TAIL_MISSES_BEFORE_STOP:
            return
        now = self.clock()
        if self.tail_asked_at is not None:
            since = now - self.tail_asked_at
            if since < TAIL_POLL_SECONDS or (self.tail_open and since < TAIL_ANSWER_SECONDS):
                return
        # A call still out timed out: forgetting it drops its answer (`_on_response` ignores an id not in `pending`).
        self._forget_tail_calls()
        self.tail_asked_at, self.tail_open = now, True
        sid, subagent_id = self.sid, agent.subagent_id
        self._request(
            "subagent.tail",
            {"session_id": sid, "subagent_id": subagent_id},
            lambda result: self._on_tail(sid, subagent_id, result),
            lambda error: self._on_tail(sid, subagent_id, {}),  # the log keeps what the events gave it
        )

    def _clear_roster(self) -> None:
        """Drop the agents and every piece of tail bookkeeping and pending action that names them, and the view's
        hold (`_held_view_rows`). The open dag run's lanes stay (`_open_dag_nodes`): their children outlive the turn
        that sent them, and the tree's rows under each node read them."""
        viewed = self.roster.agents.get(self.viewing.subagent_id) if self.viewing is not None else None
        self.roster.clear(self._open_dag_nodes())
        if viewed is not None and viewed.subagent_id not in self.roster.agents:
            self.roster.agents[viewed.subagent_id] = viewed  # the agent on screen stays listed until it is left (NB2)
        self.view_hold = None
        self._drop_agent_actions()
        self._prune_child_drafts()

    def _prune_kept_lanes(self) -> None:
        """Drop the lanes a new turn kept for a dag run (`_clear_roster`) once a payload shows that run over (its
        graph one summary line, `panels.dag_run_summary`): the payload the turn read was a stale one. A payload that
        shows no run (no session, a graph that lingered out of the HUD, one the HUD could not read) shows nothing
        over, so nothing goes. Only that run's lanes go, its superseded ones included; another run's stay."""
        payload = self.hud.payload if self.hud is not None else None
        if not isinstance(payload, Mapping) or payload.get("error") or not graph_is_dag(payload):
            return
        graph = payload["delegation_graph"]
        if not dag_run_summary(graph):
            return
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        ids = (str(node.get("id")) for node in nodes if isinstance(node, Mapping))
        # By run, not by node: a kept lane whose node left the drawing (a superseded repair) belongs to the run too.
        runs = frozenset(node_id.rpartition(":")[0] for node_id in ids if node_id.startswith("d:"))
        self._forget_agents(self.roster.drop_kept(runs))

    def _brief_finished(self, agent: Agent) -> None:
        """Brief an agent its `subagent.complete` just finished in the transcript (`transcript.AgentDoneBlock`), with
        its time, its output tokens and what it said. A dag node's child is named by the node's role and id, as Claude
        Code names a teammate (`● build @notify finished`, the owner's pick of 2026-11-05): the role as the graph
        records it (none for a graph that records none), the id `@<id>` in a hue of its own, and the node's label on a
        row of its own under it (none when the label is empty or the id itself). Until the HUD's graph holds the node,
        the id is the one its goal's `[dag:<run>/<node>]` marker names (`Agent.dag_node`), with no role and its short
        title on the row under it. Any other agent is named by its short title, as the list names it, with no such
        row, no role and no `@`: Hermes' subagent frames carry no name to make a handle of (`subagents`). Held
        under what is live and written at the next block boundary (`Transcript.add_aside`), so it never splits a
        streaming reply or cuts off a running call."""
        payload = self.hud.payload if self.hud is not None else None
        handle = title = role = ""
        node_index: int | None = None
        if isinstance(payload, Mapping) and not payload.get("error") and graph_is_dag(payload):
            handle, title, role, node_index = bound_node(payload["delegation_graph"], self.roster, agent)
        if not handle and agent.dag_node:
            handle, title = agent.dag_node.rpartition(":")[2], short_title(agent.goal)
        if title.casefold() == handle.casefold():
            title = ""
        tokens = f"{TOKENS_MARK}{compact_count(agent.output_tokens)}" if agent.output_tokens else ""
        elapsed = agent.elapsed(self.clock())
        facts = tuple(fact for fact in (elapsed_text(elapsed) if elapsed >= 1 else "", tokens) if fact)  # no `0s`
        outcome = AGENT_OUTCOMES.get(agent.status, AGENT_FAILED)
        self.transcript.add_aside(AgentDoneBlock(handle or short_title(agent.goal) or agent.name, outcome, facts,
                                                 agent.reply, title=title, handle=bool(handle), role=role,
                                                 node_index=node_index))

    def _forget_agents(self, dropped: frozenset[str]) -> None:
        """Forget a pending `x`, a picked steer and the tail misses of the agents the roster just `dropped`."""
        if self.interrupt_armed in dropped:
            self.interrupt_armed = None
        if self.agent_steer in dropped:
            self.agent_steer = None
        for subagent_id in dropped:
            self.tail_misses.pop(subagent_id, None)
        self._prune_child_drafts()

    def _lose_roster(self) -> None:
        """The gateway exited: the agents stay listed as they were, those not finished marked interrupted, and every
        piece of tail bookkeeping and pending action that names them is dropped."""
        self.roster.lose_unfinished(self.clock())
        self._drop_agent_actions()

    def _drop_agent_actions(self) -> None:
        """Forget a pending `x`, a picked steer and the tail calls and timers: nothing may act on an agent now."""
        self.interrupt_armed = self.agent_steer = None
        self.tail_misses.clear()
        self._forget_tail_calls()  # an answer still on its way is for an agent the TUI no longer reads
        self.tail_asked_at, self.tail_open = None, False

    def _forget_tail_calls(self) -> None:
        """Drop the `subagent.tail` calls still waiting for an answer, here and in the client, so neither grows."""
        for request_id in [rid for rid, call in self.pending.items() if call.method == "subagent.tail"]:
            del self.pending[request_id]
            self.client.forget(request_id)

    def _on_tail(self, sid: str, subagent_id: str, result: Mapping[str, Any]) -> bool:
        """A `subagent.tail` answer: read only when Hermes has a tail, for an agent still running in this session.

        A tail that arrives after its agent finished would replace the reply
        its `subagent.complete` put in the log, so it is dropped. An answer
        without a tail (`available` anything but true, or an error) counts
        towards `TAIL_MISSES_BEFORE_STOP`. An answer to a call that timed out
        (`TAIL_ANSWER_SECONDS`) never reaches here: the call after it forgot it.
        """
        self.tail_open = False
        if result.get(contract.TAIL_AVAILABLE) is not True:
            self.tail_misses[subagent_id] = self.tail_misses.get(subagent_id, 0) + 1
            return True
        self.tail_misses.pop(subagent_id, None)
        agent = self.roster.agents.get(subagent_id)
        if sid == self.sid and agent is not None and agent.status == RUNNING:
            text, truncated = as_text(result.get(contract.TAIL_TEXT)), result.get(contract.TAIL_TRUNCATED) is True
            self.roster.ingest_tail(subagent_id, text, truncated)
        return True
