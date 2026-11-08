"""Name the Hermes session that closed when OMH's own TUI launch exited.

Bare ``omh`` runs the user's ``hermes`` as a child (``commands/bare_launch.py``,
``_launch_hermes_tui``), so control returns to this process when the TUI
exits. Hermes prints its own epilogue first and that epilogue names the other
binary -- ``hermes --tui --resume <id>`` -- so someone who came in through
``omh`` is told to come back through ``hermes``.

OMH cannot read the id Hermes used for that epilogue. Hermes creates
``HERMES_TUI_ACTIVE_SESSION_FILE`` itself with ``mkstemp`` and unlinks it in a
``finally`` before returning (``hermes_cli/main_tui_launch.py``), so by the
time this process runs the file is gone. The id is recovered instead from the
state database the TUI just wrote to: the TUI gateway calls
``db.end_session()`` on exit when it owns the session's lifecycle
(``tui_gateway/session_lifecycle.py``), which stamps ``sessions.ended_at`` as
the child exits.

A gateway-originated session, or one another backend holds a lease on, is
deliberately never ended there. It therefore produces no candidate here and
no line, which is the right outcome rather than a gap: OMH would have no way
to tell which of several live sessions the person was looking at.

That recovery is the fallback. The OMH TUI writes the session it has open
into a file of OMH's own (``tui/launch.py``, ``SESSION_FILE_ENV``), which
``omh`` reads before removing it; only when that file names nothing (Hermes'
own TUI opened instead, or the OMH TUI never got a session) does the
``ended_at`` timing above choose. The timing cannot name a resumed session the
person sent nothing in: Hermes mounts a resumed session read-only and leaves
its old ``ended_at`` as it was until a prompt reopens it
(``tui_gateway/methods_prompt.py``, ``_reopen_if_finalized``), so the row
never falls inside the child's lifetime.

Once the session is known, ``exit_card_lines`` reads its one row, by id, to
say what it was: its title, never message content or the cwd.

Everything here is best effort and runs after the person's session has
already ended. A line naming the wrong session is worse than no line, so
every ambiguity resolves to ``None``.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..plugin_bundle.omh.sqlite_readonly import connect_readonly

# Hermes' own profile id rule (``hermes_cli/main.py``, ``_PROFILE_NAME_RE``,
# which mirrors ``hermes_cli/profiles.py``). A name that could not identify a
# profile directory never becomes a path component here.
_PROFILE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# What a session id has to look like before a copyable line carries it.
# Hermes' ids are `YYYYMMDD_HHMMSS_<hex>`; anything a shell would read as more
# than one word, or as an option, is never printed.
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")

# A database the gateway is still finishing with is reported as no line, never
# as a wait: this runs in a shell that has just come back from the TUI.
_DB_BUSY_TIMEOUT_SECONDS = 0.25

# How close to the child's exit a session's ``ended_at`` has to sit before it
# reads as "the session that just closed", and how far apart the two newest
# candidates have to be before the later one is unambiguous.
#
# What it has to cover: the gateway finishing its shutdown once the TUI
# process goes away, and then Hermes' own launcher opening state.db to print
# its exit summary (``hermes_cli/main_tui_launch.py``,
# ``_print_tui_exit_summary``) and returning, all before this process sees the
# child's exit status at all.
#
# Why it is not larger: the same window is what makes another terminal's
# session look like this one. Someone with two TUIs open who closes both
# around the same moment is the case this has to stay narrow enough to refuse,
# and ``_chosen_candidate`` refuses it by comparing the two newest ``ended_at``
# values against this same value.
#
# The value is reasoned from that ordering, not measured. Measuring it would
# take a live TUI exit, which nothing in this repository runs.
RESUME_END_PROXIMITY_SECONDS = 5.0

# Only what choosing the session needs: the id to print, the end stamp the
# rules compare, and whether the session holds a conversation at all. No
# title, no message content, no cwd.
#
# ``cwd`` is deliberately absent as a filter too, not just as a column:
# ``hermes --resume`` restores the session's own working directory unless
# ``--no-restore-cwd`` is given, so a resumed session's ``cwd`` legitimately
# differs from the directory the launch happened in.
#
# ``ended_at IS NOT NULL`` is a stated precondition rather than a branch:
# removing it turns no test red, because ``NULL >= ?`` is NULL and the window
# comparison below already drops the row. It is kept because "a session
# nothing ended is not a candidate" is the rule the gateway's behaviour makes
# load-bearing, and a later change to the window must not silently take it
# with it.
_CANDIDATE_SELECT = (
    "SELECT id, ended_at, message_count FROM sessions "
    "WHERE source = 'tui' AND ended_at IS NOT NULL "
    "AND ended_at >= ? AND ended_at <= ? "
    "ORDER BY ended_at DESC LIMIT 2"
)


def _epoch(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def hermes_profile_home(hermes_home: str | Path, profile: str | None = None) -> Path | None:
    """The Hermes home of the default profile, or of one named profile.

    Hermes' default profile lives at the home itself and every named one under
    ``<home>/profiles/<name>``. A name this cannot use as a directory
    component returns ``None`` instead of a path built out of it; the launch
    still forwards the name to Hermes, which validates it itself.
    """
    home = Path(hermes_home)
    if profile is None:
        return home
    if not _PROFILE_NAME_RE.fullmatch(profile):
        return None
    return home / "profiles" / profile


def hermes_state_db_path(hermes_home: str | Path, profile: str | None = None) -> Path | None:
    """The state database for the default home, or for one named profile (`hermes_profile_home`)."""
    home = hermes_profile_home(hermes_home, profile)
    return None if home is None else home / "state.db"


def _chosen_candidate(rows: list[tuple], child_ended_at: float) -> str | None:
    if not rows:
        return None
    session_id, ended_at, message_count = rows[0]
    latest = _epoch(ended_at)
    if latest is None or child_ended_at - latest > RESUME_END_PROXIMITY_SECONDS:
        return None
    if len(rows) > 1:
        runner_up = _epoch(rows[1][1])
        if runner_up is None or latest - runner_up <= RESUME_END_PROXIMITY_SECONDS:
            return None
    try:
        if int(message_count) <= 0:
            return None
    except (TypeError, ValueError):
        return None
    return str(session_id or "").strip() or None


def resumable_session_id(
    db_path: str | Path | None,
    child_started_at: float,
    child_ended_at: float,
) -> str | None:
    """The id of the TUI session that ended with this child, or ``None``.

    The window is the child's own lifetime: a session that ended before the
    launch started is some earlier terminal's. Within it, the newest ended TUI
    session wins, and only when it ended close to the child's exit, no second
    session ended within :data:`RESUME_END_PROXIMITY_SECONDS` of it, and it
    holds at least one message.

    A missing, locked, corrupt or foreign database returns ``None`` and
    raises nothing: the caller prints no line, which is the outcome every
    unresolved case wants.
    """
    if db_path is None or child_ended_at < child_started_at:
        return None
    try:
        connection = connect_readonly(db_path, timeout=_DB_BUSY_TIMEOUT_SECONDS)
    except (sqlite3.Error, ValueError, OSError):
        return None
    try:
        rows = connection.execute(_CANDIDATE_SELECT, (child_started_at, child_ended_at)).fetchall()
    except (sqlite3.Error, ValueError):
        return None
    finally:
        try:
            connection.close()
        except sqlite3.Error:
            pass
    return _chosen_candidate(rows, child_ended_at)


def resume_command_line(session_id: str, profile: str | None = None) -> str:
    """The copyable line: the same door the person came in through.

    The profile is carried because a profile has its own ``state.db``. Without
    it the line would send the person back to the default home, where the id
    does not exist.
    """
    if profile:
        return f"omh -p {profile} --resume {session_id}"
    return f"omh --resume {session_id}"


# The one row the exit card reads, by the id already chosen: its title, and
# whether anything was said in it. No message content, no cwd.
_CARD_SELECT = "SELECT title, message_count FROM sessions WHERE id = ?"

# What a session nothing was said in leaves: Hermes stores a session's row
# only once its first prompt is sent, and prints no epilogue for one without
# messages, so there is nothing to resume.
NOTHING_SAID_LINE = "omh: nothing was said in this session, so there is nothing to resume."
UNTITLED = "untitled session"


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _session_card_row(db_path: str | Path, session_id: str) -> tuple[str, int] | None | bool:
    """The session's title and message count; None when it has no row; False when the database cannot be read."""
    try:
        connection = connect_readonly(db_path, timeout=_DB_BUSY_TIMEOUT_SECONDS)
    except (sqlite3.Error, ValueError, OSError):
        return False
    try:
        row = connection.execute(_CARD_SELECT, (session_id,)).fetchone()
    except (sqlite3.Error, ValueError):
        return False
    finally:
        try:
            connection.close()
        except sqlite3.Error:
            pass
    if row is None:
        return None
    return " ".join(str(row[0] or "").split()), _count(row[1])


def exit_card_lines(db_path: str | Path | None, session_id: str, profile: str | None = None) -> list[str]:
    """What `omh` prints for `session_id` as the TUI closes: the card, `NOTHING_SAID_LINE`, or nothing.

    The card is the session's title and, after a blank line, the `omh` way
    back, the command alone (`omh --resume <id>`; owner, 2026-10-31: no
    `resume:` label), with the id whole so it can be copied,
    then a blank line so the shell prompt does not sit right under it. The id
    always resolves, where a title lookup can land on another session.

    A session with no row is one nothing was said in: Hermes stores the row
    with the first prompt. A database that cannot be read prints nothing,
    since it cannot tell those apart from a session that has messages.
    """
    if db_path is None or not _SESSION_ID_RE.fullmatch(session_id):
        return []
    card = _session_card_row(db_path, session_id)
    if card is False:
        return []
    if card is None or card[1] == 0:
        return [NOTHING_SAID_LINE]
    title = card[0]
    return [
        f"omh · {title if title and title.isprintable() else UNTITLED}",
        "",
        "  " + resume_command_line(session_id, profile),
        "",
    ]


def session_known(db_path: str | Path, session_id: str) -> bool:
    """Whether Hermes' state database at `db_path` has a row for `session_id`; False when it has none or cannot
    be read (a missing database is a home no session was ever opened in)."""
    if not session_id or not Path(db_path).is_file():
        return False
    return bool(_session_card_row(db_path, session_id))
