"""How the last turn of each session ended, as this OMH home's TUIs saw it: what a resume reads to go on by itself.

Hermes keeps no cause for an interrupted turn: its `message.complete` says only
`interrupted`, and the placeholder row it stores is hidden from the history a
resume returns. So an interrupt Hermes made itself (a sleep past the turn's
lease) and the person's own Esc look the same from a stored session. The TUI
that saw the turn end knows which it was (`App._arm_auto_continue`), and writes
it here under the session's stored id:

* `TURN_OPEN`: a turn started and its end was not seen (the TUI quit or lost
  the gateway first);
* `TURN_STOPPED`: the person asked for the stop (Esc, `/stop`, a prompt in busy
  mode `interrupt`), written as they ask, so a TUI that quits before the end
  still says so;
* `TURN_INTERRUPTED`: Hermes interrupted a turn this TUI had submitted;
* `TURN_DONE`: anything else (a completed turn, an error, another client's).

Kept in `<omh_home>/tui/turn-ends.json`, the newest `MAX_SESSIONS` sessions.
Two TUIs writing at once keep the last writer's file, so a session can lose
its line; that only leaves it without a resume, never with one it should not
have, except that a lost `TURN_STOPPED` no longer holds back an open dag-ulw
run (`App._resume_evidence`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..system.local_store import atomic_write_json, read_json_object_result

TURN_ENDS_SCHEMA = "omh_tui_turn_ends/v1"
TURN_OPEN = "open"
TURN_STOPPED = "stopped"
TURN_INTERRUPTED = "interrupted"
TURN_DONE = "done"
TURN_ENDS = (TURN_OPEN, TURN_STOPPED, TURN_INTERRUPTED, TURN_DONE)
MAX_SESSIONS = 128


def turn_ends_path(omh_home: Path) -> Path:
    return Path(omh_home) / "tui" / "turn-ends.json"


def _entries(omh_home: Path) -> list[dict[str, Any]]:
    """The kept entries, oldest first (a list: the JSON writer sorts an object's keys, which would lose the order)."""
    record, _error = read_json_object_result(turn_ends_path(omh_home))
    if record is None or record.get("schema_version") != TURN_ENDS_SCHEMA:
        return []
    sessions = record.get("sessions")
    if not isinstance(sessions, list):
        return []
    return [entry for entry in sessions if isinstance(entry, dict) and isinstance(entry.get("id"), str)]


def read_turn_end(omh_home: Path, stored_id: str) -> str | None:
    """How `stored_id`'s last turn ended (one of `TURN_ENDS`); None when no TUI of this home wrote it."""
    if not stored_id:
        return None
    end = next((entry.get("end") for entry in reversed(_entries(omh_home)) if entry["id"] == stored_id), None)
    return end if end in TURN_ENDS else None


def record_turn_end(omh_home: Path, stored_id: str, end: str, at: float) -> bool:
    """Write `end` for `stored_id` as its newest entry; whether it was written (an unwritable home loses it)."""
    if not stored_id or end not in TURN_ENDS:
        return False
    kept = [entry for entry in _entries(omh_home) if entry["id"] != stored_id]
    kept = [*kept, {"id": stored_id, "end": end, "at": at}][-MAX_SESSIONS:]
    try:
        atomic_write_json(turn_ends_path(omh_home), {"schema_version": TURN_ENDS_SCHEMA, "sessions": kept})
    except OSError:
        return False
    return True
