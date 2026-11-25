"""Read-only Hermes Kanban lanes in the OMH HUD.

The board is native Hermes state (``kanban.db`` at the Hermes root); OMH only
projects it. These cases pin where the reader looks, what it refuses, how a
task's native status becomes a HUD verdict, and how the rows merge beside the
delegate_task rows under the shared row cap.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from _local_package import load_local_package
from _tui_lines import line_text

load_local_package()

from omh.plugin_bundle.omh import kanban_board_reader as reader  # noqa: E402
from omh.plugin_bundle.omh.runtime_reader import (  # noqa: E402
    ACTIVITY_ROW_LIMIT,
    MAX_WIDGET_HUD_BYTES,
    read_omh_hud,
)
from omh.tui.panels import panel_lines  # noqa: E402
from omh.tui.theme import DEFAULT_THEME  # noqa: E402

NOW = 1_800_000_000

# The columns Hermes' ``SCHEMA_SQL`` declares on ``tasks`` that the reader
# selects, plus the ones the native ``kanban_create`` writes beside them.
TASKS_DDL = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT, assignee TEXT,
    status TEXT NOT NULL, priority INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL, started_at INTEGER, completed_at INTEGER,
    workspace_kind TEXT NOT NULL DEFAULT 'scratch', workspace_path TEXT,
    branch_name TEXT, claim_lock TEXT, claim_expires INTEGER, result TEXT,
    idempotency_key TEXT, consecutive_failures INTEGER NOT NULL DEFAULT 0,
    worker_pid INTEGER, last_failure_error TEXT, max_runtime_seconds INTEGER,
    last_heartbeat_at INTEGER, current_run_id INTEGER, skills TEXT,
    model_override TEXT, provider_override TEXT, reasoning_effort TEXT,
    max_retries INTEGER, session_id TEXT
);
CREATE TABLE task_links (
    parent_id TEXT NOT NULL, child_id TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);
"""

# Hermes' ``task_runs`` columns: one attempt at a task, opened on claim and
# closed by ``_end_run``, which is what writes the worker's own ``metadata``
# stamp onto the row.
TASK_RUNS_DDL = """
CREATE TABLE task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, profile TEXT,
    step_key TEXT, status TEXT NOT NULL, claim_lock TEXT, claim_expires INTEGER,
    worker_pid INTEGER, max_runtime_seconds INTEGER, last_heartbeat_at INTEGER,
    started_at INTEGER NOT NULL, ended_at INTEGER, outcome TEXT, summary TEXT,
    metadata TEXT, error TEXT
);
"""

# The columns Hermes declares on ``sessions`` (hermes_state_common.py) that the
# reader selects, plus the two it filters the fallback on.
SESSIONS_DDL = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, model TEXT, model_config TEXT,
    started_at REAL NOT NULL, ended_at REAL, message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0, api_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0, cwd TEXT, title TEXT,
    estimated_cost_usd REAL, actual_cost_usd REAL, cost_status TEXT
);
"""

# An older host whose sessions table predates `title`: the title rule must
# step aside and the window rule must still answer.
SESSIONS_DDL_WITHOUT_TITLE = SESSIONS_DDL.replace(" title TEXT,", "")


def _insert(connection: sqlite3.Connection, table: str, rows) -> None:
    for row in rows:
        columns = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(row.values()))


def build_board(
    db: Path, tasks: list[dict], links: list[tuple[str, str]] = (), runs: list[dict] = ()
) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.executescript(TASKS_DDL)
        if runs:
            connection.executescript(TASK_RUNS_DDL)
        _insert(connection, "tasks", tasks)
        for parent, child in links:
            connection.execute("INSERT INTO task_links VALUES (?, ?)", (parent, child))
        _insert(connection, "task_runs", runs)


def build_state_db(db: Path, sessions: list[dict], *, ddl: str = SESSIONS_DDL) -> None:
    """A profile's ``state.db`` holding the sessions its workers recorded."""
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.executescript(ddl)
        _insert(connection, "sessions", sessions)


def task(identity: str, status: str, **fields) -> dict:
    row = {"id": identity, "title": f"Task {identity}", "assignee": "mbot", "status": status, "created_at": NOW - 600}
    row.update(fields)
    return row


def run(task_id: str, **fields) -> dict:
    row = {"task_id": task_id, "status": "running", "started_at": NOW - 300}
    row.update(fields)
    return row


def worker_session(identity: str, **fields) -> dict:
    """A dispatched worker's own session row, shaped the way Hermes writes it.

    ``source`` is the ``HERMES_SESSION_SOURCE=kanban`` the dispatcher exports,
    ``model_config`` is the ``{max_iterations, reasoning_config}`` the CLI
    records, and ``cwd`` is absent because ``_launch_cwd_for_session`` stamps
    one only when the source is ``cli``.
    """
    row = {
        "id": identity, "source": "kanban", "model": "gpt-5.6-sol",
        "model_config": json.dumps(
            {"max_iterations": 40, "reasoning_config": {"enabled": True, "effort": "medium"}}
        ),
        "started_at": float(NOW - 290), "api_call_count": 9, "tool_call_count": 14,
        "input_tokens": 11_000, "output_tokens": 2_345, "cache_read_tokens": 900,
        "actual_cost_usd": None, "estimated_cost_usd": 0.1234, "cost_status": "estimated",
    }
    row.update(fields)
    return row


class KanbanPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {"HERMES_KANBAN_HOME": "", "HERMES_KANBAN_BOARD": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_default_board_lives_at_the_hermes_root(self) -> None:
        self.assertEqual(reader.kanban_db_path(self.root / ".hermes"), self.root / ".hermes" / "kanban.db")
        self.assertEqual(reader.kanban_db_path(self.root / ".hermes", "default"), self.root / ".hermes" / "kanban.db")

    def test_a_profile_home_resolves_to_its_root(self) -> None:
        # Hermes shares one board across profiles by design: the board is the
        # root's, never <root>/profiles/<name>/kanban.db.
        profile = self.root / ".hermes" / "profiles" / "coder"
        self.assertEqual(reader.kanban_db_path(profile), self.root / ".hermes" / "kanban.db")
        self.assertEqual(reader.hermes_root(self.root / ".hermes"), self.root / ".hermes")

    def test_kanban_home_override_wins(self) -> None:
        with mock.patch.dict(os.environ, {"HERMES_KANBAN_HOME": str(self.root / "shared")}):
            self.assertEqual(reader.kanban_db_path(self.root / ".hermes"), self.root / "shared" / "kanban.db")

    def test_named_board_and_refused_slug(self) -> None:
        self.assertEqual(
            reader.kanban_db_path(self.root / ".hermes", "team-a"),
            self.root / ".hermes" / "kanban" / "boards" / "team-a" / "kanban.db",
        )
        for slug in ("Team", "../escape", "a b", "-lead", "x" * 65):
            with self.subTest(slug=slug):
                self.assertIsNone(reader.kanban_db_path(self.root / ".hermes", slug))

    @unittest.skipIf(sys.platform == "win32", "symlink creation needs privileges on Windows")
    def test_symlinked_db_or_directory_is_refused(self) -> None:
        hermes = self.root / ".hermes"
        hermes.mkdir()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        build_board(elsewhere / "kanban.db", [task("t_00000001", "running")])
        (hermes / "kanban.db").symlink_to(elsewhere / "kanban.db")
        self.assertIsNone(reader.kanban_db_path(hermes))
        self.assertEqual(reader.read_kanban_lanes(hermes, now=NOW)["rows"], [])
        boards = hermes / "kanban" / "boards"
        boards.mkdir(parents=True)
        (boards / "linked").symlink_to(elsewhere)
        self.assertIsNone(reader.kanban_db_path(hermes, "linked"))


class KanbanLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes = self.root / ".hermes"
        self.hermes.mkdir()
        self.db = self.hermes / "kanban.db"
        self.env = mock.patch.dict(os.environ, {"HERMES_KANBAN_HOME": "", "HERMES_KANBAN_BOARD": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def lanes(self, **kwargs):
        return reader.read_kanban_lanes(self.hermes, now=NOW, **kwargs)

    def test_missing_board_is_empty_and_silent(self) -> None:
        result = self.lanes()
        self.assertEqual(result["rows"], [])
        self.assertEqual((result["scope"], result["dispatcher_presence"], result["board"]), ("none", "unknown", "default"))
        self.assertEqual((result["active"], result["running"], result["blocked"], result["completed"], result["queued"]), (0, 0, 0, 0, 0))

    def test_foreign_schema_is_skipped_by_the_column_guard(self) -> None:
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT)")
            connection.execute("INSERT INTO tasks VALUES ('t_1', 'Old shape', 'running')")
        self.assertEqual(self.lanes()["rows"], [])
        # A file that is not a database at all is the same silence.
        self.db.write_bytes(b"not sqlite")
        self.assertEqual(self.lanes()["rows"], [])

    def test_native_status_maps_to_a_hud_verdict(self) -> None:
        build_board(self.db, [
            task("t_run00001", "running", started_at=NOW - 100, worker_pid=41, last_heartbeat_at=NOW - 5,
                 skills='["research", "review"]', model_override="gpt-5.6-sol", provider_override="openai",
                 reasoning_effort="high"),
            task("t_stale001", "running", started_at=NOW - 3000, worker_pid=42, last_heartbeat_at=NOW - 16 * 60),
            task("t_block001", "blocked", started_at=NOW - 500, last_heartbeat_at=NOW - 400),
            task("t_retry001", "todo", last_failure_error="worker crashed"),
            task("t_ready001", "ready"),
            task("t_revw0001", "review", started_at=NOW - 900, completed_at=None),
            task("t_done0001", "done", started_at=NOW - 800, completed_at=NOW - 300),
            task("t_arch0001", "archived", started_at=NOW - 800, completed_at=NOW - 200),
            task("t_old00001", "done", started_at=NOW - 9000, completed_at=NOW - reader.COMPLETED_LINGER_SECONDS - 1),
        ], links=[("t_run00001", "t_ready001"), ("t_done0001", "t_ready001")])
        result = self.lanes(limit=20)
        by_id = {row["task_id"]: row for row in result["rows"]}
        self.assertNotIn("old00001", by_id, "a finished row past the linger window is history")
        self.assertEqual(
            {identity: (row["state"], row["native_status"]) for identity, row in by_id.items()},
            {
                "run00001": ("running", "running"),
                "stale001": ("stale", "running"),
                "block001": ("blocked", "blocked"),
                "retry001": ("queued", "todo"),
                "ready001": ("queued", "ready"),
                "revw0001": ("queued", "review"),
                "done0001": ("done", "done"),
                "arch0001": ("done", "archived"),
            },
        )
        running = by_id["run00001"]
        self.assertEqual(
            (running["role"], running["model"], running["provider"], running["effort"], running["assignee"]),
            ("research", "gpt-5.6-sol", "openai", "high", "mbot"),
        )
        self.assertEqual((running["lane_backend"], running["board"], running["tokens"]), ("kanban", "default", None))
        self.assertEqual(running["elapsed_seconds"], 100.0)
        self.assertEqual(running["model_attestation"]["verdict"], "unknown")
        # A recorded failure on a non-running row is a requeued retry, not a
        # blocker: Hermes sets `ready`/`review` after a crash and clears the
        # error only on a later success.
        self.assertTrue(by_id["retry001"]["retry_pending"])
        self.assertFalse(by_id["ready001"]["retry_pending"])
        self.assertFalse(by_id["block001"]["retry_pending"])
        self.assertEqual(by_id["ready001"]["role"], "worker")
        self.assertEqual(by_id["ready001"]["parent_count"], 2)
        # Never started: no elapsed time at all, not an observed zero. The HUD
        # renders a queued lane's elapsed cell blank either way.
        self.assertIsNone(by_id["ready001"]["elapsed_seconds"])
        # Finished rows freeze at completion; a settled one at its heartbeat.
        self.assertEqual(by_id["done0001"]["elapsed_seconds"], 500.0)
        self.assertTrue(by_id["done0001"]["completed"])
        self.assertEqual(by_id["block001"]["elapsed_seconds"], 100.0)
        self.assertEqual(by_id["stale001"]["elapsed_seconds"], 3000.0 - 16 * 60)
        # Running lanes lead the selection; the rest follow creation order.
        self.assertEqual([row["task_id"] for row in result["rows"]][:2], ["run00001", "stale001"])
        self.assertEqual(
            (result["running"], result["blocked"], result["completed"], result["queued"], result["active"]),
            (2, 1, 2, 3, 3),
        )
        self.assertEqual(result["dispatcher_presence"], "observed")
        self.assertEqual(result["scope"], "global")
        self.assertTrue(all(row["scope"] == "global" for row in result["rows"]))
        # Every key a native delegate row carries is present, so the widget's
        # row layout reads one shape for both lanes.
        native_keys = {
            "scope", "state", "task_id", "role", "action", "alias", "provider", "model", "effort",
            "tokens", "elapsed_seconds", "observed_at", "category", "completed", "delegation_id",
            "model_attestation",
        }
        self.assertTrue(native_keys <= set(running))

    def test_title_is_bounded_and_control_free_id_is_short(self) -> None:
        build_board(self.db, [task("t_abcdef12", "ready", title="x" * 200)])
        row = self.lanes()["rows"][0]
        self.assertEqual(len(row["action"]), reader._ACTION_LIMIT)
        self.assertEqual(row["task_id"], "abcdef12")

    def test_session_rows_are_owned_and_unmatched_identities_fall_back_to_global(self) -> None:
        build_board(self.db, [
            task("t_mine0001", "running", started_at=NOW - 10, session_id="sess-mine"),
            task("t_other001", "running", started_at=NOW - 10, session_id="sess-other"),
            task("t_cli00001", "ready"),
        ])
        owned = self.lanes(session_ids={"sess-mine", "sess-mine-continued"})
        self.assertEqual([row["task_id"] for row in owned["rows"]], ["mine0001"])
        self.assertEqual(owned["scope"], "session")
        self.assertTrue(all(row["scope"] == "session" for row in owned["rows"]))
        self.assertEqual((owned["running"], owned["queued"]), (1, 0))
        fallback = self.lanes(session_ids={"sess-unknown"})
        self.assertEqual(len(fallback["rows"]), 3)
        self.assertEqual(fallback["scope"], "global")
        self.assertTrue(all(row["scope"] == "global" for row in fallback["rows"]))
        unscoped = self.lanes()
        self.assertEqual((len(unscoped["rows"]), unscoped["scope"]), (3, "global"))

    def test_dispatcher_presence_rules(self) -> None:
        build_board(self.db, [task("t_ready001", "ready", created_at=NOW - 30)])
        self.assertEqual(self.lanes()["dispatcher_presence"], "unknown", "a fresh ready task proves nothing yet")
        for case, rows, expected in (
            ("ready past the wait window, nobody claiming", [task("t_ready001", "ready", created_at=NOW - 121)], "not_observed"),
            ("a claim lock on any row", [task("t_ready001", "ready", created_at=NOW - 121), task("t_claim001", "running", claim_lock="lock-1")], "observed"),
            ("a worker pid on any row", [task("t_ready001", "ready", created_at=NOW - 121), task("t_pid00001", "running", worker_pid=9)], "observed"),
            ("only todo rows waiting", [task("t_todo0001", "todo", created_at=NOW - 9000)], "unknown"),
        ):
            with self.subTest(case=case):
                self.db.unlink()
                build_board(self.db, rows)
                self.assertEqual(self.lanes()["dispatcher_presence"], expected)

    def test_row_budget_discloses_hidden_rows(self) -> None:
        build_board(self.db, [task(f"t_{index:08d}", "ready", created_at=NOW - 1000 + index) for index in range(10)])
        result = self.lanes(limit=ACTIVITY_ROW_LIMIT)
        self.assertEqual(len(result["rows"]), ACTIVITY_ROW_LIMIT)
        self.assertEqual(result["hidden"], 2)
        self.assertEqual(result["queued"], 10)
        # The oldest queued rows are the ones next in line, so they stay.
        self.assertEqual(result["rows"][0]["task_id"], "00000000")

    def test_named_board_reads_its_own_db(self) -> None:
        build_board(self.hermes / "kanban" / "boards" / "team-a" / "kanban.db", [task("t_team0001", "running", started_at=NOW - 3)])
        result = self.lanes(board="team-a")
        self.assertEqual([row["board"] for row in result["rows"]], ["team-a"])
        self.assertEqual(result["board"], "team-a")
        self.assertEqual(self.lanes()["rows"], [])

    def test_switched_board_is_the_one_projected(self) -> None:
        # `hermes kanban boards switch team-a` writes <root>/kanban/current;
        # the session's kanban_* tools then act on team-a, so the HUD must
        # project team-a, not the default board's rows.
        build_board(self.db, [task("t_dflt0001", "ready")])
        build_board(self.hermes / "kanban" / "boards" / "team-a" / "kanban.db", [task("t_team0001", "running", started_at=NOW - 3)])
        (self.hermes / "kanban" / "current").write_text("team-a\n", encoding="utf-8")
        self.assertEqual(reader.current_board(self.hermes), "team-a")
        self.assertEqual(reader.kanban_db_path(self.hermes), self.hermes / "kanban" / "boards" / "team-a" / "kanban.db")
        result = self.lanes()
        self.assertEqual([(row["task_id"], row["board"]) for row in result["rows"]], [("team0001", "team-a")])
        self.assertEqual(result["board"], "team-a")
        # An explicit board argument still wins over the switch.
        self.assertEqual([row["task_id"] for row in self.lanes(board="default")["rows"]], ["dflt0001"])

    def test_board_env_wins_over_the_current_file(self) -> None:
        build_board(self.hermes / "kanban" / "boards" / "team-a" / "kanban.db", [task("t_team0001", "ready")])
        build_board(self.hermes / "kanban" / "boards" / "team-b" / "kanban.db", [task("t_teamb001", "ready")])
        (self.hermes / "kanban" / "current").write_text("team-a\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"HERMES_KANBAN_BOARD": "Team-B"}):
            self.assertEqual(reader.current_board(self.hermes), "team-b")
            self.assertEqual([row["task_id"] for row in self.lanes()["rows"]], ["teamb001"])
        # The env names a board that does not exist: fall through to the file.
        with mock.patch.dict(os.environ, {"HERMES_KANBAN_BOARD": "team-c"}):
            self.assertEqual(reader.current_board(self.hermes), "team-a")

    def test_stale_or_malformed_current_file_falls_back_to_default(self) -> None:
        build_board(self.db, [task("t_dflt0001", "ready")])
        marker = self.hermes / "kanban" / "current"
        marker.parent.mkdir(parents=True)
        for content in (b"gone\n", b"../escape\n", b"", b"\xff", b"-lead"):
            with self.subTest(content=content):
                marker.write_bytes(content)
                self.assertEqual(reader.current_board(self.hermes), "default")
                self.assertEqual([row["task_id"] for row in self.lanes()["rows"]], ["dflt0001"])
        # A board directory that exists but holds no board file is not a board.
        (self.hermes / "kanban" / "boards" / "empty").mkdir(parents=True)
        marker.write_text("empty\n", encoding="utf-8")
        self.assertEqual(reader.current_board(self.hermes), "default")

    @unittest.skipIf(sys.platform == "win32", "symlink creation needs privileges on Windows")
    def test_symlinked_current_file_is_treated_as_absent(self) -> None:
        build_board(self.hermes / "kanban" / "boards" / "team-a" / "kanban.db", [task("t_team0001", "ready")])
        elsewhere = self.root / "elsewhere"
        elsewhere.write_text("team-a\n", encoding="utf-8")
        marker = self.hermes / "kanban" / "current"
        marker.symlink_to(elsewhere)
        self.assertEqual(reader.current_board(self.hermes), "default")


class KanbanWorkerUsageTests(unittest.TestCase):
    """The figures a board row borrows from the worker's own Hermes session.

    The board records no usage at all. A dispatched worker runs under the
    assignee profile's home, so its session row in that profile's ``state.db``
    is where the model, turns, tool calls, tokens and cost live. These cases
    pin the two links the reader will accept, and pin that everything else
    leaves the row exactly as the board stated it.
    """

    WORKSPACE = "/tmp/hermes-workspaces/t_run00001"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes = self.root / ".hermes"
        self.hermes.mkdir()
        self.db = self.hermes / "kanban.db"
        self.profile_db = self.hermes / "profiles" / "mbot" / "state.db"
        self.env = mock.patch.dict(os.environ, {"HERMES_KANBAN_HOME": "", "HERMES_KANBAN_BOARD": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def lanes(self, **kwargs):
        return reader.read_kanban_lanes(self.hermes, now=NOW, **kwargs)

    def board(self, *, status: str = "running", runs: list[dict] = (), **fields) -> None:
        row = task(
            "t_run00001", status, started_at=NOW - 300, worker_pid=41,
            last_heartbeat_at=NOW - 5, workspace_path=self.WORKSPACE, **fields,
        )
        build_board(self.db, [row], runs=runs)

    def row(self, **kwargs) -> dict:
        rows = self.lanes(**kwargs)["rows"]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_a_stamped_worker_session_fills_the_lane_row(self) -> None:
        # kanban_complete / kanban_request_review stamp `worker_session_id`
        # onto the run's metadata from the worker's own HERMES_SESSION_ID, and
        # `_end_run` writes it to the row: an exact link, not a guess.
        self.board(
            status="done", completed_at=NOW - 60,
            runs=[run("t_run00001", status="done", outcome="completed", ended_at=NOW - 60,
                      metadata=json.dumps({"worker_session_id": "sess-worker-1", "artifacts": ["a.md"]}))],
        )
        build_state_db(self.profile_db, [worker_session("sess-worker-1")])
        row = self.row()
        self.assertEqual(
            (row["model"], row["effort"], row["tokens"], row["turn_count"], row["tool_count"]),
            ("gpt-5.6-sol", "medium", 13_345, 9, 14),
        )
        self.assertEqual((row["usage_match"], row["usage_session_id"]), ("worker_session_id", "sess-worker-1"))
        self.assertEqual((row["cost_usd"], row["cost_status"]), (0.1234, "estimated"))
        # Tokens are the sum the native delegate rows report, so the two lanes
        # mean one thing in the dock's one token column: input + output, with
        # the cache read the session also recorded left out of it.
        self.assertEqual(row["tokens"], 11_000 + 2_345)
        # Nothing here observes which model answered the worker's calls; the
        # session row records the model it was configured with.
        self.assertEqual(row["model_attestation"]["verdict"], "unknown")

    def test_a_running_worker_is_matched_by_its_dispatch_window(self) -> None:
        # A worker that has not called a kanban tool yet stamped nothing, and
        # Hermes records no cwd on a kanban-source session, so the open run's
        # own window in the assignee's profile is the only link left.
        self.board(runs=[run("t_run00001")])
        build_state_db(self.profile_db, [worker_session("sess-live-1")])
        row = self.row()
        self.assertEqual((row["usage_match"], row["usage_session_id"]), ("dispatch_window", "sess-live-1"))
        self.assertEqual((row["tokens"], row["turn_count"], row["tool_count"]), (13_345, 9, 14))

    def test_the_window_refuses_sessions_that_are_not_this_dispatch(self) -> None:
        self.board(runs=[run("t_run00001")])
        for case, session in (
            ("started before the run was claimed", worker_session("s", started_at=float(NOW - 400))),
            ("started long after the spawn window", worker_session("s", started_at=float(NOW + 90))),
            ("not a dispatched worker", worker_session("s", source="cli")),
            ("another workspace's worker", worker_session("s", cwd="/tmp/hermes-workspaces/t_other")),
        ):
            with self.subTest(case=case):
                self.profile_db.unlink(missing_ok=True)
                build_state_db(self.profile_db, [session])
                row = self.row()
                self.assertIsNone(row["tokens"])
                self.assertNotIn("usage_match", row)
        # A legacy worker row that does carry the task's own workspace is this
        # dispatch: the cwd rule only ever excludes.
        self.profile_db.unlink()
        build_state_db(self.profile_db, [worker_session("sess-legacy", cwd=self.WORKSPACE)])
        self.assertEqual(self.row()["usage_match"], "dispatch_window")

    def test_two_candidate_sessions_leave_the_lane_unlinked(self) -> None:
        # Two workers of the same profile claimed inside one window: nothing
        # on either row says which is this task's, so the lane reports no
        # usage rather than the newer one's figures.
        self.board(runs=[run("t_run00001")])
        build_state_db(self.profile_db, [
            worker_session("sess-a", started_at=float(NOW - 290)),
            worker_session("sess-b", started_at=float(NOW - 280)),
        ])
        row = self.row()
        self.assertIsNone(row["tokens"])
        self.assertNotIn("usage_match", row)
        self.assertNotIn("turn_count", row)
        # The stamp is exact, so it still identifies one of them.
        self.db.unlink()
        self.board(runs=[run("t_run00001", metadata=json.dumps({"worker_session_id": "sess-a"}))])
        self.assertEqual(self.row()["usage_session_id"], "sess-a")

    def test_two_workers_spawned_together_link_by_their_prompt_title(self) -> None:
        # One dispatcher tick spawns two workers of the same profile a second
        # apart: their windows overlap, but Hermes derives each session's
        # title from the dispatcher's own opening prompt, `work kanban task
        # <id>`, so the title is the one recorded field that names the task.
        build_board(self.db, [
            task("t_run00001", "running", started_at=NOW - 300, worker_pid=41, last_heartbeat_at=NOW - 5),
            task("t_run00002", "running", started_at=NOW - 299, worker_pid=42, last_heartbeat_at=NOW - 5),
        ], runs=[run("t_run00001"), run("t_run00002", started_at=NOW - 299)])
        build_state_db(self.profile_db, [
            worker_session("sess-one", title="work kanban task t_run00001", input_tokens=1_000, output_tokens=1),
            worker_session("sess-two", title="work kanban task t_run00002", started_at=float(NOW - 289),
                           input_tokens=2_000, output_tokens=2),
        ])
        rows = {row["task_id"]: row for row in self.lanes()["rows"]}
        self.assertEqual(rows["run00001"]["usage_session_id"], "sess-one")
        self.assertEqual(rows["run00001"]["usage_match"], "worker_prompt_title")
        self.assertEqual(rows["run00001"]["tokens"], 1_001)
        self.assertEqual(rows["run00002"]["usage_session_id"], "sess-two")
        self.assertEqual(rows["run00002"]["tokens"], 2_002)

    def test_the_prompt_title_needs_the_window_and_the_kanban_source(self) -> None:
        # The title alone is not the link: an earlier attempt at the same
        # task keeps its title but sits outside this run's window, and a CLI
        # session an operator titled the same way is not a dispatched worker.
        self.board(runs=[run("t_run00001")])
        for case, session in (
            ("an earlier attempt's session", worker_session("s", title="work kanban task t_run00001",
                                                              started_at=float(NOW - 7_200))),
            ("a cli session with the same title", worker_session("s", title="work kanban task t_run00001",
                                                                   source="cli")),
        ):
            with self.subTest(case=case):
                self.profile_db.unlink(missing_ok=True)
                build_state_db(self.profile_db, [session])
                row = self.row()
                self.assertIsNone(row["tokens"])
                self.assertNotIn("usage_match", row)
        # Two attempts inside one window are both this task; the newest is
        # the live one.
        self.profile_db.unlink()
        build_state_db(self.profile_db, [
            worker_session("sess-old", title="work kanban task t_run00001", started_at=float(NOW - 295)),
            worker_session("sess-new", title="work kanban task t_run00001", started_at=float(NOW - 250)),
        ])
        self.assertEqual(self.row()["usage_session_id"], "sess-new")

    def test_a_retitled_session_falls_back_to_the_window(self) -> None:
        # A host that re-titles the session later loses the title link; one
        # candidate in the window still answers, two do not.
        self.board(runs=[run("t_run00001")])
        build_state_db(self.profile_db, [worker_session("sess-live", title="Widen the create arguments")])
        self.assertEqual(self.row()["usage_match"], "dispatch_window")
        self.profile_db.unlink()
        build_state_db(self.profile_db, [
            worker_session("sess-a", title="Widen the create arguments"),
            worker_session("sess-b", title="Read the board", started_at=float(NOW - 280)),
        ])
        self.assertNotIn("usage_match", self.row())

    def test_a_sessions_table_without_title_still_matches_by_window(self) -> None:
        self.board(runs=[run("t_run00001")])
        build_state_db(self.profile_db, [worker_session("sess-live")], ddl=SESSIONS_DDL_WITHOUT_TITLE)
        self.assertEqual(self.row()["usage_match"], "dispatch_window")

    def test_a_stamp_that_does_not_resolve_answers_with_nothing(self) -> None:
        # The run named its own session and this home does not have it, so
        # this is the wrong home: the window rule would answer with whatever
        # other worker of this profile happens to sit in the run's window.
        self.board(runs=[run("t_run00001", metadata=json.dumps({"worker_session_id": "sess-elsewhere"}))])
        build_state_db(self.profile_db, [worker_session("sess-someone-else")])
        row = self.row()
        self.assertIsNone(row["tokens"])
        self.assertNotIn("usage_match", row)

    def test_a_lane_with_no_worker_session_keeps_the_board_s_own_facts(self) -> None:
        self.board(runs=[run("t_run00001")])
        for case, prepare in (
            ("no profile home at all", lambda: None),
            ("a state.db that is not one", lambda: self.profile_db.write_bytes(b"not sqlite")),
            ("a profile that recorded nothing", lambda: build_state_db(self.profile_db, [])),
            ("a session the stamp names that is gone",
             lambda: build_state_db(self.profile_db, [worker_session("sess-other", source="cli")])),
        ):
            with self.subTest(case=case):
                self.profile_db.parent.mkdir(parents=True, exist_ok=True)
                self.profile_db.unlink(missing_ok=True)
                prepare()
                row = self.row()
                self.assertIsNone(row["tokens"])
                self.assertEqual((row["model"], row["effort"]), ("", ""))
                self.assertNotIn("usage_match", row)
                self.assertNotIn("cost_usd", row)

    def test_a_board_without_task_runs_still_projects_and_still_matches(self) -> None:
        # An older board has no run table; the task's own claim time dates the
        # window, and the stamp lookup simply has nothing to read.
        self.board()
        build_state_db(self.profile_db, [worker_session("sess-live-1")])
        row = self.row()
        self.assertEqual((row["usage_match"], row["tokens"]), ("dispatch_window", 13_345))

    def test_the_task_pin_wins_over_the_session_row(self) -> None:
        self.board(
            model_override="claude-fable-5-1", reasoning_effort="xhigh",
            runs=[run("t_run00001", metadata=json.dumps({"worker_session_id": "sess-worker-1"}))],
        )
        build_state_db(self.profile_db, [worker_session("sess-worker-1")])
        row = self.row()
        # The override is what the dispatcher was told to run; the session only
        # observes what it was configured with.
        self.assertEqual((row["model"], row["effort"]), ("claude-fable-5-1", "xhigh"))
        self.assertEqual(row["tokens"], 13_345)

    def test_the_assignee_profile_decides_which_state_db_is_read(self) -> None:
        root = self.hermes
        (root / "profiles" / "mbot").mkdir(parents=True)
        (root / "state.db").write_bytes(b"")
        (root / "profiles" / "mbot" / "state.db").write_bytes(b"")
        self.assertEqual(reader._worker_state_db(root, "mbot"), root / "profiles" / "mbot" / "state.db")
        # Hermes normalizes the name before it resolves the home.
        self.assertEqual(reader._worker_state_db(root, " Mbot "), root / "profiles" / "mbot" / "state.db")
        # The default profile IS the root, and so is an unnamed assignee.
        for name in ("", "default", "Default"):
            with self.subTest(name=name):
                self.assertEqual(reader._worker_state_db(root, name), root / "state.db")
        # A profile whose home is gone leaves the root's state.db to ask.
        self.assertEqual(reader._worker_state_db(root, "gone"), root / "state.db")
        # Board text that could not name a profile directory never builds one.
        for name in ("../escape", "a b", "-lead", "x" * 65):
            with self.subTest(name=name):
                self.assertIsNone(reader._worker_state_db(root, name))

    @unittest.skipIf(sys.platform == "win32", "symlink creation needs privileges on Windows")
    def test_a_symlinked_state_db_is_refused(self) -> None:
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        build_state_db(elsewhere / "state.db", [worker_session("sess-live-1")])
        self.profile_db.parent.mkdir(parents=True)
        self.profile_db.symlink_to(elsewhere / "state.db")
        self.assertIsNone(reader._worker_state_db(self.hermes, "mbot"))
        self.board(runs=[run("t_run00001")])
        self.assertIsNone(self.row()["tokens"])

    def test_one_connection_per_state_db_serves_every_row(self) -> None:
        build_board(self.db, [
            task(f"t_{index:08d}", "running", assignee="mbot", started_at=NOW - 300,
                 last_heartbeat_at=NOW - 5, workspace_path=self.WORKSPACE)
            for index in range(4)
        ] + [task("t_default01", "running", assignee="default", started_at=NOW - 300, last_heartbeat_at=NOW - 5)])
        build_state_db(self.profile_db, [worker_session("sess-live-1")])
        build_state_db(self.hermes / "state.db", [worker_session("sess-default-1")])
        opened: list[str] = []
        real_connect = sqlite3.connect

        def counting_connect(target, *args, **kwargs):
            opened.append(str(target))
            return real_connect(target, *args, **kwargs)

        with mock.patch("omh.plugin_bundle.omh.kanban_board_reader.sqlite3.connect", counting_connect):
            rows = self.lanes()["rows"]
        self.assertEqual(len(rows), 5)
        # Five rows, two distinct profile homes: the board plus one connection
        # per state.db, never one per row.
        self.assertEqual(len([target for target in opened if "state.db" in target]), 2)


class KanbanHudMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes = self.root / ".hermes"
        self.hermes.mkdir()
        self.omh = self.root / ".omh"
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(self.root), "OMH_HOME": str(self.omh), "HERMES_HOME": str(self.hermes), "HERMES_KANBAN_HOME": "", "HERMES_KANBAN_BOARD": "",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.clock = mock.patch("omh.plugin_bundle.omh.kanban_board_reader.time.time", return_value=float(NOW))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def hud(self, **kwargs):
        return read_omh_hud(self.omh, self.hermes, status={"runs": []}, **kwargs)

    def test_no_board_projects_an_empty_kanban_block(self) -> None:
        payload = self.hud()
        self.assertEqual(payload["kanban"], {
            "board": "default", "dispatcher_presence": "unknown", "rows_total": 0,
            "queued": 0, "running": 0, "blocked": 0, "done": 0,
        })
        self.assertFalse(payload["active"])

    def test_board_rows_merge_beside_native_rows_under_the_shared_cap(self) -> None:
        build_board(self.hermes / "kanban.db", [
            task(f"t_{index:08d}", "ready", created_at=NOW - 1000 + index) for index in range(9)
        ] + [task("t_running1", "running", started_at=NOW - 20, worker_pid=7, last_heartbeat_at=NOW - 1)])
        payload = self.hud()
        agents = payload["subagents"]
        self.assertTrue(payload["active"])
        self.assertEqual(len(agents["rows"]), ACTIVITY_ROW_LIMIT)
        self.assertEqual(agents["rows"][0]["task_id"], "running1")
        self.assertEqual(agents["hidden_rows"], 2)
        self.assertEqual((agents["active"], agents["running"], agents["blocked"], agents["completed"]), (1, 1, 0, 0))
        self.assertEqual(agents["scope"], "global")
        self.assertEqual(agents["status"], "observed")
        self.assertEqual(payload["kanban"], {
            "board": "default", "dispatcher_presence": "observed", "rows_total": 10,
            "queued": 9, "running": 1, "blocked": 0, "done": 0,
        })
        self.assertTrue(all(row["lane_backend"] == "kanban" for row in agents["rows"]))
        self.assertLessEqual(len(json.dumps(payload).encode("utf-8")) + 1, MAX_WIDGET_HUD_BYTES)

    def test_the_tui_renders_the_kanban_identity_and_lane_markers(self) -> None:
        # The OMH TUI's agent rows (`tui/panels.py`), which took this
        # rendering over from the Hermes status widget, over the reader's
        # real payload.
        build_board(self.hermes / "kanban.db", [
            task("t_running1", "running", title="Ship the board lane", started_at=NOW - 280, worker_pid=7,
                 last_heartbeat_at=NOW - 1, model_override="gpt-5.6-sol", reasoning_effort="high"),
            task("t_queued01", "ready", title="Write the release notes", created_at=NOW - 30),
            task("t_stale001", "running", title="Stalled worker", started_at=NOW - 3000, worker_pid=8,
                 last_heartbeat_at=NOW - 20 * 60),
        ])
        # The running lane's worker recorded its own session in the assignee
        # profile's home; the stalled lane was claimed an hour earlier, so no
        # session answers its window and its row keeps the board's facts only.
        build_state_db(self.hermes / "profiles" / "mbot" / "state.db",
                       [worker_session("sess-live-1", started_at=float(NOW - 270))])
        payload = self.hud()
        native = {"scope": "global", "state": "running", "task_id": "a1b2c3d4", "role": "hermes-native",
                  "action": "Review the router change", "model": "claude-fable-5-1", "effort": "xhigh",
                  "tokens": 12345, "turn_count": 4, "tool_count": 6, "elapsed_seconds": 42, "category": "architect"}
        payload["subagents"]["rows"].insert(0, native)
        payload["subagents"]["active"] += 1
        payload["subagents"]["running"] += 1
        idle_payload = {**payload, "kanban": {**payload["kanban"], "rows_total": 0, "dispatcher_presence": "not_observed"}}

        def view(value, cols):
            return [line_text(line) for line in panel_lines(value, cols, 30, DEFAULT_THEME, float(NOW))]

        dock = view(payload, 160)
        idle = "\n".join(view(idle_payload, 160))
        wide = view(payload, 220)
        self.assertIn("3 agents · 3 running · board 1q 2r 0b", dock[0])
        self.assertNotIn("dispatcher not observed", dock[0])
        self.assertNotIn("board 1q", idle)
        self.assertIn("dispatcher not observed", idle)
        lines = [line for line in dock if any(name in line for name in ("Review", "Ship", "Stalled", "Write"))]
        self.assertEqual(len(lines), 4)
        self.assertIn("category:architect(claude-fable-5-1:xhigh)", lines[0])
        running = next(line for line in lines if "Ship the board lane" in line)
        self.assertIn("kanban/mbot(gpt-5.6-sol:high)", running)
        self.assertIn("running · 4m 40s", running)
        self.assertIn("13.3k tokens", running)
        wide_board = next(line for line in wide if "Ship the board lane" in line)
        wide_native = next(line for line in wide if "Review the router change" in line)
        self.assertIn("turn 9 (14 tools)", wide_board)
        self.assertIn("turn 4 (6 tools)", wide_native)
        self.assertIn("$0.1234", wide_board, "the session's recorded cost reads like a native row's")
        stale = next(line for line in lines if "Stalled worker" in line)
        self.assertTrue(stale.startswith("! "), stale)
        self.assertIn("kanban/mbot", stale)
        self.assertNotIn("kanban/mbot(", stale, "no model pin, no parenthesis")
        self.assertIn("running ·", stale, "the tail keeps the native status word")
        self.assertNotIn("tokens", stale, "an unlinked lane shows blank cells, never a borrowed figure")
        queued = next(line for line in lines if "Write the release notes" in line)
        self.assertTrue(queued.startswith("· "), queued)
        self.assertIn("ready   ·", queued)
        # Kind tags: a board row is `[bot]`, a delegate child `[sub]`; no
        # scope word on a row.
        self.assertIn("[bot] ", running)
        self.assertIn("[sub] ", lines[0])
        self.assertNotIn("[global]", running)


if __name__ == "__main__":
    unittest.main()
