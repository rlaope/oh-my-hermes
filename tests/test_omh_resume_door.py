"""Contracts for `omh --resume` and the copyable line the TUI exit prints.

Two surfaces, pinned separately.

The pass-through is argv: which elements reach `hermes`, in which order, and
that a bare-launch flag typed alongside a subcommand is refused by name
rather than dropped.

The line is a selection over Hermes' own `sessions` table, and the whole of
its contract is when it declines. This code runs after the person's session
has already ended, with no way to confirm anything it decides, so a line
naming the wrong session is worse than no line at all. Every rule below is
therefore a negative one, and each is proved by a fixture that differs from
the naming case in exactly the one field the rule reads.

The fixtures are real temporary SQLite files carrying the real column names
from `hermes_state_common.py`, including `title` and `cwd`, which the
selection may not read: `title` because choosing a session by its words
would guess, `cwd` because `hermes --resume` restores the session's own
working directory unless `--no-restore-cwd` is given, so a resumed session's
`cwd` legitimately differs from where the launch happened. The exit card
reads the title once the session is chosen, and never the cwd.

The card's session comes first from the file the OMH TUI keeps
(`SESSION_FILE_ENV`); the selection is the fallback when that file names
nothing. A resumed session the person sent nothing in keeps the `ended_at`
it had before the launch, so only the file can name it.

What these tests do NOT establish: that a live TUI exit is observed at all.
No test here launches Hermes, so the claim is about the selection rules and
the argv, never about an end-to-end exit on a real machine.
"""

from __future__ import annotations

import io
import json
import os
import signal
import sqlite3
import sys
import unittest
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from omh.commands.main import _launch_hermes_tui, build_parser
from omh.tui.launch import omh_tui_blocker
from omh.tui.terminal import terminal_blocker
from omh.maintenance.hermes_resume import (
    RESUME_END_PROXIMITY_SECONDS,
    hermes_state_db_path,
    resumable_session_id,
    resume_command_line,
)

# A child that ran for a minute and exited at this instant. Fixed rather than
# clock-derived so no case here can go red with the passage of time.
CHILD_STARTED_AT = 1_800_000_000.0
CHILD_ENDED_AT = CHILD_STARTED_AT + 60.0

_SCHEMA = (
    "CREATE TABLE sessions ("
    "id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL, "
    "ended_at REAL, end_reason TEXT, message_count INTEGER DEFAULT 0, "
    "title TEXT, cwd TEXT, model TEXT, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, "
    "cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0, reasoning_tokens INTEGER DEFAULT 0, "
    "model_config TEXT)"
)
_MESSAGES_SCHEMA = (
    "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, "
    "content TEXT, timestamp REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1)"
)
_INSERT = (
    "INSERT INTO sessions (id, source, started_at, ended_at, message_count, title, cwd) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)

# Sentinels for the two columns the selection may never carry out of the
# database. They are deliberately distinctive strings.
SECRET_TITLE = "renaming the production cluster"
SECRET_CWD = "/private/somewhere/else"

# An environment inherited from an earlier OMH frontend, not supplied by the runner.
INHERITED_TUI_ENV = {
    "HERMES_TUI_DIR": "/earlier/frontend",
    "OMH_TUI_PYTHON": "/earlier/python",
    "OMH_TUI_SITE": "/earlier/site",
    "OMH_TUI_FALLBACK_SENTINEL": "/earlier/fallback",
    "OMH_TUI_SESSION_FILE": "/earlier/session",
    "OMH_TUI_PICK_SESSION": "1",
    "OMH_TUI_RELAUNCH_FILE": "/earlier/relaunch",
    "OMH_TUI_RUNTIME": "own",
    "OMH_TUI_BOTS_HOME": "/earlier/bots",
    "OMH_TUI_UPDATED": "plan",
}


def write_sessions(path: Path, rows: list[tuple]) -> None:
    """Create a real state database holding exactly *rows*.

    Each row is ``(id, source, started_at, ended_at, message_count)``; the
    title and cwd are filled with the sentinels so any leak is visible.
    """
    connection = sqlite3.connect(path)
    try:
        connection.execute(_SCHEMA)
        connection.execute(_MESSAGES_SCHEMA)
        connection.executemany(
            _INSERT,
            [(*row, SECRET_TITLE, SECRET_CWD) for row in rows],
        )
        connection.commit()
    finally:
        connection.close()


def write_card_session(
    path: Path,
    session_id: str,
    *,
    title: str | None = "Fix the login bug",
    started_at: float = CHILD_STARTED_AT + 1,
    ended_at: float | None = CHILD_ENDED_AT - 0.2,
    turns: int = 3,
) -> None:
    """Add one session to a state database (created when missing) with `turns` user prompts, each followed by a reply.

    The row carries Hermes' model and token columns too, which the card does not read."""
    fresh = not path.exists()
    connection = sqlite3.connect(path)
    try:
        if fresh:
            connection.execute(_SCHEMA)
            connection.execute(_MESSAGES_SCHEMA)
        connection.execute(
            "INSERT INTO sessions (id, source, started_at, ended_at, message_count, title, cwd, model, input_tokens, "
            "output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens) "
            "VALUES (?, 'tui', ?, ?, ?, ?, ?, 'moonshotai/kimi-k3.1-pro', 12000, 3000, 2000, 1000, 200)",
            (session_id, started_at, ended_at, 2 * turns, title, SECRET_CWD),
        )
        for index in range(turns):
            connection.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, active) VALUES (?, 'user', ?, ?, 1)",
                (session_id, f"prompt {index}", started_at + index),
            )
            connection.execute(
                "INSERT INTO messages (session_id, role, content, timestamp, active) VALUES (?, 'assistant', ?, ?, 1)",
                (session_id, f"reply {index}", started_at + index + 0.5),
            )
        connection.commit()
    finally:
        connection.close()


class _TtyStream(io.StringIO):
    """A captured stream that still answers `isatty()` the way a terminal does."""

    def isatty(self) -> bool:
        return True


@contextmanager
def terminal_stdio():
    """Run with stdin/stdout that look like a terminal and capture stdout."""
    stdout = _TtyStream()
    previous_in, previous_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = _TtyStream(), stdout
    try:
        yield stdout
    finally:
        sys.stdin, sys.stdout = previous_in, previous_out


@contextmanager
def launched(
    hermes_home: Path,
    argv: list[str],
    *,
    returncode: int | list[int] = 0,
    omh_tui: bool = False,
    blocker: str = "TERM=dumb cannot draw the OMH TUI",
    node: bool = False,
    environments: list[dict[str, str] | None] | None = None,
    signal_fallback: bool | str = False,
    while_tui_runs=None,
    killed: list[str] | None = None,
    errors: list[str] | None = None,
    session_record: dict | list | str | None = None,
):
    """Run the bare launch with a faked `hermes` child.

    Yields ``(recorded, stdout, status)``: the argv handed to
    ``subprocess.Popen`` (the OMH TUI attempt) or ``subprocess.run`` (Hermes'
    own terminal), everything the launch printed, and the code it
    returned. ``omh_tui`` says whether the OMH TUI can run here, and
    ``blocker`` is the reason given when it cannot; ``node`` says whether
    Node is found, which picks Hermes' own TUI over plain `hermes` for
    the fallback. The surface-neutral tests keep both off, so they pin plain
    `hermes`. A list of return codes answers successive children in order,
    ``environments`` (when given) collects the ``env`` each child was started
    with, and ``errors`` (when given) collects what the launch wrote to stderr.
    With ``signal_fallback``, a child started with a fallback sentinel name
    creates that file, as the OMH TUI does before it exits 75, holding the
    text when it is one (what the TUI said about why).
    With ``session_record``, a child started with a session file name writes
    it there as the OMH TUI does (JSON for a dict, the text as it is for a
    string).
    ``while_tui_runs`` is called while the OMH TUI attempt is being waited on,
    and ``killed`` collects a note for each kill, terminate or signal sent to
    that child.
    """
    from omh.tui.launch import FALLBACK_SENTINEL_ENV, SESSION_FILE_ENV

    recorded: list[list[str]] = []
    codes = list(returncode) if isinstance(returncode, list) else None

    class _Completed:
        def __init__(self, code: int) -> None:
            self.returncode = code

    def fake_run(command, *args, **kwargs):
        recorded.append(list(command))
        env = kwargs.get("env")
        if environments is not None:
            environments.append(env)
        if session_record is not None and env and SESSION_FILE_ENV in env:
            text = session_record if isinstance(session_record, str) else json.dumps(session_record)
            Path(env[SESSION_FILE_ENV]).write_text(text, encoding="utf-8")
        if signal_fallback and env and FALLBACK_SENTINEL_ENV in env:
            Path(env[FALLBACK_SENTINEL_ENV]).write_text(signal_fallback if isinstance(signal_fallback, str) else "")
        return _Completed(codes.pop(0) if codes is not None else returncode)

    class _Child:
        def __init__(self, code: int) -> None:
            self.code = code

        def wait(self, timeout: float | None = None) -> int:
            if while_tui_runs is not None:
                while_tui_runs()
            return self.code

        def kill(self) -> None:
            if killed is not None:
                killed.append("kill")

        def terminate(self) -> None:
            if killed is not None:
                killed.append("terminate")

        def send_signal(self, signum: int) -> None:
            if killed is not None:
                killed.append(f"signal {signum}")

    def fake_popen(command, *args, **kwargs):
        return _Child(fake_run(command, *args, **kwargs).returncode)

    parsed = build_parser().parse_args(["--hermes-home", str(hermes_home), *argv])
    stderr = io.StringIO()
    with terminal_stdio() as stdout, redirect_stderr(stderr), \
            patch("shutil.which", return_value="/usr/local/bin/hermes"), \
            patch("omh.commands.bare_launch._run_startup_update_check"), \
            patch("omh.commands.bare_launch._omh_tui_blocker", return_value="" if omh_tui else blocker), \
            patch("omh.commands.bare_launch._node_available", return_value=node), \
            patch("omh.commands.bare_launch.subprocess.run", side_effect=fake_run), \
            patch("omh.commands.bare_launch.subprocess.Popen", side_effect=fake_popen), \
            patch("omh.commands.bare_launch.time.time", side_effect=[CHILD_STARTED_AT, CHILD_ENDED_AT]):
        status = _launch_hermes_tui(parsed)
    if errors is not None:
        errors.append(stderr.getvalue())
    yield recorded, stdout.getvalue(), status


class SessionSelectionTests(unittest.TestCase):
    """Which session, if any, the launch names after the child exits."""

    def test_the_one_session_that_ended_in_the_window_is_named(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-alpha", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12)])

            self.assertEqual(
                resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT),
                "sess-alpha",
            )

    def test_an_empty_table_names_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [])

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_session_that_ended_well_before_the_child_exited_names_nothing(self) -> None:
        # Inside the child's lifetime, so the window keeps it, but nowhere
        # near the exit: some earlier terminal in the same minute.
        stale = CHILD_ENDED_AT - RESUME_END_PROXIMITY_SECONDS - 1.0
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-stale", "tui", CHILD_STARTED_AT + 1, stale, 12)])

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_two_sessions_ending_together_name_nothing(self) -> None:
        # Two TUIs closed at once. Either could be the child's, so neither is.
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(
                db,
                [
                    ("sess-alpha", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12),
                    ("sess-beta", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.4, 9),
                ],
            )

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_an_earlier_session_outside_the_tolerance_does_not_block_the_naming(self) -> None:
        # The positive control for the rule above: a second session is only
        # an ambiguity while it is close enough to be confused with the first.
        far = CHILD_ENDED_AT - RESUME_END_PROXIMITY_SECONDS - 0.5
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(
                db,
                [
                    ("sess-alpha", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12),
                    ("sess-earlier", "tui", CHILD_STARTED_AT + 0.5, far, 9),
                ],
            )

            self.assertEqual(
                resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT),
                "sess-alpha",
            )

    def test_a_session_with_no_messages_names_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-empty", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 0)])

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_session_from_another_source_is_not_a_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-kanban", "kanban", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12)])

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_session_that_never_ended_is_not_a_candidate(self) -> None:
        # Still running, or gateway-owned: the gateway deliberately never ends
        # a session another backend holds, so `ended_at` stays NULL.
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-live", "tui", CHILD_STARTED_AT + 1, None, 12)])

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_session_that_ended_before_the_child_started_is_not_a_candidate(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(
                db,
                [("sess-yesterday", "tui", CHILD_STARTED_AT - 500, CHILD_STARTED_AT - 1, 12)],
            )

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_short_launch_does_not_reach_back_before_it_started(self) -> None:
        # The window's lower bound only does work a launch shorter than the
        # tolerance can expose: with a long child the proximity rule already
        # implies it. Here the child lived one second, and a session that
        # ended two seconds before it started is still within the tolerance
        # of its exit -- only the window keeps it out.
        started = CHILD_STARTED_AT
        ended = started + 1.0
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-previous", "tui", started - 60, started - 2.0, 12)])

            self.assertIsNone(resumable_session_id(db, started, ended))

    def test_a_session_that_ended_after_the_child_did_is_not_a_candidate(self) -> None:
        # Another terminal closing a fraction of a second later. It is the
        # newest ended session and it is well inside the tolerance, so only
        # the window's upper bound keeps it from being named.
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-later", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT + 0.5, 12)])

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_session_left_open_alongside_the_closing_one_is_not_a_rival(self) -> None:
        # The gateway-owned case from the other side: a session nothing ended
        # is not a candidate at all, so it cannot make the closing one
        # ambiguous.
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(
                db,
                [
                    ("sess-alpha", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12),
                    ("sess-gateway", "tui", CHILD_STARTED_AT + 2, None, 40),
                ],
            )

            self.assertEqual(
                resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT),
                "sess-alpha",
            )

    def test_a_missing_database_names_nothing_and_raises_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(
                resumable_session_id(Path(tmp) / "state.db", CHILD_STARTED_AT, CHILD_ENDED_AT)
            )

    def test_a_corrupt_database_names_nothing_and_raises_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            db.write_bytes(b"this is not a database, it is a note about one\n" * 64)

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_foreign_schema_names_nothing_and_raises_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            connection = sqlite3.connect(db)
            try:
                connection.execute("CREATE TABLE notes (id TEXT)")
                connection.commit()
            finally:
                connection.close()

            self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_a_locked_database_names_nothing_and_raises_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-alpha", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12)])
            holder = sqlite3.connect(db, isolation_level=None)
            try:
                holder.execute("BEGIN EXCLUSIVE")

                self.assertIsNone(resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT))
            finally:
                holder.close()

    def test_no_database_path_names_nothing(self) -> None:
        self.assertIsNone(resumable_session_id(None, CHILD_STARTED_AT, CHILD_ENDED_AT))

    def test_the_selection_reads_neither_the_title_nor_the_working_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-alpha", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12)])

            named = resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT)

            self.assertEqual(named, "sess-alpha")
            self.assertNotIn(SECRET_TITLE, resume_command_line(named))
            self.assertNotIn(SECRET_CWD, resume_command_line(named))

    def test_a_session_whose_directory_moved_is_still_named(self) -> None:
        # `hermes --resume` restores the session's own cwd, so a resumed
        # session legitimately ended somewhere other than the launch
        # directory. Filtering on cwd would lose exactly the resumed case.
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_sessions(db, [("sess-moved", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 4)])

            self.assertEqual(
                resumable_session_id(db, CHILD_STARTED_AT, CHILD_ENDED_AT),
                "sess-moved",
            )


class StateDatabasePathTests(unittest.TestCase):
    def test_the_default_home_keeps_its_database_at_the_root(self) -> None:
        self.assertEqual(
            hermes_state_db_path(Path("/tmp/hermes-home")),
            Path("/tmp/hermes-home/state.db"),
        )

    def test_a_profile_reads_its_own_database(self) -> None:
        self.assertEqual(
            hermes_state_db_path(Path("/tmp/hermes-home"), "work"),
            Path("/tmp/hermes-home/profiles/work/state.db"),
        )

    def test_a_name_that_could_not_be_a_profile_directory_yields_no_path(self) -> None:
        for name in ("../../etc", "Work", "", "has space", "a/b"):
            with self.subTest(name=name):
                self.assertIsNone(hermes_state_db_path(Path("/tmp/hermes-home"), name))


class ResumeLineTests(unittest.TestCase):
    def test_the_line_without_a_profile(self) -> None:
        self.assertEqual(resume_command_line("sess-alpha"), "omh --resume sess-alpha")

    def test_the_line_with_a_profile(self) -> None:
        # A profile has its own state.db, so the line is useless without it.
        self.assertEqual(
            resume_command_line("sess-alpha", "work"),
            "omh -p work --resume sess-alpha",
        )


class PassThroughArgvTests(unittest.TestCase):
    """What the bare launch hands to `hermes`."""

    def _argv_for(self, argv: list[str]) -> list[str]:
        with TemporaryDirectory() as tmp:
            with launched(Path(tmp), argv) as (recorded, _stdout, _status):
                pass
        self.assertEqual(len(recorded), 1)
        return recorded[0]

    def test_a_bare_launch_adds_nothing(self) -> None:
        self.assertEqual(self._argv_for([]), ["/usr/local/bin/hermes"])

    def test_resume_is_forwarded_as_its_own_element(self) -> None:
        self.assertEqual(
            self._argv_for(["--resume", "sess alpha"]),
            ["/usr/local/bin/hermes", "--resume", "sess alpha"],
        )

    def test_the_short_resume_form_forwards_the_same_way(self) -> None:
        self.assertEqual(
            self._argv_for(["-r", "sess-alpha"]),
            ["/usr/local/bin/hermes", "--resume", "sess-alpha"],
        )

    def test_continue_without_a_name_forwards_the_flag_alone(self) -> None:
        self.assertEqual(
            self._argv_for(["--continue"]),
            ["/usr/local/bin/hermes", "--continue"],
        )

    def test_continue_with_a_name_forwards_both(self) -> None:
        self.assertEqual(
            self._argv_for(["-c", "yesterday's plan"]),
            ["/usr/local/bin/hermes", "--continue", "yesterday's plan"],
        )

    def test_a_profile_is_forwarded(self) -> None:
        self.assertEqual(
            self._argv_for(["-p", "work"]),
            ["/usr/local/bin/hermes", "--profile", "work"],
        )

    def test_the_forwarding_order_is_fixed(self) -> None:
        # Profile first because it selects the home the session lives in.
        self.assertEqual(
            self._argv_for(["--resume", "sess-alpha", "--profile", "work"]),
            ["/usr/local/bin/hermes", "--profile", "work", "--resume", "sess-alpha"],
        )



class OmhTuiDoorTests(unittest.TestCase):
    """When the OMH TUI can run, bare `omh` opens it through `hermes --tui`."""

    def test_the_omh_tui_attempt_adds_tui_after_the_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            with launched(Path(tmp), ["--resume", "sess-alpha", "-p", "work"], omh_tui=True) as (recorded, _o, _s):
                pass
        self.assertEqual(
            recorded,
            [["/usr/local/bin/hermes", "--profile", "work", "--tui", "--resume", "sess-alpha"]],
        )

    def test_the_attempt_carries_the_frontend_dir_the_interpreter_its_import_root_and_the_omh_home(self) -> None:
        from omh.tui.launch import FRONTEND_DIR, SITE_ENV, omh_import_root

        environments: list[dict[str, str] | None] = []
        # A value left in the person's environment must not pick the tree the TUI imports.
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {SITE_ENV: "/another/tree"}):
            with launched(Path(tmp), ["--omh-home", str(Path(tmp) / "omh")], omh_tui=True,
                          environments=environments) as (_r, _o, _s):
                pass
        (environment,) = environments
        self.assertEqual(environment["HERMES_TUI_DIR"], str(FRONTEND_DIR))
        self.assertEqual(environment["OMH_TUI_PYTHON"], sys.executable)
        self.assertEqual(environment[SITE_ENV], omh_import_root())
        self.assertEqual(Path(environment["OMH_HOME"]).name, "omh")

    def test_a_profile_that_names_its_own_store_hands_the_tui_that_store(self) -> None:
        # The theme, the HUD and `/omh-model` read OMH_HOME; for a split-store
        # profile that has to be the store its config names, where setup
        # saved its theme, not the primary's.
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            split = root / "split-store"
            (root / "profiles" / "split").mkdir(parents=True)
            (root / "profiles" / "split" / "config.yaml").write_text(
                f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {split.as_posix()}\n",
                encoding="utf-8",
            )
            (root / "profiles" / "plain").mkdir(parents=True)
            # Hermes loads this flow shape; OMH's setting scan refuses it,
            # and the launch must not end in a traceback over that.
            (root / "profiles" / "flow").mkdir(parents=True)
            (root / "profiles" / "flow" / "config.yaml").write_text(
                f"plugins:\n  entries: {{omh: {{settings: {{omh_home: {split.as_posix()}}}}}}}\n",
                encoding="utf-8",
            )
            homes: dict[str, str] = {}
            for name, argv in (
                ("none", []),
                ("split", ["-p", "split"]),
                ("plain", ["-p", "plain"]),
                ("flow", ["-p", "flow"]),
                ("named", ["--omh-home", str(root / "named"), "-p", "split"]),
            ):
                environments: list[dict[str, str] | None] = []
                with launched(root, argv, omh_tui=True, environments=environments) as (_r, _o, _s):
                    pass
                homes[name] = environments[0]["OMH_HOME"]
        self.assertEqual(Path(homes["split"]), split)
        # A profile that names none keeps the store this `omh` resolved, and
        # an explicit --omh-home still wins.
        self.assertEqual(homes["plain"], homes["none"])
        self.assertEqual(homes["flow"], homes["none"])
        self.assertEqual(Path(homes["named"]), root / "named")

    def test_the_fallback_code_with_its_sentinel_reopens_hermes_own_terminal(self) -> None:
        from omh.tui.launch import FALLBACK_EXIT

        with TemporaryDirectory() as tmp:
            with launched(Path(tmp), ["-c"], returncode=[FALLBACK_EXIT, 0], omh_tui=True,
                          signal_fallback=True) as (recorded, _o, status):
                pass
        self.assertEqual(
            recorded,
            [["/usr/local/bin/hermes", "--tui", "--continue"], ["/usr/local/bin/hermes", "--continue"]],
        )
        self.assertEqual(status, 0)

    def test_the_fallback_code_without_its_sentinel_is_an_ordinary_exit(self) -> None:
        # Hermes exits 75 (EX_TEMPFAIL) on paths of its own; that must not open a second terminal.
        from omh.tui.launch import FALLBACK_EXIT

        with TemporaryDirectory() as tmp:
            with launched(Path(tmp), ["-c"], returncode=[FALLBACK_EXIT, 0], omh_tui=True) as (recorded, _o, status):
                pass
        self.assertEqual(recorded, [["/usr/local/bin/hermes", "--tui", "--continue"]])
        self.assertEqual(status, FALLBACK_EXIT)

    def test_the_sentinel_and_its_directory_are_gone_after_the_launch(self) -> None:
        from omh.tui.launch import FALLBACK_EXIT, FALLBACK_SENTINEL_ENV

        for codes, signal_fallback in (([FALLBACK_EXIT, 0], True), ([FALLBACK_EXIT], False), ([0], False)):
            with self.subTest(codes=codes, signal_fallback=signal_fallback), TemporaryDirectory() as tmp:
                environments: list[dict[str, str] | None] = []
                with launched(Path(tmp), [], returncode=list(codes), omh_tui=True, environments=environments,
                              signal_fallback=signal_fallback) as (_r, _o, _s):
                    pass
                sentinel = Path(environments[0][FALLBACK_SENTINEL_ENV])
                self.assertFalse(sentinel.parent.exists())
                # Hermes' own terminal, when it opens, is started without the name.
                self.assertTrue(all(FALLBACK_SENTINEL_ENV not in env for env in environments[1:]))

    def test_any_other_code_ends_the_launch_without_a_second_terminal(self) -> None:
        with TemporaryDirectory() as tmp:
            for code in (0, 1, 2, 42, 130):
                with self.subTest(code=code):
                    with launched(Path(tmp), [], returncode=[code], omh_tui=True) as (recorded, _o, status):
                        pass
                    self.assertEqual(len(recorded), 1)
                    self.assertEqual(status, code)

    @unittest.skipIf(os.name == "nt", "SIGHUP is POSIX-only, and the OMH TUI is never attempted on Windows")
    def test_a_hangup_or_terminate_while_the_tui_runs_removes_the_sentinel_directory_and_leaves_the_child(self) -> None:
        # Closing the terminal window sends SIGHUP; left to its default action it ended `omh` before any `finally`.
        from omh.tui.launch import FALLBACK_SENTINEL_ENV

        for name in ("SIGHUP", "SIGTERM"):
            signum = getattr(signal, name)
            before = signal.getsignal(signum)
            with self.subTest(signal=name), TemporaryDirectory() as tmp:
                environments: list[dict[str, str] | None] = []
                killed: list[str] = []
                seen: list[bool] = []

                def deliver() -> None:
                    seen.append(Path(environments[0][FALLBACK_SENTINEL_ENV]).parent.is_dir())
                    os.kill(os.getpid(), signum)

                with self.assertRaises(SystemExit) as raised:
                    with launched(Path(tmp), [], omh_tui=True, environments=environments,
                                  while_tui_runs=deliver, killed=killed) as (_r, _o, _s):
                        pass
                self.assertEqual(raised.exception.code, 128 + signum)
                self.assertEqual(seen, [True])
                self.assertFalse(Path(environments[0][FALLBACK_SENTINEL_ENV]).parent.exists())
                self.assertEqual(killed, [])  # Hermes' launcher deals with the signal itself, as before
                self.assertIs(signal.getsignal(signum), before)

    def test_without_the_omh_tui_and_without_node_plain_hermes_runs(self) -> None:
        environments: list[dict[str, str] | None] = []
        with TemporaryDirectory() as tmp, patch.dict(os.environ, INHERITED_TUI_ENV):
            with launched(Path(tmp), [], omh_tui=False, environments=environments) as (recorded, _o, _s):
                pass
        self.assertEqual(recorded, [["/usr/local/bin/hermes"]])
        self.assertEqual(len(environments), 1)
        self.assertNotIn("HERMES_TUI_DIR", environments[0].keys())
        self.assertIn("HERMES_HOME", environments[0])


class FallbackTargetTests(unittest.TestCase):
    """Where the OMH TUI cannot run, which Hermes terminal opens, and the one line that says why.

    Bare `hermes` is stock Hermes, so the fallback asks for Hermes' own TUI
    when the reason is the OMH TUI's own and Node is found. A terminal no TUI
    can use (`TERM=dumb`, `OMH_NO_TUI=1`) and a machine without Node get
    plain `hermes`, which opens what `display.interface` chooses.
    """

    HERMES = "/usr/local/bin/hermes"

    def _fallback(
        self, environ: dict[str, str] | None = None, **kwargs
    ) -> tuple[list[list[str]], list[dict[str, str] | None], str, int]:
        environments: list[dict[str, str] | None] = []
        errors: list[str] = []
        # The runner's own TERM must not decide the target.
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            for name in ("TERM", "OMH_NO_TUI"):
                os.environ.pop(name, None)
            os.environ.update(environ or {})
            with launched(Path(tmp), kwargs.pop("argv", []), environments=environments, errors=errors,
                          **kwargs) as (recorded, _o, status):
                pass
        return recorded, environments, errors[0], status

    def test_no_termios_with_node_opens_hermes_own_tui(self) -> None:
        with patch("omh.tui.terminal.termios", None):
            reason = terminal_blocker(_TtyStream(), _TtyStream(), {})
        self.assertIn("termios", reason)
        recorded, environments, stderr, _status = self._fallback(INHERITED_TUI_ENV, blocker=reason, node=True)
        self.assertEqual(recorded, [[self.HERMES, "--tui"]])
        # Hermes' own TUI, not the OMH frontend; the selected home still reaches it.
        self.assertEqual(len(environments), 1)
        self.assertNotIn("HERMES_TUI_DIR", environments[0].keys())
        self.assertIn("HERMES_HOME", environments[0])
        self.assertEqual(stderr, f"omh: {reason}; opening Hermes' own TUI (`hermes --tui`).\n")

    def test_fallback_drops_frontend_environment_with_and_without_messaging_scrub(self) -> None:
        from types import SimpleNamespace

        from omh.commands.bare_launch import _run_hermes_fallback

        inherited = {
            **INHERITED_TUI_ENV,
            "OMH_HOME": "/chosen/omh",
            "HERMES_HOME": "/earlier/hermes",
            "TERM": "xterm-256color",
            "OMH_NO_TUI": "0",
            "TELEGRAM_BOT_TOKEN": "test-messaging-token",
            "PATH": "/chosen/bin",
        }
        paths = SimpleNamespace(hermes_home=Path("/resolved/hermes"))
        chosen_hermes_home = Path("/chosen/hermes")
        args = build_parser().parse_args([])
        for scrub in (False, True):
            for node in (False, True):
                with self.subTest(scrub=scrub, node=node), patch.dict(os.environ, inherited), \
                        patch("omh.commands.bare_launch._node_available", return_value=node), \
                        patch("omh.commands.bare_launch.subprocess.run") as run, redirect_stderr(io.StringIO()):
                    run.return_value.returncode = 3
                    status = _run_hermes_fallback(
                        self.HERMES, args, paths, "frontend unavailable",
                        hermes_home=chosen_hermes_home, scrub=scrub,
                    )
                    env = run.call_args.kwargs["env"]
                    for name in INHERITED_TUI_ENV:
                        self.assertNotIn(name, env.keys(), name)
                        self.assertEqual(os.environ[name], inherited[name])
                    self.assertEqual(env["OMH_HOME"], inherited["OMH_HOME"])
                    # The fallback passes str(Path), which is native: backslashes on Windows.
                    self.assertEqual(env["HERMES_HOME"], str(chosen_hermes_home))
                    self.assertEqual(env["PATH"], inherited["PATH"])
                    self.assertEqual("TELEGRAM_BOT_TOKEN" in env, not scrub)
                    self.assertEqual(run.call_args.args[0], [self.HERMES, *(["--tui"] if node else [])])
                    self.assertEqual(status, 3)

    def test_a_dumb_terminal_opens_plain_hermes_even_with_node(self) -> None:
        # No TUI draws on TERM=dumb, Hermes' included.
        reason = terminal_blocker(_TtyStream(), _TtyStream(), {"TERM": "dumb"})
        recorded, _environments, stderr, _status = self._fallback(
            {"TERM": "dumb"}, blocker=reason, node=True, argv=["-p", "work"]
        )
        self.assertEqual(recorded, [[self.HERMES, "--profile", "work"]])
        self.assertEqual(stderr, f"omh: {reason}; opening `hermes`.\n")

    def test_omh_no_tui_opens_plain_hermes_even_with_node(self) -> None:
        reason = terminal_blocker(_TtyStream(), _TtyStream(), {"OMH_NO_TUI": "1"})
        recorded, _environments, stderr, _status = self._fallback({"OMH_NO_TUI": "1"}, blocker=reason, node=True)
        self.assertEqual(recorded, [[self.HERMES]])
        self.assertEqual(stderr, f"omh: {reason}; opening `hermes`.\n")

    def test_the_fallback_code_with_node_opens_hermes_own_tui(self) -> None:
        from omh.tui.launch import FALLBACK_EXIT

        recorded, environments, stderr, status = self._fallback(
            omh_tui=True, node=True, returncode=[FALLBACK_EXIT, 0], argv=["-c"], signal_fallback=True
        )
        self.assertEqual(recorded, [[self.HERMES, "--tui", "--continue"], [self.HERMES, "--tui", "--continue"]])
        self.assertIsNotNone(environments[0])
        self.assertNotIn("HERMES_TUI_DIR", environments[1])
        self.assertEqual(environments[1]["HERMES_HOME"], environments[0]["HERMES_HOME"])
        self.assertEqual(
            stderr, "omh: the OMH TUI did not start (its reason is above); opening Hermes' own TUI (`hermes --tui`).\n"
        )
        self.assertEqual(status, 0)

    def test_what_the_tui_said_is_said_again_after_hermes_own_tui_closes(self) -> None:
        # Hermes' TUI clears the screen the TUI's reason was printed on, so the person never saw it.
        from omh.tui.launch import FALLBACK_EXIT

        said = "omh: the Hermes gateway did not start: it exited\n  [gateway-exit] refused: owned\n"
        _recorded, _environments, stderr, status = self._fallback(
            omh_tui=True, node=True, returncode=[FALLBACK_EXIT, 3], signal_fallback=said
        )
        self.assertEqual(stderr, (
            "omh: the OMH TUI did not start (its reason is above); opening Hermes' own TUI (`hermes --tui`).\n"
            "omh: Hermes' own TUI (`hermes --tui`) opened because the OMH TUI did not start; it said:\n"
            "  omh: the Hermes gateway did not start: it exited\n"
            "    [gateway-exit] refused: owned\n"
        ))
        self.assertEqual(status, 3)  # the session Hermes' TUI ran is what the launch returns

    def test_no_node_opens_plain_hermes(self) -> None:
        with TemporaryDirectory() as tmp, patch("omh.tui.launch.terminal_supported", return_value=True):
            reason = omh_tui_blocker(_TtyStream(), _TtyStream(), {"PATH": ""}, Path(tmp))
        self.assertIn("no Node found", reason)
        recorded, environments, stderr, _status = self._fallback(blocker=reason, node=False)
        self.assertEqual(recorded, [[self.HERMES]])
        self.assertEqual(len(environments), 1)
        self.assertNotIn("HERMES_TUI_DIR", environments[0].keys())
        self.assertIn("HERMES_HOME", environments[0])
        self.assertEqual(stderr, f"omh: {reason}; opening `hermes`.\n")

    def test_the_session_ending_in_the_omh_tui_prints_no_fallback_line(self) -> None:
        _recorded, _environments, stderr, _status = self._fallback(omh_tui=True, node=True, returncode=[0])
        self.assertEqual(stderr, "")


# What a launch prints for `write_card_session`'s defaults, after Hermes' own
# epilogue: the title, and the one way back.
CARD_ALPHA = "\nomh · Fix the login bug\n\n  omh --resume sess-alpha\n\n"


class LaunchExitTests(unittest.TestCase):
    """What the launch prints, and what it returns, once the child is gone."""

    def _home_with_session(self, tmp: str, *, profile: str | None = None) -> Path:
        home = Path(tmp)
        directory = home / "profiles" / profile if profile else home
        directory.mkdir(parents=True, exist_ok=True)
        write_card_session(directory / "state.db", "sess-alpha")
        return home

    def test_a_clean_exit_prints_the_card(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home_with_session(tmp)
            with launched(home, []) as (_recorded, stdout, status):
                pass

        self.assertEqual(status, 0)
        self.assertEqual(stdout, CARD_ALPHA)

    def test_an_interrupted_exit_prints_the_card_too(self) -> None:
        # 130 is the other code Hermes' own epilogue treats as a normal close.
        with TemporaryDirectory() as tmp:
            home = self._home_with_session(tmp)
            with launched(home, [], returncode=130) as (_recorded, stdout, status):
                pass

        self.assertEqual(status, 130)
        self.assertEqual(stdout, CARD_ALPHA)

    def test_a_profile_launch_prints_the_profile_in_the_resume_line(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home_with_session(tmp, profile="work")
            with launched(home, ["-p", "work"]) as (_recorded, stdout, _status):
                pass

        self.assertEqual(stdout, "\nomh · Fix the login bug\n\n  omh -p work --resume sess-alpha\n\n")

    def test_a_failed_exit_prints_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home_with_session(tmp)
            with launched(home, [], returncode=2) as (_recorded, stdout, status):
                pass

        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")

    def test_an_exit_code_is_returned_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            home = self._home_with_session(tmp)
            for code in (0, 1, 2, 42, 130):
                with self.subTest(code=code):
                    with launched(home, [], returncode=code) as (_recorded, _stdout, status):
                        pass
                    self.assertEqual(status, code)

    def test_a_home_with_no_database_prints_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            with launched(Path(tmp), []) as (_recorded, stdout, status):
                pass

        self.assertEqual(status, 0)
        self.assertEqual(stdout, "")

    def test_a_non_terminal_stdout_launches_nothing_at_all(self) -> None:
        # The TTY rule the line inherits: nothing is launched, so there is no
        # child to name a session for.
        recorded: list[list[str]] = []

        def fake_run(command, *args, **kwargs):  # pragma: no cover - must not run
            recorded.append(list(command))
            raise AssertionError("the launch must not reach a child without a terminal")

        parsed = build_parser().parse_args([])
        with patch("shutil.which", return_value="/usr/local/bin/hermes"), \
                patch("omh.commands.bare_launch.subprocess.run", side_effect=fake_run):
            self.assertIsNone(_launch_hermes_tui(parsed))
        self.assertEqual(recorded, [])


class ExitCardTests(unittest.TestCase):
    """The card the launch prints for the session the OMH TUI recorded, and the line for one nothing was said in."""

    def _launch(self, home: Path, record: dict | list | str | None, argv: list[str] | None = None, *,
                returncode: int | None = None) -> str:
        # The OMH TUI exits CLOSED_EXIT for a session the person closed under `omh`.
        from omh.tui.launch import CLOSED_EXIT

        code = CLOSED_EXIT if returncode is None else returncode
        with launched(home, argv or [], omh_tui=True, session_record=record, returncode=code) as (_r, out, _s):
            pass
        return out

    def test_the_closed_code_is_returned_as_0_with_the_card_and_no_other_code_moves(self) -> None:
        from omh.tui.launch import CLOSED_EXIT, FALLBACK_EXIT

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha")
            record = {"session_id": "sess-alpha", "hermes_home": str(home)}
            with launched(home, [], omh_tui=True, session_record=record, returncode=CLOSED_EXIT) as (recorded, out, status):
                pass
            self.assertEqual((status, out, len(recorded)), (0, CARD_ALPHA, 1))
            # 130 is Hermes' own interrupted close: its epilogue printed, the card follows.
            for code, card in ((0, CARD_ALPHA), (130, CARD_ALPHA), (1, ""), (2, ""), (42, ""), (FALLBACK_EXIT, ""),
                               (128 + 15, ""), (128 + 1, "")):  # SIGTERM, SIGHUP: literal, Windows has no SIGHUP
                with self.subTest(code=code):
                    with launched(home, [], omh_tui=True, session_record=record, returncode=code) as (_r, out, status):
                        pass
                    self.assertEqual((status, out), (code, card))

    def test_the_closed_code_from_hermes_own_terminal_is_not_turned_into_0(self) -> None:
        # Only the OMH TUI this launch started speaks that code; Hermes' own terminal's codes pass as they are.
        from omh.tui.launch import CLOSED_EXIT

        with TemporaryDirectory() as tmp:
            with launched(Path(tmp), [], returncode=CLOSED_EXIT) as (_recorded, out, status):
                pass
        self.assertEqual((status, out), (CLOSED_EXIT, ""))

    def test_the_recorded_session_gets_the_card(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha")
            out = self._launch(home, {"session_id": "sess-alpha", "hermes_home": str(home)})
        self.assertEqual(out, CARD_ALPHA)

    def test_a_resumed_session_nothing_was_sent_in_is_named_by_the_record_alone(self) -> None:
        # Hermes mounts a resumed session read-only: its `ended_at` stays the one
        # it had before this launch, so the end-stamp selection cannot see it.
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha", started_at=CHILD_STARTED_AT - 86_400,
                               ended_at=CHILD_STARTED_AT - 80_000)
            recorded = self._launch(home, {"session_id": "sess-alpha", "hermes_home": str(home)}, ["-r", "sess-alpha"])
            unrecorded = self._launch(home, None, ["-r", "sess-alpha"])
        self.assertEqual(recorded, CARD_ALPHA)
        self.assertEqual(unrecorded, "")

    def test_a_session_still_open_elsewhere_is_named_by_the_record(self) -> None:
        # A shared gateway keeps the session after the TUI detaches: nothing ends it.
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha", ended_at=None)
            out = self._launch(home, {"session_id": "sess-alpha", "hermes_home": str(home)})
        self.assertEqual(out, CARD_ALPHA)

    def test_a_session_with_no_row_gets_the_one_line(self) -> None:
        # Hermes stores a session's row with its first prompt.
        from omh.maintenance.hermes_resume import NOTHING_SAID_LINE

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-other")
            out = self._launch(home, {"session_id": "sess-empty", "hermes_home": str(home)})
        self.assertEqual(out, NOTHING_SAID_LINE + "\n")

    def test_a_row_with_no_messages_gets_the_one_line(self) -> None:
        from omh.maintenance.hermes_resume import NOTHING_SAID_LINE

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-empty", turns=0, title=None)
            out = self._launch(home, {"session_id": "sess-empty", "hermes_home": str(home)})
        self.assertEqual(out, NOTHING_SAID_LINE + "\n")

    def test_the_recorded_home_is_read_rather_than_the_one_omh_named(self) -> None:
        # Hermes' launcher can pick a sticky active profile `omh` was not told about.
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            sticky = home / "profiles" / "sticky"
            sticky.mkdir(parents=True)
            write_card_session(home / "state.db", "sess-other")
            write_card_session(sticky / "state.db", "sess-alpha")
            out = self._launch(home, {"session_id": "sess-alpha", "hermes_home": str(sticky)})
        self.assertEqual(out, CARD_ALPHA)

    def test_an_untitled_session_says_so(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha", title=None)
            out = self._launch(home, {"session_id": "sess-alpha", "hermes_home": str(home)})
        self.assertEqual(out, "\nomh · untitled session\n\n  omh --resume sess-alpha\n\n")

    def test_the_card_is_the_title_and_the_resume_line_only(self) -> None:
        # No counts, tokens, model or `omh -c "<title>"`: a title a shell would read as options, or one another
        # session's `<title> #N` would shadow under Hermes' title lookup, changes nothing but the title line.
        from omh.maintenance.hermes_resume import exit_card_lines

        for title, others in (("-p work", []), ("Reply with ok", ["Reply with ok #2"]), ('Say "hi" for $5', [])):
            with self.subTest(title=title), TemporaryDirectory() as tmp:
                db = Path(tmp) / "state.db"
                write_card_session(db, "sess-alpha", title=title)
                for index, other in enumerate(others):
                    write_card_session(db, f"sess-other-{index}", title=other, started_at=CHILD_STARTED_AT + 5 + index)
                self.assertEqual(exit_card_lines(db, "sess-alpha"), [f"omh · {title}", "", "  omh --resume sess-alpha", ""])

    def test_a_long_id_is_printed_whole(self) -> None:
        # Hermes' newer stored ids are `local-<64 hex>`: the resume line is typed back, so it is never shortened,
        # whatever the terminal's width (the card is printed as lines; the terminal wraps them).
        from omh.maintenance.hermes_resume import exit_card_lines

        long_id = "local-" + "b3c800dd" * 8
        self.assertEqual(len(long_id), 70)
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            write_card_session(db, long_id)
            with patch.dict(os.environ, {"COLUMNS": "40"}):
                lines = exit_card_lines(db, long_id)
        self.assertEqual(lines, ["omh · Fix the login bug", "", f"  omh --resume {long_id}", ""])

    def test_after_new_the_newest_earlier_session_with_messages_gets_the_card(self) -> None:
        # `/new` just before quitting: the open session is empty, the one before it is what this launch said.
        from omh.maintenance.hermes_resume import NOTHING_SAID_LINE

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha")
            write_card_session(home / "state.db", "sess-blank", turns=0, title=None)
            fallen_back = self._launch(home, {"session_id": "sess-new", "hermes_home": str(home),
                                              "opened": ["sess-alpha", "sess-blank"]})
            all_empty = self._launch(home, {"session_id": "sess-new", "hermes_home": str(home),
                                            "opened": ["sess-blank", "sess-gone"]})
        self.assertEqual(fallen_back, CARD_ALPHA)
        self.assertEqual(all_empty, NOTHING_SAID_LINE + "\n")

    def test_an_unreadable_database_prints_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "state.db").write_bytes(b"not a database\n" * 64)
            out = self._launch(home, {"session_id": "sess-alpha", "hermes_home": str(home)})
        self.assertEqual(out, "")

    def test_an_id_a_shell_would_split_prints_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess alpha")
            out = self._launch(home, {"session_id": "sess alpha", "hermes_home": str(home)})
        self.assertEqual(out, "")

    def test_a_record_that_cannot_be_read_falls_back_to_the_end_stamps(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha")
            for record in ("not json", {"session_id": "sess-alpha", "hermes_home": "relative/home"},
                           {"session_id": "sess-alpha"}, ["sess-alpha"]):
                with self.subTest(record=record):
                    self.assertEqual(self._launch(home, record), CARD_ALPHA)

    def test_a_failed_exit_prints_no_card_even_with_a_record(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_card_session(home / "state.db", "sess-alpha")
            out = self._launch(home, {"session_id": "sess-alpha", "hermes_home": str(home)}, returncode=2)
        self.assertEqual(out, "")


class SubcommandRefusalTests(unittest.TestCase):
    """A bare-launch flag typed alongside a subcommand is named, not dropped."""

    def test_resume_with_a_subcommand_is_refused_by_name(self) -> None:
        status, _stdout, stderr = run_cli(["--resume", "sess-alpha", "doctor"])

        self.assertEqual(status, 2)
        self.assertIn("--resume", stderr)
        self.assertIn("doctor", stderr)

    def test_continue_with_a_subcommand_is_refused_by_name(self) -> None:
        status, _stdout, stderr = run_cli(["-c", "yesterday", "doctor"])

        self.assertEqual(status, 2)
        self.assertIn("--continue", stderr)

    def test_a_profile_with_a_subcommand_is_refused_by_name(self) -> None:
        status, _stdout, stderr = run_cli(["-p", "work", "doctor"])

        self.assertEqual(status, 2)
        self.assertIn("--profile", stderr)

    def test_a_valueless_continue_with_a_subcommand_is_refused(self) -> None:
        status, _stdout, stderr = run_cli(["--continue=", "doctor"])

        self.assertEqual(status, 2)
        self.assertIn("--continue", stderr)

    def test_continue_without_a_value_swallows_the_next_token(self) -> None:
        """Recorded, not endorsed: argparse gives an optional-value flag the
        next token, so `omh --continue doctor` continues a session named
        "doctor" instead of running the subcommand.

        Hermes' own `-c` behaves identically. It is left alone because a
        session may legitimately be named after a subcommand, so refusing the
        value would refuse a real continue. `--continue=<name>` and a
        subcommand on its own are both unambiguous.
        """
        parsed = build_parser().parse_args(["--continue", "doctor"])

        self.assertIsNone(parsed.command)
        self.assertEqual(parsed.tui_continue, "doctor")

    def test_the_homes_and_scope_options_still_reach_a_subcommand(self) -> None:
        # The refusal is scoped to the three bare-launch flags; the options
        # every subcommand honours are untouched.
        with TemporaryDirectory() as tmp:
            status, _stdout, _stderr = run_cli(["--hermes-home", tmp, "docs", "roles", "--check"])

        self.assertEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
