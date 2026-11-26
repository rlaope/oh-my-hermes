"""Every SQLite URI open in `src/` quotes its path, and every reader of a Hermes store reads its own file.

`sqlite3.connect(f"file:{path}?mode=ro", uri=True)` hands the path to SQLite's URI parser as it is. A home whose path
holds `#` or `?` cuts the path there: the open loses `mode=ro` and creates a writable file at the cut. A `%41` decodes
to `A` and opens another directory's file. The policy gate re-derives from source every `sqlite3.connect(...)` spelled
that way with a `uri=` keyword; the reader cases put each reader family's real store under such a home and require its
rows back and no new file.
"""

from __future__ import annotations

import ast
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import Any, Callable
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.sqlite_readonly import connect_readonly  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
# Windows allows no `?` in a file name.
ODD_NAMES = ("a#b", "50%41") if os.name == "nt" else ("a#b", "a?b", "50%41")
# A POSIX file name that is not valid UTF-8. A Linux file system takes it; APFS and Windows refuse it.
NON_UTF8_NAME = b"lat\xe9"


# ── the policy ───────────────────────────────────────────────────────────


def _quoted_part(node: ast.expr) -> bool:
    """A literal, or a `quote(...)` / `....as_uri()` call: a piece that cannot carry a raw `#`, `?` or `%`."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if not isinstance(node, ast.Call):
        return False
    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
    return name in {"quote", "as_uri"}


def quoted_uri(node: ast.expr) -> bool:
    """Whether a URI expression builds its path only from quoted pieces."""
    if isinstance(node, ast.JoinedStr):
        return all(
            isinstance(part, ast.Constant) or (isinstance(part, ast.FormattedValue) and _quoted_part(part.value))
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return quoted_uri(node.left) and quoted_uri(node.right)
    return _quoted_part(node)


def _uri_opens(source: str) -> list[tuple[int, ast.expr | None]]:
    """Each `sqlite3.connect(...)` that enables URI parsing, with the expression it opens."""
    opens: list[tuple[int, ast.expr | None]] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "sqlite3"
        ):
            continue
        uri = next((keyword.value for keyword in node.keywords if keyword.arg == "uri"), None)
        if uri is None or (isinstance(uri, ast.Constant) and not uri.value):
            continue
        database = node.args[0] if node.args else next(
            (keyword.value for keyword in node.keywords if keyword.arg == "database"), None
        )
        opens.append((node.lineno, database))
    return opens


class QuotedUriPolicyTests(unittest.TestCase):
    def test_every_uri_open_in_src_quotes_its_path(self) -> None:
        sites: list[str] = []
        unquoted: list[str] = []
        for path in sorted(SOURCE_ROOT.rglob("*.py")):
            for line, database in _uri_opens(path.read_text(encoding="utf-8")):
                site = f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"
                sites.append(site)
                if database is None or not quoted_uri(database):
                    unquoted.append(site)
        # Not vacuous: the helper's own open is one of them.
        self.assertIn("src/plugin_bundle/omh/sqlite_readonly.py", {site.rsplit(":", 1)[0] for site in sites})
        self.assertEqual(
            unquoted,
            [],
            "a `uri=True` open builds its URI from an unquoted path; open it with "
            "`sqlite_readonly.connect_readonly`, or quote the path (`quote(str(path))`, `Path.as_uri()`)",
        )

    def test_the_scan_tells_a_quoted_path_from_a_raw_one(self) -> None:
        raw = [
            'sqlite3.connect(f"file:{path}?mode=ro", uri=True)',
            'sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)',
            'sqlite3.connect(database=f"file:{quote(str(a))}/{b}?mode=ro", uri=True)',
            'sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)',
            "sqlite3.connect(uri_text, uri=True)",
        ]
        quoted = [
            'sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True)',
            'sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)',
            'sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)',
            'sqlite3.connect("file::memory:", uri=True)',
        ]
        for source in raw:
            with self.subTest(source=source):
                [(_, database)] = _uri_opens(source)
                self.assertFalse(quoted_uri(database))
        for source in quoted:
            with self.subTest(source=source):
                [(_, database)] = _uri_opens(source)
                self.assertTrue(quoted_uri(database))
        # A plain path open does not parse a URI, so it is not a site.
        self.assertEqual(_uri_opens('sqlite3.connect(f"{path}")\nsqlite3.connect(path, uri=False)'), [])


# ── the helper ───────────────────────────────────────────────────────────


def _tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _store(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO sessions VALUES (?)", (marker,))


def _non_utf8_home(test: unittest.TestCase, root: Path) -> Path:
    """`root/NON_UTF8_NAME`, made, or the test skipped where the platform or file system refuses the name.

    Call it at the top of a test, never inside a `subTest`: a skip there records the subtest, and the test itself
    then records no outcome.
    """
    try:
        home = root / os.fsdecode(NON_UTF8_NAME)
        home.mkdir()
    except (OSError, ValueError):
        test.skipTest(f"this file system refuses the name {NON_UTF8_NAME!r}")
    return home


class ConnectReadonlyTests(unittest.TestCase):
    def reads_its_own_file(self, root: Path, home: Path) -> None:
        db = home / "state.db"
        _store(db, "real")
        # Where an unquoted `%41` lands.
        _store(root / "50A" / "state.db", "decoy")
        before = _tree(root)
        with closing(connect_readonly(db, timeout=0.25)) as connection:
            rows = connection.execute("SELECT id FROM sessions").fetchall()
            # The path comes back as its file-system bytes, which need not be UTF-8.
            connection.text_factory = os.fsdecode
            opened = connection.execute("PRAGMA database_list").fetchall()[0][2]
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE written (x)")
        self.assertEqual(rows, [("real",)])
        # A resolved comparison: a temp root can be an 8.3 short name on Windows.
        self.assertTrue(os.path.samefile(opened, db), (opened, str(db)))
        self.assertEqual(_tree(root), before)

    def creates_no_missing_file(self, root: Path, home: Path) -> None:
        with self.assertRaises(sqlite3.OperationalError):
            connect_readonly(home / "state.db", timeout=0.25)
        self.assertEqual(_tree(root), [home.name])

    def test_an_odd_or_ordinary_home_opens_its_own_file_read_only_and_creates_nothing(self) -> None:
        for name in (*ODD_NAMES, "plain"):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                (Path(tmp) / name).mkdir()
                self.reads_its_own_file(Path(tmp), Path(tmp) / name)

    def test_a_home_whose_name_is_not_utf8_opens_its_own_file_read_only_and_creates_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            self.reads_its_own_file(Path(tmp), _non_utf8_home(self, Path(tmp)))

    def test_a_missing_file_is_an_error_and_is_not_created(self) -> None:
        for name in (*ODD_NAMES, "plain"):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                (Path(tmp) / name).mkdir()
                self.creates_no_missing_file(Path(tmp), Path(tmp) / name)

    def test_a_missing_file_under_a_home_whose_name_is_not_utf8_is_not_created(self) -> None:
        with TemporaryDirectory() as tmp:
            self.creates_no_missing_file(Path(tmp), _non_utf8_home(self, Path(tmp)))

    @unittest.skipIf(os.name == "nt", "Windows has no file name that is not valid UTF-8 as bytes")
    def test_a_path_that_is_not_valid_utf8_fails_as_sqlite_does_on_every_file_system(self) -> None:
        # `quote` of the `str` raised UnicodeEncodeError here, which the readers' `except sqlite3.Error` let through.
        # The directory is never made, so APFS runs this too: the open reaches SQLite and fails there.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / os.fsdecode(NON_UTF8_NAME) / "state.db"
            with self.assertRaises(sqlite3.OperationalError):
                connect_readonly(path, timeout=0.25)
            self.assertEqual(_tree(Path(tmp)), [])


# ── each reader family ───────────────────────────────────────────────────


class ReaderFamilyTests(unittest.TestCase):
    """Each reader of a Hermes store, with that store under an odd home: its own rows back, no file made."""

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {"HERMES_KANBAN_HOME": "", "HERMES_KANBAN_BOARD": ""})
        env.start()
        self.addCleanup(env.stop)

    def each_home(self, build: Callable[[Path], None], read: Callable[[Path], Any], expected: Any) -> None:
        """`read(home)` equals `expected` for a home named each of `ODD_NAMES`, after `build(home)`, and makes no file."""
        for name in ODD_NAMES:
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                root = Path(tmp)
                home = root / name
                home.mkdir()
                build(home)
                before = _tree(root)
                self.assertEqual(read(home), expected)
                self.assertEqual(_tree(root), before, f"reading under {name!r} created a file")

    def test_a_home_whose_name_is_not_utf8(self) -> None:
        # The readers that let `quote`'s UnicodeEncodeError through. Run where the file system takes the name (Linux).
        from omh.plugin_bundle.omh import delegation_ledger, kanban_board_reader
        from omh.plugin_bundle.omh.tools import dag_tool

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = _non_utf8_home(self, root)
            with closing(sqlite3.connect(home / "state.db")) as connection, connection:
                connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, model_config TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('child', ?)", (json.dumps({"_delegate_from": "parent"}),))
                connection.execute("INSERT INTO sessions VALUES ('parent', '{}')")
                connection.execute("CREATE TABLE async_delegations (delegation_id TEXT, state TEXT, owner_pid INTEGER)")
                connection.execute("INSERT INTO async_delegations VALUES ('call-1-0', 'running', 4242)")
            before = _tree(root)
            delegation_ledger._roots.clear()
            try:
                self.assertEqual(delegation_ledger.root_session("child", home), "parent")
            finally:
                delegation_ledger._roots.clear()
            self.assertEqual(kanban_board_reader.conversation_session_ids(home, "parent"), {"parent"})
            slots = dag_tool.free_slots(home, pid=4242)
            self.assertEqual((slots["basis"], slots["running_calls"]), ("state_db", 1))
            self.assertEqual(_tree(root), before)

    def test_resume_door(self) -> None:
        from omh.maintenance.hermes_resume import resumable_session_id
        from test_omh_resume_door import CHILD_ENDED_AT, CHILD_STARTED_AT, write_sessions

        def build(home: Path) -> None:
            write_sessions(home / "state.db", [("sess-alpha", "tui", CHILD_STARTED_AT + 1, CHILD_ENDED_AT - 0.2, 12)])

        self.each_home(
            build, lambda home: resumable_session_id(home / "state.db", CHILD_STARTED_AT, CHILD_ENDED_AT), "sess-alpha"
        )

    def test_cost_receipt_sessions_and_boards(self) -> None:
        from omh.plugin_bundle.omh.cost_receipt import build_cost_receipt
        from test_cost_receipt import CONTINUED, _build_kanban, _build_state_db

        def build(home: Path) -> None:
            _build_state_db(home / "hermes")
            _build_kanban(home / "hermes")

        def read(home: Path) -> tuple:
            receipt = build_cost_receipt(hermes_home=home / "hermes", omh_home=home / "omh", session_id=CONTINUED)
            return receipt["sources"]["session"]["count"], receipt["sources"]["kanban_workers"]["count"], receipt["kanban"]

        # The counts `test_cost_receipt` pins for this fixture under an ordinary home.
        self.each_home(build, read, (2, 7, {"boards_read": ["default", "ops"], "boards_unreadable": []}))

    def test_delegation_ledger_root_walk(self) -> None:
        from omh.plugin_bundle.omh import delegation_ledger

        def build(home: Path) -> None:
            with closing(sqlite3.connect(home / "state.db")) as connection, connection:
                connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, model_config TEXT)")
                connection.execute("INSERT INTO sessions VALUES ('child', ?)", (json.dumps({"_delegate_from": "parent"}),))
                connection.execute("INSERT INTO sessions VALUES ('parent', '{}')")

        def read(home: Path) -> str:
            delegation_ledger._roots.clear()
            try:
                return delegation_ledger.root_session("child", home)
            finally:
                delegation_ledger._roots.clear()

        self.each_home(build, read, "parent")

    def test_native_delegate_reader(self) -> None:
        from omh.plugin_bundle.omh.hermes_delegation import read_hermes_native_subagents
        from test_plugin_hermes_delegation import NOW, _build_state_db

        def build(home: Path) -> None:
            _build_state_db(home, [{"id": "20260818_100100_opened", "model": "deepseek/deepseek-flash", "started_at": NOW - 30}])

        def read(home: Path) -> tuple:
            payload = read_hermes_native_subagents(home, now=NOW, omh_home=home / ".omh")
            return payload.get("read_status"), [row["task_id"] for row in payload["rows"]]

        self.each_home(build, read, ("read", ["opened"]))

    def test_kanban_board_reader(self) -> None:
        from omh.plugin_bundle.omh import kanban_board_reader
        from test_kanban_board_reader import NOW, build_board, build_state_db, run, task, worker_session

        def build(home: Path) -> None:
            build_board(
                home / "kanban.db",
                [task("t_run00001", "done", started_at=NOW - 300, completed_at=NOW - 60)],
                runs=[run("t_run00001", status="done", outcome="completed", ended_at=NOW - 60,
                          metadata=json.dumps({"worker_session_id": "sess-worker-1"}))],
            )
            build_state_db(home / "profiles" / "mbot" / "state.db", [worker_session("sess-worker-1")])
            build_state_db(home / "state.db", [{"id": "sess-parent", "source": "tui", "started_at": float(NOW)}])

        def read(home: Path) -> tuple:
            [row] = kanban_board_reader.read_kanban_lanes(home, now=NOW)["rows"]
            return (
                kanban_board_reader.conversation_session_ids(home, "sess-parent"),
                row["usage_session_id"],
                row["tokens"],
            )

        # The board (`_query_tasks`), the worker's profile store (`_state_db_connection`) and the conversation's own.
        self.each_home(build, read, ({"sess-parent"}, "sess-worker-1", 11_000 + 2_345))

    def test_dag_free_slots(self) -> None:
        from omh.plugin_bundle.omh.tools import dag_tool

        def build(home: Path) -> None:
            with closing(sqlite3.connect(home / "state.db")) as connection, connection:
                connection.execute("CREATE TABLE async_delegations (delegation_id TEXT, state TEXT, owner_pid INTEGER)")
                connection.execute("INSERT INTO async_delegations VALUES ('call-1-0', 'running', 4242)")

        def read(home: Path) -> tuple:
            slots = dag_tool.free_slots(home, pid=4242)
            return slots["basis"], slots["running_calls"]

        self.each_home(build, read, ("state_db", 1))

    def test_run_summary(self) -> None:
        from omh.plugin_bundle.omh.tools.run_summary_tool import omh_run_summary_handler
        from test_run_summary_tool import _build_state_db

        def build(home: Path) -> None:
            _build_state_db(home, [{"id": "20260819_100000_main01", "started_at": 1_000_000.0, "ended_at": 1_000_060.0,
                                    "input_tokens": 400, "output_tokens": 70}])

        def read(home: Path) -> tuple:
            result = json.loads(omh_run_summary_handler({"hermes_home": str(home)}, session_id="20260819_100000_main01"))
            return result["status"], result["tokens_used"]

        self.each_home(build, read, ("observed", 470))


if __name__ == "__main__":
    unittest.main()
