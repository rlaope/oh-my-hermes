"""`/dag`: the conversation's delegation graph as boxes, full screen in the pager, live and keyboard-driven.

The pager reads the HUD's newest payload at every frame (`payload`), so a
node that starts, finishes or fails while it is open is drawn as it changes.
When the newest payload holds no active graph (it settled and aged out, or
the HUD stopped reading), the last drawing stays, under a line saying it is
not live and how long ago its payload was read (`read_at`, the HUD's own read
time; failing that, when the pager first drew that payload), never how long
ago it was last redrawn.
It draws what `panels.dag_page_lines` draws (the boxes, Dependencies, Node
details) at its own `Focus`: the highlighted node, the folded ones and
whether Node details are shown. A running node's box takes the dag-ulw aura
where it moves (`aura`, the phase the app's tick stands at), so the page is
drawn again each tick while one runs. Nothing it does is sent anywhere: no key
here reaches the gateway, a child or a chat.

Keys: Tab / n the next box, Shift-Tab / p the one before, in reading order
(frontier by frontier, left to right); Space / Enter fold or unfold the
highlighted box; d Node details on or off; ↑↓ (j / k) a line, PageUp /
PageDown (b) a page, g / G either end; q / Esc leave. It opens on the first
running node, else the first box. A payload holds one conversation's graph,
so there is no other run to switch to and ↔ is not offered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import time
from typing import Any, ClassVar

from .keys import CHAR, END, ENTER, ESCAPE, HOME, PAGE_DOWN, PAGE_UP, TAB, Key, Paste, list_nav_step
from .pager import Pager
from .panels import dag_page_lines
from .style import TRUECOLOR, Line, Span
from .theme import Theme

DAG_KEYS = "Tab/n next  Shift-Tab/p prev  Space/Enter fold  d Details  ↑↓ Scroll  q Close"
RUNNING_STATES = ("running", "stuck")


def _no_payload() -> Any:
    return None


def _no_read_time() -> float | None:
    return None


def _no_aura() -> int | None:
    return None


@dataclass
class DagPager(Pager):
    FOOTER_ROWS: ClassVar[int] = 2

    lines: list[Line] = field(default_factory=list)
    payload: Callable[[], Any] = _no_payload
    read_at: Callable[[], float | None] = _no_read_time  # when the newest payload was read, on `clock`'s timeline
    depth: str = TRUECOLOR
    clock: Callable[[], float] = time.time
    aura: Callable[[], int | None] = _no_aura  # the dag-ulw aura's phase now, None where it does not move
    node: str = ""  # the highlighted box's node id; "" until the first frame picks one
    folded: frozenset[str] = frozenset()
    details: bool = True
    # The boxes of the last drawing, (node id, first line, last line) in reading order, and what it was drawn for.
    _boxes: tuple[tuple[str, int, int], ...] = field(default=(), init=False, repr=False, compare=False)
    _drawn: tuple[Any, ...] | None = field(default=None, init=False, repr=False, compare=False)
    # The last drawing of an active graph, when its payload was read, that payload, and the aura phase it was drawn
    # at: kept once the graph is gone.
    _live: tuple[list[Line], tuple[tuple[str, int, int], ...], float, Any, int | None] | None = field(
        default=None, init=False, repr=False, compare=False)
    _follow: bool = field(default=True, init=False, repr=False, compare=False)  # scroll to the highlight next frame

    def handle_key(self, event: Key | Paste, rows: int) -> bool:
        """One key; False when the person left. Moves the highlight, folds, switches Node details, or scrolls."""
        if not isinstance(event, Key):
            return True
        char = event.char if event.name == CHAR and not event.ctrl and not event.alt else ""
        if event.name == ESCAPE or char == "q":
            return False
        if (event.name == TAB and not event.shift) or char == "n":
            self._step(1)
        elif (event.name == TAB and event.shift) or char == "p":
            self._step(-1)
        elif event.name == ENTER or char == " ":
            if self.node:
                self.folded = self.folded ^ {self.node}
                self._follow = True
        elif char == "d":
            self.details = not self.details
        elif list_nav_step(event) == 1 or char == "j":
            self._scroll(1, rows)
        elif list_nav_step(event) == -1 or char == "k":
            self._scroll(-1, rows)
        elif event.name == PAGE_DOWN:
            self._scroll(self.body_rows(rows), rows)
        elif event.name == PAGE_UP or char == "b":
            self._scroll(-self.body_rows(rows), rows)
        elif event.name == HOME or char == "g":
            self._scroll_to_end(False, rows)
        elif event.name == END or char == "G":
            self._scroll_to_end(True, rows)
        return True

    def _step(self, step: int) -> None:
        order = [node_id for node_id, _top, _bottom in self._boxes]
        if not order:
            return
        at = order.index(self.node) if self.node in order else -step
        self.node = order[(at + step) % len(order)]
        self._follow = True

    def _page(self, cols: int, rows: int, theme: Theme) -> tuple[list[Line], str]:
        self._draw(cols, theme)
        if self._follow:
            self._follow = False
            box = next(((top, bottom) for node_id, top, bottom in self._boxes if node_id == self.node), None)
            if box is not None:
                body = self.body_rows(rows)
                if box[0] < self.top:
                    self.top = box[0]
                elif box[1] >= self.top + body:
                    self.top = min(box[0], box[1] - body + 1)
        return super()._page(cols, rows, theme)

    def _draw(self, cols: int, theme: Theme) -> None:
        """Draw the newest payload at this width and focus, unless the last frame already drew exactly that.

        A payload with no active graph (it settled and aged out while the
        pager was open, or the HUD stopped reading) leaves the last drawing on
        the screen, under a `not live` line.
        """
        from ..plugin_bundle.omh.delegation_view import Focus
        from ..plugin_bundle.omh.hud_text import elapsed_text

        payload = self.payload()
        # Only a running box takes the aura: a graph with none is drawn once, not every tick.
        phase = self.aura() if _running(payload) else None
        focus = (cols, theme, self.depth, self.node, self.folded, self.details, phase)
        if self._drawn is not None and self._drawn[0] is payload and self._drawn[1:] == focus:
            return
        drawn = dag_page_lines(payload, cols, theme, self.depth, Focus(self.node, self.folded, self.details), phase)
        if drawn is None:
            if self._live is not None:
                lines, boxes, read_at, last, painted = self._live
                still = None if painted is None else dag_page_lines(
                    last, cols, theme, self.depth, Focus(self.node, self.folded, self.details))
                if still is not None:  # nothing runs on a page that is not live: its boxes stand still
                    lines, boxes = still[0], tuple(still[1].boxes)
                    self._live = (lines, boxes, read_at, last, None)
                note = f"not live · last update {elapsed_text(self.clock() - read_at)} ago"
                self.lines = [(Span(note, theme.muted),), *lines]
                self._boxes = tuple((node_id, top + 1, bottom + 1) for node_id, top, bottom in boxes)
                self._drawn = None  # the note's age moves with the clock: drawn again every frame
            return
        lines, view = drawn
        boxes = tuple(view.boxes)
        ids = [node_id for node_id, _top, _bottom in boxes]
        if boxes and self.node not in ids:
            # The first frame, or the highlighted node left the graph: the first running node, else the first box.
            running = [node_id for node_id in ids if _state(payload, node_id) in RUNNING_STATES]
            self.node = (running or ids)[0]
            self._follow = True
            lines, view = dag_page_lines(payload, cols, theme, self.depth, Focus(self.node, self.folded, self.details),
                                         phase)
            boxes = tuple(view.boxes)
        self.lines, self._boxes = lines, boxes
        self._drawn = (payload, cols, theme, self.depth, self.node, self.folded, self.details, phase)
        # A redraw of the same payload (a key, a resize) keeps its read time: the note says how old the data is.
        if self._live is not None and self._live[3] is payload:
            read_at = self._live[2]
        else:
            stamp = self.read_at()
            read_at = stamp if isinstance(stamp, (int, float)) else self.clock()
        self._live = (lines, boxes, read_at, payload, phase)

    def footer(self, position: str, theme: Theme) -> list[Line]:
        """The keys, then the title and the rows the page shows."""
        return [(Span(f" {DAG_KEYS} ", theme.status),), (Span(f" {self.title} · rows {position} ", theme.status),)]


def _running(payload: Any) -> bool:
    graph = payload.get("delegation_graph") if isinstance(payload, Mapping) else None
    nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
    nodes = nodes if isinstance(nodes, list) else []
    return any(isinstance(node, Mapping) and node.get("state") == "running" for node in nodes)


def _state(payload: Any, node_id: str) -> str:
    graph = payload.get("delegation_graph") if isinstance(payload, Mapping) else None
    nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, Mapping) and node.get("id") == node_id:
            return str(node.get("state"))
    return ""
