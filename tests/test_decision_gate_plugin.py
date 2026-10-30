from __future__ import annotations

import json
import os
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package
from _module_patch import patch_modules
from _standalone_bundle import run_in_no_package_host

load_local_package()
from omh.paths import resolve_paths  # noqa: E402
from omh.plugin_bundle.omh.package_backend import PACKAGE_BACKEND_ROUTE  # noqa: E402
from omh.plugin_bundle.omh.tools.decision_gate_tool import OMH_DECISION_GATE_SCHEMA, omh_decision_gate_handler  # noqa: E402
from omh.system.local_store import utc_now  # noqa: E402
from omh.workflows.decision_gate_receipts import CONNECTOR_DECISION_STATUSES  # noqa: E402
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


_GATE_ARGS = {
    "gate_id": "gate-1", "expected_resume_digest": "a" * 64, "choice": "approve", "actor": "actor-1",
    "connector": "discord", "channel_ref": "channel-1", "thread_ref": "thread-1",
    "interaction_ref": "interaction-1", "authentication_method": "host_authenticated",
    "observed_at": "2026-09-07T10:00:00Z", "event_id": "event-1", "wrapper_session_ref": "ws-1",
    "wrapper_expected_revision": 1,
}


class DecisionGatePackageBackendTests(unittest.TestCase):
    """With no usable `omh` package the tool refuses, bounded, and never raises (#2166)."""

    def assert_unavailable(self, payload: dict, status: str) -> dict:
        self.assertEqual(payload["schema_version"], "connector_decision_gate_result/v1")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["reason_code"], f"package_backend_{status}")
        self.assertEqual(payload["receipt"], {})
        self.assertEqual(payload["package_backend"]["status"], status)
        self.assertEqual(payload["package_backend"]["install_route"], PACKAGE_BACKEND_ROUTE)
        self.assertTrue(payload["detail"].startswith("No gate answer was recorded."))
        self.assertIn(PACKAGE_BACKEND_ROUTE, payload["detail"])
        return payload["package_backend"]

    def test_a_host_with_no_omh_package_gets_a_bounded_refusal(self) -> None:
        code = (
            "from hermes_plugin_omh.tools.decision_gate_tool import omh_decision_gate_handler\n"
            f"args = json.loads({json.dumps(json.dumps(_GATE_ARGS))})\n"
            "print(json.dumps({'omh_spec': omh_spec, 'result': json.loads(omh_decision_gate_handler(args))}))\n"
        )
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            env = {"OMH_HOME": str(omh_home), "HERMES_HOME": str(Path(tmp) / ".hermes")}
            with patch.dict(os.environ, env, clear=False):
                observed = run_in_no_package_host(code, cwd=Path(tmp))
            self.assertEqual([path.name for path in omh_home.rglob("*decision*")], [])
        self.assertFalse(observed["omh_spec"])
        backend = self.assert_unavailable(observed["result"], "absent")
        self.assertEqual(backend["failed_import"], "omh")
        detail = observed["result"]["detail"]
        self.assertIn("so the decision gate has no backend here", detail)
        self.assertIn("Run `omh update` (or `omh setup`)", detail)
        for forbidden in ("pip", "uv ", "omh --omh-home"):
            self.assertNotIn(forbidden, detail)

    def test_a_present_package_missing_the_receipt_module_reads_incompatible(self) -> None:
        with patch_modules({"omh.workflows.decision_gate_receipts": None}):
            payload = json.loads(omh_decision_gate_handler(dict(_GATE_ARGS)))
        backend = self.assert_unavailable(payload, "incompatible")
        self.assertEqual(backend["failed_import"], "omh.workflows.decision_gate_receipts")

    def test_a_present_package_lacking_a_name_reads_incompatible_without_raising(self) -> None:
        # `cannot import name` is a plain ImportError, not ModuleNotFoundError.
        empty = types.ModuleType("omh.workflows.decision_gate_receipts")
        with patch_modules({"omh.workflows.decision_gate_receipts": empty}):
            payload = json.loads(omh_decision_gate_handler(dict(_GATE_ARGS)))
        backend = self.assert_unavailable(payload, "incompatible")
        self.assertEqual(backend["failed_import"], "omh.workflows.decision_gate_receipts")

    def test_the_whole_core_service_is_imported_before_validating(self) -> None:
        # A trusted, well-formed event would otherwise reach the answer path
        # and raise there; importing the service up front refuses it here.
        with patch_modules({"omh.commands.decision_gate": None}):
            payload = json.loads(
                omh_decision_gate_handler(dict(_GATE_ARGS), trusted_connector_event=dict(_GATE_ARGS))
            )
        backend = self.assert_unavailable(payload, "incompatible")
        self.assertEqual(backend["failed_import"], "omh.commands.decision_gate")

    def test_a_non_import_error_at_import_is_refused_as_broken(self) -> None:
        from omh.plugin_bundle.omh.tools import decision_gate_tool

        failure = RuntimeError("receipts failed at import time")
        with patch.object(decision_gate_tool, "_import_gate_service", side_effect=failure):
            payload = json.loads(omh_decision_gate_handler(dict(_GATE_ARGS)))
        backend = self.assert_unavailable(payload, "broken")
        self.assertEqual(backend["error_type"], "RuntimeError")
        self.assertNotIn("failed at import time", json.dumps(payload))

    def test_the_refusal_is_in_the_core_status_vocabulary(self) -> None:
        self.assertIn("unavailable", CONNECTOR_DECISION_STATUSES)
