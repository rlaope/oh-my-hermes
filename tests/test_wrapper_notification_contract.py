from __future__ import annotations

import json
from pathlib import Path
import unittest

from _local_package import load_local_package

load_local_package()
from omh.wrapper_contract import (
    DELIVERY_OBLIGATION_SCHEMA_VERSION,
    DELIVERY_OBLIGATION_STATE,
    DELIVERY_OBLIGATION_TRIGGERS,
    build_wrapper_delivery_obligation,
)

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
GOLDEN_FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "wrapper-golden" / "delivery-obligation.json"


class WrapperDeliveryObligationContractTests(unittest.TestCase):
    def test_obligation_is_pinned_prepared_not_delivered(self) -> None:
        obligation = build_wrapper_delivery_obligation(
            origin_thread_key="discord:guild:chan:thread-1",
            trigger="handoff_ci_pass",
            evidence_refs=["ci_recorded:run-abc", "status:passed"],
        )

        self.assertEqual(obligation["schema_version"], DELIVERY_OBLIGATION_SCHEMA_VERSION)
        self.assertEqual(obligation["schema_version"], "wrapper_delivery_obligation/v1")
        self.assertEqual(obligation["obligation_state"], "prepared_not_delivered")
        self.assertEqual(DELIVERY_OBLIGATION_STATE, "prepared_not_delivered")
        self.assertTrue(obligation["not_delivered_until_wrapper_observed"])
        self.assertEqual(obligation["evidence_policy"], "metadata_only")

    def test_payload_never_carries_a_delivered_state(self) -> None:
        for trigger in DELIVERY_OBLIGATION_TRIGGERS:
            obligation = build_wrapper_delivery_obligation(
                origin_thread_key="slack:team:chan:ts-1",
                trigger=trigger,
                evidence_refs=["loop:loop-1"],
            )
            serialized = json.dumps(obligation).lower()
            with self.subTest(trigger=trigger):
                self.assertNotIn("delivery_confirmed", serialized)
                self.assertNotIn("sent_at", serialized)
                # No affirmative delivered state (prepared_not_delivered is the pin).
                self.assertEqual(obligation["obligation_state"], "prepared_not_delivered")
                self.assertNotIn(obligation["obligation_state"], {"delivered", "delivery_observed"})

    def test_no_field_implies_omh_sent_a_message(self) -> None:
        obligation = build_wrapper_delivery_obligation(
            origin_thread_key="telegram:chat:-1001:thread-42",
            trigger="handoff_ci_pass",
        )

        self.assertIn("delivered message", obligation["not_evidence"])
        self.assertIn("thread reply sent", obligation["not_evidence"])
        self.assertIn("user notified", obligation["not_evidence"])
        self.assertIn("wrapper-observed delivery", obligation["not_evidence"])
        boundary = str(obligation["claim_boundary"]).lower()
        self.assertIn("not delivered", boundary)
        self.assertIn("unobserved until a wrapper records", boundary)

    def test_rejects_unsupported_trigger(self) -> None:
        with self.assertRaises(ValueError):
            build_wrapper_delivery_obligation(
                origin_thread_key="discord:guild:chan:thread-1",
                trigger="message_received",
            )

    def test_shape_is_executor_neutral(self) -> None:
        # The builder takes no executor input, so codex, claude-code, and hermes
        # runs that reach the same trigger must produce byte-identical shapes.
        payloads = [
            build_wrapper_delivery_obligation(
                origin_thread_key="discord:guild:chan:thread-1",
                trigger="loop_iteration_complete",
                evidence_refs=["loop:loop-xyz", "cycle:cycle-7"],
            )
            for _executor in ("codex", "claude-code", "hermes")
        ]

        first = json.dumps(payloads[0], sort_keys=True)
        for payload in payloads[1:]:
            self.assertEqual(json.dumps(payload, sort_keys=True), first)

    def test_evidence_refs_are_metadata_only_bounded_strings(self) -> None:
        obligation = build_wrapper_delivery_obligation(
            origin_thread_key="slack:team:chan:ts-1",
            trigger="loop_iteration_complete",
            evidence_refs=["loop:loop-xyz", "loop:loop-xyz", "", "  ", "x" * 500],
        )
        refs = obligation["evidence_refs"]

        self.assertIsInstance(refs, list)
        self.assertEqual(refs.count("loop:loop-xyz"), 1)  # deduplicated
        self.assertNotIn("", refs)
        self.assertTrue(all(len(ref) <= 181 for ref in refs))  # bounded, no raw logs

    def test_no_live_trigger_emission_in_runtime_or_observation_code(self) -> None:
        # Guard: this PR ships the contract SHAPE only. The builder must not be
        # called from any runtime/observation/workflow/command code path. Its
        # only reference under src/ is its own definition in wrapper/contract.py.
        callable_name = "build_wrapper_delivery_obligation"
        referencing_files: list[str] = []
        for path in SOURCE_ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if callable_name in text:
                referencing_files.append(str(path.relative_to(SOURCE_ROOT)))

        self.assertEqual(
            referencing_files,
            ["wrapper/contract.py"],
            msg=f"delivery-obligation builder leaked into live code paths: {referencing_files}",
        )

        # Nothing in runtime/observation writers may emit the obligation schema.
        for subtree in ("runtime", "workflows", "commands", "plugin_bundle"):
            for path in (SOURCE_ROOT / subtree).rglob("*.py"):
                self.assertNotIn(
                    DELIVERY_OBLIGATION_SCHEMA_VERSION,
                    path.read_text(encoding="utf-8"),
                    msg=f"{path} references the delivery-obligation schema; wiring is a gated follow-up",
                )


class WrapperDeliveryObligationGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))

    def test_golden_metadata(self) -> None:
        self.assertEqual(self.payload["schema_version"], "wrapper_delivery_obligation_golden_examples/v1")
        self.assertEqual(self.payload["obligation_state_invariant"], "prepared_not_delivered")
        self.assertTrue(self.payload["no_live_trigger_wiring"])

    def test_golden_covers_all_three_surfaces(self) -> None:
        sources = {item["source"] for item in self.payload["scenarios"]}
        self.assertEqual(sources, {"discord", "slack", "telegram"})

    def test_every_scenario_is_prepared_not_delivered(self) -> None:
        for item in self.payload["scenarios"]:
            obligation = item["expected_obligation"]
            with self.subTest(item["scenario"]):
                self.assertEqual(obligation["schema_version"], "wrapper_delivery_obligation/v1")
                self.assertEqual(obligation["obligation_state"], "prepared_not_delivered")
                self.assertTrue(obligation["not_delivered_until_wrapper_observed"])
                self.assertEqual(obligation["evidence_policy"], "metadata_only")
                self.assertIn(obligation["trigger"], DELIVERY_OBLIGATION_TRIGGERS)
                self.assertTrue(item["claim_boundary"])
                self.assertTrue(item["observed_evidence"])
                self.assertTrue(item["not_evidence"])
                self.assertNotIn(obligation["obligation_state"], {"delivered", "delivery_observed"})

    def test_golden_matches_live_builder_output(self) -> None:
        for item in self.payload["scenarios"]:
            expected = item["expected_obligation"]
            live = build_wrapper_delivery_obligation(
                origin_thread_key=expected["origin_thread_key"],
                trigger=expected["trigger"],
                evidence_refs=expected["evidence_refs"],
                claim_boundary=item["claim_boundary"],
            )
            with self.subTest(item["scenario"]):
                self.assertEqual(live["schema_version"], expected["schema_version"])
                self.assertEqual(live["origin_thread_key"], expected["origin_thread_key"])
                self.assertEqual(live["trigger"], expected["trigger"])
                self.assertEqual(live["obligation_state"], expected["obligation_state"])
                self.assertEqual(
                    live["not_delivered_until_wrapper_observed"],
                    expected["not_delivered_until_wrapper_observed"],
                )
                self.assertEqual(live["evidence_policy"], expected["evidence_policy"])
                self.assertEqual(live["evidence_refs"], expected["evidence_refs"])
                self.assertEqual(live["observed_evidence"], item["observed_evidence"])
                self.assertEqual(live["not_evidence"], item["not_evidence"])
                self.assertEqual(live["claim_boundary"], item["claim_boundary"])

    def test_golden_records_future_trigger_hook_sites(self) -> None:
        hooks = self.payload["future_trigger_hook_sites"]
        self.assertIn("handoff_ci_pass", hooks)
        self.assertIn("loop_iteration_complete", hooks)
        self.assertIn("write_ci_record", hooks["handoff_ci_pass"])
        self.assertIn("record_loop_feedback", hooks["loop_iteration_complete"])


if __name__ == "__main__":
    unittest.main()
