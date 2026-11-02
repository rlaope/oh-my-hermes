"""Only a Discord thread Hermes auto-created can share its parent's memory scope."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import memory_thread_parent  # noqa: E402
from omh.plugin_bundle.omh.memory_thread_parent import auto_thread_parent_channel  # noqa: E402

SESSION_ID = "20261101_120000_example:thread-1"
THREAD_ID = "234567890123456789"
PARENT_ID = "123456789012345678"


def auto_thread_origin() -> dict:
    return {
        "platform": "discord",
        "chat_type": "thread",
        "chat_id": THREAD_ID,
        "parent_chat_id": PARENT_ID,
        "auto_thread_created": True,
    }


class DiscordThreadParentTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.db = self.home / "state.db"

    def seed_origin(self, origin: object, *, session_id: str = SESSION_ID) -> None:
        self.seed_raw_origin(json.dumps(origin), session_id=session_id)

    def seed_raw_origin(self, raw: str | bytes | None, *, session_id: str = SESSION_ID) -> None:
        connection = sqlite3.connect(self.db)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(id TEXT PRIMARY KEY, source TEXT, origin_json TEXT, started_at REAL)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO sessions (id, source, origin_json, started_at) VALUES (?, 'discord', ?, 0)",
                (session_id, raw),
            )
            connection.commit()
        finally:
            connection.close()

    def test_auto_created_discord_thread_returns_its_parent(self) -> None:
        self.seed_origin(auto_thread_origin())
        self.assertEqual(auto_thread_parent_channel(self.home, SESSION_ID), PARENT_ID)
        self.assertEqual(auto_thread_parent_channel(str(self.home), SESSION_ID), PARENT_ID)

    def test_auto_thread_marker_must_be_the_boolean_true(self) -> None:
        for marker in (False, None, "true", "True", 1, 0, [], {}):
            with self.subTest(marker=marker):
                self.seed_origin({**auto_thread_origin(), "auto_thread_created": marker})
                self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))
        origin = auto_thread_origin()
        del origin["auto_thread_created"]
        self.seed_origin(origin)
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_other_platforms_and_chat_types_keep_their_own_scope(self) -> None:
        for field, value in (
            ("platform", "slack"),
            ("platform", "telegram"),
            ("platform", "Discord"),
            ("platform", None),
            ("chat_type", "group"),
            ("chat_type", "dm"),
            ("chat_type", None),
        ):
            with self.subTest(field=field, value=value):
                self.seed_origin({**auto_thread_origin(), field: value})
                self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))
        for field in ("platform", "chat_type"):
            with self.subTest(missing=field):
                origin = auto_thread_origin()
                del origin[field]
                self.seed_origin(origin)
                self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_parent_must_be_a_string_containing_an_ascii_snowflake(self) -> None:
        for parent in (
            None, "", "not-a-snowflake", "1" * 16, "1" * 21, "0" + "1" * 17,
            f" {PARENT_ID}", f"{PARENT_ID} ", f"{PARENT_ID}\n", "+" + PARENT_ID,
            "\u0661" * 18, int(PARENT_ID), True, [], {},
        ):
            with self.subTest(parent=parent):
                self.seed_origin({**auto_thread_origin(), "parent_chat_id": parent})
                self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))
        origin = auto_thread_origin()
        del origin["parent_chat_id"]
        self.seed_origin(origin)
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_snowflake_length_boundaries_are_accepted(self) -> None:
        for parent in ("1" * 17, "1" * 18, "1" * 19, "1" * 20):
            with self.subTest(parent=parent):
                self.seed_origin({**auto_thread_origin(), "parent_chat_id": parent})
                self.assertEqual(auto_thread_parent_channel(self.home, SESSION_ID), parent)

    def test_parent_equal_to_chat_id_gives_none(self) -> None:
        self.seed_origin({**auto_thread_origin(), "parent_chat_id": THREAD_ID})
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_malformed_json_gives_none(self) -> None:
        for raw in ("{", "not-json", "", '[' * 2000 + ']' * 2000):
            with self.subTest(raw_prefix=raw[:20]):
                self.seed_raw_origin(raw)
                self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_json_values_other_than_a_dict_give_none(self) -> None:
        for origin in ([auto_thread_origin()], [], None, "discord", 1, True):
            with self.subTest(origin=origin):
                self.seed_origin(origin)
                self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_sql_null_and_blob_origins_give_none(self) -> None:
        for raw in (None, json.dumps(auto_thread_origin()).encode("utf-8"), b"\xff"):
            with self.subTest(raw=raw):
                self.seed_raw_origin(raw)
                self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_missing_row_does_not_use_another_sessions_origin(self) -> None:
        self.seed_origin(auto_thread_origin(), session_id="another-session")
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_missing_store_is_not_created(self) -> None:
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))
        self.assertFalse(self.db.exists())
        absent_home = self.home / "absent-home"
        self.assertIsNone(auto_thread_parent_channel(absent_home, SESSION_ID))
        self.assertFalse(absent_home.exists())

    def test_store_without_origin_json_column_gives_none(self) -> None:
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL)")
            connection.execute("INSERT INTO sessions VALUES (?, 'discord', 0)", (SESSION_ID,))
            connection.commit()
        finally:
            connection.close()
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_store_without_sessions_table_gives_none(self) -> None:
        connection = sqlite3.connect(self.db)
        connection.close()
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_non_database_store_gives_none(self) -> None:
        self.db.write_text("not a SQLite database", encoding="utf-8")
        before = self.db.read_bytes()
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))
        self.assertEqual(self.db.read_bytes(), before)

    def test_locked_store_gives_none(self) -> None:
        self.seed_origin(auto_thread_origin())
        writer = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(writer.close)
        writer.execute("BEGIN EXCLUSIVE")
        self.addCleanup(writer.execute, "ROLLBACK")
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_store_open_errors_give_none(self) -> None:
        self.seed_origin(auto_thread_origin())
        for error in (sqlite3.OperationalError("unable to open"), PermissionError("read denied"), ValueError("bad path")):
            with self.subTest(error=type(error).__name__):
                with patch.object(memory_thread_parent, "connect_readonly", side_effect=error):
                    self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_unsafe_session_ids_do_not_even_resolve_the_store_path(self) -> None:
        class UnopenableHome:
            def __fspath__(self) -> str:
                raise AssertionError("an unsafe session id must not touch the store path")

        for session_id in ("../x", "", "x" * 200, "x" * 129, "a b", "session\n", "\u00e9", None, 1):
            with self.subTest(session_id=session_id):
                self.assertIsNone(auto_thread_parent_channel(UnopenableHome(), session_id))

    def test_safe_session_id_boundaries_and_characters_are_accepted(self) -> None:
        for session_id in ("x", "x" * 128, "AZaz09_.:-"):
            with self.subTest(session_id=session_id):
                self.seed_origin(auto_thread_origin(), session_id=session_id)
                self.assertEqual(auto_thread_parent_channel(self.home, session_id), PARENT_ID)

    def test_read_leaves_store_bytes_and_directory_unchanged(self) -> None:
        self.seed_origin(auto_thread_origin())
        self.assertFalse((self.home / "state.db-wal").exists())
        self.assertFalse((self.home / "state.db-shm").exists())
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns, sorted(path.name for path in self.home.iterdir()))
        self.assertEqual(auto_thread_parent_channel(self.home, SESSION_ID), PARENT_ID)
        after = (self.db.read_bytes(), self.db.stat().st_mtime_ns, sorted(path.name for path in self.home.iterdir()))
        self.assertEqual(after, before)

    def test_wal_store_without_sidecars_is_left_untouched(self) -> None:
        self.seed_origin(auto_thread_origin())
        connection = sqlite3.connect(self.db)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        finally:
            connection.close()
        self.assertFalse((self.home / "state.db-wal").exists())
        self.assertFalse((self.home / "state.db-shm").exists())
        before = (self.db.read_bytes(), sorted(path.name for path in self.home.iterdir()))
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))
        self.assertEqual((self.db.read_bytes(), sorted(path.name for path in self.home.iterdir())), before)

    def test_live_wal_store_with_sidecars_reads_the_committed_origin(self) -> None:
        self.seed_origin(auto_thread_origin())
        writer = sqlite3.connect(self.db)
        self.addCleanup(writer.close)
        self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        writer.execute("UPDATE sessions SET origin_json = ? WHERE id = ?", (json.dumps(auto_thread_origin()), SESSION_ID))
        writer.commit()
        self.assertTrue((self.home / "state.db-wal").is_file())
        self.assertTrue((self.home / "state.db-shm").is_file())
        self.assertEqual(auto_thread_parent_channel(self.home, SESSION_ID), PARENT_ID)
        writer.execute(
            "UPDATE sessions SET origin_json = ? WHERE id = ?",
            (json.dumps({**auto_thread_origin(), "auto_thread_created": False}), SESSION_ID),
        )
        writer.commit()
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))

    def test_origin_is_not_cached(self) -> None:
        self.seed_origin(auto_thread_origin())
        self.assertEqual(auto_thread_parent_channel(self.home, SESSION_ID), PARENT_ID)
        self.seed_origin({**auto_thread_origin(), "auto_thread_created": False})
        self.assertIsNone(auto_thread_parent_channel(self.home, SESSION_ID))


if __name__ == "__main__":
    unittest.main()
