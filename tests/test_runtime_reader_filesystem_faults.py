"""Filesystem-fault behaviour of `plugin_bundle/omh/runtime_reader.py`.

PR #654 stopped `pre_llm_call` from reading a failed status read as a host with
nothing to report: the broad handler now records a `runtime_status_read`
degradation. That handler only helps if the reader below it does not quietly
turn a fault into an empty result first, so this module pins the reader's
behaviour per filesystem call site, forcing the real condition rather than
mocking it.

Two shapes are proved here, and the difference between them is the point:

* Directory enumeration (`read_omh_status` runs, executor-progress bindings)
  must tell "nothing has been written yet" apart from "cannot be read". The
  first is a routine empty state and returns `[]`. The second propagates, so
  the classifying handler sees it. `Path.glob` cannot express that split --
  it swallows the `os.scandir` `OSError` and yields nothing either way --
  which is why `_child_files` reads with an API that propagates.

* `_expand_path` and the plugin role-catalog probe are deliberately left
  unguarded. Their tests are here to prove those decisions still hold, not to
  record a gap; each explains why below.

Skipped rather than faked where the mechanism is not reproducible: POSIX
permission bits do not restrict root, and neither `chmod` nor symlink loops
behave the same off POSIX.
"""

from __future__ import annotations

import json
import os
import unittest
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.degradation import COMPONENT_RUNTIME_STATUS_READ
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
from omh.plugin_bundle.omh.runtime_reader import read_omh_hud, read_omh_status

BINDING_SCHEMA_VERSION = "omh_executor_progress_binding/v1"

requires_posix_permissions = unittest.skipUnless(
    os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0,
    "POSIX permission bits do not restrict root and do not exist off POSIX",
)
requires_symlinks = unittest.skipUnless(
    os.name == "posix",
    "symlink-loop resolution differs off POSIX",
)


@contextmanager
def unreadable(directory: Path) -> Iterator[Path]:
    """Make `directory` unreadable, restoring the mode so cleanup can run."""
    original = directory.stat().st_mode
    os.chmod(directory, 0o000)
    try:
        yield directory
    finally:
        os.chmod(directory, original)


def write_run(runs_dir: Path, run_id: str) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "phase": "planned"}), encoding="utf-8")


def write_binding(root: Path, target_id: str, target_type: str) -> None:
    progress_dir = root / target_id / "executor_progress"
    progress_dir.mkdir(parents=True)
    (progress_dir / "binding.json").write_text(
        json.dumps(
            {
                "schema_version": BINDING_SCHEMA_VERSION,
                "binding_id": f"{target_type}:{target_id}:codex",
                "instance_id": "instance-1",
                "target_type": target_type,
                "target_id": target_id,
                "executor_profile": "codex",
                "correlation_root": "correlation-1",
                "state": "active",
                "claim_boundary": "progress signal, not result evidence",
            }
        ),
        encoding="utf-8",
    )


class RunEnumerationFaultTests(unittest.TestCase):
    """`read_omh_status` runs: absence is empty, unreadable is a fault."""

    def test_missing_runs_directory_is_a_routine_empty_state(self) -> None:
        with TemporaryDirectory() as tmp:
            status = read_omh_status(Path(tmp) / ".omh")

            self.assertEqual(status["runs"], [])
            self.assertFalse(status["runtime_state_present"])

    def test_readable_runs_directory_still_summarizes_its_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / ".omh" / "runtime" / "runs"
            write_run(runs_dir, "run-a")
            write_run(runs_dir, "run-b")

            status = read_omh_status(Path(tmp) / ".omh")

            self.assertEqual([run["run_id"] for run in status["runs"]], ["run-b", "run-a"])

    @requires_posix_permissions
    def test_unreadable_runs_directory_propagates_instead_of_reporting_no_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / ".omh" / "runtime" / "runs"
            write_run(runs_dir, "run-a")

            with unreadable(runs_dir):
                with self.assertRaises(PermissionError):
                    read_omh_status(Path(tmp) / ".omh")

    @requires_posix_permissions
    def test_unreadable_runs_directory_is_not_reported_as_an_empty_one(self) -> None:
        # The regression this guards: the fault and the routine empty state
        # used to produce byte-identical payloads, so a caller reading `runs`
        # could not tell them apart.
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            empty_runs = home / "runtime" / "runs"
            empty_runs.mkdir(parents=True)
            empty_status = read_omh_status(home)

            with unreadable(empty_runs):
                with self.assertRaises(PermissionError):
                    read_omh_status(home)

            self.assertEqual(empty_status["runs"], [])


class ProgressBindingEnumerationFaultTests(unittest.TestCase):
    """Executor-progress roots carry the same split as the runs directory."""

    def test_missing_wrapper_sessions_directory_is_a_routine_empty_state(self) -> None:
        with TemporaryDirectory() as tmp:
            status = read_omh_status(Path(tmp) / ".omh")

            self.assertEqual(status["active_executors"], [])
            self.assertEqual(status["stale_executors"], [])

    @requires_posix_permissions
    def test_unreadable_wrapper_sessions_directory_propagates(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / ".omh" / "runtime"
            sessions_dir = runtime_dir / "wrapper_sessions"
            write_binding(sessions_dir, "session-a", "wrapper_session")

            with unreadable(sessions_dir):
                with self.assertRaises(PermissionError):
                    read_omh_status(Path(tmp) / ".omh")

    @requires_posix_permissions
    def test_unreadable_progress_root_is_not_reported_as_no_active_executors(self) -> None:
        # An executor mid-flight must never read as "nothing is running"
        # because the directory holding its binding could not be opened.
        with TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / ".omh" / "runtime"
            sessions_dir = runtime_dir / "wrapper_sessions"
            sessions_dir.mkdir(parents=True)
            empty_status = read_omh_status(Path(tmp) / ".omh")

            with unreadable(sessions_dir):
                with self.assertRaises(PermissionError):
                    read_omh_status(Path(tmp) / ".omh")

            self.assertEqual(empty_status["active_executors"], [])


class ClassifyingHandlerReachTests(unittest.TestCase):
    """Every propagated fault must land in `pre_llm_call`'s classifier."""

    def call_pre_llm(self, omh_home: Path, hermes_home: Path) -> dict | None:
        return pre_llm_call(
            omh_home=str(omh_home),
            hermes_home=str(hermes_home),
            user_message="unrelated message",
            is_first_turn=False,
            include_omh_awareness=False,
        )

    def assert_status_read_degradation(self, payload: dict | None, error_type: str) -> None:
        self.assertIsNotNone(payload)
        assert payload is not None
        block = payload["omh_degradation"]
        self.assertEqual(
            block["components"],
            [{"component": COMPONENT_RUNTIME_STATUS_READ, "error_type": error_type}],
        )
        self.assertIn("[OMH Degraded] components=", str(payload["context"]))

    def test_idle_host_still_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(self.call_pre_llm(Path(tmp) / ".omh", Path(tmp) / ".hermes"))

    @requires_posix_permissions
    def test_unreadable_runs_directory_is_classified_not_read_as_idle(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            runs_dir = home / "runtime" / "runs"
            write_run(runs_dir, "run-a")

            with unreadable(runs_dir):
                payload = self.call_pre_llm(home, Path(tmp) / ".hermes")

            self.assert_status_read_degradation(payload, "PermissionError")

    @requires_symlinks
    def test_symlink_loop_home_is_classified_not_read_as_idle(self) -> None:
        # Deliberately not narrowed at `_expand_path`. That function must
        # return a `Path`, and every fallback path it could invent would send
        # the reads below it somewhere else -- where they all find nothing and
        # report a healthy idle host. Propagating is the only answer that
        # keeps the fault visible.
        with TemporaryDirectory() as tmp:
            loop = Path(tmp) / "loop"
            loop.symlink_to(loop)

            with self.assertRaises((OSError, RuntimeError)):
                read_omh_status(loop)

            payload = self.call_pre_llm(loop, Path(tmp) / ".hermes")

            self.assert_status_read_degradation(payload, "RuntimeError")

    @requires_symlinks
    def test_either_home_fault_stops_all_scoped_io_before_awareness(self) -> None:
        from unittest.mock import patch
        from omh.plugin_bundle.omh.hooks import llm_hooks

        with TemporaryDirectory() as tmp:
            loop = Path(tmp) / "private-loop"
            loop.symlink_to(loop)
            for home_key in ("omh_home", "hermes_home"):
                for awareness in (False, True):
                    with self.subTest(home=home_key, awareness=awareness):
                        homes = {"omh_home": str(Path(tmp) / ".omh"), "hermes_home": str(Path(tmp) / ".hermes")}
                        homes[home_key] = str(loop)
                        with (
                            patch.object(llm_hooks, "record_approval_bypass") as approval,
                            patch.object(llm_hooks, "read_running_work_board") as board,
                            patch.object(llm_hooks, "_record_delivery") as delivery,
                            patch.object(llm_hooks, "observe_plugin_hook_call") as observation,
                        ):
                            payload = pre_llm_call(
                                **homes, user_message="fix the GitHub PR", is_first_turn=True,
                                include_omh_awareness=awareness,
                            )
                        self.assert_status_read_degradation(payload, "RuntimeError")
                        self.assertNotIn(str(loop), str(payload))
                        for downstream in (approval, board, delivery, observation):
                            downstream.assert_not_called()


class RoleCatalogProbeTests(unittest.TestCase):
    """The role-catalog probe is deliberately left tolerant."""

    @requires_posix_permissions
    def test_unreadable_role_catalog_reports_the_capability_as_unavailable(self) -> None:
        # Unlike the enumeration sites, the tolerant answer here is the
        # accurate one: a role catalog the process cannot read really does
        # make the role-dependent tools unusable, and the HUD says so. The
        # defect shape would be a false `ready`, not this. Raising instead
        # would take down the whole HUD read over one degraded sub-capability.
        with TemporaryDirectory() as tmp:
            hermes_home = Path(tmp) / ".hermes"
            references = hermes_home / "plugins" / "omh" / "references"
            references.mkdir(parents=True)
            (references / "role-executor.md").write_text("role", encoding="utf-8")

            with unreadable(references):
                payload = read_omh_hud(Path(tmp) / ".omh", hermes_home)

            self.assertFalse(payload["plugin"]["capabilities"]["files"]["role_catalog"])
            self.assertNotEqual(payload["plugin"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
