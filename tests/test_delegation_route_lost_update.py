"""Regression: a route write must not drop unrelated config keys (#2998).

`hermes config set` (the Hermes Agent CLI, outside OMH's lock) can add an
unrelated key between the route writer's validation snapshot and its rename.
The pre-fix writer replaced the file from the stale snapshot and silently
dropped the key: the observed case was `context_file_max_chars` reset to
unset, repeatedly. The fix re-reads the latest config and re-applies only
the delegation delta just before the rename, and skips byte-identical
writes, so the needless per-dispatch rewrite is gone too.

Every test passes an explicit temporary home. Nothing here may read or
write the developer's own `~/.hermes` or `~/.omh`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omh.plugin_bundle.omh import delegation_routing
from omh.plugin_bundle.omh.delegation_routing import write_delegation_route


class RouteWriteLostUpdateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "home"
        self.home.mkdir()
        self.config = self.home / "config.yaml"

    def _write_config(self, text: str) -> None:
        self.config.write_text(text, encoding="utf-8")

    def test_skip_byte_identical(self):
        text = (
            "context_file_max_chars: 60000\n"
            "delegation:\n"
            "  model: 'm1'\n"
            "  provider: 'p1'\n"
        )
        self._write_config(text)
        inode_before = self.config.stat().st_ino
        result = write_delegation_route(self.home, model="m1", provider="p1")
        self.assertEqual(result["status"], "routed")
        self.assertEqual(self.config.stat().st_ino, inode_before)
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_concurrent_pin_preserved(self):
        no_pin = "delegation:\n  model: 'm1'\n  provider: 'p1'\n"
        self._write_config(no_pin)
        real_read = delegation_routing._read_config_snapshot
        calls = {"n": 0}

        def racing_read(path):
            calls["n"] += 1
            if calls["n"] == 2:
                # A concurrent `hermes config set` adds the pin after the
                # validation snapshot but before the write's fresh read.
                self._write_config("context_file_max_chars: 60000\n" + no_pin)
            return real_read(path)

        with mock.patch.object(
            delegation_routing, "_read_config_snapshot", racing_read
        ):
            result = write_delegation_route(self.home, model="m2", provider="p1")
        self.assertEqual(result["status"], "routed")
        final = self.config.read_text(encoding="utf-8")
        self.assertIn("context_file_max_chars: 60000", final)
        self.assertIn("model: 'm2'", final)

    def test_unrelated_bytes_preserved(self):
        text = (
            "# comment\n"
            "context_file_max_chars: 60000\n"
            "model:\n"
            "  default: 'main'\n"
            "delegation:\n"
            "  model: 'm1'\n"
            "  base_url: 'http://x'\n"
        )
        self._write_config(text)
        result = write_delegation_route(
            self.home, model="m2", provider="p2", reasoning_effort="high"
        )
        self.assertEqual(result["status"], "routed")
        final = self.config.read_text(encoding="utf-8")
        for needle in (
            "context_file_max_chars: 60000",
            "# comment",
            "default: 'main'",
            "model: 'm2'",
            "provider: 'p2'",
            "reasoning_effort: 'high'",
            "base_url: 'http://x'",
        ):
            self.assertIn(needle, final)

    def test_clear_removes_only_routable_keys(self):
        text = (
            "context_file_max_chars: 60000\n"
            "delegation:\n"
            "  model: 'm1'\n"
            "  provider: 'p1'\n"
        )
        self._write_config(text)
        result = write_delegation_route(self.home, clear=True)
        self.assertEqual(result["status"], "cleared")
        final = self.config.read_text(encoding="utf-8")
        self.assertIn("context_file_max_chars: 60000", final)
        self.assertNotIn("model: 'm1'", final)
        self.assertNotIn("provider: 'p1'", final)


if __name__ == "__main__":
    unittest.main()
