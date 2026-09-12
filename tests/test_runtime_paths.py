"""Profile bindings must not borrow a launch profile's runtime state."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import runtime_reader


class RuntimePathsTests(unittest.TestCase):
    def test_scoped_readers_do_not_borrow_process_homes(self):
        home = ContextVar("test_home")
        values = ContextVar("test_values")
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = home.get
        constants.get_hermes_home_override = home.get
        secrets = types.ModuleType("agent.secret_scope")
        secrets.is_multiplex_active = lambda: True
        secrets.current_secret_scope = values.get
        secrets.get_secret = lambda key, default=None: values.get().get(key, default)
        config = types.ModuleType("hermes_cli.config")
        config.load_config_readonly = lambda: {}
        config.require_readable_config_before_write = lambda *args: {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            modules = {"hermes_constants": constants, "agent.secret_scope": secrets,
                       "hermes_cli.config": config}
            async def read(label):
                expected_home, expected_store = root / label, root / (label + "-state")
                home.set(expected_home)
                values.set({"OMH_HOME": str(expected_store)})
                await asyncio.sleep(0)
                self.assertEqual(runtime_reader._default_omh_home(), expected_store)
                self.assertEqual(runtime_reader._default_hermes_home(), expected_home)
                self.assertEqual(await asyncio.to_thread(runtime_reader._default_omh_home), expected_store)
            async def run():
                await asyncio.gather(read("alpha"), read("beta"))
            with patch.dict("sys.modules", modules), patch.dict("os.environ", {
                "OMH_HOME": str(root / "launch-state"), "HERMES_HOME": str(root / "launch")
            }):
                asyncio.run(run())


    def test_standalone_explicit_pairs_and_host_failures(self):
        import os
        from omh.plugin_bundle.omh import runtime_paths as paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.dict("sys.modules", {"hermes_constants": None}), patch.dict(os.environ, {
                "HOME": str(root), "OMH_HOME": str(root / "state"), "HERMES_HOME": str(root / "profile")
            }):
                self.assertEqual(paths.resolve_homes(), (root / "state", root / "profile"))
                self.assertEqual(paths.resolve_homes(root / "shared", root / "other"), (root / "shared", root / "other"))
                self.assertEqual(paths.resolve_homes("$HERMES_HOME/state", root / "other"), (root / "other/state", root / "other"))
                for invalid in ("", "   ", [], {}, False, "bad\0path", "$UNBOUND_OMH_TEST_PATH/state"):
                    with self.subTest(invalid=invalid), self.assertRaises(paths.RuntimeBindingError):
                        paths.resolve_homes(invalid, root / "other")
                del os.environ["OMH_HOME"]
                self.assertEqual(paths.default_omh_home(), root / ".omh")
            broken = ModuleNotFoundError("missing host dependency", name="host_dependency")
            with patch.object(paths, "import_module", side_effect=broken):
                with self.assertRaises(ModuleNotFoundError) as caught:
                    paths.default_omh_home()
                self.assertIs(caught.exception, broken)

    def test_same_session_ids_do_not_consume_another_profiles_guards(self):
        import json
        from omh.plugin_bundle.omh import agent_board_bridge as board, toolcall_rules as rules
        from omh.plugin_bundle.omh import runtime_paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ("a", "b"):
                rule_path = root / name / "rules" / "toolcall-rules.json"
                rule_path.parent.mkdir(parents=True)
                rule_path.write_text(json.dumps({"schema_version": rules.TOOLCALL_RULES_SCHEMA_VERSION,
                    "rules": [{"name": "same-rule", "pattern": "blocked", "message": "Stop", "repeat": "once"}]}))
            for name in ("a", "b"):
                with patch.object(runtime_paths, "default_hermes_home", return_value=root / name):
                    self.assertIsNotNone(rules.toolcall_rule_directive(tool_name="blocked",
                        tool_input={}, session_id="collision", omh_home=str(root / name)))
            host_a = board.HostIdentity("session", "task", "call-a")
            host_b = board.HostIdentity("session", "task", "call-b")
            args = {"operation": "prepare"}
            for name, host in (("a", host_a), ("b", host_b)):
                with patch.object(runtime_paths, "default_hermes_home", return_value=root / name):
                    board._arm_prepare_call(host, board._input_digest(args))
            for name, host in (("a", host_a), ("b", host_b)):
                with patch.object(runtime_paths, "default_hermes_home", return_value=root / name):
                    self.assertEqual(board.handler_identity(args, {"session_id": "session", "task_id": "task"}), host)


if __name__ == "__main__":
    unittest.main()
