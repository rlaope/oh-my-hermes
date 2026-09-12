from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import import_module
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

from _local_package import load_local_package
load_local_package()
from omh.plugin_bundle import omh as plugin
from omh.system.paths import OmhPaths
from omh.workflows.session_activity_receipts import read_session_activity_receipts
from test_plugin_distribution import FakeHermesContext


class NativeContext(FakeHermesContext):
    def __init__(self):
        super().__init__()
        self.cleanups = []

    def get_config(self, key, default=None):
        return {"enabled": True} if key == "group_chat_activity" else default

    def register_hook(self, name, handler):
        super().register_hook(name, handler)
        return SimpleNamespace(dispose=lambda: self.hooks.pop(name, None))

    def on_unload(self, callback):
        self.cleanups.append(callback)


class NativeObserverTests(unittest.TestCase):
    @contextmanager
    def host(self, root: Path):
        context = NativeContext()
        paths = OmhPaths(root / "omh", root / "hermes")
        with patch.dict("os.environ", {"OMH_HOME": str(paths.omh_home), "HERMES_HOME": str(paths.hermes_home)}), patch.dict(
            "sys.modules", {"hermes_cli.plugins": SimpleNamespace(VALID_HOOKS={"on_room_member_activity"}),
                            "hermes_constants": SimpleNamespace(get_hermes_home=lambda: paths.hermes_home),
                            "agent.secret_scope": SimpleNamespace(is_multiplex_active=lambda: False,
                                current_secret_scope=lambda: None, get_secret=lambda name: str(paths.omh_home)),
                            "hermes_cli.config": SimpleNamespace(
                                require_readable_config_before_write=lambda path: {},
                                load_config_readonly=lambda: {})}):
            try:
                plugin.register(context)
                callback = context.hooks.get("on_room_member_activity")
                assert isinstance(callback, MethodType), "supported host callback was not registered"
                yield callback, paths
            finally:
                for cleanup in reversed(context.cleanups):
                    cleanup()
                if context.cleanups:
                    self.assertTrue(context.cleanups[0].__self__.engine.close())

    def metadata(self, kind="tool.started", seq=1):
        return dict(room_id="RAW_ROOM", thread_id="RAW_THREAD", member_id="RAW_MEMBER", turn_id="RAW_TURN",
                    task_id="RAW_TASK", execution_generation=1, kind=kind, seq=seq,
                    payload={"text": "RAW_PRIVATE_SENTINEL", "tool_args": {"token": "RAW_PRIVATE_SENTINEL"}})

    def test_native_tool_started_is_a_partial_call_not_a_tool_error(self):
        with TemporaryDirectory() as tmp:
            with self.host(Path(tmp)) as (callback, paths):  # Given
                callback(**self.metadata())
                callback(**self.metadata("turn.error", 2))
                callback(**self.metadata("tool.completed", 4))
                self.assertTrue(callback.__self__.engine.flush())
            # When: supported unload, not a fabricated room terminal.
            receipts = read_session_activity_receipts(paths)
            self.assertEqual(len(receipts), 1)  # Then
            self.assertFalse(receipts[0]["boundary"]["final"])
            self.assertEqual(receipts[0]["metrics"]["tool_calls"],
                             {"value": 1, "availability": "observed", "measurement": "floor"})
            self.assertIsNone(receipts[0]["metrics"]["tool_errors"]["value"])
            self.assertGreater(callback.__self__.status()["gapped"], 0)

    def test_duplicate_native_sequence_does_not_depend_on_callback_clock(self):
        with TemporaryDirectory() as tmp:
            with self.host(Path(tmp)) as (callback, paths):
                native = import_module(callback.__self__.__class__.__module__)
                with patch.object(native, "datetime") as clock:
                    clock.now.return_value = datetime(2026, 9, 12, tzinfo=timezone.utc)
                    callback(**self.metadata())  # Given
                    self.assertTrue(callback.__self__.engine.flush())
                    # When: duplicate delivered later; payload and collector time are not event identity.
                    clock.now.return_value = datetime(2026, 9, 12, 0, 1, tzinfo=timezone.utc)
                    event = self.metadata()
                    event["payload"] = {"text": "RAW_DIFFERENT_SENTINEL"}
                    callback(**event)
                    self.assertTrue(callback.__self__.engine.flush())
                self.assertEqual(callback.__self__.status()["rejected"], 0)
            self.assertEqual(read_session_activity_receipts(paths)[0]["metrics"]["tool_calls"]["value"], 1)

    def test_native_member_sequences_and_profiles_are_isolated(self):
        with TemporaryDirectory() as tmp:
            receipts = []
            for name in ("a", "b"):
                with self.host(Path(tmp) / name) as (callback, paths):  # Given
                    callback(**self.metadata())
                    callback(**dict(self.metadata(), member_id="RAW_OTHER_MEMBER"))  # When: same seq, independent session.
                    self.assertTrue(callback.__self__.engine.flush())
                own = read_session_activity_receipts(paths)  # Then
                self.assertEqual(len(own), 2)
                self.assertTrue(all(r["metrics"]["tool_calls"]["value"] == 1 for r in own))
                receipts.append(own[0])
            self.assertNotEqual(receipts[0]["profile_ref"], receipts[1]["profile_ref"])
            self.assertNotEqual(receipts[0]["session_ref"], receipts[1]["session_ref"])

    def test_native_payload_is_absent_from_queue_status_and_all_persisted_state(self):
        with TemporaryDirectory() as tmp:
            with self.host(Path(tmp)) as (callback, paths):  # Given
                callback(**self.metadata())  # When
                self.assertTrue(callback.__self__.engine.flush())
                self.assertNotIn("RAW_", repr(callback.__self__.engine._pending))
                self.assertNotIn("RAW_", json.dumps(callback.__self__.status()))
            for path in paths.omh_home.rglob("*"):  # Then
                if path.is_file():
                    self.assertNotIn(b"RAW_", path.read_bytes())

    def test_superseded_generation_is_rejected_after_new_attempt(self):
        with TemporaryDirectory() as tmp:
            with self.host(Path(tmp)) as (callback, paths):
                callback(**dict(self.metadata(), execution_generation=2))  # Given
                callback(**self.metadata(seq=2))  # When: old generation after a newer observed attempt.
                self.assertTrue(callback.__self__.engine.flush())
                self.assertEqual(callback.__self__.status()["last_outcome"], "stale_event")  # Then
                self.assertEqual(callback.__self__.status()["rejected"], 1)
            self.assertEqual(len(read_session_activity_receipts(paths)), 1)

    def test_profile_key_is_stable_across_adapter_reload(self):
        with TemporaryDirectory() as tmp:
            with self.host(Path(tmp)) as (callback, paths):
                callback(**self.metadata())
                self.assertTrue(callback.__self__.engine.flush())
                profile = callback.__self__.engine.profile_ref  # Given
            with self.host(Path(tmp)) as (callback, _):  # When: same profile, new adapter.
                self.assertEqual(callback.__self__.engine.profile_ref, profile)  # Then
                callback(**self.metadata(seq=2))
                self.assertTrue(callback.__self__.engine.flush())
            self.assertTrue(all(r["metrics"]["tool_calls"]["measurement"] == "floor"
                                for r in read_session_activity_receipts(paths)))

    def test_profile_status_snapshot_rejects_raw_or_malformed_fields(self):
        from omh.plugin_bundle.omh.group_activity_status import read_group_activity_status, status_path
        with TemporaryDirectory() as tmp:
            with self.host(Path(tmp)) as (callback, paths):
                self.assertTrue(callback.__self__.engine.flush())
            snapshot = status_path(paths.omh_home, paths.hermes_home)
            snapshot.write_text(json.dumps({"payload": "RAW_PRIVATE_SENTINEL"}))  # Given
            status = read_group_activity_status(paths.omh_home, paths.hermes_home)  # When
            self.assertEqual(status["compatibility"], "status_unreadable")  # Then
            self.assertNotIn("RAW_", json.dumps(status))

    def test_missing_sequence_unknown_kind_and_malformed_coordinates_are_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.host(Path(tmp)) as (callback, paths):  # Given
                for event in (self.metadata(seq=None), self.metadata(kind="unsupported"),
                              dict(self.metadata(), room_id=[]), dict(self.metadata(), execution_generation=True)):
                    callback(**event)  # When
                self.assertTrue(callback.__self__.engine.flush())
                self.assertEqual(callback.__self__.status()["rejected"], 4)  # Then
            self.assertEqual(read_session_activity_receipts(paths), [])


if __name__ == "__main__":
    unittest.main()
