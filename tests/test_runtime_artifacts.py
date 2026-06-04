from __future__ import annotations

import json
import os
import stat
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths
from omh.runtime_artifacts import (
    create_run,
    export_runtime,
    list_runs,
    new_run_id,
    show_run,
    update_state,
    validate_runtime,
    validate_run_record,
    write_delegation,
    write_wrapper_contract,
)


class RuntimeArtifactTests(unittest.TestCase):
    def test_new_run_id_is_stable_and_slugged(self) -> None:
        now = datetime(2026, 6, 4, 12, 1, 2, tzinfo=timezone.utc)

        self.assertEqual(new_run_id(now, "Coding Handling!"), "20260604T120102000000Z-coding-handling")

    def test_create_run_writes_run_events_and_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})

            run_dir = paths.runtime_runs_dir / run["run_id"]
            self.assertTrue((run_dir / "run.json").exists())
            self.assertTrue((run_dir / "events.jsonl").exists())
            self.assertTrue((run_dir / "evidence").is_dir())
            self.assertEqual(json.loads(paths.runtime_state_path.read_text(encoding="utf-8"))["last_run_id"], run["run_id"])
            self.assertEqual(list_runs(paths)[0]["run_id"], run["run_id"])
            self.assertEqual(validate_run_record(run), [])

    def test_create_run_does_not_collide_for_rapid_same_harness_records(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            first = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            second = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})

            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertEqual(len(list_runs(paths)), 2)

    @unittest.skipUnless(hasattr(os, "umask"), "permission checks require POSIX-like mode bits")
    def test_runtime_artifacts_are_private_even_with_permissive_umask(self) -> None:
        with TemporaryDirectory() as tmp:
            old_umask = os.umask(0o022)
            try:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            finally:
                os.umask(old_umask)

            run_dir = paths.runtime_runs_dir / run["run_id"]
            self.assertEqual(stat.S_IMODE(paths.runtime_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((run_dir / "run.json").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((run_dir / "events.jsonl").stat().st_mode), 0o600)

    def test_write_delegation_preserves_observed_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "critic", "status": "completed"})

            delegation = write_delegation(
                paths.runtime_runs_dir / run["run_id"],
                {"requested": True, "observed": False, "result": "not_observed", "evidence_refs": ["run.json"]},
            )

            self.assertTrue(delegation["requested"])
            self.assertFalse(delegation["observed"])
            shown = show_run(paths, run["run_id"])
            self.assertEqual(shown["delegation"]["result"], "not_observed")

    def test_write_delegation_rejects_contradictory_observation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "critic", "status": "completed"})

            with self.assertRaises(ValueError):
                write_delegation(paths.runtime_runs_dir / run["run_id"], {"observed": True, "result": "not_observed"})
            with self.assertRaises(ValueError):
                write_delegation(paths.runtime_runs_dir / run["run_id"], {"observed": False, "result": "completed"})

    def test_write_wrapper_contract_records_observed_boundaries(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})

            wrapper = write_wrapper_contract(
                paths.runtime_runs_dir / run["run_id"],
                {
                    "prompt_dispatched": True,
                    "hermes_response_observed": True,
                    "verification_observed": False,
                    "completion_status": "blocked",
                    "unobserved_gaps": ["separate specialist lane not exposed"],
                },
            )

            self.assertTrue(wrapper["prompt_dispatched"])
            self.assertFalse(wrapper["verification_observed"])
            shown = show_run(paths, run["run_id"])
            self.assertEqual(shown["wrapper"]["completion_status"], "blocked")
            self.assertIn("wrapper_contract_recorded", {event["event"] for event in shown["events"]})

    def test_validate_runtime_rejects_missing_and_invalid_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            good = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})

            self.assertTrue(validate_runtime(paths, good["run_id"])["ok"])

            bad_dir = paths.runtime_runs_dir / "bad-run"
            bad_dir.mkdir(parents=True)
            (bad_dir / "run.json").write_text('{"schema_version": 1, "run_id": "bad-run", "status": "bogus"}', encoding="utf-8")
            (bad_dir / "events.jsonl").write_text('{"schema_version": 1, "timestamp": "now", "event": "x", "level": "bad", "message": ""}\n', encoding="utf-8")

            result = validate_runtime(paths)
            self.assertFalse(result["ok"])
            bad = next(item for item in result["runs"] if item["run_id"] == "bad-run")
            self.assertTrue(any("status is invalid" in error for error in bad["errors"]))
            self.assertTrue(any("event level is invalid" in error for error in bad["errors"]))

    def test_export_runtime_redacts_sensitive_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            write_wrapper_contract(
                paths.runtime_runs_dir / run["run_id"],
                {
                    "prompt_dispatched": True,
                    "completion_status": "completed",
                    "message": "safe summary",
                    "prompt_body": "do not export",
                },
            )

            exported = export_runtime(paths, redacted=True)

            self.assertTrue(exported["redacted"])
            self.assertEqual(exported["runs"][0]["wrapper"]["message"], "safe summary")
            self.assertNotIn("do not export", json.dumps(exported))

    def test_update_state_merges_patch(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            update_state(paths, {"installed_skills": 18})
            state = update_state(paths, {"last_run_id": "r1"})

            self.assertEqual(state["installed_skills"], 18)
            self.assertEqual(state["last_run_id"], "r1")


if __name__ == "__main__":
    unittest.main()
