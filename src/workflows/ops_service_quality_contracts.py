from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

EXTERNAL_METRIC_PROVIDER_SCHEMA_VERSION: Final = "external_metric_provider/v1"
EXTERNAL_METRIC_PROVIDER_ADAPTER_SCHEMA_VERSION: Final = "external_metric_provider_adapter/v1"
OPS_SERVICE_QUALITY_BOARD_SCHEMA_VERSION: Final = "ops_service_quality_board/v1"

BOARD_SURFACE: Final = "ops-observability-card"
BOARD_KIND: Final = "ops_service_quality_board"
SUPPORTED_ADAPTER_STATUSES: Final = ("prepared", "observed", "not_observed")
SUPPORTED_SERVICE_CLAIMS: Final = ("evidence_gated_summary", "not_assessed")
SUPPORTED_SERVICE_HEALTH: Final = ("not_assessed",)
DOWNGRADE_GAP_CODES: Final = (
    "missing_metric_window",
    "missing_source_refs",
    "missing_freshness",
    "missing_slo_target",
    "missing_incident_reference",
    "missing_remediation_evidence",
    "provider_truth_not_observed",
    "connector_not_observed",
)

NOT_EVIDENCE_UNTIL_OBSERVED: Final = (
    "provider billing truth",
    "provider quota truth",
    "live provider account state",
    "live connector invocation",
    "SLO pass",
    "incident closure",
    "root cause confirmation",
    "remediation complete",
    "service health verdict",
)


@dataclass(frozen=True, slots=True)
class MetricObservationInput:
    name: str
    value: str
    unit: str = ""
    source_ref: str = ""


@dataclass(frozen=True, slots=True)
class ExternalMetricProviderInput:
    provider_id: str
    provider_kind: str
    display_name: str
    metric_window: str = ""
    freshness: str = ""
    source_refs: tuple[str, ...] = ()
    metrics: tuple[MetricObservationInput, ...] = ()
    slo_targets: tuple[str, ...] = ()
    incident_refs: tuple[str, ...] = ()
    remediation_refs: tuple[str, ...] = ()
    provider_truth_observed: bool = False
    observed_evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderAdapterInput:
    adapter_id: str
    provider_kind: str
    input_contract: str
    connector_status: str = "prepared"
    observed_evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ServiceQualityBoardInput:
    title: str
    providers: tuple[JsonObject, ...]
    adapters: tuple[JsonObject, ...] = ()
    created_at: str = ""
