from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import time
import unittest
from abc import ABC
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from functools import cached_property, partial
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Protocol, TypedDict, runtime_checkable
from unittest.mock import Mock, patch

from _local_package import load_local_package
from _typing_support import override

load_local_package()

from omh.plugin_bundle.omh import egress_attempt_receipts as receipt_module
from omh.plugin_bundle.omh import egress_attempts as guard_module
from _module_patch import patch_modules


class IndexedParameters(Protocol):
    def __len__(self) -> int: ...
    def __getitem__(self, index: int, /) -> object: ...


class SchemaStore(Protocol):
    """Structurally checked white-box access for schema transaction assertions."""

    def _connect(self) -> tuple[sqlite3.Connection, bool]: ...


class SchemaProbe(SchemaStore, ABC):
    @staticmethod
    def connect(store: SchemaStore) -> tuple[sqlite3.Connection, bool]:
        return store._connect()


def _row(cursor: sqlite3.Cursor) -> tuple[object, ...] | None:
    fetchone: Callable[[], tuple[object, ...] | None] = cursor.fetchone
    return fetchone()


Handler = Callable[..., str]
Hook = Callable[..., Mapping[str, str | dict[str, str]] | None]


@dataclass
class RegistryEntry:
    handler: Handler
    max_result_size_chars: None = None
    dynamic_schema_overrides: None = None
    is_async: bool = False
    toolset: str = "test"
    schema: dict[str, object] = field(default_factory=dict)
    check_fn: None = None
    requires_env: list[str] = field(default_factory=list)
    description: str = ""
    emoji: str = ""


@dataclass
class RegistrationContext:
    register_hook: Callable[..., object]
    register_tool: Callable[..., object]


@runtime_checkable
class ErrorResponse(Protocol):
    def __contains__(self, key: str, /) -> bool: ...


def _response(
    result: str, decode: Callable[[str], object] = json.loads
) -> ErrorResponse:
    response = decode(result)
    assert isinstance(response, ErrorResponse)
    return response


class AttemptRequest(TypedDict):
    session_id: str
    tool_call_id: str
    tool_name: str
    action_class: str
    destination_class: str
    request_fingerprint: str
    effect_id: str
    destination_digest: str
    payload_digest: str
    payload_bytes: int
    idempotency_key: str | None
    approval_ref: str | None


BUSY_BUDGET_MILLISECONDS = 10
BUSY_BUDGET_SECONDS = BUSY_BUDGET_MILLISECONDS / 1000


@contextmanager
def _bounded_by_configured_budget(
    test: unittest.TestCase,
    *,
    connections: int,
    factory: type[sqlite3.Connection] | None = None,
) -> Iterator[None]:
    """Bound a failure path by its mechanism rather than by a measured duration.

    These paths must return without waiting: no retry loop, no backoff sleep,
    no wait longer than the configured contention budget. Those are properties
    of the code, so this asserts them directly: the exact number of SQLite
    connections the path opens, the busy budget each one carries (the same
    budget ``test_connections_use_ten_millisecond_busy_budget`` pins as a
    ``PRAGMA``), and that nothing slept. Reading a clock instead would assert
    the same properties only on an idle machine, so a loaded shared runner
    reports a false failure.
    """
    connect = sqlite3.connect
    budgets: list[float] = []

    def recording_connect(
        database: Path, *, timeout: float, isolation_level: None
    ) -> sqlite3.Connection:
        budgets.append(timeout)
        if factory is None:
            return connect(database, timeout=timeout, isolation_level=isolation_level)
        return connect(
            database, timeout=timeout, isolation_level=isolation_level, factory=factory
        )

    with (
        patch.object(sqlite3, "connect", side_effect=recording_connect),
        patch.object(time, "sleep") as sleeper,
    ):
        yield
    sleeper.assert_not_called()
    test.assertEqual(budgets, [BUSY_BUDGET_SECONDS] * connections)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request(call: str = "call-1") -> AttemptRequest:
    return {
        "session_id": "session-1",
        "tool_call_id": call,
        "tool_name": "egress_probe_sensitive_tool",
        "action_class": "message_send",
        "destination_class": "chat_channel",
        "request_fingerprint": _digest(call),
        "effect_id": _digest("effect"),
        "destination_digest": _digest("destination"),
        "payload_digest": _digest("payload"),
        "payload_bytes": 37,
        "idempotency_key": _digest("idempotency"),
        "approval_ref": _digest("host-approval"),
    }


class EgressAttemptStoreTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        for name in ("temporary", "home", "store"):
            self.addCleanup(self.__dict__.pop, name, None)
        self.assertIsNotNone(importlib.util.find_spec(receipt_module.__name__))
        _ = self.temporary, self.home, self.store

    @cached_property
    def temporary(self) -> TemporaryDirectory[str]:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return temporary

    @cached_property
    def home(self) -> Path:
        return Path(self.temporary.name) / ".omh"

    @cached_property
    def store(self) -> receipt_module.AttemptStore:
        return receipt_module.AttemptStore(self.home)

    def test_attempt_is_durable_and_public_rows_are_bounded_metadata(self) -> None:
        first = self.store.open_attempt(**_request())

        reopened = receipt_module.AttemptStore(self.home)
        replay = reopened.open_attempt(**_request())
        self.assertEqual(first["disposition"], "created")
        self.assertEqual(replay["disposition"], "already_recorded")
        self.assertEqual(first["attempt_id"], replay["attempt_id"])
        rows = reopened.public_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row_type"], "attempt")
        self.assertNotIn("session-1", json.dumps(rows))
        self.assertNotIn("call-1", json.dumps(rows))
        self.assertLessEqual(
            len(json.dumps(rows[0], sort_keys=True, separators=(",", ":")).encode()),
            1024,
        )

    def test_changed_request_cannot_reuse_a_call_identity(self) -> None:
        _ = self.store.open_attempt(**_request())
        changed: AttemptRequest = {**_request(), "request_fingerprint": _digest("different")}

        with self.assertRaises(receipt_module.AttemptStoreError):
            _ = self.store.open_attempt(**changed)
        self.assertEqual(len(self.store.public_rows()), 1)

    def test_terminal_is_unique_and_conflicting_observations_are_refused(self) -> None:
        attempt = self.store.open_attempt(**_request())
        assert isinstance(attempt["attempt_id"], str)
        first = self.store.record_terminal(attempt["attempt_id"], "returned")
        duplicate = self.store.record_terminal(attempt["attempt_id"], "returned")

        self.assertFalse(first["already_recorded"])
        self.assertTrue(duplicate["already_recorded"])
        with self.assertRaises(receipt_module.AttemptStoreError):
            _ = self.store.record_terminal(attempt["attempt_id"], "error")
        rows = self.store.public_rows()
        self.assertEqual([row["row_type"] for row in rows], ["attempt", "terminal"])
        for row in rows:
            self.assertLessEqual(len(json.dumps(row, separators=(",", ":")).encode()), 1024)

    def test_unknown_outcome_is_preserved_across_reopening(self) -> None:
        attempt = self.store.open_attempt(**_request())
        assert isinstance(attempt["attempt_id"], str)
        _ = self.store.record_terminal(attempt["attempt_id"], "unknown")

        reopened = receipt_module.AttemptStore(self.home)
        replay = reopened.open_attempt(**_request())

        self.assertEqual(replay["disposition"], "already_recorded")
        self.assertEqual(replay["attempt_id"], attempt["attempt_id"])
        self.assertEqual(replay["terminal_state"], "unknown")
        self.assertEqual(len(reopened.public_rows()), 2)

    def test_each_supported_terminal_state_remains_distinct(self) -> None:
        for state in ("blocked", "cancelled", "error", "returned", "unknown"):
            with self.subTest(state=state):
                attempt = self.store.open_attempt(**_request(state))
                assert isinstance(attempt["attempt_id"], str)
                observed = self.store.record_terminal(attempt["attempt_id"], state)
                self.assertEqual(observed["terminal_state"], state)
        with self.assertRaises(receipt_module.AttemptStoreError):
            _ = self.store.record_terminal(attempt["attempt_id"], "delivered")

    def test_writer_lock_fails_within_the_bound_without_appending(self) -> None:
        _ = self.store.open_attempt(**_request("seed"))
        with closing(sqlite3.connect(self.store.database_path)) as holder:
            _ = holder.execute("BEGIN IMMEDIATE")
            with _bounded_by_configured_budget(self, connections=1):
                with self.assertRaises(receipt_module.AttemptStoreError):
                    _ = self.store.open_attempt(**_request("blocked"))
            holder.rollback()

        with self.assertRaises(sqlite3.ProgrammingError):
            _ = holder.execute("SELECT 1")
        self.assertEqual(len(self.store.public_rows()), 1)

    def test_connections_use_ten_millisecond_busy_budget(self) -> None:
        for cold in (True, False):
            with self.subTest(cold=cold):
                connection, created = SchemaProbe.connect(self.store)
                with closing(connection):
                    self.assertEqual(created, cold)
                    self.assertEqual(
                        connection.execute("PRAGMA busy_timeout").fetchone(),
                        (BUSY_BUDGET_MILLISECONDS,),
                    )
                    self.assertEqual(connection.execute("PRAGMA synchronous").fetchone(), (2,))
                    self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone(), ("delete",))
                    self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone(), (1,))
                    self.assertIsNone(connection.isolation_level)
                    self.assertFalse(connection.in_transaction)

    def test_connections_do_not_reconfigure_busy_handler_through_sql(self) -> None:
        connect = sqlite3.connect
        setters: list[str] = []

        def authorize(
            action: int, first: str | None, second: str | None,
            _database: str | None, _trigger: str | None,
        ) -> int:
            if action == sqlite3.SQLITE_PRAGMA and first == "busy_timeout" and second is not None:
                setters.append(second)
            return sqlite3.SQLITE_OK

        def observed_connect(
            database: Path, *, timeout: float, isolation_level: None
        ) -> sqlite3.Connection:
            connection = connect(database, timeout=timeout, isolation_level=isolation_level)
            connection.set_authorizer(authorize)
            return connection

        for cold in (True, False):
            with self.subTest(cold=cold):
                setters.clear()
                with patch.object(sqlite3, "connect", side_effect=observed_connect):
                    connection, created = SchemaProbe.connect(self.store)
                    with closing(connection):
                        self.assertEqual(created, cold)
                self.assertEqual(setters, [])

    def test_writer_lock_blocks_registered_handler_without_consuming_call(self) -> None:
        _ = self.store.open_attempt(**_request("seed"))
        rows = self.store.public_rows()
        handler = Mock(return_value="local-spy-returned")
        wrapper, args, _, _ = self._registered_handler(handler)
        with closing(sqlite3.connect(self.store.database_path)) as holder:
            _ = holder.execute("BEGIN IMMEDIATE")
            self.assertIn("error", _response(wrapper(args, session_id="session-1")))
            handler.assert_not_called()
            self.assertEqual(self.store.public_rows(), rows)
            holder.rollback()

        # Only an unrecorded identity can succeed once after the lock is released.
        wrapper, args, _, _ = self._registered_handler(handler)
        self.assertEqual(wrapper(args, session_id="session-1"), "local-spy-returned")
        recorded = self.store.public_rows()
        self.assertEqual(len(recorded), 2)
        wrapper, args, _, _ = self._registered_handler(handler)
        self.assertIn("error", _response(wrapper(args, session_id="session-1")))
        handler.assert_called_once()
        self.assertEqual(self.store.public_rows(), recorded)

    def test_cold_schema_is_atomic_and_repeated_open_does_not_write(self) -> None:
        connect = sqlite3.connect
        visible_objects: list[int] = []
        database_path = self.store.database_path

        class ObservedSchema(sqlite3.Connection):
            @override
            def execute(
                self, sql: str, parameters: IndexedParameters | Mapping[str, object] = (), /
            ) -> sqlite3.Cursor:
                cursor = super().execute(sql, parameters)
                if sql.lstrip().startswith("CREATE"):
                    with closing(connect(database_path)) as observer:
                        row = _row(observer.execute(
                            "SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                        ))
                        assert row is not None
                        count = row[0]
                        assert isinstance(count, int)
                        visible_objects.append(count)
                return cursor

        with patch.object(sqlite3, "connect", side_effect=partial(connect, factory=ObservedSchema)):
            connection, created = SchemaProbe.connect(self.store)
            with closing(connection):
                self.assertTrue(created)
                self.assertFalse(connection.in_transaction)
        self.assertEqual(visible_objects, [0, 0, 0, 0])

        with closing(connect(database_path)) as observer:
            self.assertEqual(set(observer.execute(
                "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            )), {
                ("table", "egress_attempts"), ("table", "egress_attempt_terminals"),
                ("index", "egress_attempts_identity_lookup"),
                ("index", "egress_attempts_recent_lookup"),
            })
            self.assertEqual(observer.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            version = _row(observer.execute("PRAGMA data_version"))
            before = database_path.read_bytes()
            # Existing-schema reads must not acquire a writer lock or commit changes.
            _ = observer.execute("BEGIN IMMEDIATE")
            connection, created = SchemaProbe.connect(receipt_module.AttemptStore(self.home))
            with closing(connection):
                self.assertFalse(created)
                self.assertFalse(connection.in_transaction)
                self.assertEqual(connection.execute("PRAGMA synchronous").fetchone(), (2,))
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone(), ("delete",))
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone(), (1,))
            self.assertEqual(self.store.public_rows(), [])
            observer.rollback()
            self.assertEqual(observer.execute("PRAGMA data_version").fetchone(), version)
            self.assertEqual(database_path.read_bytes(), before)

    def test_cold_schema_failure_rolls_back_and_blocks_registered_handler(self) -> None:
        connect = sqlite3.connect
        for failure in ("ddl", "commit"):
            with self.subTest(failure=failure):
                self.home = Path(self.temporary.name) / failure
                self.store = receipt_module.AttemptStore(self.home)
                denied: list[str] = []

                def failing_connect(
                    database: Path, *, timeout: float, isolation_level: None
                ) -> sqlite3.Connection:
                    connection = connect(database, timeout=timeout, isolation_level=isolation_level)

                    def authorize(
                        action: int, first: str | None, _second: str | None,
                        _database: str | None, _trigger: str | None,
                    ) -> int:
                        if (
                            failure == "ddl" and action == sqlite3.SQLITE_CREATE_TABLE
                            and first == "egress_attempt_terminals"
                        ) or (
                            failure == "commit" and action == sqlite3.SQLITE_TRANSACTION
                            and first == "COMMIT" and connection.total_changes == 0
                        ):
                            denied.append(failure)
                            return sqlite3.SQLITE_DENY
                        return sqlite3.SQLITE_OK

                    connection.set_authorizer(authorize)
                    return connection

                handler = Mock(return_value="local-spy-returned")
                wrapper, args, _, _ = self._registered_handler(handler)
                with patch.object(sqlite3, "connect", side_effect=failing_connect):
                    result = wrapper(args, session_id="session-1")
                handler.assert_not_called()
                self.assertIn("error", _response(result))
                self.assertEqual(denied, [failure])
                # Inspect directly: public_rows would repair a partially committed schema.
                with closing(connect(self.store.database_path)) as observer:
                    self.assertEqual(observer.execute("SELECT name FROM sqlite_master").fetchall(), [])
                    self.assertEqual(observer.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
                # After removing the fault, the same cold store can initialize normally.
                wrapper, args, _, _ = self._registered_handler(handler)
                self.assertEqual(wrapper(args, session_id="session-1"), "local-spy-returned")
                wrapper, args, _, _ = self._registered_handler(handler)
                self.assertIn("error", _response(wrapper(args, session_id="session-1")))
                handler.assert_called_once()
                self.assertEqual([row["row_type"] for row in self.store.public_rows()], ["attempt"])

    def test_corruption_is_not_replaced_with_an_empty_store(self) -> None:
        self.store.database_path.parent.mkdir(parents=True)
        _ = self.store.database_path.write_bytes(b"not a database")

        with self.assertRaises(receipt_module.AttemptStoreError):
            _ = self.store.open_attempt(**_request())
        self.assertEqual(self.store.database_path.read_bytes(), b"not a database")

    def test_unredacted_values_are_rejected_before_storage(self) -> None:
        for key, value in (
            ("destination_digest", "https://private.example.test/path"),
            ("payload_digest", "private message body"),
            ("effect_id", "/Users/operator/secret"),
            ("idempotency_key", "sk-live-secret"),
            ("approval_ref", "approval-from-model"),
        ):
            with self.subTest(key=key):
                request = _request()
                request[key] = value
                with self.assertRaises(receipt_module.AttemptStoreError):
                    _ = self.store.open_attempt(**request)
        self.assertFalse(self.home.exists())

    def test_storage_oserror_cannot_be_reported_as_a_durable_attempt(self) -> None:
        with patch.object(Path, "mkdir", side_effect=OSError("injected storage failure")):
            with self.assertRaises(receipt_module.AttemptStoreError):
                _ = self.store.open_attempt(**_request())
        self.assertFalse(self.home.exists())

    def test_optional_refs_are_null_not_hashes_of_missing_labels(self) -> None:
        request: AttemptRequest = {**_request(), "approval_ref": None, "idempotency_key": None}
        _ = self.store.open_attempt(**request)
        row = self.store.public_rows()[0]
        self.assertIsNone(row["approval_ref"])
        self.assertIsNone(row["idempotency_key"])

    def _registered_handler(
        self, handler: Handler
    ) -> tuple[Handler, dict[str, str], dict[str, Hook], dict[str, str]]:
        entries = {"send_probe": RegistryEntry(handler)}
        hooks: dict[str, Hook] = {}

        def register_tool(
            name: str, _toolset: str, _schema: dict[str, object], wrapper: Handler, **_kwargs: object
        ) -> None:
            entries[name] = RegistryEntry(wrapper)

        def get_entry(name: str, **_kwargs: object) -> RegistryEntry | None:
            return entries.get(name)

        ctx = RegistrationContext(register_hook=hooks.__setitem__, register_tool=register_tool)
        registry = SimpleNamespace(get_entry=get_entry)
        with patch_modules({"tools.registry": SimpleNamespace(registry=registry)}):
            guard_module.register(ctx, {
                "omh_home": str(self.home),
                "tools": {"send_probe": {
                    "action_class": "message_send", "destination_class": "chat_channel",
                    "destination_arg": "channel", "payload_arg": "body",
                }},
            })
        identity = {"tool_name": "send_probe", "session_id": "session-1", "tool_call_id": "call-1"}
        directive = hooks["pre_tool_call"](**identity)
        assert directive is not None
        self.assertEqual(directive["action"], "modify")
        additions = directive["args"]
        assert isinstance(additions, dict)
        args = {"channel": "private-room", "body": "payload", **additions}
        return entries["send_probe"].handler, args, hooks, identity

    def test_windows_full_commit_precedes_handler_without_directory_open(self) -> None:
        events: list[str] = []
        test = self

        class ObservedConnection(sqlite3.Connection):
            @override
            def commit(self) -> None:
                test.assertEqual(self.execute("PRAGMA synchronous").fetchone(), (2,))
                test.assertEqual(self.execute("PRAGMA journal_mode").fetchone(), ("delete",))
                super().commit()
                if self.total_changes:
                    events.append("committed")

        def handler(args: dict[str, object], **_kwargs: object) -> str:
            rows = receipt_module.AttemptStore(self.home).public_rows()
            self.assertEqual([row["row_type"] for row in rows], ["attempt"])
            self.assertEqual(args, {"channel": "private-room", "body": "payload"})
            events.append("handler")
            return "local-spy-returned"

        wrapper, args, hooks, identity = self._registered_handler(handler)
        connect = sqlite3.connect
        directory_open = Mock(side_effect=PermissionError("Windows CRT rejects directories"))
        directory_fsync = Mock(wraps=os.fsync)
        platform_os = Mock(wraps=os, open=directory_open, fsync=directory_fsync)
        platform_os.name = "nt"
        with (
            patch.object(receipt_module, "os", platform_os),
            patch.object(sqlite3, "connect", side_effect=partial(connect, factory=ObservedConnection)),
        ):
            # Only OMH's platform seam is simulated; SQLite and pathlib stay real.
            self.assertEqual(wrapper(args, session_id="session-1"), "local-spy-returned")
            self.assertEqual(events, ["committed", "handler"])
            _ = hooks["post_tool_call"](**identity, status="ok")
            _ = hooks["post_tool_call"](**identity, status="ok")
            self.assertEqual(events, ["committed", "handler", "committed"])
            replay = hooks["pre_tool_call"](**identity)
            assert replay is not None
            additions = replay["args"]
            assert isinstance(additions, dict)
            replay_args = {"channel": "private-room", "body": "payload", **additions}
            self.assertIn("error", _response(wrapper(replay_args, session_id="session-1")))
            self.assertEqual(events, ["committed", "handler", "committed"])
            directory_open.assert_not_called()
            directory_fsync.assert_not_called()
        rows = receipt_module.AttemptStore(self.home).public_rows()
        self.assertEqual([row["row_type"] for row in rows], ["attempt", "terminal"])
        self.assertEqual(rows[1]["terminal_state"], "returned")

    def test_windows_commit_failure_blocks_handler_and_does_not_mint_attempt(self) -> None:
        commits: list[str] = []
        test = self

        class FailedCommit(sqlite3.Connection):
            @override
            def commit(self) -> None:
                test.assertEqual(self.execute("PRAGMA synchronous").fetchone(), (2,))
                test.assertEqual(self.execute("PRAGMA journal_mode").fetchone(), ("delete",))
                if self.total_changes:
                    test.assertTrue(self.in_transaction)
                    test.assertEqual(self.execute("SELECT count(*) FROM egress_attempts").fetchone(), (1,))
                    commits.append("attempt")
                    raise sqlite3.OperationalError("injected SQLITE_IOERR_FSYNC")
                super().commit()
                commits.append("schema")

        handler = Mock()
        wrapper, args, _, _ = self._registered_handler(handler)
        platform_os = Mock(wraps=os)
        platform_os.name = "nt"
        with (
            patch.object(receipt_module, "os", platform_os),
            _bounded_by_configured_budget(self, connections=1, factory=FailedCommit),
        ):
            self.assertFalse(self.store.database_path.exists())
            result = wrapper(args, session_id="session-1")
        self.assertIn("error", _response(result))
        handler.assert_not_called()
        self.assertEqual(commits, ["schema", "attempt"])
        self.assertEqual(self.store.public_rows(), [])

    def test_posix_directory_failures_block_handler_after_commit(self) -> None:
        for operation in ("open", "fsync"):
            with self.subTest(operation=operation):
                self.home = Path(self.temporary.name) / operation
                self.store = receipt_module.AttemptStore(self.home)
                handler = Mock()
                wrapper, args, _, _ = self._registered_handler(handler)
                # Simulate descriptor operations so the negative control also runs on Windows.
                directory_open = Mock(return_value=123)
                directory_fsync = Mock(return_value=None)
                directory_close = Mock(return_value=None)
                platform_os = Mock(
                    wraps=os, open=directory_open, fsync=directory_fsync, close=directory_close,
                )
                platform_os.name = "posix"
                failed_operation = {"open": directory_open, "fsync": directory_fsync}[operation]
                failed_operation.side_effect = OSError("injected directory failure")
                with (
                    patch.object(receipt_module, "os", platform_os),
                    _bounded_by_configured_budget(self, connections=1),
                ):
                    result = wrapper(args, session_id="session-1")
                    failed_operation.assert_called_once()
                    if operation == "fsync":
                        directory_close.assert_called_once_with(123)
                self.assertIn("error", _response(result))
                handler.assert_not_called()
                rows = self.store.public_rows()
                self.assertEqual([row["row_type"] for row in rows], ["attempt"])
                # A committed-but-unconfirmed attempt remains unresolved, never replayable.
                wrapper, args, _, _ = self._registered_handler(handler)
                self.assertIn("error", _response(wrapper(args, session_id="session-1")))
                handler.assert_not_called()
                self.assertEqual(self.store.public_rows(), rows)


if __name__ == "__main__":
    _ = unittest.main()
