"""Delegated work in a chat reply: once when a run starts, a count line while it runs, once when it ends.

OMH sends no message. Hermes calls `transform_llm_output` once per turn with
the reply it is about to deliver (`agent/turn_finalizer.py`), and a messaging
gateway delivers a transformed reply on purpose, editing the streamed message
to include what a plugin appended (`gateway/run_turn.py`). On a chat platform
(`MESSENGER_PLATFORMS`) this appends to that reply at three moments of a run,
the conversation's lanes that no end post has closed yet:

* **start**, once: a code block, ``DAG · <name> · <N> tasks · <W> layers``,
  then one line per layer listing its tasks' titles, at most `MOMENT_LINES`
  of them and then ``+N more``;
* **during**, no graph: on a turn where the counts changed since the last
  post, one plain line, ``DAG <name> · <done>/<total> done · <running>
  running``, and the failures with the first one's title when there are any
  (and the dag-ulw nodes accepted with their handoff not checked),
  unless the reply already has a line opening ``DAG <name> ·`` (a dag-ulw
  completion turn answers with the run's own status line). Nodes a dag run
  added since the last post (a repair, or an extend round) are named once at
  its end, ``+1 added (repair: Docs body)``, at most `ADDED_LABELS` of them
  and then ``+N more``; when the line with them does not fit, the line goes
  without them and they are named on a later one. Nodes added after the end
  post reopen the run: they get this line, not a second start block;
* **end**, once: a short block that puts each lane under Done, Failed or
  Stopped (and Working, only while one is in flight), names the lane that
  failed first, and gives the totals; a dag-ulw node accepted with its
  handoff not checked says so under Done and in the totals. It goes on the
  first reply after every lane has settled (for a dag-ulw run, once nothing
  in it is out or ready: done, cancelled, out of repair cycles, or left
  waiting on a repair the reply did not make), or, for a run a start
  opened, once nothing has been in flight and nothing has changed for
  `STALL_SECONDS` (a team part waiting on work that will not come). Such a
  ``stalled`` end lists the parts not moving under Stopped with their
  status, and leaves them out of the closed lanes, so a part that moves
  again opens a run of its own.

A run whose first reply finds it already settled (a synchronous call) gets the
end post alone. A conversation Hermes' rotating compaction moved to a new
session id mid-run goes on from the last post any of its segments recorded
(`conversation_posted`), so its run is not announced again. A chat reply
never carries the box drawing: the OMH TUI and `omh hud --graph` draw that.

Nothing is appended:

* with ``OMH_SUBAGENT_GRAPH=off`` in Hermes' environment, the switch that
  already turns the HUD's graphs off;
* on a delegated child's own turn (Hermes passes it as platform
  ``subagent``, which is no chat platform, and its session is not the
  conversation's root), with no active graph, or for a run no start opened
  that is not moving;
* when the graph's fingerprint (structure, states and labels, never elapsed
  time) equals the one the last post recorded, unless time alone has
  brought a stalled end, or a running run's counts did not change;
* unless the post can be recorded in the delegation ledger, so a ledger that
  cannot be written never turns into a post on every reply, and a restart
  does not post it again;
* when the reply ends inside an open code fence.

When the reply and a start or end block together pass the platform's
single-message cap (`MESSAGE_CAPS`, measured the way Hermes' adapter measures
it), the count line goes alone in its place. When even that does not fit,
nothing is appended: the skip is recorded in the ledger (`note_skipped`) and
the moment stays due, so a later reply that fits carries it. The reply's own
text is never changed: the post follows it (`appended`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import os
from pathlib import Path
import time
from typing import Any, Final

from . import runtime_paths
from .dag_run import ADDED_ORIGIN_KINDS, HANDOFF_NOT_CHECKED
from .delegation_graph import (
    GRAPH_LINGER_SECONDS,
    SETTLED_STATES,
    build_delegation_graph,
    dag_graph_name,
    dag_node_id,
    dag_origin,
    graph_fingerprint,
    graph_segments,
)
from .delegation_ledger import conversation_posted, note_posted, note_skipped, posted_record, root_session
from .delegation_view import UNICODE, UNTITLED, cells, clean_text, fit

MESSENGER_PLATFORMS: Final = frozenset({"discord", "slack", "telegram", "mattermost", "matrix"})
FENCE: Final = "```"
GRAPH_SWITCH: Final = "OMH_SUBAGENT_GRAPH"
MOMENT_LINES: Final = 8  # a start block's layer lines; past them, `+N more`
LINE_CELLS: Final = 72  # one listing line; titles that do not fit are counted as `+N`
LABEL_CELLS: Final = 28  # one title in a listing
STATUS_CELLS: Final = 20
# A team part's status words while its record says the attempt was sent (`delegation_graph._TEAM_VIEW`), and what an
# end post says for one with no child the ledger holds.
SENT_WORDS: Final = frozenset({"dispatched", "repair dispatched"})
UNSEEN_CHILD: Final = "sent, no child seen"
ADDED_LABELS: Final = 2  # the added nodes a count line names; past them, `+N more`
# One message's cap on each platform and the unit its Hermes adapter counts, at v0.22.2 (d923a5eb48) and on main
# (8b9ac5773e) alike, in plugins/platforms/<platform>/adapter.py: Discord's and Slack's MAX_MESSAGE_LENGTH (2,000;
# 39,000), Telegram's 4,096 counted by `utf16_len`, Mattermost's MAX_POST_LENGTH (4,000), and Matrix's
# DEFAULT_MAX_MESSAGE_LENGTH (45,000 // 3 UTF-8 bytes), which MATRIX_MAX_MESSAGE_LENGTH can lower to 500.
MESSAGE_CAPS: Final = {
    "discord": (2_000, "chars"),
    "slack": (39_000, "chars"),
    "telegram": (4_096, "utf16"),
    "mattermost": (4_000, "chars"),
    "matrix": (15_000, "utf8"),
}
MATRIX_CAP_ENV: Final = "MATRIX_MAX_MESSAGE_LENGTH"
# The share of a cap the reply and post may fill: the rest is left for the adapter's own formatting (Telegram's
# escapes, Matrix's HTML body), which adds to the text before it is measured.
CAP_SHARE: Final = 0.9
SKIPPED_CAP: Final = "graph_skipped_cap"
SKIPPED_OPEN_FENCE: Final = "graph_skipped_open_fence"
KNOWN_STATES: Final = frozenset({"done", "failed", "interrupted", "unknown", "running", "stuck", "dispatched", "waiting"})
# A run with nothing in flight that has not changed for this long is stalled: its end post goes out with what settled.
STALL_SECONDS: Final = GRAPH_LINGER_SECONDS
# The end post's groups, in the order it lists them, with the glyph each takes (`collapse` puts a lane in one).
COLLAPSE: Final = (("Done", "done"), ("Failed", "failed"), ("Stopped", "interrupted"), ("Working", "running"))


def appended(reply: str, post: str) -> str:
    """The message a reply becomes with the post after it; the reply's own text, trailing space included, unchanged."""
    return f"{reply}\n\n{post}"


def message_cap(platform: str) -> tuple[int, str]:
    """(cap, unit) for one platform's single message, Matrix's lowered by its environment setting as Hermes does."""
    cap, unit = MESSAGE_CAPS[platform]
    if platform == "matrix":
        try:
            cap = max(500, min(int(os.environ.get(MATRIX_CAP_ENV, "") or cap), cap))
        except ValueError:
            pass
    return cap, unit


def measured(text: str, unit: str) -> int:
    if unit == "utf16":
        return len(text.encode("utf-16-le")) // 2
    if unit == "utf8":
        return len(text.encode("utf-8"))
    return len(text)


def ends_in_open_fence(reply: str) -> bool:
    """Whether the reply leaves a code fence open, so a block after it would close the reply's own block instead."""
    return sum(1 for line in reply.splitlines() if line.lstrip().startswith(("```", "~~~"))) % 2 == 1


# ── what a post says ─────────────────────────────────────────────────────


def lane_key(name: str, node_id: str) -> str:
    """A lane's key in the ledger's closed list.

    A native child's node id names its subagent, which no other child shares,
    so it keeps its key when a team record later renames the graph. A team
    part's or fanout unit's id is unique only within its team or fanout, so the
    graph's name is part of its key.
    """
    scope = "" if node_id.startswith("s:") else name
    return hashlib.sha256(f"{scope}\0{node_id}".encode("utf-8")).hexdigest()[:16]


def graph_name(graph: Mapping[str, Any]) -> str:
    return clean_text(graph.get("name")) or "delegation"


def lanes_of(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The graph's lanes (every node but the root), in drawing order."""
    raw = graph.get("nodes")
    lanes = [
        node for node in (raw if isinstance(raw, list) else [])
        if isinstance(node, Mapping) and node.get("kind") != "root" and isinstance(node.get("id"), str)
    ]
    return sorted(lanes, key=lambda node: node.get("order") if isinstance(node.get("order"), int) else 0)


def _state(node: Mapping[str, Any]) -> str:
    """The node's state, or ``unknown`` for one the graph does not define."""
    state = node.get("state")
    return state if isinstance(state, str) and state in KNOWN_STATES else "unknown"


def collapse(node: Mapping[str, Any]) -> str:
    """The lane's group in an end post.

    Working is a lane in flight: running, stuck, or dispatched to a child
    Hermes recorded (`session_tail`), which settles on its own. Stopped is one
    that is not moving: interrupted, `unknown`, or a team part waiting or sent
    with no child the ledger holds.
    """
    state = _state(node)
    if state in ("done", "failed"):
        return state.capitalize()
    if state in ("running", "stuck") or (state == "dispatched" and node.get("session_tail")):
        return "Working"
    return "Stopped"


def _label(node: Mapping[str, Any], *, with_status: bool = False) -> str:
    """A lane's title, and, when asked, its status word: always for a Stopped lane, which says why it is not moving,
    and otherwise where the word says more than the state (``no model call``). A Stopped team part the team record
    says was sent reads `UNSEEN_CHILD`, never ``dispatched``, which would read as in flight."""
    title = fit(clean_text(node.get("title")) or UNTITLED, LABEL_CELLS)
    word = clean_text(node.get("status"))
    if word in SENT_WORDS and collapse(node) == "Stopped":
        word = UNSEEN_CHILD
    status = fit(word, STATUS_CELLS)
    shown = with_status and status and (status != _state(node) or collapse(node) == "Stopped")
    return f"{title} ({status})" if shown else title


def _ended_at(node: Mapping[str, Any]) -> float:
    value = node.get("ended_at")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float("inf")


def tally(lanes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The counts a count line and an end post give, and the title of the lane that failed first (by its stop time,
    then by drawing order)."""
    groups = [collapse(node) for node in lanes]
    failed = sorted((node for node in lanes if _state(node) == "failed"), key=_ended_at)
    return {
        "total": len(lanes),
        "done": groups.count("Done"),
        "running": sum(1 for node in lanes if _state(node) == "running"),
        "failed": len(failed),
        "stopped": groups.count("Stopped"),
        "working": groups.count("Working"),
        "settled": all(_state(node) in SETTLED_STATES for node in lanes),
        "first_failed": _label(failed[0]) if failed else "",
        "first_failure": _label(failed[0], with_status=True) if failed else "",
        "unchecked": sum(1 for node in lanes if node.get("handoff_checked") is False),
    }


def counts_key(counts: Mapping[str, Any]) -> str:
    return "/".join(str(counts[key]) for key in ("done", "total", "running", "failed", "first_failed"))


def count_line(name: str, counts: Mapping[str, Any]) -> str:
    """``DAG <name> · <done>/<total> done · <running> running``; when any failed, how many and the first; when a
    dag-ulw node was accepted with its handoff not checked, how many."""
    parts = [f"DAG {name}", f"{counts['done']}/{counts['total']} done", f"{counts['running']} running"]
    if counts["failed"]:
        parts.append(f"{counts['failed']} failed ({counts['first_failed']})")
    if counts["unchecked"]:
        parts.append(f"{counts['unchecked']} {HANDOFF_NOT_CHECKED}")
    return " · ".join(parts)


def added_kind(node: Mapping[str, Any]) -> str:
    """``repair`` or ``extend`` for a dag lane a run added after define (its ``dag_origin``), else ""."""
    kind = str(node.get("dag_origin") or "").partition(":")[0]
    return kind if kind in ADDED_ORIGIN_KINDS else ""


def added_clause(items: Sequence[tuple[str, str]]) -> str:
    """``+N added (repair: <title>, extend: <title>, +M more)``: (kind, title) pairs, at most `ADDED_LABELS` named.

    A kind is said once for the titles that follow it: ``extend: CSV export, CSV docs``.
    """
    if not items:
        return ""
    named: list[str] = []
    said = ""
    for kind, title in items[:ADDED_LABELS]:
        label = fit(clean_text(title) or UNTITLED, LABEL_CELLS)
        named.append(label if kind == said else f"{kind}: {label}")
        said = kind
    if len(items) > ADDED_LABELS:
        named.append(f"+{len(items) - ADDED_LABELS} more")
    return f"+{len(items)} added ({', '.join(named)})"


def dag_lane_key(record: Mapping[str, Any], node_id: str) -> str:
    """A dag node's lane key, as a post of its graph records it."""
    return lane_key(clean_text(dag_graph_name(record)) or "delegation", dag_node_id(str(record["run"]), node_id))


def shown_lanes(omh_home: Path, sessions: Sequence[str]) -> set[str] | None:
    """The lane keys the conversation's chat posts showed or closed, or None when it never had a chat post."""
    keys: set[str] | None = None
    for session in sessions:
        posted = posted_record(omh_home, session)
        if posted.get("fingerprint"):
            keys = (keys or set()) | set(posted.get("seen") or []) | set(posted.get("closed") or [])
    return keys


def dag_added_clause(
    record: Mapping[str, Any], derived: Mapping[str, Mapping[str, Any]], shown: set[str] | None
) -> str:
    """The clause `omh_dag` puts on a run's status line: the added nodes no chat post showed yet; "" off a chat.

    It names the nodes the next count line would name, so a reply that is
    the run's own status line says what the post would have said.
    """
    if shown is None:
        return ""
    return added_clause([
        (dag_origin(node)[0], str(node["label"])) for node in record["nodes"]
        if dag_origin(node)[0] and derived[str(node["id"])]["state"] != "superseded"
        and dag_lane_key(record, str(node["id"])) not in shown
    ])


def carries_count_line(reply: str, name: str) -> bool:
    """Whether the reply already has a line that opens like the count line, ``DAG <name> ·``."""
    lead = f"DAG {name} ·"
    return any(line.strip().startswith(lead) for line in reply.splitlines())


def _listing(lead: str, labels: Sequence[str]) -> str:
    """``lead`` and the labels joined by `` · `` within `LINE_CELLS`; the ones that do not fit are counted (``+2``)."""
    shown = lead
    for index, label in enumerate(labels):
        piece = label if index == 0 else f" · {label}"
        left = len(labels) - index - 1
        if index and cells(shown + piece) + (cells(f" +{left}") if left else 0) > LINE_CELLS:
            return f"{shown} +{len(labels) - index}"
        shown += piece
    return shown


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _fenced(lines: Sequence[str]) -> str:
    return "\n".join([FENCE, *lines, FENCE])


def start_block(graph: Mapping[str, Any], lanes: Sequence[Mapping[str, Any]]) -> str:
    """The run's start: its size, then one line per layer listing its tasks, at most `MOMENT_LINES` lines."""
    by_id = {str(node["id"]): node for node in lanes}
    layers = [
        [by_id[node_id] for node_id in layer if node_id in by_id]
        for layer in (graph.get("layers") if isinstance(graph.get("layers"), list) else [])
        if isinstance(layer, list)
    ]
    layers = [layer for layer in layers if layer]
    placed = {str(node["id"]) for layer in layers for node in layer}
    unplaced = [node for node in lanes if str(node["id"]) not in placed]
    if unplaced:  # a graph with no layering (a recorded cycle) lists those lanes on one line
        layers.append(unplaced)
    sep = UNICODE.separator
    lines = [sep.join(["DAG", graph_name(graph), _plural(len(lanes), "task"), _plural(len(layers), "layer")])]
    for number, layer in enumerate(layers[:MOMENT_LINES], start=1):
        lines.append(_listing(f"{number}  ", [_label(node) for node in layer]))
    hidden = sum(len(layer) for layer in layers[MOMENT_LINES:])
    if hidden:
        lines.append(f"+{hidden} more")
    return _fenced(lines)


def end_block(graph: Mapping[str, Any], lanes: Sequence[Mapping[str, Any]]) -> str:
    """The run's end: each lane under Done, Failed, Stopped or Working (`collapse`), the first failure, the totals.

    The header says ``ended`` when every lane settled, ``stalled`` when some
    are not moving and none is in flight, and ``so far`` while one is; a
    dag-ulw run's then says its goal verdict (`dag_run.goal_verdict`):
    ``verified``, ``unverified`` or ``verify_failed``, and for a run with goal
    criteria how many are met (``2/3 criteria met``).
    """
    counts = tally(lanes)
    sep = UNICODE.separator
    verdict = "ended" if counts["settled"] else ("so far" if counts["working"] else "stalled")
    goal = [text for text in (graph.get("dag_verdict"), graph.get("dag_criteria")) if isinstance(text, str) and text]
    lines = [sep.join(["DAG", graph_name(graph), verdict, *goal])]
    width = max(len(word) for word, _glyph in COLLAPSE)
    for word, glyph_state in COLLAPSE:
        members = [node for node in lanes if collapse(node) == word]
        if members:
            lead = f"{UNICODE.glyphs[glyph_state]} {word.ljust(width)}  "
            # A Done lane says its status only when its handoff was not checked (`dag_run.HANDOFF_NOT_CHECKED`).
            labels = [_label(node, with_status=word != "Done" or node.get("handoff_checked") is False)
                      for node in members]
            lines.append(_listing(lead, labels))
    if counts["first_failure"]:
        lines.append(f"first failure: {counts['first_failure']}")
    totals = [_plural(counts["total"], "task"), f"{counts['done']} done", f"{counts['failed']} failed",
              f"{counts['stopped']} stopped"]
    if counts["working"]:
        totals.append(f"{counts['working']} working")
    if counts["unchecked"]:  # said in the totals too, for a lane the listing counted as `+N`
        totals.append(f"{counts['unchecked']} {HANDOFF_NOT_CHECKED}")
    lines.append(sep.join(totals))
    return _fenced(lines)


# ── when a post is due ───────────────────────────────────────────────────


def messenger_snapshot(
    *, session_id: object, platform: object, model: object = "", reply: str = "", now: float | None = None
) -> str:
    """What to append to ``reply`` at this moment of the conversation's run, or "" when nothing is due or fits."""
    if not isinstance(platform, str) or platform.strip().lower() not in MESSENGER_PLATFORMS:
        return ""
    cap, unit = message_cap(platform.strip().lower())
    if os.environ.get(GRAPH_SWITCH, "").strip().lower() == "off":
        return ""  # the same switch that turns the HUD's graphs off
    if not isinstance(session_id, str) or not session_id.strip():
        return ""
    session = session_id.strip()
    moment = time.time() if now is None else now
    try:
        omh_home = runtime_paths.plugin_home(None)
        hermes_home = runtime_paths.plugin_home(None, hermes=True)
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError):
        return ""  # a host that cannot name this profile's homes gets no post, and the reply goes out as it is
    if root_session(session, hermes_home) != session:
        return ""  # a delegated child's own turn: its parent's reply carries the run
    # A conversation Hermes' rotating compaction moved to a new session id goes on from its earlier segment's post.
    segments = graph_segments(hermes_home, session)
    posted = conversation_posted(omh_home, segments)
    run_open = posted.get("phase") == "open"
    graph = build_delegation_graph(
        omh_home, hermes_home, session, now=moment, root_model=model if isinstance(model, str) else "",
        # A run a start post opened gets its end post however long it took to settle; any other settled graph
        # stops being news after the usual linger.
        linger=None if run_open else GRAPH_LINGER_SECONDS, segments=segments,
    )
    if graph.get("status") != "active":
        return ""
    name = graph_name(graph)
    closed = list(posted.get("closed") or [])
    seen = list(posted.get("seen") or [])
    every = lanes_of(graph)
    lanes = [node for node in every if lane_key(name, str(node["id"])) not in set(closed)]
    if not lanes:
        return ""
    run_keys = {lane_key(name, str(node["id"])) for node in every if node.get("dag_node")}
    if not run_open and graph.get("dag_open") and run_keys & set(closed) and all(added_kind(node) for node in lanes):
        # A repair or an extend round after the end post: the same run goes on, so it gets a count line naming
        # what was added, not a second start block, and its earlier lanes count in it again.
        seen += [key for key in closed if key in run_keys]
        closed = [key for key in closed if key not in run_keys]
        lanes = [node for node in every if lane_key(name, str(node["id"])) not in set(closed)]
        run_open = True
    added = [node for node in lanes if added_kind(node) and lane_key(name, str(node["id"])) not in set(seen)]
    keys = [lane_key(name, str(node["id"])) for node in lanes]
    counts = tally(lanes)
    changed_at = graph.get("changed_at")
    # Nothing in flight and no start, stop or team write for `STALL_SECONDS`: a team part that waits on a part that
    # will not come (or was sent with no child the ledger holds) would otherwise keep its run from ever ending.
    stalled = (not counts["working"] and isinstance(changed_at, (int, float))
               and moment - float(changed_at) > STALL_SECONDS)
    fingerprint = graph_fingerprint(graph)
    if fingerprint == posted.get("fingerprint") and not (run_open and stalled):
        return ""  # the graph the last post showed; only time can still bring a stalled end
    # A dag run is over when the run says so: a node whose child went quiet is still out, though its lane reads settled.
    ended = counts["settled"] and not graph.get("dag_open")
    if ended or (run_open and stalled):
        moment_name, block = "end", end_block(graph, lanes)
    elif stalled:
        return ""  # a run no start opened that is not moving is not news
    elif not run_open:
        moment_name, block = "start", start_block(graph, lanes)
    elif counts_key(counts) != posted.get("counts") or added:
        moment_name, block = "count", ""
    else:
        return ""
    if moment_name == "count" and carries_count_line(reply, name):
        # The reply already says where the run stands (a dag-ulw completion turn answers with its status line, which
        # names the added nodes as this line would): record it and add nothing, so the person reads one line, not two.
        note_posted(omh_home, session, fingerprint, moment_name=moment_name, phase="open",
                    counts=counts_key(counts), closed=closed, seen=list(dict.fromkeys(seen + keys)), now=moment)
        return ""
    if ends_in_open_fence(reply):
        note_skipped(omh_home, session, fingerprint, SKIPPED_OPEN_FENCE, now=moment)
        return ""
    line = count_line(name, counts)
    clause = added_clause([(added_kind(node), str(node.get("title") or "")) for node in added])
    candidates = [block] if block else ([f"{line} · {clause}"] if clause else [])
    post = next((text for text in [*candidates, line] if measured(appended(reply, text), unit) <= cap * CAP_SHARE), "")
    if not post:
        note_skipped(omh_home, session, fingerprint, SKIPPED_CAP, now=moment)
        return ""
    if post == line and clause:
        # The added nodes did not fit: the line goes without them, and a later line names them.
        keys = [key for key, node in zip(keys, lanes) if not added_kind(node) or key in set(seen)]
    if moment_name == "end":
        # A lane that settled is closed; one left not moving at a stalled end stays, so it opens a run if it moves.
        closed += [lane_key(name, str(node["id"])) for node in lanes if _state(node) in SETTLED_STATES]
    if not note_posted(
        omh_home, session, fingerprint, moment_name=moment_name, phase="closed" if moment_name == "end" else "open",
        counts=counts_key(counts), closed=closed, seen=list(dict.fromkeys(seen + keys)), now=moment,
    ):
        return ""
    return post
