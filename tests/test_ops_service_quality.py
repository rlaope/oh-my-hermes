from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests._local_package import load_local_package

load_local_package()
from omh.ops_service_quality import (
    ExternalMetricProviderInput,
    MetricObservationInput,
    ProviderAdapterInput,
    ServiceQualityBoardInput,
    build_external_metric_provider,
    build_ops_service_quality_board,
    build_provider_adapter,
    validate_external_metric_provider,
    validate_ops_service_quality_board,
    validate_provider_adapter,
)
from tests._ops_quality_helpers import object_items, string_field_values, string_items


class OpsServiceQualityTests(unittest.TestCase):
    def test_service_quality_board_keeps_supplied_metrics_evidence_bounded(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="prod-prometheus-export",
                provider_kind="prometheus",
                display_name="Prometheus export",
                metric_window="2026-07-02T09:00:00Z/2026-07-02T10:00:00Z",
                freshness="exported_at=2026-07-02T10:01:00Z",
                source_refs=("s3://ops-fixtures/prometheus-api.json",),
                metrics=(
                    MetricObservationInput("api_availability", "99.95", "%", "promql:up"),
                    MetricObservationInput("p95_latency_ms", "220", "ms", "promql:histogram_quantile"),
                ),
                slo_targets=("api_availability>=99.9",),
                incident_refs=("INC-42",),
            )
        )
        adapter = build_provider_adapter(
            ProviderAdapterInput(
                adapter_id="prometheus-json-export",
                provider_kind="prometheus",
                input_contract="prometheus_http_api_export",
                connector_status="prepared",
                observed_evidence_refs=("fixture://examples/ops-service-quality/prometheus-like.json",),
            )
        )

        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Checkout API service quality",
                providers=(provider,),
                adapters=(adapter,),
                created_at="2026-07-02T10:02:00Z",
            )
        )

        self.assertEqual(board["schema_version"], "ops_service_quality_board/v1")
        self.assertEqual(board["surface"], "ops-observability-card")
        self.assertEqual(board["observation_status"], "prepared")
        self.assertEqual(board["service_quality_claim"], "evidence_gated_summary")
        self.assertIn("external_metric_provider/v1", string_items(board, "accepted_input_contracts"))
        self.assertIn("external_metric_provider_adapter/v1", string_items(board, "accepted_input_contracts"))
        self.assertIn("reliability-review", string_field_values(board, "specialist_lanes", "workflow"))
        self.assertIn("workflow-learning", string_field_values(board, "specialist_lanes", "workflow"))
        self.assertIn("provider_truth_not_observed", string_field_values(board, "downgrade_gaps", "code"))
        self.assertIn("connector_not_observed", string_field_values(board, "downgrade_gaps", "code"))
        self.assertIn("provider billing truth", string_items(board, "not_evidence_until_observed"))
        self.assertEqual(validate_external_metric_provider(provider), [])
        self.assertEqual(validate_provider_adapter(adapter), [])
        self.assertEqual(validate_ops_service_quality_board(board), [])

    def test_missing_operational_evidence_stays_typed_downgrade_gaps(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="grafana-panel-export",
                provider_kind="grafana",
                display_name="Grafana panel export",
                metrics=(MetricObservationInput("error_rate", "0.2", "%", "panel:error-rate"),),
            )
        )

        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="API quality board",
                providers=(provider,),
                created_at="2026-07-02T10:03:00Z",
            )
        )

        gap_codes = string_field_values(board, "downgrade_gaps", "code")
        self.assertTrue(
            {
                "missing_metric_window",
                "missing_source_refs",
                "missing_freshness",
                "missing_slo_target",
                "missing_incident_reference",
                "missing_remediation_evidence",
                "provider_truth_not_observed",
                "connector_not_observed",
            }.issubset(gap_codes)
        )
        self.assertEqual(board["service_health"], "not_assessed")
        self.assertEqual(validate_ops_service_quality_board(board), [])

    def test_provider_truth_and_connector_claims_require_observed_evidence_refs(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="live-provider",
                provider_kind="prometheus",
                display_name="Prometheus",
                provider_truth_observed=True,
            )
        )
        adapter = build_provider_adapter(
            ProviderAdapterInput(
                adapter_id="live-adapter",
                provider_kind="prometheus",
                input_contract="prometheus_http_api",
                connector_status="observed",
            )
        )

        self.assertIn("provider_truth_observed requires observed_evidence_refs", "; ".join(validate_external_metric_provider(provider)))
        self.assertIn("observed connectors require observed_evidence_refs", "; ".join(validate_provider_adapter(adapter)))

    def test_board_keeps_connector_gap_when_observed_adapter_does_not_match_provider_kind(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="live-prometheus",
                provider_kind="prometheus",
                display_name="Prometheus",
                metric_window="30m",
                freshness="queried_at=2026-07-02T10:00:00Z",
                source_refs=("prometheus://api/v1/query",),
                slo_targets=("availability>=99.9",),
                incident_refs=("INC-42",),
                remediation_refs=("RUNBOOK-9",),
                provider_truth_observed=True,
                observed_evidence_refs=("evidence://prometheus/query/42",),
            )
        )
        adapter = build_provider_adapter(
            ProviderAdapterInput(
                adapter_id="observed-grafana",
                provider_kind="grafana",
                input_contract="grafana_panel_export",
                connector_status="observed",
                observed_evidence_refs=("evidence://grafana/panel/9",),
            )
        )

        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Mismatched connector evidence",
                providers=(provider,),
                adapters=(adapter,),
                created_at="2026-07-02T10:10:00Z",
            )
        )

        self.assertIn("connector_not_observed", string_field_values(board, "downgrade_gaps", "code"))
        self.assertEqual(validate_ops_service_quality_board(board), [])

    def test_example_fixtures_match_generated_contracts(self) -> None:
        prometheus_fixture = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Checkout API service quality",
                providers=(
                    build_external_metric_provider(
                        ExternalMetricProviderInput(
                            provider_id="prod-prometheus-export",
                            provider_kind="prometheus",
                            display_name="Prometheus export",
                            metric_window="2026-07-02T09:00:00Z/2026-07-02T10:00:00Z",
                            freshness="exported_at=2026-07-02T10:01:00Z",
                            source_refs=("s3://ops-fixtures/prometheus-api.json",),
                            metrics=(
                                MetricObservationInput("api_availability", "99.95", "%", "promql:up"),
                                MetricObservationInput("p95_latency_ms", "220", "ms", "promql:histogram_quantile"),
                            ),
                            slo_targets=("api_availability>=99.9",),
                            incident_refs=("INC-42",),
                        )
                    ),
                ),
                adapters=(
                    build_provider_adapter(
                        ProviderAdapterInput(
                            adapter_id="prometheus-json-export",
                            provider_kind="prometheus",
                            input_contract="prometheus_http_api_export",
                            connector_status="prepared",
                            observed_evidence_refs=("fixture://examples/ops-service-quality/prometheus-like.json",),
                        )
                    ),
                ),
                created_at="2026-07-02T10:02:00Z",
            )
        )
        grafana_fixture = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="API quality board from Grafana-like panel export",
                providers=(
                    build_external_metric_provider(
                        ExternalMetricProviderInput(
                            provider_id="grafana-panel-export",
                            provider_kind="grafana",
                            display_name="Grafana panel export",
                            metrics=(MetricObservationInput("error_rate", "0.2", "%", "panel:error-rate"),),
                        )
                    ),
                ),
                adapters=(
                    build_provider_adapter(
                        ProviderAdapterInput(
                            adapter_id="grafana-panel-json-export",
                            provider_kind="grafana",
                            input_contract="grafana_panel_json_export",
                            connector_status="prepared",
                        )
                    ),
                ),
                created_at="2026-07-02T10:03:00Z",
            )
        )

        self.assertEqual(Path("examples/ops-service-quality/prometheus-like.json").read_text(encoding="utf-8"), json.dumps(prometheus_fixture, indent=2) + "\n")
        self.assertEqual(Path("examples/ops-service-quality/grafana-like.json").read_text(encoding="utf-8"), json.dumps(grafana_fixture, indent=2) + "\n")
        self.assertEqual(validate_ops_service_quality_board(prometheus_fixture), [])
        self.assertEqual(validate_ops_service_quality_board(grafana_fixture), [])
        self.assertEqual(object_items(prometheus_fixture, "metric_providers")[0]["provider_kind"], "prometheus")
        self.assertEqual(object_items(grafana_fixture, "metric_providers")[0]["provider_kind"], "grafana")
        self.assertIn("connector_not_observed", string_field_values(prometheus_fixture, "downgrade_gaps", "code"))
        self.assertIn("missing_slo_target", string_field_values(grafana_fixture, "downgrade_gaps", "code"))


if __name__ == "__main__":
    _ = unittest.main()
