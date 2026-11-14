"""What the model meant to say before a clarify question it asked without a word of reply.

A model sometimes writes the explanation that should precede a question only
into its reasoning, then calls `clarify` with no reply text at all. With
Hermes' `display.show_reasoning` off (Hermes sends no reasoning then), the
person sees a picker with nothing above it to say what it is about.

Hermes writes the turn's assistant row, tool call included, to `state.db`
before it runs any tool (`agent/turn_tool_round.py`), so by the time the
`clarify` request reaches the TUI that row is on disk. `read_silent_lead`
reads it, read-only: when the session's newest assistant row calls `clarify`,
carries no reply text and does carry reasoning, the reasoning is what the
picker shows, dim, above the question (`PromptSlot.silent_lead`). Any other
row, a missing store or a read that fails gives "" and the picker is drawn
as before.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from ..plugin_bundle.omh.sqlite_readonly import connect_readonly

STATE_DB = "state.db"
BUSY_SECONDS = 0.25  # a read that would wait longer on a writer gives up: the picker opens without the lead
CLARIFY_TOOL = "clarify"
LEAD_CHARS = 4000  # at most this much of the reasoning is kept; the picker shows three rows, Ctrl+O the rest


def read_silent_lead(hermes_home: str, session_id: str, call_id: str) -> str:
    """The reasoning of the session's newest assistant row when that row made the `clarify` call `call_id` (the
    `tool.start` id of the question being opened) with no reply text; "" otherwise, and for no home, no session, no
    call id, no store or a read that fails. Matching the call id keeps an older turn's reasoning off a question
    whose own row is not on disk."""
    if not hermes_home or not session_id or not call_id:
        return ""
    path = Path(hermes_home) / STATE_DB
    try:
        if not path.is_file():
            return ""
        connection = connect_readonly(path, timeout=BUSY_SECONDS, immutable=_no_connection_open(path))
    except (OSError, ValueError, sqlite3.Error):
        return ""
    try:
        row = connection.execute(
            "SELECT content, reasoning, tool_calls FROM messages WHERE session_id = ? AND role = 'assistant'"
            " ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        connection.close()
    if row is None:
        return ""
    content, reasoning, tool_calls = row
    if (isinstance(content, str) and content.strip()) or not isinstance(reasoning, str) or not reasoning.strip():
        return ""
    if (CLARIFY_TOOL, call_id) not in _called(tool_calls):
        return ""
    return reasoning.strip()[:LEAD_CHARS]


def _no_connection_open(path: Path) -> bool:
    """Whether no connection has the WAL store at `path` open (no `-wal`, `-shm` or `-journal` beside it), so it is
    opened immutable and a `mode=ro` open leaves no `-wal` or `-shm` behind (`bot_board._no_connection_open`)."""
    try:
        return not any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    except OSError:
        return False


def _called(tool_calls: object) -> set[tuple[str, str]]:
    """The (tool name, call id) pairs a stored `tool_calls` column names (OpenAI's `[{"id": ..., "function": {"name":
    ...}}]`, with Hermes' `call_id` beside `id`), each id the row carries."""
    if not isinstance(tool_calls, str) or not tool_calls:
        return set()
    try:
        calls = json.loads(tool_calls)
    except ValueError:
        return set()
    found: set[tuple[str, str]] = set()
    for call in calls if isinstance(calls, list) else ():
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str):
            found.update((name, ident) for key in ("id", "call_id") if isinstance(ident := call.get(key), str) and ident)
    return found
