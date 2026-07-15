from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .local_store import atomic_write_json, ensure_dir, read_json_object_result, utc_now
from .paths import OmhPaths


QUALITY_SCHEMA_VERSION = "adapter_quality_observation/v1"
QUALITY_CARD_SCHEMA_VERSION = "adapter_quality_channel_delivery_card/v1"
QUALITY_PREPARATION_SCHEMA_VERSION = "adapter_quality_delivery_preparation/v1"
QUALITY_DELIVERY_SCHEMA_VERSION = "adapter_quality_delivery_observation/v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$")
_SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,240}$")
_SECRET = re.compile(r"(?i)(api[_-]?key|token=|secret=|password=|sk-[a-z0-9])")
_URL = re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|[/?#])")


def build_adapter_quality_observation(
    *,
    observation_id: str,
    subject_id: str,
    surface_kind: str,
    adapter_id: str,
    source_revision: str,
    debug_signals: list[dict[str, object]] | None = None,
    checks: list[dict[str, object]],
    layout_checks: list[dict[str, object]],
    metrics: list[dict[str, object]],
) -> dict[str, object]:
    _identifier(observation_id, "observation_id")
    _identifier(subject_id, "subject_id")
    _choice(surface_kind, "surface_kind", {"web", "desktop", "app"})
    _identifier(adapter_id, "adapter_id")
    _identifier(source_revision, "source_revision")
    signals = debug_signals or []
    _limit(signals, "debug_signals")
    _limit(checks, "checks")
    _limit(layout_checks, "layout_checks")
    _limit(metrics, "metrics")
    normalized_signals = [_signal(item) for item in signals]
    normalized_checks = [_check(item) for item in checks]
    normalized_layout = [_layout(item) for item in layout_checks]
    normalized_metrics = [_metric(item) for item in metrics]
    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "observation_id": observation_id,
        "subject_id": subject_id,
        "surface_kind": surface_kind,
        "adapter_id": adapter_id,
        "observed_at": utc_now(),
        "source_revision": source_revision,
        "debug_signals": normalized_signals,
        "checks": normalized_checks,
        "layout_checks": normalized_layout,
        "metrics": normalized_metrics,
        "evidence_refs": _refs([]),
        "overall_evidence_state": _state(normalized_signals, normalized_checks, normalized_layout, normalized_metrics),
        "does_not_prove": ["omh_executed_surface", "global_quality_pass", "root_cause", "message_delivery"],
    }


def build_adapter_quality_delivery_card(observation: dict[str, object], *, renderer_target: str) -> dict[str, object]:
    _choice(renderer_target, "renderer_target", {"discord", "slack", "telegram"})
    if observation.get("schema_version") != QUALITY_SCHEMA_VERSION:
        raise ValueError("observation schema_version is invalid")
    subject_id = _identifier(str(observation.get("subject_id", "")), "subject_id")
    source_revision = _identifier(str(observation.get("source_revision", "")), "source_revision")
    card = {
        "schema_version": QUALITY_CARD_SCHEMA_VERSION,
        "subject_id": subject_id,
        "renderer_target": renderer_target,
        "safe_display_label": subject_id,
        "quality_observation_id": _identifier(str(observation.get("observation_id", "")), "observation_id"),
        "source_revision": source_revision,
        "quality_summary": {
            "state": str(observation.get("overall_evidence_state", "not_observed")),
            "debug_signal_count": len(_list(observation.get("debug_signals"))),
            "check_count": len(_list(observation.get("checks"))),
            "layout_check_count": len(_list(observation.get("layout_checks"))),
            "metric_count": len(_list(observation.get("metrics"))),
        },
        "status": "prepared_not_observed",
        "claim_boundary": "Adapter-owned delivery is unobserved until a matching delivery record exists.",
        "does_not_prove": ["message_sent", "attachment_uploaded", "platform_delivery"],
    }
    return {**card, "card_fingerprint": _fingerprint(card)}


def write_adapter_quality_observation(paths: OmhPaths, observation: dict[str, object]) -> dict[str, object]:
    if observation.get("schema_version") != QUALITY_SCHEMA_VERSION:
        raise ValueError("observation schema_version is invalid")
    observation_id = _identifier(str(observation.get("observation_id", "")), "observation_id")
    path = _record_path(paths, "observations", observation_id)
    existing, error = read_json_object_result(path)
    if error:
        raise ValueError(f"invalid existing observation: {error}")
    if existing and _canonical(existing) != _canonical(observation):
        raise ValueError("quality observation already exists with different content")
    ensure_dir(path.parent, private=True)
    atomic_write_json(path, observation, private=True)
    return observation


def link_adapter_quality_session(
    paths: OmhPaths,
    *,
    session_id: str,
    subject_id: str,
    surface_kind: str,
    source_revision: str,
    observation_id: str = "",
    renderer_target: str = "",
) -> dict[str, object]:
    _identifier(session_id, "session_id")
    _identifier(subject_id, "subject_id")
    _choice(surface_kind, "surface_kind", {"web", "desktop", "app"})
    _identifier(source_revision, "source_revision")
    if observation_id:
        _identifier(observation_id, "observation_id")
    if renderer_target:
        _choice(renderer_target, "renderer_target", {"discord", "slack", "telegram"})
    record = {"schema_version": "adapter_quality_session_link/v1", "session_id": session_id, "subject_id": subject_id, "surface_kind": surface_kind, "source_revision": source_revision, "selected_quality_observation_id": observation_id, "renderer_target": renderer_target, "status": "prepared_not_observed" if not observation_id else "observed"}
    path = _record_path(paths, "links", session_id)
    ensure_dir(path.parent, private=True)
    atomic_write_json(path, record, private=True)
    return record


def quality_session_control(paths: OmhPaths, session_id: str) -> dict[str, object]:
    record, error = read_json_object_result(_record_path(paths, "links", session_id))
    if error or record is None:
        return {"status": "unlinked", "actions": [{"id": "link_quality_subject", "enabled": True, "owner": "adapter"}]}
    observation_id = str(record.get("selected_quality_observation_id", ""))
    if not observation_id:
        return {"status": "linked_no_observation", "link": record, "actions": [{"id": "request_adapter_quality_observation", "enabled": True, "owner": "adapter"}]}
    observation, observation_error = read_json_object_result(_record_path(paths, "observations", observation_id))
    if observation_error or observation is None or str(observation.get("source_revision", "")) != str(record.get("source_revision", "")):
        return {"status": "stale", "link": record, "actions": [{"id": "request_adapter_quality_observation", "enabled": True, "owner": "adapter"}]}
    return {"status": "quality_observed", "link": record, "quality_summary": {"state": observation.get("overall_evidence_state", "partial_observed")}, "actions": [{"id": "show_quality_evidence", "enabled": True, "owner": "adapter"}, {"id": "prepare_channel_quality_delivery", "enabled": True, "owner": "adapter"}]}


def prepare_adapter_quality_delivery(paths: OmhPaths, *, session_id: str, card: dict[str, object]) -> dict[str, object]:
    _identifier(session_id, "session_id")
    fingerprint = _digest(str(card.get("card_fingerprint", "")), "card_fingerprint")
    preparation_id = f"prep-{fingerprint[:16]}"
    record = {
        "schema_version": QUALITY_PREPARATION_SCHEMA_VERSION,
        "preparation_id": preparation_id,
        "session_id": session_id,
        "subject_id": _identifier(str(card.get("subject_id", "")), "subject_id"),
        "renderer_target": str(card.get("renderer_target", "")),
        "quality_observation_id": _identifier(str(card.get("quality_observation_id", "")), "quality_observation_id"),
        "card_fingerprint": fingerprint,
        "prepared_at": utc_now(),
        "status": "prepared_not_observed",
    }
    path = _record_path(paths, "preparations", preparation_id)
    existing, error = read_json_object_result(path)
    if error:
        raise ValueError(f"invalid existing preparation: {error}")
    if existing and _canonical(existing) != _canonical(record):
        raise ValueError("delivery preparation already exists with different content")
    ensure_dir(path.parent, private=True)
    atomic_write_json(path, record, private=True)
    return record


def record_adapter_quality_delivery(
    paths: OmhPaths,
    *,
    preparation: dict[str, object],
    adapter: str,
    delivery_result: str,
    external_message_ref: str = "",
) -> dict[str, object]:
    if preparation.get("schema_version") != QUALITY_PREPARATION_SCHEMA_VERSION:
        raise ValueError("preparation schema_version is invalid")
    _identifier(adapter, "adapter")
    _choice(delivery_result, "delivery_result", {"delivered", "failed", "blocked"})
    if delivery_result == "delivered" and not external_message_ref:
        raise ValueError("external_message_ref is required for delivered")
    if external_message_ref:
        _identifier(external_message_ref, "external_message_ref")
    preparation_id = _identifier(str(preparation.get("preparation_id", "")), "preparation_id")
    stored, error = read_json_object_result(_record_path(paths, "preparations", preparation_id))
    if error or stored is None or _canonical(stored) != _canonical(preparation):
        raise ValueError("delivery preparation is missing or does not match stored record")
    record = {
        "schema_version": QUALITY_DELIVERY_SCHEMA_VERSION,
        "observation_id": f"delivery-{preparation_id[5:]}",
        "preparation_id": preparation_id,
        "session_id": str(preparation["session_id"]),
        "subject_id": str(preparation["subject_id"]),
        "renderer_target": str(preparation["renderer_target"]),
        "quality_observation_id": str(preparation["quality_observation_id"]),
        "card_fingerprint": str(preparation["card_fingerprint"]),
        "adapter": adapter,
        "delivery_result": delivery_result,
        "external_message_ref": external_message_ref,
        "observed_at": utc_now(),
        "observation_status": "observed",
    }
    path = _record_path(paths, "deliveries", str(record["observation_id"]))
    ensure_dir(path.parent, private=True)
    atomic_write_json(path, record, private=True)
    return record


def _signal(value: dict[str, object]) -> dict[str, object]:
    return {"signal_id": _identifier(str(value.get("signal_id", "")), "signal_id"), "kind": _choice(str(value.get("kind", "")), "signal.kind", {"crash", "error", "warning", "assertion", "network_failure", "other"}), "severity": _choice(str(value.get("severity", "")), "signal.severity", {"info", "warning", "error"}), "status": _choice(str(value.get("status", "")), "signal.status", {"observed", "ignored", "resolved_by_adapter"}), "summary": _safe_text(str(value.get("summary", "")), "signal.summary"), "evidence_refs": _refs(_list(value.get("evidence_refs")))}


def _check(value: dict[str, object]) -> dict[str, object]:
    return {"check_id": _identifier(str(value.get("check_id", "")), "check_id"), "kind": _choice(str(value.get("kind", "")), "check.kind", {"functional", "accuracy", "regression"}), "status": _choice(str(value.get("status", "")), "check.status", {"pass", "fail", "blocked", "not_observed"}), "expected_summary": _safe_text(str(value.get("expected_summary", "")), "expected_summary"), "actual_summary": _safe_text(str(value.get("actual_summary", "")), "actual_summary"), "evidence_refs": _refs(_list(value.get("evidence_refs")))}


def _layout(value: dict[str, object]) -> dict[str, object]:
    return {"check_id": _identifier(str(value.get("check_id", "")), "layout.check_id"), "scope": _safe_text(str(value.get("scope", "")), "layout.scope"), "status": _choice(str(value.get("status", "")), "layout.status", {"pass", "fail", "blocked", "not_observed"}), "summary": _safe_text(str(value.get("summary", "")), "layout.summary"), "evidence_refs": _refs(_list(value.get("evidence_refs")))}


def _metric(value: dict[str, object]) -> dict[str, object]:
    status = _choice(str(value.get("status", "")), "metric.status", {"pass", "fail", "not_observed"})
    number = float(value.get("value", -1))
    threshold = float(value.get("threshold", -1))
    if not 0 <= number <= 1_000_000_000 or not 0 <= threshold <= 1_000_000_000:
        raise ValueError("metric value and threshold must be bounded")
    return {"metric_id": _identifier(str(value.get("metric_id", "")), "metric_id"), "name": _safe_text(str(value.get("name", "")), "metric.name"), "value": number, "unit": _choice(str(value.get("unit", "")), "metric.unit", {"ms", "bytes", "percent", "count"}), "threshold": threshold, "comparison": _choice(str(value.get("comparison", "")), "metric.comparison", {"lte", "gte", "equal"}), "status": status, "evidence_refs": _refs(_list(value.get("evidence_refs")))}


def _state(signals: list[dict[str, object]], checks: list[dict[str, object]], layouts: list[dict[str, object]], metrics: list[dict[str, object]]) -> str:
    statuses = [str(item.get("status", "")) for item in [*checks, *layouts, *metrics]]
    if "fail" in statuses or signals:
        return "observed_with_failures"
    return "observed_no_failures" if statuses else "partial_observed"


def _record_path(paths: OmhPaths, kind: str, record_id: str) -> Path:
    _identifier(record_id, "record_id")
    return paths.omh_home / "adapter-quality" / kind / f"{record_id}.json"


def _fingerprint(value: dict[str, object]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _identifier(value: str, field: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a bounded identifier")
    return value


def _digest(value: str, field: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field} must be sha256")
    return value


def _choice(value: str, field: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise ValueError(f"{field} is invalid")
    return value


def _safe_text(value: str, field: str) -> str:
    if not _SAFE_TEXT.fullmatch(value) or _URL.search(value) or _SECRET.search(value):
        raise ValueError(f"{field} must be safe bounded text")
    return value


def _refs(values: list[object]) -> list[str]:
    return [_identifier(str(value), "evidence_ref") for value in values]


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _limit(values: list[dict[str, object]], field: str) -> None:
    if len(values) > 50:
        raise ValueError(f"{field} must have at most 50 items")
