"""The row above the composer for this session's background processes (`omh.tui.background`).

A `terminal` command Hermes runs in the background with `notify_on_complete`
off ends without waking the session, so the screen looked dead for an hour
(owner, 2026-10-28). While this session owns such a process one row says so
and who will be told when it ends; once one ends unreported the row says it
finished, the bell rings once, and Enter on an empty composer sends one
prompt. Driven through `test_tui_modes`' app, the poller's snapshots handed
in as it would hand them, and Hermes' `processes.json` written in the shape
the live checkpoint has.
"""

from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from _hermes_session_rows import compacted, row as session_row, write_sessions
from _tui_lines import line_text
from test_tui_modes import SID, drawn, make_app, type_text

from omh.tui.app import IDLE_READ_SECONDS, WORKING_GLYPHS
from omh.tui.background import (
    LABEL_CELLS, PROCESSES_FILE, PROCESSES_MAX_BYTES, BackgroundProcess, finished_line, process_label,
    read_processes, report_prompt, running_line, still_running,
)
from omh.tui.bot_board import ON_POSIX, process_facts
from omh.tui.keys import ENTER, Key
from omh.skin_pack import theme_for_name
from omh.tui.layout import MIN_COLS
from omh.tui.panels import (
    DELEGATION_DEPTH, LINEAGE_READS, PARENT_READS, ROUTE_READS, HudPoller, HudSnapshot, delegated_from,
    recorded_routes,
)
from omh.tui.style import NO_COLOR, Span
from omh.tui.theme import (
    DEFAULT_THEME, TEXT_CONTRAST, build_theme, contrast_ratio, kind_style, surface_for, with_catch_colours,
    without_colour,
)
from omh.tui.width import cell_width, line_width

# A local session's stored id, as `session.create` names it, and the key Hermes records on a process its turn
# starts: the route `local_source` (gateway/session_local_recovery.py:41-45) and `build_session_key`
# (gateway/session.py:670-678, 691-729) make, at Hermes origin/main 0431192d69. The live checkpoint of
# 2026-10-28 had exactly this pair.
STORED = "local-099c6f1e2a7b4d3c8e5f60718293a4b5c6d7e8f90123456789abcdef0123abcd"
ROUTE = f"agent:main:local:dm:{STORED}"
DARK = "#1E2030"
NOW = 1_793_160_000.0
COMMAND = 'cd "/Users/me/work tree" && PYTHONPATH=tests uv run python -m unittest tests.test_payment'


def row(**fields: object) -> dict:
    """One checkpoint entry in the shape `ProcessCheckpointMixin._write_checkpoint` writes."""
    entry = {
        "session_id": "proc_36b5cd4d7445", "command": COMMAND, "pid": 88629, "pid_scope": "host",
        "host_start_time": None, "cwd": "/Users/me/work", "started_at": NOW - 4033, "task_id": f"session:{ROUTE}",
        "owner_task_id": STORED, "session_key": ROUTE, "parent_session_id": STORED, "notify_on_complete": False,
        "watch_patterns": [], "completion_output_chars": 0, "heartbeat_seconds": 0, "output_log": "",
    }
    entry.update(fields)
    return entry


# A Telegram DM a bot profile serves, resumed in the TUI: its state.db id, and the route Hermes records on that row
# (`sessions.session_key`, gateway/session_recovery.py:440,457 at origin/main 0431192d69; 425,442 at bf0203a794).
# The running row's glyph steps with its clock (`1h 07m 13s` = 4033 s with the fixture's `started_at`).
GLYPH = WORKING_GLYPHS[4033 % len(WORKING_GLYPHS)]
CHAT = "20261029_090000_aa11bb"
CHAT_ROUTE = "agent:kami:telegram:dm:12345"


def record_routes(hermes_home: str, keys: dict[str, str]) -> None:
    """Hermes' `sessions.session_key` column (hermes_state_common.py:468) on rows `write_sessions` wrote."""
    connection = sqlite3.connect(Path(hermes_home) / "state.db")
    try:
        connection.execute("ALTER TABLE sessions ADD COLUMN session_key TEXT")
        connection.executemany("UPDATE sessions SET session_key = ? WHERE id = ?",
                               [(key, session) for session, key in keys.items()])
        connection.commit()
    finally:
        connection.close()


def process(**fields: object) -> BackgroundProcess:
    values = {
        "proc_id": "proc_36b5cd4d7445", "pid": 88629, "host": True, "start_time": None, "command": COMMAND,
        "started_at": NOW - 4033, "notify": False, "watched": False,
    }
    values.update(fields)
    return BackgroundProcess(**values)  # type: ignore[arg-type]


def text(line) -> str:
    return line_text(line) if line is not None else ""


def bells(app) -> int:
    return sum(write.count("\a") for write in app.terminal.writes)


class Clock:
    def __init__(self, at: float) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


class ReadProcessesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.path = Path(self.home) / PROCESSES_FILE

    def write(self, payload: object) -> None:
        self.path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")

    def test_only_this_session_s_rows_are_read(self) -> None:
        self.write([
            row(),
            row(session_id="proc_other", session_key="agent:main:local:dm:local-a1d7"),
            row(session_id="proc_slack", session_key="agent:kami:slack:group:T0:C0:1.2", parent_session_id=STORED),
        ])
        (found,) = read_processes(self.home, STORED)
        self.assertEqual((found.proc_id, found.pid, found.host, found.notify, found.watched),
                         ("proc_36b5cd4d7445", 88629, True, False, False))
        self.assertEqual(read_processes(self.home, "20261028_000000_ffffff"), ())
        self.assertEqual(read_processes(self.home, ""), ())

    def test_a_process_is_matched_on_the_key_shapes_hermes_records_and_nothing_looser(self) -> None:
        """A session the TUI gateway runs itself records its stored id as the key (tui_gateway/prompt_turn.py:670,
        tools/terminal_tool.py:1496); a gateway-owned local one its route, `agent:<namespace>:local:dm:<id>`, the
        namespace `agent:main`, `agent:main~` or `agent:<profile>` (gateway/session.py:670-678)."""
        tui = "20261028_101500_ab12cd"
        owned = (ROUTE, f"agent:kami:local:dm:{STORED}", f"agent:main~:local:dm:{STORED}", STORED)
        others = (
            f"agent:main:local:dm:{STORED[:-4]}",  # an id ours begins with
            f"agent:main:local:dm:{STORED}0",  # one that begins with ours
            f"agent:main:local:dm:x{STORED}",  # one that ends with ours
            f"agent:main:local:dm:{STORED}:thread",  # a thread after the chat id: not a local route
            f"agent:main:local:group:{STORED}",
            f"agent:main:telegram:dm:{STORED}",
            f"agent::local:dm:{STORED}",  # no namespace word
            f"agent:a:b:local:dm:{STORED}",  # a namespace of two words
            f"x:agent:main:local:dm:{STORED}",
            f"session:{ROUTE}",  # the task id, not a session key
            STORED[:-4], "", None, 7,
        )
        # No spawning session named: the key alone decides.
        self.write([row(session_id=f"proc_{index}", session_key=key, parent_session_id="")
                    for index, key in enumerate(owned + others)]
                   + [row(session_id="proc_tui", session_key=tui, parent_session_id="")])
        self.assertEqual([found.proc_id for found in read_processes(self.home, STORED)],
                         [f"proc_{index}" for index in range(len(owned))])
        self.assertEqual([found.proc_id for found in read_processes(self.home, tui)], ["proc_tui"])
        # The session whose id ours begins with owns its own two, and none of ours.
        shorter = {f"proc_{index}" for index, key in enumerate(owned + others) if key in (STORED[:-4], others[0])}
        self.assertEqual({found.proc_id for found in read_processes(self.home, STORED[:-4])}, shorter)
        self.assertEqual(len(shorter), 2)

    def test_a_recorded_route_owns_only_the_rows_this_conversation_spawned(self) -> None:
        """A messaging chat's route is per chat and outlives a conversation on it, so a row under it is this
        session's only when its `parent_session_id` (the spawning session-db id, tools/process_registry.py:581-583,
        1092) is this session's. Without the recorded route nothing is guessed from the key."""
        self.write([
            row(session_id="proc_ours", session_key=CHAT_ROUTE, parent_session_id=CHAT),
            row(session_id="proc_later", session_key=CHAT_ROUTE, parent_session_id="20261029_100000_cc22dd"),
            row(session_id="proc_unparented", session_key=CHAT_ROUTE, parent_session_id=""),
            row(session_id="proc_longer", session_key=f"{CHAT_ROUTE}6", parent_session_id=CHAT),
            row(session_id="proc_shorter", session_key=CHAT_ROUTE[:-1], parent_session_id=CHAT),
            row(session_id="proc_default", session_key="agent:main:telegram:dm:12345", parent_session_id=CHAT),
            row(session_id="proc_thread", session_key=f"{CHAT_ROUTE}:77", parent_session_id=CHAT),
        ])
        self.assertEqual([found.proc_id for found in read_processes(self.home, CHAT, routes=(CHAT_ROUTE,))],
                         ["proc_ours"])
        self.assertEqual(read_processes(self.home, CHAT), ())
        self.assertEqual(read_processes(self.home, "20261029_100000_cc22dd"), ())

    def test_recorded_routes_are_read_off_the_session_rows_and_nothing_else(self) -> None:
        self.assertEqual(recorded_routes(self.home, (CHAT,)), ((), False))  # no state.db
        write_sessions(Path(self.home), session_row(CHAT), session_row("other"), session_row("bare"))
        record_routes(self.home, {CHAT: CHAT_ROUTE, "other": "agent:main:discord:dm:9", "bare": ""})
        self.assertEqual(recorded_routes(self.home, (CHAT,)), ((CHAT_ROUTE,), True))
        self.assertEqual(recorded_routes(self.home, (CHAT, "bare", "missing")), ((CHAT_ROUTE,), True))
        self.assertEqual(recorded_routes(self.home, ("bare",)), ((), True))  # a row with no key: settled
        self.assertEqual(recorded_routes(self.home, ("missing",)), ((), False))
        self.assertEqual(recorded_routes(self.home, ()), ((), False))
        self.assertEqual(recorded_routes(None, (CHAT,)), ((), False))
        (Path(self.home) / "state.db").write_bytes(b"not a database\n" * 64)
        self.assertEqual(recorded_routes(self.home, (CHAT,)), ((), False))

    def test_the_earlier_segments_of_the_conversation_are_owned_too(self) -> None:
        """Rotating compaction re-anchors the stored id (tui_gateway/session_compression.py:331); a process started
        before keeps its key."""
        self.write([row(session_id="proc_before", session_key="20261028_101500_ab12cd",
                        parent_session_id="20261028_101500_ab12cd"),
                    row(session_id="proc_after", session_key="20261028_111500_cd34ef",
                        parent_session_id="20261028_111500_cd34ef")])
        self.assertEqual([found.proc_id for found in read_processes(self.home, "20261028_111500_cd34ef")],
                         ["proc_after"])
        self.assertEqual(
            [found.proc_id for found in read_processes(self.home, "20261028_111500_cd34ef", ("20261028_101500_ab12cd",))],
            ["proc_before", "proc_after"],
        )

    def test_notify_and_watch_patterns_are_read_as_hermes_writes_them(self) -> None:
        self.write([
            row(session_id="proc_a", notify_on_complete=True),
            row(session_id="proc_b", watch_patterns=["READY"]),
            row(session_id="proc_c", notify_on_complete="true", watch_patterns=[""]),
            row(session_id="proc_d", pid_scope="sandbox", pid=True),
        ])
        found = {process.proc_id: process for process in read_processes(self.home, STORED)}
        self.assertEqual((found["proc_a"].notify, found["proc_a"].watched), (True, False))
        self.assertEqual((found["proc_b"].notify, found["proc_b"].watched), (False, True))
        self.assertEqual((found["proc_c"].notify, found["proc_c"].watched), (False, False))
        self.assertEqual((found["proc_d"].host, found["proc_d"].pid), (False, None))

    def test_a_missing_malformed_or_huge_file_reads_as_nothing_and_never_raises(self) -> None:
        self.assertEqual(read_processes(self.home, STORED), ())  # no file
        self.assertEqual(read_processes(None, STORED), ())
        for payload in ("{not json", '{"rows": []}', "[1, null, \"x\"]", "[" * 100_000 + "]" * 100_000,
                        json.dumps([row(session_id=7), row(started_at=True), row(started_at=float("nan")),
                                    row(command=None), row(session_id=""), row(started_at=10**400),
                                    row(started_at=-(10**400)), row(started_at=1e300)])):
            with self.subTest(payload=payload[:20]):
                self.write(payload)
                self.assertEqual(read_processes(self.home, STORED), ())
        # Numbers too big to be a pid or a start time are dropped, not carried to where they would overflow.
        nested = "[" * 900 + "]" * 900  # deep, but within what the decoder takes
        self.write("[" + json.dumps(row(host_start_time=10**400, pid=10**400)).replace(
            '"watch_patterns": []', f'"watch_patterns": {nested}') + "]")
        (found,) = read_processes(self.home, STORED)
        self.assertEqual((found.start_time, found.pid, found.watched), (None, None, False))
        # Its liveness cannot be asked without a pid, so it runs while listed; nothing raises.
        self.assertEqual(list(still_running({}, (found,))), [found.proc_id])

    def test_a_huge_number_never_ends_the_poller_thread(self) -> None:
        # The row with no start is dropped; one with no usable start time or pid runs while it is listed.
        cases = (({"started_at": 10**400}, ()), ({"host_start_time": 10**400}, ((os.getpid(), None),)),
                 ({"pid": -(10**400)}, ((None, None),)))
        for fields, expected in cases:
            with self.subTest(fields=list(fields)):
                self.write([row(**{"pid": os.getpid(), **fields})])
                poller = HudPoller("/omh", None, reader=lambda *_a, **_k: {"hermes_home": self.home}, clock=lambda: 5.0)
                poller.set_session(STORED)
                poller.poll_once()  # raises nothing: on the poller's thread an exception would end the thread
                found = poller.take().processes
                self.assertEqual(tuple((process.pid, process.start_time) for process in found), expected)
        self.write(json.dumps([row()]).ljust(PROCESSES_MAX_BYTES + 1))
        self.assertEqual(read_processes(self.home, STORED), ())
        self.path.unlink()
        self.path.mkdir()  # a directory where the file goes
        self.assertEqual(read_processes(self.home, STORED), ())

    def test_the_file_is_never_written(self) -> None:
        self.write([row()])
        before = (self.path.read_bytes(), self.path.stat().st_mtime_ns)
        read_processes(self.home, STORED)
        self.assertEqual((self.path.read_bytes(), self.path.stat().st_mtime_ns), before)


class LabelTests(unittest.TestCase):
    def test_a_leading_cd_and_assignments_are_dropped(self) -> None:
        cases = {
            COMMAND: "uv run python -m unittest tests…",
            "cd /repo && pytest -x tests/test_payment.py": "pytest -x tests/test_payment.py",
            'cd "/a b" && L=/tmp/e2e && rm -rf $L && mkdir -p $L': "rm -rf $L && mkdir -p $L",
            'FOO="a b c" BAR=1 make test': "make test",
            "pytest": "pytest",
            "cd /repo": "cd /repo",  # nothing follows the cd: the command is what it says
            "--flag=1 run": "--flag=1 run",  # not an assignment
            "  npm\ttest  ": "npm test",
            "\x1b[31mnpm test": "npm test",  # escapes never reach the label
        }
        for command, label in cases.items():
            with self.subTest(command=command):
                self.assertEqual(process_label(command), label)

    def test_a_long_command_is_cut_with_an_ellipsis(self) -> None:
        label = process_label("python " + "x" * 80)
        self.assertEqual(cell_width(label), LABEL_CELLS)
        self.assertTrue(label.endswith("…"))

    def test_the_report_prompt_names_the_call_and_the_process(self) -> None:
        self.assertEqual(
            report_prompt((process(),)),
            "The background process `terminal(uv run python -m unittest tests…)` (proc_36b5cd4d7445) finished. "
            "Check its result and continue.",
        )
        self.assertEqual(
            report_prompt((process(proc_id="proc_a", command="make lint"), process(proc_id="proc_b", command="ls"))),
            "The background processes `terminal(make lint)` (proc_a), `terminal(ls)` (proc_b) finished. "
            "Check their results and continue.",
        )


class StillRunningTests(unittest.TestCase):
    def test_a_row_the_file_dropped_is_kept_while_its_process_runs(self) -> None:
        tracked = {"proc_a": process(proc_id="proc_a")}
        self.assertEqual(list(still_running(tracked, (), probe=lambda _p: True)), ["proc_a"])
        self.assertEqual(still_running(tracked, (), probe=lambda _p: False), {})

    def test_a_listed_row_whose_process_ended_is_not_running(self) -> None:
        self.assertEqual(still_running({}, (process(),), probe=lambda _p: False), {})

    def test_where_nothing_can_be_asked_the_file_decides(self) -> None:
        listed = process(proc_id="proc_b", host=False)
        kept = still_running({"proc_a": process(proc_id="proc_a", host=False)}, (listed,), probe=lambda _p: None)
        self.assertEqual(list(kept), ["proc_b"])

    def test_the_listed_copy_is_the_newer_one(self) -> None:
        kept = still_running({"proc_a": process(proc_id="proc_a")}, (process(proc_id="proc_a", notify=True),),
                             probe=lambda _p: True)
        self.assertTrue(kept["proc_a"].notify)

    @unittest.skipUnless(ON_POSIX, "signal 0 is a probe only on POSIX")
    def test_the_default_probe_asks_the_process(self) -> None:
        with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE) as child:
            try:
                started = process_facts(child.pid)[0]  # recorded while it runs, as Hermes records it at spawn
            finally:
                child.kill()
            child.wait(timeout=30)
        # Reaped, with its start time: a later process given the same pid does not pass for it.
        alive = process(proc_id="proc_alive", pid=os.getpid())
        ended = process(proc_id="proc_ended", pid=child.pid, start_time=started)
        self.assertEqual(list(still_running({}, (alive, ended))), ["proc_alive"])
        # A pid that is alive under another start time is another process: the recorded one ended.
        reused = process(proc_id="proc_reused", pid=os.getpid(), start_time=1)
        self.assertEqual(still_running({"proc_reused": reused}, ()), {})


class PollerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.path = Path(self.home) / PROCESSES_FILE
        self.poller = HudPoller("/omh", None, reader=lambda *_a, **_k: {"hermes_home": self.home}, clock=lambda: 5.0)

    def test_a_read_carries_this_session_s_running_processes(self) -> None:
        pid = os.getpid()
        self.path.write_text(json.dumps([
            row(pid=pid, started_at=NOW), row(session_id="proc_other", pid=pid, session_key="another"),
        ]), encoding="utf-8")
        self.poller.set_session(STORED)
        self.poller.take()  # the empty snapshot a switch delivers
        self.poller.poll_once()
        snapshot = self.poller.take()
        self.assertIsNotNone(snapshot)
        self.assertEqual([found.proc_id for found in snapshot.processes], ["proc_36b5cd4d7445"])

    @unittest.skipUnless(ON_POSIX, "signal 0 is a probe only on POSIX")
    def test_a_process_another_rewrite_dropped_stays_until_it_ends_and_its_end_is_a_change(self) -> None:
        self.path.write_text(json.dumps([row(pid=os.getpid())]), encoding="utf-8")
        self.poller.set_session(STORED)
        self.poller.poll_once()
        self.path.write_text("[]", encoding="utf-8")  # another interpreter of the profile rewrote it
        self.poller.poll_once()
        self.assertEqual(len(self.poller.take().processes), 1)
        self.poller.poll_once()
        self.assertIsNone(self.poller.take())  # nothing changed
        self.poller.set_session("rotated")
        self.assertEqual(self.poller.take().processes, ())


    def test_a_rotation_keeps_the_conversation_s_processes(self) -> None:
        """QA R-E: with `compression.in_place: false` Hermes moves the session to a new stored id
        (tui_gateway/session_compression.py:331) and writes the rotation into state.db (`publish_compression_child`);
        a process started before keeps its key. The first read of the new id verifies the link and keeps them."""
        write_sessions(Path(self.home), compacted("seg_a", at=1050.0), session_row("seg_b", parent="seg_a"),
                       session_row("other"))
        host = row(session_id="proc_host", session_key="seg_a", parent_session_id="seg_a", pid=os.getpid())
        sandbox = row(session_id="proc_sandbox", session_key="seg_a", parent_session_id="seg_a", pid_scope="sandbox")
        self.path.write_text(json.dumps([host, sandbox]), encoding="utf-8")
        self.poller.set_session("seg_a")
        self.poller.poll_once()
        self.assertEqual(len(self.poller.take().processes), 2)
        if ON_POSIX:  # a host process another rewrite dropped is kept while it runs, across the rotation too
            self.path.write_text(json.dumps([sandbox]), encoding="utf-8")
        self.poller.set_session("seg_b")
        self.assertEqual(self.poller.take().processes, ())  # the switch's own snapshot reads nothing
        self.poller.poll_once()
        snapshot = self.poller.take()
        self.assertEqual({found.proc_id for found in snapshot.processes}, {"proc_host", "proc_sandbox"})
        self.assertEqual((snapshot.session_id, snapshot.earlier), ("seg_b", ("seg_a",)))
        # Another conversation is not a rotation: nothing of seg_b's is carried into it.
        self.poller.set_session("other")
        self.poller.poll_once()
        snapshot = self.poller.take()
        self.assertEqual((snapshot.processes, snapshot.earlier), ((), ()))

    def test_a_resumed_messaging_session_shows_the_processes_its_turns_started(self) -> None:
        """A bot profile's Telegram session resumed here: matched on the route Hermes recorded on its row, including
        after a rotation (a continuation inherits the route, hermes_state_sessions.py:392-395 at origin/main).
        Also a named profile's local session, `agent:<profile>:local:dm:<id>`, recorded the same way."""
        local = "local-5f0e9d8c7b6a5f4e3d2c1b0a99887766554433221100ffeeddccbbaa99887766"
        local_route = f"agent:kami:local:dm:{local}"
        self.path.write_text(json.dumps([
            row(session_id="proc_chat", pid=os.getpid(), session_key=CHAT_ROUTE, parent_session_id=CHAT),
            row(session_id="proc_later", pid=os.getpid(), session_key=CHAT_ROUTE,
                parent_session_id="20261029_100000_cc22dd"),
            row(session_id="proc_local", pid=os.getpid(), session_key=local_route, parent_session_id=local),
        ]), encoding="utf-8")
        self.poller.set_session(CHAT)
        self.poller.poll_once()
        self.assertEqual(self.poller.take().processes, ())  # no row records a route yet: nothing is guessed
        write_sessions(Path(self.home), compacted(CHAT, at=1050.0), session_row("20261029_110000_ee33ff", parent=CHAT),
                       session_row("20261029_100000_cc22dd"), session_row(local))
        record_routes(self.home, {CHAT: CHAT_ROUTE, "20261029_110000_ee33ff": CHAT_ROUTE,
                                  "20261029_100000_cc22dd": CHAT_ROUTE, local: local_route})
        self.poller.poll_once()  # the row came after the first read: asked again
        self.assertEqual([found.proc_id for found in self.poller.take().processes], ["proc_chat"])
        self.poller.set_session("20261029_110000_ee33ff")
        self.poller.poll_once()
        self.assertEqual([found.proc_id for found in self.poller.take().processes], ["proc_chat"])
        self.poller.set_session(local)
        self.poller.poll_once()
        self.assertEqual([found.proc_id for found in self.poller.take().processes], ["proc_local"])

    def test_a_refresh_keeps_the_next_read_even_when_nothing_changed(self) -> None:
        self.path.write_text("[]", encoding="utf-8")
        self.poller.set_session(STORED)
        self.poller.poll_once()
        self.poller.take()
        self.poller.poll_once()
        self.assertIsNone(self.poller.take())  # nothing changed
        self.poller.refresh()  # a turn ended
        self.poller.poll_once()
        self.assertIsNotNone(self.poller.take())
        self.poller.poll_once()
        self.assertIsNone(self.poller.take())  # once

    def test_a_read_under_way_at_a_refresh_is_not_the_read_it_asks_for(self) -> None:
        reads: list[int] = []

        def reader(*_args: object, **_kwargs: object) -> dict:
            reads.append(1)
            if len(reads) == 3:
                poller.refresh()  # the turn ends while this read is under way
            return {"hermes_home": self.home}

        poller = HudPoller("/omh", None, reader=reader, clock=lambda: 5.0)
        poller.set_session(STORED)
        poller.poll_once()
        poller.take()
        poller.poll_once()
        self.assertIsNone(poller.take())
        poller.poll_once()
        self.assertIsNone(poller.take())  # it may have read the file before the turn ended
        poller.poll_once()
        self.assertIsNotNone(poller.take())


class OwnershipTests(unittest.TestCase):
    """One rule for every key (review of #2388): a row that names its spawning session (`parent_session_id`,
    tools/process_registry.py:581-583,1092; terminal_tool_background.py:70-73) is this session's only when that is
    one of its ids or a subagent it delegated to (delegate_tool.py:343 stamps `_delegate_from`;
    delegate_tool_dispatch.py:76-79: the child's id replaces HERMES_SESSION_ID). State.db is read on the poller
    thread only, a bounded number of times."""

    LOCAL = "local-0d1c2b3a49586776a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f00f1e"

    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.path = Path(self.home) / PROCESSES_FILE
        self.poller = HudPoller("/omh", None, reader=lambda *_a, **_k: {"hermes_home": self.home}, clock=lambda: 5.0)

    def processes(self, rows: list[dict], session: str) -> list[str]:
        self.path.write_text(json.dumps(rows), encoding="utf-8")
        self.poller.set_session(session)
        self.poller.poll_once()
        snapshot = self.poller.take()
        return sorted(found.proc_id for found in snapshot.processes) if snapshot is not None else []

    def sessions(self) -> None:
        local_route = f"agent:main:local:dm:{self.LOCAL}"
        write_sessions(
            Path(self.home),
            session_row(self.LOCAL, source="local"),
            session_row("child", parent=self.LOCAL, source="subagent", delegate_from=self.LOCAL),
            session_row("grandchild", parent="child", source="subagent", delegate_from="child"),
            compacted("rotated_child", at=1050.0, parent=self.LOCAL, source="subagent", delegate_from=self.LOCAL),
            session_row("rotated_child_2", parent="rotated_child", source="subagent", delegate_from=self.LOCAL),
            session_row("branch", parent=self.LOCAL, config={"_branched_from": self.LOCAL}),
            session_row("reset", parent=self.LOCAL, source="local", config={"_reset_from": self.LOCAL}),
            session_row("unrelated", source="local"),
            session_row(CHAT, source="telegram"),
            session_row("chat_child", parent=CHAT, source="subagent", delegate_from=CHAT),
        )
        record_routes(self.home, {self.LOCAL: local_route, "reset": local_route, CHAT: CHAT_ROUTE})

    def test_a_delegated_child_s_process_is_this_session_s_on_a_local_and_a_messaging_route(self) -> None:
        self.sessions()
        local_route = f"agent:main:local:dm:{self.LOCAL}"
        rows = [row(session_id=f"proc_{parent[:12]}", pid=os.getpid(), session_key=local_route,
                    parent_session_id=parent)
                for parent in (self.LOCAL, "child", "grandchild", "rotated_child_2", "branch", "reset", "unrelated",
                               "nowhere")]
        self.assertEqual(self.processes(rows, self.LOCAL),
                         sorted(f"proc_{parent[:12]}"
                                for parent in (self.LOCAL, "child", "grandchild", "rotated_child_2")))
        rows = [row(session_id=f"proc_{parent}", pid=os.getpid(), session_key=CHAT_ROUTE, parent_session_id=parent)
                for parent in (CHAT, "chat_child", "child", "unrelated")]
        self.assertEqual(self.processes(rows, CHAT), [f"proc_{CHAT}", "proc_chat_child"])

    def test_after_a_reset_neither_conversation_shows_or_offers_the_other_s_process(self) -> None:
        """A gateway-side `/new` keeps the local route (`reset_local_session`, gateway/session_local_recovery.py
        :379-392) and Hermes drops the old conversation's completion; OMH must not offer it to the new one."""
        self.sessions()
        local_route = f"agent:main:local:dm:{self.LOCAL}"
        old = row(session_id="proc_old", pid=os.getpid(), session_key=local_route, parent_session_id=self.LOCAL)
        new = row(session_id="proc_new", pid=os.getpid(), session_key=local_route, parent_session_id="reset")
        self.assertEqual(self.processes([old, new], "reset"), ["proc_new"])
        self.assertEqual(self.processes([old, new], self.LOCAL), ["proc_old"])
        app, client = make_app(cols=120)
        app.stored_id, app.poller = "reset", self.poller
        self.processes([old], "reset")
        self.poller.poll_once()
        app._take_hud()
        self.assertIsNone(app._background_line(120))
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit"), [])

    def test_delegation_is_followed_to_its_depth_and_no_further(self) -> None:
        """Second review 1: the last link read was never tested, so a chain of `DELEGATION_DEPTH` links read as no."""
        chain, parent = [session_row("us")], "us"
        for depth in range(1, DELEGATION_DEPTH + 2):
            chain.append(session_row(f"d{depth}", parent=parent, source="subagent", delegate_from=parent))
            parent = f"d{depth}"
        chain += [session_row("cA", parent="cB", source="subagent", delegate_from="cB"),
                  session_row("cB", parent="cA", source="subagent", delegate_from="cA")]
        write_sessions(Path(self.home), *chain)
        for depth in (1, DELEGATION_DEPTH - 1, DELEGATION_DEPTH):
            self.assertIs(delegated_from(self.home, f"d{depth}", ("us",)), True, depth)
        self.assertIs(delegated_from(self.home, f"d{DELEGATION_DEPTH + 1}", ("us",)), False)
        self.assertIs(delegated_from(self.home, "cA", ("us",)), False)  # a cycle ends at the bound
        self.assertIsNone(delegated_from(self.home, "not_yet", ("us",)))  # no row: undecided, not "no"
        self.assertIsNone(delegated_from(str(Path(self.home) / "missing"), "d1", ("us",)))
        with patch("omh.plugin_bundle.omh.live_session.compaction_ancestors", side_effect=PermissionError):
            self.assertIsNone(delegated_from(self.home, "d1", ("us",)))  # second review 5: never raises

    def test_an_undecided_child_is_asked_again_without_a_turn_ending(self) -> None:
        """Second review 2: a child whose row was not there at first sight stayed "not ours" until a refresh, which
        an idle TUI watching a resumed session never makes. Undecided answers are asked again, `PARENT_READS` times."""
        write_sessions(Path(self.home), session_row("us"))
        self.path.write_text(json.dumps([
            row(session_id="proc_kid", session_key="us", parent_session_id="kid", pid_scope="sandbox"),
            row(session_id="proc_ghost", session_key="us", parent_session_id="ghost", pid_scope="sandbox"),
        ]), encoding="utf-8")
        self.poller.set_session("us")
        self.poller.poll_once()
        self.assertEqual(self.poller.take().processes, ())
        connection = sqlite3.connect(Path(self.home) / "state.db")
        connection.execute("INSERT INTO sessions (id, source, model_config, parent_session_id, started_at) "
                           "VALUES ('kid', 'subagent', ?, 'us', 1000.0)", (json.dumps({"_delegate_from": "us"}),))
        connection.commit()
        connection.close()
        self.poller.poll_once()
        self.assertEqual([found.proc_id for found in self.poller.take().processes], ["proc_kid"])
        with patch("omh.tui.panels.delegated_from", side_effect=delegated_from) as asked:
            for _ in range(PARENT_READS + 5):
                self.poller.poll_once()
        self.assertEqual(asked.call_count, PARENT_READS - 2)  # `ghost` was asked twice before: bounded

    def test_a_no_decided_against_an_unverified_lineage_is_asked_again_once_it_settles(self) -> None:
        """Second review 3: a child of the earlier segment, judged before the lineage verified it, stayed not ours."""
        write_sessions(Path(self.home), compacted("E", at=1050.0),
                       session_row("kid", parent="E", source="subagent", delegate_from="E"))
        # Under the local route of S, so the first read asks about `kid` while the lineage cannot name E yet.
        self.path.write_text(json.dumps([row(session_id="proc_k", session_key="agent:main:local:dm:S",
                                             parent_session_id="kid", pid_scope="sandbox")]), encoding="utf-8")
        self.poller.set_session("S")  # its row not readable yet: the lineage is unverified
        self.poller.poll_once()
        self.assertEqual(self.poller.take().processes, ())
        connection = sqlite3.connect(Path(self.home) / "state.db")
        connection.execute("INSERT INTO sessions (id, source, parent_session_id, started_at) "
                           "VALUES ('S', 'tui', 'E', 1050.0)")
        connection.commit()
        connection.close()
        self.poller.poll_once()
        snapshot = self.poller.take()
        self.assertEqual(([found.proc_id for found in snapshot.processes], snapshot.earlier), (["proc_k"], ("E",)))

    def test_a_parallel_continuation_of_an_earlier_segment_counts_as_this_conversation(self) -> None:
        """Decided with the review: a second continuation X beside S under the earlier segment E (a raced compaction
        or a reconnect's stale sibling) is in the conversation by OMH's one lineage rule (`conversation_segments`
        includes it; Hermes' own chain walk meets it), so its processes are this session's too."""
        write_sessions(Path(self.home), compacted("E", at=1050.0), session_row("S", parent="E"),
                       session_row("X", parent="E"))
        rows = [row(session_id="proc_x", session_key="E", parent_session_id="X", pid_scope="sandbox")]
        self.path.write_text(json.dumps(rows), encoding="utf-8")
        self.poller.set_session("S")
        self.poller.poll_once()
        self.assertEqual([found.proc_id for found in self.poller.take().processes], ["proc_x"])

    def test_a_read_that_raises_never_ends_the_thread_nor_reads_as_an_end(self) -> None:
        """Second review 5: an exception past the readers' guards ended the poller thread for the session."""
        self.path.write_text(json.dumps([row(session_id="proc_live", session_key="us", parent_session_id="us",
                                             pid_scope="sandbox")]), encoding="utf-8")
        self.poller.set_session("us")
        self.poller.poll_once()
        self.poller.take()
        reads = []

        def failing() -> float:
            reads.append(1)
            if len(reads) == 1:
                raise PermissionError("state.db")
            self.poller._stopping.set()
            return 0.0

        with patch.object(self.poller, "poll_once", side_effect=failing), \
                patch("omh.tui.panels.HUD_POLL_MAX_SECONDS", 0.01):
            self.poller.start()
            self.poller._thread.join(5)
        self.assertFalse(self.poller._thread.is_alive())
        self.assertEqual(len(reads), 2)  # read again after the failure
        snapshot = self.poller.take()
        # Delta review 1: the class, where it raised and its repr, so a failure that repeats is diagnosable.
        raised_at = failing.__code__.co_firstlineno + 3
        self.assertEqual(snapshot.payload,
                         {"error": f"PermissionError at failing:{raised_at}: PermissionError('state.db')"})
        self.assertEqual([found.proc_id for found in snapshot.processes], ["proc_live"])
        self.assertEqual((snapshot.refreshes, snapshot.failed), (0, True))

    def test_a_raising_wake_never_ends_the_thread(self) -> None:
        """Delta review 4: the callback a read ends with ran outside the guard; the failed read calls none."""
        self.path.write_text("[]", encoding="utf-8")
        reads = []

        def reader(*_args: object, **_kwargs: object) -> dict:
            reads.append(1)
            if len(reads) >= 3:
                self.poller._stopping.set()
            return {"hermes_home": self.home, "n": len(reads)}  # every read changes: every read wakes

        def wake() -> None:
            raise RuntimeError("the UI went away")

        self.poller = HudPoller("/omh", None, reader=reader, clock=lambda: 5.0)
        self.poller.set_session("us")
        with patch("omh.tui.panels.HUD_POLL_MAX_SECONDS", 0.01), patch("omh.tui.panels.HUD_POLL_MIN_SECONDS", 0.01):
            self.poller.start(wake)
            self.poller._thread.join(5)
        self.assertFalse(self.poller._thread.is_alive())
        self.assertGreaterEqual(len(reads), 3)  # it read on after each raising wake
        self.assertTrue(self.poller.take().failed)

    def test_a_failed_read_changes_nothing_the_row_holds(self) -> None:
        """Delta review 2 and 3: a failed snapshot stamped kept processes quiet (`bg_after` 0 before the first turn
        ends) and, right after a switch to a rotated session, read as a session change that reset the row."""
        app, _client = make_app(cols=120)
        app.stored_id = "seg_a"
        app._take_background(HudSnapshot("seg_a", {}, 0.0, {}, (process(proc_id="proc_a"),)))
        held = (app.bg_session, app.bg_running, dict(app.bg_quiet), app.bg_done)
        app.bg_quiet = {}
        app._take_background(HudSnapshot("seg_a", {"error": "X"}, 0.0, {}, (process(proc_id="proc_a"),), 0,
                                         failed=True))
        self.assertEqual(app.bg_quiet, {})  # nothing stamped quiet
        app.bg_quiet = held[2]
        app.stored_id = "seg_b"  # rotated; the first read of seg_b fails
        app._take_background(HudSnapshot("seg_b", {"error": "X"}, 0.0, {}, (), 0, failed=True))
        self.assertEqual((app.bg_session, app.bg_running, app.bg_quiet, app.bg_done), held)
        app._take_background(HudSnapshot("seg_b", {}, 0.0, {}, (process(proc_id="proc_a"),), 0, ("seg_a",)))
        self.assertEqual((app.bg_session, [found.proc_id for found in app.bg_running]), ("seg_b", ["proc_a"]))

    def test_an_unverified_lineage_is_asked_again_and_the_carry_waits_for_it(self) -> None:
        """Review L1: an `unverified` answer (the continuation's row not there yet) was kept for the session."""
        self.path.write_text(json.dumps([row(session_id="proc_seg", session_key="seg_a", parent_session_id="seg_a",
                                             pid_scope="sandbox")]), encoding="utf-8")
        write_sessions(Path(self.home), session_row("seg_a"))
        self.poller.set_session("seg_a")
        self.poller.poll_once()
        self.poller.set_session("seg_b")  # Hermes said the new id before its row is readable here
        self.poller.poll_once()
        self.assertEqual(self.poller.take().processes, ())
        connection = sqlite3.connect(Path(self.home) / "state.db")
        connection.execute("UPDATE sessions SET ended_at = 1050.0, end_reason = 'compression' WHERE id = 'seg_a'")
        connection.execute("INSERT INTO sessions (id, source, started_at, parent_session_id) "
                           "VALUES ('seg_b', 'tui', 1050.0, 'seg_a')")
        connection.commit()
        connection.close()
        self.poller.poll_once()
        snapshot = self.poller.take()
        self.assertEqual(([found.proc_id for found in snapshot.processes], snapshot.earlier),
                         (["proc_seg"], ("seg_a",)))
        with patch("omh.tui.panels.earlier_segments") as asked:
            self.poller.poll_once()
        asked.assert_not_called()  # resolved: kept
        self.poller.set_session("seg_never")  # never resolves: asked a bounded number of times
        with patch("omh.tui.panels.earlier_segments", return_value=((), False)) as asked:
            for _ in range(LINEAGE_READS + 5):
                self.poller.poll_once()
        self.assertEqual(asked.call_count, LINEAGE_READS)

    def test_the_route_is_asked_until_the_row_is_there_and_again_after_a_turn(self) -> None:
        """Review L2: a session whose row records no key (the stdio lane) was asked every poll."""
        self.path.write_text("[]", encoding="utf-8")
        write_sessions(Path(self.home), session_row("tui_sess"))
        record_routes(self.home, {})
        real = recorded_routes
        with patch("omh.tui.panels.recorded_routes", side_effect=real) as asked:
            self.poller.set_session("tui_sess")
            for _ in range(20):
                self.poller.poll_once()
            self.assertEqual(asked.call_count, 1)  # the row is there with no key: settled
            self.poller.refresh()  # a turn ended: it may have recorded one
            self.poller.poll_once()
            self.poller.poll_once()
            self.assertEqual(asked.call_count, 2)
            self.poller.set_session("missing")
            for _ in range(ROUTE_READS + 5):
                self.poller.poll_once()
            self.assertEqual(asked.call_count, 2 + ROUTE_READS)
        connection = sqlite3.connect(Path(self.home) / "state.db")
        connection.execute("UPDATE sessions SET session_key = ? WHERE id = 'tui_sess'", (CHAT_ROUTE,))
        connection.commit()
        connection.close()
        self.path.write_text(json.dumps([row(session_id="proc_routed", pid_scope="sandbox", session_key=CHAT_ROUTE,
                                             parent_session_id="tui_sess")]), encoding="utf-8")
        self.poller.set_session("tui_sess")
        self.poller.poll_once()
        self.assertEqual([found.proc_id for found in self.poller.take().processes], ["proc_routed"])


@unittest.skipUnless(ON_POSIX, "signal 0 is a probe only on POSIX")
class TurnEndTests(unittest.TestCase):
    """The poller and the app together, a real process in a checkpoint row, nothing else in the read changing."""

    def setUp(self) -> None:
        self.home = tempfile.mkdtemp()
        self.clock, self.wall = Clock(100.0), Clock(NOW)
        self.app, _client = make_app(cols=120, clock=self.clock, wall_clock=self.wall)
        self.app.stored_id = STORED
        self.app.poller = HudPoller("/omh", None, reader=lambda *_a, **_k: {"hermes_home": self.home},
                                    clock=lambda: 5.0)
        self.app.poller.set_session(STORED)

    def read(self) -> None:
        self.app.poller.poll_once()
        self.app._take_hud()

    def start_turn_with(self, child: subprocess.Popen) -> None:
        """A turn starts `child` in the background (notify off) and the poller reads it while the turn runs."""
        started = process_facts(child.pid)[0]
        (Path(self.home) / PROCESSES_FILE).write_text(json.dumps([row(pid=child.pid, host_start_time=started)]),
                                                      encoding="utf-8")
        self.app.turn_pending = True
        self.app.busy_since = self.clock.at
        self.read()
        self.assertTrue(text(self.app._background_line(120)).startswith(f"{GLYPH} background"))
        self.clock.at += 1

    def end_turn(self) -> None:
        self.app.turn_pending = False  # as `message.complete` ends it
        self.app._turn_ended()

    def test_a_process_first_seen_during_a_turn_finishes_once_it_ends_after_the_turn(self) -> None:
        with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE) as child:
            try:
                self.start_turn_with(child)
                self.end_turn()
                self.read()  # the read after the turn: nothing in it changed, and it is delivered
                self.app.poller.poll_once()
                self.assertIsNone(self.app.poller.take())  # an idle session's reads are unchanged from here on
                self.assertTrue(text(self.app._background_line(120)).endswith("OMH is watching it"))
                before = bells(self.app)
            finally:
                child.kill()
            child.wait(timeout=30)
        self.clock.at += 3600
        self.wall.at += 3600
        self.read()
        self.assertTrue(text(self.app._background_line(120)).startswith("✓ background"),
                        text(self.app._background_line(120)))
        self.assertEqual(bells(self.app), before + 1)
        self.read()
        self.assertEqual(bells(self.app), before + 1)

    def test_a_read_taken_during_the_turn_and_handed_over_after_it_stamps_nothing(self) -> None:
        reads = iter(range(1, 1000))
        # The HUD payload changes on every read, as a live turn's does, so each read is a snapshot of its own.
        self.app.poller = HudPoller("/omh", None, reader=lambda *_a, **_k: {"hermes_home": self.home,
                                                                             "tick": next(reads)}, clock=lambda: 5.0)
        self.app.poller.set_session(STORED)
        with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE) as child:
            try:
                self.start_turn_with(child)
                self.app.poller.poll_once()  # mid-turn: it lists the process, and it waits to be taken
            finally:
                child.kill()
            child.wait(timeout=30)  # the process ends while the turn still runs
        before = bells(self.app)
        self.end_turn()  # `message.complete`, in the same loop step as the `_take_hud` below
        self.app._take_hud()  # the mid-turn read, taken with no turn running
        self.clock.at += 1
        self.read()  # the read the refresh asked for: the process is gone
        self.assertIsNone(self.app._background_line(120))
        self.assertEqual(bells(self.app), before)

    def test_a_process_that_ended_during_the_turn_just_goes(self) -> None:
        with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE) as child:
            try:
                self.start_turn_with(child)
                before = bells(self.app)
            finally:
                child.kill()
            child.wait(timeout=30)
        self.end_turn()
        self.read()
        self.assertIsNone(self.app._background_line(120))
        self.assertEqual(bells(self.app), before)


def ask_on_any_platform(case: unittest.TestCase) -> None:
    """`askable` as on POSIX, so a host process's end can be asked on Windows too; the rows are what is tested."""
    patcher = patch("omh.tui.background.ON_POSIX", True)
    patcher.start()
    case.addCleanup(patcher.stop)


class RowTests(unittest.TestCase):
    def setUp(self) -> None:
        ask_on_any_platform(self)
        self.clock, self.wall = Clock(100.0), Clock(NOW)
        self.app, self.client = make_app(cols=120, clock=self.clock, wall_clock=self.wall)
        self.app.stored_id = STORED

    def deliver(self, *processes: BackgroundProcess, session: str = STORED, earlier: tuple[str, ...] = ()) -> None:
        snapshot = HudSnapshot(session, {}, 0.0, {}, tuple(processes))
        if earlier:
            snapshot = replace(snapshot, earlier=earlier)
        self.app.poller.take = lambda: snapshot
        self.app._take_hud()

    def shown(self) -> str:
        return text(self.app._background_line(120))

    def test_nothing_shows_without_a_process(self) -> None:
        self.deliver()
        self.assertIsNone(self.app._background_line(120))
        self.assertFalse(any("background" in line for line in drawn(self.app)))

    def test_a_turn_in_progress_shows_no_right_side(self) -> None:
        self.app.turn_pending = True
        self.deliver(process())
        self.assertEqual(self.shown().split("  "), [f"{GLYPH} background",
                                                     "terminal(uv run python -m unittest tests…)",
                                                     "1h 07m 13s"])

    def test_after_the_turn_it_says_hermes_will_ping_when_notify_is_on(self) -> None:
        self.deliver(process(notify=True))
        self.assertTrue(self.shown().endswith("  🔔 will ping you when done"), self.shown())

    def test_watch_patterns_wake_the_session_on_a_match_not_on_exit(self) -> None:
        self.deliver(process(watched=True))
        self.assertTrue(self.shown().endswith("  🔔 will ping you on a match"), self.shown())

    def test_with_nothing_to_wake_the_session_it_says_omh_is_watching(self) -> None:
        self.deliver(process())
        shown = self.shown()
        self.assertTrue(
            shown.startswith(f"{GLYPH} background  terminal(uv run python -m unittest tests…)  1h 07m 13s"))
        self.assertTrue(shown.endswith("  🔕 Hermes won't be pinged · OMH is watching it"), shown)
        self.assertEqual(line_width(self.app._background_line(120)), 120)
        self.assertIn(shown.rstrip(), [line.rstrip() for line in drawn(self.app)])

    def test_the_row_sits_right_above_the_composer_s_top_rule(self) -> None:
        self.deliver(process())
        screen = drawn(self.app)
        rule = next(index for index, line in enumerate(screen) if line.startswith("─") and index > 0)
        self.assertTrue(screen[rule - 1].startswith(f"{GLYPH} background"), screen[rule - 1])

    def test_the_elapsed_clock_ticks_in_seconds(self) -> None:
        self.deliver(process())
        first = self.shown()
        self.wall.at += 1
        self.assertIn("1h 07m 14s", self.shown())
        self.assertNotEqual(first, self.shown())
        self.deliver(process(started_at=NOW - 73))
        self.assertIn("  1m 14s  ", self.shown())

    def test_the_session_s_other_processes_are_counted(self) -> None:
        self.deliver(process(proc_id="proc_a", notify=True), process(proc_id="proc_b", command="make lint"))
        self.assertIn("terminal(make lint)  1h 07m 13s  +1 more", self.shown())

    def test_another_session_s_snapshot_is_not_taken(self) -> None:
        self.deliver(process(), session="another")
        self.assertIsNone(self.app._background_line(120))

    def test_an_unreported_end_shows_the_finished_row_and_rings_once(self) -> None:
        self.deliver(process())
        before = bells(self.app)
        self.clock.at += 8
        self.wall.at += 8
        self.deliver()
        self.wall.at += 12
        shown = self.shown()
        self.assertTrue(shown.startswith(
            "✓ background  terminal(uv run python -m unittest tests…)  finished 0:12 ago"), shown)
        self.assertTrue(shown.endswith("  ↵ report result"), shown)
        self.assertEqual(bells(self.app), before + 1)
        self.deliver()
        self.deliver()
        self.assertEqual(bells(self.app), before + 1)  # once, at the transition

    def test_enter_on_an_empty_composer_sends_one_prompt_and_clears_the_row(self) -> None:
        self.deliver(process())
        self.clock.at += 8
        self.deliver()
        self.app._on_input(Key(ENTER))
        self.assertEqual(self.client.named("prompt.submit"), [{"session_id": SID, "text": report_prompt((process(),))}])
        self.assertNotIn("finished", self.shown())
        self.app.turn_pending = False
        self.app._on_input(Key(ENTER))
        self.assertEqual(len(self.client.named("prompt.submit")), 1)  # the offer was taken; nothing more is sent

    def rotate(self, to: str) -> None:
        """Hermes says the session goes on under another stored id, and the poller hands over a switch's snapshot."""
        self.app._on_session_info({"stored_session_id": to})
        self.assertEqual(self.app.stored_id, to)
        switched = HudSnapshot(to, None, 0.0)
        self.app.poller.take = lambda: switched
        self.app._take_hud()

    def test_a_rotation_keeps_the_row_and_its_unreported_end(self) -> None:
        """QA R-E: rotating compaction gave the session a new stored id and the row, and an end it had not reported
        yet, were gone. A read that finds the old id among the conversation's earlier segments keeps both."""
        self.deliver(process(proc_id="proc_a"), process(proc_id="proc_b", command="make lint"))
        self.clock.at += 8
        self.deliver(process(proc_id="proc_b", command="make lint"))  # proc_a ended unreported
        self.assertIn("finished", self.shown())
        self.rotate("20261028_111500_cd34ef")
        self.assertIsNone(self.app._background_line(120))  # nothing decided yet: hidden, not reported
        self.assertFalse(self.app._background_live())
        self.deliver(process(proc_id="proc_b", command="make lint"), session="20261028_111500_cd34ef",
                     earlier=(STORED,))
        self.assertIn("finished", self.shown())
        self.app._on_input(Key(ENTER))
        self.assertEqual(self.client.named("prompt.submit"),
                         [{"session_id": SID, "text": report_prompt((process(proc_id="proc_a"),))}])

    def test_a_switch_to_another_conversation_starts_the_row_over(self) -> None:
        self.deliver(process())
        self.clock.at += 8
        self.deliver()
        self.assertIn("finished", self.shown())
        self.rotate("20261028_111500_cd34ef")
        self.app._on_input(Key(ENTER))  # hidden while undecided: Enter is not the row's
        self.deliver(session="20261028_111500_cd34ef", earlier=("20261028_000000_ffffff",))
        self.assertIsNone(self.app._background_line(120))
        self.app.turn_pending = False
        self.app._on_input(Key(ENTER))
        self.assertEqual(self.client.named("prompt.submit"), [])

    def test_enter_with_text_sends_the_text_and_keeps_nothing_automatic(self) -> None:
        self.deliver(process())
        self.clock.at += 8
        self.deliver()
        self.assertEqual(self.client.named("prompt.submit"), [])  # nothing is ever sent on its own
        type_text(self.app, "what next")
        self.app._on_input(Key(ENTER))
        self.assertEqual(self.client.named("prompt.submit"), [{"session_id": SID, "text": "what next"}])
        self.assertIsNone(self.app._background_line(120))  # a turn started: the offer was for an idle session

    def test_a_process_hermes_reports_just_goes(self) -> None:
        self.deliver(process(notify=True))
        before = bells(self.app)
        self.clock.at += 8
        self.deliver()
        self.assertIsNone(self.app._background_line(120))
        self.assertEqual(bells(self.app), before)

    def test_a_watched_process_just_goes_since_hermes_may_report_its_end(self) -> None:
        # Hermes turns watch patterns into a completion notice in memory once they stop matching, and the checkpoint
        # never says so: the row cannot tell whether the session will be told.
        self.deliver(process(watched=True))
        before = bells(self.app)
        self.clock.at += 8
        self.deliver()
        self.assertIsNone(self.app._background_line(120))
        self.assertEqual(bells(self.app), before)

    def test_a_process_whose_end_cannot_be_asked_never_finishes(self) -> None:
        # A sandbox process's row goes when another interpreter of the profile rewrites the file from its own table,
        # whether or not the process ended: the running row goes, silently.
        self.deliver(process(host=False, pid=None))
        self.assertTrue(self.shown().endswith("  🔕 won't ping you · ask Hermes for the result"), self.shown())
        before = bells(self.app)
        self.clock.at += 8
        self.deliver()  # dropped by a foreign rewrite
        self.assertIsNone(self.app._background_line(120))
        self.assertEqual(bells(self.app), before)

    def test_several_ends_make_one_offer_that_reports_them_all(self) -> None:
        first, second, third = (process(proc_id=f"proc_{name}", command=f"make {name}") for name in "abc")
        self.deliver(first, second, third)
        before = bells(self.app)
        self.clock.at += 8
        self.wall.at += 8
        self.deliver(third)  # two ended in one read
        self.assertIn("terminal(make a)  finished 0:00 ago  +1 more", self.shown())
        self.assertEqual(bells(self.app), before + 1)
        self.wall.at += 5
        self.deliver()  # one more ends before the offer is taken: it joins, and the first end's clock stays
        self.assertIn("terminal(make a)  finished 0:05 ago  +2 more", self.shown())
        self.assertEqual(bells(self.app), before + 2)
        self.app._on_input(Key(ENTER))
        self.assertEqual(self.client.named("prompt.submit"),
                         [{"session_id": SID, "text": report_prompt((first, second, third))}])

    def test_a_whitespace_composer_is_not_empty(self) -> None:
        self.deliver(process())
        self.clock.at += 8
        self.deliver()
        type_text(self.app, "   ")
        self.app._on_input(Key(ENTER))
        self.assertEqual(self.client.named("prompt.submit"), [])
        self.assertIn("finished", self.shown())

    def test_with_one_row_the_queue_keeps_it(self) -> None:
        self.app.turn_pending = True
        self.deliver(process())
        type_text(self.app, "next step")
        self.app._on_input(Key(ENTER))  # queued behind the turn
        self.assertEqual(len(self.app.queued), 1)
        with patch("omh.tui.app.slot_cap", return_value=1):
            (only,) = self.app._slot_lines(120, 30)
        self.assertTrue(line_text(only).startswith("⧗"), line_text(only))
        with patch("omh.tui.app.slot_cap", return_value=2):
            shown = [line_text(line) for line in self.app._slot_lines(120, 30)]
        self.assertTrue(shown[0].startswith("⧗") and shown[1].startswith(f"{GLYPH} background"), shown)

    def test_a_process_that_ends_during_a_turn_or_after_one_started_just_goes(self) -> None:
        self.deliver(process())
        self.clock.at += 1
        self.app.turn_pending = True
        self.app.busy_since = self.clock.at
        self.deliver(process())
        self.clock.at += 1
        self.deliver()
        self.assertIsNone(self.app._background_line(120))

        self.app.turn_pending = False  # the turn ended; the next read is the first since it
        self.deliver(process(proc_id="proc_b"))
        self.app.busy_since = self.clock.at + 1  # a turn came and went between two reads
        self.clock.at += 2
        self.deliver()
        self.assertIsNone(self.app._background_line(120))

    def test_bell_off_rings_nothing(self) -> None:
        app, _client = make_app(cols=120, clock=self.clock, wall_clock=self.wall, environ={"OMH_TUI_BELL": "0"})
        app.stored_id = STORED
        for processes in ((process(),), ()):
            snapshot = HudSnapshot(STORED, {}, 0.0, {}, processes)
            app.poller.take = lambda snapshot=snapshot: snapshot
            self.clock.at += 1
            app._take_hud()
        self.assertIn("finished", text(app._background_line(120)))
        self.assertEqual(bells(app), 0)

    def test_the_spinner_turns_and_reduced_motion_shows_its_first_frame(self) -> None:
        self.deliver(process())
        glyphs = set()
        for step in range(len(WORKING_GLYPHS)):
            self.clock.at, self.wall.at = 100.0 + step * 0.1, NOW + step * 0.09
            glyphs.add(self.shown()[0])
        self.assertEqual(len(glyphs), 1)  # once a second, as the clock beside it: not at the 0.1 s frame rate
        for step in range(len(WORKING_GLYPHS)):
            # On the row's own second, the one its clock and its frames go by: never one ahead of the other.
            self.clock.at, self.wall.at = 100.37 + step, NOW + 0.6 + step
            shown = self.shown()
            self.assertEqual(shown[0], WORKING_GLYPHS[(4033 + step) % len(WORKING_GLYPHS)])
            self.assertIn(f"1h 07m {13 + step:02d}s", shown)
            glyphs.add(shown[0])
        self.assertGreater(len(glyphs), 1)
        still, _client = make_app(cols=120, clock=self.clock, wall_clock=self.wall,
                                  environ={"OMH_TUI_REDUCED_MOTION": "1"})
        still.stored_id = STORED
        snapshot = HudSnapshot(STORED, {}, 0.0, {}, (process(),))
        still.poller.take = lambda: snapshot
        still._take_hud()
        for step in range(len(WORKING_GLYPHS)):
            self.clock.at, self.wall.at = 100.0 + step * 0.37, NOW + step * 0.37
            self.assertEqual(text(still._background_line(120))[0], WORKING_GLYPHS[0])

    def test_the_row_keeps_the_loop_ticking(self) -> None:
        self.assertFalse(self.app._background_live())
        self.deliver(process())
        self.assertTrue(self.app._background_live())
        self.app._render_when_due()
        rendered = self.app.last_render
        self.clock.at += 1.0
        self.wall.at += 1.0
        self.app._render_when_due()
        self.assertGreater(self.app.last_render, rendered)

    def idle_frames(self, seconds: float, step: float = 0.1) -> int:
        """Frames the idle loop draws over `seconds`, both clocks moving `step` at a time, nothing else to do."""
        self.app.dirty = False
        frames = 0
        for _ in range(round(seconds / step)):
            self.clock.at += step
            self.wall.at += step
            before = self.app.last_render
            self.app._render_when_due()
            frames += self.app.last_render != before
        return frames

    def test_the_row_alone_draws_one_frame_a_second_and_none_under_the_pager(self) -> None:
        """QA P4 (2026-10-28): the row kept the loop at the spinners' 10 Hz for the process's whole life (64 frames
        in 10 s idle); its clock and glyph change once a second, so that is all it asks for."""
        self.deliver(process())
        self.app._render_when_due()
        self.wall.at = math.floor(self.wall.at) + 0.05  # just past a second of the row's clock
        self.assertEqual(self.idle_frames(10.0), 10)
        # The loop sleeps until that next second rather than waking at the spinner tick.
        self.assertAlmostEqual(self.app._read_timeout(), 1.0 - (self.wall.at - process().started_at) % 1.0, places=6)
        self.app.bg_done = ((process(),), self.wall.at)
        self.assertEqual(self.idle_frames(5.0), 5)  # `finished 0:12 ago` ticks the same way
        self.app._open_pager("transcript", [(Span("a line"),)])  # the pager covers the row
        self.assertEqual(self.idle_frames(5.0), 0)
        self.assertEqual(self.app._read_timeout(), IDLE_READ_SECONDS)
        self.app._leave_pager()
        for surface in ("slot", "launch_picker", "picker", "search", "rewind_picker", "model_picker"):
            # Review L5: whatever takes the slot hides the row too.
            with self.subTest(surface=surface), patch.object(self.app, surface, object()):
                self.assertIsNone(self.app._background_second())
                self.assertEqual(self.idle_frames(3.0), 0)
        self.assertEqual(self.idle_frames(2.0), 2)
        # Second review 4: a slot the frame has no room for (here a terminal under `MIN_COLS`) draws no row either.
        self.app.size = (MIN_COLS - 1, 24)
        self.app.dirty = True
        self.app._render_when_due()
        self.assertFalse(self.app.bg_row_shown)
        self.assertEqual(self.idle_frames(3.0), 0)
        self.app.size = (120, 40)
        self.app.dirty = True
        self.app._render_when_due()
        self.assertTrue(self.app.bg_row_shown)
        self.app.turn_pending = True  # a turn's spinner still ticks at its own rate
        self.assertGreater(self.idle_frames(1.0), 2)


class WallpaperTickTests(unittest.TestCase):
    """The row's once-a-second frames and the living wallpaper's own tick (#2395) share the idle loop: each keeps its
    deadline, neither starves the other, and the row's frames still stop while it is off screen."""

    def test_the_row_s_frames_and_the_wallpaper_s_ticks_both_keep_their_rate(self) -> None:
        from omh.tui import app as app_module
        from omh.tui.wallpaper import Cell
        from test_tui_wallpaper import ANSWERED, WALLPAPER_ON

        def moving(look, cols, rows, seconds, light):
            return (Cell(rows - 6, int(seconds * 4) % cols, "░", "#445566"),)

        ask_on_any_platform(self)
        clock, wall = Clock(1000.0), Clock(NOW + 0.05)
        with patch.object(app_module, "scene", moving):
            app, _client = make_app(rows=42, cols=150, clock=clock, wall_clock=wall, environ=WALLPAPER_ON)
            app.adopt_background(ANSWERED)
            app.region = app._new_region(at_top=True)
            app.stored_id = STORED
            snapshot = HudSnapshot(STORED, {}, 0.0, {}, (process(),))
            app.poller.take = lambda: snapshot
            app._take_hud()
            app._render_when_due()
            self.assertTrue(app._wallpaper_moves() and app.bg_row_shown)
            tick = app_module.WALLPAPER_TICK_SECONDS
            steps = round(10.0 / tick)
            with patch.object(app, "_render", wraps=app._render) as render, \
                    patch.object(app.region, "paint_ambient", wraps=app.region.paint_ambient) as painted:
                for _ in range(steps):
                    clock.at += tick
                    wall.at += tick
                    self.assertLessEqual(app._read_timeout(), max(tick, 1.0) + 1e-9)
                    app._render_when_due()
            self.assertEqual(render.call_count, 10)  # the row: one frame a second
            self.assertGreaterEqual(painted.call_count, steps - 10 - 1)  # the wallpaper: every other tick
            app.size = (MIN_COLS - 1, 42)  # the row off screen: its frames stop, the wallpaper's ticks go on
            app.dirty = True
            app._render_when_due()
            self.assertFalse(app.bg_row_shown)
            with patch.object(app, "_render", wraps=app._render) as render:
                for _ in range(steps):
                    clock.at += tick
                    wall.at += tick
                    app._render_when_due()
            self.assertEqual(render.call_count, 0)


class StyleTests(unittest.TestCase):
    def setUp(self) -> None:
        ask_on_any_platform(self)
        skin = theme_for_name("amber")
        self.theme = with_catch_colours(build_theme(skin, DARK), skin, DARK, "spectrum")

    def running(self, theme=None, width: int = 120, turn_runs: bool = False, **fields: object):
        return running_line(process(**fields), more=0, now=NOW, glyph=WORKING_GLYPHS[0], turn_runs=turn_runs,
                            theme=theme or self.theme, width=width)

    def test_the_left_side_takes_its_roles(self) -> None:
        line = self.running()
        styles = {span.text: span.style for span in line}
        self.assertEqual(styles[WORKING_GLYPHS[0]], self.theme.background_word)
        self.assertEqual(styles["background"], self.theme.background_word)
        self.assertEqual(styles["terminal"], kind_style("terminal", self.theme))
        self.assertEqual(styles["(uv run python -m unittest tests…)"], self.theme.muted)
        self.assertEqual(styles["  1h 07m 13s"], self.theme.faint)

    def test_omh_is_watching_it_in_the_catch_row_s_colours(self) -> None:
        line = self.running()
        styles = {span.text: span.style for span in line}
        self.assertEqual(styles["🔕 "], self.theme.warn)
        self.assertEqual(styles["Hermes won't be pinged · "], self.theme.warn)
        mark = [span.style for span in line if span.text in ("O", "M", "H")]
        self.assertEqual(mark, list(self.theme.catch_mark[:3]))
        self.assertEqual(styles[" is watching it"], self.theme.catch_words)
        bare = replace(DEFAULT_THEME, catch_mark=())  # a theme with no catch colours: brand and muted, as a catch row
        bare_styles = {span.text: span.style for span in self.running(theme=bare)}
        self.assertEqual([span.style for span in self.running(theme=bare) if span.text in ("O", "M", "H")],
                         [bare.brand] * 3)
        self.assertEqual(bare_styles[" is watching it"], bare.muted)

    def test_where_omh_cannot_ask_it_says_to_ask_hermes_in_the_same_colours(self) -> None:
        line = self.running(host=False, pid=None)
        self.assertTrue(text(line).endswith("  🔕 won't ping you · ask Hermes for the result"), text(line))
        styles = {span.text: span.style for span in line}
        self.assertEqual((styles["🔕 "], styles["won't ping you · "]), (self.theme.warn, self.theme.warn))
        self.assertEqual(styles["ask Hermes for the result"], self.theme.catch_words)
        self.assertNotIn("watching", text(line))
        bare = replace(DEFAULT_THEME, catch_mark=())
        bare_styles = {span.text: span.style for span in self.running(theme=bare, host=False, pid=None)}
        self.assertEqual(bare_styles["ask Hermes for the result"], bare.muted)
        with patch("omh.tui.background.ON_POSIX", False):  # off POSIX no host process can be asked either
            self.assertIn("ask Hermes for the result", text(self.running()))

    def test_will_ping_is_ok(self) -> None:
        styles = {span.text: span.style for span in self.running(notify=True)}
        self.assertEqual(styles["🔔 will ping you when done"], self.theme.ok)

    def test_the_finished_row_is_ok_and_its_key_bold(self) -> None:
        line = finished_line(process(), ago=12, theme=self.theme, width=120)
        styles = {span.text: span.style for span in line}
        self.assertEqual(styles["✓"].fg, self.theme.ok.fg)
        self.assertEqual((styles["background"].fg, styles["background"].bold), (self.theme.ok.fg, True))
        self.assertEqual(styles["  finished 0:12 ago"], self.theme.ok)
        self.assertTrue(styles["↵"].bold)
        self.assertEqual(styles[" report result"], self.theme.hint)

    def test_without_colour_the_text_is_the_same(self) -> None:
        plain = without_colour(self.theme)
        self.assertEqual(text(self.running(theme=plain)), text(self.running()))
        self.assertEqual(text(finished_line(process(), ago=12, theme=plain, width=120)),
                         text(finished_line(process(), ago=12, theme=self.theme, width=120)))
        self.assertTrue(all(span.style.depth == NO_COLOR for span in self.running(theme=plain) if span.style.fg))

    def test_narrow_rows_stay_inside_the_width_and_keep_the_clock_longest(self) -> None:
        for width in (1, 5, 12, 20, 30, 40, 60, 80, 100, 119, 140):
            for line in (self.running(width=width), self.running(width=width, notify=True),
                         self.running(width=width, host=False, pid=None),
                         self.running(width=width, turn_runs=True), finished_line(process(), ago=12, theme=self.theme,
                                                                                   width=width)):
                with self.subTest(width=width, line=text(line)):
                    self.assertLessEqual(line_width(line), width)
        self.assertTrue(text(self.running(width=60)).endswith("1h 07m 13s"), text(self.running(width=60)))
        self.assertIn("terminal(uv run python -m unittest…)  1h 07m 13s  🔕", text(self.running(width=110)))
        self.assertTrue(text(self.running(width=110)).endswith("OMH is watching it"))  # the label gave way first

    def test_the_background_word_is_label_a_little_darker(self) -> None:
        for name in ("sky", "amber", "crimson", "mono"):
            skin = theme_for_name(name)
            for background in (None, DARK, "#000000"):
                theme = build_theme(skin, background)
                surface = surface_for(skin, background)
                with self.subTest(theme=name, background=background):
                    self.assertTrue(theme.background_word.bold)
                    self.assertLess(contrast_ratio(theme.background_word.fg, surface),
                                    contrast_ratio(theme.label.fg, surface))
                    self.assertGreaterEqual(contrast_ratio(theme.background_word.fg, surface), TEXT_CONTRAST)
            light = build_theme(skin, "#FFFFFF")  # on a light one it is held at 4.5:1 rather than faded
            self.assertGreaterEqual(contrast_ratio(light.background_word.fg, "#FFFFFF"), TEXT_CONTRAST)


if __name__ == "__main__":
    unittest.main()
