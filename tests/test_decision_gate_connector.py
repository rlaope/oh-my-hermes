from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.commands.decision_gate import apply_connector_decision_answer  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.runtime.artifacts import validate_runtime  # noqa: E402
from omh.system.local_store import utc_now  # noqa: E402
from omh.workflows.decision_gate_receipts import answer_connector_decision_gate, read_connector_decision_receipts  # noqa: E402
from omh.wrapper_sessions import (  # noqa: E402
    create_or_resume_wrapper_session,
    open_wrapper_session_decision_gate,
)

_OPENED = "2026-09-07T10:00:00Z"
_OBSERVED = "2026-09-07T10:05:00Z"
_NOW = "2026-09-07T10:06:00Z"


class ConnectorDecisionGateTests(unittest.TestCase):
    def _started_gate(self, paths, *, actor: str = "actor-1", now: str = _OPENED) -> tuple[dict, dict]:
        session = create_or_resume_wrapper_session(paths, "make a plan for the checkout migration", source="discord")["session"]
        gate = open_wrapper_session_decision_gate(
            paths,
            session_id=str(session["session_id"]),
            approver=actor,
            safety_profile_revision="safety-1",
            now=now,
        )
        return session, gate

    def _payload(self, session: dict, gate: dict, *, event_id: str = "event-1", actor: str = "actor-1") -> dict:
        return {
            "gate_id": gate["gate_id"],
            "expected_resume_digest": gate["resume_digest"],
            "choice": "approve",
            "actor": actor,
            "connector": "discord",
            "channel_ref": "channel-1",
            "thread_ref": "thread-1",
            "interaction_ref": "interaction-1",
            "authentication_method": "host_authenticated",
            "observed_at": _OBSERVED,
            "event_id": event_id,
            "wrapper_session_ref": str(session["session_id"]),
            "wrapper_expected_revision": int(session["record_revision"]),
        }

    def test_given_a_bound_event_when_applied_then_it_advances_only_its_session(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths)
            untouched = create_or_resume_wrapper_session(paths, "make a plan for the billing migration", source="discord")["session"]

            result = apply_connector_decision_answer(paths, **self._payload(session, gate), trusted_now=_NOW)

            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["wrapper"]["session"]["status"], "plan_accepted")
            self.assertEqual(untouched["status"], "plan_presented")
            self.assertTrue(validate_runtime(paths)["ok"])

    def test_given_a_gate_bound_to_session_a_when_event_names_session_b_then_it_refuses_without_mutating_b(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session_a, gate = self._started_gate(paths, actor="actor-bound")
            session_b = create_or_resume_wrapper_session(paths, "make a plan for the inventory migration", source="discord")["session"]

            result = apply_connector_decision_answer(
                paths,
                **self._payload(session_b, gate, event_id="event-bound", actor="actor-bound"),
                trusted_now=_NOW,
            )

            self.assertEqual(result["status"], "stale_revision")
            self.assertEqual(session_a["status"], "plan_presented")
            self.assertEqual(session_b["status"], "plan_presented")
            self.assertEqual(read_connector_decision_receipts(paths), [])

    def test_given_an_answered_gate_when_a_new_event_arrives_then_it_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-replay")

            first = apply_connector_decision_answer(
                paths, **self._payload(session, gate, event_id="event-first", actor="actor-replay"), trusted_now=_NOW
            )
            second = apply_connector_decision_answer(
                paths, **self._payload(session, gate, event_id="event-second", actor="actor-replay"), trusted_now=_NOW
            )

            self.assertEqual(first["status"], "applied")
            self.assertEqual(second["status"], "superseded")

    def test_given_an_identical_event_when_retried_then_it_replays_and_recovers_consumption(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-recovery")
            payload = self._payload(session, gate, event_id="event-recovery", actor="actor-recovery")

            appended = answer_connector_decision_gate(paths, **payload, trusted_now=_NOW)
            recovered = apply_connector_decision_answer(paths, **payload, trusted_now=_NOW)
            conflict = apply_connector_decision_answer(paths, **{**payload, "choice": "decline"}, trusted_now=_NOW)

            self.assertEqual(appended["status"], "applied")
            self.assertEqual(recovered["status"], "already_applied")
            self.assertTrue(recovered["wrapper"]["session"]["status"].startswith("plan_accepted"))
            self.assertEqual(conflict["reason_code"], "conflicting_replay")

    def test_given_a_stale_wrapper_revision_when_an_event_arrives_then_no_answer_is_written(self) -> None:
        from omh.wrapper_sessions import record_plan_decision

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-stale")
            record_plan_decision(paths, str(session["session_id"]), "revise")

            result = apply_connector_decision_answer(
                paths, **self._payload(session, gate, event_id="event-stale", actor="actor-stale"), trusted_now=_NOW
            )

            self.assertEqual(result["status"], "stale_revision")
            self.assertEqual(read_connector_decision_receipts(paths), [])

    def test_given_a_crash_after_answer_append_when_the_same_event_retries_then_only_that_event_recovers(self) -> None:
        from omh.workflows import decision_gate_receipts

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-crash")
            payload = self._payload(session, gate, event_id="event-crash", actor="actor-crash")
            append = decision_gate_receipts.append_store_line

            def crash_after_answer(path, record):
                if record.get("schema_version") == "connector_decision_gate_receipt/v1":
                    raise OSError("simulated receipt append boundary")
                append(path, record)

            with patch.object(decision_gate_receipts, "append_store_line", side_effect=crash_after_answer):
                with self.assertRaises(OSError):
                    answer_connector_decision_gate(paths, **payload, trusted_now=_NOW)
            recovered = apply_connector_decision_answer(paths, **payload, trusted_now=_NOW)
            different_event = apply_connector_decision_answer(
                paths, **{**payload, "event_id": "event-after-crash"}, trusted_now=_NOW
            )

            self.assertEqual(recovered["status"], "applied")
            self.assertEqual(different_event["status"], "superseded")

    def test_given_invalid_timestamps_when_applied_then_it_writes_no_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths)
            payload = self._payload(session, gate)

            before_open = apply_connector_decision_answer(
                paths, **{**payload, "observed_at": "2026-09-07T09:59:59Z"}, trusted_now=_NOW
            )
            future = apply_connector_decision_answer(
                paths, **{**payload, "observed_at": "2026-09-07T10:07:00Z", "event_id": "event-future"}, trusted_now=_NOW
            )
            expired = apply_connector_decision_answer(
                paths, **{**payload, "event_id": "event-expired"}, trusted_now="2026-09-07T12:00:00Z"
            )

            self.assertEqual(before_open["status"], "invalid")
            self.assertEqual(future["status"], "invalid")
            self.assertEqual(expired["status"], "expired")
            self.assertEqual(read_connector_decision_receipts(paths), [])

    def test_given_concurrent_events_when_applied_then_only_one_wins(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-race")
            barrier = Barrier(2)

            def answer(choice: str) -> dict:
                barrier.wait(timeout=2)
                return apply_connector_decision_answer(
                    paths,
                    **{**self._payload(session, gate, event_id=f"event-{choice}", actor="actor-race"), "choice": choice},
                    trusted_now=_NOW,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(answer, ("approve", "decline")))

            self.assertEqual(sorted(result["status"] for result in results), ["applied", "superseded"])

    def test_given_an_open_wrapper_gate_when_the_public_cli_answers_then_it_returns_a_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            current = utc_now()
            session, gate = self._started_gate(paths, actor="actor-cli", now=current)
            payload = self._payload(session, gate, event_id="event-cli", actor="actor-cli")
            payload["observed_at"] = current

            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home),
                    "runtime", "decision-gate", "answer",
                    "--gate-id", payload["gate_id"], "--expected-resume-digest", payload["expected_resume_digest"],
                    "--choice", payload["choice"], "--actor", payload["actor"], "--connector", payload["connector"],
                    "--channel-ref", payload["channel_ref"], "--thread-ref", payload["thread_ref"],
                    "--interaction-ref", payload["interaction_ref"], "--authentication-method", payload["authentication_method"],
                    "--observed-at", payload["observed_at"], "--event-id", payload["event_id"],
                    "--wrapper-session-ref", payload["wrapper_session_ref"],
                    "--wrapper-expected-revision", str(payload["wrapper_expected_revision"]),
                ]
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "applied")

    def test_given_a_cancelled_session_when_an_event_arrives_then_no_receipt_is_written(self) -> None:
        from omh.wrapper_sessions import record_plan_decision

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-cancelled")
            record_plan_decision(paths, str(session["session_id"]), "cancel")

            result = apply_connector_decision_answer(
                paths, **self._payload(session, gate, event_id="event-cancelled", actor="actor-cancelled"), trusted_now=_NOW
            )

            self.assertEqual(result["status"], "cancelled")
            self.assertEqual(read_connector_decision_receipts(paths), [])

    def test_given_an_unknown_gate_when_an_event_arrives_then_no_receipt_is_written(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session = create_or_resume_wrapper_session(paths, "make a plan for the checkout migration", source="discord")["session"]
            payload = {"gate_id": "gate-unknown", "expected_resume_digest": "a" * 64, "choice": "approve", "actor": "actor-unknown", "connector": "discord", "channel_ref": "channel-unknown", "thread_ref": "thread-unknown", "interaction_ref": "interaction-unknown", "authentication_method": "host_authenticated", "observed_at": _OBSERVED, "event_id": "event-unknown", "wrapper_session_ref": session["session_id"], "wrapper_expected_revision": session["record_revision"]}

            result = apply_connector_decision_answer(paths, **payload, trusted_now=_NOW)

            self.assertEqual(result["status"], "unknown_gate")
            self.assertEqual(read_connector_decision_receipts(paths), [])

    def test_given_an_unexpected_actor_when_an_event_arrives_then_no_receipt_is_written(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-bound")

            result = apply_connector_decision_answer(
                paths, **self._payload(session, gate, event_id="event-unauthorized", actor="actor-other"), trusted_now=_NOW
            )

            self.assertEqual(result["status"], "unauthorized")
            self.assertEqual(read_connector_decision_receipts(paths), [])

    def test_given_a_choice_not_declared_by_the_gate_when_an_event_arrives_then_no_receipt_is_written(self) -> None:
        from omh.workflows.decision_gate_receipts import wrapper_gate_binding
        from omh.workflows.decision_gates import open_decision_gate

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session = create_or_resume_wrapper_session(paths, "make a plan for the checkout migration", source="discord")["session"]
            gate = open_decision_gate(
                paths,
                **wrapper_gate_binding(str(session["session_id"]), int(session["record_revision"])),
                question_code="accept_plan_direction",
                risk_class="reversible",
                choices=("approve", "decline"),
                approver="actor-choice",
                safety_profile_revision="safety-choice",
                now=_OPENED,
            )

            result = apply_connector_decision_answer(
                paths,
                **{**self._payload(session, gate, event_id="event-undeclared", actor="actor-choice"), "choice": "defer"},
                trusted_now=_NOW,
            )

            self.assertEqual(result["status"], "invalid_choice")
            self.assertEqual(read_connector_decision_receipts(paths), [])

    def test_given_concurrent_identical_events_when_applied_then_one_receipt_is_replayed(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session, gate = self._started_gate(paths, actor="actor-identical")
            payload = self._payload(session, gate, event_id="event-identical", actor="actor-identical")
            barrier = Barrier(2)

            def answer() -> dict:
                barrier.wait(timeout=2)
                return apply_connector_decision_answer(paths, **payload, trusted_now=_NOW)

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: answer(), range(2)))

            self.assertEqual(sorted(result["status"] for result in results), ["already_applied", "applied"])
            self.assertEqual(len(read_connector_decision_receipts(paths)), 1)
