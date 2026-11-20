"""The validated-config memo behind every hook's home binding (#2973).

Only the host validator's parse of a local profile `config.yaml` is
remembered, keyed on the bytes read. These tests pin both halves: a warm call
skips the validating parse, and nothing the binding depends on beyond those
bytes (path aliases, the working directory, secret ownership, the config
backend, the validator) is served from the memo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import runtime_paths as paths
from _module_patch import patch_modules


def _setting(value) -> str:
    return json.dumps({"plugins": {"entries": {"omh": {"settings": {"omh_home": value}}}}})


class ResolutionMemoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "profile"
        self.home.mkdir()
        self.config_path = self.home / "config.yaml"
        self.enterContext(patch.dict(os.environ, {
            "HOME": str(self.root), "USERPROFILE": str(self.root), "HERMES_HOME": str(self.home)}))
        os.environ.pop("OMH_HOME", None)
        # No state crosses tests: each starts and ends with an empty memo.
        self._reset_memo()
        self.addCleanup(self._reset_memo)

        self.validate = Mock(side_effect=self._parse)
        self.backend = types.SimpleNamespace(name="file")
        self.scope = None
        self.owned = {}
        self.modules = {
            "hermes_constants": types.SimpleNamespace(
                get_hermes_home=lambda: self.home, get_hermes_home_override=lambda: str(self.home)),
            "agent.secret_scope": types.SimpleNamespace(
                is_multiplex_active=lambda: False,
                current_secret_scope=lambda: self.scope,
                current_secret_scope_home=lambda: None,
                get_secret=lambda name, default=None: default,
                build_profile_secret_scope=lambda home: dict(self.owned)),
            # get_config_path / get_managed_dir: the key helpers the earlier
            # witness-keyed memo read, so that version's memo engages here.
            "hermes_cli.config": types.SimpleNamespace(
                require_readable_config_before_write=self.validate,
                load_config_readonly=lambda: self._parse(self.config_path),
                get_config_path=lambda: self.config_path),
            "hermes_cli.config_backend": types.SimpleNamespace(get_config_backend=lambda: self.backend),
            "hermes_cli.managed_scope": types.SimpleNamespace(
                load_managed_config=lambda: {}, get_managed_dir=lambda: None),
            "agent.runtime_cwd": types.SimpleNamespace(resolve_context_cwd=lambda: None, resolve_agent_cwd=Path.cwd),
            # Hermes' YAML reader, which re-reads the keyed bytes before a
            # parse is published; the fixture's configs are JSON, i.e. YAML.
            "hermes_yaml": types.SimpleNamespace(
                safe_load=lambda stream: json.loads(stream.read() or "null"), YAMLError=ValueError),
        }
        self.enterContext(patch_modules(self.modules))

    @staticmethod
    def _reset_memo():
        # Also the name an earlier, whole-binding memo used, so these tests
        # run red, not erroring, against it.
        for name in ("_VALIDATED_CONFIG", "_CONFIG_RESOLUTION_MEMO"):
            getattr(paths, name, {}).clear()

    @staticmethod
    def _parse(path):
        path = Path(path)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8") or "{}")

    def _write(self, text: str) -> None:
        self.config_path.write_text(text, encoding="utf-8")

    def test_warm_call_returns_the_same_binding_without_a_second_parse(self):
        store = self.root / "store"
        self._write(_setting(str(store)))
        first = paths.resolve_homes()
        for _ in range(5):
            self.assertEqual(paths.resolve_homes(), first)
        self.assertEqual(first, (store, self.home))
        self.assertEqual(self.validate.call_count, 1)

    def test_same_size_rewrite_with_restored_timestamps_recomputes(self):
        self._write(_setting(str(self.root / "aaaa")))
        before = os.stat(self.config_path)
        self.assertEqual(paths.resolve_homes()[0], self.root / "aaaa")
        self._write(_setting(str(self.root / "bbbb")))
        os.utime(self.config_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(os.stat(self.config_path).st_size, before.st_size)
        self.assertEqual(paths.resolve_homes()[0], self.root / "bbbb")
        self.assertEqual(self.validate.call_count, 2)

    def test_atomic_replacement_recomputes(self):
        self._write(_setting(str(self.root / "one")))
        self.assertEqual(paths.resolve_homes()[0], self.root / "one")
        staged = self.home / "config.yaml.tmp"
        staged.write_text(_setting(str(self.root / "two")), encoding="utf-8")
        os.replace(staged, self.config_path)
        self.assertEqual(paths.resolve_homes()[0], self.root / "two")

    def test_create_and_delete_recompute(self):
        self.assertEqual(paths.resolve_homes()[0], self.root / ".omh")
        self._write(_setting(str(self.root / "made")))
        self.assertEqual(paths.resolve_homes()[0], self.root / "made")
        self.config_path.unlink()
        self.assertEqual(paths.resolve_homes()[0], self.root / ".omh")
        # Absence is never remembered: the host validator answers each time.
        self.assertEqual(paths.resolve_homes()[0], self.root / ".omh")
        self.assertEqual(self.validate.call_count, 4)

    def test_unreadable_file_after_a_warm_hit_goes_to_the_validator(self):
        self._write(_setting(str(self.root / "store")))
        paths.resolve_homes()
        self.validate.side_effect = PermissionError("denied")
        with patch.object(paths, "open", side_effect=PermissionError("denied"), create=True):
            with self.assertRaises(paths.RuntimeBindingError):
                paths.resolve_homes()
        self.assertEqual(self.validate.call_count, 2)

    def test_a_validation_failure_is_not_cached(self):
        self._write(_setting(str(self.root / "store")))
        self.validate.side_effect = [ValueError("broken"), {"plugins": {}}]
        with self.assertRaises(paths.RuntimeBindingError):
            paths.resolve_homes()
        with self.assertRaises(paths.RuntimeBindingError):
            # The second parse answers again; its disagreement with the
            # effective config is a fresh, live refusal.
            paths.resolve_homes()
        self.assertEqual(self.validate.call_count, 2)

    def test_a_non_file_backend_always_takes_the_host_read(self):
        self._write(_setting(str(self.root / "store")))
        self.backend = types.SimpleNamespace(name="remote")
        for _ in range(3):
            paths.resolve_homes()
        self.assertEqual(self.validate.call_count, 3)

    def test_no_backend_module_takes_the_uncached_path(self):
        self._write(_setting(str(self.root / "store")))
        with patch_modules({"hermes_cli.config_backend": None}):
            paths.resolve_homes()
            paths.resolve_homes()
        self.assertEqual(self.validate.call_count, 2)

    def test_a_replaced_validator_is_called(self):
        self._write(_setting(str(self.root / "store")))
        paths.resolve_homes()
        replacement = Mock(side_effect=self._parse)
        self.modules["hermes_cli.config"].require_readable_config_before_write = replacement
        paths.resolve_homes()
        replacement.assert_called_once()

    def test_a_write_during_validation_is_not_published(self):
        self._write(_setting(str(self.root / "old")))

        def racing(path):
            parsed = self._parse(path)
            self._write(_setting(str(self.root / "new")))
            return parsed

        self.validate.side_effect = racing
        with self.assertRaises(paths.RuntimeBindingError):
            # The parse names `old`, the effective read already sees `new`.
            paths.resolve_homes()
        self.validate.side_effect = self._parse
        self.assertEqual(paths.resolve_homes()[0], self.root / "new")
        self.assertEqual(self.validate.call_count, 2)

    def test_an_a_b_a_swap_during_validation_recovers_on_the_next_call(self):
        a, b = _setting(str(self.root / "a")), _setting(str(self.root / "b"))
        self._write(a)

        def save(text):
            staged = self.home / "config.yaml.stage"
            staged.write_text(text, encoding="utf-8")
            os.replace(staged, self.config_path)

        def swapping(path):
            # Two atomic saves: the validator opens B, the file reads A both
            # before and after it.
            save(b)
            try:
                return self._parse(path)
            finally:
                save(a)

        self.validate.side_effect = swapping
        with self.assertRaises(paths.RuntimeBindingError):
            # The parse names `b`, the effective read sees `a`.
            paths.resolve_homes()
        self.validate.side_effect = self._parse
        for _ in range(3):
            self.assertEqual(paths.resolve_homes()[0], self.root / "a")
        # B's parse was never published under A: the first stable call parses
        # A once, and that parse is what later calls reuse.
        self.assertEqual(self.validate.call_count, 2)

    def test_without_the_host_yaml_reader_nothing_is_published(self):
        self._write(_setting(str(self.root / "store")))
        with patch_modules({"hermes_yaml": None}):
            for _ in range(3):
                self.assertEqual(paths.resolve_homes()[0], self.root / "store")
        self.assertEqual(self.validate.call_count, 3)

    def test_path_alias_is_resolved_live_under_unchanged_config(self):
        first, second, alias = self.root / "first", self.root / "second", self.root / "alias"
        first.mkdir()
        second.mkdir()
        alias.symlink_to(first)
        self._write(_setting(str(alias)))
        self.assertEqual(paths.resolve_homes()[0], first)
        alias.unlink()
        alias.symlink_to(second)
        self.assertEqual(paths.resolve_homes()[0], second)
        self.assertEqual(self.validate.call_count, 1)

    def test_relative_launch_fallback_follows_the_working_directory(self):
        os.environ["OMH_HOME"] = "relative-store"
        one, two = self.root / "one", self.root / "two"
        one.mkdir()
        two.mkdir()
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(one)
        self.modules["agent.secret_scope"].get_secret = lambda name, default=None: os.environ.get(name, default)
        self.assertEqual(paths.resolve_homes()[0], one / "relative-store")
        os.chdir(two)
        self.assertEqual(paths.resolve_homes()[0], two / "relative-store")

    def test_secret_ownership_is_rechecked_on_every_call(self):
        store = self.root / "store"
        self.scope = {"OMH_HOME": str(store)}
        self.owned = {"OMH_HOME": str(store)}
        self.assertEqual(paths.resolve_homes()[0], store)
        # Same bound scope, but the profile no longer owns that value.
        self.owned = {"OMH_HOME": str(self.root / "elsewhere")}
        with self.assertRaises(paths.RuntimeBindingError):
            paths.resolve_homes()

    def test_concurrent_cold_calls_parse_once(self):
        self._write(_setting(str(self.root / "store")))

        def slow(path):
            time.sleep(0.05)
            return self._parse(path)

        self.validate.side_effect = slow
        start = threading.Barrier(6)
        results, errors = [], []

        def call():
            start.wait()
            try:
                results.append(paths.resolve_homes())
            except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
                errors.append(exc)

        threads = [threading.Thread(target=call) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(set(results), {(self.root / "store", self.home)})
        self.assertEqual(self.validate.call_count, 1)

    def test_distinct_profiles_keep_separate_entries_and_the_memo_is_bounded(self):
        for index in range(paths._VALIDATED_CONFIG_MAX + 3):
            home = self.root / f"profile-{index}"
            home.mkdir()
            (home / "config.yaml").write_text(_setting(str(self.root / f"store-{index}")), encoding="utf-8")
            raw = paths._validated_config(self.modules["hermes_cli.config"], home / "config.yaml")
            self.assertEqual(raw["plugins"]["entries"]["omh"]["settings"]["omh_home"], str(self.root / f"store-{index}"))
        self.assertLessEqual(len(paths._VALIDATED_CONFIG), paths._VALIDATED_CONFIG_MAX)

    def test_the_memo_holds_a_digest_not_the_file_bytes(self):
        self._write(_setting(str(self.root / "store")))
        paths.resolve_homes()
        (entry,) = paths._VALIDATED_CONFIG.values()
        self.assertNotIn(self.config_path.read_bytes(), entry)
        self.assertEqual(len(entry[1]), 32)


if __name__ == "__main__":
    unittest.main()
