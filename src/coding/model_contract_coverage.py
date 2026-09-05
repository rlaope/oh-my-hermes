"""Deterministic model-contract coverage over caller-supplied inventories.

The report is a pure comparison between bounded model identifiers and OMH's
shipped contracts/recommendations. It performs no discovery or provider calls,
changes no configuration or route, and treats inventory presence as catalog
evidence only — never availability, entitlement, or execution evidence.
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Final, Iterable, Mapping

from ..system.metadata_safety import require_opaque_metadata_ref
from .model_contracts import model_contract, model_contract_projection
from .model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS
from .model_routing import model_family
from .unit_prompt_protocol import (
    MODEL_COMPOSITION_CALIBRATIONS,
    MODEL_HIGH_EFFORT_CALIBRATIONS,
)

MODEL_CONTRACT_COVERAGE_SCHEMA_VERSION: Final[str] = "model_contract_coverage/v1"
MODEL_CONTRACT_COVERAGE_CLAIM_BOUNDARY: Final[str] = (
    "This deterministic report compares supplied inventory identifiers with shipped OMH metadata. "
    "Catalog presence and declared inheritance are not evidence of provider availability, account "
    "entitlement, wire translation, dispatch, or execution; the host/runtime owns those observations."
)
MODEL_CONTRACT_COVERAGE_STATUSES: Final[tuple[str, ...]] = (
    "exact",
    "declared_inheritance",
    "intentional_exclusion",
    "missing",
)
_INVENTORY_STATUSES: Final[frozenset[str]] = frozenset({"observed", "cold", "unavailable"})
_SERVICE_TIER_MULTIPLIERS: Final[dict[str, float]] = {"fast": 2.0, "flex": 0.5}
_SOURCE_LINEAGE_KEY: Final[str] = "provenance"
_MODEL_DOCS: Final[dict[str, tuple[str, ...]]] = {
    "gpt-6-astra": ("MODEL_OPTI.md", "docs/MODEL-ONBOARDING.md"),
}


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _digest(value: object) -> str:
    return sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _model_ref(value: object) -> str:
    return require_opaque_metadata_ref(value, field="model_id")


def _inventory_ref(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"inventory {field} must be a non-empty string")
    try:
        return require_opaque_metadata_ref(value, field=field)
    except ValueError as exc:
        raise ValueError(f"inventory {field} must be a safe opaque metadata reference") from exc


def _validate_optional_inventory_refs(
    mapping: Mapping[str, object],
    *,
    fields: tuple[str, ...],
    context: str,
) -> None:
    for field in fields:
        if field in mapping:
            _inventory_ref(mapping[field], field=f"{context}.{field}")


def _list_value(mapping: Mapping[str, object], key: str) -> list[object]:
    value = mapping.get(key, ())
    return list(value) if isinstance(value, (list, tuple)) else []


def _validate_inventory_shape(inventory: Mapping[str, object]) -> None:
    inventory_fields = ("models", "available_models", "model_discovery")
    if not any(field in inventory for field in inventory_fields):
        raise ValueError(
            "inventory must include models, available_models, or model_discovery"
        )

    for field in ("models", "available_models"):
        value = inventory.get(field)
        if field in inventory and not isinstance(value, (list, tuple)):
            raise ValueError(f"inventory {field} must be a JSON array")

    _validate_optional_inventory_refs(
        inventory,
        fields=("inventory_status", "status", "schema_version"),
        context="metadata",
    )
    if "source" in inventory:
        _inventory_ref(inventory["source"], field="inventory_source")
    if "digest" in inventory:
        _inventory_ref(inventory["digest"], field="inventory_digest")
    if _SOURCE_LINEAGE_KEY in inventory:
        provenance = inventory[_SOURCE_LINEAGE_KEY]
        if not isinstance(provenance, Mapping):
            raise ValueError("inventory provenance must be a JSON object")
        if "source" in provenance:
            _inventory_ref(provenance["source"], field="inventory_source")
        if "digest" in provenance:
            _inventory_ref(provenance["digest"], field="inventory_digest")

    raw_models = inventory.get("models", ())
    if isinstance(raw_models, (list, tuple)):
        for entry in raw_models:
            if isinstance(entry, str):
                _model_ref(entry)
                continue
            if not isinstance(entry, Mapping):
                raise ValueError("inventory models entries must be model ids or JSON objects")
            model_id = entry.get("model_id", entry.get("model", entry.get("id", "")))
            _inventory_ref(model_id, field="models.model_id")
            _validate_optional_inventory_refs(
                entry,
                fields=("provider", "source", "status"),
                context="models",
            )

    available = inventory.get("available_models", ())
    if isinstance(available, (list, tuple)):
        for entry in available:
            if not isinstance(entry, Mapping):
                raise ValueError("inventory available_models entries must be JSON objects")
            model_id = entry.get("model_id", entry.get("model", entry.get("id", "")))
            _inventory_ref(model_id, field="available_models.model_id")
            _validate_optional_inventory_refs(
                entry,
                fields=("provider",),
                context="available_models",
            )

    discovery = inventory.get("model_discovery")
    if "model_discovery" in inventory:
        if not isinstance(discovery, Mapping):
            raise ValueError("inventory model_discovery must be a JSON object")
        observations = discovery.get("observations")
        if not isinstance(observations, (list, tuple)):
            raise ValueError("inventory model_discovery.observations must be a JSON array")
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise ValueError(
                    "inventory model_discovery.observations entries must be JSON objects"
                )
            model_id = observation.get(
                "model_id", observation.get("model", observation.get("id", ""))
            )
            _inventory_ref(model_id, field="model_discovery.observations.model_id")
            _validate_optional_inventory_refs(
                observation,
                fields=("provider", "source", "status"),
                context="model_discovery.observations",
            )


def _inventory_model_refs(
    inventory: Mapping[str, object],
) -> tuple[tuple[str, ...], dict[str, dict[str, object]]]:
    evidence: dict[str, set[tuple[str, str]]] = {}
    identities: dict[str, set[str]] = {}

    def add(value: object, *, source: str, status: str) -> None:
        ref = _model_ref(value)
        key = ref.casefold()
        clean_source = require_opaque_metadata_ref(source or "supplied_models", field="inventory_source")
        clean_status = require_opaque_metadata_ref(status or "supplied", field="inventory_status")
        identities.setdefault(key, set()).add(ref)
        evidence.setdefault(key, set()).add((clean_source, clean_status))

    raw_models = inventory.get("models", ())
    if isinstance(raw_models, (list, tuple)):
        for entry in raw_models:
            if isinstance(entry, str):
                add(entry, source="supplied_models", status="supplied")
            elif isinstance(entry, Mapping):
                model_id = entry.get("model_id", entry.get("model", entry.get("id", "")))
                provider = str(entry.get("provider", "")).strip()
                if model_id:
                    ref = _model_ref(model_id)
                    add(
                        ref if "/" in ref or not provider else f"{provider}/{ref}",
                        source=str(entry.get("source", "supplied_models")),
                        status=str(entry.get("status", "supplied")),
                    )

    available = inventory.get("available_models", ())
    if isinstance(available, (list, tuple)):
        for entry in available:
            if not isinstance(entry, Mapping):
                continue
            model_id = entry.get("model_id", entry.get("model", entry.get("id", "")))
            provider = str(entry.get("provider", "")).strip()
            if not model_id:
                continue
            ref = _model_ref(model_id)
            add(
                ref if "/" in ref or not provider else f"{provider}/{ref}",
                source="available_models",
                status="configured",
            )

    discovery = inventory.get("model_discovery")
    observations = discovery.get("observations", ()) if isinstance(discovery, Mapping) else ()
    if isinstance(observations, (list, tuple)):
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            model_id = observation.get(
                "model_id", observation.get("model", observation.get("id", ""))
            )
            if model_id:
                ref = _model_ref(model_id)
                provider = str(observation.get("provider", "")).strip()
                add(
                    ref if "/" in ref or not provider else f"{provider}/{ref}",
                    source=str(observation.get("source", "model_discovery")),
                    status=str(observation.get("status", "observed")),
                )
    refs = tuple(
        min(identities[key], key=lambda value: (value.casefold(), value))
        for key in sorted(identities)
    )
    records = {
        key: {
            "identities": sorted(identities[key], key=lambda value: (value.casefold(), value)),
            "records": [
                {"source": source, "status": status}
                for source, status in sorted(evidence[key])
            ],
        }
        for key in sorted(identities)
    }
    return refs, records


def _normalized_refs(values: Iterable[str]) -> tuple[str, ...]:
    by_key: dict[str, str] = {}
    for value in values:
        ref = _model_ref(value)
        key = ref.casefold()
        current = by_key.get(key)
        if current is None or (ref.casefold(), ref) < (current.casefold(), current):
            by_key[key] = ref
    return tuple(by_key[key] for key in sorted(by_key))


def _inventory_record(
    inventory: Mapping[str, object],
    model_refs: tuple[str, ...],
    model_evidence: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    status = str(inventory.get("inventory_status", inventory.get("status", "observed"))).strip().casefold()
    if status not in _INVENTORY_STATUSES:
        raise ValueError(f"inventory status must be one of {sorted(_INVENTORY_STATUSES)}")
    provenance = inventory.get(_SOURCE_LINEAGE_KEY)
    provenance_map = provenance if isinstance(provenance, Mapping) else {}
    source = str(
        provenance_map.get(
            "source",
            inventory.get("source", inventory.get("schema_version", "supplied_json")),
        )
    ).strip() or "supplied_json"
    source = require_opaque_metadata_ref(source, field="inventory_source")
    supplied_digest = str(provenance_map.get("digest", inventory.get("digest", ""))).strip()
    if supplied_digest:
        supplied_digest = require_opaque_metadata_ref(
            supplied_digest,
            field="inventory_digest",
        )
    comparison_seed = {
        "models": [
            {
                "identities": _list_value(
                    model_evidence.get(model_id.casefold(), {}), "identities"
                ),
                "model_id": model_id,
                "records": _list_value(
                    model_evidence.get(model_id.casefold(), {}), "records"
                ),
            }
            for model_id in model_refs
        ],
        "source": source,
        "status": status,
    }
    return {
        "digest": _digest(comparison_seed),
        "model_count": len(model_refs),
        "source": source,
        "status": status,
        "supplied_digest": supplied_digest,
    }


def _recommendation_metadata(contract_model_id: str) -> tuple[list[str], list[str]]:
    categories: list[str] = []
    providers: list[str] = []
    catalog = SHIPPED_MODEL_RECOMMENDATIONS
    raw_categories = catalog.get("categories", {})
    if isinstance(raw_categories, Mapping):
        for category, chain in raw_categories.items():
            if not isinstance(chain, (list, tuple)):
                continue
            for candidate in chain:
                if not isinstance(candidate, Mapping):
                    continue
                if str(candidate.get("model_alias", "")).casefold() != contract_model_id.casefold():
                    continue
                categories.append(str(category))
                if not providers:
                    raw_providers = candidate.get("preferred_provider_families", ())
                    if isinstance(raw_providers, (list, tuple)):
                        providers = [str(value) for value in raw_providers]
                break
    if not providers:
        for section_name in ("role_suggestions", "domain_affinities", "last_resort"):
            section = catalog.get(section_name, {})
            if not isinstance(section, Mapping):
                continue
            for chain in section.values():
                if not isinstance(chain, (list, tuple)):
                    continue
                for candidate in chain:
                    if not isinstance(candidate, Mapping):
                        continue
                    if str(candidate.get("model_alias", "")).casefold() == contract_model_id.casefold():
                        raw_providers = candidate.get("preferred_provider_families", ())
                        if isinstance(raw_providers, (list, tuple)):
                            providers = [str(value) for value in raw_providers]
                        break
                if providers:
                    break
            if providers:
                break
    return sorted(set(categories)), list(dict.fromkeys(providers))


def _price_dimension(contract: Mapping[str, object] | None, projection: Mapping[str, str] | None) -> dict[str, object]:
    if contract is None or projection is None:
        return {"status": "absent"}
    raw_price = contract.get("pricing_usd_per_mtok")
    if not isinstance(raw_price, Mapping):
        return {"status": "absent"}
    tier = str(projection.get("service_tier", "standard"))
    multiplier = _SERVICE_TIER_MULTIPLIERS.get(tier, 1.0)
    prices: dict[str, object] = {}
    for key, value in raw_price.items():
        if isinstance(value, bool):
            prices[str(key)] = value
        elif isinstance(value, (int, float)):
            prices[str(key)] = float(value) * multiplier
        else:
            prices[str(key)] = value
    return {
        "prices_usd_per_mtok": prices,
        "provenance": (
            "exact_contract"
            if projection.get(_SOURCE_LINEAGE_KEY) == "exact"
            else "inherited_contract"
        ),
        "service_tier": tier,
        "service_tier_multiplier": multiplier,
        "status": "documented_list",
    }


def _covered_dimensions(
    requested_model: str,
    contract: Mapping[str, object],
    projection: Mapping[str, str],
) -> dict[str, object]:
    contract_id = str(projection["contract_model_id"])
    family = str(contract.get("family", "")) or model_family(requested_model)
    categories, providers = _recommendation_metadata(contract_id)
    docs = list(_MODEL_DOCS.get(contract_id, ()))
    raw_sources = contract.get("sources", ())
    sources = (
        sorted(str(value) for value in raw_sources if value)
        if isinstance(raw_sources, (list, tuple))
        else []
    )
    raw_efforts = contract.get("reasoning_efforts", ())
    efforts = [str(value) for value in raw_efforts] if isinstance(raw_efforts, (list, tuple)) else []
    raw_unsupported = contract.get("unsupported_efforts", {})
    unsupported = dict(raw_unsupported) if isinstance(raw_unsupported, Mapping) else {}
    return {
        "calibration": {
            "composition": "model_specific" if contract_id in MODEL_COMPOSITION_CALIBRATIONS else "family_or_generic",
            "high_effort": "model_specific" if contract_id in MODEL_HIGH_EFFORT_CALIBRATIONS else "family_or_generic",
            "status": "covered",
        },
        "category_projection": {
            "categories": categories,
            "provenance": "shipped_recommendation",
            "status": "covered" if categories else "missing",
        },
        "contract": {
            "provenance": str(projection.get(_SOURCE_LINEAGE_KEY, "")),
            "schema_version": str(contract.get("schema_version", "")),
            "status": "covered",
        },
        "docs": {
            "paths": docs,
            "sources": sources,
            "status": "covered" if docs and sources else "missing",
        },
        "effort": {
            "floor": str(contract.get("effort_floor", "")),
            "reasoning_efforts": efforts,
            "status": "covered" if efforts else "missing",
            "unsupported_efforts": unsupported,
        },
        "family_recognition": {"family": family, "status": "recognized" if family else "missing"},
        "price": _price_dimension(contract, projection),
        "provider_eligibility": {
            "families": providers,
            "provenance": "shipped_recommendation",
            "status": "covered" if providers else "missing",
        },
    }


def _missing_dimensions(requested_model: str, *, excluded: bool) -> dict[str, object]:
    family = model_family(requested_model)
    status = "excluded" if excluded else "missing"
    return {
        "calibration": {"composition": "generic", "high_effort": "generic", "status": status},
        "category_projection": {"categories": [], "status": status},
        "contract": {"status": status},
        "docs": {"paths": [], "sources": [], "status": status},
        "effort": {"status": status},
        "family_recognition": {"family": family, "status": "recognized" if family else status},
        "price": {"status": "absent" if not excluded else status},
        "provider_eligibility": {"families": [], "status": status},
    }


def _coverage_row(
    requested_model: str,
    *,
    present: bool,
    inventory_record: Mapping[str, object],
    inventory_evidence: Mapping[str, object],
    required: frozenset[str],
    recommended: frozenset[str],
    exclusions: frozenset[str],
) -> dict[str, object]:
    key = requested_model.casefold()
    excluded = key in exclusions
    projection = None if excluded else model_contract_projection(requested_model)
    contract = model_contract(requested_model) if projection is not None else None
    if excluded:
        status = "intentional_exclusion"
    elif projection is not None:
        status = str(projection.get(_SOURCE_LINEAGE_KEY, ""))
    else:
        status = "missing"
    if status == "missing" and key in required:
        actionability = "required_missing"
    elif status == "missing" and key in recommended:
        actionability = "recommended_missing"
    elif status == "missing":
        actionability = "optional_discovery"
    elif status == "intentional_exclusion":
        actionability = "intentional_exclusion"
    else:
        actionability = "covered"
    return {
        "actionability": actionability,
        "canonical_model_id": (
            str(projection["canonical_model_id"])
            if projection is not None
            else requested_model.rsplit("/", 1)[-1].casefold()
        ),
        "contract_model_id": str(projection["contract_model_id"]) if projection is not None else None,
        "dimensions": (
            _covered_dimensions(requested_model, contract, projection)
            if contract is not None and projection is not None
            else _missing_dimensions(requested_model, excluded=excluded)
        ),
        "inventory_evidence": {
            "digest": str(inventory_record["digest"]),
            "identities": _list_value(inventory_evidence, "identities"),
            "present": present,
            "records": _list_value(inventory_evidence, "records"),
            "source": str(inventory_record["source"]),
            "status": str(inventory_record["status"]),
        },
        "reasoning_mode": str(projection["reasoning_mode"]) if projection is not None else None,
        "requested_model": requested_model,
        "service_tier": str(projection["service_tier"]) if projection is not None else None,
        "status": status,
    }


def build_model_contract_coverage(
    inventory: Mapping[str, object],
    *,
    required_models: Iterable[str] = (),
    recommended_models: Iterable[str] = (),
    intentional_exclusions: Iterable[str] = (),
) -> dict[str, object]:
    """Build a stable network-free coverage report for one supplied inventory."""
    if not isinstance(inventory, Mapping):
        raise ValueError("model contract inventory must be a JSON object")
    _validate_inventory_shape(inventory)
    inventory_models, inventory_evidence = _inventory_model_refs(inventory)
    required_refs = _normalized_refs(required_models)
    recommended_refs = _normalized_refs(recommended_models)
    exclusion_refs = _normalized_refs(intentional_exclusions)
    model_by_key: dict[str, str] = {}
    # Requirement identities deliberately win the display slot while all
    # supplied spellings remain in inventory_evidence.identities.
    for refs in (inventory_models, recommended_refs, exclusion_refs, required_refs):
        for model_id in refs:
            model_by_key[model_id.casefold()] = model_id
    all_models = tuple(model_by_key[key] for key in sorted(model_by_key))
    inventory_record = _inventory_record(inventory, inventory_models, inventory_evidence)
    present = frozenset(value.casefold() for value in inventory_models)
    required = frozenset(value.casefold() for value in required_refs)
    recommended = frozenset(value.casefold() for value in recommended_refs)
    exclusions = frozenset(value.casefold() for value in exclusion_refs)
    rows = [
        _coverage_row(
            model_id,
            present=model_id.casefold() in present,
            inventory_record=inventory_record,
            inventory_evidence=inventory_evidence.get(model_id.casefold(), {}),
            required=required,
            recommended=recommended,
            exclusions=exclusions,
        )
        for model_id in all_models
    ]
    status_counts = {status: 0 for status in MODEL_CONTRACT_COVERAGE_STATUSES}
    action_counts = {name: 0 for name in ("required_missing", "recommended_missing", "optional_discovery")}
    for row in rows:
        status_counts[str(row["status"])] += 1
        actionability = str(row["actionability"])
        if actionability in action_counts:
            action_counts[actionability] += 1
    inventory_status = str(inventory_record["status"])
    if inventory_status == "cold":
        outcome = "cold_inventory"
    elif inventory_status == "unavailable":
        outcome = "unavailable_inventory"
    elif action_counts["required_missing"]:
        outcome = "required_gaps"
    elif action_counts["recommended_missing"]:
        outcome = "recommended_gaps"
    elif action_counts["optional_discovery"]:
        outcome = "optional_gaps"
    else:
        outcome = "covered"
    comparison = {
        "inventory": inventory_record,
        "models": rows,
        "requirements": {
            "intentional_exclusions": list(exclusion_refs),
            "recommended_models": list(recommended_refs),
            "required_models": list(required_refs),
        },
        "summary": {
            **action_counts,
            "outcome": outcome,
            "status_counts": status_counts,
            "total_models": len(rows),
        },
    }
    report = {
        "blocking": bool(action_counts["required_missing"]),
        "claim_boundary": MODEL_CONTRACT_COVERAGE_CLAIM_BOUNDARY,
        "comparison": comparison,
        "comparison_digest": _digest(comparison),
        "schema_version": MODEL_CONTRACT_COVERAGE_SCHEMA_VERSION,
    }
    return report


def coverage_exit_code(report: Mapping[str, object]) -> int:
    """Return a deterministic CLI status: required gaps block, other gaps advise."""
    return 1 if report.get("blocking") is True else 0


__all__ = [
    "MODEL_CONTRACT_COVERAGE_CLAIM_BOUNDARY",
    "MODEL_CONTRACT_COVERAGE_SCHEMA_VERSION",
    "MODEL_CONTRACT_COVERAGE_STATUSES",
    "build_model_contract_coverage",
    "coverage_exit_code",
]
