"""The bounded, redacted receipt of one live prefetch.

Hermes prints "recalled N memories" and nothing else survives the turn: which
records were selected, which of them the renderer actually emitted, which lens
and configuration produced that answer, and for which session. When a user
later asks why an expected memory was not used, that question cannot be
answered from a count. This receipt is the record-bound answer.

It proves exactly one thing: the OMH provider prepared this section and
returned it to the host. It is not evidence that the host put the text into a
model call, nor that a model used it; both stay `None` here on purpose, and a
consumer that needs them must observe them elsewhere. It carries record IDs,
digests, counts, reason codes and identities -- never a summary, a query, a
rendered section or any other content.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .memory_query_sanitizer import SanitizedQuery
from .memory_records import PreparedPrefetch, RECORD_SUMMARY_LIMIT_CHARS
from .memory_session_lens import SURFACE_CLASSES
from .project_identity import DIAGNOSTICS, RESOLVER_VERSION, ProjectIdentityResolution

LEGACY_MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION = "omh_memory_prefetch_receipt/v1"
PRINCIPAL_MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION = "omh_memory_prefetch_receipt/v2"
MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION = "omh_memory_prefetch_receipt/v3"
PREFETCH_RECEIPT_FILENAME = "prefetch_receipt.json"
MAX_PREFETCH_RECEIPT_BYTES = 64 * 1024
RECEIPT_STATES = ("prepared", "returned_to_host")
PROVES = "local_provider_preparation_and_return"
CLAIM_BOUNDARY = (
    "This receipt proves that the OMH memory provider prepared and returned this record section locally. "
    "It is not evidence of host delivery, model use, execution, review, CI, merge, or Hermes internal memory."
)
_HEX64 = frozenset("0123456789abcdef")
_UNSIGNED_KEYS = frozenset({"receipt_id", "state", "served_at"})
# Basenames of unreadable store files the receipt names; the count is never cut.
MAX_UNREADABLE_NAMES = 16
# Records a newer same-subject record replaced, named by id; the count in
# `exclusion_reason_counts` is never cut.
MAX_SUBJECT_SUPERSEDED = 16


def build_prefetch_receipt(
    prepared: PreparedPrefetch,
    *,
    session_id: str,
    home_digests: tuple[str, ...] | list[str],
    rendered_block_count: int = 0,
    project_resolution: ProjectIdentityResolution | None = None,
    reminder: dict[str, object] | None = None,
    unreadable: tuple[str, ...] | list[str] = (),
    store_read_error: bool = False,
    pack_chars: int | None = None,
    surface_class: str | None = None,
    tightened_by_foreign_lens: bool = False,
    query_sanitized: SanitizedQuery | None = None,
) -> dict[str, Any]:
    """Bind one selection and its rendering to configuration, lens, session and store.

    Raises ValueError when the rendering does not describe the selection it
    claims to render: a receipt must never be assembled from mismatched parts.

    ``unreadable`` names the store files the reader skipped (basenames, or a
    directory label when a whole directory could not be listed) and
    ``store_read_error`` says a directory listing failed: without them a
    corrupt record and a missing one produce the same receipt.

    ``reminder`` discloses the one ``omh reminder:`` line the pack carries
    about an open record -- record id and age only, never its summary -- so
    a receipt says the turn was asked a question even though Hermes'
    ``RecallStatus`` has no field to carry it. None when the pack asked
    nothing.
    """
    selection, section = prepared.selection, prepared.section
    pack = selection.pack
    selected_ids = [str(item.get("record_id", "")) for item in pack.get("included_records", []) if isinstance(item, dict)]
    rendered_ids = [str(item.get("record_id", "")) for item in section.rendered]
    indexed_ids = list(section.indexed)
    unindexed_ids = [record_id for record_id in selected_ids if record_id not in indexed_ids]
    if not _indexed_ids_ok(indexed_ids, selected_ids) or rendered_ids != unindexed_ids[: len(rendered_ids)]:
        raise ValueError("incompatible prefetch rendering: rendered records are not the selected prefix excluding indexed records")
    for item in section.rendered:
        digest = str(item.get("content_digest", ""))
        if len(digest) != 64 or set(digest) - _HEX64:
            raise ValueError("incompatible prefetch rendering: content digest is not sha256 hex")
    task_ref: dict[str, Any] = _object(pack.get("task_ref"))
    perspective: dict[str, Any] = _object(pack.get("perspective"))
    configuration = selection.configuration
    render_configuration = {"budget_chars": int(section.budget_chars), "summary_limit_chars": RECORD_SUMMARY_LIMIT_CHARS}
    body: dict[str, Any] = {
        "schema_version": MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION,
        "prepared_at": _stamp(prepared.clock),
        "session_id": str(pack.get("session_id", "") or session_id or ""),
        "store": {
            "home_digests": [str(digest) for digest in home_digests],
            "unreadable_count": len(unreadable),
            "unreadable": [str(name) for name in list(unreadable)[:MAX_UNREADABLE_NAMES]],
            "store_read_error": bool(store_read_error),
        },
        "configuration_id": selection.configuration_id,
        "resolver_version": str(configuration["resolver_version"]),
        "project_identity": str(configuration["project_identity"]),
        "selector_schema_version": str(configuration.get("selector_schema_version", "")),
        "recall_pack_schema_version": str(pack.get("schema_version", "")),
        "render_configuration": render_configuration,
        "render_configuration_id": _digest(render_configuration),
        "lens": {
            "scope_allowlist": [dict(scope) for scope in selection.scope_allowlist],
            "scope_status": selection.scope_status,
            "project_identity_state": project_resolution.state if project_resolution else selection.scope_status,
            "project_identity_diagnostics": list(project_resolution.diagnostics) if project_resolution else [],
            "perspective": {"observer": str(perspective.get("observer", "")), "observed": str(perspective.get("observed", ""))},
            "query_intent": str(pack.get("query_intent", "")),
            "query_digest": str(task_ref.get("sha256", "")),
            "query_supplied": bool(task_ref.get("query_supplied", False)),
        },
        "principal_decision": dict(selection.principal_decision),
        "audience_policy_digest": selection.audience_policy_digest,
        "selection": {
            "clock": _stamp(prepared.clock),
            "recall_enabled": bool(pack.get("enabled", False)),
            "selected_record_ids": selected_ids,
            "selected_count": len(selected_ids),
            "truncated": bool(pack.get("truncated", False)),
            # The pack carries this only when the active-tier fallback served
            # it; the receipt keeps a fixed shape and says null otherwise.
            "query_fallback": dict(pack["query_fallback"]) if isinstance(pack.get("query_fallback"), dict) else None,
            "exclusion_reason_counts": {str(key): int(value) for key, value in sorted(selection.exclusion_reason_counts.items())},
            # Which record stood in for which: a count alone cannot answer
            # "why did the old value not come back?". Ids only.
            "subject_superseded": [
                {"record_id": str(item.get("record_id", "")), "superseded_by": str(item.get("superseded_by", ""))}
                for item in pack.get("excluded_records", [])
                if isinstance(item, dict) and item.get("reason") == "superseded_by_subject"
            ][:MAX_SUBJECT_SUPERSEDED],
        },
        "rendering": {
            "rendered_records": [
                {"record_id": str(item.get("record_id", "")), "content_digest": str(item.get("content_digest", ""))}
                for item in section.rendered
            ],
            "rendered_count": len(section.rendered),
            "indexed_records": indexed_ids,
            "selected_not_rendered": [
                {"record_id": record_id, "reason": "render_budget_exhausted"} for record_id in unindexed_ids[len(rendered_ids) :]
            ],
            "omission_counts": {str(key): int(value) for key, value in section.omissions.items()},
            "rendered_block_count": max(int(rendered_block_count), 0),
            # The length of the whole text the provider returns, every section
            # included; None when the receipt describes a record section alone.
            "pack_chars": max(int(pack_chars), 0) if pack_chars is not None else None,
        },
        "reminder": _reminder_projection(reminder),
        # The class the pack was rendered under, and whether another
        # provider's tighter lens for this session id narrowed it, so a
        # downgrade never passes unseen. None for a record section alone.
        "surface_class": surface_class if surface_class in SURFACE_CLASSES else None,
        "tightened_by_foreign_lens": bool(tightened_by_foreign_lens),
        "write_failures_count": 0,
        "last_write_failure": None,
        "delivery_observed": None,
        "model_use_observed": None,
        "proves": PROVES,
        "redaction_policy": "metadata_only",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if query_sanitized is not None:
        body["lens"].update(
            query_method=query_sanitized.method,
            query_original_length=query_sanitized.original_length,
            query_clean_length=query_sanitized.clean_length,
        )
    return {**body, "receipt_id": _digest(body), "state": "prepared", "served_at": ""}


def mark_prefetch_receipt_returned(
    receipt: dict[str, Any],
    *,
    served_at: datetime | None = None,
    write_failures_count: int = 0,
    last_write_failure: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The prepared receipt, now recording that the section was handed back to the host.

    ``write_failures_count`` and ``last_write_failure`` are the provider's
    swallowed state writes up to this serve: a receipt that reports what the
    provider did must also report what it failed to record. They are known
    only at serve time, so the receipt id is re-derived over them here.
    """
    body = {key: value for key, value in receipt.items() if key not in _UNSIGNED_KEYS}
    body["write_failures_count"] = max(int(write_failures_count), 0)
    body["last_write_failure"] = _write_failure_projection(last_write_failure)
    stamp = _stamp(served_at if served_at is not None else datetime.now(timezone.utc))
    return {**body, "receipt_id": _digest(body), "state": "returned_to_host", "served_at": stamp}


def validate_prefetch_receipt(value: object) -> list[str]:
    """Bounded structural checks; a receipt that fails any of them is not consumed."""
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["receipt must be an object"]
    try:
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_PREFETCH_RECEIPT_BYTES:
            return ["size"]
        body = {key: item for key, item in value.items() if key not in _UNSIGNED_KEYS}
        if value.get("receipt_id") != _digest(body):
            errors.append("receipt_id")
    except (TypeError, ValueError, RecursionError):
        return ["encoding"]
    schema_version = value.get("schema_version")
    if schema_version not in {LEGACY_MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION, PRINCIPAL_MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION, MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION}:
        errors.append("schema_version")
    if schema_version == MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION:
        if value.get("resolver_version") != RESOLVER_VERSION:
            errors.append("resolver_version")
        if not isinstance(value.get("project_identity"), str):
            errors.append("project_identity")
        identity_lens = value.get("lens")
        if not isinstance(identity_lens, dict) or identity_lens.get("project_identity_state") not in ("resolved", "unresolved", "inspection"):
            errors.append("project_identity_state")
        elif not isinstance(identity_lens.get("project_identity_diagnostics"), list) or any(not isinstance(token, str) or token not in DIAGNOSTICS for token in identity_lens["project_identity_diagnostics"]):
            errors.append("project_identity_diagnostics")
    if schema_version in {PRINCIPAL_MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION, MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION}:
        decision = value.get("principal_decision")
        if not isinstance(decision, dict) or decision.get("binding_state") not in {"validated_local", "host_validated", "unbound"}:
            errors.append("principal_decision")
        if not _hex64(value.get("audience_policy_digest")):
            errors.append("audience_policy_digest")
    if value.get("state") not in RECEIPT_STATES:
        errors.append("state")
    for key in ("receipt_id", "configuration_id"):
        if not _hex64(value.get(key)):
            errors.append(key)
    if not isinstance(value.get("session_id"), str):
        errors.append("session_id")
    lens = value.get("lens")
    if not isinstance(lens, dict) or not isinstance(lens.get("scope_allowlist"), list) or not isinstance(lens.get("perspective"), dict):
        errors.append("lens")
    if isinstance(lens, dict) and any(key in lens for key in ("query_method", "query_original_length", "query_clean_length")):
        if (
            not isinstance(lens.get("query_method"), str)
            or lens["query_method"] not in {"passthrough", "framing_only", "question_extraction", "tail_sentence", "tail_truncation", "empty"}
            or not _non_negative_int(lens.get("query_original_length"))
            or not _non_negative_int(lens.get("query_clean_length"))
            or lens["query_clean_length"] > lens["query_original_length"]
        ):
            errors.append("lens.query_sanitized")
    selection = value.get("selection")
    rendering = value.get("rendering")
    if not isinstance(selection, dict) or not isinstance(selection.get("selected_record_ids"), list):
        errors.append("selection")
    elif selection.get("selected_count") != len(selection["selected_record_ids"]):
        errors.append("selection.selected_count")
    elif "subject_superseded" in selection and not _subject_superseded_ok(selection["subject_superseded"]):
        errors.append("selection.subject_superseded")
    if not isinstance(rendering, dict) or not isinstance(rendering.get("rendered_records"), list):
        errors.append("rendering")
    else:
        rendered = rendering["rendered_records"]
        if rendering.get("rendered_count") != len(rendered):
            errors.append("rendering.rendered_count")
        # Absent on a receipt an earlier bundle wrote.
        if rendering.get("pack_chars") is not None and not _non_negative_int(rendering["pack_chars"]):
            errors.append("rendering.pack_chars")
        if not all(isinstance(item, dict) and isinstance(item.get("record_id"), str) and _hex64(item.get("content_digest")) for item in rendered):
            errors.append("rendering.rendered_records")
        if isinstance(selection, dict) and isinstance(selection.get("selected_record_ids"), list):
            rendered_ids = [item.get("record_id") for item in rendered if isinstance(item, dict)]
            indexed = rendering.get("indexed_records", [])
            selected_ids = selection["selected_record_ids"]
            if not _indexed_ids_ok(indexed, selected_ids):
                errors.append("rendering.indexed_records")
                indexed = []
            unindexed_ids = [record_id for record_id in selected_ids if record_id not in indexed]
            if rendered_ids != unindexed_ids[: len(rendered_ids)]:
                errors.append("rendering.selected_prefix")
            if any(isinstance(item, dict) and item.get("record_id") in indexed for item in rendering.get("selected_not_rendered", [])):
                errors.append("rendering.selected_not_rendered")
    if value.get("delivery_observed") is not None or value.get("model_use_observed") is not None:
        errors.append("observation_claims")
    # Absent on a receipt an earlier bundle wrote.
    if value.get("surface_class") is not None and value.get("surface_class") not in SURFACE_CLASSES:
        errors.append("surface_class")
    if "tightened_by_foreign_lens" in value and not isinstance(value["tightened_by_foreign_lens"], bool):
        errors.append("tightened_by_foreign_lens")
    reminder = value.get("reminder")
    if reminder is not None and (
        not isinstance(reminder, dict)
        or set(reminder) != {"record_id", "open_days"}
        or not isinstance(reminder.get("record_id"), str)
        or not reminder["record_id"]
        or not isinstance(reminder.get("open_days"), int)
        or isinstance(reminder.get("open_days"), bool)
        or reminder["open_days"] < 0
    ):
        errors.append("reminder")
    # Absent on a receipt an earlier bundle wrote; when present, closed shapes.
    store = value.get("store")
    if isinstance(store, dict) and "unreadable_count" in store and not _store_unreadable_ok(store):
        errors.append("store.unreadable")
    if "write_failures_count" in value or "last_write_failure" in value:
        count = value.get("write_failures_count")
        last = value.get("last_write_failure")
        if not _non_negative_int(count) or (last is None) != (count == 0) or (
            last is not None and _write_failure_projection(last) != last
        ):
            errors.append("write_failures")
    if value.get("proves") != PROVES:
        errors.append("proves")
    for key in ("summary", "included_records", "query", "rendered_text"):
        if key in value:
            errors.append(f"content:{key}")
    return errors


def prefetch_receipt_path(omh_home: str | Path) -> Path:
    return Path(omh_home).expanduser() / "memory" / PREFETCH_RECEIPT_FILENAME


def read_prefetch_receipt(omh_home: str | Path) -> dict[str, Any] | None:
    """The last receipt the provider persisted, or None when there is no valid one.

    Malformed, foreign-schema or internally inconsistent files read as absent:
    a consumer that needs the receipt must treat absence as unknown, never as
    evidence that nothing was served.
    """
    path = prefetch_receipt_path(omh_home)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as handle:
            encoded = handle.read(MAX_PREFETCH_RECEIPT_BYTES + 1)
        if len(encoded) > MAX_PREFETCH_RECEIPT_BYTES:
            return None
        value = json.loads(encoded)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if validate_prefetch_receipt(value):
        return None
    return value


def _indexed_ids_ok(value: object, selected_ids: list[str]) -> bool:
    """Index ids are a unique, selection-ordered subset; older receipts omit them."""
    return (
        isinstance(value, list)
        and all(isinstance(record_id, str) for record_id in value)
        and len(value) == len(set(value))
        and value == [record_id for record_id in selected_ids if record_id in value]
    )


def _object(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _subject_superseded_ok(value: object) -> bool:
    """A bounded list of {record_id, superseded_by} id pairs; absent on older receipts."""
    return (
        isinstance(value, list)
        and len(value) <= MAX_SUBJECT_SUPERSEDED
        and all(
            isinstance(item, dict)
            and set(item) == {"record_id", "superseded_by"}
            and all(isinstance(item[key], str) and item[key] for key in item)
            for item in value
        )
    )


def _reminder_projection(reminder: dict[str, object] | None) -> dict[str, object] | None:
    """Record id and age only: the receipt never carries a summary."""
    if not isinstance(reminder, dict) or not str(reminder.get("record_id", "") or ""):
        return None
    days = reminder.get("open_days", 0)
    return {
        "record_id": str(reminder["record_id"]),
        "open_days": days if isinstance(days, int) and not isinstance(days, bool) and days >= 0 else 0,
    }


def _write_failure_projection(failure: object) -> dict[str, str] | None:
    """Op and error class only: never the file path or the exception message."""
    if not isinstance(failure, dict):
        return None
    op, error = failure.get("op"), failure.get("error")
    if not isinstance(op, str) or not op or not isinstance(error, str) or not error:
        return None
    return {"op": op, "error": error}


def _store_unreadable_ok(store: dict[str, Any]) -> bool:
    count, names = store.get("unreadable_count"), store.get("unreadable")
    return (
        _non_negative_int(count)
        and isinstance(names, list)
        and all(isinstance(name, str) and name for name in names)
        and len(names) == min(count, MAX_UNREADABLE_NAMES)
        and isinstance(store.get("store_read_error"), bool)
    )


def _non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and not (set(value) - _HEX64)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _stamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "CLAIM_BOUNDARY",
    "LEGACY_MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION",
    "MEMORY_PREFETCH_RECEIPT_SCHEMA_VERSION",
    "PREFETCH_RECEIPT_FILENAME",
    "PROVES",
    "RECEIPT_STATES",
    "build_prefetch_receipt",
    "mark_prefetch_receipt_returned",
    "prefetch_receipt_path",
    "read_prefetch_receipt",
    "validate_prefetch_receipt",
]
