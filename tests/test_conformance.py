from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import build_coding_delegation_payload, coding_delegation_record_payload
from omh.conformance.checker import check_runtime_run
from omh.conformance.contract import ConformanceReport
from omh.paths import OmhPaths, resolve_paths
from omh.runtime_artifacts import (
    append_journal_observation,
    create_prepared_coding_delegation_run,
    write_ci_record,
    write_coding_delegation,
    write_delegation,
    write_merge_record,
    write_review_record,
    write_wrapper_contract,
)


class ConformanceTests(unittest.TestCase):
    def test_runtime_prepared_handoff_is_not_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _prepared_delegation_run(paths)

            report = check_runtime_run(paths, run_id)

            self.assertTrue(report["ok"])
            self.assertEqual(report["schema_version"], "omh_conformance_report/v1")
            self.assertEqual(report["subject"], {"type": "runtime_run", "id": run_id})
            self.assertEqual(report["claim_state"], "handoff_prepared")
            self.assertIn("handoff_prepared", report["allowed_claims"])
            self.assertIn("execution_observed", _blocked_claims(report))
            self.assertIn("validate_runtime", _evidence_sources(report))
            self.assertIn("summarize_delegated_coding_status", _evidence_sources(report))
            self.assertIn("Prepared", report["claim_boundary"])

    def test_runtime_execution_without_verification_blocks_verified_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _prepared_delegation_run(paths)
            _observe(paths, run_id, "executor_dispatch", "wrapper dispatched the handoff")
            _observe(paths, run_id, "executor_result", "executor reported completion")

            report = check_runtime_run(paths, run_id)

            self.assertEqual(report["claim_state"], "execution_observed")
            self.assertIn("executor_dispatched", report["allowed_claims"])
            self.assertIn("execution_observed", report["allowed_claims"])
            self.assertIn("verification_observed", _blocked_claims(report))
            self.assertNotIn("review_observed", report["allowed_claims"])

    def test_runtime_merge_ready_uses_existing_status_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _prepared_delegation_run(paths)
            run_dir = paths.runtime_runs_dir / run_id
            write_wrapper_contract(
                run_dir,
                {
                    "prompt_dispatched": True,
                    "hermes_response_observed": True,
                    "verification_observed": True,
                    "completion_status": "completed",
                },
            )
            write_delegation(run_dir, {"requested": True, "observed": True, "result": "completed"})
            write_review_record(run_dir, {"status": "passed", "reviewer": "code-review", "evidence_refs": ["review"]})
            write_ci_record(run_dir, {"status": "passed", "provider": "local", "checks": ["unit:passed"]})
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main", "evidence_refs": ["merge-ready"]})

            report = check_runtime_run(paths, run_id)

            self.assertEqual(report["claim_state"], "merge_ready")
            self.assertIn("merge_ready", report["allowed_claims"])
            self.assertIn("merged", _blocked_claims(report))
            self.assertEqual(report["next_action"], "report_merge_ready")
            self.assertIn("summarize_delegated_coding_status", _evidence_sources(report))

    def test_validation_failure_caps_safe_claims(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            run_id = _prepared_delegation_run(paths)
            run_dir = paths.runtime_runs_dir / run_id
            write_wrapper_contract(
                run_dir,
                {
                    "prompt_dispatched": True,
                    "hermes_response_observed": True,
                    "verification_observed": True,
                    "completion_status": "completed",
                },
            )
            write_delegation(run_dir, {"requested": True, "observed": True, "result": "completed"})
            write_review_record(run_dir, {"status": "passed", "reviewer": "code-review", "evidence_refs": ["review"]})
            write_ci_record(run_dir, {"status": "passed", "provider": "local", "checks": ["unit:passed"]})
            _corrupt_ci_checks(run_dir)
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main", "evidence_refs": ["merge-ready"]})

            report = check_runtime_run(paths, run_id)

            self.assertFalse(report["ok"])
            self.assertEqual(report["claim_state"], "metadata_available")
            self.assertEqual(report["allowed_claims"], ["metadata_available"])
            self.assertIn("handoff_prepared", _blocked_claims(report))
            self.assertIn("runtime validation failed", _blocked_reasons(report))
            self.assertNotIn("merge_ready", report["allowed_claims"])
            self.assertTrue(any("ci passed status requires at least one check" in violation for violation in report["violations"]))

            status, stdout, stderr = run_cli(
                ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home), "conformance", "check", "--run", run_id],
                output_json=False,
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            self.assertIn("Conformance result: invalid", stdout)
            self.assertIn("Allowed claim: metadata available", stdout)
            self.assertNotIn("Allowed claim: merge ready", stdout)

    def test_wrapper_session_validation_errors_are_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _prepared_delegation_run(paths)
            run_dir = paths.runtime_runs_dir / run_id
            write_wrapper_contract(
                run_dir,
                {
                    "prompt_dispatched": True,
                    "hermes_response_observed": True,
                    "verification_observed": True,
                    "completion_status": "completed",
                },
            )
            write_delegation(run_dir, {"requested": True, "observed": True, "result": "completed"})
            write_review_record(run_dir, {"status": "passed", "reviewer": "code-review", "evidence_refs": ["review"]})
            write_ci_record(run_dir, {"status": "passed", "provider": "local", "checks": ["unit:passed"]})
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main", "evidence_refs": ["merge-ready"]})
            _write_invalid_wrapper_session(paths, run_id)

            report = check_runtime_run(paths, run_id)

            self.assertFalse(report["ok"])
            self.assertEqual(report["claim_state"], "metadata_available")
            self.assertEqual(report["next_action"], "fix_validation_violations")
            self.assertIn("validation failed", report["safe_summary"])
            self.assertNotIn("ready to merge", report["safe_summary"])
            self.assertTrue(any("wrapper_session" in violation for violation in report["violations"]))

            status, stdout, stderr = run_cli(
                ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home), "conformance", "check", "--run", run_id],
                output_json=False,
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            self.assertIn("Next action: fix_validation_violations", stdout)
            self.assertNotIn("ready to merge", stdout)

    def test_malformed_wrapper_session_is_reported_as_validation_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _prepared_delegation_run(paths)
            run_dir = paths.runtime_runs_dir / run_id
            write_wrapper_contract(
                run_dir,
                {
                    "prompt_dispatched": True,
                    "hermes_response_observed": True,
                    "verification_observed": True,
                    "completion_status": "completed",
                },
            )
            write_delegation(run_dir, {"requested": True, "observed": True, "result": "completed"})
            write_review_record(run_dir, {"status": "passed", "reviewer": "code-review", "evidence_refs": ["review"]})
            write_ci_record(run_dir, {"status": "passed", "provider": "local", "checks": ["unit:passed"]})
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main", "evidence_refs": ["merge-ready"]})
            _write_malformed_wrapper_session(paths)

            report = check_runtime_run(paths, run_id)

            self.assertFalse(report["ok"])
            self.assertEqual(report["claim_state"], "metadata_available")
            self.assertEqual(report["next_action"], "fix_validation_violations")
            self.assertIn("validation failed", report["safe_summary"])
            self.assertNotIn("ready to merge", report["safe_summary"])
            self.assertTrue(any("session.json" in violation for violation in report["violations"]))

            status, stdout, stderr = run_cli(
                ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home), "conformance", "check", "--run", run_id],
                output_json=False,
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            self.assertIn("Conformance result: invalid", stdout)
            self.assertIn("Next action: fix_validation_violations", stdout)
            self.assertNotIn("ready to merge", stdout)

    def test_malformed_run_json_is_reported_as_validation_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _prepared_delegation_run(paths)
            run_dir = paths.runtime_runs_dir / run_id
            _write_malformed_json(run_dir / "run.json")

            report = check_runtime_run(paths, run_id)

            self.assertFalse(report["ok"])
            self.assertEqual(report["claim_state"], "metadata_available")
            self.assertEqual(report["allowed_claims"], ["metadata_available"])
            self.assertEqual(report["next_action"], "fix_validation_violations")
            self.assertTrue(any("run.json" in violation for violation in report["violations"]))

            status, stdout, stderr = run_cli(
                ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home), "conformance", "check", "--run", run_id],
                output_json=False,
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 1)
            self.assertIn("Conformance result: invalid", stdout)
            self.assertNotIn("Traceback", stdout)

    def test_malformed_run_owned_records_are_reported_as_validation_failure(self) -> None:
        for record_name in ("coding_delegation.json", "ci.json"):
            with self.subTest(record_name=record_name), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                run_id = _prepared_delegation_run(paths)
                run_dir = paths.runtime_runs_dir / run_id
                if record_name == "ci.json":
                    write_ci_record(run_dir, {"status": "passed", "provider": "local", "checks": ["unit:passed"]})
                _write_malformed_json(run_dir / record_name)

                report = check_runtime_run(paths, run_id)

                self.assertFalse(report["ok"])
                self.assertEqual(report["claim_state"], "metadata_available")
                self.assertEqual(report["allowed_claims"], ["metadata_available"])
                self.assertEqual(report["next_action"], "fix_validation_violations")
                self.assertTrue(any(record_name in violation for violation in report["violations"]))

    def test_conformance_checker_is_read_only(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run_id = _prepared_delegation_run(paths)
            before = _runtime_snapshot(paths.runtime_runs_dir)

            check_runtime_run(paths, run_id)

            self.assertEqual(_runtime_snapshot(paths.runtime_runs_dir), before)

    def test_conformance_cli_json_and_human_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            base = ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home)]
            status, stdout, stderr = run_cli(base + ["coding", "lifecycle", "start", "--record", "risky", "refactor"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["run"]["run_id"]

            status, stdout, stderr = run_cli(base + ["conformance", "check", "--run", run_id, "--json"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            report = json.loads(stdout)
            self.assertEqual(report["schema_version"], "omh_conformance_report/v1")
            self.assertEqual(report["claim_state"], "handoff_prepared")

            status, stdout, stderr = run_cli(
                base + ["conformance", "check", "--run", run_id],
                output_json=False,
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertIn(f"Conformance: runtime run {run_id}", stdout)
            self.assertIn("Allowed claim: handoff prepared", stdout)
            self.assertIn("Blocked claim: execution observed", stdout)


def _prepared_delegation_run(paths: OmhPaths) -> str:
    run = create_prepared_coding_delegation_run(paths, {"skill": "coding", "harness": "delegate"})
    run_dir = paths.runtime_runs_dir / run["run_id"]
    message = "implement safe conformance adapter without overclaiming"
    payload = build_coding_delegation_payload(message, source="discord", executor_target="codex")
    write_coding_delegation(run_dir, coding_delegation_record_payload(payload, message))
    return str(run["run_id"])


def _observe(paths: OmhPaths, run_id: str, event: str, summary: str) -> None:
    append_journal_observation(
        paths,
        {
            "target_type": "run",
            "target_id": run_id,
            "run_id": run_id,
            "event": event,
            "status": "observed",
            "summary": summary,
        },
    )


def _blocked_claims(report: ConformanceReport) -> set[str]:
    return {str(item["claim"]) for item in report["blocked_claims"]}


def _blocked_reasons(report: ConformanceReport) -> str:
    return "\n".join(str(item["reason"]) for item in report["blocked_claims"])


def _evidence_sources(report: ConformanceReport) -> set[str]:
    return {str(item["source"]) for item in report["evidence"]}


def _corrupt_ci_checks(run_dir: Path) -> None:
    ci_path = run_dir / "ci.json"
    ci_record = json.loads(ci_path.read_text(encoding="utf-8"))
    ci_record["checks"] = []
    ci_path.write_text(json.dumps(ci_record, sort_keys=True), encoding="utf-8")


def _write_invalid_wrapper_session(paths: OmhPaths, run_id: str) -> None:
    session_dir = paths.runtime_wrapper_sessions_dir / "ws-invalid"
    session_dir.mkdir(parents=True)
    session = {
        "schema_version": "wrapper_session/v1",
        "record_type": "wrapper_session",
        "session_id": "ws-invalid",
        "current_run_id": run_id,
        "status": "handoff_prepared",
        "decision": "none",
    }
    (session_dir / "session.json").write_text(json.dumps(session, sort_keys=True), encoding="utf-8")


def _write_malformed_wrapper_session(paths: OmhPaths) -> None:
    session_dir = paths.runtime_wrapper_sessions_dir / "ws-malformed"
    session_dir.mkdir(parents=True)
    _write_malformed_json(session_dir / "session.json")


def _write_malformed_json(path: Path) -> None:
    path.write_text("{", encoding="utf-8")


def _runtime_snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): path.read_text(encoding="utf-8") for path in sorted(root.rglob("*")) if path.is_file()}
