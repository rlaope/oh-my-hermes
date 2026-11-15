"""Metadata-only routing observation bridge and deterministic surface projections.

The bridge joins three records without reading process output or starting work:
a prepared model route, a Hermes ``delegate_task`` child manifest, and an
executor/runtime session observation. Input records may contain prompts, goals,
logs, or summaries; only the explicit scalar allowlist below can reach output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
import re
from typing import Final, Mapping, Sequence, TypeAlias, TypeGuard, TypeVar

from ..system.metadata_safety import require_opaque_metadata_ref
from .hermes_child_arm_setup import arm_setup_errors
from .hermes_child_evaluation import evaluation_binding_errors
from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
_BindingCandidate = TypeVar("_BindingCandidate")

ROUTING_OBSERVATION_SCHEMA_VERSION: Final[str] = "routing_observation/v1"
ROUTING_OBSERVATION_CLAIMS: Final[tuple[str, ...]] = ("prepared", "observed")
ROUTING_OBSERVATION_STATUSES: Final[tuple[str, ...]] = (
    "prepared",
    "dispatched",
    "running",
    "completed",
    "failed",
    "timed_out",
    "blocked",
    "cancelled",
)

_STATUS_ALIASES: Final[dict[str, str]] = {
    "prepared": "prepared",
    "prepared_not_observed": "prepared",
    "pending": "dispatched",
    "queued": "dispatched",
    "dispatching": "dispatched",
    "dispatched": "dispatched",
    "active": "running",
    "in_progress": "running",
    "running": "running",
    "passed": "running",
    "tests_passed": "running",
    "completed": "completed",
    "complete": "completed",
    "succeeded": "completed",
    "success": "completed",
    "executor_completed": "completed",
    "failed": "failed",
    "timed_out": "timed_out",
    "timeout": "timed_out",
    "error": "failed",
    "executor_failed": "failed",
    "worktree_failed": "failed",
    "blocked": "blocked",
    "executor_blocked": "blocked",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

_ID_FIELDS: Final[tuple[str, ...]] = (
    "parent_session_id",
    "child_session_id",
    "run_id",
    "dispatch_id",
)
_INTEGER_METRIC_FIELDS: Final[tuple[str, ...]] = ("turn", "tools", "tokens")
_NUMERIC_METRIC_FIELDS: Final[tuple[str, ...]] = (
    "elapsed_seconds",
    "cost_usd",
    "rate_tokens_per_second",
)
_METRIC_FIELDS: Final[tuple[str, ...]] = (*_INTEGER_METRIC_FIELDS, *_NUMERIC_METRIC_FIELDS)
_OBSERVATION_AUTHORITY: Final[object] = object()
_OBSERVATION_SOURCES: Final[tuple[str, ...]] = ("hermes_child", "executor")
_UTC_Z: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


@dataclass(frozen=True, slots=True)
class AuthenticatedRoutingObservation:
    """A sealed record emitted by an OMH-owned observation adapter.

    The seal is process-local and identity-checked. Consequently a JSON object
    or arbitrary mapping cannot promote itself by copying a marker field.
    """

    record: Mapping[str, object]
    source: str
    _authority: object


def authenticate_child_observation(record: Mapping[str, object]) -> AuthenticatedRoutingObservation:
    """Mark metadata read from the OMH Hermes child observer as authenticated."""
    return AuthenticatedRoutingObservation(dict(record), "hermes_child", _OBSERVATION_AUTHORITY)


def authenticate_executor_observation(record: Mapping[str, object]) -> AuthenticatedRoutingObservation:
    """Mark metadata read from an OMH executor/runtime observer as authenticated."""
    return AuthenticatedRoutingObservation(dict(record), "executor", _OBSERVATION_AUTHORITY)


_PAYLOAD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "claim",
        "status",
        *_ID_FIELDS,
        "category",
        "lane",
        "role",
        "selected_owner",
        "selected_provider",
        "selected_model",
        "selected_reasoning",
        "fallback_chain",
        "fallback_index",
        "reason",
        "provenance",
        "routing_provenance",
        *_METRIC_FIELDS,
        # The provenance that says which of the three zeros a `cost_usd` of
        # 0.0 is: billed nothing, not reported, or unpriceable.
        "cost_status",
        "cost_source",
        "current_action",
        "observed_at",
        "evaluation_binding",
        # Paired-run evaluation only: whether the arm home held the enabled
        # OMH plugin and the digest of the OMH skills it held, read from disk
        # by the dispatcher and signed with the rest of the receipt.
        "arm_setup",
    }
)


def build_routing_observation(
    *,
    route: Mapping[str, object] | None = None,
    child_dispatch: Mapping[str, object] | AuthenticatedRoutingObservation | None = None,
    session_observation: Mapping[str, object] | AuthenticatedRoutingObservation | None = None,
    parent_session_id: str = "",
    child_session_id: str = "",
    run_id: str = "",
    task_index: int = 0,
) -> dict[str, JsonValue]:
    """Join prepared and observed routing metadata into one canonical payload.

    Unknown metrics are always ``None``. A genuine observed zero is retained.
    Hermes manifests are consumed by selecting one task row; their ``goal`` and
    ``log`` fields are intentionally unreachable from the output builder.
    """
    route = route if isinstance(route, Mapping) else {}
    child_dispatch, child_authenticated = _observation_record(child_dispatch, source="hermes_child")
    session_observation, session_authenticated = _observation_record(
        session_observation,
        source="executor",
    )
    child = _hermes_child(child_dispatch, task_index)
    dispatch_status = _normalized_status(child.get("status"))
    child_observed = child_authenticated and dispatch_status not in {None, "prepared"}
    runtime_status = _session_status(session_observation)
    runtime_observed = (
        session_authenticated
        and runtime_status != "prepared"
        and _has_runtime_observation(session_observation)
    )
    observed_child = child if child_observed else {}
    observed_session = session_observation if runtime_observed else {}

    route_provider, route_model = _provider_model(route.get("selected_model"))
    fallback_chain = _fallback_chain(route.get("chain"))
    selected_provider = route_provider
    selected_model = route_model
    selected_reasoning = _safe_ref(route.get("selected_reasoning_effort"), field="selected_reasoning")

    raw_child_usage = observed_child.get("usage")
    child_usage: Mapping[str, object] = (
        raw_child_usage
        if isinstance(raw_child_usage, Mapping)
        and all(isinstance(key, str) for key in raw_child_usage)
        else {}
    )
    observed_provider, observed_model = _observed_provider_model(observed_session)
    child_provider, child_model = _observed_provider_model({**observed_child, **child_usage})
    observed_provider = observed_provider or child_provider
    observed_model = observed_model or child_model
    if observed_provider:
        selected_provider = observed_provider
    if observed_model:
        selected_model = observed_model
    observed_reasoning = _first_safe(
        observed_session,
        ("reasoning", "reasoning_effort", "routed_reasoning_effort"),
        field="selected_reasoning",
    )
    if observed_reasoning:
        selected_reasoning = observed_reasoning

    status = (runtime_status if runtime_observed else None) or (
        dispatch_status if child_observed else None
    ) or ("running" if runtime_observed else "prepared")
    observed = child_observed or runtime_observed
    provenance = "runtime_observation" if runtime_observed else (
        "hermes_child_dispatch" if child_observed else "route_metadata"
    )
    reason_source = "dispatch" if child_observed else ("runtime" if runtime_observed else "route")

    ids = {
        "parent_session_id": _safe_ref(parent_session_id, field="parent_session_id")
        or _first_safe(child_dispatch, ("parent_session_id", "parent_id", "parent_run_id"), field="parent_session_id")
        or _first_safe(observed_session, ("parent_session_id", "parent_id"), field="parent_session_id"),
        "child_session_id": _safe_ref(child_session_id, field="child_session_id")
        or _first_safe(child, ("child_session_id", "session_id", "child_id"), field="child_session_id")
        or _first_safe(observed_session, ("child_session_id", "session_id"), field="child_session_id"),
        "run_id": _safe_ref(run_id, field="run_id")
        or _first_safe(observed_session, ("run_id", "target_id"), field="run_id")
        or _first_safe(child, ("run_id",), field="run_id"),
        "dispatch_id": _first_safe(
            child_dispatch,
            ("delegation_id", "dispatch_id"),
            field="dispatch_id",
        ),
    }

    runtime_metrics = _observed_metrics(observed_session)
    child_metrics = _observed_metrics(child_usage)
    metrics = {
        field: runtime_metrics[field] if runtime_metrics[field] is not None else child_metrics[field]
        for field in _METRIC_FIELDS
    }
    # A cost of exactly zero means three different things -- billed nothing,
    # not reported by the provider, or a model nothing can price -- and the
    # figure alone cannot say which. Hermes' own usage record carries the
    # answer in `cost_status`/`cost_source`; both travel with the number so a
    # renderer can decline to state a zero it cannot vouch for.
    cost_status = _first_safe(observed_session, ("cost_status",), field="cost_status") \
        or _first_safe(child_usage, ("cost_status",), field="cost_status")
    cost_source = _first_safe(observed_session, ("cost_source",), field="cost_source") \
        or _first_safe(child_usage, ("cost_source",), field="cost_source")
    current_action = _first_safe(
        observed_session,
        ("current_action", "next_action"),
        field="current_action",
    )
    fallback_index = _fallback_index(fallback_chain, selected_provider, selected_model)
    fallback_payload: list[JsonValue] = []
    for item in fallback_chain:
        normalized_item: dict[str, JsonValue] = {}
        for key, value in item.items():
            normalized_item[key] = value
        fallback_payload.append(normalized_item)

    from .model_routing import canonical_model_category

    raw_category = route.get("category") or route.get("requested_category")
    category = canonical_model_category(raw_category) if isinstance(raw_category, str) else ""
    payload: dict[str, JsonValue] = {
        "schema_version": ROUTING_OBSERVATION_SCHEMA_VERSION,
        "claim": "observed" if observed else "prepared",
        "status": status,
        **ids,
        "category": category or None,
        "lane": _first_safe(route, ("lane", "domain", "requested_domain"), field="lane"),
        "role": _first_safe(route, ("role",), field="role"),
        "selected_owner": _first_safe(
            observed_session,
            ("owner", "executor_profile", "executor"),
            field="selected_owner",
        )
        or _first_safe(route, ("executor_profile", "owner"), field="selected_owner"),
        "cost_status": cost_status,
        "cost_source": cost_source,
        "selected_provider": selected_provider,
        "selected_model": selected_model,
        "selected_reasoning": selected_reasoning,
        "fallback_chain": fallback_payload,
        "fallback_index": fallback_index,
        "reason": f"{reason_source}_{status}",
        "provenance": provenance,
        "routing_provenance": _routing_provenance(route),
        **metrics,
        "current_action": current_action,
    }
    errors = validate_routing_observation(payload)
    if errors:
        raise ValueError("invalid routing observation: " + "; ".join(errors))
    return payload


def validate_routing_observation(payload: Mapping[str, object] | object) -> list[str]:
    """Validate the canonical schema without accepting body-shaped metadata."""
    if not isinstance(payload, Mapping):
        return ["payload must be an object"]
    errors: list[str] = []
    extra_fields = sorted(set(payload) - _PAYLOAD_FIELDS)
    if extra_fields:
        errors.append(f"unsupported fields: {extra_fields}")
    if payload.get("schema_version") != ROUTING_OBSERVATION_SCHEMA_VERSION:
        errors.append("schema_version is invalid")
    if payload.get("claim") not in ROUTING_OBSERVATION_CLAIMS:
        errors.append("claim is invalid")
    if payload.get("status") not in ROUTING_OBSERVATION_STATUSES:
        errors.append("status is invalid")
    if payload.get("claim") == "prepared" and payload.get("status") != "prepared":
        errors.append("prepared claim requires prepared status")
    if payload.get("claim") == "observed" and payload.get("status") == "prepared":
        errors.append("observed claim must not use prepared status")

    for field in (*_ID_FIELDS, "category", "lane", "role", "selected_owner", "selected_provider", "selected_model", "selected_reasoning", "reason", "provenance", "routing_provenance", "current_action"):
        value = payload.get(field)
        if value is None:
            continue
        try:
            require_opaque_metadata_ref(value, field=field)
        except ValueError:
            errors.append(f"{field} must be metadata-only")

    chain = payload.get("fallback_chain")
    if not isinstance(chain, list):
        errors.append("fallback_chain must be a list")
    else:
        for index, item in enumerate(chain):
            if not isinstance(item, Mapping) or set(item) != {"provider", "model", "reasoning"}:
                errors.append(f"fallback_chain[{index}] is invalid")
                continue
            for field in ("provider", "model", "reasoning"):
                value = item.get(field)
                if value is None:
                    continue
                try:
                    require_opaque_metadata_ref(value, field=f"fallback_chain[{index}].{field}")
                except ValueError:
                    errors.append(f"fallback_chain[{index}].{field} must be metadata-only")
    fallback_index = payload.get("fallback_index")
    if fallback_index is not None and (
        not isinstance(fallback_index, int)
        or isinstance(fallback_index, bool)
        or fallback_index < 0
        or not isinstance(chain, list)
        or fallback_index >= len(chain)
    ):
        errors.append("fallback_index is invalid")
    evaluation_binding = payload.get("evaluation_binding")
    if evaluation_binding is not None:
        if _is_evaluation_binding_value(evaluation_binding):
            errors.extend(evaluation_binding_errors(evaluation_binding))
        else:
            errors.append("evaluation_binding must be a scalar object")
    arm_setup = payload.get("arm_setup")
    if arm_setup is not None:
        errors.extend(arm_setup_errors(arm_setup))
    observed_at = payload.get("observed_at")
    if observed_at is not None:
        if isinstance(observed_at, str) and _UTC_Z.fullmatch(observed_at) is not None:
            try:
                strict_fromisoformat(observed_at.removesuffix("Z") + "+00:00")
            except ValueError:
                errors.append("observed_at must be an exact UTC-Z timestamp")
        else:
            errors.append("observed_at must be an exact UTC-Z timestamp")
    for field in _METRIC_FIELDS:
        value = payload.get(field)
        if payload.get("claim") == "prepared" and value is not None:
            errors.append(f"prepared claim requires {field} to be null")
        if field in _INTEGER_METRIC_FIELDS:
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                errors.append(f"{field} must be a non-negative observed integer or null")
        elif value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            errors.append(f"{field} must be a non-negative observed number or null")
    return errors


def _is_evaluation_binding_value(
    value: _BindingCandidate,
) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and (
            item is None
            or isinstance(item, (str, int, float, bool))
        )
        for key, item in value.items()
    )


def render_routing_status_rows(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return deterministic ASCII rows shared verbatim by every user surface.

    Optional runtime metrics are omitted when unobserved. In particular, a
    missing value never becomes a visible zero or an ``unknown`` metric claim.
    """
    chain = payload.get("fallback_chain")
    safe_chain = [item for item in chain if isinstance(item, Mapping)] if isinstance(chain, list) else []
    index = payload.get("fallback_index")
    fallback = f"{index + 1}/{len(safe_chain)}" if isinstance(index, int) and not isinstance(index, bool) else f"unselected/{len(safe_chain)}"
    route_parts = [
        _labeled("category", payload.get("category")),
        _labeled("lane", payload.get("lane")),
        _labeled("role", payload.get("role")),
        _labeled("owner", payload.get("selected_owner")),
        _labeled("selected", _provider_model_text(payload)),
        _labeled("reasoning", payload.get("selected_reasoning")),
        f"fallback {fallback}",
    ]
    rows = ["ROUTE " + "  ".join(part for part in route_parts if part)]
    if safe_chain:
        rows.append("CHAIN " + " > ".join(_chain_item_text(item) for item in safe_chain))
    rows.append(
        "STATE "
        + "  ".join(
            part
            for part in (
                _labeled("status", payload.get("status")),
                _labeled("claim", payload.get("claim")),
                _labeled("reason", payload.get("reason")),
            )
            if part
        )
    )
    action = _labeled("action", payload.get("current_action"))
    if action:
        rows.append("ACTION " + action)
    metrics = [
        _metric("turn", payload.get("turn")),
        _metric("tools", payload.get("tools")),
        _metric("elapsed", payload.get("elapsed_seconds"), suffix="s"),
        _metric("tokens", payload.get("tokens")),
        _cost_metric(payload),
        _metric("rate", payload.get("rate_tokens_per_second"), suffix=" tok/s"),
    ]
    observed_metrics = [item for item in metrics if item]
    if observed_metrics:
        rows.append("METRICS " + "  ".join(observed_metrics))
    rows.append(f"VIA {_text(_field(payload, 'provenance'))}")
    return tuple(rows)


def render_routing_code_block_text(payload: Mapping[str, object]) -> str:
    """Canonical unfenced code-block body for messaging and Desktop adapters."""
    return "\n".join(render_routing_status_rows(payload))


def routing_surface_projection(payload: dict[str, object]) -> dict[str, object]:
    """Project one valid payload to CLI and identical messaging/Desktop text."""
    errors = validate_routing_observation(payload)
    if errors:
        raise ValueError("invalid routing surface observation: " + "; ".join(errors))
    rows = render_routing_status_rows(payload)
    text = "\n".join(rows)
    return {
        "payload": payload,
        "cli_status_rows": list(rows),
        "messaging_code_block_text": text,
        "desktop_code_block_text": text,
    }


def _observation_record(
    value: Mapping[str, object] | AuthenticatedRoutingObservation | None,
    *,
    source: str,
) -> tuple[Mapping[str, object], bool]:
    if (
        isinstance(value, AuthenticatedRoutingObservation)
        and value._authority is _OBSERVATION_AUTHORITY
        and value.source == source
        and value.source in _OBSERVATION_SOURCES
    ):
        return value.record, True
    return (value, False) if isinstance(value, Mapping) else ({}, False)


def _hermes_child(record: Mapping[str, object], task_index: int) -> Mapping[str, object]:
    tasks = record.get("tasks")
    if isinstance(tasks, Sequence) and not isinstance(tasks, (str, bytes)):
        for task in tasks:
            if isinstance(task, Mapping) and task.get("index") == task_index:
                return {
                    key: value
                    for key, value in task.items()
                    if isinstance(key, str)
                }
        indexed_task = tasks[task_index] if 0 <= task_index < len(tasks) else None
        if isinstance(indexed_task, Mapping):
            return {
                key: value
                for key, value in indexed_task.items()
                if isinstance(key, str)
            }
        return {}
    return record


def _session_status(record: Mapping[str, object]) -> str | None:
    direct = _normalized_status(record.get("status"))
    if direct:
        return direct
    latest = record.get("latest_event")
    if isinstance(latest, Mapping):
        return _normalized_status(latest.get("event_type") or latest.get("status"))
    return _normalized_status(record.get("event_type"))


def _normalized_status(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _STATUS_ALIASES.get(value.strip().casefold().replace("-", "_"))


def _has_runtime_observation(record: Mapping[str, object]) -> bool:
    if _session_status(record) or _first_safe(record, ("provenance",), field="runtime_provenance"):
        return True
    if any(value is not None for value in _observed_metrics(record).values()):
        return True
    return bool(_first_safe(record, ("current_action", "next_action", "provider", "model", "routed_model"), field="runtime_observation"))


def _observed_metrics(record: Mapping[str, object]) -> dict[str, int | float | None]:
    return {
        "turn": _first_integer(record, ("turn", "turn_index")),
        "tools": _first_integer(record, ("tools", "tools_count", "tool_count")),
        "elapsed_seconds": _first_number(record, ("elapsed_seconds",)),
        "tokens": _first_integer(record, ("tokens", "tokens_total", "total_tokens", "tokens_billable")),
        "cost_usd": _first_number(record, ("cost_usd", "estimated_cost_usd")),
        "rate_tokens_per_second": _first_number(record, ("rate_tokens_per_second",)),
    }


def _first_integer(record: Mapping[str, object], keys: tuple[str, ...]) -> int | None:
    value = _first_metric(record, keys, integer=True)
    return value if isinstance(value, int) else None


def _first_number(record: Mapping[str, object], keys: tuple[str, ...]) -> int | float | None:
    return _first_metric(record, keys, integer=False)


def _first_metric(
    record: Mapping[str, object],
    keys: tuple[str, ...],
    *,
    integer: bool,
) -> int | float | None:
    validator = _observed_integer if integer else _observed_number
    for key in keys:
        value = validator(record.get(key))
        if value is not None:
            return value
    latest = record.get("latest_event")
    if isinstance(latest, Mapping):
        signal = latest.get("signal")
        if isinstance(signal, Mapping):
            for key in keys:
                value = validator(signal.get(key))
                if value is not None:
                    return value
    return None


def _observed_integer(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _observed_number(value: object) -> int | float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return value


def _routing_provenance(route: Mapping[str, object]) -> str | None:
    # Frozen v1 routes use ``source`` while v2 routes use ``provenance``.
    # Keep model_routing.route_provenance as the one compatibility accessor.
    from .model_routing import route_provenance

    value, vocabulary = route_provenance(route)
    return value if vocabulary != "unknown" else None


def _observed_provider_model(record: Mapping[str, object]) -> tuple[str | None, str | None]:
    provider = _first_safe(record, ("provider", "selected_provider"), field="selected_provider")
    binding = _first_safe(record, ("model", "routed_model", "selected_model"), field="selected_model")
    binding_provider, model = _provider_model(binding)
    return provider or binding_provider, model


def _fallback_chain(value: object) -> list[dict[str, str | None]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        provider = _safe_ref(item.get("provider"), field="fallback_provider")
        binding = _safe_ref(item.get("model_id") or item.get("model"), field="fallback_model")
        binding_provider, model = _provider_model(binding)
        if not model:
            continue
        result.append(
            {
                "provider": provider or binding_provider,
                "model": model,
                "reasoning": _safe_ref(
                    item.get("reasoning_effort") or item.get("reasoning"),
                    field="fallback_reasoning",
                ),
            }
        )
    return result


def _fallback_index(chain: list[dict[str, str | None]], provider: str | None, model: str | None) -> int | None:
    if not model:
        return None
    for index, item in enumerate(chain):
        if item["model"] == model and (not provider or not item["provider"] or item["provider"] == provider):
            return index
    return None


def _provider_model(value: object) -> tuple[str | None, str | None]:
    binding = _safe_ref(value, field="model_binding")
    if not binding:
        return None, None
    if "/" not in binding:
        return None, binding
    provider, model = binding.split("/", 1)
    return provider or None, model or None


def _first_safe(record: Mapping[str, object], keys: tuple[str, ...], *, field: str) -> str | None:
    for key in keys:
        value = _safe_ref(record.get(key), field=field)
        if value:
            return value
    latest = record.get("latest_event")
    if isinstance(latest, Mapping):
        signal = latest.get("signal")
        if isinstance(signal, Mapping):
            for key in keys:
                value = _safe_ref(signal.get(key), field=field)
                if value:
                    return value
    return None


def _safe_ref(value: object, *, field: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        return require_opaque_metadata_ref(value, field=field)
    except ValueError:
        return None


def _field(record: Mapping[str, object], field: str) -> object:
    """Dynamic lookup keeps model-route provenance reads at their sole accessor."""
    return record.get(field)


def _text(value: object) -> str:
    return str(value) if value is not None and value != "" else "unknown"


def _provider_model_text(payload: Mapping[str, object]) -> str | None:
    provider = payload.get("selected_provider")
    model = payload.get("selected_model")
    if provider and model:
        return f"{provider}/{model}"
    return str(model or provider) if model or provider else None


def _chain_item_text(item: Mapping[str, object]) -> str:
    provider = item.get("provider")
    model = item.get("model")
    binding = f"{provider}/{model}" if provider and model else str(model or provider or "unknown")
    reasoning = item.get("reasoning")
    return f"{binding}[{reasoning}]" if reasoning else binding


def _labeled(label: str, value: object) -> str:
    return f"{label} {value}" if value is not None and value != "" else ""


def _metric(label: str, value: object, *, prefix: str = "", suffix: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return f"{label} {prefix}{value}{suffix}"


def _cost_metric(payload: Mapping[str, object]) -> str:
    """Render a cost only when the figure is one the record can vouch for.

    A positive number speaks for itself. A zero does not: the provider may
    have billed nothing, may not have reported at all, or may serve a model
    nothing can price, and all three arrive here as ``0.0``. Rendering the
    bare ``cost $0.0`` for the last two states a billing fact the record does
    not hold -- the failure an operator hit when a gateway route reported
    nothing and the surface printed a confident zero. A zero renders only
    alongside the provenance that earns it.
    """
    value = payload.get("cost_usd")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if value > 0:
        return _metric("cost", value, prefix="$")
    provenance = payload.get("cost_status") or payload.get("cost_source")
    if not isinstance(provenance, str) or not provenance.strip():
        return ""
    return f"cost ${value} ({provenance.strip()})"
