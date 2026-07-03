from __future__ import annotations

from collections.abc import Iterable

from omh.local_store import utc_now
from .ops_service_quality_gaps import downgrade_gaps
from .ops_service_quality_contracts import (
    BOARD_KIND,
    BOARD_SURFACE,
    DOWNGRADE_GAP_CODES,
    EXTERNAL_METRIC_PROVIDER_ADAPTER_SCHEMA_VERSION,
    EXTERNAL_METRIC_PROVIDER_SCHEMA_VERSION,
    NOT_EVIDENCE_UNTIL_OBSERVED,
    OPS_SERVICE_QUALITY_BOARD_SCHEMA_VERSION,
    SUPPORTED_ADAPTER_STATUSES,
    SUPPORTED_SERVICE_CLAIMS,
    SUPPORTED_SERVICE_HEALTH,
    ExternalMetricProviderInput,
    JsonObject,
    JsonValue,
    MetricObservationInput,
    ProviderAdapterInput,
    ServiceQualityBoardInput,
)


def build_external_metric_provider(config: ExternalMetricProviderInput) -> JsonObject:
    return {
        "schema_version": EXTERNAL_METRIC_PROVIDER_SCHEMA_VERSION,
        "provider_id": config.provider_id.strip(),
        "provider_kind": config.provider_kind.strip(),
        "display_name": config.display_name.strip(),
        "metric_window": config.metric_window.strip(),
        "freshness": config.freshness.strip(),
        "source_refs": _strings(config.source_refs),
        "metrics": _json_array(_metric_payload(metric) for metric in config.metrics),
        "slo_targets": _strings(config.slo_targets),
        "incident_refs": _strings(config.incident_refs),
        "remediation_refs": _strings(config.remediation_refs),
        "provider_truth_observed": config.provider_truth_observed,
        "observed_evidence_refs": _strings(config.observed_evidence_refs),
        "claim_boundary": "Supplied provider payloads are evidence inputs only, not live provider truth.",
    }


def build_provider_adapter(config: ProviderAdapterInput) -> JsonObject:
    return {
        "schema_version": EXTERNAL_METRIC_PROVIDER_ADAPTER_SCHEMA_VERSION,
        "adapter_id": config.adapter_id.strip(),
        "provider_kind": config.provider_kind.strip(),
        "input_contract": config.input_contract.strip(),
        "connector_status": config.connector_status.strip() or "prepared",
        "observed_evidence_refs": _strings(config.observed_evidence_refs),
        "claim_boundary": "Adapter metadata is connector-ready shape only unless observed evidence refs prove invocation.",
    }


def build_ops_service_quality_board(config: ServiceQualityBoardInput) -> JsonObject:
    providers = _json_objects(config.providers)
    adapters = _json_objects(config.adapters)
    gaps = downgrade_gaps(providers, adapters)
    created_at = config.created_at.strip() or utc_now()
    return {
        "schema_version": OPS_SERVICE_QUALITY_BOARD_SCHEMA_VERSION,
        "kind": BOARD_KIND,
        "surface": BOARD_SURFACE,
        "title": config.title.strip(),
        "created_at": created_at,
        "updated_at": created_at,
        "status": "prepared",
        "observation_status": "prepared",
        "service_quality_claim": "evidence_gated_summary",
        "service_health": "not_assessed",
        "accepted_input_contracts": _json_array((
            EXTERNAL_METRIC_PROVIDER_SCHEMA_VERSION,
            EXTERNAL_METRIC_PROVIDER_ADAPTER_SCHEMA_VERSION,
        )),
        "metric_providers": _json_array(providers),
        "provider_adapters": _json_array(adapters),
        "downgrade_gaps": _json_array(gaps),
        "specialist_lanes": _json_array((
            {
                "workflow": "reliability-review",
                "purpose": "Review SLOs, incidents, error budgets, and remediation evidence with stricter SRE gates.",
            },
            {
                "workflow": "workflow-learning",
                "purpose": "Route recurring gaps or missed workflow behavior into reviewed learning artifacts.",
            },
        )),
        "analysis_methods": _json_array((
            "compare metric window, freshness, source refs, SLO targets, incident refs, and remediation evidence",
            "downgrade any unsupported service-health, outage, root-cause, or remediation claim to typed missing evidence",
            "separate supplied metric evidence from live provider, billing, quota, account, or connector truth",
        )),
        "not_evidence_until_observed": _strings(NOT_EVIDENCE_UNTIL_OBSERVED),
    }


def validate_external_metric_provider(record: JsonObject) -> list[str]:
    errors: list[str] = []
    if _text(record.get("schema_version")) != EXTERNAL_METRIC_PROVIDER_SCHEMA_VERSION:
        errors.append("schema_version must be external_metric_provider/v1")
    for key in ("provider_id", "provider_kind", "display_name"):
        if not _text(record.get(key)):
            errors.append(f"{key} is required")
    _require_list(record, "source_refs", errors)
    _require_list(record, "metrics", errors)
    for index, metric in enumerate(_items(record.get("metrics"))):
        if not isinstance(metric, dict):
            errors.append(f"metrics[{index}] must be an object")
            continue
        if not _text(metric.get("name")):
            errors.append(f"metrics[{index}].name is required")
        if not _text(metric.get("value")):
            errors.append(f"metrics[{index}].value is required")
    _require_list(record, "slo_targets", errors)
    _require_list(record, "incident_refs", errors)
    _require_list(record, "remediation_refs", errors)
    _require_list(record, "observed_evidence_refs", errors)
    if record.get("provider_truth_observed") is True and not _items(record.get("observed_evidence_refs")):
        errors.append("provider_truth_observed requires observed_evidence_refs")
    return errors


def validate_provider_adapter(record: JsonObject) -> list[str]:
    errors: list[str] = []
    if _text(record.get("schema_version")) != EXTERNAL_METRIC_PROVIDER_ADAPTER_SCHEMA_VERSION:
        errors.append("schema_version must be external_metric_provider_adapter/v1")
    for key in ("adapter_id", "provider_kind", "input_contract"):
        if not _text(record.get(key)):
            errors.append(f"{key} is required")
    connector_status = _text(record.get("connector_status"))
    if connector_status not in SUPPORTED_ADAPTER_STATUSES:
        errors.append(f"unsupported connector_status: {connector_status}")
    if connector_status == "observed" and not _items(record.get("observed_evidence_refs")):
        errors.append("observed connectors require observed_evidence_refs")
    _require_list(record, "observed_evidence_refs", errors)
    return errors


def validate_ops_service_quality_board(record: JsonObject) -> list[str]:
    errors: list[str] = []
    if _text(record.get("schema_version")) != OPS_SERVICE_QUALITY_BOARD_SCHEMA_VERSION:
        errors.append("schema_version must be ops_service_quality_board/v1")
    if _text(record.get("kind")) != BOARD_KIND:
        errors.append("kind must be ops_service_quality_board")
    if _text(record.get("surface")) != BOARD_SURFACE:
        errors.append("surface must be ops-observability-card")
    if _text(record.get("status")) != "prepared":
        errors.append("status must remain prepared")
    if _text(record.get("observation_status")) != "prepared":
        errors.append("observation_status must remain prepared")
    if not _text(record.get("title")):
        errors.append("title is required")
    if _text(record.get("service_quality_claim")) not in SUPPORTED_SERVICE_CLAIMS:
        errors.append("service_quality_claim must stay evidence-gated")
    if _text(record.get("service_health")) not in SUPPORTED_SERVICE_HEALTH:
        errors.append("service_health must remain not_assessed without observed reliability evidence")
    _require_object_items(record, "metric_providers", errors)
    _require_object_items(record, "provider_adapters", errors)
    _require_object_items(record, "downgrade_gaps", errors)
    providers = _objects(record.get("metric_providers"))
    adapters = _objects(record.get("provider_adapters"))
    gaps = _objects(record.get("downgrade_gaps"))
    if not providers:
        errors.append("metric_providers must include at least one external_metric_provider/v1 payload")
    for provider in providers:
        errors.extend(validate_external_metric_provider(provider))
    for adapter in adapters:
        errors.extend(validate_provider_adapter(adapter))
    accepted_contracts = {_text(item) for item in _items(record.get("accepted_input_contracts"))}
    required_contracts = {
        EXTERNAL_METRIC_PROVIDER_SCHEMA_VERSION,
        EXTERNAL_METRIC_PROVIDER_ADAPTER_SCHEMA_VERSION,
    }
    missing_contracts = sorted(required_contracts - accepted_contracts)
    if missing_contracts:
        errors.append(f"accepted_input_contracts must include: {', '.join(missing_contracts)}")
    extra_contracts = sorted(contract for contract in accepted_contracts if contract and contract not in required_contracts)
    if extra_contracts:
        errors.append(f"accepted_input_contracts contains unsupported contracts: {', '.join(extra_contracts)}")
    gap_code_list = [_text(gap.get("code")) for gap in gaps]
    gap_codes = set(gap_code_list)
    duplicate_gap_codes = sorted({code for code in gap_code_list if code and gap_code_list.count(code) > 1})
    if duplicate_gap_codes:
        errors.append(f"downgrade_gaps contains duplicate codes: {', '.join(duplicate_gap_codes)}")
    required_gaps = {_text(gap.get("code")): gap for gap in downgrade_gaps(providers, adapters)}
    required_gap_codes = set(required_gaps)
    missing_gap_codes = sorted(code for code in required_gap_codes if code and code not in gap_codes)
    if missing_gap_codes:
        errors.append(f"downgrade_gaps missing required codes: {', '.join(missing_gap_codes)}")
    extra_gap_codes = sorted(code for code in gap_codes if code and code not in required_gap_codes)
    extra_known_gap_codes = [code for code in extra_gap_codes if code in DOWNGRADE_GAP_CODES]
    if extra_known_gap_codes:
        errors.append(f"downgrade_gaps contains non-required codes: {', '.join(extra_known_gap_codes)}")
    gaps_by_code = {_text(gap.get("code")): gap for gap in gaps}
    for code, required_gap in required_gaps.items():
        gap = gaps_by_code.get(code)
        if gap is None:
            continue
        if _text(gap.get("status")) != _text(required_gap.get("status")):
            errors.append(f"downgrade_gaps {code} status must be missing_or_not_observed")
        if _text(gap.get("message")) != _text(required_gap.get("message")):
            errors.append(f"downgrade_gaps {code} message must match canonical missing evidence")
    unknown_codes = sorted(code for code in gap_codes if code and code not in DOWNGRADE_GAP_CODES)
    if unknown_codes:
        errors.append(f"unsupported downgrade gap codes: {', '.join(unknown_codes)}")
    _require_list(record, "accepted_input_contracts", errors)
    _require_list(record, "specialist_lanes", errors)
    _require_list(record, "analysis_methods", errors)
    _require_list(record, "not_evidence_until_observed", errors)
    lane_workflows = {_text(lane.get("workflow")) for lane in _objects(record.get("specialist_lanes"))}
    for workflow in ("reliability-review", "workflow-learning"):
        if workflow not in lane_workflows:
            errors.append(f"specialist_lanes must include {workflow}")
    not_evidence = {_text(item) for item in _items(record.get("not_evidence_until_observed"))}
    for boundary in NOT_EVIDENCE_UNTIL_OBSERVED:
        if boundary not in not_evidence:
            errors.append(f"not_evidence_until_observed must include {boundary}")
    return errors


def _metric_payload(metric: MetricObservationInput) -> JsonObject:
    return {
        "name": metric.name.strip(),
        "value": metric.value.strip(),
        "unit": metric.unit.strip(),
        "source_ref": metric.source_ref.strip(),
    }


def _strings(values: tuple[str, ...]) -> list[JsonValue]:
    return [value.strip() for value in values if value.strip()]


def _json_array(values: Iterable[JsonValue]) -> list[JsonValue]:
    return list(values)


def _json_objects(values: tuple[JsonObject, ...]) -> list[JsonObject]:
    return list(values)


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _items(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def _objects(value: JsonValue) -> list[JsonObject]:
    return [item for item in _items(value) if isinstance(item, dict)]


def _require_list(record: JsonObject, key: str, errors: list[str]) -> None:
    if not isinstance(record.get(key), list):
        errors.append(f"{key} must be a list")


def _require_object_items(record: JsonObject, key: str, errors: list[str]) -> None:
    value = record.get(key)
    if not isinstance(value, list):
        errors.append(f"{key} must be a list")
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{key}[{index}] must be an object")
