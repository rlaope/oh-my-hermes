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
then; a key it does not bind does nothing. Enter or a click opens one
agent's log in the pager. In a dag run Down gives the keys to the tree
instead (`_tree_key`): its rows fold and unfold, and Enter, `x` and `s` act
on the highlighted node's child as the list's keys do. The log is
read-only: `subagent.tail` is asked for the open agent while it runs, at most
every `TAIL_POLL_SECONDS`, and no more once `TAIL_MISSES_BEFORE_STOP` answers
in a row had no tail, until that agent sends a frame; nothing is ever sent to
a subagent. On the main screen, mouse reports are on only while the agent list (or the dag
tree) has the keys and the row a click would land on is certain (the owner's decision of 2026-10-14:
during a turn the wheel scrolls and a drag selects, and Down opens the list
from the keyboard); a pager, an agent's log among them, takes them for its
own wheel and drag (`pager`). A plain left click on a list row opens that agent's log,
or on the list's main row leaves the list; on a tree row it takes the
highlight, and on a node's row opens its child's log; every other report
does nothing. Reports the terminal sent before it acted on an off
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
from .keys import BUTTON_LEFT, CHAR, DOWN, ENTER, ESCAPE, LEFT, RIGHT, UP, Key, Mouse, Paste
from .layout import Budget, agent_view_cap, is_tiny, max_height
from .dag_tree import TreeState, run_key, tree_lines
from .panels import (
    RUNNING_NODE_STATES, agent_view_count, agent_view_keep, dag_run_summary, graph_is_dag, panel_lines,
)
from .style import Line, Span, Style
from .subagents import FINISHED_STATUSES, MAIN_ID, OPEN_MARK, RUNNING, Hit
from .width import cell_width
from .transcript import NOTICE_WARN, STEER_QUEUED, STEER_REFUSED, NoticeBlock, SteerBlock, as_text

# The list Down opens (the agent view's rows, `layout.agent_view_cap` of them; a longer roster scrolls), and one
# agent's log in the pager.
CHIP_SEPARATOR = " · "  # between the agent count and what Down opens, on the info line
# Its keys, on the info line while it is open, longest first: each keeps the two action keys and the way back.
AGENT_LIST_HINT = "↑↓ select · ⏎ log · x interrupt · s steer · esc back"
AGENT_LIST_HINTS = (AGENT_LIST_HINT, "⏎ log · x interrupt · s steer · esc back", "x interrupt · s steer · esc back")
# The dag tree's keys, the same way: each keeps the fold keys, the two action keys and the way back while it fits.
TREE_HINT = "↑↓ select · ←/→ or space fold · ⏎ log · x interrupt · s steer · esc back"
TREE_HINTS = (
    TREE_HINT, "←/→ fold · ⏎ log · x interrupt · s steer · esc back", "←/→ fold · x interrupt · s steer · esc back",
    "←/→ fold · esc back",
)
# The fewest rows a tree takes the keys in: its highlight between a count above and one below. Under it Down opens the
# agent list in the view's rows, as it did before the tree.
MIN_TREE_ROWS = 3
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
        tree (`_tree_view`) is the view, in up to a third of the screen from
        the start and no more rows than the tree has (the owner wants the
        graph in sight while it runs); Down gives the tree the keys. A run
        that is over leaves the view as its turn ends (`_run_gone`): its end
        print in the transcript holds its final graph. Otherwise the roster's
        rows while it holds agents, else the HUD's agents block and the tree,
        each in `layout.agent_view_cap`.
        """
        self.listed = ()
        self.tree_state = None
        if not self._busy():
            self.tree_hold = 0  # whatever the view draws between turns, the next turn's tree starts from its own rows
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
            cap = self._view_cap(rows, cols, rows // 3, room)
            lines = self._tree_view(payload, cols, cap)
            lines += [()] * self._tree_held_rows(len(lines), cap, rows)
            if self.list_selected is None:
                return lines
            listed, self.listed = self.roster.list_lines(cols, self.theme, self.list_selected, frame, len(lines), now)
            return listed + [()] * (len(lines) - len(listed))
        self.tree_selected = None  # no tree is drawn to hold the keys
        if self.roster.agents:
            running = self.roster.running_count()
            cap = self._view_cap(rows, cols, 1 + running + int(len(self.roster.agents) > running), room)
            if self.list_selected is not None:
                lines, self.listed = self.roster.list_lines(cols, self.theme, self.list_selected, frame, cap, now)
                return lines
            return self.roster.view_lines(cols, self.theme, frame, cap, now)
        if not valid:
            return []
        return self._hud_view(payload, cols, self._view_cap(rows, cols, agent_view_keep(payload, cols), room))

    def _tree_held_rows(self, drawn: int, cap: int, rows: int) -> int:
        """Blank rows under a tree that shrank while the turn runs on the screen's bottom rows: the tree keeps the
        most rows it took this turn (in `cap`), so a layer that shuts mid-run leaves its rows under the tree, not as
        a blank band between the transcript and the working row (rows the content gives up stay, `layout`). The
        hold ends with the turn (`_agent_view`, whatever the view then draws), at the next prompt and on a session
        change (`_clear_roster`), and above the bottom rows, where the composer follows the content; it never passes
        `cap`, which a taller composer or a slot can lower mid-turn."""
        if not self._busy() or self.region.last_row(rows) != rows - 1:
            self.tree_hold = 0
            return 0
        self.tree_hold = max(self.tree_hold, drawn)
        return max(min(self.tree_hold, cap) - drawn, 0)

    def _run_gone(self, graph: Mapping[str, Any]) -> bool:
        """Whether the view no longer draws `graph`'s dag run (the owner, 2026-10-26: a finished run stayed under the
        composer until the next prompt). It is over (`panels.dag_run_summary`) and no turn runs, or it was retired
        (`_retire_finished_run`) and has not moved since: a payload older than the end print that retired it still
        shows a lane running, and a later turn reads the same run over. A run whose every lane settled mid-turn
        keeps its tree (each layer shut) until the turn ends: on the screen's bottom rows a view that shrank there
        left its rows blank between the transcript and the working row, as rows the content gives up stay
        (`layout`), and at the turn's end the run's end print and the turn's summary line fill them. A run an
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
        The rows its tree took in the last frame are noted in `tree_freed` (`App._render` keeps them, blank, under the
        info line until output fills them)."""
        key, changed = run_key(graph), _changed_at(graph)
        if self.retired_run is None or self.retired_run[0] != key or changed > self.retired_run[1]:
            self.tree_freed = self.frame_budget.agents if self.frame_budget is not None else 0
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

        def draw() -> tuple[list[Line], TreeState]:
            return tree_lines(graph, self.roster, cols, cap, self.theme, frame, folds, self.tree_selected,
                              self.color_depth, now, self._aura_phase())

        lines, self.tree_state = draw()
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
        if self.tree_selected is None and name != DOWN:
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
        if name in (UP, DOWN):
            at = state.order.index(key) + (-1 if name == UP else 1)
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
                self._open_agent_log(agent)
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
        the keys), and ask for mouse reports only while one of them is open.

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
        self._set_mouse(bool(self.clickable) and self.region.last_row(rows) is not None)

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
            if name != DOWN or self.composer.text or self._menu_rows() or not self._list_available():
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
        elif name in (UP, DOWN):
            ids = self.roster.ids()
            row = ids.index(self.list_selected) + (-1 if name == UP else 1)
            self.list_selected = ids[min(max(row, 0), len(ids) - 1)]
        elif name == ENTER and self.list_selected != MAIN_ID:
            self._open_agent_log(self.list_selected)  # over the list: leaving the log comes back to it
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

    def _steer_agent(self, text: str) -> None:
        """Send `text`, the line the person typed after `s`, to the agent they picked; back to the composer if it cannot go."""
        subagent_id, self.agent_steer = self.agent_steer, None
        agent = self.roster.agents.get(subagent_id or "")
        if agent is None or agent.status in FINISHED_STATUSES or not self.sid:
            name = agent.name if agent is not None else "That agent"
            self.transcript.add_aside(NoticeBlock(AGENT_FINISHED_NOTICE.format(name=name, action="steer"), NOTICE_WARN))
            self._set_composer(text)
            return
        block = self.transcript.add_steer(text, agent=agent.name)  # held under what runs, as the main steer is
        sid, session = self.sid, self.stored_id or self.sid
        self._request(
            "subagent.steer",
            {"session_id": sid, "subagent_id": agent.subagent_id, "text": text},
            lambda result: self._on_agent_steered(sid, session, block, result),
            lambda error: self._on_agent_steered(sid, session, block, {}, as_text(error.get("message")).strip().rstrip(".")),
            lambda seconds: self._on_agent_steer_unanswered(sid, session, block, seconds),  # given back, never resent
            steer=block,
        )

    def _on_agent_steered(
        self, sid: str, session: str, block: SteerBlock, result: Mapping[str, Any], reason: str = ""
    ) -> bool:
        """Hermes' answer to an agent steer: taken, or refused (with `reason` when Hermes gave one) and given back.

        Settled after `sid`, the session it went to, was left (named `session`), whatever the answer, its text
        comes back with a notice saying so, as the main steer's does.
        """
        if sid != self.sid:
            self._steer_back(block.text, AGENT_STEER_LEFT_NOTICE.format(name=block.agent, session=session))
            return True
        if as_text(result.get("status")) == contract.STEER_QUEUED:
            self.transcript.steer_answered(block, STEER_QUEUED)
        else:
            said = AGENT_STEER_REFUSED_BECAUSE.format(reason=reason) if reason else AGENT_STEER_REFUSED
            self.transcript.steer_answered(block, STEER_REFUSED, said)
            self._give_back(block.text)
        return True

    def _on_mouse(self, event: Mouse) -> None:
        """A plain left press on an agent's row of the list opens that agent's log, and on a dag tree row moves the
        highlight there and opens the node's child's log if it has one; nothing else does anything.

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
            return
        above, column = last - (event.y - 1), event.x - 1 - self._margin()  # a report counts from 1
        target = next((hit.subagent_id for hit in self.clickable.get(above, ()) if hit.start <= column < hit.end), None)
        if target is None:
            return
        if self.tree_selected is not None:  # a dag tree row: it takes the highlight, and a node's child its log opens
            if not target:
                return  # a count or blank row selects nothing
            self.tree_selected = target
            agent = self.tree_state.agents.get(target) if self.tree_state is not None else None
            if agent is not None:
                self._open_agent_log(agent)
            return
        if self.list_selected is not None:
            self.list_selected = target if target != MAIN_ID else None  # main has no log: the click leaves the list
        if target != MAIN_ID:
            self._open_agent_log(target)

    def _open_agent_log(self, subagent_id: str) -> None:
        """One agent's log on the alternate screen, opened at its newest rows; nothing for an agent no longer held."""
        if subagent_id not in self.roster.agents:
            return
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
        holds (`_held_view_rows`, `_tree_held_rows`). The open dag run's lanes stay (`_open_dag_nodes`): their children outlive the turn
        that sent them, and the tree's rows under each node read them."""
        self.roster.clear(self._open_dag_nodes())
        self.view_hold = None
        self.tree_hold = 0
        self._drop_agent_actions()

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

    def _forget_agents(self, dropped: frozenset[str]) -> None:
        """Forget a pending `x`, a picked steer and the tail misses of the agents the roster just `dropped`."""
        if self.interrupt_armed in dropped:
            self.interrupt_armed = None
        if self.agent_steer in dropped:
            self.agent_steer = None
        for subagent_id in dropped:
            self.tail_misses.pop(subagent_id, None)

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
