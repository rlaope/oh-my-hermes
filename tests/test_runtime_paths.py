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
from omh.plugin_bundle.omh import runtime_paths, runtime_reader
from _module_patch import patch_modules


class RuntimePathsTests(unittest.TestCase):
    def test_a_symlink_loop_is_a_binding_error_on_every_interpreter(self):
        # CPython 3.11 and 3.12 raise from `Path.resolve()` on a loop; 3.13
        # resolves it without raising and returns the link itself. The
        # resolver must classify both shapes as a binding error, because the
        # runtime reader's own symlink guard downstream raises a bare
        # RuntimeError that no hook classifier catches (the 3.13 turn-start
        # crash the filesystem-fault tests pin).
        with tempfile.TemporaryDirectory() as tmp:
            loop = Path(tmp) / "loop"
            loop.symlink_to(loop)
            with self.assertRaises(runtime_paths.RuntimeBindingError):
                runtime_paths.expand_path(loop)
            # The 3.13 shape, simulated on every interpreter: resolution
            # returns the path unchanged and raises nothing.
            with patch.object(Path, "resolve", lambda self, strict=False: self):
                with self.assertRaises(runtime_paths.RuntimeBindingError):
                    runtime_paths.expand_path(loop)
            # A link to a real directory still resolves to its target.
            target = Path(tmp) / "target"
            target.mkdir()
            link = Path(tmp) / "link"
            link.symlink_to(target)
            self.assertEqual(runtime_paths.expand_path(link), target.resolve())

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
        managed = types.ModuleType("hermes_cli.managed_scope")
        managed.load_managed_config = lambda: {}
        secrets.build_profile_secret_scope = lambda owner: {"OMH_HOME": str(owner.parent / (owner.name + "-state"))}
        config.require_readable_config_before_write = lambda *args: {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            modules = {"hermes_constants": constants, "agent.secret_scope": secrets,
                       "hermes_cli.config": config, "hermes_cli.managed_scope": managed,
                       "agent.runtime_cwd": types.SimpleNamespace(resolve_context_cwd=lambda: None, resolve_agent_cwd=Path.cwd)}
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
            with patch_modules(modules), patch.dict("os.environ", {
                "OMH_HOME": str(root / "launch-state"), "HERMES_HOME": str(root / "launch")
            }):
                asyncio.run(run())


    def test_standalone_explicit_pairs_and_host_failures(self):
        import os
        from omh.plugin_bundle.omh import runtime_paths as paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch_modules({"hermes_constants": None}), patch.dict(os.environ, {
                "HOME": str(root), "USERPROFILE": str(root),
                "OMH_HOME": str(root / "state"), "HERMES_HOME": str(root / "profile")
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

    def test_standalone_lane_reads_the_launch_homes_own_setting_first(self):
        """`plugins.entries.omh.settings.omh_home`, read with no host loaded.

        The native plugin resolves that setting before any environment value.
        The standalone lane -- the `omh` CLI and the TUI widget's reader
        spawn -- read env `OMH_HOME` or `~/.omh` and never the file, so in a
        profile that named its store, `/omh-model` and `omh model-chains`
        edited one its dispatches never read (#1679).
        """
        import os
        from omh.plugin_bundle.omh import runtime_paths as paths

        setting = "plugins:\n  enabled:\n    - omh\n  entries:\n    omh:\n      settings:\n        omh_home: {value}\nkanban:\n  x: 1\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            profile = root / "profile"
            profile.mkdir()

            def config(text, home=profile):
                home.mkdir(exist_ok=True)
                (home / "config.yaml").write_text(text, encoding="utf-8")

            with patch_modules({"hermes_constants": None}), patch.dict(os.environ, {
                "HOME": str(root), "USERPROFILE": str(root), "SECRET_TOKEN": "sk-live-not-a-path",
                "OMH_HOME": str(root / "state"), "HERMES_HOME": str(profile)
            }):
                # No file, then a file that names nothing -- in block style or
                # inline -- and the environment answers.
                self.assertEqual(paths.resolve_homes(), (root / "state", profile))
                for text in (
                    "model:\n  default: x\nplugins:\n  enabled:\n    - omh\n",
                    "plugins:\n  entries: {}\n",
                    "plugins:\n",
                    "plugins: {enabled: [omh]}\n",
                    "plugins:\n  entries: {other: {}}\n",
                    "plugins:\n  entries:\n    omh:\n      settings:\n        # omh_home: /commented\n",
                ):
                    config(text)
                    with self.subTest(text=text):
                        self.assertEqual(paths.resolve_homes(), (root / "state", profile))
                # The setting beats the environment, under either spelling;
                # a relative value is anchored at the profile and quotes and
                # trailing comments are not part of it.
                config(setting.format(value=str(root / "store")))
                self.assertEqual(paths.resolve_homes(), (root / "store", profile))
                config("plugins:\n  entries:\n    omh:\n      config:\n        omh_home: 'omh/legacy'  # anchored here\n")
                self.assertEqual(paths.resolve_homes(), (profile / "omh" / "legacy", profile))
                config(setting.format(value=f"{root / 'store2'}  # unquoted, comment stripped"))
                self.assertEqual(paths.resolve_homes(), (root / "store2", profile))
                config(setting.format(value='"$HERMES_HOME/omh"'))
                self.assertEqual(paths.resolve_homes(), (profile / "omh", profile))
                # A commented-out line at the setting's own depth is not the
                # setting; the last duplicate wins as a YAML loader reads it;
                # CRLF is a line break; a quoted `null` is a directory name.
                config(
                    "plugins:\n  entries:\n    omh:\n      settings:\n        # omh_home: /commented\n"
                    f"        omh_home: /first\n        omh_home: {root / 'last'}\n"
                )
                self.assertEqual(paths.resolve_homes(), (root / "last", profile))
                config(setting.format(value=str(root / "store")).replace("\n", "\r\n"))
                self.assertEqual(paths.resolve_homes(), (root / "store", profile))
                config(setting.format(value="'null'"))
                self.assertEqual(paths.resolve_homes(), (profile / "null", profile))
                # An anchor is a node property, not the value: one heading a
                # block mapping still has children, one before a scalar
                # still names it.
                config(setting.format(value=f"&store {root / 'anchored'}").replace("plugins:\n", "plugins: &base\n"))
                self.assertEqual(paths.resolve_homes(), (root / "anchored", profile))
                # Another plugin's identical key is not it.
                config("plugins:\n  entries:\n    other:\n      settings:\n        omh_home: /elsewhere\n")
                self.assertEqual(paths.resolve_homes(), (root / "state", profile))
                # An explicit pair still wins, and a named Hermes home follows
                # its own file rather than the launch profile's.
                config(setting.format(value=str(root / "store")))
                self.assertEqual(paths.resolve_homes(root / "named", profile), (root / "named", profile))
                config(setting.format(value=str(root / "other-store")), home=root / "other")
                self.assertEqual(paths.resolve_homes(None, root / "other"), (root / "other-store", root / "other"))
                self.assertEqual(paths.default_omh_home(), root / "store")
                # Refusals, never a substitute store: blank and null; an inline
                # section that does name the setting; an alias or merge key
                # the setting could be inherited through; a leaf a YAML loader
                # would not hand back as one string; a `$VAR` this lane cannot
                # verify (the native lane checks it against the profile's own
                # secret scope); tab indentation; a malformed quote.
                for text in (
                    setting.format(value=""),
                    setting.format(value="~"),
                    setting.format(value="null"),
                    "plugins: {entries: {omh: {settings: {omh_home: /x}}}}\n",
                    "plugins:\n  entries:\n    omh: {settings: {omh_home: /x}}\n",
                    "plugins: 'text'\n",
                    "base: &base\n  entries: {}\nplugins: *base\n",
                    "base: &base\n  omh: {}\nplugins:\n  entries:\n    <<: *base\n",
                    setting.format(value="{a: b}"),
                    setting.format(value="[a, b]"),
                    setting.format(value="true"),
                    setting.format(value="123"),
                    setting.format(value="*alias"),
                    setting.format(value="a\x85b"),
                    setting.format(value="$SECRET_TOKEN/state"),
                    setting.format(value="'unterminated"),
                    setting.format(value="'a' b"),
                    "plugins:\n\tentries:\n\t\tomh: {}\n",
                ):
                    config(text)
                    with self.subTest(text=text), self.assertRaises(paths.RuntimeBindingError):
                        paths.resolve_homes()
                # So is a file that cannot be read at all.
                (profile / "config.yaml").unlink()
                (profile / "config.yaml").mkdir()
                with self.assertRaises(paths.RuntimeBindingError):
                    paths.resolve_homes()

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


    def test_untrusted_evidence_paths_cannot_expand_environment(self):
        import json
        from omh.plugin_bundle.omh.tools.evidence_tool import omh_evidence_handler
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch_modules({"hermes_constants": None}), patch.dict("os.environ", {
                "OMH_HOME": str(root / "state"), "HERMES_HOME": str(root / "profile"),
                "SYNTHETIC_PATH_SECRET": "SYNTHETIC_NOT_FOR_OUTPUT",
            }):
                for field in ("project_root", "workdir"):
                    for reference in ("$SYNTHETIC_PATH_SECRET", "${SYNTHETIC_PATH_SECRET}",
                                      "${env:SYNTHETIC_PATH_SECRET}", "%SYNTHETIC_PATH_SECRET%"):
                        with self.subTest(field=field, reference=reference):
                            result = omh_evidence_handler({"commands": ["git diff --check"],
                                "project_root": str(root), field: reference})
                            self.assertNotIn("SYNTHETIC_NOT_FOR_OUTPUT", result)
                            self.assertEqual(json.loads(result)["error"],
                                             "OMH input paths do not support variable references")
                # Evidence itself remains useful: literal paths still run the
                # allowlisted local probe, with the same minimal environment.
                with patch("subprocess.run") as child:
                    child.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
                    result = json.loads(omh_evidence_handler({"commands": ["git diff --check"],
                                                             "project_root": str(root)}))
                    self.assertTrue(result["all_pass"])
                    self.assertNotIn("SYNTHETIC_PATH_SECRET", child.call_args.kwargs["env"])

    def test_foreign_scope_is_not_a_profile_binding(self):
        from omh.plugin_bundle.omh import runtime_paths as paths
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            private, public = root / "private", root / "public"
            secrets = types.SimpleNamespace(is_multiplex_active=lambda: True,
                current_secret_scope=lambda: {"OMH_HOME": str(private)},
                build_profile_secret_scope=lambda home: {"OMH_HOME": str(public)})
            with patch_modules({"agent.secret_scope": secrets}):
                with self.assertRaisesRegex(paths.RuntimeBindingError, "ownership is unverified"):
                    paths._profile_variable("OMH_HOME", root / "profile")
                secrets.current_secret_scope = lambda: {"OMH_HOME": str(public)}
                self.assertEqual(paths._profile_variable("OMH_HOME", root / "profile"), str(public))

    def test_managed_winning_raw_leaf_ignores_shadowed_user_template(self):
        from omh.plugin_bundle.omh import runtime_paths as paths
        def config(value):
            return {"plugins": {"entries": {"omh": {"settings": {"omh_home": value}}}}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            managed = config(str(root / "managed"))
            host = types.SimpleNamespace(require_readable_config_before_write=lambda path: config("$UNAVAILABLE_USER_PATH/state"),
                                         load_config_readonly=lambda: managed)
            with patch_modules({"hermes_cli.config": host,
                    "hermes_cli.managed_scope": types.SimpleNamespace(load_managed_config=lambda: managed)}):
                self.assertEqual(paths._configured_home(root / "profile"), root / "managed")


if __name__ == "__main__":
    unittest.main()
