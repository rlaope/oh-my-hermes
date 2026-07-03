from __future__ import annotations

from .ops_service_quality_contracts import JsonObject, JsonValue


def downgrade_gaps(providers: list[JsonObject], adapters: list[JsonObject]) -> list[JsonObject]:
    checks = (
        ("missing_metric_window", not any(_text(provider.get("metric_window")) for provider in providers), "No metric window was supplied."),
        ("missing_source_refs", not any(_items(provider.get("source_refs")) for provider in providers), "No source refs were supplied."),
        ("missing_freshness", not any(_text(provider.get("freshness")) for provider in providers), "No freshness marker was supplied."),
        ("missing_slo_target", not any(_items(provider.get("slo_targets")) for provider in providers), "No SLO target was supplied."),
        ("missing_incident_reference", not any(_items(provider.get("incident_refs")) for provider in providers), "No incident reference was supplied."),
        (
            "missing_remediation_evidence",
            not any(_items(provider.get("remediation_refs")) for provider in providers),
            "No remediation evidence was supplied.",
        ),
        (
            "provider_truth_not_observed",
            not providers or not all(provider.get("provider_truth_observed") is True for provider in providers),
            "Provider truth was not observed by OMH.",
        ),
        (
            "connector_not_observed",
            not _all_provider_connectors_observed(providers, adapters),
            "No live provider connector invocation was observed.",
        ),
    )
    return [{"code": code, "message": message, "status": "missing_or_not_observed"} for code, missing, message in checks if missing]


def _all_provider_connectors_observed(providers: list[JsonObject], adapters: list[JsonObject]) -> bool:
    if not providers:
        return False
    observed_adapter_kinds = _observed_adapter_kinds(adapters)
    return all(_provider_kind(provider) in observed_adapter_kinds for provider in providers)


def _observed_adapter_kinds(adapters: list[JsonObject]) -> set[str]:
    adapter_kinds: set[str] = set()
    for adapter in adapters:
        provider_kind = _provider_kind(adapter)
        if provider_kind and _text(adapter.get("connector_status")) == "observed" and _items(adapter.get("observed_evidence_refs")):
            adapter_kinds.add(provider_kind)
    return adapter_kinds


def _provider_kind(record: JsonObject) -> str:
    return _text(record.get("provider_kind")).strip()


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _items(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []
