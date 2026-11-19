"""The readiness probe reports every PATH resolution, pinned to no version.

Users update codex and claude on their own cadence and through more than one
installer, so binaries of different versions routinely coexist on PATH.
Observed live: a stale npm codex 0.144.5 resolved first and probed "ready"
while the standalone 0.145.0 the auth session actually required sat one PATH
entry later -- `shutil.which` answers only "what will run", so the newer
install was invisible and the dispatch failed mid-flight.

The structural rule these pin: OMH never compares an executor version against
an expectation of its own. It observes what each resolution prints and says
when the binary that will run is not the only one installed.
"""

from __future__ import annotations

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package
from _platform_support import requires_posix

load_local_package()
from omh.coding.executor_readiness import (
    EXECUTOR_VERSION_POLICY,
    _COMMANDS,
    _executor_readiness_contract_cached,
    _run_probe,
    executor_readiness_contract,
)
from omh.coding.fanout_dispatch import PI_FAMILY_HOST_CANDIDATES
from omh.coding.pi_family_interop import PI_DISTRIBUTION_HOST, PI_FORK_HOST


def _fake_binary(directory: str, name: str, version: str) -> Path:
    path = Path(directory) / name
    path.write_text(f"#!/bin/sh\necho 'codex-cli {version}'\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@requires_posix
class PathResolutionReportTests(unittest.TestCase):
    def _probe(self, path_value: str) -> dict:
        with patch.dict(os.environ, {"PATH": path_value}):
            return _run_probe(dict(executor_readiness_contract("codex")))

    def test_a_stale_binary_shadowing_a_newer_one_is_reported(self) -> None:
        # The live failure, reproduced: first-on-PATH is old, newer sits behind.
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            _fake_binary(first, "codex", "0.144.5")
            _fake_binary(second, "codex", "0.145.0")
            result = self._probe(os.pathsep.join([first, second]))

            self.assertTrue(result["shadowed"])
            versions = [row["observed_version"] for row in result["path_resolutions"]]
            self.assertEqual(versions, ["codex-cli 0.144.5", "codex-cli 0.145.0"])
            # The stale one is still what runs, so status stays honest...
            self.assertEqual(result["status"], "ready")
            # ...and the summary names the alternative instead of hiding it.
            self.assertIn("0.145.0", result["summary"])
            self.assertIn("PATH also resolves", result["summary"])

    def test_a_single_binary_reports_no_shadow(self) -> None:
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "0.145.0")
            result = self._probe(only)
            self.assertFalse(result["shadowed"])
            self.assertEqual(len(result["path_resolutions"]), 1)
            self.assertNotIn("PATH also resolves", result["summary"])

    def test_a_symlink_to_the_same_binary_is_not_a_conflict(self) -> None:
        # Dedup is by real path: standalone installs symlink through a
        # `current` pointer, and a chain to one binary is one binary.
        with TemporaryDirectory() as real_dir, TemporaryDirectory() as link_dir:
            real = _fake_binary(real_dir, "codex", "0.145.0")
            (Path(link_dir) / "codex").symlink_to(real)
            result = self._probe(os.pathsep.join([link_dir, real_dir]))
            self.assertFalse(result["shadowed"])
            self.assertEqual(len(result["path_resolutions"]), 1)

    def test_same_version_in_two_places_is_not_flagged_as_shadowed(self) -> None:
        # Two distinct binaries printing the same version disagree about
        # nothing a user must resolve; flagging them would train people to
        # ignore the flag.
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            _fake_binary(first, "codex", "0.145.0")
            _fake_binary(second, "codex", "0.145.0")
            result = self._probe(os.pathsep.join([first, second]))
            self.assertFalse(result["shadowed"])

    def test_the_probe_carries_the_no_pinned_version_policy(self) -> None:
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "9.9.9")
            result = self._probe(only)
            self.assertEqual(result["version_policy"], EXECUTOR_VERSION_POLICY)
            # A future version OMH has never seen probes ready: nothing in the
            # contract encodes an expected version to fall behind.
            self.assertEqual(result["status"], "ready")

    def test_a_ready_probe_says_it_observed_only_the_binary_version(self) -> None:
        # The 2026-09-11 gap: `available: true` was read as "this executor can
        # do the work". The probe has no worktree, so it cannot have observed
        # anything about one, and the payload has to say that out loud.
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "0.145.0")
            result = self._probe(only)

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["available"])
            self.assertEqual(result["observed"], "binary_version_only")
            self.assertIn("workspace not yet probed", result["summary"])
            self.assertIn("workspace_preflight", result["summary"])
            self.assertIn("workspace_preflight", result["claim_boundary"])
            self.assertIn("is not a claim that the work can be done", result["claim_boundary"])
            # The observed version line is still there; the qualification is
            # appended to it rather than replacing it.
            self.assertIn("0.145.0", result["summary"])

    def test_a_missing_binary_also_states_what_was_observed(self) -> None:
        with TemporaryDirectory() as empty:
            result = self._probe(empty)

            self.assertEqual(result["status"], "missing")
            self.assertEqual(result["observed"], "binary_version_only")

    def test_no_source_line_hardcodes_an_executor_version(self) -> None:
        # The guard for the structural rule itself: the module may print
        # versions it observed, never carry one of its own.
        import inspect

        import omh.coding.executor_readiness as module

        source = inspect.getsource(module)
        for literal in ("0.144", "0.145", "2.1.2"):
            self.assertNotIn(literal, source)


class OmoRuntimeProbeCommandTests(unittest.TestCase):
    """pi-family-runtime readiness probes the DETECTED host CLI, pi-first.

    The static `_COMMANDS` entry is a mirror of the first host candidate,
    never the resolution authority: `_resolved_command` always asks
    `pi_family_host` which host is actually on PATH.
    """

    def setUp(self) -> None:
        _executor_readiness_contract_cached.cache_clear()
        self.addCleanup(_executor_readiness_contract_cached.cache_clear)

    def test_contract_probes_the_detected_host_pi_first(self) -> None:
        with patch(
            "omh.coding.fanout_dispatch.shutil.which",
            lambda name: f"/x/{name}" if name in ("pi", PI_DISTRIBUTION_HOST) else None,
        ):
            contract = executor_readiness_contract("pi-family-runtime")
        self.assertEqual(contract["probe"]["command"], "pi")

    def test_detected_pi_distribution_host_overrides_the_static_entry(self) -> None:
        with patch(
            "omh.coding.fanout_dispatch.shutil.which",
            lambda name: f"/x/{PI_DISTRIBUTION_HOST}" if name == PI_DISTRIBUTION_HOST else None,
        ):
            contract = executor_readiness_contract("pi-family-runtime")
        self.assertEqual(contract["probe"]["command"], PI_DISTRIBUTION_HOST)

    def test_detected_fork_host_is_probed_by_its_own_name(self) -> None:
        with patch(
            "omh.coding.fanout_dispatch.shutil.which",
            lambda name: f"/x/{PI_FORK_HOST}" if name == PI_FORK_HOST else None,
        ):
            contract = executor_readiness_contract("pi-family-runtime")
        self.assertEqual(contract["probe"]["command"], PI_FORK_HOST)
        self.assertEqual(contract["probe"]["args"], ["--version"])

    def test_no_host_on_path_falls_back_to_the_first_candidate(self) -> None:
        with patch("omh.coding.fanout_dispatch.shutil.which", lambda name: None):
            contract = executor_readiness_contract("pi-family-runtime")
        self.assertEqual(contract["probe"]["command"], PI_FAMILY_HOST_CANDIDATES[0])
        self.assertEqual(contract["probe"]["command"], "pi")

    def test_static_command_entry_mirrors_the_first_host_candidate(self) -> None:
        # A future second consumer of `_COMMANDS` must see the same pi-first
        # default the detector promises; repinning the entry to one
        # distribution (the old distribution-host pin) fails here.
        self.assertEqual(_COMMANDS["pi-family-runtime"][0], PI_FAMILY_HOST_CANDIDATES[0])


if __name__ == "__main__":
    unittest.main()
