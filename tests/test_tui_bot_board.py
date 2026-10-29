"""The bot board (Ctrl+S, `/bots`): this machine's Hermes profiles, read-only, in the pager.

Fixture homes stand in for a real root: `default` with a gateway this very
process "runs" (its pid and start time), a connected Slack it stamped and a
Discord entry an older process left; `miku` whose record still says running
for a pid that is gone; `broken` with a record that is not JSON and no
state.db; `locked` whose state.db another connection holds exclusively; and
three directories that are no profile (hidden, no identity file, a deletion
tombstone). `default` also has a config.yaml (its model, memory limits and an
OMH store with two records) and a MEMORY.md; `SummaryTests` build the token
columns, memory files and configs the summaries read, and the shapes they must
refuse, in the same tree. The cases read them through the board's own readers, draw them at
a narrow and a wide width, drive the board's keys, open it from the app with
Ctrl+S and `/bots` (and not from inside Ctrl+R's search), and prove nothing is
written: every connection is `mode=ro`, the only signal is 0, and the tree's
bytes and times are what they were.
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from _test_temp_root import make_test_tempdir
from _tui_lines import line_text, lines_text
from test_tui_modes import make_app, type_text
from test_tui_muscle_memory import commands, send
from omh.plugin_bundle.omh import sqlite_readonly
from omh.tui import bot_board
from omh.tui.bot_board import (
    BOARD_TITLE,
    MESSAGE_ROWS_READ,
    BoardSnapshot,
    BoardView,
    BotBoard,
    board_homes,
    avatar,
    message_lines,
    profile_lines,
    read_board,
    read_gateway,
    read_messages,
    read_profile,
    read_sessions,
    session_lines,
    process_facts,
)
from omh.tui.history import HistorySearch
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, UP, Key
from omh.skin_pack import default_theme
from omh.tui.theme import (
    DEFAULT_THEME, EDGE_CONTRAST, LAUNCH_PRESETS, TEXT_CONTRAST, build_theme, contrast_ratio, is_light,
    with_launch_look,
)
from omh.tui.style import Span
from omh.tui.width import cluster_width, clusters, line_width

NOW = 1_800_000_000.0
DAY = 24 * 3600
CTRL_S = Key(CHAR, "s", ctrl=True)
GONE_PID = 4_194_301  # past macOS' pid range; `pid_exists` is patched where it matters
# The board probes a gateway pid on POSIX only (the OMH TUI needs termios); off it no gateway ever reads as running.
POSIX_ONLY = unittest.skipUnless(os.name == "posix", "the board's liveness probe is POSIX-only")


def write_store(home: Path, sessions: list[tuple], messages: list[tuple] = (), *, wal: bool = False) -> Path:
    """A state.db with the columns the board reads: (id, source, title, started, last activity, count) rows."""
    path = home / "state.db"
    connection = sqlite3.connect(path)
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, display_name TEXT, "
        "started_at REAL NOT NULL, ended_at REAL, last_activity_at REAL, message_count INTEGER DEFAULT 0);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, "
        "content TEXT, tool_name TEXT, tool_calls TEXT, timestamp REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);"
    )
    connection.executemany(
        "INSERT INTO sessions (id, source, title, started_at, last_activity_at, message_count) VALUES (?, ?, ?, ?, ?, ?)",
        sessions,
    )
    connection.executemany(
        "INSERT INTO messages (session_id, role, content, tool_name, tool_calls, timestamp, active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        messages,
    )
    connection.commit()
    connection.close()
    return path


USAGE_COLUMNS = (
    "model TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, "
    "estimated_cost_usd REAL, actual_cost_usd REAL, cost_status TEXT"
)


def write_usage_store(home: Path, sessions: list[tuple], columns: str = USAGE_COLUMNS) -> Path:
    """A state.db as Hermes writes one now: (id, source, title, last activity, count, *the `columns`) rows."""
    path = home / "state.db"
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, display_name TEXT, "
        f"started_at REAL NOT NULL, ended_at REAL, last_activity_at REAL, message_count INTEGER DEFAULT 0, {columns});"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, "
        "content TEXT, tool_name TEXT, tool_calls TEXT, timestamp REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);"
    )
    names = [column.split()[0] for column in columns.split(", ")]
    marks = ", ".join("?" * (6 + len(names)))
    connection.executemany(
        f"INSERT INTO sessions (id, source, title, started_at, last_activity_at, message_count, {', '.join(names)}) "
        f"VALUES ({marks})",
        [(row[0], row[1], row[2], row[3] - 60, row[3], row[4], *row[5:]) for row in sessions],
    )
    connection.commit()
    connection.close()
    return path


def write_memory(home: Path, name: str, entries: list[str] | bytes) -> Path:
    path = home / "memories" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(entries if isinstance(entries, bytes) else "\n§\n".join(entries).encode("utf-8"))
    return path


ROOT_CONFIG = """model:
  provider: claude-proxy
  default: claude-opus-5-5
memory:
  memory_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
plugins:
  entries:
    omh:
      settings:
        omh_home: omh-store
"""


def write_record(home: Path, record: dict | str) -> None:
    text = record if isinstance(record, str) else json.dumps(record)
    (home / "gateway_state.json").write_text(text, encoding="utf-8")


def make_root(root: Path) -> None:
    pid, started = os.getpid(), process_facts(os.getpid())[0]
    write_record(root, {
        "pid": pid, "start_time": started, "hermes_home": str(root), "gateway_state": "running",
        "active_agents": 2, "served_profiles": ["default"],
        "platforms": {
            "slack": {"state": "connected", "writer_pid": pid, "writer_start_time": started},
            "discord": {"state": "connected", "writer_pid": GONE_PID, "writer_start_time": 1},
        },
    })
    write_store(
        root,
        [
            ("s-new", "slack", "Release notes", NOW - 3 * DAY, NOW - 600, 12),
            ("s-old", "slack", None, NOW - 30 * DAY, None, 4),
            ("s-cli", "cli", "Local run", NOW - 2 * DAY, NOW - 2 * DAY, 2),
            ("s-child", "subagent", "child", NOW - 700, NOW - 700, 3),
        ],
        [
            ("s-new", "user", "ship it?", None, None, NOW - 900, 1),
            ("s-new", "assistant", "\x1b[31mred\x1b[0m done \x1b]0;pwned\x07now", None, None, NOW - 800, 1),
            ("s-new", "assistant", "", None, json.dumps([{"function": {"name": "terminal"}}]), NOW - 700, 1),
            ("s-new", "tool", "exit 0", "terminal", None, NOW - 650, 1),
            ("s-new", "user", "compacted away", None, None, NOW - 640, 0),
        ],
    )
    (root / "config.yaml").write_text(ROOT_CONFIG, encoding="utf-8")
    write_memory(root, "MEMORY.md", ["User ships on Fridays", "  Prefers short answers  "])
    records = root / "omh-store" / "memory" / "records"
    records.mkdir(parents=True)
    for name in ("mem_a.json", "mem_b.json", "notes.txt"):
        (records / name).write_text("{}", encoding="utf-8")
    profiles = root / "profiles"
    miku = profiles / "miku"
    miku.mkdir(parents=True)
    write_record(miku, {
        "pid": GONE_PID, "start_time": 1, "hermes_home": str(miku), "gateway_state": "running",
        "platforms": {"slack": {"state": "connected", "writer_pid": GONE_PID, "writer_start_time": 1}},
    })
    write_store(miku, [(f"m-{n}", "slack", f"chat {n}", NOW - 20 * DAY, NOW - 19 * DAY, 5) for n in range(3)], wal=True)
    broken = profiles / "broken"
    broken.mkdir()
    (broken / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    write_record(broken, "{not json")
    locked = profiles / "locked"
    locked.mkdir()
    write_record(locked, {"pid": GONE_PID, "gateway_state": "stopped", "exit_reason": "signal"})
    write_store(locked, [("l-1", "cli", "x", NOW, NOW, 1)], wal=True)
    (profiles / ".hidden").mkdir()
    (profiles / ".hidden" / "config.yaml").write_text("", encoding="utf-8")
    (profiles / "ghost").mkdir()  # no identity file: a cron heartbeat's leftover, never a profile
    (profiles / "gone").mkdir()
    (profiles / "gone" / "config.yaml").write_text("", encoding="utf-8")
    (profiles / ".deleted" / "gone").mkdir(parents=True)


def tree_state(root: Path) -> dict[str, tuple[int, int]]:
    """Every file under `root` with its size and modification time."""
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*")) if path.is_file()
    }


class FixtureRoot(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(make_test_tempdir("omh-bot-board-")))
        make_root(self.root)
        self.environ = {"HERMES_HOME": str(self.root)}


class HomesTests(FixtureRoot):
    def test_the_root_and_each_named_profile_and_nothing_that_is_no_profile(self) -> None:
        current, homes = board_homes(self.environ)
        self.assertEqual(current, self.root)
        self.assertEqual([name for name, _home in homes], ["default", "broken", "locked", "miku"])

    def test_a_profile_home_finds_its_root_and_is_the_one_marked_as_this_tui(self) -> None:
        environ = {"HERMES_HOME": str(self.root / "profiles" / "miku")}
        current, homes = board_homes(environ)
        self.assertEqual(homes[0], ("default", self.root))
        snapshot = read_board(environ, BoardView(), NOW)
        self.assertEqual([profile.name for profile in snapshot.profiles if profile.this_tui], ["miku"])

    def test_without_hermes_home_it_is_hermes_own_default_under_home(self) -> None:
        current, homes = board_homes({"HOME": str(self.root)})
        self.assertEqual(current, self.root / ".hermes")
        self.assertEqual(homes, [("default", self.root / ".hermes")])
        self.assertEqual(board_homes({}), (None, []))


class GatewayTests(FixtureRoot):
    @POSIX_ONLY
    def test_a_running_record_whose_process_runs_reads_as_running_with_its_own_platforms(self) -> None:
        gateway = read_gateway(self.root)
        self.assertTrue(gateway.live)
        self.assertEqual((gateway.state, gateway.pid, gateway.active_agents), ("running", os.getpid(), 2))
        platforms = {platform.name: platform.current for platform in gateway.platforms}
        self.assertEqual(platforms, {"discord": False, "slack": True}, "an entry another process stamped is old news")

    def test_a_running_record_whose_pid_is_gone_does_not_read_as_running(self) -> None:
        gateway = read_gateway(self.root / "profiles" / "miku")
        self.assertEqual(gateway.state, "running")
        self.assertFalse(gateway.live)
        self.assertEqual([platform.current for platform in gateway.platforms], [False])

    @POSIX_ONLY
    def test_a_pid_the_os_gave_to_another_process_does_not_read_as_running(self) -> None:
        record = json.loads((self.root / "gateway_state.json").read_text(encoding="utf-8"))
        for start, live in ((record["start_time"] + 10_000, False), (record["start_time"] + 150, True), (None, True)):
            with self.subTest(start=start):
                write_record(self.root, {**record, "start_time": start})
                self.assertIs(read_gateway(self.root).live, live)

    def test_a_record_naming_another_home_does_not_read_as_running_and_says_why(self) -> None:
        record = json.loads((self.root / "gateway_state.json").read_text(encoding="utf-8"))
        write_record(self.root, {**record, "hermes_home": "/srv/container/hermes"})
        gateway = read_gateway(self.root)
        self.assertEqual((gateway.live, gateway.elsewhere), (False, "/srv/container/hermes"))
        lines, _span = profile_lines(snapshot(self.environ).profiles, 0, NOW, 300, DEFAULT_THEME)  # boxes of 149
        text = "\n".join(lines_text(lines))
        self.assertIn("gateway not running here · its record is another home's (/srv/container/hermes)", text)
        self.assertNotIn(f"pid {os.getpid()} is gone", text, "its pid may well be alive: that is not the reason")

    def test_off_posix_nothing_is_probed_and_nothing_reads_as_running(self) -> None:
        # The module's flag, not `os.name`: Python 3.11's pathlib reads `os.name` to build every `Path`.
        with patch.object(bot_board, "ON_POSIX", False), patch.object(bot_board, "pid_exists") as probe:
            self.assertFalse(bot_board.process_is_record(os.getpid(), 1))
            self.assertFalse(read_gateway(self.root).live)
        probe.assert_not_called()

    @POSIX_ONLY
    def test_a_zombie_or_an_unreadable_start_time_does_not_read_as_running(self) -> None:
        record = json.loads((self.root / "gateway_state.json").read_text(encoding="utf-8"))
        started = record["start_time"]
        for facts, recorded, live in (
            ((started, True), started, False),  # a zombie: Hermes' `_pid_exists` calls it dead
            ((None, False), started, False),  # another user's process whose start time cannot be read
            ((None, False), None, True),  # a record without a start time is taken on its pid
        ):
            with self.subTest(facts=facts, recorded=recorded):
                write_record(self.root, {**record, "start_time": recorded})
                with patch.object(bot_board, "process_facts", return_value=facts):
                    self.assertIs(read_gateway(self.root).live, live)

    @POSIX_ONLY
    def test_the_start_time_of_another_users_process_is_read(self) -> None:
        # pid 1 runs as root: macOS' `proc_pidinfo` answers nothing for it, `sysctl(KERN_PROC_PID)` does.
        start, zombie = bot_board.process_facts(1)
        if sys.platform in ("darwin", "linux"):
            self.assertIsInstance(start, int)
        self.assertFalse(zombie)

    @POSIX_ONLY
    def test_a_zombie_child_reads_as_one(self) -> None:
        if sys.platform not in ("darwin", "linux"):
            self.skipTest("no zombie reader on this platform")
        child = os.fork()
        if child == 0:
            os._exit(0)
        self.addCleanup(os.waitpid, child, 0)
        deadline = time.monotonic() + 5
        while not bot_board.process_facts(child)[1] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(bot_board.process_facts(child)[1])
        self.assertTrue(bot_board.pid_exists(child), "signal 0 still answers for a zombie")
        self.assertFalse(bot_board.process_is_record(child, None))

    def test_a_missing_or_corrupt_record_says_so(self) -> None:
        self.assertEqual(read_gateway(self.root / "profiles" / "broken").problem, "gateway record unreadable")
        self.assertEqual(read_gateway(self.root / "profiles" / "ghost").problem, "no gateway record")
        write_record(self.root, "[1, 2]")
        self.assertEqual(read_gateway(self.root).problem, "gateway record unreadable")

    def test_odd_values_in_a_record_never_raise(self) -> None:
        write_record(self.root, '{"pid": 100000000000000000000, "start_time": NaN, "gateway_state": "running"}')
        self.assertFalse(read_gateway(self.root).live)
        write_record(self.root, "[" * 200_000)
        self.assertEqual(read_gateway(self.root).problem, "gateway record unreadable")

    def test_no_pid_below_two_is_ever_probed(self) -> None:
        probed: list[int] = []
        with patch.object(bot_board, "pid_exists", side_effect=lambda pid: probed.append(pid) or True):
            for pid in (0, -1, 1, True, "97968"):
                write_record(self.root, {"pid": pid, "gateway_state": "running"})
                self.assertFalse(read_gateway(self.root).live)
        self.assertEqual(probed, [])


class StoreTests(FixtureRoot):
    def test_sessions_are_counted_by_source_with_the_last_day_active_ones_and_the_last_activity(self) -> None:
        profile = read_profile("default", self.root, self.root, NOW)
        self.assertEqual(profile.store, "")
        self.assertEqual(dict(profile.sources), {"slack": 2, "cli": 1, "subagent": 1})
        self.assertEqual(profile.active, 2, "s-new (10 min) and s-child (12 min); s-cli is two days old")
        self.assertEqual(profile.last_activity, NOW - 600)

    def test_open_sessions_days_old_are_not_active(self) -> None:
        profile = read_profile("miku", self.root / "profiles" / "miku", None, NOW)
        self.assertEqual((profile.sources, profile.active), ((("slack", 3),), 0))

    def test_a_locked_store_reads_as_busy_and_does_not_wait(self) -> None:
        holder = sqlite3.connect(self.root / "profiles" / "locked" / "state.db", isolation_level=None)
        self.addCleanup(holder.close)
        holder.execute("PRAGMA locking_mode=EXCLUSIVE")
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("INSERT INTO sessions (id, source, started_at) VALUES ('l-2', 'cli', 0)")
        started = time.monotonic()
        profile = read_profile("locked", self.root / "profiles" / "locked", None, NOW)
        self.assertEqual(profile.store, "state.db busy")
        self.assertLess(time.monotonic() - started, 2.0)

    def test_a_missing_store_says_so_and_is_never_created(self) -> None:
        home = self.root / "profiles" / "broken"
        self.assertEqual(read_profile("broken", home, None, NOW).store, "no state.db")
        self.assertEqual(read_sessions(home)[2], "no state.db")
        self.assertFalse((home / "state.db").exists())

    def test_the_sessions_list_newest_activity_first_without_delegated_children(self) -> None:
        sessions, unlisted, problem = read_sessions(self.root)
        self.assertEqual(([row.id for row in sessions], unlisted, problem), (["s-new", "s-cli", "s-old"], 1, ""))
        self.assertEqual(sessions[2].last_activity, NOW - 30 * DAY, "no last_activity_at: its start")

    def test_messages_are_the_live_tail_oldest_first_with_escapes_and_controls_gone(self) -> None:
        messages, session, problem = read_messages(self.root, "s-new")
        self.assertEqual((problem, session.title, session.message_count), ("", "Release notes", 12))
        self.assertEqual(
            [(row.role, row.text) for row in messages],
            [("user", "ship it?"), ("assistant", "red done now"), ("assistant", "(calls terminal)"),
             ("tool", "terminal: exit 0")],
        )

    def test_text_that_is_not_utf8_is_shown_replaced_not_dropped(self) -> None:
        connection = sqlite3.connect(self.root / "state.db")
        connection.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s-new', 'user', "
                           "CAST(X'6f6bff21' AS TEXT), ?)", (NOW,))
        connection.commit()
        connection.close()
        messages, _session, problem = read_messages(self.root, "s-new")
        self.assertEqual((problem, messages[-1].text), ("", "ok\ufffd!"))

    def test_the_tail_is_bounded(self) -> None:
        write_store(self.root / "profiles" / "broken", [("b", "cli", "b", NOW, NOW, 99)],
                    [("b", "user", f"line {n} " + "x" * 5000, None, None, NOW + n, 1) for n in range(99)])
        messages, _session, _problem = read_messages(self.root / "profiles" / "broken", "b")
        self.assertEqual(len(messages), MESSAGE_ROWS_READ)
        self.assertTrue(messages[-1].text.startswith("line 98 "))
        self.assertLessEqual(max(len(row.text) for row in messages), bot_board.MESSAGE_CHARS_READ)


class ReadOnlyTests(FixtureRoot):
    def test_the_store_itself_is_never_opened_outside_sqlite(self) -> None:
        # Closing any descriptor on a store drops every SQLite lock this process holds on it (POSIX record locks
        # are per process), the HUD reader's included, so the board decides how to open it from the names beside it.
        opened: list[str] = []
        real_open, real_io_open = os.open, bot_board.Path.open

        def os_open(path, *args, **kwargs):
            opened.append(str(path))
            return real_open(path, *args, **kwargs)

        def path_open(self, *args, **kwargs):
            opened.append(str(self))
            return real_io_open(self, *args, **kwargs)

        with patch.object(os, "open", side_effect=os_open), patch.object(bot_board.Path, "open", path_open):
            for view in (BoardView(), BoardView("default"), BoardView("default", "s-new"), BoardView("miku")):
                read_board(self.environ, view, NOW)
        self.assertEqual([path for path in opened if path.endswith("state.db")], [])
        self.assertTrue([path for path in opened if path.endswith("gateway_state.json")], "the probe saw the reads")


    def test_a_wal_store_a_writer_has_open_is_read_with_what_the_writer_committed(self) -> None:
        writer = sqlite3.connect(self.root / "profiles" / "miku" / "state.db")
        self.addCleanup(writer.close)
        writer.execute("INSERT INTO sessions (id, source, started_at) VALUES ('m-new', 'slack', ?)", (NOW,))
        writer.commit()
        self.assertTrue((self.root / "profiles" / "miku" / "state.db-wal").exists())
        profile = read_profile("miku", self.root / "profiles" / "miku", None, NOW)
        self.assertEqual((profile.sources, profile.active), ((("slack", 4),), 1))

    @POSIX_ONLY
    def test_the_board_opens_no_write_connection_sends_only_signal_zero_and_changes_no_file(self) -> None:
        before = tree_state(self.root)
        connects: list[tuple[str, dict]] = []
        signals: list[tuple[int, int]] = []
        real_connect, real_kill = sqlite3.connect, os.kill

        def connect(database, *args, **options):
            connects.append((str(database), options))
            return real_connect(database, *args, **options)

        def kill(pid, signal):
            signals.append((pid, signal))
            return real_kill(pid, signal) if signal == 0 else None

        with patch.object(sqlite_readonly.sqlite3, "connect", side_effect=connect), patch.object(os, "kill", side_effect=kill):
            for view in (BoardView(), BoardView("default"), BoardView("default", "s-new"), BoardView("miku"),
                         BoardView("locked"), BoardView("broken"), BoardView("broken", "nope")):
                read_board(self.environ, view, NOW)
        self.assertTrue(connects)
        for database, options in connects:
            self.assertTrue(database.startswith("file:"), database)
            self.assertIn(database.rsplit("?", 1)[1], ("mode=ro", "mode=ro&immutable=1"))
            self.assertIs(options.get("uri"), True)
        self.assertTrue(signals)
        self.assertEqual({signal for _pid, signal in signals}, {0})
        self.assertEqual(tree_state(self.root), before)


HEAD = bot_board.BOARD_HEAD_ROWS
BOX_CORNERS = {"unicode": "╮", "ascii": "+"}  # a box's top-right corner in each charset  # level 1's totals box and the gap after it


def field(rows: list[str], label: str, separator: str = "│") -> str:
    """The words of the first box cell, in any row, whose words begin with `label`; "" when there is none."""
    for row in rows:
        for cell in row.split(separator)[1:-1]:
            words = squeeze(cell)
            if words == label or words.startswith(label + " "):
                return words
    return ""


def field_row(rows: list[str], label: str, separator: str = "│") -> int:
    """The index of the row holding the cell `field` finds."""
    return next(index for index, row in enumerate(rows) if field([row], label, separator))


def gauge(percent: int, cells: int) -> str:
    return "▰" * cells + "▱" * (10 - cells) + f" {percent}%"


class SummaryTests(FixtureRoot):
    """The model, token, memory and gateway summaries: what each reads, and what it says when it cannot."""

    def profile(self, name: str = "default"):
        home = self.root if name == "default" else self.root / "profiles" / name
        return read_profile(name, home, self.root, NOW)

    def row(self, profile, name: str, cols: int = 400) -> str:
        """`profile`'s card on level 1: its top or bottom edge, or the cell labelled `name`, padding squeezed."""
        lines, _span = profile_lines([profile], 0, NOW, cols, DEFAULT_THEME)
        text = lines_text(lines)[HEAD:]
        if name == "top":
            return squeeze(text[0])
        if name == "bottom":
            return squeeze(next(row for row in text if row.startswith(("╰", "+"))))
        return field(text, {"day": "24 h"}.get(name, name))

    def detail(self, name: str = "default") -> str:
        """Level 2's box for the profile, its rows squeezed and joined."""
        lines, _span = session_lines(snapshot(self.environ, BoardView(name)), 0, NOW, 400, DEFAULT_THEME)
        text = lines_text(lines)
        return "\n".join(squeeze(row) for row in text[: text.index("")])

    def test_the_configured_model_and_the_one_the_newest_session_ran(self) -> None:
        write_usage_store(self.root, [
            ("new", "slack", "t", NOW - 60, 2, "z-ai/glm-5.3", 10, 5, 0, 0.01, None, "estimated"),
            ("child", "subagent", "t", NOW - 10, 2, "child-model", 10, 5, 0, 0.0, None, "included"),
            ("old", "cli", "t", NOW - 3 * DAY, 2, "claude-opus-5-5", 10, 5, 0, 0.0, None, "included"),
        ])
        profile = self.profile()
        self.assertEqual((profile.model, profile.provider, profile.newest.model), ("claude-opus-5-5", "claude-proxy", "z-ai/glm-5.3"))
        self.assertEqual(self.row(profile, "now"), "now t slack · 1m ago", "its newest session but delegated children")
        self.assertEqual(self.row(profile, "model"), "model claude-opus-5-5 claude-proxy · newest z-ai/glm-5.3")
        write_usage_store(self.root, [("same", "cli", "t", NOW - 60, 2, "claude-opus-5-5", 1, 1, 0, None, None, None)])
        self.assertEqual(self.row(self.profile(), "model"), "model claude-opus-5-5 claude-proxy", "said once")

    def test_a_model_written_as_a_string_or_not_at_all(self) -> None:
        for config, model in (
            ("model: gpt-5.5\n", "gpt-5.5"), ("model:\n  model: kimi-k3\n", "kimi-k3"), ("agent: {}\n", ""),
            ("model: {}\n", ""),  # an empty mapping, as Hermes reads it: no model
        ):
            with self.subTest(config=config):
                (self.root / "config.yaml").write_text(config, encoding="utf-8")
                self.assertEqual((self.profile().model, self.profile().config), (model, ""))
        self.assertEqual(self.row(self.profile(), "model"), "model no default model configured")

    def test_a_config_it_cannot_read_says_so_and_names_no_model_or_limit(self) -> None:
        config = self.root / "config.yaml"
        for content, said in (
            (b"model:\n\tdefault: tabbed\n", "config.yaml unreadable"),  # YAML indents with spaces
            (b"model:\n  default: \xff\xfe\n", "config.yaml unreadable"),
            (b"model: {default: inline}\n", "config.yaml unreadable"),  # a flow mapping the scan does not follow
            (b"#" * (bot_board.CONFIG_BYTES + 1), "config.yaml too large to read (1 MB)"),
        ):
            with self.subTest(said=said, size=len(content)):
                config.write_bytes(content)
                profile = self.profile()
                self.assertEqual((profile.config, profile.model), (said, ""))
                self.assertEqual(self.row(profile, "model"), f"model {said}")
        config.unlink()
        profile = self.profile()
        self.assertEqual(profile.config, "no config.yaml")
        self.assertEqual([memory.limit for memory in profile.memory], [None, None])
        self.assertIsNone(profile.omh_records, "no config: no store is named, and none is guessed")

    def test_the_active_sessions_tokens_and_only_the_cost_hermes_priced(self) -> None:
        write_usage_store(self.root, [
            ("a", "slack", "t", NOW - 60, 2, "m", 1_000_000, 200_000, 12_400_000, 1.5, 4.0, "actual"),
            ("b", "slack", "t", NOW - 120, 2, "m", 200_000, 34_500, 0, 0.12, None, "estimated"),
            ("c", "cli", "t", NOW - 180, 2, "m", 50_000, 10_000, 0, 0.0, None, "unknown"),
            ("d", "cli", "t", NOW - 240, 2, "m", 1_000, 0, 0, 0.0, None, "included"),
            ("e", "cli", "t", NOW - 300, 2, "m", 0, 0, 0, None, None, None),  # nothing used yet: not unpriced
            ("old", "cli", "t", NOW - 3 * DAY, 2, "m", 9_000_000, 9_000_000, 0, 99.0, None, "estimated"),
        ])
        profile = self.profile()
        self.assertEqual(profile.active, 5)
        self.assertEqual(profile.usage, bot_board.Usage(1_251_000, 244_500, 12_400_000, 4.12, True, 1, 1))
        self.assertTrue(self.row(profile, "day").endswith(" 5 active · 6 stored"))
        self.assertEqual(self.row(profile, "tokens"), "tokens lifetime 1.3M in · 244.5k out · 12.4M cached")
        self.assertEqual(self.row(profile, "cost"), "cost lifetime ~$4.12 + 1 unpriced")

    def test_a_cost_hermes_never_priced_is_never_shown_as_zero(self) -> None:
        for statuses, said in (
            (("unknown", "unknown"), "cost unknown"), (("included", "included"), "included"),
            (("actual", "actual"), "$0.00"), ((None, None), "cost unknown"),
        ):
            with self.subTest(statuses=statuses):
                write_usage_store(self.root, [
                    (f"s{n}", "cli", "t", NOW - 60, 2, "m", 10, 10, 0, 0.0, None, status) for n, status in enumerate(statuses)
                ])
                self.assertEqual(self.row(self.profile(), "tokens"), "tokens lifetime 20 in · 20 out · 0 cached")
                self.assertEqual(self.row(self.profile(), "cost"), f"cost lifetime {said}")

    def test_older_stores_without_the_columns_show_less_and_no_number_they_lack(self) -> None:
        # The fixture's own store has no model, token or cost column at all.
        profile = self.profile()
        self.assertEqual((profile.usage, profile.newest.model, profile.hourly), (None, "", ()))
        self.assertEqual(self.row(profile, "now"), "now Release notes slack · 10m ago")
        self.assertEqual(self.row(profile, "model"), "model claude-opus-5-5 claude-proxy")
        self.assertEqual(self.row(profile, "day"), "24 h 2 active · 4 stored", "no sparkline drawn flat")
        self.assertEqual((self.row(profile, "tokens"), self.row(profile, "cost")), ("", ""), "and no tokens or cost")
        sessions = snapshot(self.environ, BoardView("default"))
        self.assertEqual((sessions.sessions[0].model, sessions.sessions[0].usage), ("", None))
        rows = lines_text(session_lines(sessions, 0, NOW, 150, DEFAULT_THEME)[0])[-1 - len(sessions.sessions):-1]
        self.assertEqual(squeeze(rows[0]), "│ ❯ Release notes │ slack 10m ago 12 │", "no model or token column")
        tail = snapshot(self.environ, BoardView("default", "s-new"))
        head = lines_text(message_lines(tail, tail.sessions[0], NOW, 150, DEFAULT_THEME))
        self.assertEqual(head.index(""), 3, "the session's box has its facts row only: no model, no tokens")
        write_usage_store(self.root, [("t", "cli", "t", NOW - 60, 2, 5, 7)], "input_tokens INTEGER, output_tokens INTEGER")
        profile = self.profile()
        self.assertEqual(profile.usage, bot_board.Usage(5, 7, None, None, False, 0, 1))
        self.assertEqual(self.row(profile, "tokens"), "tokens lifetime 5 in · 7 out", "no cache read column")
        self.assertEqual(self.row(profile, "cost"), "cost lifetime cost unknown")

    def test_levels_two_and_three_show_each_sessions_model_tokens_and_cost(self) -> None:
        write_usage_store(self.root, [
            ("a", "slack", "Release notes", NOW - 60, 12, "anthropic/claude-opus-5-5", 325_170, 89_019, 12_469_303, 0.4321, None, "estimated"),
            ("b", "cli", "Probe", NOW - 120, 2, "glm-5.3", 192, 67_200, 0, 0.0, None, "unknown"),
        ])
        sessions = snapshot(self.environ, BoardView("default"))
        rows = lines_text(session_lines(sessions, 0, NOW, 150, DEFAULT_THEME)[0])[-3:-1]
        self.assertEqual(squeeze(rows[0]), "│ ❯ Release notes │ claude-opus-5-5 325.2k 89k ~$0.43 slack 1m ago 12 │")
        self.assertEqual(squeeze(rows[1]), "│ Probe │ glm-5.3 192 67.2k cli 2m ago 2 │", "no unpriced cost")
        tail = snapshot(self.environ, BoardView("default", "a"))
        head = lines_text(message_lines(tail, tail.sessions[0], NOW, 150, DEFAULT_THEME))[:4]
        self.assertEqual(squeeze(head[2]), "│ anthropic/claude-opus-5-5 · 325.2k in · 89k out · 12.5M cache read · ~$0.43 │")

    def test_memory_is_counted_as_hermes_counts_it_against_the_configured_limits(self) -> None:
        memory, user = self.profile().memory
        joined = len("User ships on Fridays\n§\nPrefers short answers")  # entries stripped, joined by the delimiter
        self.assertEqual(memory, bot_board.MemoryFile("memory", 2, joined, 2200, True))
        self.assertEqual(user, bot_board.MemoryFile("user", 0, 0, 1375, True), "no USER.md yet: empty")
        percent = joined * 100 // 2200
        self.assertEqual(self.row(self.profile(), "memory"), f"memory {gauge(percent, 1)}")
        self.assertEqual(self.row(self.profile(), "user"), f"user {gauge(0, 0)}")
        self.assertEqual(self.row(self.profile(), "OMH"), "OMH 2 records")
        detail = self.detail()
        self.assertIn(f"memory {gauge(percent, 1)} 2 entries · {joined}/2,200 chars", detail, "the exact numbers are level 2's")
        self.assertIn(f"user {gauge(0, 0)} 0 entries · 0/1,375 chars", detail)
        write_memory(self.root, "USER.md", ["x" * 1400])
        lines, _span = profile_lines([self.profile()], 0, NOW, 400, DEFAULT_THEME)
        over = next(span for span in lines[field_row(lines_text(lines), "user")] if span.text.endswith(" 101%"))
        self.assertIs(over.style, DEFAULT_THEME.error, "past its limit")

    def test_memory_gauges_are_coloured_by_how_full_they_are(self) -> None:
        theme = DEFAULT_THEME
        for chars, cells, style in ((0, 0, theme.ok), (40, 1, theme.ok), (690, 6, theme.ok), (700, 7, theme.warn),
                                    (890, 8, theme.warn), (900, 9, theme.warn), (910, 9, theme.error), (1200, 10, theme.error)):
            with self.subTest(chars=chars):
                spans = bot_board._gauge(bot_board.MemoryFile("memory", 3, chars, 1000), theme, "unicode")
                self.assertEqual(line_text(spans), gauge(chars // 10, cells))
                self.assertIs(spans[-1].style, style)
                self.assertIs(spans[1].style, theme.dim, "the empty cells stay quiet")

    def test_memory_that_is_off_unreadable_or_huge_says_so_without_counting(self) -> None:
        config = ROOT_CONFIG.replace("memory_enabled: true", "memory_enabled: false")
        (self.root / "config.yaml").write_text(config.replace("  user_char_limit: 1375\n", ""), encoding="utf-8")
        write_memory(self.root, "USER.md", b"caf\xe9")
        self.assertEqual((self.row(self.profile(), "memory"), self.row(self.profile(), "user")), ("memory off", "user unreadable"))
        write_memory(self.root, "USER.md", ["a", "b"])
        self.assertEqual(self.row(self.profile(), "user"), "user 2 entries", "no limit: no gauge")
        huge = write_memory(self.root, "MEMORY.md", b"x" * (2 * bot_board.MEMORY_FILE_BYTES))
        (self.root / "config.yaml").write_text(ROOT_CONFIG, encoding="utf-8")
        read: list[int] = []
        real_open = bot_board.Path.open

        def path_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            if path == huge:
                real_read = handle.read
                handle.read = lambda size=-1: read.append(size) or real_read(size)
            return handle

        with patch.object(bot_board.Path, "open", path_open):
            memory = self.profile().memory[0]
        self.assertEqual((memory.problem, memory.entries), ("too large to read (2 MB)", 0))
        self.assertEqual(read, [bot_board.MEMORY_FILE_BYTES + 1], "one bounded read")
        self.assertEqual(self.row(self.profile(), "memory"), "memory too large to read (2 MB)")

    def test_the_omh_store_is_the_one_config_names_and_only_regular_json_files_count(self) -> None:
        records = self.root / "omh-store" / "memory" / "records"
        with contextlib.suppress(OSError):  # Windows without the symlink privilege: the count is the same
            (records / "linked.json").symlink_to(records / "mem_a.json")
        (records / "dir.json").mkdir()
        self.assertEqual(self.profile().omh_records, 2)
        for setting, records_seen, said in (
            ("$HERMES_HOME/omh-store", 2, ""),
            ("${OMH_SECRET}/store", None, "OMH store not resolvable"),  # read from no environment
            (str(self.root / "nowhere"), None, "OMH store not found"),
            (str(self.root), 0, ""),  # a store with no records yet
        ):
            with self.subTest(setting=setting):
                (self.root / "config.yaml").write_text(ROOT_CONFIG.replace("omh-store", setting), encoding="utf-8")
                profile = self.profile()
                self.assertEqual((profile.omh_records, profile.omh), (records_seen, said))
        (self.root / "config.yaml").write_text(ROOT_CONFIG.split("plugins:")[0], encoding="utf-8")
        self.assertEqual(self.row(self.profile(), "OMH"), "", "no setting: no store named, ~/.omh not guessed")

    @POSIX_ONLY
    def test_a_live_gateway_shows_its_uptime_agents_and_memory_and_level_two_its_record(self) -> None:
        record = json.loads((self.root / "gateway_state.json").read_text(encoding="utf-8"))
        # 75 s before the board's clock (NOW is 2027-01-15 08:00:00 UTC).
        write_record(self.root, {**record, "updated_at": "2027-01-15T07:58:45Z", "restart_requested": True})
        now = time.time()
        gateway = read_gateway(self.root, now)
        self.assertEqual((gateway.live, gateway.updated, gateway.restart_requested), (True, NOW - 75, True))
        bot = self.row(self.profile(), "top")
        self.assertIn("restart requested", self.row(self.profile(), "bottom"))
        self.assertNotIn(f"pid {os.getpid()}", bot, "the pid is level 2's")
        self.assertIn(f"gateway running · pid {os.getpid()} · 2 agents running · updated 1m ago", self.detail())
        self.assertIn("restart requested", self.detail().splitlines()[-1], "in the bottom edge")
        if sys.platform not in ("darwin", "linux"):
            self.assertEqual((gateway.started, gateway.rss), (None, None))
            return
        # The record's start time is this process's own: its age is this process's.
        self.assertLess(abs(gateway.started - bot_board.started_at(bot_board.process_facts(os.getpid())[0], now)), 5)
        self.assertLess(now - gateway.started, 7 * DAY, "this test process started recently")
        self.assertGreater(gateway.rss, 1 << 20, "this process holds more than a megabyte")
        self.assertRegex(bot, r"up \S+( \S+)? · 2 agents · [\d.]+ [KMG]B ─╮$")

    def test_a_gateway_that_is_not_running_says_so_and_level_two_how_old_its_record_is(self) -> None:
        miku = self.root / "profiles" / "miku"
        record = json.loads((miku / "gateway_state.json").read_text(encoding="utf-8"))
        write_record(miku, {**record, "updated_at": NOW - 3 * DAY})
        with patch.object(bot_board, "resident_bytes") as rss:
            top, bottom = self.row(self.profile("miku"), "top"), self.row(self.profile("miku"), "bottom")
        rss.assert_not_called()
        self.assertTrue(top.startswith("╭──────────┬─ ◌ miku ─") and top.endswith("──╮"), "no running gateway: no facts on top")
        self.assertNotIn(" up ", top)
        self.assertIn("its record still says running (pid 4194301 is gone) slack ○", bottom)
        self.assertIn("its record still says running (pid 4194301 is gone) · updated 3d ago", self.detail("miku"))
        self.assertIn("slack ○", self.detail("miku").splitlines()[-1], "a platform as last recorded, in the bottom edge")

    def test_the_sparkline_is_the_active_sessions_tokens_by_hour(self) -> None:
        write_usage_store(self.root, [
            ("now", "cli", "t", NOW - 60, 2, "m", 80, 20, 0, None, None, None),
            ("three", "cli", "t", NOW - 3 * 3600 - 60, 2, "m", 50, 0, 0, None, None, None),
            ("also", "cli", "t", NOW - 3 * 3600 - 120, 2, "m", 0, 0, 0, None, None, None),
            ("old", "cli", "t", NOW - 25 * 3600, 2, "m", 9_000, 0, 0, None, None, None),
        ])
        hourly = self.profile().hourly
        self.assertEqual((len(hourly), hourly[-1], hourly[-4], sum(hourly)), (24, 100, 50, 150))
        self.assertEqual(bot_board._spark(hourly, "unicode"), "▁" * 20 + "▅▁▁█")
        lines, _span = profile_lines([self.profile()], 0, NOW, 150, DEFAULT_THEME)
        spark = next(span for span in lines[field_row(lines_text(lines), "24 h")] if "▅▁▁█" in span.text)
        self.assertIs(spark.style, DEFAULT_THEME.running)
        write_usage_store(self.root, [("idle", "cli", "t", NOW - 60, 2, "m", 0, 0, 0, None, None, None)])
        self.assertNotIn("▁", self.row(self.profile(), "day"), "no tokens in the day: no flat line")

    def test_the_ascii_charset_draws_gauges_sparkline_and_chips_without_unicode_blocks(self) -> None:
        write_usage_store(self.root, [("now", "cli", "t", NOW - 60, 2, "m", 80, 20, 0, None, None, None)])
        lines, _span = profile_lines([self.profile(), self.profile("miku")], 0, NOW, 80, DEFAULT_THEME, charset="ascii")
        text = lines_text(lines)
        self.assertFalse({character for row in text for character in row if ord(character) > 127} - {"·", "…"},
                         "no block, box or chip glyph is left")
        self.assertIn("#.........", field(text, "memory", "|"))
        self.assertTrue(field(text, "24 h", "|").split()[2].endswith("#"), "the busiest hour is the tallest cell")
        self.assertTrue(text[0].startswith("+- Hermes bots -") and text[0].endswith("+"))
        # `*` running on POSIX, `?` where the board never probes a pid (Windows): the record still says running.
        self.assertRegex(text[HEAD], r"^\+-{10}\+- [*?] default ", "the face's column meets the edge in a joint")
        bottom = next(squeeze(row) for row in text[HEAD + 1 :] if row.startswith("+"))
        self.assertTrue(bottom.startswith("+----------+- "), bottom)
        # Off POSIX the gateway's words come first and take an 80-column edge; 150 leaves room for the chips.
        wide, _span = profile_lines([self.profile()], 0, NOW, 150, DEFAULT_THEME, charset="ascii")
        self.assertIn("discord o", squeeze(lines_text(wide)[-2]), "a platform as last recorded: o")
        self.assertTrue(any(row.startswith("+----------+- ? miku -") for row in text), "a gateway whose record outlived it: ?")

    def test_hermes_display_name_is_read_from_profile_yaml(self) -> None:
        self.assertEqual(self.profile().display, "")
        (self.root / "profile.yaml").write_text("display_name: Kami Sama\nui_meta: {}\n", encoding="utf-8")
        self.assertEqual(self.profile().display, "Kami Sama")
        # The mark is the gateway's state: running only on POSIX, where the board probes the fixture's own pid.
        top = self.row(self.profile(), "top")
        self.assertTrue(top.startswith("╭──────────┬─ ") and "Kami Sama (default) (this TUI) ─" in top, top)
        (self.root / "profile.yaml").write_bytes(b"display_name: \xff\n")
        self.assertEqual(self.profile().display, "", "an unreadable profile.yaml names nothing")

    def test_record_times_are_read_as_hermes_reads_them(self) -> None:
        at = datetime(2026, 10, 26, 4, 14, 34, tzinfo=timezone.utc).timestamp()
        for value, expected in (
            ("2026-10-26T04:14:34+00:00", at), ("2026-10-26T04:14:34Z", at), ("2026-10-26T04:14:34", at),
            ("2026-10-26T13:14:34+09:00", at), (at, at),
            (12, None), (True, None), ("yesterday", None), (None, None), (float("nan"), None),
        ):
            with self.subTest(value=value):
                self.assertEqual(bot_board._record_time(value), expected)

    def test_compact_numbers(self) -> None:
        self.assertEqual(
            [bot_board._bytes_text(size) for size in (512, 12 * 1024, 1536 * 1024, 412 << 20, int(1.2 * (1 << 30)))],
            ["512 B", "12 KB", "1.5 MB", "412 MB", "1.2 GB"],
        )
        self.assertEqual([bot_board._duration_text(s) for s in (45, 720, 12_000, 190_000)], ["45s", "12m", "3h 20m", "2d 4h"])
        self.assertEqual(bot_board._cost_text(bot_board.Usage(cost=0.001)), "<$0.01")


def bots() -> tuple:
    """Three fictional bots as level 1 reads them, with no file behind them: two live gateways, one served."""
    usage = bot_board.Usage(5_920_000, 418_000, 41_300_000, 4.87, True, 0, 1)
    live = bot_board.Gateway("running", True, 52417, 3, platforms=(
        bot_board.Platform("discord", "connected", current=True),
        bot_board.Platform("whatsapp", "connected", needs_attention=True, current=True),
        bot_board.Platform("slack", "fatal", "token revoked", current=True),
    ), started=NOW - 6 * DAY - 2 * 3600, rss=512 << 20)
    memory = (bot_board.MemoryFile("memory", 18, 3_120, 3_500), bot_board.MemoryFile("user", 11, 2_260, 2_500))
    return (
        bot_board.Profile("default", Path("/h"), bot_board.Gateway("running", True, 100, 1, served=("default", "kami"),
                          started=NOW - 3600), (("tui", 40),), 2, NOW - 40, model="claude-opus-5-5", provider="anthropic",
                          usage=bot_board.Usage(184_200, 41_700, 2_310_000, 1.86, True, 0, 0), memory=memory, this_tui=True),
        bot_board.Profile("kami", Path("/h/kami"), bot_board.Gateway("", False, problem="no gateway record"),
                          (("slack", 9),), 0, NOW - 20 * DAY, model="glm-5.3", memory=memory),
        bot_board.Profile("miku", Path("/h/miku"), live, (("discord", 688), ("telegram", 344)), 31, NOW - 12,
                          model="deepseek-v4.1-flash", provider="deepseek", usage=usage,
                          newest=bot_board.SessionRow("s1", "#live-stage · setlist for Saturday's stream", "discord",
                                                      NOW - 12, 48, "kimi-k3.1-pro"),
                          hourly=tuple(range(24)), memory=memory, omh_records=139),
    )


class LayoutTests(unittest.TestCase):
    """Level 1: the totals in a box, then one full-width card a row, its columns lined up down the page."""

    def lines(self, cols: int, selected: int = 2, theme=DEFAULT_THEME) -> list:
        lines, _span = profile_lines(bots(), selected, NOW, cols, theme)
        self.assertLessEqual(max(line_width(line) for line in lines), cols, "never past the edge, never wrapped")
        return lines

    def rows(self, cols: int, selected: int = 2) -> list[str]:
        return lines_text(self.lines(cols, selected))

    def cards(self, cols: int) -> list[list[str]]:
        rows, cards = self.rows(cols)[HEAD:], []
        while rows:
            end = rows.index("")
            cards.append(rows[:end])
            rows = rows[end + 1 :]
        return cards

    def test_the_totals_sit_in_a_box_of_their_own(self) -> None:
        rows = self.rows(150)
        self.assertTrue(rows[0].startswith("╭─ Hermes bots ─") and rows[0].endswith("─╮"))
        self.assertEqual(squeeze(rows[1]), "│ 3 profiles · 2 gateways up · 4 agents running · "
                                           "lifetime of those active in 24 h: 6.1M in · 459.7k out · ~$6.73 + 1 unpriced │")
        self.assertTrue(rows[2].startswith("╰─") and rows[2].endswith("─╯"))
        self.assertEqual(squeeze(self.rows(60)[1]), "│ 3 profiles · 2 gateways up · 4 agents running │",
                         "the day's totals give way first")

    def test_one_card_a_row_at_every_width_and_every_card_alike(self) -> None:
        for cols in (150, 120, 80):
            with self.subTest(cols=cols):
                cards = self.cards(cols)
                self.assertEqual(len(cards), 3, "one card a row: no grid")
                self.assertEqual({len(row) for card in cards for row in card}, {cols}, "every card full width")
                joints = [{index for index, glyph in enumerate(card[0]) if glyph == "┬"} for card in cards]
                self.assertEqual(len({frozenset(found) for found in joints}), 1, "the same inner grid in every card")
                for card in cards:
                    for row in card[1:-1]:
                        self.assertEqual({row[index] for index in joints[0]}, {"│"}, "each divider runs top to bottom")
                    self.assertEqual({card[-1][index] for index in joints[0]}, {"┴"}, "and meets the bottom edge in a joint")

    def test_at_150_and_120_the_fields_sit_in_two_columns_beside_the_face(self) -> None:
        for cols in (150, 120):
            with self.subTest(cols=cols):
                miku = self.cards(cols)[2]
                self.assertEqual(len(miku), 6, "the edges and four rows: the face's height")
                self.assertTrue(miku[0].startswith("╭──────────┬─ ● miku ─"))
                self.assertTrue(miku[0].endswith(" up 6d 2h · 3 agents · 512 MB ─╮"))
                self.assertTrue(miku[1].startswith("│ " + avatar("miku")[0] + " │ model   deepseek-v4.1-flash"))
                cells = [[squeeze(cell) for cell in row.split("│")[2:-1]] for row in miku[1:-1]]
                self.assertEqual([left.split()[0] for left, _right in cells], ["model", "now", "tokens", "cost"])
                self.assertEqual([right.split()[0] for _left, right in cells], ["24", "memory", "user", "OMH"])
                self.assertTrue(cells[1][0].startswith("now #live-stage"))
                self.assertTrue(cells[1][0].endswith("discord · just now"), "source and age at the right")
                self.assertTrue(cells[2][0].startswith("tokens lifetime 5.9M in · 418k out"), "cache reads go first")
                self.assertEqual(cells[3][0], "cost lifetime ~$4.87 + 1 unpriced")
                self.assertTrue(cells[0][1].endswith("█ 31 active · 1,032 stored"))
                self.assertEqual(cells[1][1], f"memory {gauge(89, 8)}")
                self.assertEqual(cells[2][1], f"user {gauge(90, 9)}")
                self.assertEqual(cells[3][1], "OMH 139 records")
                self.assertTrue(squeeze(miku[-1]).startswith("╰──────────┴─ discord ● whatsapp ●! slack ●! ─"))

    def test_at_80_the_fields_stack_in_one_column(self) -> None:
        miku = self.cards(80)[2]
        labels = [squeeze(row.split("│")[2]).split(" ")[0] for row in miku[1:-1]]
        self.assertEqual(labels, ["model", "now", "tokens", "cost", "24", "memory", "user", "OMH"])
        self.assertEqual([row[1:11] for row in miku[1:5]], [f" {line} " for line in avatar("miku")])
        self.assertEqual({row[1:11] for row in miku[5:-1]}, {" " * 10}, "the face is four rows; the rest are blank")

    def test_the_kami_card_says_its_gateway_serves_it_and_it_had_no_day(self) -> None:
        kami = self.cards(150)[1]
        self.assertEqual(field(kami, "24 h"), "24 h no activity · last active 20d ago · 9 stored")
        self.assertEqual(field(kami, "now"), "now no session yet")
        self.assertTrue(squeeze(kami[-1]).startswith("╰──────────┴─ served by the default gateway ─"))

    def test_the_selected_card_takes_the_accent_and_the_rest_the_rule(self) -> None:
        lines = self.lines(150)
        edges = lambda line: {span.style for span in line if span.text.strip() and set(span.text) <= set("╭╮╰╯─┬┴│ ")}
        self.assertEqual(edges(lines[HEAD + 6 + 1 + 6 + 1]), {bot_board._highlight(DEFAULT_THEME)}, "miku's top edge")
        self.assertEqual(edges(lines[HEAD]), {DEFAULT_THEME.rule})

    def test_a_narrow_card_gives_up_its_figures_its_face_and_its_last_chips(self) -> None:
        states = []
        for cols in range(80, 24, -1):
            miku = self.cards(cols)[2]
            top, body, bottom = miku[0], miku[1], squeeze(miku[-1])
            state = ("up 6d" in top, avatar("miku")[0] in body, "slack" in bottom, "whatsapp" in bottom)
            if not states or state != states[-1]:
                states.append(state)
        self.assertEqual(states[0], (True, True, True, True))
        self.assertEqual(states[-1], (False, False, False, False))
        self.assertEqual(states[1], (False, True, True, True), "the top edge's figures go first")
        self.assertFalse([state for state in states if not state[3] and state[2]], "the last chip goes before the one ahead of it")
        self.assertIn((False, False, False, True), states, "and the face before the first chip")

    def test_the_chips_say_each_platforms_state_in_its_colour(self) -> None:
        lines = self.lines(150)
        bottom = lines[HEAD + 6 + 1 + 6 + 1 + 5]
        marks = [(span.text, span.style) for span in bottom if span.text in ("●", "●!")]
        self.assertEqual(marks, [("●", DEFAULT_THEME.ok), ("●!", DEFAULT_THEME.warn), ("●!", DEFAULT_THEME.error)])


class ProfileBoxTests(unittest.TestCase):
    """Level 2: the profile's box, then the sessions in a table box, whole at 150 and 120 columns."""

    def page(self, cols: int, sessions=()) -> list[str]:
        snapshot_ = BoardSnapshot(BoardView("miku"), bots(), tuple(sessions), 41, read_at=NOW)
        lines, _span = session_lines(snapshot_, 0, NOW, cols, DEFAULT_THEME)
        self.assertLessEqual(max(line_width(line) for line in lines), cols)
        return lines_text(lines)

    def test_the_profile_box_holds_the_record_gauges_and_sources(self) -> None:
        for cols in (150, 120):
            with self.subTest(cols=cols):
                text = self.page(cols)
                box = text[: text.index("")]
                self.assertEqual({len(row) for row in box}, {cols})
                self.assertTrue(box[0].startswith("╭──────────┬─ ● miku ─") and box[0].endswith(" up 6d 2h · 3 agents · 512 MB ─╮"))
                self.assertEqual(field(box, "gateway"), "gateway running · pid 52417 · 3 agents running")
                self.assertEqual(field(box, "error"), "error slack: token revoked")
                self.assertEqual(field(box, "memory"), f"memory {gauge(89, 8)} 18 entries · 3,120/3,500 chars")
                self.assertEqual(field(box, "user"), f"user {gauge(90, 9)} 11 entries · 2,260/2,500 chars")
                self.assertEqual(field(box, "sources"), "sources discord 688 · telegram 344")
                self.assertTrue(squeeze(box[-1]).startswith("╰──────────┴─ discord ● whatsapp ●! slack ●! ─"))
                self.assertFalse([row for row in box if "…" in row], "nothing is cut")

    def test_a_narrow_profile_box_gives_up_whole_fields(self) -> None:
        box = self.page(60)
        box = box[: box.index("")]
        self.assertFalse([row for row in box if "…" in row], box)
        self.assertEqual(field(box, "memory"), f"memory {gauge(89, 8)} 18 entries", "the characters give way first")

    def test_the_sessions_sit_in_a_table_box_with_a_header_and_one_separator(self) -> None:
        sessions = [
            bot_board.SessionRow("s1", "#live-stage · setlist for Saturday's stream", "discord", NOW - 12, 48, "kimi-k3.1-pro",
                                 bot_board.Usage(412_300, 38_900, 3_100_000, 0.41, True)),
            bot_board.SessionRow("s2", "Poll", "x", NOW - 2 * 3600, 9, "glm-5.3", bot_board.Usage(192, 4_100)),
        ]
        for cols in (150, 120):
            with self.subTest(cols=cols):
                text = self.page(cols, sessions)
                table = text[text.index("") + 1 :]
                self.assertEqual(len(table), 6, "top edge, header, rule, two rows, bottom edge")
                self.assertEqual({len(row) for row in table}, {cols})
                joint = table[0].index("┬")
                self.assertEqual([row[joint] for row in table], ["┬", "│", "┼", "│", "│", "┴"], "one separator, joined")
                self.assertTrue(table[2].startswith("├") and table[2].endswith("┤"))
                self.assertEqual(squeeze(table[1][joint:]), "│ model in out cost source age msgs │")
                self.assertTrue(table[0].startswith("╭─ 2 sessions"))
                self.assertFalse([row for row in table if "…" in row], "the titles fit at this width")
                for unit in ("k ", " ago", "48 │"):
                    if unit in table[3]:
                        self.assertEqual(table[3].index(unit) if unit != "48 │" else table[3].rindex("│"),
                                         table[3].index(unit) if unit != "48 │" else table[4].rindex("│"))

    def test_the_selected_row_is_the_pointer_and_an_accent_title_with_no_fill(self) -> None:
        # Every menu lost its fill on 2026-10-27 (the owner's ragged teal bands): the table marks its row as the
        # completion menu and the pickers do.
        sessions = [bot_board.SessionRow(f"s{n}", f"chat {n}", "cli", NOW - n, 1) for n in range(3)]
        snapshot_ = BoardSnapshot(BoardView("miku"), bots(), tuple(sessions), read_at=NOW)
        lines, span = session_lines(snapshot_, 1, NOW, 120, DEFAULT_THEME)
        selected, other = lines[span[0]], lines[span[0] + 1]
        self.assertEqual({item.style.bg for line in lines for item in line}, {None}, "no row has a fill")
        self.assertTrue(line_text(selected).startswith("│ ❯ chat 1"))
        self.assertTrue(line_text(other).startswith("│   chat 2"))
        self.assertEqual(next(item for item in selected if "chat 1" in item.text).style, DEFAULT_THEME.menu_current)
        self.assertEqual(next(item for item in other if "chat 2" in item.text).style, DEFAULT_THEME.text)


class MessageBoxTests(unittest.TestCase):
    """Level 3: the session in a box, its messages in a second one with the time and role in a column of their own."""

    def page(self, cols: int, charset: str = "unicode") -> list[str]:
        session = bot_board.SessionRow("s1", "#live-stage · setlist for Saturday's stream", "discord", NOW - 12, 48,
                                       "kimi-k3.1-pro", bot_board.Usage(412_300, 38_900, 3_100_000, 0.41, True))
        messages = (
            bot_board.MessageRow("user", "can you lock the setlist for saturday? " * 6, NOW - 600),
            bot_board.MessageRow("tool", "omh_memory: recall · setlist", NOW - 590),
            bot_board.MessageRow("assistant", "Locked.", NOW - 580),
        )
        snapshot_ = BoardSnapshot(BoardView("miku", "s1"), bots(), (session,), messages=messages, read_at=NOW)
        lines = message_lines(snapshot_, session, NOW, cols, DEFAULT_THEME, charset)
        self.assertLessEqual(max(line_width(line) for line in lines), cols)
        self.lines = lines
        return lines_text(lines)

    def test_the_session_and_its_messages_are_two_boxes(self) -> None:
        for cols in (150, 120):
            with self.subTest(cols=cols):
                text = self.page(cols)
                head, body = text[: text.index("")], text[text.index("") + 1 :]
                self.assertTrue(head[0].startswith("╭─ miku › #live-stage · setlist for Saturday's stream ─"))
                self.assertEqual(squeeze(head[1]), "│ discord · 48 messages · last active just now │")
                self.assertEqual(squeeze(head[2]), "│ kimi-k3.1-pro · 412.3k in · 38.9k out · 3.1M cache read · ~$0.41 │")
                joint = body[0].index("┬")
                self.assertEqual({row[joint] for row in body[1:-1]}, {"│"})
                self.assertEqual(body[-1][joint], "┴")
                self.assertTrue(body[0].endswith(" the last 40 at most, oldest first ─╮"))
                self.assertTrue(body[1].startswith("│ ") and squeeze(body[1][:joint]).endswith("user"))
                self.assertEqual(body[2][:joint], "│" + " " * (joint - 1), "a wrapped row keeps to its own column")
                self.assertEqual({len(row) for row in head + body}, {cols})

    def test_a_tool_row_takes_the_tool_style(self) -> None:
        text = self.page(150)
        row = next(index for index, line in enumerate(text) if "omh_memory: recall" in line)
        style = next(item.style for item in self.lines[row] if "omh_memory: recall" in item.text)
        self.assertEqual(style, DEFAULT_THEME.tool)

    def test_the_ascii_charset_draws_the_same_boxes(self) -> None:
        text = self.page(120, "ascii")
        self.assertFalse({character for row in text for character in row if ord(character) > 127} - {"·", "›", "…"})
        self.assertTrue(text[0].startswith("+- miku"))


# Emoji built with chr(): a ZWJ family (five code points, one two-cell cluster) and VS16 emoji (two code points each).
FAMILY = chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467)
HEART = chr(0x2764) + chr(0xFE0F)
SUN = chr(0x2600) + chr(0xFE0F)
WIDTHS = (150, 135, 120, 117, 116, 80, 60, 40)
JOINT_GLYPHS = {"unicode": ("┬", "│┼", "┴"), "ascii": ("+", "|+", "+")}


def cell_columns(line) -> dict[int, str]:
    """Each cluster's text by the display column it starts at."""
    at, columns = 0, {}
    for span in line:
        for cluster in clusters(span.text):
            columns[at] = cluster
            at += cluster_width(cluster)
    return columns


class GraphemeEdgeTests(unittest.TestCase):
    """Edge text is sized per grapheme cluster, as `truncate_line` sizes it: emoji in a title or a display name never
    overflow a box's edge, move a joint or end the TUI (#2321 review, HIGH)."""

    def boxes(self, lines, charset: str) -> list[list]:
        """Each box in `lines`: the board separates its boxes with one blank row."""
        found, current = [], []
        for line in [*lines, ()]:
            if line:
                current.append(line)
            elif current:
                found.append(current)
                current = []
        return found

    def assert_whole(self, lines, cols: int, charset: str) -> None:
        self.assertEqual({line_width(line) for line in lines if line} - {cols}, set(), "every row is the width")
        down, through, up = JOINT_GLYPHS[charset]
        for box in self.boxes(lines, charset):
            top = cell_columns(box[0])
            joints = [column for column, glyph in top.items() if glyph == down and 0 < column < cols - 1]
            for row in box[1:-1]:
                self.assertEqual({cell_columns(row).get(column) in tuple(through) for column in joints}, {True} if joints else set(),
                                 f"a divider moved at {cols}: {line_text(row)}")
            self.assertEqual({cell_columns(box[-1]).get(column) for column in joints}, {up} if joints else set())
            self.assertEqual(cell_columns(box[0]).get(cols - 1), BOX_CORNERS[charset], "the corner stands")

    def test_emoji_titles_and_display_names_keep_every_box_whole_at_every_width(self) -> None:
        title = (FAMILY + " stage " + HEART + SUN) * 12
        profile = replace(bots()[2], display=HEART + " Miku " + FAMILY * 3, newest=replace(bots()[2].newest, title=title))
        session = replace(profile.newest, title=title)
        messages = (bot_board.MessageRow("user", title, NOW - 60), bot_board.MessageRow("tool", FAMILY * 50, NOW - 30))
        for charset in ("unicode", "ascii"):
            for cols in WIDTHS:
                with self.subTest(charset=charset, cols=cols):
                    level_one, _span = profile_lines((bots()[0], profile), 1, NOW, cols, DEFAULT_THEME, charset)
                    self.assert_whole(level_one, cols, charset)
                    listed = BoardSnapshot(BoardView("miku"), (profile,), (session,), read_at=NOW)
                    level_two, _span = session_lines(listed, 0, NOW, cols, DEFAULT_THEME, charset)
                    self.assert_whole(level_two, cols, charset)
                    opened = BoardSnapshot(BoardView("miku", "s1"), (profile,), (session,), messages=messages, read_at=NOW)
                    self.assert_whole(message_lines(opened, session, NOW, cols, DEFAULT_THEME, charset), cols, charset)

    def test_the_reviewers_family_title_draws_and_does_not_raise(self) -> None:
        session = bot_board.SessionRow("s1", FAMILY * 40, "x", 0, 1)
        for cols in (80, 60, 40):
            with self.subTest(cols=cols):
                lines = message_lines(BoardSnapshot(BoardView("p", "s1"), (), (session,), read_at=0), session, 0, cols, DEFAULT_THEME)
                self.assertEqual({line_width(line) for line in lines if line}, {cols})
                self.assertIn(FAMILY, line_text(lines[0]), "the title is drawn, cut where it must be")

    def test_place_never_writes_at_or_past_its_stop(self) -> None:
        cells = [("-", DEFAULT_THEME.rule)] * 10
        end = bot_board._place(cells, 2, (Span(FAMILY * 5, DEFAULT_THEME.text),), 7)
        self.assertEqual((end, [cell[0] for cell in cells[7:]]), (6, ["-", "-", "-"]), "a cluster that would reach it waits")


class ChipEdgeTests(unittest.TestCase):
    """A two-column card's bottom edge holds whole chips only, spilling past the second joint (#2321 review, MEDIUM)."""

    def test_every_chip_is_whole_with_its_mark_at_every_width(self) -> None:
        names = ["discord", "telegram", "slack", "whatsapp", "signal", "matrix", "mattermost", "x"]
        platforms = tuple(bot_board.Platform(name, "connected", current=True, needs_attention=number % 3 == 1)
                          for number, name in enumerate(names))
        profile = replace(bots()[2], gateway=replace(bots()[2].gateway, platforms=platforms))
        for cols in (150, 135, 120, 117, 116, 100, 80):
            with self.subTest(cols=cols):
                bottom = lines_text(profile_lines([profile], 0, NOW, cols, DEFAULT_THEME)[0])[-2]
                self.assertNotIn("…", bottom, "never a cut chip")
                words = squeeze(bottom.replace("─", " ").replace("┴", " ").replace("╰", " ").replace("╯", " ")).split()
                shown = [word for word in words if word in names]
                self.assertEqual(shown, names[: len(shown)], "whole chips, in order")
                for name in shown:
                    self.assertEqual(words[words.index(name) + 1], "●!" if names.index(name) % 3 == 1 else "●")
                if cols >= 117:
                    self.assertEqual(shown, names, "the second segment takes what the first cannot")


class ReviewBoundaryTests(unittest.TestCase):
    """The boundaries the review found no test held (#2321 review, LOW)."""

    def test_cards_split_into_two_field_columns_from_117_columns(self) -> None:
        self.assertEqual(bot_board._card_widths(117)[1:], (True, True))
        self.assertEqual(bot_board._card_widths(116)[1:], (True, False))
        self.assertEqual(sum(1 for glyph in lines_text(profile_lines(bots(), 0, NOW, 117, DEFAULT_THEME)[0])[HEAD] if glyph == "┬"), 2)
        self.assertEqual(sum(1 for glyph in lines_text(profile_lines(bots(), 0, NOW, 116, DEFAULT_THEME)[0])[HEAD] if glyph == "┬"), 1)

    def test_a_profile_named_in_bytes_that_are_not_utf8_still_draws(self) -> None:
        name = "bot" + chr(0xDC80)  # how Linux hands Python a directory name that is not UTF-8
        self.assertEqual(len(avatar(name)), bot_board.AVATAR_ROWS)
        lines, _span = profile_lines([replace(bots()[2], name=name)], 0, NOW, 120, DEFAULT_THEME)
        self.assertEqual({line_width(line) for line in lines if line}, {120})

    def test_the_highlighted_edge_stands_3_to_1_from_the_others_on_light_and_dark(self) -> None:
        for background in ("#FCF9FD", "#FFFFFF", "#F3F8FD", "#0F1B2D", "#1E1E1E"):
            with self.subTest(background=background):
                theme = build_theme(default_theme(), background)
                lines, span = profile_lines(bots(), 2, NOW, 150, theme)
                edge = lines[span[0]][0].style
                self.assertGreaterEqual(contrast_ratio(edge.fg, theme.rule.fg), EDGE_CONTRAST)
                self.assertGreaterEqual(contrast_ratio(edge.fg, background), EDGE_CONTRAST)


class DeltaReviewTests(unittest.TestCase):
    """The #2321 delta review: the highlight on mid-tone pages, gateway words built whole, chips kept together, and
    a totals label that gives way before its figures."""

    MID_TONES = ("#444444", "#666666", "#808080", "#929292", "#B2B2B2", "#13773D", "#224FBC", "#504945")

    def test_the_highlighted_edge_never_turns_back_into_a_mid_tone_page(self) -> None:
        from omh.skin_pack import SKIN_THEMES

        for skin in SKIN_THEMES:
            for background in (*self.MID_TONES, "#FCF9FD", "#0F1B2D"):
                with self.subTest(skin=skin.short_name, background=background):
                    theme = build_theme(skin, background)
                    edge = bot_board._highlight(theme).fg
                    self.assertGreaterEqual(contrast_ratio(edge, background), 4.5, "it reads on the page")
                    reached = contrast_ratio(edge, theme.rule.fg) >= EDGE_CONTRAST
                    self.assertTrue(reached or edge in ("#000000", "#FFFFFF"), "3:1 from the rule, or as far as ink goes")

    def test_gateway_words_are_whole_parts_never_split_out_of_rendered_text(self) -> None:
        stopped = bot_board.Gateway("stopped", False, 52417, exit_reason="signal · SIGTERM",
                                    platforms=(bot_board.Platform("discord", "connected"),))
        profile = replace(bots()[2], gateway=stopped)
        for cols in (150, 135, 120, 117, 80, 60):
            with self.subTest(cols=cols):
                bottom = squeeze(lines_text(profile_lines([profile], 0, NOW, cols, DEFAULT_THEME)[0])[-2])
                self.assertIn("gateway stopped (signal · SIGTERM)", bottom, "its reason is part of its state")
                self.assertEqual(bottom.count("("), bottom.count(")"))

    def test_restart_requested_never_splits_the_chips(self) -> None:
        names = ["discord", "telegram", "slack", "whatsapp", "signal", "matrix", "mattermost", "x"]
        gateway = replace(bots()[2].gateway, restart_requested=True,
                          platforms=tuple(bot_board.Platform(name, "connected", current=True) for name in names))
        profile = replace(bots()[2], gateway=gateway)
        for cols in (150, 135, 120):
            with self.subTest(cols=cols):
                bottom = squeeze(lines_text(profile_lines([profile], 0, NOW, cols, DEFAULT_THEME)[0])[-2])
                self.assertLess(bottom.index("restart requested"), bottom.index("discord"))
                words = [word for word in bottom.replace("─", " ").replace("┴", " ").split() if word in names]
                self.assertEqual(words, names[: len(words)], "the chips in one run, the last ones dropped whole")
                if cols >= 135:
                    self.assertEqual(words, names)

    def test_the_totals_label_shortens_before_its_figures_go(self) -> None:
        wide = squeeze(lines_text(profile_lines(bots(), 0, NOW, 150, DEFAULT_THEME)[0])[1])
        self.assertIn("lifetime of those active in 24 h: 6.1M in", wide)
        narrow = squeeze(lines_text(profile_lines(bots(), 0, NOW, 120, DEFAULT_THEME)[0])[1])
        self.assertIn("lifetime (active 24 h): 6.1M in · 459.7k out", narrow)


class AvatarTests(unittest.TestCase):
    def test_a_name_draws_the_same_face_on_every_run(self) -> None:
        self.assertEqual(avatar("miku"), [" █▀▄▄▀█ ", " █    █ ", "█▀████▀█", " ▀ ▀▀ ▀ "])  # pinned: sha256 of the name
        self.assertEqual(avatar("miku", "ascii"), [" #',,'# ", " #    # ", "#'####'#", " ' '' ' "])
        self.assertEqual(avatar("kami"), avatar("kami"))
        self.assertNotEqual(avatar("kami"), avatar("miku"))

    def test_a_face_is_mirrored_and_fills_its_cells(self) -> None:
        for name in ("default", "frieren", "a", "名前"):
            with self.subTest(name=name):
                face = avatar(name)
                self.assertEqual(len(face), bot_board.AVATAR_ROWS)
                for row in face:
                    self.assertEqual((len(row), row), (bot_board.AVATAR_COLS, row[::-1]))
                    self.assertLessEqual(set(row), set(" ▀▄█"))

    def test_its_colour_is_an_accent_step_that_reads_on_light_and_dark(self) -> None:
        for background in ("#FCF9FD", "#0F1B2D"):
            theme = build_theme(default_theme(), background)
            for name in ("default", "kami", "miku", "frieren"):
                style = bot_board._avatar_style(name, theme)
                self.assertGreaterEqual(contrast_ratio(style.fg, background), TEXT_CONTRAST, (background, name))
                self.assertEqual(style, bot_board._avatar_style(name, theme))

    def test_hermes_display_name_titles_the_box_beside_the_profile_name(self) -> None:
        profile = replace(bots()[2], display="Miku Hatsune")
        top = lines_text(bot_board.bot_box(profile, "", False, NOW, 80, DEFAULT_THEME))[0]
        self.assertTrue(top.startswith("╭──────────┬─ ● Miku Hatsune (miku) ─"), top)


class ThemeBandTests(unittest.TestCase):
    """The footer bar on a light background is light and reads at AA; the menus have no band at all
    (`test_tui_theme`)."""

    def test_a_light_background_gets_a_light_status_bar_that_reads_at_aa(self) -> None:
        for background in ("#FCF9FD", "#FFFFFF", "#F3F8FD"):
            with self.subTest(background=background):
                status = build_theme(default_theme(), background).status
                self.assertTrue(is_light(status.bg), status)
                self.assertGreaterEqual(contrast_ratio(status.fg, status.bg), TEXT_CONTRAST, status)

    def test_the_highlighted_box_edge_and_the_others_read_on_light_and_dark(self) -> None:
        # The other boxes' edge is the launch look's rule colour (owner, 2026-10-29), so every look is measured; the
        # highlighted edge (`_highlight`) is the brand moved 3:1 away from it.
        for background in ("#FCF9FD", "#0F1B2D"):
            for look in LAUNCH_PRESETS:
                with self.subTest(background=background, look=look):
                    skin = default_theme()
                    theme = with_launch_look(build_theme(skin, background), skin, background, look)
                    self.assertGreaterEqual(contrast_ratio(theme.brand.fg, background), TEXT_CONTRAST)
                    self.assertGreaterEqual(contrast_ratio(theme.rule.fg, background), EDGE_CONTRAST)
                    highlight = bot_board._highlight(theme).fg
                    self.assertGreaterEqual(contrast_ratio(highlight, theme.rule.fg), EDGE_CONTRAST, "it stands apart")


class TableTests(FixtureRoot):
    """Level 2's table: which columns it keeps at a width."""

    def sessions(self) -> BoardSnapshot:
        write_usage_store(self.root, [
            ("a", "telegram", "Rehearsal schedule for the anniversary", NOW - 60, 140, "moonshot/kimi-k3.1-pro",
             302_000, 41_200, 0, 0.52, None, "estimated"),
            ("b", "x", "Poll", NOW - 2 * 3600, 9, "glm-5.3", 192, 4_100, 0, None, None, "unknown"),
            ("c", "discord", "Merch drop", NOW - 3 * DAY, 12, "deepseek/deepseek-v4.1-flash", 44_600, 9_300, 0, 0.0, None, "included"),
        ])
        return snapshot(self.environ, BoardView("default"))

    def test_a_narrow_board_gives_up_source_then_cost_then_tokens(self) -> None:
        table = bot_board._session_table(self.sessions().sessions, NOW)
        seen: list[list[str]] = []
        for cols in range(200, 20, -1):
            keep = bot_board._session_columns(table, cols)
            if not seen or keep != seen[-1]:
                seen.append(keep)
        everything = ["model", "input", "output", "cost", "source", "age", "messages"]
        self.assertEqual(seen, [
            everything,
            ["model", "input", "output", "cost", "age", "messages"],
            ["model", "input", "output", "age", "messages"],
            ["model", "age", "messages"],
        ])
        lines, _span = session_lines(self.sessions(), 0, NOW, 40, DEFAULT_THEME)
        self.assertEqual({line_width(row) for row in lines if row}, {40}, "past every drop, the title alone, one row each")

    def test_a_column_no_session_fills_is_left_out(self) -> None:
        sessions = snapshot(self.environ, BoardView("default"))  # a store with no model or token column
        self.assertEqual(bot_board._session_columns(bot_board._session_table(sessions.sessions, NOW), 150),
                         ["source", "age", "messages"])

    def test_right_aligned_figures_end_in_one_column(self) -> None:
        lines, _span = session_lines(self.sessions(), 0, NOW, 150, DEFAULT_THEME)
        rows = lines_text(lines)[-4:-1]
        self.assertEqual(len({row.index(" │", row.index("┼") if "┼" in row else 2) for row in rows}), 1)
        self.assertEqual(len({row.rindex(" │") for row in rows}), 1)
        self.assertIn("   192  ", rows[1], "a short count is padded on its left")


def squeeze(text: str) -> str:
    """A row's words, each run of padding one space: what it says, apart from where it says it."""
    return " ".join(text.split())


def snapshot(environ: dict, view: BoardView = BoardView()) -> BoardSnapshot:
    return read_board(environ, view, NOW)


class DrawingTests(FixtureRoot):
    @POSIX_ONLY
    def test_level_one_says_what_each_gateway_and_store_is_at_any_width(self) -> None:
        with patch.object(bot_board, "pid_exists", side_effect=lambda pid: pid == os.getpid()):
            profiles = snapshot(self.environ).profiles
        for cols in (40, 150):
            with self.subTest(cols=cols):
                lines, span = profile_lines(profiles, 1, NOW, cols, DEFAULT_THEME)
                self.assertLessEqual(max(line_width(line) for line in lines), cols)
                if cols == 150:
                    text = "\n".join(squeeze(row) for row in lines_text(lines))
                    self.assertIn(BOARD_TITLE, text)
                    self.assertIn("╭──────────┬─ ● default (this TUI) ─", text)
                    self.assertIn("╰──────────┴─ discord ○ slack ● ─", text, "a platform as last recorded: ○")
                    self.assertIn("2 agents", text)
                    self.assertIn("24 h 2 active · 4 stored", text)
                    self.assertIn("╭──────────┬─ ◌ miku ─", text)
                    self.assertIn("╰──────────┴─ gateway not running slack ○ ─", text, "the why gives way to the chips")
                    self.assertNotIn("is gone…", text, "never cut mid-word")
                    self.assertIn("╭──────────┬─ ○ broken ─", text)
                    self.assertIn("╰──────────┴─ gateway record unreadable ─", text)
                    self.assertIn("24 h sessions: no state.db", text)
                    self.assertIn("╰──────────┴─ gateway stopped (signal) ─", text)
                    self.assertTrue(lines_text(lines)[span[0]].startswith("╭──────────┬─ ○ broken"), "the highlighted card")
                    self.assertEqual(lines[span[0]][0].style, bot_board._highlight(DEFAULT_THEME), "takes the accent")

    @POSIX_ONLY
    def test_a_profile_the_default_gateway_serves_reads_as_served(self) -> None:
        record = json.loads((self.root / "gateway_state.json").read_text(encoding="utf-8"))
        write_record(self.root, {**record, "served_profiles": ["default", "miku"]})
        lines, _span = profile_lines(snapshot(self.environ).profiles, 0, NOW, 150, DEFAULT_THEME)
        text = "\n".join(squeeze(row) for row in lines_text(lines))
        self.assertIn("╭──────────┬─ ● miku ─", text)
        self.assertIn("╰──────────┴─ served by the default gateway slack ○ ─", text)

    def test_levels_two_and_three_fit_any_width_and_show_the_tail(self) -> None:
        sessions = snapshot(self.environ, BoardView("default"))
        messages = snapshot(self.environ, BoardView("default", "s-new"))
        for cols in (40, 150):
            with self.subTest(cols=cols):
                listed, span = session_lines(sessions, 0, NOW, cols, DEFAULT_THEME)
                tail = message_lines(messages, sessions.sessions[0], NOW, cols, DEFAULT_THEME)
                self.assertLessEqual(max(line_width(line) for line in listed + tail), cols)
        listed, span = session_lines(sessions, 0, NOW, 150, DEFAULT_THEME)
        text = lines_text(listed)
        self.assertIn("1 subagent session not listed", next(row for row in text if "sessions" in row and row.startswith("╭─")))
        self.assertTrue(text[span[0]].startswith("│ ❯ Release notes"))
        self.assertTrue(squeeze(text[span[0]]).endswith("slack 10m ago 12 │"))
        tail = "\n".join(lines_text(message_lines(messages, sessions.sessions[0], NOW, 150, DEFAULT_THEME)))
        self.assertIn("default › Release notes", tail)
        self.assertIn("assistant │ red done now", "\n".join(squeeze(row) for row in tail.splitlines()))
        self.assertNotIn("pwned", tail)
        self.assertNotIn("\x1b", tail)


class FakeReader:
    """A `BoardReader` that reads at once on this thread, and records what the board asked."""

    instances: list[FakeReader] = []

    def __init__(self, environ, *, clock=time.time) -> None:
        self.environ = environ
        self.views: list[BoardView] = []
        self.refreshes = 0
        self.started = self.stopped = self.closed = False
        self.view = BoardView()
        self.pending: BoardSnapshot | None = None
        FakeReader.instances.append(self)

    def start(self, wake=None) -> None:
        self.started, self.stopped = True, False
        self.view = BoardView()
        self.pending = read_board(self.environ, self.view, NOW)

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def show(self, view: BoardView) -> None:
        self.views.append(view)
        self.view = view
        self.pending = read_board(self.environ, view, NOW)

    def refresh(self) -> None:
        self.refreshes += 1

    def take(self) -> BoardSnapshot | None:
        pending, self.pending = self.pending, None
        return pending


class ReaderThreadTests(FixtureRoot):
    def test_the_thread_reads_at_start_and_for_each_view_and_stops(self) -> None:
        woken: list[int] = []
        reader = bot_board.BoardReader(self.environ, clock=lambda: NOW)
        reader.start(lambda: woken.append(1))
        self.addCleanup(reader.stop)
        first = self.wait_for(reader)
        self.assertEqual((first.view, len(first.profiles)), (BoardView(), 4))
        reader.show(BoardView("default"))
        second = self.wait_for(reader, lambda snapshot: snapshot.view == BoardView("default"))
        self.assertEqual([row.id for row in second.sessions], ["s-new", "s-cli", "s-old"])
        self.assertTrue(woken)
        reader.stop()

    def wait_for(self, reader, accept=lambda snapshot: True) -> BoardSnapshot:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            snapshot = reader.take()
            if snapshot is not None and accept(snapshot):
                return snapshot
            time.sleep(0.01)
        self.fail("no snapshot arrived")

    def test_a_read_that_raises_is_drawn_as_a_named_failure(self) -> None:
        def broken(environ, view, now):
            raise RuntimeError("boom")

        reader = bot_board.BoardReader(self.environ, read=broken, clock=lambda: NOW)
        reader._open = True
        reader.poll_once()
        snapshot = reader.take()
        self.assertEqual((snapshot.problem, snapshot.read_at), ("the board could not be read: RuntimeError", NOW))
        board = BotBoard("bots", clock=lambda: NOW + 120)
        board.take(snapshot)
        board.frame(80, 10, DEFAULT_THEME)
        self.assertEqual(lines_text(board.lines), ["the board could not be read: RuntimeError"])
        self.assertIn("read 2m ago", line_text(board.footer("1-1/1", DEFAULT_THEME)[1]))

    def test_a_closed_board_reads_nothing_and_opening_it_again_reuses_the_thread(self) -> None:
        reads: list[BoardView] = []

        def read(environ, view, now):
            reads.append(view)
            return BoardSnapshot(view, (), read_at=now)

        reader = bot_board.BoardReader(self.environ, read=read)
        reader.start()
        self.addCleanup(reader.close)
        thread = reader._thread
        self.wait_for(reader)
        reader.stop()
        settled = len(reads)
        time.sleep(0.2)
        self.assertEqual(len(reads), settled, "nothing is read while the board is closed")
        reader.show(BoardView("miku"))
        reader.start()
        self.assertIs(reader._thread, thread)
        self.assertEqual(self.wait_for(reader).view, BoardView(), "it opens again at the profiles")

    def test_a_read_finished_after_the_board_closed_is_dropped(self) -> None:
        reader = bot_board.BoardReader(self.environ)
        reader._open = True

        def slow(environ, view, now):
            reader.stop()  # the person closed the board while this read ran
            return BoardSnapshot(view, ())

        reader._read = slow
        reader.poll_once()
        self.assertIsNone(reader.take())

    def test_a_read_finished_after_the_view_changed_is_dropped(self) -> None:
        reader = bot_board.BoardReader(self.environ)

        def slow(environ, view, now):
            reader.show(BoardView("miku"))  # the person moved while this read ran
            return BoardSnapshot(view, ())

        reader._open = True
        reader._read = slow
        reader.poll_once()
        self.assertIsNone(reader.take())


class BoardKeysTests(FixtureRoot):
    def board(self) -> tuple[BotBoard, FakeReader]:
        reader = FakeReader(self.environ)
        board = BotBoard("bots", show=reader.show, refresh=reader.refresh, clock=lambda: NOW)
        reader.start()
        board.take(reader.take())
        return board, reader

    def press(self, board: BotBoard, reader: FakeReader, *keys: Key) -> bool:
        stays = True
        for key in keys:
            stays = board.handle_key(key, 24)
            arrived = reader.take()
            if arrived is not None:
                board.take(arrived)
            board.frame(100, 24, DEFAULT_THEME)
        return stays

    def test_down_enter_left_walk_the_levels_and_q_closes_from_the_top(self) -> None:
        board, reader = self.board()
        board.frame(100, 24, DEFAULT_THEME)
        self.press(board, reader, Key(DOWN), Key(DOWN), Key(DOWN), Key(UP))
        self.assertEqual(board.profile_index, 2)
        self.press(board, reader, Key(ENTER))
        self.assertEqual(reader.views[-1], BoardView("locked"))
        self.press(board, reader, Key(LEFT))
        self.assertEqual(reader.views[-1], BoardView())
        self.press(board, reader, Key(UP), Key(UP), Key(ENTER), Key(ENTER))
        self.assertEqual(reader.views[-1], BoardView("default", "s-new"))
        page = "\n".join(lines_text(board.lines))
        self.assertIn("default › Release notes", page)
        self.assertTrue(self.press(board, reader, Key(ESCAPE)))
        self.assertEqual(reader.views[-1], BoardView("default"))
        self.assertTrue(self.press(board, reader, Key(CHAR, "q")))
        self.assertFalse(self.press(board, reader, Key(CHAR, "q")), "q on the profiles closes the board")

    def test_r_reads_again_and_the_footer_says_how_old_the_reading_is(self) -> None:
        board, reader = self.board()
        self.press(board, reader, Key(CHAR, "r"))
        self.assertEqual(reader.refreshes, 1)
        footer = [line_text(line) for line in board.footer("1-9/9", DEFAULT_THEME)]
        self.assertIn("read just now", footer[1])
        self.assertIn("read-only", footer[1])

    def test_the_highlight_stays_on_screen_on_a_short_terminal(self) -> None:
        board, reader = self.board()
        for _ in range(3):
            board.handle_key(Key(DOWN), 8)
        board.frame(80, 8, DEFAULT_THEME)
        first, _last = board._span
        self.assertTrue(board.top <= first < board.top + board.body_rows(8), "the highlighted box's top edge is on screen")
        self.assertIn("miku", line_text(board.lines[first]))

    def test_the_highlight_stays_on_its_session_when_the_list_reorders(self) -> None:
        board, reader = self.board()
        self.press(board, reader, Key(ENTER))  # default's sessions: s-new, s-cli, s-old
        self.press(board, reader, Key(DOWN))
        self.assertEqual(board.highlighted_session, "s-cli")
        connection = sqlite3.connect(self.root / "state.db")
        connection.execute("UPDATE sessions SET last_activity_at = ? WHERE id = 's-old'", (NOW,))
        connection.commit()
        connection.close()
        board.take(read_board(self.environ, BoardView("default"), NOW))  # the next refresh: s-old, s-new, s-cli
        board.frame(100, 24, DEFAULT_THEME)
        self.assertEqual([row.id for row in board.snapshot.sessions], ["s-old", "s-new", "s-cli"])
        self.assertTrue(lines_text(board.lines)[board._span[0]].startswith("│ ❯ Local run"))
        self.press(board, reader, Key(ENTER))
        self.assertEqual(reader.views[-1], BoardView("default", "s-cli"), "Enter opens the row the highlight is on")

    def test_back_to_a_long_list_brings_the_highlight_on_screen_once_the_list_arrives(self) -> None:
        write_store(self.root / "profiles" / "broken",
                    [(f"b-{n:02d}", "cli", f"chat {n:02d}", NOW - n, NOW - n, 1) for n in range(40)])
        held: list[BoardSnapshot] = []
        board = BotBoard("bots", show=lambda view: held.append(read_board(self.environ, view, NOW)), clock=lambda: NOW)
        board.take(read_board(self.environ, BoardView(), NOW))
        board.highlighted_profile = "broken"
        board.frame(100, 12, DEFAULT_THEME)
        board.handle_key(Key(ENTER), 12)
        board.take(held.pop())
        for _ in range(30):
            board.handle_key(Key(DOWN), 12)
        board.frame(100, 12, DEFAULT_THEME)
        board.handle_key(Key(ENTER), 12)  # level 3 of chat 30
        board.take(held.pop())
        board.frame(100, 12, DEFAULT_THEME)
        board.handle_key(Key(LEFT), 12)  # back: the reader has not answered yet
        board.frame(100, 12, DEFAULT_THEME)
        self.assertEqual(lines_text(board.lines), ["broken · reading…"])
        board.take(held.pop())  # the list arrives a frame later
        board.frame(100, 12, DEFAULT_THEME)
        shown = lines_text(board.lines)[board.top : board.top + board.body_rows(12)]
        self.assertTrue([row for row in shown if row.startswith("│ ❯ chat 30")], shown)

    def test_level_three_heads_with_the_sessions_row_as_read_now(self) -> None:
        board, reader = self.board()
        self.press(board, reader, Key(ENTER), Key(ENTER))
        connection = sqlite3.connect(self.root / "state.db")
        connection.execute("UPDATE sessions SET message_count = 99 WHERE id = 's-new'")
        connection.commit()
        connection.close()
        board.take(read_board(self.environ, BoardView("default", "s-new"), NOW))
        board.frame(100, 24, DEFAULT_THEME)
        self.assertIn("slack · 99 messages", "\n".join(lines_text(board.lines)))

    def test_a_snapshot_for_another_view_is_not_drawn_as_this_one(self) -> None:
        board, reader = self.board()
        board.view = BoardView("miku")
        board.frame(100, 24, DEFAULT_THEME)
        self.assertEqual(lines_text(board.lines), ["miku · reading…"])


class AppTests(FixtureRoot):
    def app(self):
        FakeReader.instances = []
        app, client = make_app(environ=self.environ)
        app.make_board_reader = FakeReader
        return app, client

    def test_ctrl_s_from_the_composer_opens_the_board_and_q_closes_it_and_stops_its_reader(self) -> None:
        app, client = self.app()
        type_text(app, "draft")
        app._on_input(CTRL_S)
        self.assertIsInstance(app.pager, BotBoard)
        app._take_board()
        app._render()
        screen = "\n".join(app.terminal.screen.lines())
        self.assertIn(BOARD_TITLE, screen)
        self.assertIn("default (this TUI)", screen)
        app._on_input(Key(CHAR, "q"))
        self.assertIsNone(app.pager)
        self.assertTrue(FakeReader.instances[0].stopped)
        self.assertEqual(app.composer.text, "draft")
        app._on_input(CTRL_S)
        self.assertEqual(len(FakeReader.instances), 1, "the board opened again reuses its one reader")
        self.assertFalse(FakeReader.instances[0].stopped)
        self.assertEqual(client.calls, [], "the board sends nothing to the gateway")

    def test_the_tui_loads_the_board_only_when_it_opens(self) -> None:
        # QA P2: importing the TUI loaded this module (and its readers' imports) for a board most sessions never open.
        code = ("import sys\nfrom test_tui_modes import make_app\n"
                "app, _client = make_app()\napp._take_board()\napp._render()\n"  # a loop tick with the board closed
                "print('omh.tui.bot_board' in sys.modules)")
        done = subprocess.run([sys.executable, "-P", "-c", code], capture_output=True, text=True, timeout=120,
                              env={**os.environ, "PYTHONPATH": os.pathsep.join([str(Path(__file__).parent),
                                                                               os.environ.get("PYTHONPATH", "")])})
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "False"), done.stderr)
        FakeReader.instances = []
        app, _client = make_app(environ=self.environ)
        with patch.object(bot_board, "BoardReader", FakeReader):
            app._on_input(CTRL_S)
        self.assertIsInstance(app.pager, BotBoard)
        self.assertEqual(len(FakeReader.instances), 1, "the board's own reader, made when it opened")

    def test_bots_opens_the_board_and_leaves_no_echo(self) -> None:
        app, client = self.app()
        send(app, "/bots")
        self.assertIsInstance(app.pager, BotBoard)
        self.assertEqual(commands(app), [], "it only opens a pager: nothing to attribute")
        self.assertEqual(client.calls, [])

    def test_ctrl_s_inside_the_history_search_does_not_open_the_board(self) -> None:
        app, _client = self.app()
        app.composer.history = ["ls -la"]
        app._on_input(Key(CHAR, "r", ctrl=True))
        app._on_input(CTRL_S)
        self.assertIsNone(app.pager)
        self.assertIsInstance(app.search, HistorySearch)
        self.assertEqual(FakeReader.instances, [])

    def test_ctrl_s_inside_another_pager_does_nothing(self) -> None:
        app, _client = self.app()
        app._keys("")
        keys = app.pager
        app._on_input(CTRL_S)
        self.assertIs(app.pager, keys)

    def test_shutdown_closes_the_boards_reader(self) -> None:
        app, _client = self.app()
        app._on_input(CTRL_S)
        app._shutdown()
        self.assertTrue(FakeReader.instances[0].stopped)
        self.assertTrue(FakeReader.instances[0].closed)


if __name__ == "__main__":
    unittest.main()
