from __future__ import annotations

import unittest

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
)
from tests._ops_quality_helpers import object_items


class OpsServiceQualityValidationTests(unittest.TestCase):
    def test_board_validation_rejects_removed_required_gaps_and_boundaries(self) -> None:
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
                title="Tampered API quality board",
                providers=(provider,),
                created_at="2026-07-02T10:04:00Z",
            )
        )
        board["downgrade_gaps"] = []
        board["accepted_input_contracts"] = ["external_metric_provider/v1"]
        board["specialist_lanes"] = [{"workflow": "reliability-review"}]
        board["not_evidence_until_observed"] = ["provider billing truth"]

        errors = "; ".join(validate_ops_service_quality_board(board))

        self.assertIn("downgrade_gaps missing required codes", errors)
        self.assertIn("accepted_input_contracts must include: external_metric_provider_adapter/v1", errors)
        self.assertIn("specialist_lanes must include workflow-learning", errors)
        self.assertIn("not_evidence_until_observed must include provider quota truth", errors)

    def test_board_validation_enforces_top_level_official_shape(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="prometheus-export",
                provider_kind="prometheus",
                display_name="Prometheus export",
                metric_window="30m",
                freshness="exported_at=2026-07-02T09:00:00Z",
                source_refs=("prometheus://api/v1/query",),
            )
        )
        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Tampered service quality board",
                providers=(provider,),
                created_at="2026-07-02T10:05:00Z",
            )
        )
        board["kind"] = "generic_dashboard"
        board["status"] = "observed"
        board["observation_status"] = "observed"
        board["accepted_input_contracts"] = [
            "external_metric_provider/v1",
            "external_metric_provider_adapter/v1",
            "legacy_dashboard/v0",
        ]

        errors = "; ".join(validate_ops_service_quality_board(board))

        self.assertIn("kind must be ops_service_quality_board", errors)
        self.assertIn("status must remain prepared", errors)
        self.assertIn("observation_status must remain prepared", errors)
        self.assertIn("accepted_input_contracts contains unsupported contracts: legacy_dashboard/v0", errors)

    def test_board_validation_rejects_tampered_gap_claims(self) -> None:
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
                title="Tampered gap board",
                providers=(provider,),
                created_at="2026-07-02T10:06:00Z",
            )
        )
        for gap in object_items(board, "downgrade_gaps"):
            if gap["code"] == "provider_truth_not_observed":
                gap["status"] = "observed"
                gap["message"] = "Provider truth observed and SLO healthy"

        errors = "; ".join(validate_ops_service_quality_board(board))

        self.assertIn("downgrade_gaps provider_truth_not_observed status must be missing_or_not_observed", errors)
        self.assertIn("downgrade_gaps provider_truth_not_observed message must match canonical missing evidence", errors)

    def test_board_validation_rejects_duplicate_gap_overclaims(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="grafana-panel-export",
                provider_kind="grafana",
                display_name="Grafana panel export",
            )
        )
        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Duplicate gap board",
                providers=(provider,),
                created_at="2026-07-02T10:07:00Z",
            )
        )
        board["downgrade_gaps"] = [
            {
                "code": "provider_truth_not_observed",
                "status": "observed",
                "message": "Provider truth observed and SLO healthy",
            },
            *object_items(board, "downgrade_gaps"),
        ]

        errors = "; ".join(validate_ops_service_quality_board(board))

        self.assertIn("downgrade_gaps contains duplicate codes: provider_truth_not_observed", errors)

    def test_board_validation_rejects_extra_gap_overclaims_when_gap_is_not_required(self) -> None:
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
                adapter_id="observed-prometheus",
                provider_kind="prometheus",
                input_contract="prometheus_http_api",
                connector_status="observed",
                observed_evidence_refs=("evidence://prometheus/connector/42",),
            )
        )
        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Fully observed connector board",
                providers=(provider,),
                adapters=(adapter,),
                created_at="2026-07-02T10:11:00Z",
            )
        )
        board["downgrade_gaps"] = [
            {
                "code": "connector_not_observed",
                "status": "observed",
                "message": "Connector observed and service healthy",
            }
        ]

        errors = "; ".join(validate_ops_service_quality_board(board))

        self.assertIn("downgrade_gaps contains non-required codes: connector_not_observed", errors)

    def test_board_validation_rejects_malformed_top_level_list_items(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="prometheus-export",
                provider_kind="prometheus",
                display_name="Prometheus export",
                source_refs=("prometheus://api/v1/query",),
                metric_window="30m",
                freshness="exported_at=2026-07-02T09:00:00Z",
            )
        )
        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Malformed list board",
                providers=(provider,),
                created_at="2026-07-02T10:08:00Z",
            )
        )
        board["metric_providers"] = [*object_items(board, "metric_providers"), "not-a-provider"]
        board["provider_adapters"] = [*object_items(board, "provider_adapters"), "not-an-adapter"]
        board["downgrade_gaps"] = [*object_items(board, "downgrade_gaps"), "not-a-gap"]

        errors = "; ".join(validate_ops_service_quality_board(board))

        self.assertIn("metric_providers[1] must be an object", errors)
        self.assertIn("provider_adapters[0] must be an object", errors)
        self.assertIn("downgrade_gaps[", errors)
        self.assertIn("must be an object", errors)

    def test_board_validation_rejects_missing_or_non_list_top_level_lists(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="prometheus-export",
                provider_kind="prometheus",
                display_name="Prometheus export",
                source_refs=("prometheus://api/v1/query",),
            )
        )
        board = build_ops_service_quality_board(
            ServiceQualityBoardInput(
                title="Malformed list board",
                providers=(provider,),
                created_at="2026-07-02T10:09:00Z",
            )
        )

        missing = dict(board)
        del missing["provider_adapters"]
        non_list = {
            **board,
            "metric_providers": "not-a-provider-list",
            "provider_adapters": "not-an-adapter-list",
            "downgrade_gaps": "not-a-gap-list",
        }

        missing_errors = "; ".join(validate_ops_service_quality_board(missing))
        non_list_errors = "; ".join(validate_ops_service_quality_board(non_list))

        self.assertIn("provider_adapters must be a list", missing_errors)
        self.assertIn("metric_providers must be a list", non_list_errors)
        self.assertIn("provider_adapters must be a list", non_list_errors)
        self.assertIn("downgrade_gaps must be a list", non_list_errors)

    def test_provider_validation_rejects_malformed_metric_items(self) -> None:
        provider = build_external_metric_provider(
            ExternalMetricProviderInput(
                provider_id="prometheus-export",
                provider_kind="prometheus",
                display_name="Prometheus export",
                metrics=(MetricObservationInput("availability", "99.9", "%", "promql:up"),),
            )
        )
        provider["metrics"] = [{"value": "99.9"}, "not-a-metric"]

        errors = "; ".join(validate_external_metric_provider(provider))

        self.assertIn("metrics[0].name is required", errors)
        self.assertIn("metrics[1] must be an object", errors)


if __name__ == "__main__":
    _ = unittest.main()
