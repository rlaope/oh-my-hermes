from __future__ import annotations

from json import JSONDecodeError
from pathlib import Path
from typing import Any, Final

from ..local_store import atomic_write_json, read_json_object, utc_now
from ..paths import OmhPaths
from .self_improvement_route_records import (
    PENDING_STORE_ROUTE_STATUS,
    REVIEW_DECISIONS,
    SELF_IMPROVEMENT_STORE_ROUTE_RECORD_SCHEMA_VERSION,
    STORE_ROUTE_REF_PREFIX,
    build_self_improvement_store_route_record,
    reviewed_self_improvement_store_route_record,
    safe_self_improvement_store_route_id,
    self_improvement_store_route_ref,
    store_route_current_destination,
    validate_self_improvement_store_route_record,
)
from .workflow_learning_errors import WorkflowLearningError


SELF_IMPROVEMENT_STORE_ROUTE_LIST_SCHEMA_VERSION: Final = "self_improvement_store_route_list/v1"


def self_improvement_store_route_path(paths: OmhPaths, route_id: str) -> Path:
    return paths.learning_store_routes_dir / f"{safe_self_improvement_store_route_id(route_id)}.json"


def write_self_improvement_store_route(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    validate_self_improvement_store_route_record(record)
    atomic_write_json(self_improvement_store_route_path(paths, str(record["route_id"])), record, private=True)
    return record


def show_self_improvement_store_route(paths: OmhPaths, route_id: str) -> dict[str, Any]:
    record = read_json_object(self_improvement_store_route_path(paths, route_id))
    if record is None:
        raise WorkflowLearningError(f"store route not found: {route_id}")
    validate_self_improvement_store_route_record(record)
    return record


def review_self_improvement_store_route(
    paths: OmhPaths,
    route_id: str,
    *,
    decision: str,
    destination: str = "",
    reviewer_ref: str = "operator",
    review_note: str = "",
) -> dict[str, Any]:
    reviewed = reviewed_self_improvement_store_route_record(
        show_self_improvement_store_route(paths, route_id),
        decision=decision,
        destination=destination,
        reviewer_ref=reviewer_ref,
        review_note=review_note,
    )
    return write_self_improvement_store_route(paths, reviewed)


def list_self_improvement_store_routes(
    paths: OmhPaths,
    *,
    limit: int | None = 20,
    include_resolved: bool = False,
) -> dict[str, Any]:
    records, invalid_records = _read_store_route_records(paths)
    pending_count = sum(1 for record in records if record.get("status") == PENDING_STORE_ROUTE_STATUS)
    filtered = records if include_resolved else [record for record in records if record.get("status") == PENDING_STORE_ROUTE_STATUS]
    limited = filtered if limit is None else filtered[: max(limit, 0)]
    return {
        "schema_version": SELF_IMPROVEMENT_STORE_ROUTE_LIST_SCHEMA_VERSION,
        "status": _list_status(pending_count=pending_count, invalid_count=len(invalid_records), returned_count=len(limited)),
        "generated_at": utc_now(),
        "scope": {
            "limit": "all" if limit is None else limit,
            "include_resolved": include_resolved,
            "store_routes_dir": str(paths.learning_store_routes_dir),
        },
        "summary": {
            "total_store_routes": len(records),
            "pending_store_routes": pending_count,
            "returned_items": len(limited),
            "invalid_records": len(invalid_records),
        },
        "store_routes": limited,
        "invalid_records": invalid_records,
        "wrapper_actions": [
            "route_self_improvement_signal",
            "review_self_improvement_store_route",
            "show_learning_review_queue",
            "show_status",
        ],
        "claim_boundary": (
            "Store route lists read local metadata-only review records. They do not write destination artifacts "
            "or prove future workflow behavior changed."
        ),
    }


def store_route_review_queue_entries(paths: OmhPaths) -> list[dict[str, Any]]:
    records, invalid_records = _read_store_route_records(paths)
    entries = [_invalid_store_route_entry(item) for item in invalid_records]
    for record in records:
        if record.get("status") == PENDING_STORE_ROUTE_STATUS:
            entries.append(_pending_store_route_entry(record))
    return entries


def _pending_store_route_entry(record: dict[str, Any]) -> dict[str, Any]:
    review = _object(record.get("destination_review"))
    route_id = str(record.get("route_id", ""))
    destination = store_route_current_destination(record)
    return {
        "entry_id": f"store-route:{route_id}",
        "kind": "self_improvement_store_route",
        "status": "needs_store_route_review",
        "severity": "review",
        "priority": 2,
        "title": str(record.get("title", "Review self-improvement store route")),
        "detail": (
            f"Prepared route to {destination} for {review.get('target_workflow', '')}; "
            "approve, change, or discard before any durable destination write."
        ),
        "primary_action": "review_self_improvement_store_route",
        "next_command": f"omh learning review-route {route_id} --decision approve_destination",
        "refs": [self_improvement_store_route_ref(route_id)],
        "created_at": str(record.get("created_at", "")),
        "route_id": route_id,
        "destination": destination,
    }


def _invalid_store_route_entry(item: dict[str, str]) -> dict[str, Any]:
    return {
        "entry_id": f"invalid-store-route:{item.get('path', '')}",
        "kind": "invalid_record",
        "status": "blocked",
        "severity": "blocking",
        "priority": 0,
        "title": "Repair invalid store route record",
        "detail": item.get("error", ""),
        "primary_action": "check_learning_index",
        "next_command": "omh learning store-routes --include-resolved",
        "refs": [item.get("path", "")],
        "created_at": f"invalid:{item.get('path', '')}",
    }


def _read_store_route_records(paths: OmhPaths) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not paths.learning_store_routes_dir.exists():
        return [], []
    records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, str]] = []
    for path in sorted(paths.learning_store_routes_dir.glob("*.json")):
        try:
            record = read_json_object(path)
            if record is None:
                continue
            validate_self_improvement_store_route_record(record)
            records.append(record)
        except (OSError, JSONDecodeError, ValueError, WorkflowLearningError) as exc:
            invalid_records.append({"path": str(path), "error": str(exc)})
    return sorted(records, key=lambda item: (str(item.get("created_at", "")), str(item.get("route_id", "")))), invalid_records


def _list_status(*, pending_count: int, invalid_count: int, returned_count: int) -> str:
    if invalid_count:
        return "blocked"
    if pending_count:
        return "needs_review"
    if returned_count:
        return "ready"
    return "empty"


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowLearningError("store route object is invalid")
    return value


__all__ = [
    "PENDING_STORE_ROUTE_STATUS",
    "REVIEW_DECISIONS",
    "SELF_IMPROVEMENT_STORE_ROUTE_LIST_SCHEMA_VERSION",
    "SELF_IMPROVEMENT_STORE_ROUTE_RECORD_SCHEMA_VERSION",
    "STORE_ROUTE_REF_PREFIX",
    "build_self_improvement_store_route_record",
    "list_self_improvement_store_routes",
    "review_self_improvement_store_route",
    "self_improvement_store_route_path",
    "self_improvement_store_route_ref",
    "show_self_improvement_store_route",
    "store_route_review_queue_entries",
    "validate_self_improvement_store_route_record",
    "write_self_improvement_store_route",
]
