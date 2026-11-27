"""The foreground /sessions inventory uses only synthetic Hermes profile stores."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _tui_lines import line_text
from test_tui_modes import make_app, type_text
from test_tui_resume_feedback import reply

from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, TAB, Key
from omh.tui.profile_sessions import Inventory
from omh.tui.session_picker import DELETE, PickerAction, SessionPicker, SessionRow, session_rows
from omh.tui.theme import DEFAULT_THEME
from omh.tui.width import line_width


def create_store(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, created_source TEXT, chat_id TEXT, title TEXT,
            started_at REAL, last_activity_at REAL, message_count INT, hidden INT, archived INT,
            parent_session_id TEXT, end_reason TEXT, ended_at REAL, model_config TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL);
        CREATE INDEX idx_messages_session ON messages (session_id, timestamp);
        CREATE INDEX idx_sessions_parent ON sessions (parent_session_id);
        CREATE TABLE state_meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    return db


def insert(db: sqlite3.Connection, sid: str, title: str, *, source: str = "local", activity: int = 200,
           hidden: bool = False, archived: bool = False, empty: bool = False, parent: str | None = None,
           ended: str | None = None, config: str | None = None, created: str | None = "desktop") -> None:
    db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (sid, source, created, sid, title, 100, activity, int(not empty), hidden, archived, parent, ended,
                activity if ended else None, config))
    if not empty:
        db.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, 'user', ?, ?)",
                   (sid, f"{title} fixture message", activity))
    db.commit()


class ProfileSessionsTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = self.enterContext(TemporaryDirectory(dir=Path.cwd(), prefix=".test-profile-sessions-"))
        self.root = Path(temp) / ".hermes"
        self.default = self.root / "state.db"
        self.named = self.root / "profiles" / "night" / "state.db"
        self.env = {"HERMES_HOME": str(self.named.parent)}

    def open_picker(self, *, profile: str = "night"):
        app, client = make_app(environ=self.env)
        app.launch_profile = profile
        type_text(app, "/sessions")
        app._on_input(Key(ENTER))
        self.assertEqual([method for method, _ in client.calls], ["session.list"])
        self.assertIsNotNone(app.profile_read)
        return app, client

    def take_inventory(self, app) -> None:
        app.profile_read[1].result(5)
        app._take_profile_sessions()

    def test_all_profiles_scope_navigation_paging_and_read_only_history(self) -> None:
        with closing(create_store(self.default)) as db:
            insert(db, "local-duplicate", "Needle default", activity=400)
        with closing(create_store(self.named)) as db:
            insert(db, "local-duplicate", "Needle night", activity=300)
            insert(db, "local-ungranted", "Needle ungranted open session", activity=250)
        app, client = self.open_picker()
        reply(app, client, {"sessions": [{"id": "local-duplicate", "title": "Needle gateway"}], "next_page": "older"})
        self.take_inventory(app)
        picker = app.picker
        self.assertEqual([(row.profile, row.label, row.read_only) for row in picker.visible()], [
            ("default", "Needle default", True), ("night", "Needle gateway", False),
            ("night", "Needle ungranted open session", True),
        ])
        for width, height in ((80, 24), (120, 40), (32, 8)):
            lines = picker.lines(width, DEFAULT_THEME, min(height, 10), 450)
            self.assertTrue(all(line_width(line) <= width for line in lines))
            self.assertIn("All local profiles", line_text(lines[0]))
            if width >= 80:
                self.assertNotIn("Profile", line_text(lines[1]))  # each bot is a block under its own heading
                self.assertIn("Last active", line_text(lines[1]))
                self.assertIn("Enter switches", picker.keys()[0])  # local scan did not steal the highlight

        type_text(app, "needle")
        app._take_input(b"\t")
        self.assertEqual((picker.scoped_profile, picker.query), ("default", "needle"))
        self.assertIn("Enter opens read-only history", picker.keys()[0])
        headers = picker.lines(80, DEFAULT_THEME, 10, 450)
        self.assertIn("Sessions · default", line_text(headers[0]))
        self.assertNotIn("Profile", line_text(headers[1]))
        app._take_input(b"\x1b[Z")
        self.assertEqual((picker.scoped_profile, picker.query), ("", "needle"))
        app._take_input(b"\x1b[Z")
        self.assertEqual((picker.scoped_profile, picker.query), ("night", "needle"))
        self.assertIn("Enter switches", picker.keys()[0])

        app._on_input(Key(CHAR, "g", ctrl=True))
        self.assertEqual(client.calls[-1], ("session.list", {"page": "older"}))
        reply(app, client, {"sessions": [{"id": "older-grant", "title": "Needle old", "started_at": 1}]})
        self.assertEqual(picker.selected().id, "local-duplicate")
        self.assertEqual(picker.query, "needle")
        app._take_input(b"\x1b[B")
        self.assertEqual(picker.selected().label, "Needle ungranted open session")
        for char in "rdd":
            app._on_input(Key(CHAR, char, ctrl=True))
        app._on_input(Key(ENTER))
        self.assertIsNotNone(app.profile_history)
        app.profile_history[2].result(5)
        app._take_profile_sessions()
        self.assertEqual([method for method, _ in client.calls], ["session.list", "session.list"])
        self.assertEqual(app.sid, "live-1")
        self.assertIn("Needle ungranted open session fixture message", "\n".join(map(line_text, app.pager.lines)))

    def test_large_table_reuses_search_until_scope_or_rows_change(self) -> None:
        rows = [SessionRow(f"session-{n}", "Routing notes", "", n, 1, profile="night" if n % 2 else "default")
                for n in range(10_000)]
        picker = SessionPicker(rows, current="", profiles=("default", "night"), query="rtn")
        self.assertEqual(len(picker.visible()), 10_000)  # non-contiguous match
        with patch("omh.tui.session_picker._matches", side_effect=AssertionError("repeated filter")):
            picker.handle_key(Key(DOWN))
            picker.lines(80, DEFAULT_THEME, 20, 12_000)
            self.assertIn("Enter switches", picker.keys()[0])
        picker.handle_key(Key(TAB))
        self.assertEqual((len(picker.visible()), picker.query), (5000, "rtn"))
        picker.renamed("session-0", "Unrelated")
        self.assertEqual(len(picker.visible()), 4999)
        picker.deleted("session-2")
        self.assertEqual(len(picker.visible()), 4998)
        picker.add_older([SessionRow("older", "Routing notes", "", 0, 1, profile="default")], "")
        self.assertEqual(len(picker.visible()), 4999)

    def test_failed_background_inventory_keeps_gateway_results(self) -> None:
        with patch.object(Inventory, "read", side_effect=RuntimeError("synthetic worker failure")):
            app, client = self.open_picker()
            with self.assertRaises(RuntimeError):
                app.profile_read[1].result(5)
        app._take_profile_sessions()
        reply(app, client, {"sessions": [{"id": "granted", "title": "Gateway result"}]})
        self.assertIsNone(app.profile_read)
        self.assertTrue(app.picker.partial)
        self.assertEqual([row.label for row in app.picker.visible()], ["Gateway result"])

    def test_filters_noise_hidden_archived_and_empty_and_revalidates_handle(self) -> None:
        with closing(create_store(self.default)) as db:
            insert(db, "local-real", "Real")
            insert(db, "local-cron", "Noise", source="cron")
            insert(db, "local-delegate", "Delegate", config='{"_delegate_from":"local-real"}')
            insert(db, "local-empty", "Empty", empty=True)
            insert(db, "local-hidden", "Hidden", hidden=True)
            insert(db, "local-archived", "Archived", archived=True)
            db.execute("UPDATE sessions SET message_count=9 WHERE id='local-empty'")
            db.commit()
        self.named.parent.mkdir(parents=True)
        self.named.write_text("unreadable synthetic database", encoding="utf-8")
        (self.named.parent / "gateway.parked").touch()
        tombstone = self.root / "profiles" / ".deleted" / "gone"
        tombstone.parent.mkdir()
        tombstone.touch()
        ghost = self.root / "profiles" / "gone"
        ghost.mkdir()
        (ghost / "config.yaml").touch()
        app, client = self.open_picker(profile="")  # HERMES_HOME is named, but the owner did not identify itself
        self.take_inventory(app)
        reply(app, client, {"sessions": [{"id": "local-real", "title": "Unknown gateway"}]})
        self.assertEqual([(row.profile, row.label) for row in app.picker.visible()], [
            ("default", "Real"), ("", "Unknown gateway"),
        ])
        self.assertEqual(app.picker.profiles, ("default", "night"))
        self.assertIn("night: session store unavailable", app.picker.inventory_status)
        self.assertIn("Partial", line_text(app.picker.lines(32, DEFAULT_THEME, 3, 450)[0]))
        self.assertIn("Partial", app.picker.keys()[-1])
        inventory = app.profile_inventory
        self.assertIn("problem", inventory.transcript(self.env, "local-real"))
        with closing(sqlite3.connect(self.default)) as db:
            db.execute("UPDATE sessions SET hidden=1 WHERE id='local-real'")
            db.commit()
        self.assertIn("no longer available", inventory.transcript(self.env, inventory.rows[0].local)["problem"])

    def test_unknown_source_is_not_background_noise(self) -> None:
        with closing(create_store(self.default)) as db:
            insert(db, "local-unknown", "Unknown source", created=None)
            db.execute("UPDATE sessions SET source=NULL WHERE id='local-unknown'")
            db.commit()
        inventory = Inventory.read(self.env)
        self.assertEqual(inventory.problems, [])
        self.assertEqual([(row.label, row.source) for row in inventory.rows], [("Unknown source", "")])
        self.assertIn("rows", inventory.transcript(self.env, inventory.rows[0].local))

    def test_gateway_running_hint_does_not_claim_another_viewer(self) -> None:
        app, client = self.open_picker()
        reply(app, client, {"sessions": [
            {"id": "busy-turn", "title": "Working", "running": True},
            {"id": "idle-turn", "title": "Idle", "running": False},
        ]})
        self.assertTrue(app.picker.rows[0].running)
        self.assertFalse(app.picker.rows[1].running)
        drawn = app.picker.lines(100, DEFAULT_THEME, 12, 450)
        busy = next(line for line in drawn if "Working" in line_text(line))
        self.assertEqual(line_text(busy).split()[-1], "running")  # in Last active, not glued to the title
        self.assertEqual(next(span.style for span in busy if span.text.strip() == "running"), DEFAULT_THEME.running)
        self.assertIn("Turn running", app.picker.keys()[0])
        app.picker.handle_key(Key(DOWN))
        self.assertNotIn("Turn running", app.picker.keys()[0])
        self.assertNotIn("turn running", "\n".join(map(line_text, app.picker.lines(100, DEFAULT_THEME, 12, 450))))
        self.assertTrue(app.picker.rows[0].resumable)  # a running turn is not a second-viewer authorization verdict

    def test_running_status_survives_an_older_gateway_lineage_page(self) -> None:
        picker = SessionPicker([], current="", profiles=("night",))
        picker.add_older(session_rows({"sessions": [{"id": "root", "running": True}]}, profile="night"), "token")
        picker.add_older(session_rows({"sessions": [{"id": "tip", "resolved_id": "root", "running": False}]},
                                      profile="night"), "")
        self.assertEqual(len(picker.rows), 1)
        self.assertTrue(picker.rows[0].running)
        self.assertIn("Turn running", picker.keys()[0])

    def test_busy_hint_does_not_change_read_only_local_history(self) -> None:
        handle = object()
        row = SessionRow("", "Other client", "", 100, 1, profile="night", local=handle)
        picker = SessionPicker([row], current="", profiles=("night",))
        self.assertTrue(picker.selected().read_only)
        self.assertNotIn("Turn running", picker.keys()[0])
        self.assertIn("Enter opens read-only history", picker.keys()[0])

    def test_latest_message_wins_over_a_stale_activity_heartbeat(self) -> None:
        with closing(create_store(self.default)) as db:
            insert(db, "old-heartbeat", "Most recent message", activity=200)
            insert(db, "new-heartbeat", "Newer heartbeat", activity=300)
            db.execute("UPDATE messages SET timestamp=400 WHERE session_id='old-heartbeat'")
            db.commit()
        self.assertEqual([(row.label, row.activity_at) for row in Inventory.read(self.env).rows], [
            ("Most recent message", 400), ("Newer heartbeat", 300),
        ])

    def test_idle_wal_untouched_and_live_wal_commits_visible(self) -> None:
        with closing(create_store(self.default)) as db:
            insert(db, "root", "Root", ended="compression")
            insert(db, "tip", "Tip", parent="root", activity=300)
            insert(db, "branch", "Branch", parent="root", config='{"_branched_from":"root"}', activity=400)
        before = self.default.read_bytes()
        idle = Inventory.read(self.env)
        self.assertEqual([row.label for row in idle.rows], ["Branch", "Tip"])
        self.assertEqual(idle.rows[1].lineage, frozenset({"tip", "root"}))
        self.assertIn("rows", idle.transcript(self.env, idle.rows[1].local))
        self.assertEqual(list(self.root.glob("state.db*")), [self.default])
        self.assertEqual(self.default.read_bytes(), before)
        with closing(sqlite3.connect(self.default)) as writer:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            insert(writer, "local-wal", "In WAL", activity=500)
            wal = self.default.with_name("state.db-wal")
            wal_bytes = wal.read_bytes()
            self.assertEqual(self.default.read_bytes(), before)
            live = Inventory.read(self.env)
            self.assertEqual(live.rows[0].label, "In WAL")
            self.assertEqual(live.transcript(self.env, live.rows[0].local)["rows"][0]["text"], "In WAL fixture message")
            self.assertEqual(wal.read_bytes(), wal_bytes)
            self.assertEqual(self.default.read_bytes(), before)

    def test_late_gateway_page_and_local_transcript_do_not_take_over_a_closed_picker(self) -> None:
        with closing(create_store(self.named)) as db:
            insert(db, "local-open", "Locally open")
        app, client = self.open_picker()
        self.take_inventory(app)
        reply(app, client, {"sessions": [], "next_page": "older"})
        app._on_input(Key(ENTER))
        app._on_input(Key(CHAR, "g", ctrl=True))
        app._on_input(Key(ESCAPE))
        app.profile_history[2].result(5)
        app._take_profile_sessions()
        reply(app, client, {"sessions": [{"id": "local-open"}]})
        self.assertIsNone(app.pager)
        self.assertIsNone(app.picker)

    def test_stale_picker_actions_do_not_delete_current_or_cover_another_pager(self) -> None:
        with closing(create_store(self.named)) as db:
            insert(db, "local-open", "Locally open")
        app, client = self.open_picker()
        self.take_inventory(app)
        reply(app, client, {"sessions": [{"id": "current"}]})
        app.stored_id = "current"
        app._edit_session(app.picker, PickerAction(DELETE, "current"))
        self.assertEqual([method for method, _ in client.calls], ["session.list"])
        app._on_input(Key(ENTER))
        app._open_pager("Another view", [])
        other = app.pager
        app.profile_history[2].result(5)
        app._take_profile_sessions()
        self.assertIs(app.pager, other)
        app._settle_lost_calls()
        self.assertIsNone(app.picker)

    def test_reset_plus_compression_and_later_gateway_alias_collapse_once(self) -> None:
        with closing(create_store(self.named)) as db:
            insert(db, "created", "Created", ended="session_reset")
            insert(db, "reset", "Reset", parent="created", ended="compression", activity=300)
            insert(db, "tip", "Tip", parent="reset", activity=400)
            db.execute("UPDATE sessions SET chat_id='created' WHERE id='reset'")
            db.execute("INSERT INTO state_meta VALUES ('gateway.local_policy.v1:created', ?)",
                       ('{"session_id":"created","lineage":["created","reset"]}',))
            db.commit()
        app, client = self.open_picker()
        self.take_inventory(app)
        self.assertEqual([row.label for row in app.picker.rows], ["Tip"])
        reply(app, client, {"sessions": [{"id": "created"}], "next_page": "old"})
        app._on_input(Key(CHAR, "g", ctrl=True))
        reply(app, client, {"sessions": [{"id": "tip", "owner_runtime": "other", "resumable": False}]})
        self.assertEqual([(row.id, row.label, row.read_only) for row in app.picker.rows], [("created", "Tip", True)])
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1], ("session.transcript", {"session_id": "created", "order": "latest", "limit": 500}))

    def test_confirmed_delete_removes_row_folded_into_an_alias_while_in_flight(self) -> None:
        picker = SessionPicker([], current="", profiles=("night",))
        rows = session_rows({"sessions": [{"id": "first"}, {"id": "target"}]}, profile="night")
        picker.add_older(rows, "older")
        picker.handle_key(Key(DOWN))
        picker.handle_key(Key(CHAR, "d", ctrl=True))
        action = picker.handle_key(Key(CHAR, "d", ctrl=True))
        self.assertEqual(action, PickerAction(DELETE, "target"))
        picker.asked(action)

        bridge = session_rows({"sessions": [{"id": "bridge", "_lineage_ids": ["first", "target"]}]}, profile="night")
        picker.add_older(bridge, "older-still")
        self.assertEqual([row.id for row in picker.visible()], ["first"])
        self.assertTrue(picker.deleted("target"))
        picker.add_older(rows + bridge, "")
        lines = picker.lines(80, DEFAULT_THEME, 10, 450)
        self.assertIn("No sessions in this view", "\n".join(map(line_text, lines)))

    def test_incomplete_sidecars_are_reported_without_creating_a_pair(self) -> None:
        with closing(create_store(self.default)) as db:
            insert(db, "local-real", "Real")
        before = self.default.read_bytes()
        sidecar = self.default.with_name("state.db-shm")
        sidecar.write_bytes(b"synthetic orphan")
        snapshot = Inventory.read(self.env)
        self.assertEqual(snapshot.problems, ["default: session store unavailable"])
        self.assertEqual(snapshot.rows, [])
        self.assertEqual(set(self.root.glob("state.db*")), {self.default, sidecar})
        self.assertEqual(self.default.read_bytes(), before)
        self.assertEqual(sidecar.read_bytes(), b"synthetic orphan")

    def test_all_profiles_is_one_block_per_bot_in_its_board_colour(self) -> None:
        from omh.tui.bot_board import _avatar_style
        from omh.tui.theme import profile_style

        def row(sid: str, profile: str, activity: int) -> SessionRow:
            return SessionRow(sid, f"{profile} {sid}", "", activity, 1, activity, profile=profile,
                              lineage=frozenset({sid}), local=object(), resumable=False)

        picker = SessionPicker([], current="", profiles=())
        # activity interleaves the two bots; the table must not
        picker.add_local(["kami", "friren"], [row("a", "kami", 500), row("b", "friren", 400), row("c", "kami", 300),
                                              row("d", "friren", 200)])
        self.assertEqual([r.id for r in picker.visible()], ["a", "c", "b", "d"])
        lines = picker.lines(100, DEFAULT_THEME, 16, 600)
        texts = [line_text(line).strip() for line in lines]
        kami, friren = texts.index("kami  2 sessions"), texts.index("friren  2 sessions")
        self.assertLess(kami, friren)
        self.assertEqual(texts[friren - 1], "")  # a blank row sets one bot's block off from the next
        for name, at in (("kami", kami), ("friren", friren)):
            span = next(span for span in lines[at] if span.text == name)
            self.assertEqual(span.style.fg, profile_style(name, DEFAULT_THEME).fg)
            self.assertEqual(span.style.fg, _avatar_style(name, DEFAULT_THEME).fg)  # the bot board's face colour
        # one bot's scope is the plain list: no headings, no blank rows
        picker.handle_key(Key(TAB))
        scoped = [line_text(line).strip() for line in picker.lines(100, DEFAULT_THEME, 16, 600)]
        self.assertNotIn("kami  2 sessions", scoped)
        self.assertNotIn("", scoped[3:-2])

    def test_the_tuis_own_runtime_profile_is_no_bot_here_either(self) -> None:
        from omh.skin_pack import TUI_PROFILE
        from omh.tui.profile_sessions import _homes

        for name in ("night", TUI_PROFILE):
            with closing(create_store(self.root / "profiles" / name / "state.db")) as db:
                insert(db, f"{name}-1", f"{name} chat")
        names = [name for name, _ in _homes(self.env)]
        self.assertIn("night", names)
        self.assertNotIn(TUI_PROFILE, names)
        self.assertNotIn(TUI_PROFILE, Inventory.read(self.env).profiles)
