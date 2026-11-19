"""Allowlisted field adapters for coding-agent model records."""

from __future__ import annotations

from collections.abc import Mapping

from .pi_family_interop import PI_DISTRIBUTION_HOST, PI_FORK_HOST
from ..system.metadata_safety import require_opaque_metadata_ref

# The pi-family runtime's own config: the one source whose models are
# confirmed active rather than merely observed in a past session.
RUNTIME_CONFIG_SOURCE = "pi-family-config"


def model_candidates(source: str, parsed: object) -> list[Mapping[str, object]]:
    if not isinstance(parsed, Mapping):
        return []
    if source == RUNTIME_CONFIG_SOURCE:
        return _runtime_config_candidates(parsed)
    if source == "codex":
        payload = parsed.get("payload")
        table = payload if isinstance(payload, Mapping) else parsed
        return [_candidate(table.get("model_provider"), table.get("model"), "", parsed.get("timestamp"))]
    if source == "claude-code":
        message = parsed.get("message")
        table = message if isinstance(message, Mapping) else parsed
        return [_candidate("anthropic", table.get("model"), "", parsed.get("timestamp"))]
    if source == PI_FORK_HOST:
        return _fork_session_candidates(parsed)
    if source in {PI_DISTRIBUTION_HOST, "pi", "hermes"}:
        return [
            _candidate(
                parsed.get("provider"),
                parsed.get("modelId", parsed.get("model")),
                parsed.get("variant", parsed.get("thinkingLevel", "")),
                parsed.get("timestamp"),
            )
        ]
    model = parsed.get("model")
    if isinstance(model, Mapping):
        return [
            _candidate(
                model.get("providerID"),
                model.get("modelID"),
                model.get("variant", ""),
                _nested_timestamp(parsed.get("time")),
            )
        ]
    return []


def accepted_observation(
    source: str,
    candidate: Mapping[str, object],
) -> dict[str, str] | None:
    try:
        safe_source = require_opaque_metadata_ref(source, field="source")
        provider = require_opaque_metadata_ref(candidate.get("provider"), field="provider")
        model_id = require_opaque_metadata_ref(candidate.get("model_id"), field="model_id")
        raw_variant = candidate.get("variant")
        raw_timestamp = candidate.get("timestamp")
        variant = require_opaque_metadata_ref(raw_variant, field="variant") if raw_variant else ""
        timestamp = (
            require_opaque_metadata_ref(raw_timestamp, field="timestamp") if raw_timestamp else ""
        )
    except ValueError:
        return None
    return {
        "source": safe_source,
        "provider": provider,
        "model_id": model_id,
        "variant": variant,
        "timestamp": timestamp,
        "status": "confirmed_active" if source == RUNTIME_CONFIG_SOURCE else "observed_before",
    }


def _runtime_config_candidates(parsed: Mapping[str, object]) -> list[Mapping[str, object]]:
    candidates: list[Mapping[str, object]] = []
    for section in ("agents", "categories"):
        table = parsed.get(section)
        if not isinstance(table, Mapping):
            continue
        for spec in table.values():
            if not isinstance(spec, Mapping):
                continue
            candidates.append(_model_reference_candidate(spec))
            fallbacks = spec.get("fallback_models")
            if isinstance(fallbacks, list):
                candidates.extend(
                    _model_reference_candidate(item)
                    for item in fallbacks
                    if isinstance(item, Mapping)
                )
    models = parsed.get("models")
    if isinstance(models, list):
        candidates.extend(
            _candidate(
                item.get("provider"),
                item.get("model", item.get("model_id")),
                item.get("variant", ""),
                item.get("timestamp"),
            )
            for item in models
            if isinstance(item, Mapping)
        )
    return candidates


def _model_reference_candidate(spec: Mapping[str, object]) -> Mapping[str, object]:
    reference = spec.get("model")
    if not isinstance(reference, str):
        return _candidate("", reference, spec.get("variant", ""), spec.get("timestamp"))
    provider, separator, model_id = reference.partition("/")
    if not separator:
        return _candidate("", reference, spec.get("variant", ""), spec.get("timestamp"))
    return _candidate(provider, model_id, spec.get("variant", ""), spec.get("timestamp"))


def _candidate(
    provider: object,
    model: object,
    variant: object,
    timestamp: object,
) -> Mapping[str, object]:
    return {
        "provider": provider,
        "model_id": model,
        "variant": variant,
        "timestamp": timestamp,
    }


def _fork_session_candidates(parsed: Mapping[str, object]) -> list[Mapping[str, object]]:
    # A fork-host session names its model in two entry types: `model_change`
    # carries one `provider/id` string, and an assistant `message` carries
    # `provider` and `model` apart. Every other entry is skipped unread.
    entry_type = parsed.get("type")
    if entry_type == "model_change":
        reference = parsed.get("model")
        provider, _, model_id = reference.partition("/") if isinstance(reference, str) else ("", "", "")
        return [_candidate(provider, model_id, "", parsed.get("timestamp"))]
    message = parsed.get("message")
    if entry_type == "message" and isinstance(message, Mapping) and message.get("role") == "assistant":
        return [_candidate(message.get("provider"), message.get("model"), "", parsed.get("timestamp"))]
    return []


def _nested_timestamp(value: object) -> object:
    if not isinstance(value, Mapping):
        return ""
    return value.get("updated", value.get("created", ""))
