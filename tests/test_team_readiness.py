from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.paths import resolve_paths
from omh.runtime_artifacts import write_runtime_observation
from omh.team_readiness import build_team_worker_readiness
from omh.wrapper_sessions import (
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)


class TeamReadinessTests(unittest.TestCase):
    def test_not_observed_runtime_record_does_not_count_as_observed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_id = _runtime_session(paths, source_event_id="not-observed")
            session_dir = paths.runtime_wrapper_sessions_dir / session_id

            write_runtime_observation(
                session_dir,
                {
                    "target_type": "wrapper_session",
                    "target_id": session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": "runtime_start",
                    "status": "not_observed",
                },
            )

            readiness = build_team_worker_readiness(paths, target_limit=None)
            observed = readiness["observed_runtime"]

            self.assertEqual(observed["status"], "not_observed")
            self.assertEqual(observed["record_count"], 1)
            self.assertEqual(observed["observed_events"], [])
            self.assertEqual(observed["next_action"], "record_runtime_observation:runtime_start")
            self.assertEqual(observed["worker_event_count"], 0)

    def test_latest_worker_event_uses_updated_at_not_scan_order(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            new_session_id = _runtime_session(paths, source_event_id="new")
            old_session_id = _runtime_session(paths, source_event_id="old")

            write_runtime_observation(
                paths.runtime_wrapper_sessions_dir / new_session_id,
                {
                    "target_type": "wrapper_session",
                    "target_id": new_session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": "worker_dispatch",
                    "status": "observed",
                    "worker_ref": "new-worker",
                    "summary": "newer worker dispatch",
                    "updated_at": "2026-06-20T10:00:00Z",
                },
            )
            write_runtime_observation(
                paths.runtime_wrapper_sessions_dir / old_session_id,
                {
                    "target_type": "wrapper_session",
                    "target_id": old_session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": "worker_dispatch",
                    "status": "observed",
                    "worker_ref": "old-worker",
                    "summary": "older worker dispatch written later",
                    "updated_at": "2026-06-19T10:00:00Z",
                },
            )

            readiness = build_team_worker_readiness(paths, target_limit=None)
            observed = readiness["observed_runtime"]

            self.assertEqual(observed["status"], "observed")
            self.assertEqual(observed["latest_worker_events"]["worker_dispatch"]["worker_ref"], "new-worker")
            self.assertEqual(observed["latest_worker_events"]["worker_dispatch"]["summary"], "newer worker dispatch")

    def test_newer_not_observed_event_overrides_older_observed_event(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            old_session_id = _runtime_session(paths, source_event_id="old-observed")
            new_session_id = _runtime_session(paths, source_event_id="new-not-observed")

            write_runtime_observation(
                paths.runtime_wrapper_sessions_dir / old_session_id,
                {
                    "target_type": "wrapper_session",
                    "target_id": old_session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": "runtime_start",
                    "status": "observed",
                    "summary": "older observed runtime start",
                    "updated_at": "2026-06-20T10:00:00Z",
                },
            )
            write_runtime_observation(
                paths.runtime_wrapper_sessions_dir / new_session_id,
                {
                    "target_type": "wrapper_session",
                    "target_id": new_session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": "runtime_start",
                    "status": "not_observed",
                    "summary": "newer check found no runtime start yet",
                    "updated_at": "2026-06-20T11:00:00Z",
                },
            )

            readiness = build_team_worker_readiness(paths, target_limit=None)
            observed = readiness["observed_runtime"]

            self.assertEqual(observed["status"], "not_observed")
            self.assertEqual(observed["observed_events"], [])
            self.assertEqual(observed["next_action"], "record_runtime_observation:runtime_start")

    def test_default_scan_keeps_recent_observation_on_older_target(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            old_session_id = _runtime_session(paths, source_event_id="old-target")
            old_session_dir = paths.runtime_wrapper_sessions_dir / old_session_id
            old_session_json = old_session_dir / "session.json"
            write_runtime_observation(
                old_session_dir,
                {
                    "target_type": "wrapper_session",
                    "target_id": old_session_id,
                    "runtime_profile": "omx-runtime",
                    "event_type": "worker_dispatch",
                    "status": "observed",
                    "worker_ref": "recent-worker",
                    "summary": "recent observation on an old target",
                    "updated_at": "2026-06-20T12:00:00Z",
                },
            )

            old_metadata_time = 1_766_000_000_000_000_000
            newer_metadata_time = old_metadata_time + 1_000_000_000
            recent_observation_time = newer_metadata_time + 1_000_000_000
            os.utime(old_session_json, ns=(old_metadata_time, old_metadata_time))
            os.utime(
                old_session_dir / "runtime_observations.jsonl",
                ns=(recent_observation_time, recent_observation_time),
            )
            for index in range(55):
                session_id = _runtime_session(paths, source_event_id=f"newer-target-{index}")
                session_json = paths.runtime_wrapper_sessions_dir / session_id / "session.json"
                timestamp = newer_metadata_time + index
                os.utime(session_json, ns=(timestamp, timestamp))

            readiness = build_team_worker_readiness(paths)
            observed = readiness["observed_runtime"]

            self.assertTrue(observed["scan_truncated"])
            self.assertEqual(observed["latest_worker_events"]["worker_dispatch"]["worker_ref"], "recent-worker")
            self.assertEqual(observed["worker_event_count"], 1)

    def test_malformed_target_metadata_is_reported_without_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            malformed_dir = paths.runtime_wrapper_sessions_dir / "malformed"
            malformed_dir.mkdir(parents=True)
            malformed_json = malformed_dir / "session.json"
            malformed_json.write_text("{not json", encoding="utf-8")

            readiness = build_team_worker_readiness(paths, target_limit=None)
            observed = readiness["observed_runtime"]

            self.assertEqual(observed["status"], "not_observed")
            self.assertEqual(observed["record_count"], 0)
            self.assertTrue(any("malformed" in error for error in observed["errors"]))


def _runtime_session(paths, *, source_event_id: str) -> str:
    started = create_or_resume_wrapper_session(
        paths,
        "risky refactor",
        source="discord",
        source_metadata={"source_event_id": source_event_id, "channel_ref": "c1"},
    )
    session_id = str(started["session"]["session_id"])
    record_plan_decision(paths, session_id, "accept")
    select_wrapper_session_executor(paths, session_id, "omx-runtime")
    prepare_wrapper_session_handoff(paths, session_id, "risky refactor")
    return session_id


if __name__ == "__main__":
    unittest.main()
