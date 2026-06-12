from __future__ import annotations

from copy import deepcopy
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
from omh.chat_router import route_chat_message, routing_record_payload
from omh.coding_delegation import build_coding_delegation_payload, coding_delegation_record_payload
from omh.runtime_artifacts import (
    create_prepared_coding_delegation_run,
    create_run,
    export_runtime,
    list_runs,
    new_run_id,
    show_run,
    summarize_delegated_coding_status,
    update_state,
    validate_coding_delegation_record,
    validate_ci_record,
    validate_delegation_record,
    validate_merge_record,
    validate_review_record,
    validate_routing_record,
    validate_runtime,
    validate_run_record,
    validate_wrapper_record,
    write_ci_record,
    write_coding_delegation,
    write_delegation,
    write_merge_record,
    write_review_record,
    write_routing_decision,
    write_wrapper_contract,
)
from omh.runtime.records import validate_coding_runtime_handoff


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

    def test_create_prepared_coding_delegation_run_has_explicit_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling", "trigger": "coding:discord:delegate"},
            )

            self.assertEqual(run["status"], "prepared")
            self.assertEqual(run["artifact_kind"], "prepared_coding_delegation")
            self.assertEqual(run["phase"], "prepared")
            self.assertEqual(run["observation_status"], "prepared_not_observed")
            self.assertEqual(validate_run_record(run), [])

    def test_create_run_does_not_collide_for_rapid_same_harness_records(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            first = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            second = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})

            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertEqual(len(list_runs(paths)), 2)

    def test_show_and_export_report_malformed_jsonl_without_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            events_path = paths.runtime_runs_dir / run["run_id"] / "events.jsonl"
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write("{not json\n")

            shown = show_run(paths, run["run_id"])
            exported = export_runtime(paths, redacted=False)
            validation = validate_runtime(paths, run["run_id"])

            self.assertIn("event_errors", shown)
            self.assertTrue(any("Expecting property name" in error for error in shown["event_errors"]))
            self.assertEqual(exported["runs"][0]["event_errors"], shown["event_errors"])
            self.assertFalse(validation["ok"])
            self.assertTrue(any("Expecting property name" in error for error in validation["runs"][0]["errors"]))

    def test_runtime_listing_and_summary_export_can_be_bounded(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            runs = [
                create_run(paths, {"run_id": "20260604T000001000000Z-one", "skill": "oh-my-hermes", "harness": "coding-handling"}),
                create_run(paths, {"run_id": "20260604T000002000000Z-two", "skill": "oh-my-hermes", "harness": "coding-handling"}),
                create_run(paths, {"run_id": "20260604T000003000000Z-three", "skill": "oh-my-hermes", "harness": "coding-handling"}),
            ]

            self.assertEqual([run["run_id"] for run in list_runs(paths, limit=2)], [runs[1]["run_id"], runs[2]["run_id"]])

            exported = export_runtime(paths, redacted=False, limit=1, full=False)

            self.assertEqual(exported["export"]["limit"], 1)
            self.assertFalse(exported["export"]["full"])
            self.assertEqual([run["run_id"] for run in exported["runs"]], [runs[2]["run_id"]])
            self.assertNotIn("events", exported["runs"][0])

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

    def test_write_routing_decision_records_pre_dispatch_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "ai-slop-cleaner", "harness": "coding-handling", "status": "started"})
            message = "risky refactor"
            decision = route_chat_message(message, source="discord")

            routing = write_routing_decision(
                paths.runtime_runs_dir / run["run_id"],
                routing_record_payload(decision, message, source_event_id="m1"),
            )

            self.assertEqual(routing["selected_skill"], "ai-slop-cleaner")
            self.assertEqual(routing["source_event_id"], "m1")
            self.assertTrue(validate_runtime(paths, run["run_id"])["ok"])
            shown = show_run(paths, run["run_id"])
            self.assertEqual(shown["routing"]["action"], "dispatch")
            self.assertIn("routing_decision_recorded", {event["event"] for event in shown["events"]})

    def test_write_routing_decision_sanitizes_full_route_decision(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "ai-slop-cleaner", "harness": "coding-handling", "status": "started"})
            secret_message = "risky refactor with private-token-123"

            routing = write_routing_decision(
                paths.runtime_runs_dir / run["run_id"],
                route_chat_message(secret_message, source="discord"),
            )

            serialized = json.dumps(routing)
            self.assertNotIn(secret_message, serialized)
            self.assertNotIn("suggested_prompt", serialized)
            self.assertEqual(set(routing["recommendations"][0]), {"skill", "score", "confidence", "matched"})

    def test_write_coding_delegation_sanitizes_full_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "ai-slop-cleaner", "harness": "coding-handling", "status": "started"})
            secret_message = "risky refactor with private-token-123"
            payload = build_coding_delegation_payload(
                secret_message,
                source="discord",
                include_message=True,
                source_metadata={"source_event_id": "m1", "unsupported": "drop-me"},
            )
            payload["suggested_prompt"] = "do not store"

            coding_delegation = write_coding_delegation(paths.runtime_runs_dir / run["run_id"], payload)

            serialized = json.dumps(coding_delegation)
            self.assertNotIn(secret_message, serialized)
            self.assertNotIn("delegation_prompt", serialized)
            self.assertNotIn("suggested_prompt", serialized)
            self.assertNotIn("drop-me", serialized)
            self.assertEqual(coding_delegation["message_length"], len(secret_message))
            self.assertEqual(coding_delegation["source_metadata"], {"source_event_id": "m1"})
            self.assertEqual(set(coding_delegation["recommendation_evidence"][0]), {"skill", "score", "confidence", "matched"})
            self.assertEqual(coding_delegation["harness_quality"]["schema_version"], "harness_quality/v1")
            self.assertEqual(coding_delegation["harness_quality"]["harness"], "coding-handling")
            self.assertIn("coding_delegation_prepared", coding_delegation["harness_quality"]["evidence_ladder"])
            self.assertEqual(
                coding_delegation["harness_quality"]["wrapper_actions"],
                ["show_prompt_handoff", "copy_prompt_handoff", "choose_executor", "show_status"],
            )
            self.assertTrue(coding_delegation["acceptance_criteria"])
            self.assertTrue(coding_delegation["verification"])
            self.assertTrue(validate_runtime(paths, run["run_id"])["ok"])

    def test_validate_coding_delegation_rejects_top_level_raw_prompt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )
            record = write_coding_delegation(
                paths.runtime_runs_dir / run["run_id"],
                build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", include_message=True),
            )
            record["message"] = "risky refactor"

            errors = validate_coding_delegation_record(record)

            self.assertTrue(any("unsupported keys" in error and "message" in error for error in errors))

    def test_validate_runtime_handoff_requires_boundary_evidence_contract(self) -> None:
        handoff = build_coding_delegation_payload("risky refactor", executor_target="omx-runtime")["runtime_handoff"]

        self.assertEqual(validate_coding_runtime_handoff(handoff), [])

        missing_key = deepcopy(handoff)
        del missing_key["evidence_contract"]["prepared_is_not"]
        self.assertIn("missing keys", json.dumps(validate_coding_runtime_handoff(missing_key)))

        unknown_key = deepcopy(handoff)
        unknown_key["evidence_contract"]["anything"] = ["runtime_start"]
        self.assertIn("unsupported keys", json.dumps(validate_coding_runtime_handoff(unknown_key)))

        empty_boundary = deepcopy(handoff)
        empty_boundary["evidence_contract"]["prepared_is_not"] = []
        self.assertIn("must not be empty", json.dumps(validate_coding_runtime_handoff(empty_boundary)))

        missing_required_boundary = deepcopy(handoff)
        missing_required_boundary["evidence_contract"]["observed_required_for"].remove("worker_dispatch")
        self.assertIn("must include required boundaries", json.dumps(validate_coding_runtime_handoff(missing_required_boundary)))

    def test_validate_runtime_requires_coding_delegation_for_prepared_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )

            result = validate_runtime(paths, run["run_id"])

            self.assertFalse(result["ok"])
            self.assertTrue(any("missing coding_delegation.json" in error for error in result["runs"][0]["errors"]))

    def test_validate_runtime_rejects_prompt_only_handoff_in_prepared_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )
            run_dir = paths.runtime_runs_dir / run["run_id"]
            payload = build_coding_delegation_payload("risky refactor", source="discord", executor_target="claude-code")
            write_coding_delegation(
                run_dir,
                coding_delegation_record_payload(payload, "risky refactor"),
            )

            result = validate_runtime(paths, run["run_id"])

            self.assertFalse(result["ok"])
            self.assertIn("prompt-only handoff must not be stored as a prepared runtime run", "\n".join(result["runs"][0]["errors"]))

    def test_validate_runtime_rejects_choice_required_payload_in_prepared_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )
            run_dir = paths.runtime_runs_dir / run["run_id"]
            payload = build_coding_delegation_payload("risky refactor", source="discord", executor_target="choose")
            write_coding_delegation(
                run_dir,
                coding_delegation_record_payload(payload, "risky refactor"),
            )

            result = validate_runtime(paths, run["run_id"])

            self.assertFalse(result["ok"])
            errors = "\n".join(result["runs"][0]["errors"])
            self.assertIn("executor choice must not be stored as a prepared runtime run", errors)
            self.assertIn("prepared runtime run requires a Codex executor_handoff", errors)

    def test_validate_runtime_rejects_raw_top_level_coding_delegation_key(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )
            run_dir = paths.runtime_runs_dir / run["run_id"]
            write_coding_delegation(
                run_dir,
                build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", include_message=True),
            )
            artifact_path = run_dir / "coding_delegation.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["message"] = "risky refactor"
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

            result = validate_runtime(paths, run["run_id"])

            self.assertFalse(result["ok"])
            self.assertTrue(any("unsupported keys" in error and "message" in error for error in result["runs"][0]["errors"]))

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

    def test_record_validators_remain_available_from_runtime_artifacts(self) -> None:
        delegation_errors = validate_delegation_record(
            {
                "schema_version": 1,
                "requested": True,
                "observed": False,
                "participants": [],
                "evidence_refs": [],
                "result": "completed",
            }
        )
        wrapper_errors = validate_wrapper_record(
            {
                "schema_version": 1,
                "prompt_dispatched": True,
                "hermes_response_observed": False,
                "verification_observed": False,
                "completion_status": "missing",
                "unobserved_gaps": [],
            }
        )
        routing_errors = validate_routing_record({"schema_version": 1, "action": "missing", "recommendations": []})
        coding_errors = validate_coding_delegation_record(
            {
                "schema_version": "coding_delegation/v1",
                "record_type": "coding_delegation",
                "updated_at": "now",
                "source": "discord",
                "action": "missing",
                "intent": "cleanup",
                "recommended_workflow": "ai-slop-cleaner",
                "recommended_harness": "coding-handling",
                "executor_profile": "coding-agent",
                "review_required": True,
                "review_workflow": "code-review",
                "message_sha256": "",
                "message_length": 13,
                "source_metadata": {"raw_message": "nope"},
                "recommendation_evidence": [],
                "status": "prepared_not_observed",
            }
        )

        self.assertIn("unobserved delegation requires result not_available or not_observed", delegation_errors)
        self.assertTrue(any("completion_status is invalid" in error for error in wrapper_errors))
        self.assertTrue(any("routing action is invalid" in error for error in routing_errors))
        self.assertTrue(any("coding_delegation action is invalid" in error for error in coding_errors))
        self.assertTrue(any("source_metadata has unsupported keys" in error for error in coding_errors))

    def test_review_ci_merge_records_validate_and_show_under_runtime_run(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            run_dir = paths.runtime_runs_dir / run["run_id"]

            review = write_review_record(
                run_dir,
                {"status": "pending", "reviewer": "code-review", "summary": "waiting for review"},
            )
            ci = write_ci_record(
                run_dir,
                {"status": "pending", "provider": "local", "checks": ["unit:pending"]},
            )
            merge = write_merge_record(
                run_dir,
                {"status": "not_observed", "target_branch": "main"},
            )

            self.assertEqual(validate_review_record(review), [])
            self.assertEqual(validate_ci_record(ci), [])
            self.assertEqual(validate_merge_record(merge), [])
            shown = show_run(paths, run["run_id"])
            self.assertEqual(shown["review"]["status"], "pending")
            self.assertEqual(shown["ci"]["checks"][0]["name"], "unit")
            self.assertEqual(shown["merge"]["status"], "not_observed")
            self.assertIn("review_recorded", {event["event"] for event in shown["events"]})
            self.assertIn("ci_recorded", {event["event"] for event in shown["events"]})
            self.assertIn("merge_recorded", {event["event"] for event in shown["events"]})

    def test_status_artifact_validators_reject_contradictory_success_claims(self) -> None:
        self.assertIn(
            "review observed=false requires pending or not_observed",
            validate_review_record(
                {
                    "schema_version": 1,
                    "run_id": "run-1",
                    "updated_at": "now",
                    "required": True,
                    "observed": False,
                    "status": "passed",
                    "reviewer": "code-review",
                    "evidence_refs": [],
                    "summary": "",
                }
            ),
        )
        self.assertIn(
            "ci passed status requires all checks to be passed",
            validate_ci_record(
                {
                    "schema_version": 1,
                    "run_id": "run-1",
                    "updated_at": "now",
                    "required": True,
                    "observed": True,
                    "status": "passed",
                    "provider": "local",
                    "checks": [{"name": "unit", "status": "failed"}],
                    "evidence_refs": [],
                    "summary": "",
                }
            ),
        )
        self.assertIn(
            "ci not_required status requires checks to be empty or not_required",
            validate_ci_record(
                {
                    "schema_version": 1,
                    "run_id": "run-1",
                    "updated_at": "now",
                    "required": False,
                    "observed": True,
                    "status": "not_required",
                    "provider": "local",
                    "checks": [{"name": "unit", "status": "failed"}],
                    "evidence_refs": [],
                    "summary": "",
                }
            ),
        )
        self.assertIn(
            "merge merged status requires merge_commit or evidence_refs",
            validate_merge_record(
                {
                    "schema_version": 1,
                    "run_id": "run-1",
                    "updated_at": "now",
                    "observed": True,
                    "ready": True,
                    "merged": True,
                    "status": "merged",
                    "target_branch": "main",
                    "merge_commit": "",
                    "evidence_refs": [],
                    "summary": "",
                }
            ),
        )
        self.assertIn(
            "merge not_ready status requires ready=false",
            validate_merge_record(
                {
                    "schema_version": 1,
                    "run_id": "run-1",
                    "updated_at": "now",
                    "observed": False,
                    "ready": True,
                    "merged": False,
                    "status": "not_ready",
                    "target_branch": "main",
                    "merge_commit": "",
                    "evidence_refs": [],
                    "summary": "",
                }
            ),
        )
        self.assertIn(
            "merge blocked status requires merged=false",
            validate_merge_record(
                {
                    "schema_version": 1,
                    "run_id": "run-1",
                    "updated_at": "now",
                    "observed": True,
                    "ready": False,
                    "merged": True,
                    "status": "blocked",
                    "target_branch": "main",
                    "merge_commit": "",
                    "evidence_refs": [],
                    "summary": "",
                }
            ),
        )

    def test_runtime_validation_rejects_merge_ready_before_upstream_gates(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            run_dir = paths.runtime_runs_dir / run["run_id"]
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main"})

            result = validate_runtime(paths, run["run_id"])

            self.assertFalse(result["ok"])
            errors = "\n".join(result["runs"][0]["errors"])
            self.assertIn("merge ready requires completed executor evidence", errors)
            self.assertIn("merge ready requires verification evidence", errors)

    def test_status_reader_does_not_overclaim_contradictory_merge_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )
            run_dir = paths.runtime_runs_dir / run["run_id"]
            write_coding_delegation(
                run_dir,
                build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", include_message=True),
            )
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

            for status, ready, merged in (("ready", False, False), ("merged", True, False)):
                (run_dir / "merge.json").write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "run_id": run["run_id"],
                            "updated_at": "now",
                            "observed": True,
                            "ready": ready,
                            "merged": merged,
                            "status": status,
                            "target_branch": "main",
                            "merge_commit": "abc123",
                            "evidence_refs": [],
                            "summary": "",
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )

                summary = summarize_delegated_coding_status(paths, run["run_id"])

                self.assertEqual(summary["next_action"], "record_merge_readiness")
                self.assertFalse(summary["merge"]["satisfied"])

    def test_status_reader_preserves_required_review_and_ci_gates(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )
            run_dir = paths.runtime_runs_dir / run["run_id"]
            write_coding_delegation(
                run_dir,
                build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", include_message=True),
            )
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
            (run_dir / "review.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run["run_id"],
                        "updated_at": "now",
                        "required": False,
                        "observed": True,
                        "status": "not_required",
                        "reviewer": "code-review",
                        "evidence_refs": [],
                        "summary": "",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            summary = summarize_delegated_coding_status(paths, run["run_id"])
            result = validate_runtime(paths, run["run_id"])

            self.assertTrue(summary["review"]["required"])
            self.assertFalse(summary["review"]["satisfied"])
            self.assertEqual(summary["next_action"], "record_review_evidence")
            self.assertFalse(result["ok"])
            self.assertIn("review not_required cannot downgrade required review evidence", "\n".join(result["runs"][0]["errors"]))

            write_review_record(run_dir, {"status": "passed", "reviewer": "code-review", "evidence_refs": ["review"]})
            (run_dir / "ci.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run["run_id"],
                        "updated_at": "now",
                        "required": False,
                        "observed": True,
                        "status": "not_required",
                        "provider": "local",
                        "checks": [{"name": "unit", "status": "failed"}],
                        "evidence_refs": [],
                        "summary": "",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            summary = summarize_delegated_coding_status(paths, run["run_id"])
            result = validate_runtime(paths, run["run_id"])
            errors = "\n".join(result["runs"][0]["errors"])

            self.assertTrue(summary["ci"]["required"])
            self.assertFalse(summary["ci"]["satisfied"])
            self.assertEqual(summary["next_action"], "record_ci_evidence")
            self.assertFalse(result["ok"])
            self.assertIn("ci not_required cannot downgrade required CI evidence", errors)
            self.assertIn("ci not_required status requires checks to be empty or not_required", errors)

    def test_status_reader_calculates_harness_quality_ladder_progress(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_prepared_coding_delegation_run(
                paths,
                {"skill": "ai-slop-cleaner", "harness": "coding-handling"},
            )
            run_dir = paths.runtime_runs_dir / run["run_id"]
            write_coding_delegation(
                run_dir,
                build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", include_message=True),
            )

            summary = summarize_delegated_coding_status(paths, run["run_id"])
            progress = summary["harness_progress"]
            states = {step["id"]: step["state"] for step in progress["steps"]}

            self.assertEqual(progress["schema_version"], "harness_progress/v1")
            self.assertEqual(progress["harness"], "coding-handling")
            self.assertEqual(progress["completed"], 1)
            self.assertFalse(progress["complete"])
            self.assertEqual(progress["next_step"], "executor_dispatch_observed")
            self.assertEqual(states["coding_delegation_prepared"], "complete")
            self.assertEqual(states["executor_dispatch_observed"], "pending")
            self.assertEqual(states["review_ci_merge_recorded_when_required"], "pending")

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
            write_merge_record(run_dir, {"status": "ready", "target_branch": "main", "evidence_refs": ["ci"], "summary": "ready"})

            summary = summarize_delegated_coding_status(paths, run["run_id"])
            progress = summary["harness_progress"]
            states = {step["id"]: step["state"] for step in progress["steps"]}

            self.assertTrue(progress["complete"])
            self.assertEqual(progress["completed"], progress["total"])
            self.assertEqual(progress["next_step"], "")
            self.assertEqual(states["executor_dispatch_observed"], "complete")
            self.assertEqual(states["executor_result_observed"], "complete")
            self.assertEqual(states["verification_recorded"], "complete")
            self.assertEqual(states["review_ci_merge_recorded_when_required"], "complete")

    def test_export_runtime_redacts_sensitive_text_and_preserves_evidence_booleans(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            run = create_run(paths, {"skill": "oh-my-hermes", "harness": "coding-handling", "status": "started"})
            write_wrapper_contract(
                paths.runtime_runs_dir / run["run_id"],
                {
                    "prompt_dispatched": True,
                    "hermes_response_observed": True,
                    "verification_observed": False,
                    "completion_status": "completed",
                    "message": "private-token-123 raw prompt",
                    "prompt_body": "do not export",
                },
            )
            wrapper_path = paths.runtime_runs_dir / run["run_id"] / "wrapper.json"
            wrapper_record = json.loads(wrapper_path.read_text(encoding="utf-8"))
            wrapper_record["prompt_body"] = "do not export"
            wrapper_path.write_text(json.dumps(wrapper_record), encoding="utf-8")

            exported = export_runtime(paths, redacted=True)

            self.assertTrue(exported["redacted"])
            wrapper = exported["runs"][0]["wrapper"]
            self.assertEqual(wrapper["message"], "[redacted]")
            self.assertEqual(wrapper["prompt_body"], "[redacted]")
            self.assertTrue(wrapper["prompt_dispatched"])
            self.assertTrue(wrapper["hermes_response_observed"])
            self.assertFalse(wrapper["verification_observed"])
            self.assertEqual(wrapper["completion_status"], "completed")
            serialized = json.dumps(exported)
            self.assertNotIn("private-token-123", serialized)
            self.assertNotIn("do not export", serialized)

    def test_update_state_merges_patch(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            update_state(paths, {"installed_skills": 18})
            state = update_state(paths, {"last_run_id": "r1"})

            self.assertEqual(state["installed_skills"], 18)
            self.assertEqual(state["last_run_id"], "r1")


if __name__ == "__main__":
    unittest.main()
