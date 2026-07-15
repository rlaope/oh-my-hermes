from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.adapter_quality import (
    build_adapter_quality_observation,
    build_adapter_quality_delivery_card,
    link_adapter_quality_session,
    prepare_adapter_quality_delivery,
    quality_session_control,
    record_adapter_quality_delivery,
    write_adapter_quality_observation,
)
from omh.paths import resolve_paths


class AdapterQualityTests(unittest.TestCase):
    def test_web_desktop_and_app_observations_are_surface_neutral(self) -> None:
        for surface_kind in ("web", "desktop", "app"):
            observation = build_adapter_quality_observation(
                observation_id=f"{surface_kind}-quality",
                subject_id="checkout",
                surface_kind=surface_kind,
                adapter_id="hermes-adapter",
                source_revision="build-42",
                checks=[{"check_id": "checkout", "kind": "functional", "status": "pass", "expected_summary": "Checkout opens", "actual_summary": "Checkout opens", "evidence_refs": ["adapter:check-1"]}],
                layout_checks=[{"check_id": "desktop", "scope": "desktop", "status": "pass", "summary": "No overlap", "evidence_refs": ["adapter:layout-1"]}],
                metrics=[{"metric_id": "startup", "name": "Startup", "value": 120.0, "unit": "ms", "threshold": 250.0, "comparison": "lte", "status": "pass", "evidence_refs": ["adapter:metric-1"]}],
            )
            self.assertEqual(observation["surface_kind"], surface_kind)
            self.assertEqual(observation["overall_evidence_state"], "observed_no_failures")

    def test_delivery_requires_matching_prepared_card_and_stales_on_revision_change(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            observation = build_adapter_quality_observation(
                observation_id="desktop-quality",
                subject_id="checkout",
                surface_kind="desktop",
                adapter_id="hermes-adapter",
                source_revision="build-42",
                checks=[],
                layout_checks=[],
                metrics=[],
            )
            card = build_adapter_quality_delivery_card(observation, renderer_target="slack")
            preparation = prepare_adapter_quality_delivery(paths, session_id="ws-quality", card=card)
            delivery = record_adapter_quality_delivery(paths, preparation=preparation, adapter="slack-adapter", delivery_result="delivered", external_message_ref="slack:message-1")

            self.assertEqual(delivery["observation_status"], "observed")
            stale_card = build_adapter_quality_delivery_card({**observation, "source_revision": "build-43"}, renderer_target="slack")
            self.assertNotEqual(stale_card["card_fingerprint"], delivery["card_fingerprint"])

    def test_raw_log_and_unbounded_metric_do_not_validate(self) -> None:
        with self.assertRaises(ValueError):
            build_adapter_quality_observation(
                observation_id="bad-quality",
                subject_id="checkout",
                surface_kind="web",
                adapter_id="hermes-adapter",
                source_revision="build-42",
                debug_signals=[{"signal_id": "log", "kind": "error", "severity": "error", "status": "observed", "summary": "https://host/?token=secret", "evidence_refs": ["adapter:log-1"]}],
                checks=[],
                layout_checks=[],
                metrics=[],
            )

    def test_session_control_fails_closed_until_selected_observation_is_current(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            link_adapter_quality_session(paths, session_id="ws-quality", subject_id="checkout", surface_kind="web", source_revision="build-42")
            self.assertEqual(quality_session_control(paths, "ws-quality")["status"], "linked_no_observation")
            observation = write_adapter_quality_observation(paths, build_adapter_quality_observation(observation_id="web-quality", subject_id="checkout", surface_kind="web", adapter_id="hermes-adapter", source_revision="build-42", checks=[], layout_checks=[], metrics=[]))
            self.assertEqual(observation["overall_evidence_state"], "partial_observed")
            link_adapter_quality_session(paths, session_id="ws-quality", subject_id="checkout", surface_kind="web", source_revision="build-42", observation_id="web-quality")
            self.assertEqual(quality_session_control(paths, "ws-quality")["status"], "quality_observed")
            link_adapter_quality_session(paths, session_id="ws-quality", subject_id="checkout", surface_kind="web", source_revision="build-43", observation_id="web-quality")
            self.assertEqual(quality_session_control(paths, "ws-quality")["status"], "stale")
        with self.assertRaises(ValueError):
            build_adapter_quality_observation(
                observation_id="bad-metric",
                subject_id="checkout",
                surface_kind="web",
                adapter_id="hermes-adapter",
                source_revision="build-42",
                checks=[],
                layout_checks=[],
                metrics=[{"metric_id": "startup", "name": "Startup", "value": 120.0, "unit": "ms", "threshold": 1_000_000_001.0, "comparison": "lte", "status": "pass", "evidence_refs": ["adapter:metric-1"]}],
            )


if __name__ == "__main__":
    unittest.main()
