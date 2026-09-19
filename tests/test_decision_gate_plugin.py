from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths  # noqa: E402
from omh.plugin_bundle.omh.tools.decision_gate_tool import OMH_DECISION_GATE_SCHEMA, omh_decision_gate_handler  # noqa: E402
from omh.system.local_store import utc_now  # noqa: E402
from omh.wrapper_sessions import create_or_resume_wrapper_session, open_wrapper_session_decision_gate  # noqa: E402


class DecisionGatePluginTests(unittest.TestCase):
    def test_given_a_missing_binding_when_called_then_the_plugin_returns_a_bounded_invalid_result(self) -> None:
        payload = json.loads(omh_decision_gate_handler({"gate_id": "gate-1"}))

        self.assertEqual(OMH_DECISION_GATE_SCHEMA["name"], "omh_decision_gate")
        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["reason_code"], "invalid_payload")

    def test_given_a_bound_event_when_called_then_the_plugin_uses_the_shared_answer_operation(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"OMH_HOME": str(Path(tmp) / ".omh")}, clear=False):
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session = create_or_resume_wrapper_session(paths, "make a plan for the checkout migration", source="discord")["session"]
            current = utc_now()
            gate = open_wrapper_session_decision_gate(
                paths,
                session_id=str(session["session_id"]),
                approver="actor-plugin",
                safety_profile_revision="safety-plugin",
                now=current,
            )
            args = {"gate_id": gate["gate_id"], "expected_resume_digest": gate["resume_digest"], "choice": "approve", "actor": "actor-plugin", "connector": "discord", "channel_ref": "channel-plugin", "thread_ref": "thread-plugin", "interaction_ref": "interaction-plugin", "authentication_method": "host_authenticated", "observed_at": current, "event_id": "event-plugin", "wrapper_session_ref": session["session_id"], "wrapper_expected_revision": session["record_revision"]}
            payload = json.loads(omh_decision_gate_handler(args, trusted_connector_event=dict(args)))

        self.assertEqual(payload["status"], "applied")
        self.assertEqual(payload["wrapper"]["session"]["status"], "plan_accepted")

    def test_given_unknown_or_raw_fields_when_called_then_the_plugin_refuses_before_opening_a_store(self) -> None:
        payload = json.loads(omh_decision_gate_handler({"gate_id": "gate-1", "body": "approve"}))

        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["reason_code"], "invalid_payload")

    def test_given_no_host_connector_event_when_model_args_are_complete_then_the_plugin_refuses(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"OMH_HOME": str(Path(tmp) / ".omh")}, clear=False):
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session = create_or_resume_wrapper_session(paths, "make a plan for the checkout migration", source="discord")["session"]
            current = utc_now()
            gate = open_wrapper_session_decision_gate(
                paths,
                session_id=str(session["session_id"]),
                approver="actor-no-host",
                safety_profile_revision="safety-plugin",
                now=current,
            )
            args = {
                "gate_id": gate["gate_id"], "expected_resume_digest": gate["resume_digest"], "choice": "approve",
                "actor": "actor-no-host", "connector": "discord", "channel_ref": "channel-plugin",
                "thread_ref": "thread-plugin", "interaction_ref": "interaction-plugin",
                "authentication_method": "host_authenticated", "observed_at": current, "event_id": "event-no-host",
                "wrapper_session_ref": session["session_id"], "wrapper_expected_revision": session["record_revision"],
            }

            payload = json.loads(omh_decision_gate_handler(args))

        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["reason_code"], "untrusted_host_context")

    def test_given_host_context_that_disagrees_with_model_args_when_called_then_the_plugin_refuses(self) -> None:
        args = {
            "gate_id": "gate-1", "expected_resume_digest": "a" * 64, "choice": "approve", "actor": "actor-1",
            "connector": "discord", "channel_ref": "channel-1", "thread_ref": "thread-1",
            "interaction_ref": "interaction-1", "authentication_method": "host_authenticated",
            "observed_at": "2026-09-07T10:00:00Z", "event_id": "event-1", "wrapper_session_ref": "ws-1",
            "wrapper_expected_revision": 1,
        }

        payload = json.loads(omh_decision_gate_handler(args, trusted_connector_event={**args, "choice": "decline"}))

        self.assertEqual(payload["status"], "invalid")
        self.assertEqual(payload["reason_code"], "host_context_mismatch")

    def test_given_matching_host_connector_event_when_called_then_the_plugin_applies_and_replays(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"OMH_HOME": str(Path(tmp) / ".omh")}, clear=False):
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            session = create_or_resume_wrapper_session(paths, "make a plan for the checkout migration", source="discord")["session"]
            current = utc_now()
            gate = open_wrapper_session_decision_gate(
                paths,
                session_id=str(session["session_id"]),
                approver="actor-host",
                safety_profile_revision="safety-plugin",
                now=current,
            )
            args = {
                "gate_id": gate["gate_id"], "expected_resume_digest": gate["resume_digest"], "choice": "approve",
                "actor": "actor-host", "connector": "discord", "channel_ref": "channel-plugin",
                "thread_ref": "thread-plugin", "interaction_ref": "interaction-plugin",
                "authentication_method": "host_authenticated", "observed_at": current, "event_id": "event-host",
                "wrapper_session_ref": session["session_id"], "wrapper_expected_revision": session["record_revision"],
            }

            applied = json.loads(omh_decision_gate_handler(args, trusted_connector_event=dict(args)))
            replayed = json.loads(omh_decision_gate_handler(args, trusted_connector_event=dict(args)))

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["wrapper"]["session"]["status"], "plan_accepted")
        self.assertEqual(replayed["status"], "already_applied")
