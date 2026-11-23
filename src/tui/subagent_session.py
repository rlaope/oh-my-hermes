"""One subagent's session on the OMH TUI's main screen, as Claude Code shows a teammate's: the state and pure helpers.

Enter on an agent's row (the agent list, a click on it, a dag tree node with a
child) shows that subagent's own session where main's transcript stands: a dim
`› From main` row, its brief as the first prompt, its tool rows, its reply and,
while it runs, its own working row. The composer's top rule ends with its
name and the placeholder says `Message @<name>…`; what is sent there goes to
that subagent. Esc, or the list's `main` row and Enter, goes back to main,
whose transcript kept folding every main event meanwhile.

How the session is read depends on the wire the TUI is on (`App.shared_gateway`):

- stdio (Hermes' own `tui_gateway.entry`): `session.resume {session_id:
  <child_session_id>, lazy: true}` answers the child's history and a live,
  agent-less watch session; Hermes mirrors the child's `message.*` and
  `tool.*` events onto that watch sid. Once the child ended, `prompt.submit`
  on the watch sid continues its own conversation (4009 while it runs).
- attached (the shared gateway): `session.transcript {session_id: <parent>,
  subagent_id, order: "oldest", limit, cursor?}` answers rows and a cursor,
  polled forward at most every `POLL_SECONDS` while the view is open and the
  child runs. That owner cannot continue a finished child: a message then says
  so in one dim row and stays in the composer.

A plain (non-lazy) `session.resume` of a child is never sent: on the shared
gateway it mounts the child read-only and moves the attach adapter's current
session. A read that is refused (any error, `available: false`, no
`child_session_id`) leaves the view closed and the agent's log opens in the
pager instead, as before.

Pure state and helpers: nothing here sends a call; `App` does
(`AgentViewMixin._open_agent`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import gateway_contract as contract
from .composer import Composer
from .style import Line, Span
from .theme import Theme
from .transcript import Transcript

WIRE_WATCH = "lazy-watch"  # stdio: a lazy resume's watch sid carries the child's mirrored events
WIRE_POLL = "transcript-poll"  # attached: `session.transcript` rows, polled forward from a cursor

FROM_MAIN = "› From main"  # the dim row over the brief: who gave the subagent its task
PLACEHOLDER = "Message @{name}…"
VIEWED_MARK = "⏺"  # the agent list's row for the subagent on screen
AWAY_MARK = "◯"  # every other row, `main` included, while a subagent is on screen
UNSUPPORTED_LINE = "{name} finished · continuing it is not supported by this Hermes"
REFUSED_WHILE_VIEWING = (
    "Slash commands, ! lines and images go to main, not to {name}: Esc goes back to main. Your text is kept."
)
STILL_RUNNING = "{name} is still running; your text is back in the composer."
CONTINUE_REFUSED = "Hermes did not continue {name}: {reason}. Your text is back in the composer."
VIEW_REFUSED_ARMED = "A rewind or a tell is armed: send or cancel it (Esc) before opening a subagent's session."
VIEW_TEXT_DROPPED = "{name} is no longer listed; what was sent to it did not go: {text}"
REFUSED_FOR_STEER = "Slash commands, ! lines and images cannot be a steer for {name}. Your text is kept."
READ_GAVE_UP = "Could not read the rest of {name}'s transcript."
VIEW_TEXT_KEPT = "{name}'s session was left before this could go; it is kept in {name}'s composer."
TELL_CHILD_LEFT = "That subagent's session is no longer on screen; what you would tell it is back in the composer."

POLL_SECONDS = 1.0  # the most often a running child's transcript is read while it is on screen
POLL_ANSWER_SECONDS = 10.0  # a poll with no answer this long is forgotten and no longer holds the next one back
READ_LIMIT = 200  # rows a transcript read asks for at once
CATCH_UP_PAGES = 50  # reads sent once the child ended (answered, refused or unanswered), until an empty page
SENT_STEERS_CAP = 64  # steers sent from an attached view awaiting their stored rows; the oldest goes first

# What Enter does with a line typed in the view (`send_kind`).
SEND_STEER = "steer"  # the child runs: `subagent.steer` on the parent session
SEND_WATCH_STEER = "watch-steer"  # a continued turn runs on the watch sid: `session.steer` there
SEND_CONTINUE = "continue"  # it ended, stdio: `prompt.submit` on the watch sid
SEND_UNSUPPORTED = "unsupported"  # it ended, attached: the dim line, the text kept

MESSAGE_ROW_KINDS = ("", "message")  # transcript rows that are messages (`row_kind`); others are not drawn

# Where a submit goes, decided once at Enter (`AgentViewMixin._submit_dest`): main, the view on screen (by agent id)
# or the agent `s` picked; a held submit keeps it. The owner of a draft, an intake or a held submit is "" for main,
# else the agent id of the view whose composer it was typed in.
DEST_MAIN = ("main", "")
DEST_VIEW = "view"
DEST_STEER = "steer"


@dataclass
class SubagentView:
    """The subagent on the main screen: its id, the name the composer says, how it is read, and its own transcript.

    `parent_sid` is the live session it belongs to: an answer or an event for a view opened in a session since
    left is dropped. `running` is the child's own run (the read's `running`, a `subagent.complete`); `turn_running`
    a turn continued on the watch sid (stdio). `brief_pending`: the goal was drawn as the brief because the read had
    no user row yet, so the first user row a later read brings is that brief and is not drawn again. `sent_steers`
    are the texts steered from here whose stored rows a later read brings back (drawn once, as the steer row).
    `main_draft` is main's composer (text, chips, images, caret) as it stood when the view was shown: the composer
    on screen is the view's own until the view is left, when main's comes back exactly."""

    subagent_id: str
    name: str
    parent_sid: str
    wire: str
    transcript: Transcript
    watch_sid: str = ""
    cursor: str = ""
    running: bool = False
    turn_running: bool = False
    polled_at: float | None = None
    poll_open: bool = False
    brief_pending: bool = False
    sent_steers: list[str] = field(default_factory=list)
    main_draft: Composer | None = None
    # The attached read's fence: the latest read's number and the request id it went as; only that read's answer,
    # asked from the cursor the view still holds, applies. `pages_left`: catch-up pages still allowed once the child
    # ended; `read_now`: the next page goes at once (the last page brought rows). `brief_block`: the goal drawn as
    # the brief until the real brief row replaces it in place.
    read_seq: int = 0
    read_id: int | None = None
    pages_left: int = 0
    read_now: bool = False
    brief_block: Any = None
    # `ended_seq`: the latest read sent when the end was seen; a read up to it never counts as caught up.
    # `gave_up`: the post-end budget ran out before an empty page (one dim line said so).
    ended_seq: int = 0
    gave_up: bool = False


def wire_for(shared_gateway: bool) -> str:
    """The wire a view reads: the transcript poll on the shared gateway, the lazy watch on Hermes' stdio entry."""
    return WIRE_POLL if shared_gateway else WIRE_WATCH


def open_call(wire: str, parent_sid: str, subagent_id: str, child_session_id: str, cols: int) -> tuple[str, dict]:
    """The call that opens a view on `wire`: never a plain resume of the child."""
    if wire == WIRE_WATCH:
        return "session.resume", {"session_id": child_session_id, "lazy": True, "cols": cols}
    return "session.transcript", read_params(parent_sid, subagent_id, "")


def read_params(parent_sid: str, subagent_id: str, cursor: str) -> dict[str, Any]:
    """`session.transcript` for one subagent's rows, oldest first, from `cursor` ("" for the first page)."""
    params: dict[str, Any] = {"session_id": parent_sid, "subagent_id": subagent_id, "order": "oldest",
                              "limit": READ_LIMIT}
    if cursor:
        params["cursor"] = cursor
    return params


def read_refused(wire: str, result: Mapping[str, Any]) -> bool:
    """Whether an open's answer gives no view: a transcript read that says `available` is not true or names no
    child session, or a lazy resume that names no watch sid."""
    if wire == WIRE_WATCH:
        return not isinstance(result.get("session_id"), str) or not result.get("session_id")
    return result.get(contract.TRANSCRIPT_AVAILABLE) is not True or not result.get("child_session_id")


def message_rows(rows: object) -> list[dict[str, Any]]:
    """The rows of a read (a resume's `messages`, a transcript's `rows`) that `App._draw_history` draws."""
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("row_kind", "") in MESSAGE_ROW_KINDS]


def unseen_rows(view: SubagentView, rows: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """`rows` less those already on screen in another form, and the real brief's text when it is among them: the
    brief the view drew from the goal (its row replaces that placeholder in place, `brief_pending`), and a steer sent
    from the view, whose row it drew as it went."""
    kept: list[dict[str, Any]] = []
    brief: str | None = None
    for row in rows:
        role, text = row.get("role"), row.get("text") if isinstance(row.get("text"), str) else ""
        if role == "user" and view.brief_pending and row.get("display_kind") != "steer":
            view.brief_pending = False
            brief = text
            continue
        if role == "user" and row.get("display_kind") == "steer" and text in view.sent_steers:
            view.sent_steers.remove(text)
            continue
        kept.append(row)
    return kept, brief


def has_brief(rows: Sequence[dict[str, Any]]) -> bool:
    """Whether `rows` hold the brief: a user row that is no steer."""
    return any(row.get("role") == "user" and row.get("display_kind") != "steer" for row in rows)


def send_kind(view: SubagentView) -> str:
    """What Enter does with a line typed in `view`: a steer while the child (or a turn continued on its watch sid)
    runs; once it ended, a continue on the stdio wire and the unsupported line on the shared gateway."""
    if view.turn_running:
        return SEND_WATCH_STEER
    if view.running:
        return SEND_STEER
    return SEND_CONTINUE if view.wire == WIRE_WATCH and view.watch_sid else SEND_UNSUPPORTED


def poll_due_at(view: SubagentView | None, now: float) -> float | None:
    """When the next transcript read may go (or the one out is forgotten), on the app's clock; None while none goes
    (no view, the watch wire, or a child that no longer runs whose post-end reads are over and none is out). One
    read at a time: while one is out, the next waits for its answer or `POLL_ANSWER_SECONDS`; else at most one
    every `POLL_SECONDS`, but a catch-up page right after a page that brought rows (`read_now`)."""
    if view is None or view.wire != WIRE_POLL or not (view.running or view.pages_left > 0 or view.poll_open):
        return None
    if view.poll_open and view.polled_at is not None:
        return view.polled_at + POLL_ANSWER_SECONDS
    if view.polled_at is None or view.read_now:
        return now
    return view.polled_at + POLL_SECONDS


def caught_up(result: Mapping[str, Any]) -> bool:
    """Whether a transcript answer is the host's caught-up mark: its wire `rows` list is empty, judged before any
    filtering for display (a page of only a handoff or other non-message row is not empty)."""
    rows = result.get(contract.TRANSCRIPT_ROWS)
    return isinstance(rows, list) and not rows


def page_read(view: SubagentView, counts: bool, empty: bool) -> bool:
    """After a page was applied: once the child ended, the next page goes at once until a page that `counts` (a read
    sent after the end was seen) is `empty` (caught up), while post-end reads are left (`pages_left`, spent as each
    one is sent). A read sent before the end never counts as caught up: a read after it always goes. True once
    caught up, and while the child runs (nothing to catch up yet)."""
    if view.running:
        view.read_now = False
        return True
    if counts and empty:
        view.pages_left, view.read_now = 0, False
        return True
    view.read_now = view.pages_left > 0
    return False


def child_ended(view: SubagentView, after: int) -> None:
    """The child's run ended (a `subagent.complete`, a read saying it no longer runs): `running` only ever goes
    from true to false, and the post-end reads start counting; only reads numbered past `after` may say caught up."""
    if view.running:
        view.running = False
        view.pages_left = CATCH_UP_PAGES
        view.ended_seq = after


def rule_label(name: str) -> str:
    """The name the composer's top rule ends with."""
    return " ".join(name.split())


def mark_rows(
    lines: Sequence[Line], ids: Sequence[str], viewing: str, selected: str | None, theme: Theme,
) -> list[Line]:
    """The agent list's rows while `viewing` is on screen: its row marked `VIEWED_MARK` and led by the list's pointer,
    as Claude Code marks the teammate shown; every other row, `main` included, `AWAY_MARK`.

    `selected` is the list's highlighted row while it has the keys (its bar stays); with the list closed the rows
    were drawn with `viewing` highlighted to keep it in sight, and that row loses the bar here. A row drawn in a
    shape this does not know (cut to a few cells) is left as it is."""
    marked: list[Line] = []
    for line, row_id in zip(lines, ids):
        glyph, style = (VIEWED_MARK, theme.running) if row_id == viewing else (AWAY_MARK, theme.muted)
        if len(line) == 1 and len(line[0].text) > 3:  # the highlighted row: one span, `❯ ` and its mark first
            text = line[0].text
            if row_id == selected:
                marked.append((Span(text[:2] + glyph + text[3:], line[0].style),))
            else:
                marked.append((Span(text[:2]), Span(glyph, style), Span(text[3:], theme.text)))
        elif len(line) >= 2 and len(line[1].text) == 1:
            marked.append((line[0], Span(glyph, style), *line[2:]))
        else:
            marked.append(line)
    return marked
